"""The explicit, reversible gate bypass (D-151): green at once, marked, and off by one switch.

`enabled()` is the one question every caller asks: `GATE_BYPASS` in the environment (1 on, 0 off) wins for the run,
else `gate.bypass` in the shared store. Where it is on:
  scripts/gate-local   `gate_bypass.py run ...` before the pin, the preflight, the lock and the worktree: a PASS for every
                       expected stage (each stage.json carries `bypass`) except `script tests`, which runs the selected
                       tests through the cache and fails the gate when one is red (D-302), the gate.passed evidence without a v4 proof
                       (D-259), the pr.ready hook through gate_report.py, and the pass record with the line `bypass=D-151`;
  train_git.Tier2Gate  the train's tier-2 gate is not bypassed (D-259): the train never admits a bypassed verdict.
Nothing here skips a hook, forces a push or edits history: the bypass is a decision of the gate, recorded in every
artifact it writes, so `grep -r bypass .gate/records` finds every verdict it gave.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import forge_events  # noqa: E402
import gate_report  # noqa: E402

try:  # the exception regime (D-260) answers the 'gate' lock; a checkout without it keeps the switch alone
    import regime  # noqa: E402
except ImportError:  # pragma: no cover
    regime = None

ENV = 'GATE_BYPASS'
MARK = 'bypass=D-151'
SUFFIXES = {'pr': 'pr.pass', 'nightly': 'pass', 'dev': 'dev.pass', 'noite': 'noite.pass', 'tier3': 'tier3.pass'}


def enabled(environ=None, root=None):
    """True when the gate must give green at once."""
    value = (os.environ if environ is None else environ).get(ENV)
    if value in ('0', '1'):
        return value == '1'
    try:
        if config.shared('gate.bypass', root):
            return True
    except Exception:  # an unreadable store is no bypass: the gate runs
        return False
    return by_regime()


def _own_switch(root):
    try:
        return bool(config.shared('gate.bypass', root))
    except Exception:
        return False


def by_regime():
    """True when the exception regime lifts the 'gate' lock (D-260); an unreadable regime lifts nothing. Read from the
    shared store like gate.bypass: a gate pinned to `file` otherwise lifts a lock the shared regime keeps (I-ddaca17c)."""
    try:
        return bool(regime and regime.lifted('gate', regime.state(shared=True)))
    except Exception:
        return False


def announce(root, sha, pr, lane='gate-local'):
    """The regime lifted the gate lock for this verdict: print the warning and emit lock.lifted (best effort: a port that
    cannot be built or reached never turns the lifted gate red; the warning is printed either way)."""
    if not by_regime():
        return False
    try:
        port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                        config.get('forge-events.gate_producer'), f'pr-{pr}' if pr else f'gate-{sha}')
        return regime.lift('gate', sha, lane, port, config.get('forge-events.repo'), pr or None)
    except Exception as error:  # the lock is lifted whatever happens to the event
        print(regime.warning('gate', regime.state()) + f' (lock.lifted not emitted: {type(error).__name__})')
        return True


def head_of(root, pr, sha):
    """The commit the verdict is for: `sha`, else the PR's head as the forge records it (D-302)."""
    if sha:
        done = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', f'{sha}^{{commit}}'], capture_output=True, text=True)
        return done.stdout.strip() if done.returncode == 0 else sha
    # D-302: the head comes from the forge's change record, as the real gate pins it. Origin's refs/pull/* are the ones
    # imported from GitHub (ORIGIN-FINISH R5), so fetching refs/pull/<n>/head judged an unrelated commit (#214: bf9154b9b).
    import gate_pin
    try:
        head = gate_pin.pr_identity(root, pr)[0]
        return gate_pin.fetch_commit(root, head)
    except gate_pin.PinError as error:
        raise SystemExit(f'gate bypass: cannot read the head of PR {pr}: {error}')


def write_stages(logs, mode, script_tests=None):
    """A PASS, marked bypass, for every stage the mode expects (and `script tests` for the dev plan), except `script tests`
    when `script_tests` (an exit code) is given: GR (D-302) runs them for real, and that stage keeps its true result."""
    names = list(gate_report.expected_stages(mode, logs))
    if mode == 'dev' and 'script tests' not in names:
        names.append('script tests')
    Path(logs).mkdir(parents=True, exist_ok=True)
    for name in names:
        stem = ''.join(ch if ch.isalnum() else '_' for ch in name)
        record = {'name': name, 'result': 'PASS', 'exit': 0, 'seconds': 0.0, 'started_at': time.time(), 'bypass': MARK}
        if name == 'script tests' and script_tests is not None:
            record = {'name': name, 'result': 'PASS' if script_tests == 0 else 'FAIL', 'exit': script_tests,
                      'seconds': 0.0, 'started_at': time.time()}
        (Path(logs) / f'{stem}.stage.json').write_text(json.dumps(record))
    (Path(logs) / 'bypass.json').write_text(json.dumps({'bypass': MARK, 'stages': names}))
    return names


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)


def run_script_tests(root, sha, logs):
    """GR (D-302): the script tests the diff selects, run through the test cache on a checkout of `sha`; returns the exit
    code (0: all green or cached). The selection is the gate's own (gate_script_tests.select over base...sha; an
    unreadable diff selects the whole suite). Anything that stops them running is a FAIL: the bypass never guesses green."""
    import tempfile
    log = Path(logs) / 'script_tests.log'
    tool = Path(__file__).resolve().parents[2]
    try:
        remote, base = config.get('push-guard.remote'), config.get('train.base_branch')
        diff = _git(root, 'diff', '--name-only', f'{remote}/{base}...{sha}')
        paths = diff.stdout.split() if diff.returncode == 0 else []
        with tempfile.TemporaryDirectory(prefix='gate-bypass-') as tmp:
            tree = Path(tmp) / 'tree'
            os.chmod(tmp, 0o755)  # mkdtemp is 0700: tests that drop to another uid (root-identity) must traverse it
            added = _git(root, 'worktree', 'add', '-q', '--detach', str(tree), sha)
            if added.returncode:
                raise RuntimeError(f'could not check out {sha}: {added.stderr.strip()}')
            try:
                if (tool / '.toolchain').is_dir() and not (tree / '.toolchain').exists():
                    (tree / '.toolchain').symlink_to((tool / '.toolchain').resolve())
                env = dict(os.environ, OU_SUBJECT_ROOT=str(tree), OU_CONFIG_STORE='file')
                plan = Path(tmp) / 'plan.json'
                plan.write_text(json.dumps({'kind': 'scoped', 'paths': paths} if paths else {'kind': 'full'}))
                chosen = subprocess.run([sys.executable, str(tool / 'scripts/lib/gate_script_tests.py'), 'select', str(plan)],
                                        capture_output=True, text=True, env=env)
                names = [line for line in chosen.stdout.splitlines() if line.strip() and not line.startswith('#')]
                if chosen.returncode or not names:
                    raise RuntimeError(f'the selector chose no script test: {chosen.stderr.strip()}')
                listing = Path(tmp) / 'list'
                listing.write_text('\n'.join(names) + '\n')
                done = subprocess.run([sys.executable, str(tool / 'scripts/lib/gate_test_cache.py'), 'run', str(listing),
                                       '--root', str(tree), '--tool-root', str(tool), '--logs', str(logs), '--source', sha],
                                      capture_output=True, text=True, env=env)
                log.write_text(done.stdout + done.stderr)
                return done.returncode
            finally:
                _git(root, 'worktree', 'remove', '--force', str(tree))
    except Exception as error:  # noqa: BLE001 - tests that cannot run are not a pass
        log.write_text(f'FAIL script tests: {error}\n')
        return 1


def run(root, mode, pr, sha, record_dir=None):
    """The whole bypassed gate; returns the exit code gate-local would."""
    sha = head_of(root, pr, sha)
    if not os.environ.get(ENV) and not _own_switch(root):
        announce(root, sha, pr)  # only the regime lifted it: name the lock and leave the event (D-260)
    record_dir = Path(record_dir or Path(root) / '.gate' / 'records')
    logs = record_dir / 'reports' / sha / f'{mode}-{time.strftime("%Y%m%dT%H%M%S")}'
    logs.mkdir(parents=True, exist_ok=True)
    code = run_script_tests(root, sha, logs)  # D-302: the one stage the bypass does not lift
    write_stages(logs, mode, code)
    script_failed = code != 0
    if script_failed:
        print(f'GATE: script tests FAILED under the bypass (D-302); log: {logs}/script_tests.log')
    # A bypassed verdict binds no v4 proof (D-259): the evidence is not one the train admits, so a head is merged only on
    # a real gate verdict of its own head. The pass is still shown, marked, to the people who read the records.
    os.environ.pop('OU_GATE_PROOF', None)
    # D-302: a red selected test is the PR's, whatever the base says: no known-defect or base excuse turns it green.
    keep, gate_report.adjudicate_known_defects = gate_report.adjudicate_known_defects, lambda *args, **kwargs: None
    try:
        code = gate_report.main([str(logs), sha, str(1 if script_failed else 0), mode, pr or ''])
    finally:
        gate_report.adjudicate_known_defects = keep
    if code:
        print('GATE: FAILED')
        return 1
    suffix = SUFFIXES.get(mode, 'pass')
    record_dir.mkdir(parents=True, exist_ok=True)
    lines = [f'sha={sha}', f'date={time.strftime("%Y-%m-%dT%H:%M:%S%z")}', 'nightly=0', f'host={os.uname().nodename}',
             f'kind={mode}', MARK]
    if pr and mode != 'dev':
        lines.append(f'pr={pr}')
    (record_dir / f'{sha}.{suffix}').write_text('\n'.join(lines) + '\n')
    print(f'GATE: PASSED ({MARK}; recorded {record_dir}/{sha}.{suffix})')
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command, rest = (argv[:1] or [''])[0], argv[1:]
    if command == 'check':
        return 0 if enabled() else 1
    if command == 'run':
        import argparse
        parser = argparse.ArgumentParser(prog='gate_bypass.py run')
        parser.add_argument('--root', default='.')
        parser.add_argument('--mode', required=True)
        parser.add_argument('--pr', default='')
        parser.add_argument('--sha', default='')
        parser.add_argument('--record-dir')
        values = parser.parse_args(rest)
        return run(values.root, values.mode, values.pr, values.sha, values.record_dir)
    raise SystemExit('usage: gate_bypass.py check | run --root R --mode M [--pr N] [--sha S] [--record-dir D]')


if __name__ == '__main__':
    sys.exit(main())
