"""Close a delivered lane from its report (VAZÃO F69): `scripts/lane collect <report>`.

The report (a file, or - for stdin) names its PR (`PR #N`; --pr overrides). For a PR merged on the base, the merge
subject names the unit (deliver.UNIT); when the closed-rows record (deliver.QUEUE_CLOSED) does not hold the PR yet, the
diary note and the closed-row line are written by deliver.diary, the same call scripts/deliver makes after a merge (F60),
so a PR merged without scripts/deliver is closed the same way and one merged with it is never noted twice. Then the
quota ledger is refreshed (F59, fronts.refresh) and the PR's lane row is printed: tokens, wall time, tool calls, lock
wait. A PR not merged closes nothing (exit 1). No report or transcript text is printed.

Detached delivery (F87): the lane ends once the preflight of `scripts/deliver` has passed (the base is right, the head
fetched, the gate started) and does not wait for the merge. The merge, or the ejection, reaches the coordinator here: a
PR not merged says whether its delivery is still running or was ejected.

Then (F86) the brief of the next free queue row is printed, the one lane.brief() gives: the first row of the active
table that is not closed (no closed-rows record line, no delivering commit on the base), not in flight (no
`units/<fxx>` branch, local or on the remote, and no open PR naming it) and whose "Depois de" units are all merged.
`--no-next` skips it. The coordinator starts the next lane from this one call.

Its own module; `scripts/lane collect` (F68's scripts/lane) hands it its arguments.
"""
import argparse
import json
import re
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver  # noqa: E402
import fronts  # noqa: E402
import lane  # noqa: E402
import usage  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent


def reported_pr(text):
    """The first `PR #N` (or `PR N`) a report names, or None."""
    found = usage.REPORTED.search(text or '')
    return int(found.group(1)) if found else None


def closed(pr, path=None):
    """True when the closed-rows record already holds the PR (scripts/deliver noted it)."""
    return any(row.get('pr') == pr for row in fronts.jsonl(path or deliver.QUEUE_CLOSED))


def pr_state(pr, root=ROOT, run=subprocess.run):
    """'open' (the delivery is still gating or queued), 'closed' (ejected or abandoned) or None (unreadable)."""
    import config
    try:
        done = run([config.get('origin-client.cli'), 'pr', 'view', str(pr), '--json', 'state'], capture_output=True,
                   text=True, cwd=str(root))
        state = str(json.loads(done.stdout).get('state', '')).lower() if done.returncode == 0 else ''
    except (OSError, ValueError, AttributeError):
        return None
    return {'open': 'open', 'draft': 'open', 'closed': 'closed'}.get(state)


def collect(pr, merges, ledger, waits, root=ROOT, run=subprocess.run, out=print, record=None):
    """Close a merged PR: its diary note and closed row when not yet recorded, then its ledger line. Returns 0, or 1
    when the PR has not merged on the base."""
    if pr not in merges:
        state = pr_state(pr, root, run)
        said = {'open': 'its delivery has not ended (still gating or queued); collect again after it',
                'closed': 'it was ejected or closed without a merge; the lane that owns it fixes and delivers again'}
        out(f'collect: PR #{pr} has not merged on the base; nothing closed' + (f': {said[state]}' if state in said else ''))
        return 1
    sha = merges[pr][0]
    if closed(pr, record):
        out(f'collect: PR #{pr} ({sha[:12]}) already noted in the diary and recorded closed by scripts/deliver')
    elif not deliver.diary(pr, [f'Merge commit: {sha}'], root, run, out, closed=record):
        out(f'collect: PR #{pr} ({sha[:12]}) names no queue unit in its merge subject; no diary note or closed row')
    rows = [row for row in ledger if row.get('pr') == pr and row.get('role') == 'lane']
    if not rows:
        out(f'collect: no ledger row for PR #{pr} (its lane transcript is not in the subagents directory read)')
    for row in rows:
        tokens = row.get('tokens') or {}
        out(f"collect: {row.get('unit') or '-'} lane {row.get('dir') or '-'}, PR #{pr}: {tokens.get('weighted', 0)} weighted "
            f"tokens ({tokens.get('input', 0)} input, {tokens.get('cache_read', 0)} cache read, {tokens.get('cache_write', 0)} "
            f"cache write, {tokens.get('output', 0)} output), {row.get('wall_s', 0)} s, {row.get('tool_calls', 0)} tool calls, "
            f"{waits.get(pr, 0):.0f} s waiting for the box's lock")
    return 0


def in_flight(root=ROOT, run=subprocess.run):
    """The units a lane holds: a `units/<fxx>` branch (local or on the remote) or an open or draft PR whose title or head names
    it. A command that fails adds nothing."""
    import config
    remote, cli = config.get('push-guard.remote'), config.get('origin-client.cli')
    texts = []
    for argv in (['git', '-C', str(root), 'for-each-ref', '--format=%(refname)', 'refs/heads/units/'],
                 ['git', '-C', str(root), 'ls-remote', '--heads', remote, 'units/*'],
                 [cli, 'pr', 'list', '-s', 'open'],
                 [cli, 'pr', 'list', '-s', 'draft']):
        try:
            done = run(argv, capture_output=True, text=True, cwd=str(root))
        except OSError:
            continue
        if done.returncode == 0:
            texts.append(done.stdout)
    text = '\n'.join(texts)
    units = {u.upper() for u in re.findall(r'\bunits/(f\d+)(?![\w-])', text)}
    units |= set(re.findall(r'(?<![\w-])(F\d+):', text))
    return units


def next_free(root=ROOT, base=lane.BASE, record=None, flight=None, run=subprocess.run):
    """(unit, None) for the first free row of the active table, or (None, why) when there is none."""
    _, rows = lane.queue_rows((Path(root) / lane.QUEUE).read_text(encoding='utf-8'))
    done = {row.get('unit') for row in fronts.jsonl(record or deliver.QUEUE_CLOSED)}
    flight = in_flight(root, run) if flight is None else flight
    cache = {}

    def merged(unit):
        if unit not in cache:
            cache[unit] = unit in done or bool(lane.merged_commit(unit, root, base, run))
        return cache[unit]

    waiting = []
    for unit, row in rows.items():
        if unit in flight or merged(unit):
            continue
        deps = [u for u in lane.depends_on(row) if u != unit and not merged(u)]
        if deps:
            waiting.append(f'{unit} after {", ".join(deps)}')
            continue
        return unit, None
    return None, 'every open row is closed, in flight' + (f' or waiting ({"; ".join(waiting)})' if waiting else '')


def print_next(root=ROOT, base=lane.BASE, record=None, flight=None, session='<session>', run=subprocess.run, out=print):
    """Print the brief of the next free row (F86); a missing queue or contract is said, never raised."""
    try:
        unit, why = next_free(root, base, record, flight, run)
        if unit is None:
            out(f'collect: no free queue row: {why}')
            return None
        out(f'collect: next free row {unit}; its brief follows (scripts/lane worktree {unit} makes the worktree)')
        out(lane.brief(unit, root=Path(root), base=base, session=session, run=run).rstrip('\n'))
        return unit
    except (lane.BriefError, OSError) as exc:
        out(f'collect: no next brief: {exc}')
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/lane collect', description=__doc__.split('\n\n')[0])
    parser.add_argument('report', help="the lane's report: a file, or - for stdin")
    parser.add_argument('--pr', type=int, help='the PR, when the report does not name it first')
    parser.add_argument('--lanes', type=Path, metavar='DIR', help='the subagents directory (default: the newest under '
                        'flow.transcripts_glob)')
    parser.add_argument('--no-next', action='store_true', help='do not print the brief of the next free queue row')
    parser.add_argument('--session', default='<session>', help='the session URL the next brief names for the trailers')
    args = parser.parse_args(argv)
    text = sys.stdin.read() if args.report == '-' else Path(args.report).read_text()
    pr = args.pr or reported_pr(text)
    if pr is None:
        parser.error('the report names no PR (PR #N); pass --pr N')
    import config
    code = collect(pr, usage.merged(), fronts.refresh(args.lanes), fronts.lock_waits(fronts.jsonl(
        config.get('delivery.gate_lock_log'))))
    if not args.no_next:
        print_next(session=args.session)
    return code


if __name__ == '__main__':
    sys.exit(main())
