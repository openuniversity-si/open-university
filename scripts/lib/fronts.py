"""The fronts in flight (VAZÃO F69): `scripts/fronts status`.

A front is a lane of the current coordinator whose PR has not merged: its unit, worktree, PR, weighted tokens, wall time,
the seconds its PR waited for the box's lock (delivery.gate_lock_log) and the seconds it logged as lost
(flow.frictions_log). The lanes come from the quota ledger (flow.lanes_ledger, F59), refreshed first from the newest
subagents directory (flow.transcripts_glob) or the one --lanes names. Read only, except the ledger refresh; no transcript
text is printed.
"""
import argparse
from collections import Counter
import glob
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import usage  # noqa: E402


def newest_transcripts(pattern):
    """The most recently changed directory the pattern matches, or None."""
    found = [Path(path) for path in glob.glob(os.path.expanduser(pattern)) if Path(path).is_dir()]
    return max(found, key=lambda path: path.stat().st_mtime) if found else None


def jsonl(path):
    """The JSON objects of a JSON-lines file; a missing file is empty and a broken line is skipped."""
    path = Path(os.path.expanduser(str(path)))
    rows = []
    for line in path.read_text().splitlines() if path.exists() else []:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def weights():
    import config
    return {'input': config.get('flow.token_weight_input'), 'cache_read': config.get('flow.token_weight_cache_read'),
            'cache_write': config.get('flow.token_weight_cache_write'), 'output': config.get('flow.token_weight_output')}


def refresh(folder=None):
    """Rewrite the ledger rows of a subagents directory (default: the newest under flow.transcripts_glob) and return
    every ledger row. With no directory found, the ledger is read as it is."""
    import config
    folder = Path(folder) if folder else newest_transcripts(config.get('flow.transcripts_glob'))
    ledger = config.get('flow.lanes_ledger')
    if folder and folder.is_dir():
        usage.write_ledger(usage.lanes(folder, weights(), usage.merged()), ledger)
    return jsonl(ledger)


def lock_waits(rows):
    """{pr: seconds waited for the box's lock}, summed over the lock log's rows of each PR."""
    waits = Counter()
    for row in rows:
        if isinstance(row.get('pr'), int):
            waits[row['pr']] += float(row.get('waited_s') or 0)
    return waits


def lost(rows):
    """{lane: seconds logged as lost} from the friction log."""
    seconds = Counter()
    for row in rows:
        if row.get('lane'):
            seconds[str(row['lane'])] += float(row.get('seconds') or 0)
    return seconds


def status(ledger, waits, frictions):
    """The fronts in flight: the lane rows of the newest session in the ledger whose PR has not merged, newest first."""
    lanes = [row for row in ledger if row.get('role') == 'lane']
    if not lanes:
        return []
    current = max(lanes, key=lambda row: row.get('end') or '').get('session')
    fronts = []
    for row in sorted(lanes, key=lambda row: row.get('end') or '', reverse=True):
        if row.get('session') != current or row.get('merged'):
            continue
        fronts.append({'unit': row.get('unit'), 'dir': row.get('dir'), 'pr': row.get('pr'),
                       'weighted': (row.get('tokens') or {}).get('weighted', 0), 'wall_s': row.get('wall_s', 0),
                       'tool_calls': row.get('tool_calls', 0), 'lock_wait_s': waits.get(row.get('pr'), 0),
                       'lost_s': frictions.get(row.get('dir') or '', 0)})
    return fronts


def render(fronts):
    if not fronts:
        return 'fronts in flight: none (every lane of the current coordinator has merged its PR)'
    lines = [f'fronts in flight: {len(fronts)}', 'unit  dir     pr    weighted  wall_s  tools  lock_wait_s  lost_s']
    for row in fronts:
        lines.append(f"{row['unit'] or '-':<4}  {row['dir'] or '-':<6}  {str(row['pr'] or '-'):<4}  {row['weighted']:>8}  "
                     f"{row['wall_s']:>6}  {row['tool_calls']:>5}  {row['lock_wait_s']:>11.0f}  {row['lost_s']:>6.0f}")
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/fronts', description=__doc__.split('\n\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    shown = sub.add_parser('status', help='the lanes in flight with their unit, PR, tokens, lock wait and lost time')
    shown.add_argument('--lanes', type=Path, metavar='DIR', help='the subagents directory (default: the newest under '
                       'flow.transcripts_glob)')
    shown.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    import config
    fronts = status(refresh(args.lanes), lock_waits(jsonl(config.get('delivery.gate_lock_log'))),
                    lost(jsonl(config.get('flow.frictions_log'))))
    print(json.dumps(fronts, indent=1) if args.json else render(fronts))
    return 0


if __name__ == '__main__':
    sys.exit(main())
