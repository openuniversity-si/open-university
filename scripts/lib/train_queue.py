"""The merge train's queue index (GX-30; GA2 G-09 and G-10: the queue rebuild cost).

The queue is every open change whose latest `pr.ready` names its current head, rests on a `gate.passed` of that head
on the same log, and has no later `pr.conflicted`, `pr.ejected`, `pr.merged` or `pr.refused` for it (queue_entry).
Replaying the logs rebuilds it (D-069 item 4), and the first build of an index is exactly that replay: every open
change's log and head, 1 + 2 × open changes reads.

The train rebuilds its queue after every batch. With train.queue_since_last_batch on and an adapter that offers
`events_since(repo, since)` (every event on any channel of the repository whose occurred_at is at or after `since`,
an RFC 3339 string), a later build reads only what happened since the previous build started: the open changes, the
events since, and the log and head of each change those events name, so it costs 2 + 2 × changed PRs instead of
1 + 2 × open PRs. Entries of the other open changes are kept; a change that closed leaves. A head pushed after
pr.ready without a new event stays indexed with the old sha: its merge is refused (--match-head-commit), it leaves
the run's queue (Train.refused, no event: its head moved) and the rest of its batch still merges
(train.rebuild_max). An adapter without the capability, or the switch off (the rollback), keeps the full replay on
every build. Nothing outside the logs is stored: a new
process starts with the full replay.

Critical path first (MQ1's merge order, GX-30): inside a batch the members are ordered by how many units transitively
require their unit (unit manifests' `requires`), then by the oldest pr.ready, then by PR number. The combined head
is built in that order, so its prefixes, the proven prefix that merges on a refusal and the bisection follow the
critical path. Which PRs enter a batch stays FIFO (the train takes the queue's first train.batch_size).
"""
from datetime import datetime, timezone
import re

import forge_events

# The queue predicate and its entry live with the log they read (forge_events, D-322); re-exported for the train.
Entry, OUT_OF_QUEUE, queue_entry = forge_events.QueueEntry, forge_events.OUT_OF_QUEUE, forge_events.queue_entry
GATES = ('gate.passed', 'gate.failed')
REVERDICT = 'r-'  # batch_id prefix of the pr.ejected of the train's own red re-verdict (train_verdict.judge_again)

PREMISES = re.compile(r'^Premises:[ \t]*(.*)$', re.MULTILINE)


def premises_of(body):
    """The premise ids a PR body's `Premises:` line names (D-066); none for `Premises: none` or no line."""
    found = PREMISES.search(body or '')
    return tuple(re.findall(r'\bP-\d+\b', found.group(1))) if found else ()


def box_entries(rows, change, base_branch, attribute=None):
    """VAZÃO F36: the box queue's live rows (box_queue.entries, oldest first) as train entries, read again from the
    forge (a leader that died left nothing the next one trusts): ([Entry], [(row, why)] of the rows that are not
    waiting for this base any more). `change(pr)` is the forge's change; `attribute(sha)` gives (unit, lane_id) for the
    ownership check (None: both unknown). The entry rests on no pr.ready: the box batch is the gate it saves."""
    entries, skipped = [], []
    for row in rows:
        found = change(row['pr'])
        if not found.get('open', True) or found.get('base_ref') not in (None, base_branch):
            skipped.append((row, f'#{row["pr"]} is not open on {base_branch}'))
            continue
        if found.get('head') != row['head']:
            skipped.append((row, f'#{row["pr"]} head moved to {found.get("head")} after {row["head"]} queued'))
            continue
        unit, lane_id = attribute(row['head']) if attribute else (None, None)
        at = forge_events.rfc3339(datetime.fromtimestamp(float(row['at']), timezone.utc))
        entries.append(Entry(row['pr'], row['head'], unit, premises_of(found.get('body')), lane_id, at, None))
    return entries, skipped


DIRTY_MARKS = ('not mergeable', 'dirty', 'conflict')


def skip_reason(events, head, refusal=''):
    """Why a PR that waits for the train is not merged now, named for its owner lane: never silent (incident of 2026-11-01:
    the train answered 'drained' for green PRs that were dirty). The forge's refusal is `refusal`."""
    ready = [event for event in events if event['type'] == 'pr.ready']
    if not ready:
        return 'it never got pr.ready'
    sha = ready[-1]['payload']['sha']
    if sha != head:
        return f'its head moved to {head} after pr.ready on {sha}: it needs a new pr.ready'
    if any(event['type'] in OUT_OF_QUEUE and event['payload']['sha'] == sha for event in events):
        return 'it is out of the queue (merged or conflicted on this head)'
    evidence = ready[-1]['payload']['evidence']
    if not any(event['type'] == 'gate.passed' and event['event_id'] == evidence and event['payload']['sha'] == sha
               for event in events):
        return 'no passed real gate of this head backs its pr.ready'
    lowered = refusal.lower()
    if any(mark in lowered for mark in DIRTY_MARKS):
        return f'dirty: the base conflicts with this head; its owner resolves it ({refusal})'
    return f'the forge refused the merge ({refusal}); it stays queued'


def resync_candidate(events, head, tip):
    """The entry the train resyncs on its own (TRAIN-VERDICT-FIX B2, D-075), or None: an open PR whose current head is
    not queued, that was ready before (its latest pr.ready gives the unit, premises and lane) and whose head's latest
    gate judged a base other than the tip. Left out: a head merged, conflicted at this very tip, or already red on the
    train's own re-verdict (its owner pushes next). The evidence is None: no verdict of this head is admitted as is."""
    ready = [event for event in events if event['type'] == 'pr.ready']
    gates = [event for event in events if event['type'] in GATES and event['payload']['sha'] == head]
    if not ready or not gates or queue_entry(events, head) is not None:
        return None
    if gates[-1]['payload'].get('base_sha') == tip:
        return None
    for event in events:
        payload = event['payload']
        if payload.get('sha') != head:
            continue
        if (event['type'] == 'pr.merged' or (event['type'] == 'pr.conflicted' and payload.get('tip_sha') == tip)
                or (event['type'] == 'pr.ejected' and str(payload.get('batch_id')).startswith(REVERDICT))):
            return None
    latest = ready[-1]
    payload = latest['payload']
    return Entry(payload['pr'], head, payload['unit'], tuple(payload['premises']), payload['lane_id'],
                 latest['occurred_at'], None)


def dependents(manifests):
    """Per unit, how many units require it directly or transitively (manifests by id, units.manifests)."""
    required_by = {}
    for unit, manifest in manifests.items():
        for needed in manifest.get('requires') or {}:
            required_by.setdefault(needed, set()).add(unit)
    weights = {}
    for unit in manifests:
        seen, todo = set(), list(required_by.get(unit, ()))
        while todo:
            other = todo.pop()
            if other not in seen:
                seen.add(other)
                todo.extend(required_by.get(other, ()))
        weights[unit] = len(seen - {unit})
    return weights


def critical_first(entries, weights):
    """Entries ordered critical path first: the heaviest unit, then the oldest pr.ready, then the lower PR number."""
    return sorted(entries, key=lambda entry: (-weights.get(entry.unit, 0), moment(entry.ready_at), entry.pr))


def moment(stamp):
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).astimezone(timezone.utc)


class QueueIndex:
    """The queue of one repository and base branch, kept between builds of one train run."""

    def __init__(self, repo, base_branch, clock, incremental):
        self.repo, self.base_branch, self.clock, self.incremental = repo, base_branch, clock, incremental
        self.entries, self.since, self.last_build = {}, None, None

    def build(self, reader):
        """Every PR waiting for the train (unordered; the train orders it). `reader` is a forge_events port."""
        started = forge_events.rfc3339(self.clock.now())
        numbers = reader.open_changes(self.repo, self.base_branch)
        since = getattr(reader.adapter, 'events_since', None)
        if self.incremental and since is not None and self.since is not None:
            open_now = set(numbers)
            changed = {event['payload'].get('pr') for event in since(self.repo, self.since)
                       if moment(event['occurred_at']) >= moment(self.since)}
            self.entries = {number: entry for number, entry in self.entries.items() if number in open_now}
            read = [number for number in numbers if number in changed]
            self.last_build = 'since'
        else:
            self.entries, read = {}, list(numbers)
            self.last_build = 'full'
        for number in read:
            entry = queue_entry(reader.read(self.repo, number), reader.change(self.repo, number)['head'])
            if entry:
                self.entries[number] = entry
            else:
                self.entries.pop(number, None)
        self.since = started
        return list(self.entries.values())
