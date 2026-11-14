"""The commit rate of the last 60 minutes, per second, minute, hour and day (D-137, D-201).

Read only: the same merged commits and the same counting rule as scripts/flow-metrics (flow_metrics.rolling), over a window of one
hour. A rate is the window's count scaled to the unit: 60 minutes is one hour, so the hour rate is the count itself.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow_metrics  # noqa: E402

WINDOW_S = flow_metrics.HOUR_S  # the last 60 minutes
SECOND_S = timedelta(seconds=1).total_seconds()
MINUTE_S = timedelta(minutes=1).total_seconds()
SINCE = '3 hours ago'  # git's own date syntax; the merges older than the window are read and ignored


def rates(counted, window_s=WINDOW_S):
    """The counted commits of the window, and the rate of each unit: count times the unit over the window."""
    return {
        'counted': counted,
        'per_second': counted * SECOND_S / window_s,
        'per_minute': counted * MINUTE_S / window_s,
        'per_hour': counted * flow_metrics.HOUR_S / window_s,
        'per_day': counted * flow_metrics.DAY_S / window_s,
    }


def last_hour(root=ROOT, base='origin/mod/roadmap-integration', now=None):
    """The rates over the last 60 minutes, and the raw count of the same window (for the difference the rule makes)."""
    now = now if now is not None else time.time()
    merged = flow_metrics.merged_envelopes(root, base, SINCE, flow_metrics.ZONE)
    found = flow_metrics.rolling(merged, now, WINDOW_S)
    return dict(rates(found['counted']), raw=found['raw'])


def render(data, now=None):
    stamp = datetime.fromtimestamp(now if now is not None else time.time(), timezone.utc).strftime('%H:%M UTC')
    return '\n'.join([
        f'commit rate, last 60 minutes, at {stamp}',
        f"counted commits: {data['counted']} (raw {data['raw']})",
        f"per second: {data['per_second']:.4f}",
        f"per minute: {data['per_minute']:.2f}",
        f"per hour:   {data['per_hour']:.1f}",
        f"per day:    {data['per_day']:.0f}",
    ])


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/commit-rate', description=__doc__.split('\n\n')[0])
    parser.add_argument('--base', default='origin/mod/roadmap-integration')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    now = time.time()
    data = last_hour(root, args.base, now)
    if args.json:
        print(json.dumps(data, indent=1))
    else:
        print(render(data, now))
    return 0


if __name__ == '__main__':
    sys.exit(main())
