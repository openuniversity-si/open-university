"""The real gate, for measurement only, while the bypass is on (D-151): `scripts/gate-shadow run [REF] | latest`."""
import fcntl
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate_bypass  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
FOLDER = '.gate/shadow'
REPORTS = '.gate/report-only/reports'  # where a report-only gate writes its stage report (gate_pin.REPORT_ONLY_DIR)
BASE = 'origin/mod/roadmap-integration'


def resolve(root, ref):
    done = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', f'{ref}^{{commit}}'], capture_output=True, text=True)
    if done.returncode:
        raise SystemExit(f'gate-shadow: unknown ref {ref}')
    return done.stdout.strip()


def run_folder(root, sha):
    """A fresh folder under the report-only tree for this run: the gate writes its report there (GATE_REPORT_DIR, D-258)."""
    base = Path(root) / REPORTS / sha
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix='shadow-', dir=str(base)))


def measure(root, sha, command=None):
    """Run the real gate on `sha` with the bypass off and no events; the result dict is also written to disk. The gate's own
    verdict in its stage report (this run's folder, GATE_REPORT_DIR) decides `passed`; the exit code only when no report was written."""
    command = command or [str(Path(root) / 'scripts' / 'gate-dev'), '--report-only', '--sha', sha]
    started = time.time()
    folder = run_folder(root, sha)
    done = subprocess.run(command, cwd=str(root), capture_output=True, text=True,
                          env=dict(os.environ, **{gate_bypass.ENV: '0', 'GATE_REPORT_DIR': str(folder)}))
    report = folder / 'stages.json'
    stages = json.loads(report.read_text()) if report.is_file() else {}
    verdict = stages.get('result')
    result = {'sha': sha, 'at': time.time(), 'passed': verdict == 'PASS' if verdict else done.returncode == 0,
              'wall_s': round(time.time() - started, 1), 'exit': done.returncode, 'verdict': verdict,
              'report': str(folder) if report.is_file() else None,
              'failing': [stage['name'] for stage in stages.get('stages', []) if stage.get('result') == 'FAIL'],
              'tail': (done.stdout + done.stderr).strip().splitlines()[-1:]}
    folder = Path(root) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f'{sha}.json').write_text(json.dumps(result, indent=1) + '\n')
    return result


def exclusive(root):
    """An open, flock-held file while this process measures; None when another shadow run holds it: two real gates on one
    checkout would fight over its lock and database, and the newer tip is measured by the run that starts after."""
    folder = Path(root) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    handle = open(folder / 'running.lock', 'w')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def latest(root):
    files = sorted((Path(root) / FOLDER).glob('*.json'), key=lambda path: path.stat().st_mtime)
    if not files:
        return None
    found = json.loads(files[-1].read_text())
    found.setdefault('at', files[-1].stat().st_mtime)  # results written before `at` existed
    return found


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    command = (argv[:1] or [''])[0]
    if command == 'run':
        ref = argv[1] if argv[1:] else BASE
        if ref == BASE:
            subprocess.run(['git', '-C', str(ROOT), 'fetch', '--quiet', 'origin', 'mod/roadmap-integration'], capture_output=True)
        held = exclusive(ROOT)
        if held is None:
            print('gate-shadow: another shadow run is measuring; this tip is measured by the next one')
            return 0
        result = measure(ROOT, resolve(ROOT, ref))
        print(f"gate-shadow: {result['sha']} {'passed' if result['passed'] else 'FAILED'} in {result['wall_s']} s")
        if not result['passed']:
            print('BASE BROKEN: the real gate fails on ' + result['sha'])
            return 1
        return 0
    if command == 'latest':
        found = latest(ROOT)
        print(json.dumps(found, indent=1) if found else 'gate-shadow: no result yet')
        return 0
    raise SystemExit('usage: scripts/gate-shadow run [REF] | latest')


if __name__ == '__main__':
    sys.exit(main())
