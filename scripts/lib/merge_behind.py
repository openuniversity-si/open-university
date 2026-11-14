"""The merge rule of merge-phase (GX-22, harvested from BD1 #667; D-070). The gate proof is for the exact head, so a
head that fell behind the base is re-gated when it is too far behind (merge.max_behind_base) or when the base's commits
since the merge-base touch a path the PR changed (merge.regate_on_overlap). The proof itself is read from the v4 event
log (GX-37): the gate.passed of the PR channel for the exact head, per gate plan, never a local `.pass` file.

python3 scripts/lib/merge_behind.py behind --pr N --sha HEAD --base-sha BASE --repo owner/repo
    exit 0 ok, 1 re-gate.
python3 scripts/lib/merge_behind.py evidence --pr N --sha HEAD --repo owner/repo
    one line per gate plan that passed on HEAD: `<plan> <event_id>`; exit 0 (an empty list is no proof), 1 log unreadable.
The standing of the head (behind_by, merge base) comes from the forge port's compare (scripts/lib/forge_events.py); the paths
each side changed since the merge base come from the local checkout, which must hold both shas.
"""
import argparse
from pathlib import Path
import subprocess
import sys

import config


def limit_line(behind_by, limit):
    """The verdict line every merge-rule reader prints (commit_check, merge-phase): the registry value next to the count."""
    return f'{behind_by} behind, limit {limit}'


def decide(behind_by, overlap_paths, max_behind, regate_on_overlap):
    """(ok, reason): a head not behind merges; overlapping changes or too many commits behind need a re-gate."""
    line = limit_line(behind_by, max_behind)
    if behind_by <= 0:
        return True, f'{line}: not behind the base'
    paths = sorted(overlap_paths)
    if regate_on_overlap and paths:
        room = config.get('merge.paths_shown')
        shown = ', '.join(paths[:room]) + (f', +{len(paths) - room} more' if len(paths) > room else '')
        return False, f're-gate: {line}, overlapping changes ({shown})'
    if behind_by > max_behind:
        return False, f're-gate: {line}'
    return True, f'{line}, no overlapping changes'


ROOT = Path(__file__).resolve().parent.parent.parent


def local_diff(root=ROOT):
    """`diff(a, b)`: the paths git changed between two commits of the checkout at `root`, or None when it lacks one."""
    def diff(old, new):
        done = subprocess.run(['git', '-C', str(root), 'diff', '--name-only', old, new], capture_output=True, text=True)
        return {line for line in done.stdout.splitlines() if line.strip()} if done.returncode == 0 else None
    return diff


def measure(port, repo, sha, base_sha, diff=None):
    """(behind_by, overlap_paths) of the head against the base tip: the port's compare of base_sha...sha, then the paths the
    head and the base each changed since their merge base (`diff(a, b)`, the local checkout by default).

    A side whose paths cannot be read cannot be proven disjoint: it raises, and the head is not merged."""
    standing = port.compare(repo, base_sha, sha)
    behind = standing.get('behind_by') or 0
    merge_base = standing.get('merge_base')
    if not behind or not merge_base:
        return behind, []
    diff = diff or local_diff()
    mine, theirs = diff(merge_base, sha), diff(merge_base, base_sha)
    if mine is None or theirs is None:
        raise RuntimeError(f'the checkout does not hold {merge_base}, {sha} and {base_sha}: the changed paths cannot be read')
    return behind, sorted(mine & theirs)


def forge(pr):
    """The forge port of the merge rule, on the PR's channel (the configured adapter, D-069 item 7)."""
    import forge_events
    return forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(), 'merge-rule',
                                    f'pr-{pr}', consumer='scripts/lib/merge_behind.py')


def evidence(events, pr, sha):
    """{plan: gate.passed event_id} for the exact head on the PR channel: the GX-37 replay, one entry per plan that passed."""
    import forge_events
    state = forge_events.replay(events)
    plans = state.get(pr, {}).get('gates', {}).get(sha, {})
    return {plan: event_id for plan in sorted(plans) if (event_id := forge_events.gate_evidence(state, pr, sha, plan))}


def read_log(repo, pr, port=None):
    """The PR channel of the configured forge_events adapter (the shared log, not this machine's records)."""
    return (port or forge(pr)).read(repo, pr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    behind_cmd = sub.add_parser('behind')
    proof = sub.add_parser('evidence')
    for command in (behind_cmd, proof):
        command.add_argument('--pr', type=int, required=True)
        command.add_argument('--sha', required=True)
        command.add_argument('--repo', required=True)
    behind_cmd.add_argument('--base-sha', required=True)
    args = parser.parse_args(argv)
    if args.command == 'evidence':
        try:
            found = evidence(read_log(args.repo, args.pr), args.pr, args.sha)
        except Exception as error:  # the port's own errors name the adapter; an unreadable log is no proof
            print(f'cannot read the event log of PR #{args.pr}: {error}')
            return 1
        for plan, event_id in found.items():
            print(f'{plan} {event_id}')
        return 0
    try:
        behind, overlap = measure(forge(args.pr), args.repo, args.sha, args.base_sha)
    except (RuntimeError, ValueError) as error:
        print(f'cannot measure how far PR #{args.pr} is behind its base: {error}')
        return 1
    ok, reason = decide(behind, overlap, config.get('merge.max_behind_base'), config.get('merge.regate_on_overlap'))
    print(reason)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
