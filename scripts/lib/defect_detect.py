"""Detect a base defect in the gate (KD1, D-069 items 4, 8 and 9): a failing test is the PR's own until it fails on the base too.

For every failing test of a gate run the test is re-run on the recorded base (GX-13: the base the proof is bound to,
defects.base_env as gate-local exports it, fetched when its objects are missing), in a throwaway worktree that is
deleted afterwards (no install: the engine has no package, vazão F16), and the outcome is kept per (base sha, test id)
through the storage port at defects.cache_dir, so a hundred PRs gated on the same base re-run it once (GS1's per-test cache is the model).

  fails on the base with the SAME normalized signature  -> a base defect: listed in the verdict as known, not blocking
  listed by the base.red tier 3 published for exactly that base sha, with the same signature (GX-32, a stage
  in defects.stages, no re-run)                           -> a base defect, too
  anything else (passes on the base, another signature, a stage outside defects.stages, an unresolvable base, a
  timeout, a worktree that cannot be made, a test whose own file or declared covers the PR changed (GX-13))
                                                          -> the PR's own failure: it blocks

Nothing is loosened: every test still runs on the PR, and a failure we cannot prove is on the base stays the PR's.
The signature is gate_failures' own (script_failures), so the gate and the registry compare like with like.

  adjudicate(...)     {'known': [...], 'own': [...]} for the failing tests of a run
  base_signal(base)   GX-32: {(test, stage): signature} the open base.red lists for that exact base sha, or None
  verification(...)   resolved defects whose test now passes on the base are verified (the gate closes them), and
                      open ones that no longer reproduce are resolved (GX-13)
  apply_to_report()   gate_report's hook: a failed stage whose failing tests are all known is reported PASS
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

import config
import defect_adapters
import defects
import failure_signatures  # D-322: the signature is layer 0, the one gate_failures re-exports
import forge_events
import globs
import script_covers  # D-322: the covers map's layer-0 reader, not the gate's selection
from adapters import storage

ROOT = Path(__file__).resolve().parents[2]
PASS, FAIL, ERROR = 'pass', 'fail', 'error'


def setting(name):
    return config.get(f'defects.{name}')


def cache_location():
    return Path(os.environ.get('DEFECTS_CACHE_DIR') or os.path.expanduser(setting('cache_dir')))


def resolve_base(root=ROOT, ref=None):
    """The sha of the integration base, or None when it cannot be resolved (then nothing is excused)."""
    done = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', '--quiet', f'{ref or config.get("gate.batch_base_ref")}^{{commit}}'],
                          capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def present(root, sha):
    return subprocess.run(['git', '-C', str(root), 'cat-file', '-e', f'{sha}^{{commit}}'], capture_output=True).returncode == 0


def fetch(root, sha):
    """Fetch one base sha from defects.fetch_remote; True when its commit is local afterwards."""
    try:
        subprocess.run(['git', '-C', str(root), 'fetch', '-q', '--no-tags', setting('fetch_remote'), sha],
                       capture_output=True, timeout=setting('rerun_timeout_s'))
    except (subprocess.TimeoutExpired, OSError):
        return False
    return present(root, sha)


def recorded_base(root=ROOT, environ=None, fetcher=None):
    """GX-13: the base the proof is bound to, never this machine's idea of the base branch. gate-local exports it
    (defects.base_env: tier 1 the PR's baseRefOid, tier 2 the batch base); set but empty, or a sha that cannot be had
    even after a fetch, is no base (nothing is excused). Unset, as in a direct call outside gate-local, the local
    gate.batch_base_ref is resolved as before."""
    environ = os.environ if environ is None else environ
    if setting('base_env') not in environ:
        return resolve_base(root)
    sha = environ[setting('base_env')].strip()
    if not sha:
        return None
    if not present(root, sha) and not (fetcher or fetch)(root, sha):
        return None
    done = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', '--quiet', f'{sha}^{{commit}}'], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() == sha else None


def _marker(base, test):
    return '/'.join([f'v{setting("cache_version")}', base, hashlib.new(setting('digest_algorithm'), test.encode()).hexdigest()])


def lookup(location, base, test, now):
    blob = storage.open_store(location).get(_marker(base, test))
    if blob is None:
        return None
    try:
        item = json.loads(blob)
        valid = item['base_sha'] == base and item['test'] == test and 0 <= now - item['stored_at'] <= setting('cache_ttl_s')
        return item if valid and item['result'] in (PASS, FAIL) else None
    except (ValueError, KeyError, TypeError):
        return None


def _now():
    return int(forge_events.clock_from_config().now().timestamp())


def rerun(test, base, root=ROOT):
    """Run one test on a detached worktree of the base: {'result': pass|fail|error, 'signature': str}. Nothing is
    installed there and the tool root's node_modules is never linked (GX-13; the engine has no package, vazão F16)."""
    parent = Path(tempfile.mkdtemp(prefix=setting('rerun_worktree_prefix')))
    tree = parent / 'base'
    try:
        added = subprocess.run(['git', '-C', str(root), 'worktree', 'add', '--detach', '-q', str(tree), base],
                               capture_output=True, text=True)
        if added.returncode != 0:
            return {'result': ERROR, 'signature': ''}
        hermetic = str(tree / 'scripts' / 'lib' / 'hermetic')
        env = dict(os.environ, PYTHONPATH=hermetic + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else ''))
        try:
            done = subprocess.run(shlex.split(setting('rerun_command').format(script=test)), cwd=tree, env=env,
                                  capture_output=True, text=True, timeout=setting('rerun_timeout_s'))
        except (subprocess.TimeoutExpired, OSError):
            return {'result': ERROR, 'signature': ''}
        if done.returncode == 0:
            return {'result': PASS, 'signature': ''}
        tail = (done.stdout + done.stderr).splitlines()[-config.get('gate.script_tests_log_lines'):]
        failure = failure_signatures.script_failures([{'test': test, 'result': 'FAIL', 'tail': tail}])[0]
        return {'result': FAIL, 'signature': failure['signature']}
    finally:
        subprocess.run(['git', '-C', str(root), 'worktree', 'remove', '--force', str(tree)], capture_output=True)
        shutil.rmtree(parent, ignore_errors=True)


def outcome(test, base, root=ROOT, location=None, runner=None, now=None):
    """The test's result on the base, cached per (base sha, test id). An error is never cached."""
    location = location or cache_location()
    stamp = _now() if now is None else now
    hit = lookup(location, base, test, stamp)
    if hit:
        return dict(hit, cached=True)
    found = (runner or rerun)(test, base, root)
    if found['result'] in (PASS, FAIL):
        item = dict(found, base_sha=base, test=test, stored_at=stamp)
        storage.open_store(location).put(_marker(base, test), json.dumps(item, sort_keys=True).encode())
    return dict(found, base_sha=base, test=test, cached=False)


def changed_files(base, sha, root=ROOT):
    """The files the PR changed (base...sha), or None when the pair cannot be diffed (then every test is touched)."""
    if not base or not sha:
        return None
    done = subprocess.run(['git', '-C', str(root), 'diff', '--name-only', f'{base}...{sha}'], capture_output=True, text=True)
    return done.stdout.split() if done.returncode == 0 else None


def base_signal(base, reader=None):
    """GX-32: what the base health signal says about exactly `base`: {(test, stage): signature} when the newest base.red
    or base.green for that sha is a base.red, else None. Off (defects.base_signal_enabled), no base, or a log that cannot
    be read: None, so nothing is excused by the signal. `reader()` returns the repository channel's events."""
    if not base or not setting('base_signal_enabled'):
        return None
    try:
        events = (reader or _repository_signal)()
    except Exception:  # noqa: BLE001 - an unreadable signal excuses nothing; the re-run path still applies
        return None
    found = [event for event in events if event['type'] in SIGNALS and event['payload']['base_sha'] == base]
    if not found or found[-1]['type'] != SIGNALS[0]:
        return None
    return {(test['id'], test['stage']): test['signature'] for test in found[-1]['payload']['tests']}


def base_red(base, reader=None):
    """GX-32: whether the base health signal lists red tests on `base` (the re-gate pause reads this)."""
    return bool(base_signal(base, reader))


SIGNALS = ('base.red', 'base.green')


def _repository_signal():
    port = defects._port(setting('producer'), setting('base_env'))
    return port.read_recent(config.get('forge-events.repo'), kinds=list(SIGNALS))  # D-085


def touched(test, changed, root=ROOT, mapping=None):
    """GX-13: whether the PR changed the script test's own file, its covers manifest or a file its declared covers match.
    An unknown change set (None) or an unreadable covers map counts as touched: a doubt is never excused."""
    if changed is None:
        return True
    changed = set(changed)
    if test in changed or script_covers.manifest_path(test, root).relative_to(root).as_posix() in changed:
        return True
    try:
        mapping = mapping or script_covers.load(root)
    except (script_covers.ScriptTestMapError, OSError, ValueError):
        return True
    covers = [pattern for item in mapping['tests'] if item['script'] == test for pattern in item['covers']]
    return any(globs.glob_match(path, pattern) for path in changed for pattern in covers)


def adjudicate(failures, base, root=ROOT, location=None, runner=None, now=None, changed=(), mapping=None, signal=None):
    """Split failing tests ({id, stage, signature}) into the base's known defects and the PR's own. `changed` is what
    the PR changed (None: unknown); a test it touched stays the PR's and is not re-run (defects.never_excuse_touched).
    `signal` is base_signal(base): a listed test with the same signature is known with no re-run (GX-32)."""
    known, own = [], []
    for failure in failures:
        if base is None or failure['stage'] not in stages():
            own.append(failure)
            continue
        if setting('never_excuse_touched') and touched(failure['id'], changed, root, mapping):
            own.append(dict(failure, touched=True))
            continue
        if signal and signal.get((failure['id'], failure['stage'])) == failure['signature']:
            known.append(dict(failure, base_sha=base, source=SIGNALS[0],
                              defect=defects.defect_id(failure['id'], failure['signature'])))
            continue
        if not defect_adapters.rerunnable(failure['stage']):
            own.append(failure)
            continue
        found = outcome(failure['id'], base, root, location, runner, now)
        if found['result'] == FAIL and found['signature'] == failure['signature']:
            known.append(dict(failure, base_sha=base, defect=defects.defect_id(failure['id'], failure['signature'])))
        else:
            own.append(failure)
    return {'known': known, 'own': own}


def verification(records, base, root=ROOT, location=None, runner=None, now=None):
    """What the base says about each resolved defect, and each open one (GX-13, defects.verify_open):
    [{'defect', 'result': verified|reopened, 'signature'}]. An open defect that passes on the base is `verified` (sync
    moves it open -> resolved); one that still fails yields nothing, it is already open.

    The gate only reads: the registry files change when `scripts/defects sync` applies the events this yields."""
    decided = []
    if base is None:
        return decided
    statuses = {'resolved', 'open'} if setting('verify_open') else {'resolved'}
    for ident, found in sorted(records.items()):
        if found['status'] not in statuses or found['stage'] not in setting('verify_stages'):
            continue
        seen = outcome(found['test'], base, root, location, runner, now)
        if seen['result'] == PASS:
            decided.append({'defect': ident, 'result': 'verified', 'signature': ''})
        elif seen['result'] == FAIL and found['status'] == 'resolved':
            decided.append({'defect': ident, 'result': 'reopened', 'signature': seen['signature']})
    return decided


def stages():
    """The adjudicated stages: defects.stages, or with the base signal off only the re-runnable ones (GX-13 behaviour)."""
    return [name for name in setting('stages') if setting('base_signal_enabled') or defect_adapters.rerunnable(name)]


def explained(report, logs, base, root=ROOT, location=None, runner=None, now=None, changed=(), mapping=None, reader=None):
    """(known, own, unexplained) for a failed gate report: only a failed stage in stages() whose every failing test is
    known is explained; a failed stage the adapters cannot attribute to tests stays the PR's (GX-32: every shape)."""
    failed = [stage['name'] for stage in report['stages'] if stage['result'] == 'FAIL']
    found, _ = defect_adapters.failures(report, logs)
    failures = [item for item in found if item['stage'] in stages()]
    signal = base_signal(base, reader) if failures else None
    judged = adjudicate(failures, base, root, location, runner, now, changed, mapping, signal)
    unexplained = [name for name in failed if name not in stages() or name not in {f['stage'] for f in failures}]
    return judged['known'], judged['own'], unexplained


def apply_to_report(report, logs, base, root=ROOT, location=None, runner=None, now=None, changed=(), mapping=None, reader=None):
    """Flip a failed stage to PASS when all its failing tests are known base defects; the stage keeps raw_result FAIL
    and the ids of the defects that excused it (F-11: the SLOs count it). Returns the known defects."""
    known, own, unexplained = explained(report, logs, base, root, location, runner, now, changed, mapping, reader)
    if not known or own or unexplained:
        report['known_defects'] = known
        return known
    for stage in report['stages']:
        if stage['result'] == 'FAIL':
            stage['raw_result'], stage['result'] = 'FAIL', 'PASS'
            stage['defects'] = sorted({item['defect'] for item in known if item['stage'] == stage['name']})
    report['result'] = 'PASS'
    report['known_defects'] = known
    return known
