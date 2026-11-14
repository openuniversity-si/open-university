"""The flow check in one report (D-197): the clock in BRT, the lanes' pace, the train, the base's last real gate, the program's
units and the next free decision number. It replaces the five status commands a session ran by hand before each
check-in: `scripts/flow-metrics --cycles`, `scripts/lane-status`, `scripts/service health`, `scripts/gate-shadow latest` and
`scripts/coordinator status`. `--unit ID` prints one unit's status.

Read only: nothing is written, nothing is pushed, no GitHub write. Each part is one existing command; a part that fails is
printed as failed, and the others still run.
"""
import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import decision_next  # noqa: E402
import forge_events  # noqa: E402

def brt(now=None):
    """The clock in BRT (the same reading as decision-next's claim stamp, D-194)."""
    return (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/Sao_Paulo')).strftime('%d/%m %H:%M BRT')


PARTS = (
    ('flow metrics', ['scripts/flow-metrics', '--cycles']),
    ('lanes', ['scripts/lane-status']),
    ('service', ['scripts/service', 'health']),
    ('base gate', ['scripts/gate-shadow', 'latest']),
)
PROGRAM = 'fluxo-amplo'


def run(root, args):
    """(ok, text) of one command, all of its output; a missing command is a failure, not a crash."""
    try:
        done = subprocess.run([str(Path(root) / args[0]), *args[1:]], cwd=root, capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as error:
        return False, f'could not run: {error}'
    return done.returncode == 0, (done.stdout + done.stderr).strip()


def unit_lines(text, unit_id):
    """The coordinator's status lines that name the unit: its stage, folded from the forge's events (D-206 (c))."""
    return [line.strip() for line in text.splitlines() if f' {unit_id} ' in f' {line} ']


def unit_report(root, program, unit, runner):
    ok, text = runner(root, ['scripts/coordinator', 'status', program])
    lines = unit_lines(text, unit) if ok else []
    return f"unit {unit} of {program}" + ('' if lines else ' (no status)') + '\n' + '\n'.join(lines)


def known_lanes(root):
    """The lanes the guide names: the numbered rows of its lane tables (docs/process/lane.md)."""
    text = (Path(root) / 'docs' / 'process' / 'lane.md').read_text()
    return sorted({int(m.group(1)) for m in re.finditer(r'^\| (\d+) \|', text, re.M)})


def branch_lane(ref):
    """The lane a branch belongs to: `-lane<N>-`, `-lanes<N>-` or the unit's `-m<N>-` (M<N> is lane N, D-209); None if none."""
    m = re.search(r'-(?:lanes?|m)(\d+)(?:-|$)', ref)
    return int(m.group(1)) if m else None


def merged_lanes(subjects):
    """The lanes with a merged pull request, from the base's merge subjects (`Merge pull request #N from owner/branch`)."""
    lanes = set()
    for subject in subjects:
        m = re.match(r'Merge pull request #\d+ from [^/\s]+/(\S+)$', subject)
        if m and branch_lane(m.group(1)) is not None:
            lanes.add(branch_lane(m.group(1)))
    return lanes


def review_ready(pulls):
    """lane -> number of its open pull request (the lane's work waits for review)."""
    open_by_lane = {}
    for pull in pulls:
        lane = branch_lane(pull.get('head_ref', ''))
        if lane is not None:
            open_by_lane.setdefault(lane, pull['number'])
    return open_by_lane


def merged_subjects(root, hours):
    """The base's merge subjects of the last `hours` hours (git reads only); None if git cannot say."""
    done = subprocess.run(['git', '-C', str(root), 'log', '--merges', '--first-parent', f'--since={hours} hours ago',
                           '--format=%s', 'origin/mod/roadmap-integration'], capture_output=True, text=True)
    return done.stdout.splitlines() if done.returncode == 0 else None


def open_pulls(root):
    """The open pull requests, in one paged list, through the configured forge port (D-069 item 7)."""
    import forge_events
    from decision_next import _repo
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.SystemClock(),
                                    'flow-check', 'flow-check', consumer='scripts/lib/flow_check.py')
    return port.open_pulls(_repo(root))


def idle_report(root=ROOT, program=PROGRAM, runner=run, hours=1, subjects=None, pulls=None):
    """The lanes with no merged pull request in the last `hours` hours; an idle lane with an open pull request is in review
    ready. Then the plan's next launches (coordinator next)."""
    if subjects is None:
        subjects = merged_subjects(root, hours)
    if pulls is None:
        try:
            pulls = open_pulls(root)
        except forge_events.ForgeCompatibilityError:
            raise
        except Exception:  # IO failure may omit review state; required capability may not
            pulls = None
    active = merged_lanes(subjects or [])
    waiting = review_ready(pulls or [])
    idle = [n for n in known_lanes(root) if n not in active]
    marks = [f'lane {n}' + (f' (review ready, PR #{waiting[n]})' if n in waiting else '') for n in idle]
    if subjects is None:
        marks.insert(0, 'merge history unknown')
    ok, nxt = runner(root, ['scripts/coordinator', 'next', program])
    launches = []
    for line in (nxt.splitlines() if ok else []):
        try:
            step = json.loads(line)
        except ValueError:
            continue
        if step.get('action') == 'launch':
            launches.append(step['unit'])
    lines = [f'idle lanes in the last {hours} h: ' + (', '.join(marks) or 'none')]
    lines.append('next launches: ' + (', '.join(launches) or ('none' if ok else 'unknown (coordinator next failed)')))
    return '\n'.join(lines)


NO_TRAIN = 'NO train serve process'
MINUTE_S = timedelta(minutes=1).total_seconds()
QUEUE_ROW = re.compile(r'^#(?P<pr>\d+) \S+ (?P<state>\S+) (?P<at>\d{4}-\S+Z)$')


def queue_rows(text, now):
    """(PR number, state, age in seconds) of each row of `scripts/train queue`."""
    rows = []
    for line in text.splitlines():
        m = QUEUE_ROW.match(line.strip())
        if m:
            at = datetime.fromisoformat(m.group('at').replace('Z', '+00:00'))
            rows.append((int(m.group('pr')), m.group('state'), (now - at).total_seconds()))
    return rows


def last_merge_time(root):
    """Unix time of the base's last merge commit, from git (None if git cannot say)."""
    done = subprocess.run(['git', '-C', str(root), 'log', '-1', '--merges', '--first-parent', '--format=%ct',
                           'origin/mod/roadmap-integration'], capture_output=True, text=True)
    return int(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None


def train_report(root=ROOT, runner=run, now=None, merged_at=None):
    """The train in one part: is its serve process alive, how long since the last merge, and which woken PRs wait.
    Red (the first line) when a waiting PR, or the silence after a merge, is older than RED_AFTER_S, or the process is down
    while PRs wait. The reason of a waiting PR comes with lane 6's train report; it is not printed yet."""
    now = now or datetime.now(timezone.utc)
    red_after_s = config.get('flow.red_after_s', root)
    ok, status = runner(root, ['scripts/lane-status'])
    alive = ok and NO_TRAIN not in status
    ok, queue = runner(root, ['scripts/train', 'queue'])
    rows = queue_rows(queue, now) if ok else []
    red = []
    if not alive and rows:
        red.append(f'the train serve process is not running and {len(rows)} PR(s) wait')
    for pr, state, age in rows:
        if age > red_after_s:
            red.append(f'PR #{pr} {state} for {int(age // MINUTE_S)} min')
    if rows and merged_at is not None and now.timestamp() - merged_at > red_after_s:
        red.append(f'no merge for {int((now.timestamp() - merged_at) // MINUTE_S)} min while PRs wait')
    lines = [('RED: ' + '; '.join(red)) if red else 'ok']
    lines.append('train serve process: ' + ('running' if alive else 'NOT running'))
    lines.append('last merge: ' + (f'{int((now.timestamp() - merged_at) // MINUTE_S)} min ago' if merged_at else 'unknown'))
    lines.append(f'woken PRs waiting: {len(rows)}' + ''.join(f'; #{pr} {state} {int(age // MINUTE_S)} min' for pr, state, age in rows))
    return '\n'.join(lines)


def report(root=ROOT, program=PROGRAM, runner=run, now=None, unit=None):
    """The report as text. `runner` is injectable for the tests. With `unit`, only that unit's status."""
    if unit is not None:
        return unit_report(root, program, unit, runner)
    lines = [f"flow check, {brt(now)}"]
    for name, args in PARTS:
        ok, text = runner(root, args)
        lines.append(f'## {name}' + ('' if ok else ' (failed)'))
        lines.append(text or '(no output)')
    lines.append('## train')
    lines.append(train_report(root, runner, now, last_merge_time(root)))
    ok, text = runner(root, ['scripts/coordinator', 'status', program])
    lines.append(f'## units of {program}' + ('' if ok else ' (failed)'))
    lines.append(text or '(no output)')
    lines.append(f'## next free decision number: D-{decision_next.free_number(decision_next.base_text(root), decision_next.open_pulls(decision_next._repo(root)))}')
    return '\n'.join(lines)


def main(argv=None, root=ROOT):
    parser = argparse.ArgumentParser(prog='scripts/flow-check', description=__doc__.split('\n\n')[0])
    parser.add_argument('--program', default=PROGRAM)
    parser.add_argument('--unit', help='only this unit: its stage in the program')
    parser.add_argument('--idle', action='store_true', help='the lanes idle in the last hour and the next launches')
    args = parser.parse_args(argv)
    print(idle_report(root, args.program) if args.idle else report(root, args.program, unit=args.unit))
    return 0


if __name__ == '__main__':
    sys.exit(main())
