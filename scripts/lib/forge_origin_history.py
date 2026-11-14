"""Origin's push history, answered from git (ORIGIN-PUSH-HISTORY, plan R1-R3; D-300: no longer from the Worker).

Origin has no push-history route, and a change's versions (`origin pr view --change-version`) start when the change is
opened, after the lane's first pushes. The history comes from this clone's reflog of refs/remotes/<remote>/<branch>:
every lane worktree and deliver share one .git, and git records there each push of the branch (`update by push`, the
sha replaced and the push time). reflog_history turns those entries into ref.updated-shaped records and push_history
turns records into the port's shape: pure, no network, no clock, so the rule is tested without a forge.

An answer is given only when the reflog proves it covers every move of the branch on Origin:
- its first entry is the push that created the branch (it replaced 40 zeros),
- every entry is a push from this clone (a fetch that moved the ref is a move another clone pushed, uncounted), and
- its last entry is Origin's head of the branch now (`git ls-remote`): no push from elsewhere came after it.
Otherwise the operation refuses and says why, so silence never reads as "no push" (fail closed). A proven history
answers honestly, and an empty list then means no move of that kind happened.
"""
from datetime import datetime, timezone

PUSH = 'update by push'  # git's reflog message for a remote-tracking ref a push of this clone moved


class HistoryGap(RuntimeError):
    """The history cannot be proven for this branch. The message names why."""


def null(sha):
    """git's null sha (all zeros): the before of a creation, the after of a deletion."""
    return not sha.strip('0')


def moment(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def reflog_history(entries, ref, tip, ancestor, forced_only=False):
    """The port's pushes (or force_pushes) of `ref` from the reflog of its remote-tracking ref, newest first.

    entries: [(before, after, unix seconds, message)], oldest first (forge_git_ref.GitRefs.push_log); a before or
    after of zeros is the branch's creation or deletion, as git writes it.
    tip: Origin's sha of `ref` now, None when it does not exist. ancestor(a, b): True, False, or None when unknown.
    """
    if not entries:
        raise HistoryGap(f'this clone\'s reflog holds no record of {ref}: it cannot say whether the branch was pushed'
                         f'{" or force-pushed" if forced_only else ""} (it was pushed from another clone)')
    first, last = entries[0], entries[-1]
    before, _, seconds, _ = first
    if not null(before):
        raise HistoryGap(f'this clone\'s reflog of {ref} does not reach its creation (its earliest entry is at '
                         f'{moment(seconds)}): earlier moves are not in it, so the answer would be partial')
    foreign = next((entry for entry in entries if entry[-1] != PUSH), None)
    if foreign:
        _, _, seconds, message = foreign
        raise HistoryGap(f'{ref} moved at {moment(seconds)} by `{message}`, not by a push of this clone: '
                         'another clone pushed it, and its pushes cannot be counted from here')
    _, pushed, _, _ = last
    if tip != pushed:
        raise HistoryGap(f'Origin\'s head of {ref} is {tip or "absent"} but this clone last pushed {pushed}: '
                         'a push from another clone is not in its reflog')
    records = []
    for before, after, seconds, _ in entries:
        created, deleted = null(before), null(after)
        forced = False
        if not created and not deleted:
            known = ancestor(before, after)
            if known is None:
                raise HistoryGap(f'this clone lacks the commits of the move {before} -> {after} of {ref}: '
                                 'it cannot tell whether that push was forced')
            forced = not known
        records.append({'ref': ref, 'before': before, 'after': after, 'created': created, 'deleted': deleted,
                        'forced': forced, 'pushed_at': moment(seconds)})
    return push_history(records, ref, True, forced_only)


def push_history(records, ref, complete, forced_only=False):
    """The port's pushes (or force_pushes, with forced_only) of `ref`, newest first.

    records: ref.updated-shaped payloads (contracts/events/ref.updated.v1.json), oldest first.
    ref: refs/heads/<branch>. complete: the records hold every move (nothing truncated).
    Returns [{before, after, timestamp}]: one entry per distinct move, a repeated move counted once.
    """
    known = [record for record in records if record.get('ref') == ref]
    if not known:
        raise HistoryGap(f'no record of {ref}: it cannot be said whether the branch was pushed'
                         f'{" or force-pushed" if forced_only else ""}')
    if not complete and not any(record.get('created') for record in known):
        earliest = known[0].get('pushed_at', '?')
        raise HistoryGap(f'the window is truncated and does not reach the creation of {ref} (its earliest record '
                         f'is at {earliest}): earlier moves are not in it, so the answer would be partial')
    moves, seen = [], set()
    for record in known:
        if record.get('deleted'):
            continue
        key = (record.get('before'), record.get('after'))
        if key in seen:  # the same move, recorded twice
            continue
        seen.add(key)
        moves.append(record)
    return [{'before': record.get('before'), 'after': record.get('after'), 'timestamp': record.get('pushed_at')}
            for record in reversed(moves) if record.get('forced') or not forced_only]
