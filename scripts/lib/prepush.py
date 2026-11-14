"""The pre-push check (TX01, T9): in seconds, on the local diff, what used to reach only the full gate.

`scripts/prepush [--base REF] [--hook] [--no-tests] [--no-overlap]`; .githooks/pre-push runs it with --hook after
`commit-check --local`. Every value is a registry entry (config/registry/prepush.json). Three parts, one line each with
its time:
  inventory  the gate's structure checks of the whole checkout, each finding with its fix: the unit manifests
             (unit_check; a file of two units gets a computed hint naming the manifest that lists it by name and the
             glob of the other unit that already owns it), the literal census against the base (literal_census, LT1),
             the covers map of the script tests (gate_script_tests), generated drift (generate --check) and the
             event names test that prepush.event_names_test names;
  tests      the script tests that own the changed files (gate_script_tests.select), with every variable of
             prepush.scrub_prefixes dropped and the hermetic harness on PYTHONPATH, prepush.test_workers at a time
             within prepush.tests_budget_s; the rest is deferred to the gate, and a selection of the whole suite (a
             selector change, an uncovered path) runs none;
  overlap    a warning for each changed file another open PR changes too: one REST list of the open PRs, then a local
             diff of each head against the base, the missing heads fetched in one quiet fetch. Offline, without a
             credential, rate-limited or on any error it is skipped with the reason; it never fails a push.
The changed files are merge-base(base, HEAD)..HEAD, the uncommitted tracked changes and the untracked files that are
not ignored. The base defaults to <push-guard.remote>/<train.base_branch>. Exit 1 on an inventory finding or, without
--hook, a failed test; 0 otherwise (--hook prints a failed test as a WARN line); 2 on a usage error. A checkout without
config/registry (the fixture repository of another tool's test) is not judged.
"""
import os

os.environ.setdefault('OU_CONFIG_STORE', 'file')  # the checkout's registry and local log; a cold shared-store read costs seconds

import argparse  # noqa: E402
from collections import namedtuple  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from datetime import timedelta  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
import re  # noqa: E402
import signal  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import config  # noqa: E402
import event_contracts  # noqa: E402
import gate_areas  # noqa: E402
import gate_script_tests  # noqa: E402
import generate  # noqa: E402
import forge_events  # noqa: E402
import literal_census  # noqa: E402
import unit_check  # noqa: E402
import units  # noqa: E402

CHECKOUT = HERE.parent.parent
OWNERS = re.compile(r'(?P<path>\S+) belongs to \d+ units \((?P<units>[^)]+)\)')
STATUS = re.compile(r'(?P<code>..) (?P<path>.+)', re.S)
SHA = re.compile(r'[0-9a-f]+')
EVENT = re.compile(r"'([a-z][a-z-]*(?:\.[a-z][a-z-]*)+)'")
Ran = namedtuple('Ran', 'status seconds tail')


class Skip(Exception):
    """A part that cannot run here; its reason is printed and it is never a finding."""


def say(line):
    print(line, flush=True)


def ms(seconds):
    return timedelta(seconds=seconds) // timedelta(milliseconds=1)


def git(root, *args, timeout=None, feed=None, env=None):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=timeout, input=feed,
                          stdin=None if feed is not None else subprocess.DEVNULL, env=env)


def toplevel(cwd=None):
    """The checkout the current directory is in, else the one this module lives in."""
    done = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=cwd, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)
    found = done.stdout.strip() if done.returncode == 0 else ''
    return Path(found).resolve() if found else CHECKOUT


def default_base(root):
    return f"{config.get('push-guard.remote', root)}/{config.get('train.base_branch', root)}"


def changed(root, base):
    """(sorted paths, merge base or None): merge-base(base, HEAD)..HEAD with deletions, the uncommitted tracked changes
    and the untracked files that are not ignored; a rename counts both names."""
    names, fork = set(), None
    if base:
        found = git(root, 'merge-base', base, 'HEAD')
        fork = found.stdout.strip() if found.returncode == 0 else None
    if fork:
        names.update(git(root, 'diff', '--name-only', '--no-renames', '-z', fork, 'HEAD').stdout.split('\0'))
    fields = iter(git(root, 'status', '--porcelain', '-z', '--untracked-files=all').stdout.split('\0'))
    for field in fields:
        match = STATUS.fullmatch(field)
        if not match:
            continue
        names.add(match['path'])
        if match['code'][0] in 'RC':  # porcelain -z: the source of a rename or copy is the next field
            names.add(next(fields, ''))
    names.discard('')
    return sorted(names), fork


# Inventory: each check returns [(finding, [fix lines])]; a check that cannot run raises Skip.


def owner_fixes(root, error):
    """The fix of `<path> belongs to N units (a, b)`: the manifest that lists the path by name drops it, since the glob
    of the other unit already owns it; two globs: narrow one; two names: keep one."""
    match = OWNERS.match(error)
    if not match:
        return []
    path, found = match['path'], [unit.strip() for unit in match['units'].split(',')]
    folder, name = units.setting('manifest_dir', root), units.setting('manifest_file', root)
    where = {unit: f'{folder}/{unit}/{name}' for unit in found}
    named, globbed = [], {}
    for unit in found:
        try:
            paths = json.loads((Path(root) / where[unit]).read_text(encoding='utf-8')).get('paths') or []
        except (OSError, ValueError):
            continue
        if path in paths:
            named.append(unit)
        globs = [glob for glob in paths if glob != path and gate_areas.glob_match(path, glob)]
        if globs:
            globbed[unit] = globs[0]
    fixes = []
    if globbed:
        owner = sorted(globbed)[0]
        fixes += [f'fix: remove "{path}" from {where[unit]} paths ({owner} owns it by "{globbed[owner]}")'
                  for unit in named if unit not in globbed]
        if len(globbed) > 1:
            choices = ', '.join(f'"{globbed[unit]}" in {where[unit]}' for unit in sorted(globbed))
            fixes.append(f'fix: narrow one of {choices} so that one unit owns "{path}"')
    elif len(named) > 1:
        listed = ', '.join(where[unit] for unit in named)
        fixes.append(f'fix: keep "{path}" in the paths of one of {listed} and remove it from the others')
    return fixes


def check_units(root, base):
    units.reset()
    errors, _ = unit_check.check(root)
    return [(error, owner_fixes(root, error)) for error in errors]


def check_literals(root, base):
    # The local check and structure check already use the operator's D-260 regime. Repeating the census here must
    # preserve that same decision, rather than turning its warnings back into refusals.
    import commit_check
    return [(error, []) for error in commit_check.lift(literal_census.check(root, base)[0], 'literals')]


def check_covers(root, base):
    return [(error, []) for error in gate_script_tests.check(root)]


def check_generated(root, base):
    return [(problem, []) for problem in generate.drift(root)]


def check_events(root, base):
    """The event names test, run in process: for each event on one side only, the side to fix."""
    path, _, name = config.get('prepush.event_names_test', root).partition('::')
    case, _, method = name.partition('.')
    file = Path(root) / path
    if not file.is_file():
        raise Skip(f'{path} is not in this checkout')
    spec = importlib.util.spec_from_file_location(f'prepush_{file.stem}', file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    test = getattr(module, case)(method)
    test.maxDiff = None  # the whole difference, so that every name is reported
    result = unittest.TestResult()
    test.run(result)
    if result.errors:
        raise RuntimeError(f'{path}::{name}: {result.errors[0][1].strip().splitlines()[-1]}')
    if not result.failures:
        return []
    message = result.failures[0][1].split('AssertionError', 1)[-1]
    contracts, known = config.get('forge-events.contracts_dir', root), set(event_contracts.catalog())
    found = []
    for event in sorted(set(EVENT.findall(message))):
        if event in known:
            found.append((f'event {event}: a schema in {contracts} and no row in the ## Events table of '
                          f'docs/process/EVENTS.md ({path}::{name})', [f'fix: add the row of {event} to that table']))
        else:
            found.append((f'event {event}: a row in the ## Events table of docs/process/EVENTS.md and no schema in '
                          f'{contracts} ({path}::{name})',
                          [f'fix: add {contracts}/{event}.v1.json and lock it (python3 scripts/lib/event_contracts.py '
                           f'lock), or drop the row']))
    return found or [(f'{path}::{name}: {message.strip().splitlines()[0]}', [])]


CHECKS = (('units', check_units), ('literals', check_literals), ('covers', check_covers),
          ('generated', check_generated), ('events', check_events))


def inventory(root, base, out, clock, checks=None, verified=()):
    """(findings, warnings): every check's line, then its findings and their fixes. A check named in `verified` was
    run by the local stage of the same push (.githooks/pre-push, scripts/lib/local_checks.py) and passed there: it is
    not run again (D-194)."""
    findings = warnings = 0
    for name, check in (CHECKS if checks is None else checks):
        if name in verified:
            out(f'{name}: skipped (the local stage of this push ran it and it passed), 0 ms')
            continue
        began = clock()
        prefix, found = '', []
        try:
            found = check(root, base)
            status = f'{len(found)} finding(s)' if found else 'ok'
        except Skip as skip:
            status = f'skipped ({skip})'
        except Exception as error:  # a broken check is a warning, never a finding
            prefix, status = 'WARN ', f'could not run ({type(error).__name__}: {error})'
            warnings += 1
        out(f'{prefix}{name}: {status}, {ms(clock() - began)} ms')
        for line, fixes in found:
            out('FAIL ' + line)
            for fix in fixes:
                out('  ' + fix)
        findings += len(found)
    return findings, warnings


# Tests: the owning script tests within the budget.


def select_tests(root, files):
    """(chosen, deferred whole suite, reason): gate_script_tests.select of the changed files; a selection of the whole
    suite is deferred to the gate whole."""
    if not files:
        return [], [], 'no changed files'
    mapping = gate_script_tests.load(root)
    chosen, reason = gate_script_tests.select(files, mapping)
    suite = list(mapping['scripts'])
    if suite and set(suite) <= set(chosen):
        return [], suite, reason
    return list(chosen), [], reason


def test_env(environ, root):
    """The environment of a script test: without the variables of prepush.scrub_prefixes (a hook's leaked
    GIT_INDEX_FILE, the gate's OU_GATE_*), with the hermetic harness first on PYTHONPATH as in the gate."""
    prefixes = tuple(config.get('prepush.scrub_prefixes', root))
    env = {key: value for key, value in environ.items() if not key.startswith(prefixes)}
    harness = HERE / 'hermetic'
    if harness.is_dir():
        rest = [part for part in env.get('PYTHONPATH', '').split(os.pathsep) if part and part != str(harness)]
        env['PYTHONPATH'] = os.pathsep.join([str(harness), *rest])
    return env


def stop(child, grace_s):
    """SIGTERM to the test's process group (its EXIT traps run), then SIGKILL to what is left of it."""
    for sent in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(child.pid, sent)
        except (ProcessLookupError, PermissionError):
            break
        try:
            child.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            continue
    child.wait()


def run_tests(root, scripts, clock=time.monotonic, environ=None):
    """{script: Ran(status, seconds, tail)}; status passed, failed, deferred (not started within the budget) or stopped
    (still running when the budget ended)."""
    budget, workers = config.get('prepush.tests_budget_s', root), config.get('prepush.test_workers', root)
    grace, keep = config.get('prepush.stop_grace_s', root), config.get('gate.script_tests_log_lines', root)
    env = test_env(os.environ if environ is None else environ, root)
    deadline = clock() + budget
    running, guard = set(), threading.Lock()

    def one(script):
        left = deadline - clock()
        if left <= 0:
            return script, Ran('deferred', 0, [])
        with tempfile.TemporaryFile() as log:
            began = clock()
            try:
                child = subprocess.Popen(['bash', script], cwd=str(root), env=env, stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            except OSError as error:
                return script, Ran('failed', clock() - began, [f'cannot start bash {script}: {error}'])
            with guard:
                running.add(child)
            try:
                child.wait(timeout=left)
            except subprocess.TimeoutExpired:
                stop(child, grace)
                return script, Ran('stopped', clock() - began, [])
            finally:
                with guard:
                    running.discard(child)
            log.seek(0)
            text = log.read().decode('utf-8', 'replace')
        if child.returncode == 0:
            return script, Ran('passed', clock() - began, [])
        return script, Ran('failed', clock() - began, text.splitlines()[-keep:])

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        return dict(pool.map(one, scripts))
    finally:
        with guard:
            left_over = list(running)
        for child in left_over:  # an interrupted run leaves no test behind
            stop(child, grace)
        pool.shutdown(wait=True)


def state_path(root):
    done = git(root, 'rev-parse', '--git-path', config.get('prepush.state_file', root))
    found = done.stdout.strip() if done.returncode == 0 else ''
    if not found:
        return None
    return Path(found) if Path(found).is_absolute() else Path(root) / found


def load_state(path):
    try:
        data = json.loads(path.read_text(encoding='utf-8')) if path else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path, state):
    if path:
        try:
            path.write_text(json.dumps(state, indent='  ', sort_keys=True) + '\n', encoding='utf-8')
        except OSError:
            pass


def tests_part(root, files, hook, out, clock, environ=None):
    """(run, deferred, failed, warnings) of the owning script tests, printed."""
    began = clock()
    try:
        chosen, whole, reason = select_tests(root, files)
    except Exception as error:  # a broken covers map is the covers check's finding
        out(f'tests: skipped (no selection: {error}), {ms(clock() - began)} ms')
        return 0, 0, 0, 0
    if whole:
        out(f'tests: none run, {len(whole)} deferred, {ms(clock() - began)} ms')
        out(f'{reason}; full script suite deferred to the gate')
        return 0, len(whole), 0, 0
    if not chosen:
        out(f'tests: none ({reason}), {ms(clock() - began)} ms')
        return 0, 0, 0, 0
    if config.get('prepush.tests_budget_s', root) == 0:  # the gate runs them on the exact head before any merge
        out(f'tests: {len(chosen)} deferred to the gate (prepush.tests_budget_s is 0), {ms(clock() - began)} ms')
        return 0, len(chosen), 0, 0
    path = state_path(root)
    state = load_state(path)
    slow = [script for script in chosen if isinstance(state.get(script), dict) and state[script].get('finished') is False]
    todo = [script for script in chosen if script not in slow]
    try:
        results = run_tests(root, todo, clock, environ) if todo else {}
    except Exception as error:  # the runner itself broke: a warning, never a finding
        out(f'WARN tests: could not run ({type(error).__name__}: {error}), {ms(clock() - began)} ms')
        return 0, 0, 0, 1
    for script, ran in results.items():
        if ran.status != 'deferred':
            state[script] = {'seconds': round(ran.seconds, 1), 'finished': ran.status != 'stopped'}
    save_state(path, state)
    by = {status: [script for script in todo if results[script].status == status]
          for status in ('passed', 'failed', 'stopped', 'deferred')}
    ran, failed = len(by['passed']) + len(by['failed']), len(by['failed'])
    deferred = len(slow) + len(by['stopped']) + len(by['deferred'])
    out(f'tests: {ran} run, {failed} failed, {deferred} deferred to the gate ({reason}), {ms(clock() - began)} ms')
    for script in by['passed']:
        out(f'PASS {script} ({ms(results[script].seconds)} ms)')
    for script in by['failed']:
        out(f'{"WARN test failed:" if hook else "FAIL"} {script} ({ms(results[script].seconds)} ms)')
        for line in results[script].tail:
            out('  ' + line)
    for script in by['stopped']:
        out(f'deferred to the gate: {script} (still running at prepush.tests_budget_s, stopped)')
    for script in by['deferred']:
        out(f'deferred to the gate: {script} (not started within prepush.tests_budget_s)')
    for script in slow:
        out(f'deferred to the gate: {script} (stopped at prepush.tests_budget_s last time; delete {path} to try it '
            f'again)')
    return ran, deferred, failed, failed if hook else 0


# Overlap: the changed files another open PR changes too.


def within(call, seconds):
    """call() in a daemon thread; TimeoutError when it has not answered within `seconds`."""
    box = {}

    def target():
        try:
            box['value'] = call()
        except BaseException as error:  # noqa: BLE001 - handed to the caller
            box['error'] = error

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(seconds)
    if worker.is_alive():
        raise TimeoutError(f'no answer within prepush.rest_timeout_s ({seconds} s)')
    if 'error' in box:
        raise box['error']
    return box['value']


def open_pulls(root, rest=None):
    """The open PRs as {number, head: {ref, sha}}: one paged list through the forge port (forge_events.ForgeEvents
    .open_pulls, D-069 item 7), bounded by prepush.rest_timeout_s; `rest(path)` replaces the port in a test."""
    repo, size = config.get('forge-events.repo', root), config.get('prepush.open_prs_page_size', root)
    timeout = config.get('prepush.rest_timeout_s', root)
    if rest is not None:
        pulls = within(lambda: rest(f'/repos/{repo}/pulls?state=open&per_page={size}'), timeout)
    else:
        port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.SystemClock(), 'prepush',
                                        'prepush')
        pulls = [{'number': pull['number'], 'head': {'ref': pull['head_ref'], 'sha': pull['head_sha']}}
                 for pull in within(lambda: port.open_pulls(repo), timeout)]
    if not isinstance(pulls, list):
        raise RuntimeError('the open PR list is not a list')
    return pulls


def present(root, shas):
    """The shas that name a commit in this checkout (one git cat-file --batch-check)."""
    if not shas:
        return set()
    done = git(root, 'cat-file', '--batch-check', feed=''.join(f'{sha}^{{commit}}\n' for sha in shas))
    if done.returncode != 0:
        return set()
    return {sha for sha, line in zip(shas, done.stdout.splitlines()) if line.split()[1:] and line.split()[1] == 'commit'}


def fetch(root, shas):
    """One quiet fetch of the missing heads; a failure or a timeout leaves the heads already present."""
    try:
        git(root, 'fetch', '--quiet', '--no-tags', '--no-write-fetch-head', config.get('push-guard.remote', root),
            *shas, timeout=config.get('prepush.fetch_timeout_s', root), env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'})
    except (subprocess.TimeoutExpired, OSError):
        pass


def overlap(root, base, files, rest=None):
    """`WARN overlap:` lines, sorted, for the changed files an open PR of another branch changes too."""
    branch = git(root, 'branch', '--show-current').stdout.strip()
    heads = []
    for pull in open_pulls(root, rest):
        head = pull.get('head') if isinstance(pull, dict) else None
        ref, sha = (head.get('ref'), head.get('sha')) if isinstance(head, dict) else (None, None)
        number = pull.get('number') if isinstance(pull, dict) else None
        if isinstance(ref, str) and ref != branch and isinstance(sha, str) and SHA.fullmatch(sha) \
                and isinstance(number, int):
            heads.append((number, ref, sha))
    shas = sorted({sha for _, _, sha in heads})
    have = present(root, shas)
    if set(shas) - have:
        fetch(root, sorted(set(shas) - have))
        have = present(root, shas)
    mine, lines = set(files), []
    for number, ref, sha in sorted(heads):
        if sha not in have:
            continue
        done = git(root, 'diff', '--name-only', '--no-renames', '-z', f'{base}...{sha}')
        if done.returncode != 0:
            continue
        lines += [f'WARN overlap: {path} is also changed by open PR #{number} ({ref})'
                  for path in sorted(mine & set(done.stdout.split('\0')))]
    return sorted(lines)


def overlap_part(root, base, files, out, clock, rest=None):
    """Warnings of the overlap check, printed; any failure skips it with its reason."""
    began = clock()
    try:
        if not files:
            raise Skip('no changed files')
        if not base:
            raise Skip('no base to diff the open PRs against')
        lines = overlap(root, base, files, rest)
    except forge_events.ForgeCompatibilityError:
        raise
    except Exception as error:  # offline, no credential, a rate limit, a broken answer: never a reason to fail
        out(f'overlap: skipped ({str(error) or type(error).__name__}), {ms(clock() - began)} ms')
        return 0
    out(f'overlap: {len(lines)} warning(s), {ms(clock() - began)} ms')
    for line in lines:
        out(line)
    return len(lines)


def run(root, base=None, hook=False, tests=True, overlaps=True, out=say, clock=time.monotonic, rest=None, environ=None,
        checks=None, verified=()):
    """The whole check on one checkout; returns the exit code."""
    began, root = clock(), Path(root)
    if not (root / 'config' / 'registry').is_dir():
        out(f'prepush: skipped ({root} has no config/registry: not a checkout of this repository)')
        return 0
    base = base or default_base(root)
    known = git(root, 'rev-parse', '--verify', '--quiet', f'{base}^{{commit}}').returncode == 0
    files, fork = changed(root, base if known else None)
    warnings = 0
    if fork:
        out(f'prepush{" --hook" if hook else ""}: {len(files)} changed file(s) since the merge base with {base}')
    elif known:
        out(f'WARN prepush: {base} shares no history with HEAD; the changed files are the uncommitted ones')
        warnings += 1
    else:
        out(f'WARN prepush: {base} is not in this checkout; the changed files are the uncommitted ones, and the '
            f'census and the overlap have no base')
        warnings += 1
    findings, more = inventory(root, base if known else None, out, clock, checks, verified)
    warnings += more
    ran = deferred = failed = 0
    if not tests:
        out('tests: skipped (--no-tests), 0 ms')
    elif findings and hook:
        out('tests: skipped (the finding(s) above refuse the push; the next push runs them), 0 ms')
    else:
        ran, deferred, failed, more = tests_part(root, files, hook, out, clock, environ)
        warnings += more
    if overlaps:
        warnings += overlap_part(root, base if known else None, files, out, clock, rest)
    else:
        out('overlap: skipped (--no-overlap), 0 ms')
    total = clock() - began
    out(f'prepush: {findings} finding(s), {ran} test(s) run, {deferred} deferred, {warnings} warning(s), {total:.1f} s')
    if findings and hook:
        out('prepush: the push is refused; fix the finding(s) above, then push again (scripts/prepush reruns this check)')
    return 1 if findings or (failed and not hook) else 0


def main(argv=None, cwd=None, out=say):
    parser = argparse.ArgumentParser(prog='scripts/prepush', description=__doc__.splitlines()[0])
    parser.add_argument('--base', help='the ref the diff and the census are measured against '
                                       '(default: <push-guard.remote>/<train.base_branch>)')
    parser.add_argument('--hook', action='store_true',
                        help='the pre-push hook: an inventory finding refuses the push, a failed test only warns')
    parser.add_argument('--no-tests', action='store_true', help='do not run the owning script tests')
    parser.add_argument('--no-overlap', action='store_true', help='do not compare with the open PRs')
    parser.add_argument('--verified', default='', help='comma-separated inventory checks the local stage of this push '
                                                       'already ran and passed (units, literals): not run again')
    args = parser.parse_args(argv)
    if args.base is not None and (not args.base or args.base.startswith('-')):
        parser.error('--base needs a ref')
    root = toplevel(cwd)
    verified = tuple(name for name in args.verified.split(',') if name)
    return run(root, args.base, hook=args.hook, tests=not args.no_tests, overlaps=not args.no_overlap, out=out,
               verified=verified)


if __name__ == '__main__':
    sys.exit(main())
