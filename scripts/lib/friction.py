"""One lane friction per line, clock ts and a closed cause (VAZÃO F85): `scripts/friction`.

`scripts/friction <cause> <seconds> <what>` appends one JSON line to ~/.cache/the-tower/frictions.jsonl:
`{"ts","lane","cause","what","seconds"}`. The ts is the real clock (UTC), never typed by hand (03/11: 4 of 44 lines
carried a ts in the future); the lane comes from the worktree (branch `units/<fxx>`, else the worktree directory
name); the cause is one of CAUSES. `scripts/friction --summary [--hours N]` sums the seconds by cause per UTC hour,
newest first; a line written before F85 has no cause and counts as `unknown`.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

LOG = Path.home() / '.cache' / 'the-tower' / 'frictions.jsonl'
CAUSES = ('env', 'base-red', 'conflict', 'hang', 'tooling', 'rule')
UNKNOWN = 'unknown'


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def stamp(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def _git(cwd, *args):
    try:
        done = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ''
    return done.stdout.strip() if done.returncode == 0 else ''


def lane_of(cwd=None):
    """The lane of the worktree at cwd: `units/<fxx>` gives `<fxx>`, else the worktree directory name."""
    branch = _git(cwd, 'rev-parse', '--abbrev-ref', 'HEAD')
    if branch.startswith('units/') and branch != 'units/':
        return branch[len('units/'):]
    top = _git(cwd, 'rev-parse', '--show-toplevel')
    return Path(top).name if top else Path(cwd or Path.cwd()).resolve().name


def entry(cause, seconds, what, lane, moment):
    if cause not in CAUSES:
        raise ValueError(f'cause {cause!r} is not one of {", ".join(CAUSES)}')
    if seconds <= 0:
        raise ValueError('seconds must be positive')
    if not what.strip():
        raise ValueError('what is empty')
    return {'ts': stamp(moment), 'lane': lane, 'cause': cause, 'what': what.strip(), 'seconds': seconds}


def record(line, log=LOG):
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(line, ensure_ascii=False, separators=(',', ':')) + '\n')


def read(log=LOG):
    try:
        text = Path(log).read_text(encoding='utf-8')
    except FileNotFoundError:
        return []
    lines = []
    for raw in text.splitlines():
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if isinstance(item, dict):
            lines.append(item)
    return lines


def _moment(value):
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def summary(lines, hours, moment):
    """{hour: {cause: seconds}} for the last `hours` UTC hours up to moment, plus the count of future ts."""
    start = moment.replace(minute=0, second=0) - timedelta(hours=hours - 1)
    table, future = defaultdict(lambda: defaultdict(int)), 0
    for item in lines:
        when = _moment(item.get('ts'))
        try:
            seconds = int(item.get('seconds') or 0)
        except (TypeError, ValueError):
            seconds = 0
        if when is None:
            continue
        if when > moment:
            future += 1
            continue
        if when < start:
            continue
        cause = item.get('cause') if item.get('cause') in CAUSES else UNKNOWN
        table[stamp(when.replace(minute=0, second=0))][cause] += seconds
    return {hour: dict(causes) for hour, causes in sorted(table.items(), reverse=True)}, future


def render(table, future):
    columns = CAUSES + (UNKNOWN,)
    out = ['hour (UTC)            ' + ' '.join(f'{c:>8}' for c in columns) + '    total']
    for hour, causes in table.items():
        out.append(f'{hour:<22}' + ' '.join(f'{causes.get(c, 0):>8}' for c in columns)
                   + f' {sum(causes.values()):>8}')
    if future:
        out.append(f'{future} line(s) with a ts in the future, left out')
    return '\n'.join(out)


def main(argv=None, log=LOG, clock=now, cwd=None):
    parser = argparse.ArgumentParser(prog='scripts/friction', description=__doc__.splitlines()[0])
    parser.add_argument('cause', nargs='?', help='one of: ' + ', '.join(CAUSES))
    parser.add_argument('seconds', nargs='?', type=int, help='seconds lost')
    parser.add_argument('what', nargs='*', help='what happened')
    parser.add_argument('--lane', help='the lane (default: from the worktree)')
    parser.add_argument('--summary', action='store_true', help='seconds by cause per UTC hour, newest first')
    parser.add_argument('--hours', type=int, default=24, metavar='N', help='--summary window (default 24)')
    parser.add_argument('--json', action='store_true', help='--summary as JSON')
    args = parser.parse_args(argv)
    if args.summary:
        table, future = summary(read(log), max(args.hours, 1), clock())
        print(json.dumps({'hours': table, 'future': future}, indent=2) if args.json else render(table, future))
        return 0
    if args.cause is None or args.seconds is None or not args.what:
        parser.error('usage: scripts/friction <cause> <seconds> <what>, or --summary')
    try:
        line = entry(args.cause, args.seconds, ' '.join(args.what), args.lane or lane_of(cwd), clock())
    except ValueError as error:
        parser.error(str(error))
    record(line, log)
    print(json.dumps(line, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
