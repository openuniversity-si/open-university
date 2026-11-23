"""Run durations as a validation source (PADRAO-DEV F8d): a snapshot of a workflow's completed runs, read by the
run-durations measure of scripts/model. The gate runs with no network, so it reads the snapshot, never the API.

    scripts/runs record <workflow> < runs.json    writes config/validation/runs/<workflow>.json from an API answer
    scripts/runs refresh <workflow>               rebuilds it from GitHub's checks of main's last merges
    scripts/runs refresh-slo                      rebuilds config/validation/slo.json, the four SLOs' samples
    scripts/runs refresh-verdicts                 rebuilds config/validation/verdicts.json, the full-suite's verdicts

`record` takes an Actions API answer (an object with `workflow_runs`, or the list itself); each run lasts from
`run_started_at` to `updated_at`. Only completed runs count; a cancelled run was superseded, not judged.

`refresh` reads no Actions API (the engine never calls it: the github-actions vendor is forbidden). It reads the check
runs GitHub keeps on each commit (GET /repos/{repo}/commits/{sha}/check-runs, through the gate's github adapter
verify_commit.gh_json) for main's last merges: the merge queue's commit (merge_group) and the pull request's head
(pull_request). A run lasts from the first start of any of its jobs (its parts) to the end of its final check.
`scripts/model measure` refreshes a snapshot older than a day, so it is renewed where it is read, with no hand; the
renewed file travels with the session's next PR. Offline (no `gh`, TOWER_OFFLINE set, the API refusing) the recorded
snapshot stays, and the measure judges it by its age as before.

`refresh-slo` reads the four SLOs of config/registry/slo.json from GitHub the same way (slo_fetch), not from the
Origin-era forge event log: merge times of the newest merged pull requests, the merge queue's wait in their timelines,
and the tower/gate check runs of the commits they pushed. scripts/model folds them with slo.evaluate_series and renews
the snapshot where it measures, when a day old.

`refresh-verdicts` reads the full-suite check run (.github/workflows/full-suite.yml: every script test, on each merge
into main) of main's last merges the same way: its conclusion on each merge commit. scripts/model reads a test's pass
state on HEAD from it (model.derive_verdicts) and renews it where it measures, when a day old.
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


def pr_commits(repo, api, count=None, limit=KEEP):
    """[(sha, 'pull_request')] of commits pushed to the newest pull requests (pass and fail alike, removing
    merge-only survival bias, M3), newest commit first and deduplicated by sha."""
    from concurrent.futures import ThreadPoolExecutor
    recent = api(f'repos/{repo}/pulls?state=all&sort=created&direction=desc&per_page={SLO_PRS if count is None else count}')
    numbers = [pull['number'] for pull in recent]
    with ThreadPoolExecutor(SLO_WORKERS) as pool:
        timelines = list(pool.map(lambda n: api(f'repos/{repo}/issues/{n}/timeline?per_page=100'), numbers))
    commits = [(item['sha'], (item.get('committer') or {}).get('date', ''))
               for timeline in timelines for item in timeline
               if item.get('event') == 'committed' and item.get('sha')]
    ordered = sorted(commits, key=lambda item: item[1], reverse=True)
    return [(sha, 'pull_request') for sha in dict.fromkeys(sha for sha, _ in ordered)][:limit]


def fetch(root, workflow, repo=None, api=None, run=subprocess.run):
    """The runs of `workflow` (a CHECKS entry) across commits pushed to recent pull requests (pass and fail alike,
    removing merge-only survival bias, M3) plus main's merge_group commits, newest first; None offline or when the API
    refuses. `api(path)` answers GitHub's REST API (the gate's github adapter, verify_commit.gh_json, by default)."""
    if workflow not in CHECKS or os.environ.get('TOWER_OFFLINE'):
        return None
    if api is None:
        import verify_commit  # the gate's github adapter: tower/gate's own reads of GitHub's REST API
        api = lambda path: verify_commit.gh_json(verify_commit.run, path)  # noqa: E731
    from concurrent.futures import ThreadPoolExecutor
    final, parts = CHECKS[workflow]
    repo = repo or repository()
    try:
        pushed = pr_commits(repo, api, SLO_PRS, KEEP)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return None
    queued = [(sha, event) for sha, event in merges(root, KEEP, run) if event == 'merge_group']
    targets, seen_shas = [], set()
    for sha, event in pushed + queued:
        if sha not in seen_shas:
            seen_shas.add(sha)
            targets.append((sha, event))
    try:
        with ThreadPoolExecutor(SLO_WORKERS) as pool:
            answers = list(pool.map(lambda target: api(f'repos/{repo}/commits/{target[0]}/check-runs?per_page=100'),
                                    targets))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return None
    found, seen_ids = [], set()
    for (_, event), answer in zip(targets, answers):
        made = from_checks(event, answer.get('check_runs', []), final, parts)
        if made and made['id'] not in seen_ids:
            seen_ids.add(made['id'])
            found.append(made)
    return sorted(found, key=lambda item: item['started'], reverse=True)[:KEEP]


def age_days(recorded, now):
    return (now - stamp(recorded['at'])).total_seconds() / 86400


def snapshot_max_merges(root=ROOT):
    """Most first-parent merges on main a snapshot may trail before being rebuilt (medir.snapshot_max_merges, M3)."""
    import config
    try:
        return config.get('medir.snapshot_max_merges', root)
    except config.ConfigError:
        return config.get('medir.snapshot_max_merges', ROOT)


def merges_since(root, since_iso, run=subprocess.run):
    """Number of first-parent merges on origin/main (else HEAD) strictly newer than `since_iso` (UTC);
    0 when `root` is not a git repository or `since_iso` cannot be parsed."""
    try:
        cutoff = int(stamp(since_iso).timestamp())
    except (TypeError, ValueError):
        return 0
    for ref in ('origin/main', 'HEAD'):
        done = run(['git', 'log', '--first-parent', '--merges', '--format=%ct', ref], cwd=root,
                   capture_output=True, text=True)
        if done.returncode == 0 and done.stdout.strip():
            return sum(1 for line in done.stdout.splitlines() if line.strip().isdigit() and int(line.strip()) > cutoff)
    return 0


def stale(root, recorded, now, max_merges=None, run=subprocess.run):
    """Whether a snapshot should be rebuilt: missing, at least REFRESH_DAYS old, or at least max_merges merges
    behind main (M3)."""
    if not recorded:
        return True
    if age_days(recorded, now) >= REFRESH_DAYS:
        return True
    limit = snapshot_max_merges(root) if max_merges is None else max_merges
    return bool(limit) and merges_since(root, recorded['at'], run) >= limit


def renewed(workflow, found, now):
    return {'workflow': workflow,
            'source': f"GitHub check runs of pull-request commits and main's merges, check {CHECKS[workflow][0]}",
            'at': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'runs': found[:KEEP]}


def refresh(root, workflow, now=None, reader=None, max_merges=None, run=subprocess.run):
    """Rebuilds the snapshot of `workflow` from GitHub's checks when it is missing, older than REFRESH_DAYS, or
    trailing main by at least medir.snapshot_max_merges merges and the API answers; the snapshot (new or kept) or None.
    `reader(workflow)` answers the runs (fetch by default)."""
    now = now or datetime.now(timezone.utc)
    recorded = read(root, workflow)
    if not stale(root, recorded, now, max_merges=max_merges, run=run):
        return recorded
    found = (reader or (lambda name: fetch(root, name)))(workflow)
    if not found:
        return recorded
    made = renewed(workflow, found, now)
    write(root, made)
    return made


SLO_FILE = 'config/validation/slo.json'  # the SLOs' GitHub snapshot (not a VAL-*.json: read_validations skips it)
SLO_MERGES = 100  # the newest merged pull requests whose merge times the pace reads (one page)
SLO_PRS = 30  # the newest pull requests whose timelines give queue times and the commits the gate judged
SLO_VERDICTS = 100  # the newest of those commits whose tower/gate check runs are read (slo.sample_window_events)
SLO_MAX_AGE_DAYS = 2  # an older snapshot gives no fresh SLO value
SLO_WORKERS = 8  # GitHub reads in flight while a snapshot is rebuilt


def slo_fetch(repo=None, api=None):
    """The SLO samples from GitHub, never the Actions API and never the forge event log (the Origin-era source):
    merges: [{pr, at}] of the newest merged pull requests (merged_at);
    queue: [{pr, at, seconds}] from the last added_to_merge_queue to merged in a pull request's timeline (the merge
        queue replaced the train, D-314; the train's pr.ready to pr.merged is that same wait);
    verdicts: [{pr, sha, id, at, passed, seconds}] the tower/gate run (from_checks) of each commit the newest pull
        requests pushed, one gate per push (commit-check refuses several commits in one push); a cancelled or
        skipped run was superseded, not judged.
    None offline or when the API refuses."""
    if os.environ.get('TOWER_OFFLINE'):
        return None
    if api is None:
        import verify_commit  # the gate's github adapter: tower/gate's own reads of GitHub's REST API
        api = lambda path: verify_commit.gh_json(verify_commit.run, path)  # noqa: E731
    from concurrent.futures import ThreadPoolExecutor
    repo, (final, parts) = repo or repository(), CHECKS['tower-gate']
    try:
        closed = api(f'repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page={SLO_MERGES}')
        recent = api(f'repos/{repo}/pulls?state=all&sort=created&direction=desc&per_page={SLO_PRS}')
        numbers = [pull['number'] for pull in recent]
        with ThreadPoolExecutor(SLO_WORKERS) as pool:
            timelines = list(pool.map(lambda n: api(f'repos/{repo}/issues/{n}/timeline?per_page=100'), numbers))
        queue, commits = [], []
        for number, timeline in zip(numbers, timelines):
            added = [item['created_at'] for item in timeline if item.get('event') == 'added_to_merge_queue']
            merged = [item['created_at'] for item in timeline if item.get('event') == 'merged']
            if added and merged and max(added) <= merged[-1]:
                queue.append({'pr': number, 'at': merged[-1],
                              'seconds': int((stamp(merged[-1]) - stamp(max(added))).total_seconds())})
            commits += [(number, item['sha'], (item.get('committer') or {}).get('date', '')) for item in timeline
                        if item.get('event') == 'committed' and item.get('sha')]
        commits = sorted(commits, key=lambda commit: commit[2], reverse=True)[:SLO_VERDICTS]
        with ThreadPoolExecutor(SLO_WORKERS) as pool:
            answers = list(pool.map(lambda c: api(f'repos/{repo}/commits/{c[1]}/check-runs?per_page=100'), commits))
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return None
    verdicts = []
    for (number, sha, _), answer in zip(commits, answers):
        made = from_checks('pull_request', answer.get('check_runs', []), final, parts)
        if made:
            verdicts.append({'pr': number, 'sha': sha, 'id': made['id'], 'at': made['started'],
                             'passed': made['conclusion'] == 'success', 'seconds': made['seconds']})
    newest = lambda items: sorted(items, key=lambda item: item['at'], reverse=True)  # noqa: E731
    return {'merges': newest({'pr': pull['number'], 'at': pull['merged_at']} for pull in closed if pull.get('merged_at')),
            'queue': newest(queue), 'verdicts': newest(verdicts)}


def read_slo(root):
    path = Path(root) / SLO_FILE
    return json.loads(path.read_text()) if path.exists() else None


def slo_refresh(root, now=None, reader=None, max_merges=None, run=subprocess.run):
    """Rebuilds the SLO snapshot from GitHub when it is missing, older than REFRESH_DAYS, or trailing main by at least
    medir.snapshot_max_merges merges and the API answers; the snapshot (new or kept) or None."""
    now = now or datetime.now(timezone.utc)
    recorded = read_slo(root)
    if not stale(root, recorded, now, max_merges=max_merges, run=run):
        return recorded
    found = (reader or slo_fetch)()
    return slo_write(root, found, now) if found else recorded


def slo_write(root, found, now):
    made = {'source': "GitHub's pull requests, their timelines and the tower/gate check runs of their commits",
            'at': now.strftime('%Y-%m-%dT%H:%M:%SZ'), **found}
    target = Path(root) / SLO_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(made, indent=1) + '\n')
    return made


VERDICTS_FILE = 'config/validation/verdicts.json'  # the full-suite's verdicts on main (not a VAL-*.json)
VERDICTS_CHECK = 'full-suite'  # .github/workflows/full-suite.yml's job: every script test on each merge into main
VERDICTS_MERGES = 40  # main's last merges whose full-suite run is read: how far back a green run is looked for
WEB_CHECK = 'web'  # .github/workflows/web.yml's job: apps/web unit & integration tests on PRs and merge queue
WEB_PATH = 'apps/web'  # path that web.yml judges when changed


def _completed_check(checks, name):
    """The newest completed, not cancelled/skipped check run of `name`, else None."""
    done = sorted((check for check in checks if check.get('name') == name
                   and check.get('status') == 'completed' and check.get('completed_at')
                   and check.get('conclusion') not in ('cancelled', 'skipped')), key=lambda check: check['completed_at'])
    return done[-1] if done else None


def web_merges(root, count, run=subprocess.run):
    """[(merge_sha, pr_head_or_none)] of main's last `count` first-parent merges that touched apps/web."""
    for ref in ('origin/main', 'HEAD'):
        done = run(['git', 'log', '--first-parent', '--merges', f'-n{count}', '--format=%H %P', ref, '--', WEB_PATH],
                   cwd=root, capture_output=True, text=True)
        if done.returncode == 0:
            found = []
            for line in done.stdout.splitlines():
                sha, *parents = line.split()
                found.append((sha, parents[1] if len(parents) > 1 else None))
            return found
    return []


def web_verdicts_fetch(root, repo=None, api=None, run=subprocess.run):
    """[{sha, id, conclusion, completed}] of the newest completed `web` check run on each of main's last merges
    that touched apps/web (checking the merge commit first, else the PR head). Only merges touching apps/web count,
    because web.yml skips pnpm test when apps/web is unchanged; None offline or when the API refuses."""
    if os.environ.get('TOWER_OFFLINE'):
        return None
    if api is None:
        import verify_commit  # the gate's github adapter: tower/gate's own reads of GitHub's REST API
        api = lambda path: verify_commit.gh_json(verify_commit.run, path)  # noqa: E731
    repo = repo or repository()
    pairs = web_merges(root, VERDICTS_MERGES, run)
    if not pairs:
        return []
    found = []
    try:
        for merge_sha, pr_head in pairs:
            picked, queried = None, merge_sha
            for candidate in (merge_sha, *([pr_head] if pr_head else [])):
                answer = api(f'repos/{repo}/commits/{candidate}/check-runs?check_name={WEB_CHECK}&per_page=100')
                picked = _completed_check(answer.get('check_runs', []), WEB_CHECK)
                if picked is not None:
                    queried = candidate
                    break
            if picked is not None:
                entry = {'sha': merge_sha, 'id': picked['id'], 'conclusion': picked.get('conclusion', ''),
                         'completed': picked['completed_at']}
                if queried != merge_sha:
                    entry['check_sha'] = queried
                found.append(entry)
    except (OSError, RuntimeError, ValueError):
        return None
    return found


def verdicts_fetch(root, repo=None, api=None, run=subprocess.run):
    """[{sha, id, conclusion, completed}] the newest completed full-suite check run of each of main's last merges,
    newest merge first (a cancelled or skipped run was superseded, not judged); None offline or when the API refuses.
    The suite runs on the merge commit itself (on: push to main), so only the merge commits are read."""
    if os.environ.get('TOWER_OFFLINE'):
        return None
    if api is None:
        import verify_commit  # the gate's github adapter: tower/gate's own reads of GitHub's REST API
        api = lambda path: verify_commit.gh_json(verify_commit.run, path)  # noqa: E731
    from concurrent.futures import ThreadPoolExecutor
    repo = repo or repository()
    shas = [sha for sha, event in merges(root, VERDICTS_MERGES, run) if event == 'merge_group']
    try:
        with ThreadPoolExecutor(SLO_WORKERS) as pool:
            answers = list(pool.map(lambda sha: api(f'repos/{repo}/commits/{sha}/check-runs?check_name={VERDICTS_CHECK}'
                                                    '&per_page=100'), shas))
    except (OSError, RuntimeError, ValueError):
        return None
    found = []
    for sha, answer in zip(shas, answers):
        last = _completed_check(answer.get('check_runs', []), VERDICTS_CHECK)
        if last is not None:
            found.append({'sha': sha, 'id': last['id'], 'conclusion': last.get('conclusion', ''),
                          'completed': last['completed_at']})
    return found


def read_verdicts(root):
    path = Path(root) / VERDICTS_FILE
    return json.loads(path.read_text()) if path.exists() else None


def verdicts_write(root, found, now, web=None):
    made = {'source': f"GitHub check runs {VERDICTS_CHECK} of main's last merges", 'check': VERDICTS_CHECK,
            'at': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'runs': found,
            **({'web_check': WEB_CHECK, 'web_runs': web} if web is not None else {})}
    target = Path(root) / VERDICTS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(made, indent=1) + '\n')
    return made


def verdicts_refresh(root, now=None, reader=None, web_reader=None, max_merges=None, run=subprocess.run):
    """Rebuilds the verdicts snapshot from GitHub when it is missing, older than REFRESH_DAYS, or trailing main by at
    least medir.snapshot_max_merges merges and the API answers; the snapshot (new or kept) or None. `reader(root)`
    answers the full-suite runs; `web_reader(root)` answers `web`."""
    now = now or datetime.now(timezone.utc)
    recorded = read_verdicts(root)
    if not stale(root, recorded, now, max_merges=max_merges, run=run):
        return recorded
    found = (reader or verdicts_fetch)(root)
    if not found:
        return recorded
    web = (web_reader or web_verdicts_fetch)(root) if (reader is None or web_reader is not None) else None
    return verdicts_write(root, found, now, web=web)


def slo_series(recorded):
    """The snapshot as the series slo.evaluate_series folds (the shape slo.fold makes from the event log)."""
    def series(items, label=lambda item: f'PR #{item["pr"]}', **fields):
        return sorted(({'at': stamp(item['at']), 'event_id': label(item),
                        **{key: item[name] for key, name in fields.items()}} for item in items),
                      key=lambda item: item['at'])
    tier1 = series(recorded.get('verdicts', []), lambda item: f'check run {item["id"]}', value='seconds', passed='passed')
    queue, merges = series(recorded.get('queue', []), value='seconds'), series(recorded.get('merges', []))
    every = sorted(tier1 + queue + merges, key=lambda item: item['at'])
    return {'tier1': tier1, 'queue': queue, 'merges': merges,
            'span': (every[0]['at'], every[-1]['at'], every[-1]['event_id']) if every else None}


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/runs', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    recorded = commands.add_parser('record', help='write the snapshot of a workflow from the API answer on stdin')
    recorded.add_argument('workflow')
    again = commands.add_parser('refresh', help="rebuild the snapshot from GitHub's checks of main's last merges")
    again.add_argument('workflow', choices=sorted(CHECKS))
    commands.add_parser('refresh-slo', help="rebuild the SLOs' samples from GitHub's pull requests and check runs")
    commands.add_parser('refresh-verdicts', help="rebuild the full-suite's verdicts from GitHub's check runs of main")
    args = parser.parse_args(argv)
    if args.command == 'refresh-verdicts':
        found = verdicts_fetch(root)
        if not found:
            print('runs: no full-suite verdicts read (offline, gh missing or the API refused); snapshot kept', file=sys.stderr)
            return 2
        web = web_verdicts_fetch(root)
        made = verdicts_write(root, found, datetime.now(timezone.utc), web=web)
        web_note = f", {len(made['web_runs'])} web verdict(s)" if 'web_runs' in made else ''
        print(f"runs: {len(made['runs'])} full-suite verdict(s){web_note} at {made['at']} -> {VERDICTS_FILE}")
        return 0
    if args.command == 'refresh-slo':
        found = slo_fetch()
        if not found:
            print('runs: no SLO samples read (offline, gh missing or the API refused); snapshot kept', file=sys.stderr)
            return 2
        made = slo_write(root, found, datetime.now(timezone.utc))
        print(f"runs: {len(made['merges'])} merge(s), {len(made['queue'])} queue time(s), "
              f"{len(made['verdicts'])} gate verdict(s) at {made['at']} -> {SLO_FILE}")
        return 0
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
