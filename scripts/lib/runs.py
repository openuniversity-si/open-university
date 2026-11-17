"""Run durations as a validation source (PADRAO-DEV F8d): a snapshot of a workflow's completed runs, recorded from
GitHub's API (`GET /repos/{owner}/{repo}/actions/workflows/{file}/runs`), read by the run-durations measure of
scripts/model. The gate runs with no network, so it reads the snapshot, never the API.

    scripts/runs record <workflow> < runs.json    writes config/validation/runs/<workflow>.json

The input is the API's answer (an object with `workflow_runs`, or the list itself); each run's duration is from
`run_started_at` to `updated_at`, in seconds. Only completed runs count; a cancelled run was superseded, not judged.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
FOLDER = 'config/validation/runs'


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


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/runs', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    recorded = commands.add_parser('record', help='write the snapshot of a workflow from the API answer on stdin')
    recorded.add_argument('workflow')
    args = parser.parse_args(argv)
    made = snapshot(args.workflow, json.load(sys.stdin))
    target = Path(root) / FOLDER / f'{args.workflow}.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(made, indent=1) + '\n')
    print(f'runs: {len(made["runs"])} completed run(s) of {args.workflow} -> {target.relative_to(root)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
