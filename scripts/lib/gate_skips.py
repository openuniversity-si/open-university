"""GK1 (D-069 item 12): a stage skipped because a hard dependency failed leaves a record.

A stage that never ran used to look the same whether the plan did not include it or a guard skipped it. The guard writes
<stage>.skip.json (not .stage.json, which the status and failure readers treat as a stage that ran); gate_report.py lists
those apart from the stages absent from the plan.

  gate_skips.py record    --logs DIR --name STAGE --blocked-by STAGE
  gate_skips.py remaining --logs DIR --mode MODE --blocked-by STAGE   every expected stage with no result is skipped
"""
import argparse
import json
from pathlib import Path
import re
import sys


def slug(name):
    return re.sub(r'[^a-zA-Z0-9]', '_', name)


def record(logs, name, blocked_by):
    reason = f'skipped: {blocked_by} failed'
    (Path(logs) / f'{slug(name)}.skip.json').write_text(json.dumps({'name': name, 'blocked_by': blocked_by, 'reason': reason}))


def load(logs):
    skips = []
    for path in sorted(Path(logs).glob('*.skip.json')):
        try:
            skips.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return skips


def remaining(logs, mode, blocked_by):
    """Records a skip for each stage the mode expects that has neither run nor been skipped; returns their names."""
    from gate_report import expected_stages
    logs = Path(logs)
    names = []
    for name in expected_stages(mode, logs):
        if (logs / f'{slug(name)}.stage.json').is_file() or (logs / f'{slug(name)}.skip.json').is_file():
            continue
        record(logs, name, blocked_by)
        names.append(name)
    return names


def main(argv):
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('record', 'remaining'))
    parser.add_argument('--logs', required=True)
    parser.add_argument('--name')
    parser.add_argument('--mode')
    parser.add_argument('--blocked-by', required=True)
    args = parser.parse_args(argv)
    if args.command == 'record':
        record(args.logs, args.name, args.blocked_by)
    else:
        for name in remaining(args.logs, args.mode, args.blocked_by):
            print(f'SKIP {name} (skipped: {args.blocked_by} failed)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
