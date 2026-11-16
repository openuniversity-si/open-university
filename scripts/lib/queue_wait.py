"""QUEUE-REARM (the Torre, 16/11/2026): how long a pull request with auto-merge on waits, after `tower/gate` turns
green on its head, before GitHub adds it to the merge queue of `main`, and whether anyone turned auto-merge off and on
in that wait.

    scripts/queue-wait [--repo owner/name] <pr>...
    scripts/queue-wait [--repo owner/name] --last N
    scripts/queue-wait [--repo owner/name] --segments <pr>... | --last N

One line per pull request: its head, the gate's first green on that head, the moment auto-merge counted from (the green,
or a later enabling), the entry into the queue, the wait in seconds, and `rearmed` when auto-merge was turned off between
the green and the entry. Read from the pull request's timeline and the head's check runs (the issues and checks APIs,
through the GitHub adapter, scripts/lib/source_remote.py); a pull request that never reached the queue says so. Standard library only.

QUEUE-RUN (the Torre, 16/11/2026): `--segments` splits a merged pull request's time in the queue, from its last entry
to its merge, into: `dispatch`, the entry to the creation of the check suite of tower/gate on the queue's commit (the
pull request's merge commit, since the queue merges with a merge commit and fast-forwards main to it); `pickup`, that
creation to the job's start on a runner; `gate`, the job's run; and `land`, its green to the merge. Then the p50 and the
max of each segment over the pull requests read.
"""
import argparse
import re
import subprocess
import sys
from datetime import datetime

import source_remote

CHECK = 'tower/gate'


def at(stamp):
    return datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')


def wait_of(timeline, runs):
    """The wait of one pull request: `timeline` is its issue timeline's events, `runs` the check runs of its head."""
    greens = sorted(r['completed_at'] for r in runs
                    if r.get('name') == CHECK and r.get('conclusion') == 'success' and r.get('completed_at'))
    out = {'green': greens[0] if greens else None, 'armed': None, 'queued': None, 'wait_s': None, 'rearmed': False}
    if not greens:
        return out
    green = at(greens[0])
    events = sorted((at(e['created_at']), e['event']) for e in timeline
                    if e.get('created_at') and e.get('event') in
                    ('auto_merge_enabled', 'auto_merge_disabled', 'added_to_merge_queue'))
    queued = next((t for t, kind in events if kind == 'added_to_merge_queue' and t >= green), None)
    if queued is None:
        return out
    enables = [t for t, kind in events if kind == 'auto_merge_enabled' and t <= queued]
    armed = max([green] + [t for t in enables if t > green]) if enables else green
    out['armed'] = armed.strftime('%Y-%m-%dT%H:%M:%SZ')
    out['queued'] = queued.strftime('%Y-%m-%dT%H:%M:%SZ')
    out['rearmed'] = any(kind == 'auto_merge_disabled' and green <= t <= queued for t, kind in events)
    start = green
    if not out['rearmed']:
        start = armed
    out['wait_s'] = int((queued - start).total_seconds())
    return out


SEGMENTS = ('dispatch', 'pickup', 'gate', 'land', 'total')


def segments_of(timeline, queue_runs, suite_created, merged_at):
    """The queue time of one merged pull request, in seconds per segment, or None without a green queue gate."""
    merged = at(merged_at)
    entries = [at(e['created_at']) for e in timeline
               if e.get('event') == 'added_to_merge_queue' and e.get('created_at') and at(e['created_at']) <= merged]
    gates = [r for r in queue_runs if r.get('name') == CHECK and r.get('conclusion') == 'success'
             and r.get('started_at') and r.get('completed_at')]
    if not entries or not gates or not suite_created:
        return None
    queued, gate, created = max(entries), max(gates, key=lambda r: r['completed_at']), at(suite_created)
    started, green = at(gate['started_at']), at(gate['completed_at'])
    span = {'dispatch': created - queued, 'pickup': started - created, 'gate': green - started,
            'land': merged - green, 'total': merged - queued}
    return {name: int(value.total_seconds()) for name, value in span.items()}


def p50(values):
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def summary(rows):
    """One line per segment: its p50 and max over the rows (the lower median of an even count)."""
    rows = [r for r in rows if r]
    if not rows:
        return ['no merged pull request with a green queue gate']
    return [f'{name} p50 {p50([r[name] for r in rows])} s max {max(r[name] for r in rows)} s (n {len(rows)})'
            for name in SEGMENTS]


def segment_line(number, row):
    if row is None:
        return f'#{number} no green {CHECK} on its queue commit'
    return f'#{number} ' + ' '.join(f'{name} {row[name]} s' for name in SEGMENTS)


def line(number, head, wait):
    if wait['green'] is None:
        return f'#{number} {head[:8]} no green {CHECK} on the head'
    if wait['queued'] is None:
        return f'#{number} {head[:8]} green {wait["green"]} never queued after it'
    tail = ' rearmed' if wait['rearmed'] else ''
    return (f'#{number} {head[:8]} green {wait["green"]} armed {wait["armed"]} queued {wait["queued"]} '
            f'wait {wait["wait_s"]} s{tail}')


def one(path):
    try:
        return source_remote.api(path)
    except RuntimeError as error:
        raise SystemExit(f'queue-wait: {error}')


def gh(path):
    """Every item of a paginated list (a check runs' page holds them under `check_runs`)."""
    try:
        pages = source_remote.api(path, paginate=True)
    except RuntimeError as error:
        raise SystemExit(f'queue-wait: {error}')
    if pages and isinstance(pages[0], dict):
        return [item for page in pages for item in page.get('check_runs', [])]
    return [item for page in pages for item in page]


def segments(repo, number):
    pull = one(f'repos/{repo}/pulls/{number}')
    if not pull.get('merged_at'):
        return None
    runs = gh(f'repos/{repo}/commits/{pull["merge_commit_sha"]}/check-runs?filter=all&per_page=100')
    gates = [r for r in runs if r.get('name') == CHECK and r.get('conclusion') == 'success']
    if not gates:
        return None
    suite = one(f'repos/{repo}/check-suites/{max(gates, key=lambda r: r["completed_at"])["check_suite"]["id"]}')
    return segments_of(gh(f'repos/{repo}/issues/{number}/timeline?per_page=100'), runs, suite.get('created_at'),
                       pull['merged_at'])


def own_repo():
    url = subprocess.run(['git', 'remote', 'get-url', 'origin'], capture_output=True, text=True).stdout.strip()
    found = re.search(r'([\w.-]+)/([\w.-]+?)(?:\.git)?/?$', url)
    if not found:
        raise SystemExit('queue-wait: no --repo and no owner/name in the origin remote')
    return f'{found.group(1)}/{found.group(2)}'


def main(argv=None):
    parser = argparse.ArgumentParser(prog='queue-wait', description=__doc__.split('\n\n')[0])
    parser.add_argument('--repo')
    parser.add_argument('--last', type=int)
    parser.add_argument('--segments', action='store_true')
    parser.add_argument('prs', nargs='*', type=int)
    args = parser.parse_args(argv)
    repo = args.repo or own_repo()
    numbers = list(args.prs)
    if args.last:
        merged = [p for p in gh(f'repos/{repo}/pulls?state=closed&sort=updated&direction=desc&per_page=100')
                  if p.get('merged_at')]
        merged.sort(key=lambda p: p['merged_at'], reverse=True)
        numbers += [p['number'] for p in merged[:args.last]]
    if not numbers:
        parser.error('name a pull request or --last N')
    if args.segments:
        rows = []
        for number in sorted(set(numbers)):
            rows.append(segments(repo, number))
            print(segment_line(number, rows[-1]))
        print('\n'.join(summary(rows)))
        return 0
    for number in sorted(set(numbers)):
        head = one(f'repos/{repo}/pulls/{number}')['head']['sha']
        wait = wait_of(gh(f'repos/{repo}/issues/{number}/timeline?per_page=100'),
                       gh(f'repos/{repo}/commits/{head}/check-runs?filter=all&per_page=100'))
        print(line(number, head, wait))
    return 0


if __name__ == '__main__':
    sys.exit(main())
