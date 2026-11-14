"""Run the unchanged full battery on main and identify candidate merged PRs for failures."""
import argparse
from fnmatch import fnmatchcase
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from gate_policy import ROOT, FULL_STAGES
from gate_report import stage_results
import regime_lifts
from session_identity import open_lock



def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def merges(head, since=None):
    args = ['log', '--first-parent', '--merges', '--format=%H%x09%s']
    if since:
        subprocess.run(['git', '-C', str(ROOT), 'merge-base', '--is-ancestor', since, head], check=True)
        args.append(since + '..' + head)
    else: args += ['--since=24 hours ago', head]
    result = []
    for line in git(*args).splitlines():
        sha, title = line.split('\t', 1)
        number = re.search(r'(?:pull request #|\(#)(\d+)', title)
        # Keep non-PR merges visible too; never invent a responsible PR.
        result.append({'sha': sha, 'pr': int(number[1]) if number else None, 'title': title,
                       'files': git('diff', '--no-renames', '--name-only', sha + '^1', sha).splitlines()})
    return result


# OU-DECOUPLE F5 (D-113): Open University's web, database and browser stages left with their source map and the browser
# report; every engine stage reads the tooling under scripts/, and an unmapped failure still lists every PR of the interval.
SOURCES = ['scripts/**']


def candidates(stage, changes):
    """The PRs of `changes` whose files can explain a failure of `stage`; every PR of the interval when none maps."""
    patterns = SOURCES
    mapped = [change for change in changes if any(fnmatchcase(path, p) for path in change['files'] for p in patterns)]
    pool = mapped or changes
    return sorted({c['pr'] for c in pool if c['pr'] is not None})


def report(logs, head, changes, rc, since):
    stages = stage_results(logs)
    present = {s['name'] for s in stages}
    # Mark unreached stages explicitly, including failures during checkout/setup.
    stages += [{'name': s, 'result': 'NOT RUN', 'seconds': 0} for s in FULL_STAGES if s not in present]
    failures = []
    for stage in stages:
        if stage['result'] != 'PASS':
            failures.append({'stage': stage['name'], 'result': stage['result'], 'candidatePRs': candidates(stage['name'], changes)})
    result = {'sha': head, 'since': since or 'last 24 hours', 'result': 'PASS' if rc == 0 and not failures else 'FAIL',
              'stages': stages, 'failures': failures, 'mergedPRs': changes,
              'attribution': 'Candidate PRs only; an unmapped failure lists all PRs in the interval.'}
    (logs / 'noite.json').write_text(json.dumps(result, indent=2))
    lines = [f'# gate-noite: {result["result"]}', f'Commit: `{head}`; since: `{result["since"]}`.', '',
             '| Stage | Result | Seconds |', '|---|---|---:|']
    lines += [f'| {s["name"]} | {s["result"]} | {s["seconds"]:.3f} |' for s in stages]
    lines += ['', 'Candidate PRs only; attribution is not certainty. Unmapped failures list all interval PRs.']
    lines += [f'- {f["stage"]}: {f["result"]}; candidate PRs: ' +
              (', '.join('#' + str(p) for p in f['candidatePRs']) or 'none in interval') for f in failures]
    (logs / 'noite.md').write_text('\n'.join(lines) + '\n')
    print(f'Night report: {logs / "noite.md"} (JSON: {logs / "noite.json"})', flush=True)
    return result


def read_events(path):
    """The envelopes of a JSON-lines file; a line that is not JSON is an error, not a skipped event (D-260)."""
    events = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except ValueError:
            raise RuntimeError(f'gate-noite: {path} line {number} is not an event (JSON)') from None
    return events


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha'); parser.add_argument('--since'); parser.add_argument('--list', '--dry-run', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--regime-since', help='RFC 3339 instant the exception regime began (D-260)')
    parser.add_argument('--events', help='JSON lines of event envelopes; lists every lock.lifted since --regime-since (D-260)')
    args = parser.parse_args()
    record = Path(os.environ.get('GATE_RECORD_DIR', str(ROOT / '.gate' / 'records')))
    record.mkdir(parents=True, exist_ok=True)
    # Serialize the nightly state/report lifecycle too, independently of the full gate's checkout lock.
    import fcntl
    with open_lock(record / 'noite.lock') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        subprocess.run(['git', '-C', str(ROOT), 'fetch', '-q', 'origin'], check=True)
        head = git('rev-parse', '--verify', (args.sha or 'origin/main') + '^{commit}')
        state = record / 'last-noite-sha'
        since = args.since or (state.read_text().strip() if state.is_file() else None)
        changes = merges(head, since)
        # OU-DECOUPLE F5 (D-113): no Neon acceptance any more, so the night needs no merged PR to borrow a branch from.
        # D-260: nothing the regime lifted is silent; the night lists every lock.lifted since it began.
        if args.events:
            print('\n'.join(regime_lifts.render(regime_lifts.lifted(read_events(args.events), args.regime_since), args.regime_since)))
        if args.list:
            print(json.dumps({'sha': head, 'since': since or 'last 24 hours', 'stages': FULL_STAGES, 'mergedPRs': changes},
                             indent=2))
            return
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
        logs = Path(os.environ.get('GATE_REPORT_DIR', str(record / 'reports' / head / ('noite-' + stamp))))
        logs.mkdir(parents=True, exist_ok=True)
        # Separate record prevents a night run from erasing a PR's full acceptance proof.
        (record / (head + '.noite.pass')).unlink(missing_ok=True)
        env = dict(os.environ, GATE_REPORT_DIR=str(logs.resolve()))
        command = [str(ROOT / 'scripts/gate-local'), '--noite', '--sha', head]
        if args.verbose: command.append('--verbose')
        rc = subprocess.run(command, env=env).returncode
        result = report(logs, head, changes, rc, since)
        if result['result'] != 'PASS':
            (record / (head + '.noite.pass')).unlink(missing_ok=True)
            raise RuntimeError('Full nightly verification failed; see report')
        temporary = state.with_suffix('.tmp'); temporary.write_text(head + '\n'); temporary.replace(state)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error) if isinstance(error, RuntimeError) else 'gate-noite setup/report failed; last successful state unchanged', file=sys.stderr)
        sys.exit(1)
