"""One line per fact of the lane (D-156): counted commits per hour, the train queue, the train process, the newest shadow gate.

`scripts/lane-status` reads local git for the rate (flow_metrics), `scripts/train queue` for the queue, the process list
for `train serve`, and `.gate/shadow` for the newest real-gate measurement. Nothing is written and nothing polls.
"""
import argparse
import json
import re
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import flow_metrics  # noqa: E402
import gate_shadow  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent


def rates(counts):
    """The counted commits of the newest hour and the mean per hour over `counts` (newest first); the mean is the pace."""
    return {'last_hour': counts[0] if counts else 0, 'mean': sum(counts) / len(counts) if counts else 0.0, 'hours': len(counts)}


def train_checkout(process_list):
    """The checkout the running `train.py serve` was started from (its shadow gate results are written there), or None."""
    found = re.search(r'(\S+)/scripts/lib/train\.py serve', process_list)
    return found.group(1) if found else None


def newest(*results):
    """The newest of several shadow results (each carries `at`, else the file time is unknown and the first wins)."""
    present = [item for item in results if item]
    return max(present, key=lambda item: item.get('at', 0)) if present else None


def serve_alive(process_list):
    """True when `ps -eo args` output holds a train serve (`scripts/train serve` runs as `train.py serve`)."""
    return any(('train serve' in line or 'train.py serve' in line) and 'grep' not in line for line in process_list.splitlines())


def guards_line(ratios):
    """The guard ratios of D-137, D-164 and D-243 over the commits of the last day, one line; a lane steers by the pace and
    reads this to see that the pace is not bought with split, tangled or prose commits."""
    names = ('split', 'tangled', 'docsonly', 'plan_linked')
    return 'guards (last 24 h): ' + ', '.join(f'{name} {ratios[name]:.3f}' for name in names if name in ratios)


def regime_line(bypass, paused):
    """The state of the regime of exception (D-151): bypass on, runner paused. A drift is named, because a lane that thinks
    the gate is green when it is not, or a paused runner that woke, loses time without a message (D-161)."""
    if bypass is not True:
        return f"regime: gate.bypass={bypass}, service.paused={paused} (DRIFT from the regime of exception, D-161)"
    if paused is False:
        return "regime: gate.bypass=True, service.paused=False (the runner resumed by Daniel's order, D-191)"
    return f"regime: gate.bypass={bypass}, service.paused={paused}" + ('' if paused is True else ' (DRIFT from the regime of exception, D-161)')


def lanes_line(by_lane):
    """Each lane's mean counted commits an hour over the hours it is given, one line: F1.3 runs on two lanes and one lane's dip
    must not hide behind the other's pace."""
    return 'lanes: ' + '; '.join(f"{lane} {rates(counts)['mean']:.1f}/h ({' '.join(str(count) for count in counts)})" for lane, counts in sorted(by_lane.items()))


def render(counts, queue_text, alive, shadow, behind=None, regime=None, guards=None, lanes=None):
    pace = rates(counts)
    lines = [f"rate: {pace['mean']:.1f} counted/hour over the last {pace['hours']} h (newest hour {pace['last_hour']}); "
             f"per hour: {' '.join(str(count) for count in counts)}",
             f"train: {'serve is running' if alive else 'NO train serve process'}; queue: {queue_text or 'unknown'}"]
    if shadow:
        age = '' if behind is None else f'; {behind} merge(s) behind the base tip'
        lines.append(f"base: real gate {'passed' if shadow['passed'] else 'FAILED (BASE BROKEN)'} on {shadow['sha']} in {shadow['wall_s']} s{age}")
    else:
        lines.append('base: no shadow gate result yet (scripts/gate-shadow run)')
    if regime:
        lines.append(regime)
    if guards:
        lines.append(guards)
    if lanes:
        lines.append(lanes)
    return '\n'.join(lines)


def regime(root):
    """The regime line from the shared store (config.shared, not this checkout's store); None when it cannot be read."""
    import config
    try:
        return regime_line(bool(config.shared('gate.bypass')), bool(config.shared('service.paused')))
    except Exception:  # noqa: BLE001 - an unreadable store is no line, never a crash of the status
        return None


def guards(merged):
    """The guards line over the merges of the last day (flow_metrics.measure on a filtered `merged`)."""
    now = time.time()
    recent = [row for row in merged if 0 <= now - row[1] < flow_metrics.DAY_S]
    if not recent:
        return None
    return guards_line(flow_metrics.report(flow_metrics.measure(ROOT, '', '', merged=recent))['guards'])


def recent_since(days=None, now=None):
    """The start of the day `days` days back (default: two), the earliest merge the status reads: the hourly pace and the guards of the
    last day need no history before it, and reading the whole history cost seconds on every call."""
    import datetime
    days = len(('today', 'yesterday')) if days is None else days
    moment = (now or datetime.datetime.now()) - datetime.timedelta(days=days)
    return moment.strftime('%Y-%m-%d 00:00')


def gather(root, hours, base):
    merged = flow_metrics.merged_envelopes(root, base, recent_since(), flow_metrics.ZONE)
    counts = flow_metrics.hourly(merged, time.time(), hours)
    queue = subprocess.run([str(Path(root) / 'scripts' / 'train'), 'queue'], capture_output=True, text=True)
    waiting = [line for line in queue.stdout.splitlines() if line.startswith('#')]
    queue_text = f'{len(waiting)} waiting' if queue.returncode == 0 else None
    process = subprocess.run(['ps', '-eo', 'args'], capture_output=True, text=True).stdout
    shadow = newest(gate_shadow.latest(root), gate_shadow.latest(train_checkout(process)) if train_checkout(process) else None)
    behind = None
    if shadow:
        done = subprocess.run(['git', '-C', str(root), 'rev-list', '--count', '--first-parent', f"{shadow['sha']}..{base}"], capture_output=True, text=True)
        behind = int(done.stdout) if done.returncode == 0 and done.stdout.strip() else None
    return counts, queue_text, serve_alive(process), shadow, behind, regime(root), guards(merged), lanes_line(flow_metrics.hourly_by_lane(merged, time.time(), hours))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/lane-status', description=__doc__.splitlines()[0])
    parser.add_argument('--hours', type=int, default=len(('h1', 'h2', 'h3')))
    parser.add_argument('--json', action='store_true', help='the same facts as one JSON object (for another lane or a script)')
    parser.add_argument('--base', default=flow_metrics.BASE if hasattr(flow_metrics, 'BASE') else 'origin/mod/roadmap-integration')
    args = parser.parse_args(argv)
    facts = gather(ROOT, args.hours, args.base)
    if args.json:
        counts, queue_text, alive, shadow, behind, regime_text, guards_text, lanes_text = facts
        print(json.dumps({'counted_per_hour': counts, 'pace': rates(counts), 'queue': queue_text, 'train_serve': alive,
                          'shadow': shadow, 'shadow_merges_behind': behind, 'regime': regime_text, 'guards': guards_text, 'lanes': lanes_text}, indent=1))
    else:
        print(render(*facts))
    return 0


if __name__ == '__main__':
    sys.exit(main())
