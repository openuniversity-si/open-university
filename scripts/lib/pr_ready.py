"""pr.ready (D-065, docs/process/EVENTS.md), emitted by the session through the forge_events port (M2).

A head is ready when its plan is fully ticked by commits (plan_tick) and the log holds a passed gate for that head and
plan (gate_report). pr.ready then names that gate.passed by event_id as its evidence. The port owns the envelope, the
idempotency key, the clock and the transport; this module only decides whether the head may be announced.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402
import gate_carry  # noqa: E402
import gate_verdicts  # noqa: E402
import git_objects  # noqa: E402
import plan_tick  # noqa: E402
import train_ownership  # noqa: E402
import train_trigger  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EVENT_TYPE = 'pr.ready'


class GateNotPassed(RuntimeError):
    pass


def short(sha):
    """The printed form of a sha (plan-tick.short_sha_chars); events keep the full sha."""
    return sha[:config.get('plan-tick.short_sha_chars')]


def tree(root):
    """The read-only reader of the checkout (git_objects.Tree, with the train's git timeout), never the train's own
    workspace: pr.ready is the gate's announcement and reads commits from below the train (D-322)."""
    return git_objects.Tree(root, config.get('train.git_timeout_s'))


def lane_of(root, base, head):
    """The lane the head's changes belong to, by the unit manifests at the merge base with `base` (train_ownership).

    A change touching several lanes, or no unit, gets None, so the train's ownership check still judges it.
    """
    workspace = tree(root)
    merge_base = workspace.git('merge-base', base, head).stdout.strip()
    return train_ownership.UnitOwnership(workspace).lane_of(merge_base, workspace.changed_files(base, head), head)  # D-112


def unit_of(root, base, head):
    """REC-1: the one unit the head's changes belong to (forge_events.unit_of at the merge base), else None."""
    workspace = tree(root)
    merge_base = workspace.git('merge-base', base, head).stdout.strip()
    return forge_events.unit_of(train_ownership.UnitOwnership(workspace), merge_base, workspace.changed_files(base, head))


def has_commit(root, sha):
    """True when `sha` names a commit of the checkout at `root`."""
    return subprocess.run(['git', '-C', str(root), 'cat-file', '-e', f'{sha}^{{commit}}'], capture_output=True).returncode == 0


def recorded_base(port, repo, pr, root, fallback=None):
    """(base, note): the base sha the forge records for the change (baseRefOid), read once through the port, so the
    plan ticks and the lane never depend on a local remote-tracking ref. When the forge cannot say or the checkout does
    not hold that commit, the base is `fallback` (default plan-tick.base_ref) and `note` says why; note is None otherwise.
    """
    fallback = fallback or config.get('plan-tick.base_ref')
    try:
        recorded = port.change(repo, pr).get('base')
    except Exception as error:  # noqa: BLE001 - an unreachable forge degrades to the configured ref, reported
        return fallback, f'forge unreachable ({error}); base is {fallback}'
    if not recorded:
        return fallback, f'forge records no base for #{pr}; base is {fallback}'
    if not has_commit(root, recorded):
        return fallback, f'recorded base {short(recorded)} is not in the checkout; base is {fallback}'
    return recorded, None


def gate_events(port, repo, pr):
    """The PR's events without the gate verdicts of an unlocked version (gate_verdicts), read once through the port."""
    return gate_verdicts.accepted(port.read(repo, pr))


def emit_ready(port, repo, pr, head_sha, premises, plan, lane_id=None, events=None, unit=None):
    """Emit pr.ready for the head (lane_id from lane_of), citing the passed gate of the plan (any locked verdict version,
    gate_verdicts). `events` is an earlier gate_events read, else the port is read. Returns the envelope."""
    events = gate_events(port, repo, pr) if events is None else events
    evidence = forge_events.gate_evidence(forge_events.replay(events), pr, head_sha, plan)
    if evidence is None:
        raise GateNotPassed(f'no passed {plan} gate for {head_sha[:8]} on #{pr} in the event log')
    return port.emit(EVENT_TYPE, dict(forge_events.subject(repo, pr, head_sha, premises, unit), lane_id=lane_id, evidence=evidence))


def plan_gap(body, messages):
    """None when every plan item of the body is ticked by a commit, else why not (shared by main and the gate hook)."""
    items = plan_tick.checklist(body, messages)
    unticked = [str(number) for number, _, done in items if not done]
    if items and not unticked:
        return None
    return f'items not ticked by a commit: {", ".join(unticked)}' if items else 'the body has no plan checklist'


def carried_proof(events, pr, sha, plan):
    """carried_from {event_id, sha, delta_files} of the head's verdict (the last accepted gate.passed or gate.failed for
    that sha and plan), or None when that verdict did not pass or carried nothing (GX-20)."""
    last = None
    for event in events:
        payload = event.get('payload') or {}
        if (event.get('type') in gate_verdicts.TYPES and payload.get('pr') == pr and payload.get('sha') == sha
                and payload.get('plan') == plan):
            last = event
    if last is None or last['type'] != 'gate.passed':
        return None
    return last['payload'].get('carried_from') or None


def check_carry(root, sha, carried):
    """None when git agrees with the carried proof (its sha is an ancestor of `sha` and the delta between them,
    gate_carry.delta, is its delta_files), else why not. Fails closed: a malformed proof or a git error refuses."""
    if not isinstance(carried, dict):
        return 'carried_from is not an object'
    origin, files = carried.get('sha'), carried.get('delta_files')
    if not isinstance(origin, str) or not isinstance(files, list):
        return 'carried_from has no sha or delta_files'
    if not gate_carry.is_ancestor(root, origin, sha):
        return f'{short(origin)} is not an ancestor of {short(sha)}'
    try:
        actual = gate_carry.delta(root, origin, sha)
    except subprocess.CalledProcessError as error:
        return f'git failed: {error.stderr.strip()}'
    if actual != sorted(files):
        return (f'carried proof does not match the delta {short(origin)}..{short(sha)} '
                f'(git: {", ".join(actual) or "none"}; proof: {", ".join(sorted(files)) or "none"})')
    return None


def carried_items(body, root, base, origin, sha):
    """The plan items ticked by a commit of origin..sha and by no commit of base..origin: the items the carried proof
    of `origin` satisfies (the RETRO item)."""
    before = plan_tick.ticked_by(plan_tick.commit_messages(base, root, origin))
    after = plan_tick.commit_messages(origin, root, sha)
    return [number for number, _, done in plan_tick.checklist(body, after) if done and number not in before]


def carry_note(body, root, base, sha, carried):
    """(note, refusal): what pr.ready says about a carried head's evidence, or why the carried proof is refused."""
    refusal = check_carry(root, sha, carried)
    if refusal:
        return None, refusal
    try:
        items = carried_items(body, root, base, carried['sha'], sha)
    except subprocess.CalledProcessError as error:
        return None, f'git failed: {error.stderr.strip()}'
    source = f'the carried proof of {carried.get("event_id")}'
    if not items:
        return f'evidence is {source}', None
    label = 'item' if len(items) == 1 else 'items'
    return f'{label} {", ".join(str(number) for number in items)} satisfied by {source}', None


def subject_root(root=None):
    """The checkout holding the gated sha: the root a caller names, else the OU_SUBJECT_ROOT the gate exported (gate-local),
    else this tool checkout. The gate hands in the tool checkout by default, so the export wins over that default only."""
    if root is None or Path(root).resolve() == ROOT:
        exported = os.environ.get('OU_SUBJECT_ROOT')
        if exported:
            return Path(exported)
    return Path(root) if root is not None else ROOT


def checkout_head(root):
    return subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                          check=True).stdout.strip()


def ready_after_gate(port, repo, pr, sha, body, root=None, plan=None, base=None, recorded=None, events=None):
    """After a passed gate (EVENTS.md: a pass with a valid body emits pr.ready). `plan` is the plan of the passed
    verdict. Emits pr.ready only for the plan-tick.required_gate_kind verdict, for the gated `sha` as a commit of the
    subject root (subject_root; never the tool checkout's HEAD), with the plan fully ticked by the commits of
    baseRefOid..sha (recorded_base; `base` or plan-tick.base_ref only when the forge cannot say, and that is reported)
    and the gate.passed in the log. A head whose gate.passed carries an earlier proof (GX-20) is ready only when git agrees
    with that carry (check_carry); the items only its later commits tick are reported as satisfied by the carried proof.
    Returns (envelope or None, reason). The port dedupes by natural key, so a second
    call for the same head is a no-op."""
    required = config.get('plan-tick.required_gate_kind')
    plan = plan or required
    if plan != required:
        return None, f'the {plan} gate is not the {required} gate pr.ready needs'
    root = subject_root(root)
    if not has_commit(root, sha):
        return None, f'the gated head {short(sha)} is not a commit of the checkout {root}'
    # A gate publisher already read the PR and acknowledged its verdict append. Reuse those observations in this
    # transaction; standalone pr-ready still obtains them through the same port.
    if recorded and has_commit(root, recorded):
        base, note = recorded, None
    else:
        base, note = recorded_base(port, repo, pr, root, fallback=base)
    if note:
        print(f'pr.ready: {note}', file=sys.stderr)
    try:
        messages = plan_tick.commit_messages(base, root, sha)
    except subprocess.CalledProcessError as error:
        return None, f'git failed: {error.stderr.strip()}'
    gap = plan_gap(body, messages)
    if gap:
        return None, f'plan: {gap}'
    try:
        events = gate_events(port, repo, pr) if events is None else gate_verdicts.accepted(events)
    except forge_events.ForgeEventsError as error:
        return None, str(error)
    carried = carried_proof(events, pr, sha, plan)
    notes = [note] if note else []
    if carried is not None:
        carry, refusal = carry_note(body, root, base, sha, carried)
        if refusal:
            return None, f'carried proof: {refusal}'
        notes.append(carry)
    try:
        event = emit_ready(port, repo, pr, sha, forge_events.premises_from_body(body), plan, lane_of(root, base, sha),
                           events, unit_of(root, base, sha))
    except (GateNotPassed, forge_events.ForgeEventsError, event_contracts.ContractError,
            git_objects.GitObjectsError) as error:
        return None, str(error)
    return event, f'ready ({"; ".join(notes)})' if notes else 'ready'


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/pr-ready', description=__doc__.splitlines()[0])
    parser.add_argument('--pr', type=int, required=True, help='PR number')
    parser.add_argument('--body', type=Path, required=True, help='file with the PR body (the plan and Premises: line)')
    parser.add_argument('--base', default=None, help='fallback base of base..HEAD when the forge records none (default: plan-tick.base_ref)')
    parser.add_argument('--root', type=Path, default=ROOT, help='checkout whose HEAD is ready')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    body = args.body.read_text(encoding='utf-8')
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    config.get('plan-tick.event_producer'), f'pr-{args.pr}')
    repo = config.get('forge-events.repo')
    base, note = recorded_base(port, repo, args.pr, root, fallback=args.base)
    if note:
        print(f'pr-ready: {note}')
    try:
        head = checkout_head(root)
        messages = plan_tick.commit_messages(base, root, head)
        lane_id = lane_of(root, base, head)
        unit = unit_of(root, base, head)
    except (subprocess.CalledProcessError, git_objects.GitObjectsError) as error:
        print(f'FAIL pr-ready: git failed: {getattr(error, "stderr", error).strip()}')
        return 1
    detail = plan_gap(body, messages)
    if detail:
        print(f'FAIL pr-ready: plan: {detail} (add "Plan: N" to the commit that delivers item N)')
        return 1
    try:
        event = emit_ready(port, repo, args.pr, head, forge_events.premises_from_body(body),
                           config.get('plan-tick.required_gate_kind'), lane_id,
                           unit=unit)
    except (GateNotPassed, forge_events.ForgeEventsError, event_contracts.ContractError) as error:
        print(f'FAIL pr-ready: {error}')
        return 1
    print(f'pr.ready #{args.pr} head={head[:8]} lane={lane_id} (event {event["event_id"][:12]})')
    try:
        print(f'train: {train_trigger.trigger(root, event, f"pr-{args.pr}")}')
    except train_trigger.NotStarted as reason:  # emit_only: the train-role session runs the train
        print(f'train: not started ({reason})')
    except train_trigger.forge_git_ref.GitRefError as error:  # wake: pr.ready stands; the periodic run catches it
        print(f'train: not woken ({error})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
