"""The train on the box (VAZÃO F36, D-297; docs/programs/vazao/design-trem.md): one batch per leadership.

`scripts/train run --box` is run by the `deliver` that won the box's lock with two or more deliveries waiting (the
leader, as in a database's group commit), or by hand, when it takes the lock itself (box_queue.hold). Inside the train
lock (train.lock_ref, unchanged) the leader:

1. reads the live entries of the box queue (box_queue.entries) and the forge's state of each (train_queue.box_entries:
   a PR closed or pushed since it queued is not waiting);
2. sizes the batch: k = min(waiting, k_max(p)), p read once from the meter (Train.size_now, train.batch_size_by_red);
   with k < 2 there is no batch and the leader says so (`box: no batch`), so its own delivery goes the single way;
3. admits the oldest k: the base merged into each member's branch (a merge commit pushed without the hook, as deliver
   does, because commit-check's FP1 refuses a head behind its base) and the PR part of the structure check that tier 2
   does not see (`commit-check --pr N` and the body's `structure-check --pr-body`). A member that does not take the base
   is `conflicted`, one the checks refuse is `refused`; both are told in their result, nothing is emitted for them
   (deliver says the same on its single path). The admission is measured (`train:admit`);
4. runs the batch (Train.run_batch: tier 2 on the combined head, the prefix bisection, the proven prefix merged with
   the culprit's ejection, the tree proof);
5. writes each resolved member's result from what the forge recorded for its judged head (pr.merged, pr.ejected,
   pr.conflicted, pr.refused). A member after the culprit, or one whose head moved, gets no result: it stays queued and
   its own `deliver` leads or joins the next batch;
6. prints `box: batch {json}` {id, prs, runs, merged, ejected, conflicted, refused, size, red} for the lock log.

One batch per leadership: the leader does not drain the queue, so its lane's `deliver` comes back soon.
"""
import json
import re
import subprocess
import sys
import tempfile
import time

import box_queue
import engine_role
import forge_events
import train_queue

RESOLVED = {'pr.merged': 'merged', 'pr.ejected': 'ejected', 'pr.conflicted': 'conflicted', 'pr.refused': 'refused'}
FAIL = re.compile(r'^(FAIL|ERROR)\b.*$', re.MULTILINE)


def checks(root, pr, body):
    """The PR part of the structure check for one member: commit-check --pr N and the body; [] when both pass."""
    problems = []
    done = subprocess.run([str(root / 'scripts' / 'commit-check'), '--pr', str(pr)], cwd=root, capture_output=True,
                          text=True)
    if done.returncode != 0:
        said = done.stdout + done.stderr
        problems += FAIL.findall(said) or [said.strip()[-300:] or f'commit-check --pr {pr} failed']
    with tempfile.NamedTemporaryFile('w', suffix='.md') as handle:
        handle.write(body or '')
        handle.flush()
        done = subprocess.run([str(root / 'scripts' / 'structure-check'), '--pr-body', handle.name], cwd=root,
                              capture_output=True, text=True)
        problems += [line for line in done.stdout.splitlines() if line.startswith('FAIL')]
        # D-322: the body's effort block is the measurement checks' part, which the structure check no longer imports
        done = subprocess.run([sys.executable, str(root / 'scripts' / 'lib' / 'measurement_checks.py'), 'body',
                               '--pr-body', handle.name], cwd=root, capture_output=True, text=True)
    problems += [line for line in done.stdout.splitlines() if line.startswith('FAIL')]
    return problems


class CountingGate:
    """The train's tier 2 with a count of its runs (the batch's line in the lock log)."""

    def __init__(self, gate):
        self.gate, self.runs = gate, 0

    def run(self, commit, env=None):
        self.runs += 1
        return self.gate.run(commit, env=env) if env else self.gate.run(commit)


def attribute(train, base):
    """(unit, lane_id) of a head for the ownership check and the payloads, from the manifests at the tip."""
    def read(sha):
        if train.ownership is None:
            return None, None
        files = train.workspace.changed_files(base, sha)
        return forge_events.unit_of(train.ownership, base, files), train.ownership.lane_of(base, files, sha)
    return read


def resync(train, entry, tip, change):
    """(entry at the head that contains the tip, None) or (None, (outcome, detail)) when the base does not come in."""
    if train.workspace.is_ancestor(tip, entry.sha):
        return entry, None
    branch = change.get('head_ref')
    if not branch or change.get('head_repo') not in (None, train.repo):
        return None, ('refused', f'the box cannot push to {change.get("head_repo")}:{branch}')
    message = (f'Merge {train.base_branch} {tip} into #{entry.pr} (box batch)\n\n'
               f'The box train (D-297) merged the base so the batch judges what lands.\n')
    commit, files, _regenerated = train.workspace.combine_regenerated(entry.sha, tip, message)
    if commit is None:
        return None, ('conflicted', f'{branch} does not merge with {train.base_branch}: {", ".join(sorted(files))}')
    try:
        train.workspace.push(commit, branch, verify=False)
    except Exception as error:  # noqa: BLE001 - the branch moved: its delivery is not waiting on this head any more
        return None, ('refused', f'the base merge could not be pushed to {branch} ({str(error)[-200:]})')
    print(f'box: #{entry.pr} took the base: {tip[:12]} merged into {entry.sha[:12]} as {commit[:12]}')
    return entry._replace(sha=commit), None


def admit(train, port, entries, tip, check):
    """[(entry, queued head)] that may enter the batch, and the results of the others {pr: (head, outcome, detail)}."""
    admitted, results = [], {}
    with train.step(port, 'admit', tip):
        for entry in entries:
            change = port.change(train.repo, entry.pr)
            synced, refusal = resync(train, entry, tip, change)
            problems = check(entry.pr, change.get('body')) if synced else []
            if problems:
                refusal = ('refused', '; '.join(problems)[-500:])
            if refusal:
                results[entry.pr] = (entry.sha, *refusal)
                print(f'box: #{entry.pr} {refusal[0]}: {refusal[1]}')
                continue
            admitted.append((synced, entry.sha))
    return admitted, results


def outcome(port, repo, entry):
    """(outcome, payload) of the forge's record for the judged head, or None while it still waits."""
    for event in reversed(port.read(repo, entry.pr)):
        kind = RESOLVED.get(event.get('type'))
        if kind and (event.get('payload') or {}).get('sha') == entry.sha:
            return kind, event['payload']
    return None


def lead(train, port, directory=None, measure=None, check=None):
    """One leadership (module docstring): 'batched', 'no batch' or 'empty'. Writes the members' results."""
    rows = box_queue.entries(directory)
    tip = train.workspace.tip(train.base_branch)
    entries, skipped = train_queue.box_entries(rows, lambda pr: port.change(train.repo, pr), train.base_branch,
                                               attribute(train, tip))
    for _row, why in skipped:
        print(f'box: not waiting: {why}')
    if not entries:
        print('box: empty (no live delivery waits)')
        return 'empty'
    k_max, red = train.size_now(measure)
    size = min(k_max, len(entries))
    if size < 2:
        print(f'box: no batch ({len(entries)} waiting, k_max {k_max} at p {red if red is not None else "unknown"})')
        return 'no batch'
    if check is None:
        check = lambda pr, body: checks(engine_role.ROOT, pr, body)  # noqa: E731
    admitted, results = admit(train, port, entries[:size], tip, check)
    queued = {entry.pr: head for entry, head in admitted}
    counting = CountingGate(train.gate)
    train.gate = counting
    try:
        train.run_batch([entry for entry, _head in admitted]) if admitted else []
    finally:
        train.gate = counting.gate
    summary = {'id': None, 'prs': [entry.pr for entry in entries[:size]], 'runs': counting.runs, 'size': size,
               'red': red, 'merged': [], 'ejected': [], 'conflicted': [], 'refused': []}
    for entry, _head in admitted:
        found = outcome(port, train.repo, entry)
        if found is None:
            continue
        kind, payload = found
        summary['id'] = summary['id'] or payload.get('batch_id')
        results[entry.pr] = (queued[entry.pr], kind, payload.get('reason') or payload.get('stage') or '',
                             payload.get('batch_id'), payload.get('merge_sha'), entry.sha)
    for pr, (head, kind, detail, *rest) in sorted(results.items()):
        bid, merge_sha, sha = (rest + [None, None, None])[:3]
        summary[kind].append(pr)
        box_queue.write_result(pr, head, kind, directory, sha=sha or head, batch_id=bid, merge_sha=merge_sha,
                               detail=detail, at=time.time())
    print('box: batch ' + json.dumps(summary, sort_keys=True))
    return 'batched'
