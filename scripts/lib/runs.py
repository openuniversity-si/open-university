"""Run durations as a validation source (PADRAO-DEV F8d): a snapshot of a workflow's completed runs, read by the
run-durations measure of scripts/model. The gate runs with no network, so it reads the snapshot, never the API.

    scripts/runs record <workflow> < runs.json    writes config/validation/runs/<workflow>.json from an API answer
    scripts/runs refresh <workflow>               rebuilds it from GitHub's checks of main's last merges

`record` takes an Actions API answer (an object with `workflow_runs`, or the list itself); each run lasts from
`run_started_at` to `updated_at`. Only completed runs count; a cancelled run was superseded, not judged.

`refresh` reads no Actions API (the engine never calls it: the github-actions vendor is forbidden). It reads the check
runs GitHub keeps on each commit (GET /repos/{repo}/commits/{sha}/check-runs, through the gate's github adapter
verify_commit.gh_json) for main's last merges: the merge queue's commit (merge_group) and the pull request's head
(pull_request). A run lasts from the first start of any of its jobs (its parts) to the end of its final check.
`scripts/model measure` refreshes a snapshot older than a day, so it is renewed where it is read, with no hand; the
renewed file travels with the session's next PR. Offline (no `gh`, TOWER_OFFLINE set, the API refusing) the recorded
snapshot stays, and the measure judges it by its age as before.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
FOLDER = 'config/validation/runs'
KEEP = 20  # the newest completed runs a refreshed snapshot keeps (VAL-gate-60s asks for 20)
REFRESH_DAYS = 1  # a snapshot younger than this is not read again
SPAN_S = 1800  # a part that started longer than this before the final check belongs to an earlier attempt
# the workflows refresh reads from GitHub's check runs: (the final check's name, the prefix of its parts' names)
CHECKS = {'tower-gate': ('tower/gate', 'gate part')}


def stamp(text):
    return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def normalize(answer):
    """[{id, event, conclusion, started, seconds}] of the completed, not cancelled, runs of an API answer."""
    runs = answer.get('workflow_runs', []) if isinstance(answer, dict) else answer
    found = []
    for run in runs:
        if run.get('status') not in (None, 'completed') or run.get('conclusion') in ('cancelled', 'skipped'):
            continue
        started = run.get('run_started_at') or run['created_at']
        found.append({'id': run['id'], 'event': run.get('event', ''), 'conclusion': run.get('conclusion', ''),
                      'started': started, 'seconds': int((stamp(run['updated_at']) - stamp(started)).total_seconds())})
    return sorted(found, key=lambda run: run['started'], reverse=True)


def snapshot(workflow, answer, now=None):
    return {'workflow': workflow, 'source': f'GitHub Actions API, workflow {workflow}',
            'at': now or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), 'runs': normalize(answer)}


def percentile(values, share):
    """The nearest-rank percentile (share in 0..100) of `values`; None when empty."""
    ordered = sorted(values)
    if not ordered:
        return None
    rank = max(1, -(-len(ordered) * share // 100))
    return ordered[int(rank) - 1]


def read(root, workflow):
    path = Path(root) / FOLDER / f'{workflow}.json'
    return json.loads(path.read_text()) if path.exists() else None


def write(root, made):
    target = Path(root) / FOLDER / f'{made["workflow"]}.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(made, indent=1) + '\n')
    return target


def repository():
    if os.environ.get('GITHUB_REPOSITORY'):
        return os.environ['GITHUB_REPOSITORY']
    import config
    return config.get('forge-events.repo')


def merges(root, count, run=subprocess.run):
    """[(sha, event)] of main's last `count` merges: the merge commit (the merge queue's, merge_group) and its second
    parent (the pull request's head, pull_request), from origin/main, else HEAD."""
    for ref in ('origin/main', 'HEAD'):
        done = run(['git', 'log', '--first-parent', '--merges', f'-n{count}', '--format=%H %P', ref], cwd=root,
                   capture_output=True, text=True)
        if done.returncode == 0 and done.stdout.strip():
            break
    else:
        return []
    found = []
    for line in done.stdout.splitlines():
        sha, *parents = line.split()
        found += [(sha, 'merge_group')] + ([(parents[1], 'pull_request')] if len(parents) > 1 else [])
    return found


def from_checks(event, checks, final, parts):
    """The run of one commit from its check runs: from the first start of a part (or of the final check) to the end of
    the newest completed final check; None when it has none or it was cancelled or skipped."""
    ended = sorted((check for check in checks if check.get('name') == final and check.get('status') == 'completed'
                    and check.get('completed_at') and check.get('started_at')), key=lambda check: check['started_at'])
    if not ended or ended[-1].get('conclusion') in ('cancelled', 'skipped'):
        return None
    last = ended[-1]
    starts = [check['started_at'] for check in checks
              if check.get('started_at') and check['started_at'] <= last['started_at']
              and (check.get('name') == final or str(check.get('name', '')).startswith(parts))
              and (stamp(last['started_at']) - stamp(check['started_at'])).total_seconds() <= SPAN_S]
    began = min(starts or [last['started_at']])
    return {'id': last['id'], 'event': event, 'conclusion': last.get('conclusion', ''), 'started': began,
            'seconds': int((stamp(last['completed_at']) - stamp(began)).total_seconds())}


def fetch(root, workflow, repo=None, api=None, run=subprocess.run):
    """The runs of `workflow` (a CHECKS entry) on main's last merges, newest first; None offline or when the API
    refuses. `api(path)` answers GitHub's REST API (the gate's github adapter, verify_commit.gh_json, by default)."""
    if workflow not in CHECKS or os.environ.get('TOWER_OFFLINE'):
        return None
    if api is None:
        import verify_commit  # the gate's github adapter: tower/gate's own reads of GitHub's REST API
        api = lambda path: verify_commit.gh_json(verify_commit.run, path)  # noqa: E731
    final, parts = CHECKS[workflow]
    repo, found = repo or repository(), []
    for sha, event in merges(root, KEEP, run):
        try:
            answer = api(f'repos/{repo}/commits/{sha}/check-runs?per_page=100')
        except (OSError, RuntimeError, ValueError):
            return None
        made = from_checks(event, answer.get('check_runs', []), final, parts)
        if made:
            found.append(made)
    return sorted(found, key=lambda item: item['started'], reverse=True)[:KEEP]


def age_days(recorded, now):
    return (now - stamp(recorded['at'])).total_seconds() / 86400


def renewed(workflow, found, now):
    return {'workflow': workflow, 'source': f"GitHub check runs of main's last merges, check {CHECKS[workflow][0]}",
            'at': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'runs': found[:KEEP]}


def refresh(root, workflow, now=None, reader=None):
    """Rebuilds the snapshot of `workflow` from GitHub's checks when it is missing or older than REFRESH_DAYS and the
    API answers; the snapshot (new or kept) or None. `reader(workflow)` answers the runs (fetch by default)."""
    now = now or datetime.now(timezone.utc)
    recorded = read(root, workflow)
    if recorded and age_days(recorded, now) < REFRESH_DAYS:
        return recorded
    found = (reader or (lambda name: fetch(root, name)))(workflow)
    if not found:
        return recorded
    made = renewed(workflow, found, now)
    write(root, made)
    return made


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/runs', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    recorded = commands.add_parser('record', help='write the snapshot of a workflow from the API answer on stdin')
    recorded.add_argument('workflow')
    again = commands.add_parser('refresh', help="rebuild the snapshot from GitHub's checks of main's last merges")
    again.add_argument('workflow', choices=sorted(CHECKS))
    args = parser.parse_args(argv)
    if args.command == 'refresh':
        found = fetch(root, args.workflow)
        if not found:
            print(f'runs: no check runs read for {args.workflow} (offline, gh missing or the API refused); snapshot kept',
                  file=sys.stderr)
            return 2
        made = renewed(args.workflow, found, datetime.now(timezone.utc))
    else:
        made = snapshot(args.workflow, json.load(sys.stdin))
    target = write(root, made)
    print(f'runs: {len(made["runs"])} completed run(s) of {args.workflow} -> {target.relative_to(root)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
