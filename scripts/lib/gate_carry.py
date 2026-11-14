"""Carry-over by delta (GX-20, B-14, GA-P01 = P-42, D-070; the GX-39 seam).

A PR gate whose head H descends from a head H0 with a passed v4 dev proof on the same base_sha, toolchain_id and
gate_version classifies delta(H0, H) instead of base...H. When every delta file is in an area of
gate-carry.carry_over_areas (docs), the plan is the delta plan (the always-stages, so the structure check executes on
H (D-B6), plus the script tests whose covers meet the delta, GX-18) and every other stage H0 passed is carried:
recorded as a passed, cached stage of this run, with `carried_from {event_id, sha, delta_files}`.

Fails closed (GA-P10): the switch off, no bound proof, no such verdict, H0 not an ancestor, a file outside the carry
areas, or any read or git error is a normal gate. Only attested forge events are read, never a box-local `.pass`
marker (P-43). A carried verdict chains to its origin (`carried_from.sha`), so the delta is always measured from a head
whose stages all ran.

`decide` runs at the gate-local plan hook (gate-hooks/plan.sh) and writes the decision; `gate_policy.classify_pr`
plans the delta and calls `record`; `carried(logs)` and `carried_from(logs)` read what the run carried."""
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

DECISION_ENV = 'OU_GATE_CARRY_FILE'  # the decision file the plan hook exports to the classification
RECORD = 'carry.json'  # the run's carry record, next to the stage records in the logs folder
PROOF_ENV = 'OU_GATE_PROOF'  # gate_proof.ENV: the binding of this run
PLAN = 'dev'  # the plan a carry reads and writes: the tier-1 PR gate


def settings():
    import config
    return config.get('gate-carry.carry_over_enabled'), list(config.get('gate-carry.carry_over_areas'))


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout


def is_ancestor(root, old, new):
    return subprocess.run(['git', '-C', str(root), 'merge-base', '--is-ancestor', old, new],
                          capture_output=True).returncode == 0


def delta(root, old, new):
    """The files changed from `old` to `new` (both sides of a rename count), sorted."""
    return sorted(path for path in git(root, 'diff', '--no-renames', '--name-only', '-z', old, new).split('\0') if path)


def is_proof(event):
    """An accepted dev gate.passed that carries the v4 proof fields a carry is matched on."""
    payload = event.get('payload') or {}
    return (event.get('type') == 'gate.passed' and payload.get('plan') == PLAN and isinstance(payload.get('sha'), str)
            and all(payload.get(key) for key in ('input_digest', 'base_sha', 'toolchain_id', 'gate_version')))


def latest_verdicts(events):
    """The last dev verdict per head, in log order (a later gate.failed on a head withdraws its earlier pass)."""
    latest = {}
    for event in events:
        payload = event.get('payload') or {}
        if event.get('type') in ('gate.passed', 'gate.failed') and payload.get('plan') == PLAN and payload.get('sha'):
            latest.pop(payload['sha'], None)
            latest[payload['sha']] = event
    return list(latest.values())


def candidate(events, binding, root):
    """(event, origin_sha, origin_event_id, reason): the newest passed proof on an ancestor head with the same base,
    toolchain and gate version, or (None, None, None, why not)."""
    head = binding['sha']
    reasons = []
    for event in reversed(latest_verdicts(events)):
        payload = event['payload']
        if payload['sha'] == head or not is_proof(event):
            continue
        differs = [key for key in ('base_sha', 'toolchain_id', 'gate_version') if payload[key] != binding.get(key)]
        if differs:
            reasons.append(f'{payload["sha"]}: different {", ".join(differs)}')
            continue
        origin = payload.get('carried_from') or {}
        origin_sha, origin_id = origin.get('sha') or payload['sha'], origin.get('event_id') or event['event_id']
        if not is_ancestor(root, origin_sha, head):
            reasons.append(f'{origin_sha}: not an ancestor of the head')
            continue
        return event, origin_sha, origin_id, ''
    return None, None, None, '; '.join(reasons) or 'no passed v4 dev proof on an earlier head of this PR'


def outside(paths, areas, area_map=None):
    """The delta files that are not in one of `areas` (gate_areas: a documentation path is the docs area only)."""
    import gate_areas
    area_map = area_map or gate_areas.load()
    allowed = set(areas)
    found = {path: {area.id for area in area_map.areas_for(path)} for path in paths}
    return [path for path in paths if not found[path] or not found[path] <= allowed]


def decide(events, binding, root, enabled, areas, area_map=None):
    """The carry decision for this run: {carry, reason, ...}. carry is True only when every rule holds."""
    normal = lambda reason: {'carry': False, 'reason': reason}  # noqa: E731
    if not enabled:
        return normal('gate-carry.carry_over_enabled is off')
    if not binding or not all(binding.get(key) for key in ('sha', 'base_sha', 'toolchain_id', 'gate_version')):
        return normal('the run has no proof binding')
    event, origin, origin_id, why = candidate(events, binding, root)
    if event is None:
        return normal(why)
    files = delta(root, origin, binding['sha'])
    if not files:
        return normal(f'no change from {origin}')
    foreign = outside(files, areas, area_map)
    if foreign:
        return normal(f'{foreign[0]} is outside {", ".join(areas)} (delta from {origin})')
    passed = [stage['name'] for stage in event['payload'].get('stages', []) if stage.get('result') == 'PASS']
    return {'carry': True, 'reason': f'{len(files)} file(s) in {", ".join(areas)} since {origin}',
            'sha': binding['sha'], 'base': binding['base_sha'], 'from': {'event_id': origin_id, 'sha': origin},
            'delta_files': files, 'passed_stages': passed}


def load_decision(path=None, environ=None):
    """The plan hook's decision, or None (no file, unreadable, or not a carry)."""
    import os
    path = path or (environ if environ is not None else os.environ).get(DECISION_ENV)
    try:
        decision = json.loads(Path(path).read_text()) if path else None
    except (OSError, ValueError):
        return None
    return decision if isinstance(decision, dict) and decision.get('carry') is True else None


def stage_slug(name):
    return re.sub(r'[^a-zA-Z0-9]', '_', name)  # gate-runner.sh and gate_report.stage_log name stage files this way


def record(logs, decision, stages):
    """Write the carry record and one passed, cached, carried stage record per carried stage; returns the record."""
    logs = Path(logs)
    logs.mkdir(parents=True, exist_ok=True)
    carried_from = {'event_id': decision['from']['event_id'], 'sha': decision['from']['sha'],
                    'delta_files': list(decision['delta_files'])}
    for name in stages:
        (logs / f'{stage_slug(name)}.stage.json').write_text(json.dumps(
            {'name': name, 'result': 'PASS', 'exit': 0, 'seconds': 0, 'cached': True, 'carried': True}))
    data = {'carried_from': carried_from, 'stages': list(stages), 'reason': decision['reason']}
    (logs / RECORD).write_text(json.dumps(data, sort_keys=True))
    return data


def _record(logs):
    try:
        data = json.loads((Path(logs) / RECORD).read_text())
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def carried(logs):
    """The stages this run carried from an earlier proof ([] when it carried nothing)."""
    return list((_record(logs) or {}).get('stages') or [])


def carried_from(logs):
    """{event_id, sha, delta_files} of the proof this run carried, or None."""
    return (_record(logs) or {}).get('carried_from')


def fields(logs):
    """The v4 payload fields of the carry: {'carried_from': ...} or {} (the seam for gate_proof.proof_payload)."""
    found = carried_from(logs)
    return {'carried_from': found} if found else {}


def binding_from_env(environ=None):
    """The run's proof binding (gate_proof.ENV, exported by gate-hooks/proof.sh), or None. Read here, not through
    gate_proof, so the plan unit does not depend on the report unit."""
    import os
    text = (environ if environ is not None else os.environ).get(PROOF_ENV, '')
    try:
        found = json.loads(text) if text else None
    except ValueError:
        return None
    return found if isinstance(found, dict) else None


def read_events(pr):
    """The PR's accepted events through the forge_events port (one read)."""
    import config
    import forge_events
    import gate_verdicts
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    config.get('forge-events.gate_producer'), f'pr-{pr}')
    return gate_verdicts.accepted(port.read(config.get('forge-events.repo'), pr))


def main(argv):
    """gate_carry.py decide --pr N --root R --out FILE: reads the binding (OU_GATE_PROOF) and the PR's events, writes
    the decision and prints one line. Exits 0 with a decision file, 1 (no file, normal gate) when it cannot decide."""
    import argparse
    parser = argparse.ArgumentParser(prog='gate_carry.py')
    parser.add_argument('command', choices=['decide'])
    parser.add_argument('--pr', type=int, required=True)
    parser.add_argument('--root', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        enabled, areas = settings()
        binding = binding_from_env()
        events = read_events(args.pr) if enabled and binding else []
        decision = decide(events, binding, args.root, enabled, areas)
    except Exception as error:  # noqa: BLE001 - fails closed: any error is a normal gate
        print(f'carry: normal gate (cannot decide: {error})')
        return 1
    args.out.write_text(json.dumps(decision, sort_keys=True))
    print(f'carry: {"delta plan" if decision["carry"] else "normal gate"} ({decision["reason"]})')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
