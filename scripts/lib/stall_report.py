"""Stalled sessions (X1): `scripts/stall-report` prints the open PRs whose session stopped, for the orchestrator.

Computed on demand from the forge, through the forge_events port (never a polling loop or a cron in the engine):
the open PRs into the integration branch (train.base_branch), each one's pushes as the forge recorded them, its gate
verdicts on its event log (gate.passed, gate.failed) and its comments. A PR is stalled for each reason that holds:
  no_push     its branch had no push for push-guard.stall_no_push_s, unless the gate passed on its head (it then
              waits on the merger, not on its session);
  red_gate    its latest gate verdict is gate.failed, nothing was pushed after it, and push-guard.stall_red_gate_s
              passed since;
  owner_wait  a comment waits on an owner decision and no later comment records a Decision line (decision_wait.py,
              DECIDE, THEN REPORT, Daniel 2026-10-26 21:29).
`since` is when the stall started (the last push, the red verdict, the waiting comment); `now` comes from the
port's injected clock. Output: a JSON list of {pr, branch, reason, since, last_push, last_gate, last_gate_at,
detail}. --emit also records each stall as engine.session.stalled on the PR's log (idempotent: the natural key is
repo, pr, reason, since). This lives beside the push guard, not in scripts/units: a stall is about a session's
branch and PR, not about which unit owns a path.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import decision_wait  # noqa: E402
import forge_events  # noqa: E402
import gate_verdicts  # noqa: E402

FIELDS = ('pr', 'branch', 'reason', 'since', 'last_push', 'last_gate', 'last_gate_at', 'detail')


def moment(text):
    return datetime.fromisoformat(text.replace('Z', '+00:00'))


def stalls(port, repo, number, now):
    """The engine.session.stalled payloads of one open PR, in reason order."""
    pull = port.pull(repo, number)
    pushes = [push['timestamp'] for push in port.pushes(repo, pull['head_ref']) if push.get('timestamp')]
    last_push = max(pushes, key=moment) if pushes else None
    verdicts = gate_verdicts.verdicts(port.read(repo, number))
    last = verdicts[-1] if verdicts else None
    last_gate = last['type'].split('.', 1)[1] if last else None
    last_gate_at = last['occurred_at'] if last else None
    base = dict(forge_events.subject(repo, number, pull['head_sha']), branch=pull['head_ref'], last_push=last_push,
                last_gate=last_gate, last_gate_at=last_gate_at, detail=None)
    found = []
    green_head = last_gate == 'passed' and last['payload'].get('sha') == pull['head_sha']
    if (last_push and not green_head
            and (now - moment(last_push)).total_seconds() >= config.get('push-guard.stall_no_push_s')):
        found.append(dict(base, reason='no_push', since=last_push))
    if (last_gate == 'failed' and (last_push is None or moment(last_push) <= moment(last_gate_at))
            and (now - moment(last_gate_at)).total_seconds() >= config.get('push-guard.stall_red_gate_s')):
        found.append(dict(base, reason='red_gate', since=last_gate_at))
    comments = port.comments(repo, number)
    waiting = decision_wait.waiting([comment['body'] for comment in comments])
    if waiting:
        index, _, line = waiting
        since = comments[index].get('created_at') or forge_events.rfc3339(now)
        found.append(dict(base, reason='owner_wait', since=since, detail=line))
    return found


def report(port, repo, base, emit=False):
    """Every stall of the open PRs into base, by PR; with emit, each is also recorded on the PR's log."""
    now = port.clock.now()
    found = []
    with port.batched():  # GX-FIX-forge-rate: one append per PR channel, not one per stall
        for number in sorted(port.open_changes(repo, base)):
            for payload in stalls(port, repo, number, now):
                if emit:
                    port.emit('engine.session.stalled', payload)
                found.append({field: payload[field] for field in FIELDS})
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/stall-report', description=__doc__.splitlines()[0])
    parser.add_argument('--base', default=None, help='integration branch (default: train.base_branch)')
    parser.add_argument('--emit', action='store_true', help='record each stall as engine.session.stalled')
    args = parser.parse_args(argv)
    repo = config.get('forge-events.repo')
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    config.get('push-guard.event_producer'), 'stall-report')
    try:
        found = report(port, repo, args.base or config.get('train.base_branch'), args.emit)
    except RuntimeError as error:
        print(f'FAIL stall-report: {error}', file=sys.stderr)
        return 1
    print(json.dumps(found, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
