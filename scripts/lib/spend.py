"""The AWS spend as a validation source (D-331, PADRAO-DEV F6b/F8d): a snapshot of the month's unblended spend to date,
read by the aws-spend measure of scripts/model for VAL-aws-200. The engine has no AWS credential and the gate no network:
the deploy build (infra/aws/deploy.sh, AWS-SPEND) reads Cost Explorer at most once a UTC day into last-build.spend, the
port serves it in GET /v1/deploy/status, and this records it.

    scripts/deploy status --json | scripts/spend record    writes config/validation/spend/aws.json

The input is the port's status (`last_build.spend`), the last-build record itself (`spend`) or the reading alone
({day, from, usd}). Cost Explorer is US$ 0.01 a call: one a day is at most US$ 0.31 a month.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT = 'config/validation/spend/aws.json'
DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def reading(answer):
    """{day, from, usd} of an input, or None when it holds no valid reading."""
    if not isinstance(answer, dict):
        return None
    found = answer
    if isinstance(answer.get('last_build'), dict):
        found = answer['last_build'].get('spend')
    elif 'spend' in answer:
        found = answer['spend']
    if not isinstance(found, dict):
        return None
    day, start, usd = found.get('day'), found.get('from'), found.get('usd')
    if not (isinstance(day, str) and DAY.match(day) and isinstance(start, str) and DAY.match(start)
            and start <= day and start[:len('2026-01')] == day[:len('2026-01')] and isinstance(usd, (int, float)) and usd >= 0):
        return None
    return {'day': day, 'from': start, 'usd': float(f'{usd:.2f}')}


def snapshot(found, now=None):
    return {'source': 'AWS Cost Explorer GetCostAndUsage (UnblendedCost, month to date), read by the deploy build',
            'at': now or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'), **found}


def read(root):
    path = Path(root) / SNAPSHOT
    return json.loads(path.read_text()) if path.exists() else None


def main(argv=None, root=ROOT, stdin=None):
    parser = argparse.ArgumentParser(prog='scripts/spend', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('record', help='write the snapshot from the port status (or last-build) on stdin')
    parser.parse_args(argv)
    try:
        found = reading(json.load(stdin or sys.stdin))
    except ValueError as error:
        print(f'spend: the input is not JSON ({error})', file=sys.stderr)
        return 1
    if not found:
        print('spend: the input holds no spend reading (no deploy build has read Cost Explorer yet)', file=sys.stderr)
        return 1
    target = Path(root) / SNAPSHOT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot(found), indent=1) + '\n')
    print(f'spend: US$ {found["usd"]:.2f} from {found["from"]} to {found["day"]} -> {SNAPSHOT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
