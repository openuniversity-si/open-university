"""Triage of plan inputs and the `scripts/plan` CLI (live-planning LP4, D-071; design 1.2-1.3).

triage(event, plan) -> candidate | seen is pure and deterministic, with no model and no lock: it dedupes by signature,
computes the affected set from units, premises and areas, and promotes to a plan.candidate
(contracts/events/plan.candidate.v1.json) or records a `seen` with the reason. Thresholds are planner.* registry keys.

Inputs are forge envelopes ({type, occurred_at, event_id, payload}). A gate.failed carrying several failing tests is
split by inputs() into one input per distinct signature, so one env cause hitting several tests is one candidate and
two causes in one run are two.

Signatures (the dedupe key, `<source>:<key>`):
  gate / base   failure:<the failing test's normalized signature (gate_failures), dotted registry names
                collapsed to <key>, no test id>: the same key on a PR head and on the base; a red stage with no
                failing test is failure:<stage>:<class>
  lesson        the lesson class          note    kind and normalized text     premise  the premise id
  defect        the defect id             owner   who and when                  overrun  the unit
  session/train/flake/base merge: the event type and the unit or test

Affected set (unit ids of the program.v1 graph, or `all`): the explicit affects of a note (unit ids, or areas matched
against each unit's `area` globs); units whose area matches a failing test or defect path; units whose events cite a
premise or whose PR a refuted premise lists; the active units of a lesson's lane; an overrun unit and its dependents;
`all` for env/contract classes, the base, owner rulings and train signals. Merged units are never affected.

Promotion: an input is a candidate when it touches an active unit other than its producer (or all), has class env or
contract, comes from a premise, owner, overrun or train source, or reaches planner.triage_promote_sightings sightings;
otherwise it is recorded as seen with the reason. Overrun: a unit whose time from its first work.assigned to its
latest event passes its estimate (minutes: the live plan's latest set_estimate record, args.estimate, else the
unit's `estimate`) times planner.overrun_factor.

CLI (scripts/plan): plan note --program P --from UNIT --affects UNITS --kind KIND --evidence REF "text"
                    plan input --program P --by WHO "text"
                    plan triage --program P [--events FILE]
"""
import argparse
from datetime import datetime, timedelta
import fnmatch
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402
import program  # noqa: E402

ALL = 'all'
OVERRUN = 'overrun'
FAILURE = 'failure'  # one key for a head and a base sighting of the same failure
ENGINE_PARTITION = 'engine'
ESTIMATE = 'estimate'  # minutes, on a unit or in a set_estimate op's args
CROSS_CUTTING = ('env', 'contract')
# Event type (or type prefix ending in '.') -> plan.candidate source (design 1.1).
SOURCES = {'gate.failed': 'gate', 'lesson.recorded': 'lesson', 'plan.note': 'note', 'plan.input': 'owner',
           'premise.confirmed': 'premise', 'premise.refuted': 'premise', 'defect.': 'defect', 'session.': 'session',
           'engine.session.stalled': 'session', 'train.': 'train', 'pr.ejected': 'train', 'test.flaked': 'flake',
           'selection.escape': 'flake', 'slo.breached': 'flake', 'integration.advanced': 'base', OVERRUN: 'overrun'}
ENGINE_SOURCES = ('gate', 'base', 'session', 'train', 'flake')
ALWAYS = ('premise', 'owner', 'overrun', 'train')
DIGITS = re.compile(r'(?<![A-Za-z_])\d+(?:\.\d+)?(?![A-Za-z_])')
SPACES = re.compile(r'\s+')
REGISTRY_NAME = re.compile(r'\b[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+\b')


def setting(name):
    return config.get(f'planner.{name}')


def source(event):
    """The plan.candidate source of an input, or None when triage does not read that event type."""
    kind = event.get('type', '')
    if kind == config.get('coordinator.event_merged'):
        return 'base'
    for prefix, name in SOURCES.items():
        if kind == prefix or (prefix.endswith('.') and kind.startswith(prefix)):
            return 'base' if name == 'gate' and event['payload'].get('pr') is None else name
    return None


def canonical(text):
    """A comparable one-line form: the first line, digits to N and runs of space collapsed (the rules of
    gate_failures.normalize, which already shaped a failing test's signature), dotted registry names to <key>."""
    line = next((line.strip() for line in (text or '').splitlines() if line.strip()), '')
    line = DIGITS.sub('N', line)
    return REGISTRY_NAME.sub('<key>', SPACES.sub(' ', line))


def red_stages(payload):
    return [stage for stage in payload.get('stages', []) if stage.get('result') == 'FAIL']


def inputs(event):
    """One input per distinct signature: a gate.failed is split into one envelope per failing test signature (and one
    per red stage without a failing test); every other event is its own single input."""
    if event.get('type') != 'gate.failed':
        return [event]
    payload, found = event['payload'], {}
    stages = {stage['name']: stage for stage in red_stages(payload)}
    for test in payload.get('failing_tests') or []:
        part = dict(payload, failing_tests=[test], stages=[stages[test['stage']]] if test['stage'] in stages else [])
        found.setdefault(signature(dict(event, payload=part)), dict(event, payload=part))
    covered = {test['stage'] for test in payload.get('failing_tests') or []}
    for name, stage in stages.items():
        if name not in covered:
            part = dict(payload, failing_tests=[], stages=[stage])
            found.setdefault(signature(dict(event, payload=part)), dict(event, payload=part))
    return list(found.values()) or [event]


def signature(event):
    """The dedupe key of an input: failure signature, lesson class, premise id or defect id."""
    payload, kind, name = event['payload'], event.get('type', ''), source(event)
    if kind == 'gate.failed':
        tests = payload.get('failing_tests') or []
        if tests:
            return f'{FAILURE}:{canonical(tests[0]["signature"])}'
        stage = (red_stages(payload) or [{'name': 'gate', 'class': None}])[0]
        return f'{FAILURE}:{stage["name"]}:{stage.get("class")}'
    if name == 'lesson':
        return f'lesson:{payload["class"]}'
    if name == 'note':
        return f'note:{payload["kind"]}:{canonical(payload["text"])}'
    if name == 'premise':
        return f'premise:{payload["id"]}'
    if name == 'defect':
        return f'defect:{payload["defect"]}'
    if name == 'owner':
        return f'owner:{payload["by"]}:{payload["at"]}'
    if name == 'overrun':
        return f'overrun:{payload["unit"]}'
    return f'{name}:{kind}:{payload.get("unit") or payload.get("test") or payload.get("sha")}'


def classes(event):
    return {stage.get('class') for stage in red_stages(event['payload'])}


def by_event_id(plan):
    return {program.unit_event_id(unit['id']): unit['id'] for unit in plan['units']}


def producer(event, plan):
    """The program unit id that produced the input, or None."""
    payload = event['payload']
    raw = payload.get('from_unit') or payload.get('source_unit') or payload.get('unit')
    return by_event_id(plan).get(program.unit_event_id(raw)) if raw else None


def stages(plan, history):
    return {row['id']: row for row in program.status(plan, list(history))}


def active(plan, history):
    """Unit ids not merged yet, in plan order."""
    rows = stages(plan, history)
    return [unit['id'] for unit in plan['units'] if rows[unit['id']]['stage'] != 'merged']


def matches(path, patterns):
    """A path inside a glob of patterns, or a glob (a note's area) that covers one of the patterns."""
    path = path.strip('/')
    return any(fnmatch.fnmatchcase(path, pattern.strip('/')) or fnmatch.fnmatchcase(pattern.strip('/'), path)
               for pattern in patterns)


def by_area(paths, plan):
    return [unit['id'] for unit in plan['units'] if any(matches(path, unit.get('area') or []) for path in paths)]


def dependents(unit_id, plan):
    """unit_id and every unit that depends on it, directly or not."""
    found, frontier = [unit_id], [unit_id]
    while frontier:
        current = frontier.pop()
        for unit in plan['units']:
            if current in unit['depends_on'] and unit['id'] not in found:
                found.append(unit['id'])
                frontier.append(unit['id'])
    return found


def citing(premise_id, plan, history, prs=()):
    """Units whose events cite the premise, or whose PR is in prs."""
    ids, rows = by_event_id(plan), stages(plan, history)
    found = {ids[e['payload']['unit']] for e in history
             if e['payload'].get('unit') in ids and premise_id in (e['payload'].get('premises') or [])}
    found |= {name for name, row in rows.items() if row['pr'] is not None and row['pr'] in prs}
    return [unit['id'] for unit in plan['units'] if unit['id'] in found]


def affected(event, plan, history=()):
    """Unit ids the input touches: owned paths and areas, units citing the premise, pending units of the lane, explicit affects."""
    payload, name, live = event['payload'], source(event), active(plan, history)
    if name in ('owner', 'train') or (name == 'base' and event.get('type') != 'gate.failed'):
        return [ALL]
    if name in ('gate', 'base') and (name == 'base' or classes(event) & set(CROSS_CUTTING)):
        return [ALL]
    found = []
    if name == 'note':
        ids = {unit['id'].lower(): unit['id'] for unit in plan['units']}
        if ALL in payload['affects']:
            return [ALL]
        for entry in payload['affects']:
            found += [ids[entry.lower()]] if entry.lower() in ids else by_area([entry], plan)
    elif name in ('gate', 'flake', 'defect'):
        paths = [test['id'] for test in payload.get('failing_tests') or []]
        paths += [payload[key] for key in ('test', 'area') if payload.get(key)]
        found = by_area(paths, plan) + [unit for unit in [producer(event, plan)] if unit]
    elif name == 'premise':
        found = citing(payload['id'], plan, history, (payload.get('dependents') or {}).get('prs', ()))
    elif name == 'lesson':
        source_unit = producer(event, plan)
        lane = next((unit['owner'] for unit in plan['units'] if unit['id'] == source_unit), payload.get('owner'))
        found = [unit['id'] for unit in plan['units'] if unit['owner'] == lane and unit['id'] != source_unit]
    elif name == 'overrun':
        found = dependents(producer(event, plan), plan)
    elif name == 'session':
        found = [unit for unit in [producer(event, plan)] if unit]
    return [unit for unit in live if unit in found]


def moment(event):
    return datetime.fromisoformat(event['occurred_at'].replace('Z', '+00:00'))


def estimate_of(unit, plan):
    """Minutes: the latest set_estimate the live plan folded (plan_live `records`, args.estimate), else the unit's own
    `estimate`, else None."""
    folded = [item['args'].get(ESTIMATE) for item in plan.get('records', [])
              if item.get('op') == 'set_estimate' and item.get('unit') == unit and (item.get('args') or {}).get(ESTIMATE)]
    row = next((item for item in plan['units'] if item['id'] == unit), {})
    return folded[-1] if folded else row.get(ESTIMATE)


def overrun(unit, plan, events):
    """True when the unit's time since work.assigned passes its estimate times planner.overrun_factor (evaluated per event)."""
    estimate = estimate_of(unit, plan)
    if not estimate:
        return False
    own, assigned_kind = program.unit_event_id(unit), config.get('coordinator.event_assigned')
    mine = [e for e in events if e['payload'].get('unit') == own or own in (e['payload'].get('units') or [])]
    assigned = next((e for e in mine if e['type'] == assigned_kind), None)
    if assigned is None:
        return False
    elapsed_s = (moment(mine[-1]) - moment(assigned)).total_seconds()
    return elapsed_s > timedelta(minutes=estimate * setting('overrun_factor')).total_seconds()


def ref(event):
    return event.get('event_id') or f'{event.get("type")}@{event.get("occurred_at")}'


def partition(name, plan, unit, found):
    """(program, area) key: engine for cross-program inputs, else the lane of the producer or first affected unit."""
    if name in ENGINE_SOURCES:
        return ENGINE_PARTITION
    lanes = {item['id']: item['owner'] for item in plan['units']}
    lane = lanes.get(unit) or next((lanes[item] for item in found if item in lanes), ALL)
    return f'{plan["program"]}:{lane}'


def triage(event, plan, seen=None, history=()):
    """A plan.candidate payload (disposition candidate, or seen with its reason) for one input event.

    `seen` is the candidates already known, so a second sighting of a signature updates its count and affected list;
    the payload is stored back into it. `history` is the log up to this event (unit stages, premise citations)."""
    seen = {} if seen is None else seen
    key, name, payload = signature(event), source(event), event['payload']
    prior = seen.get(key) or {}
    unit = producer(event, plan)
    order = [ALL] + [item['id'] for item in plan['units']]
    found = set(prior.get('affected', [])) | set(affected(event, plan, history))
    found = [ALL] if ALL in found else [item for item in order if item in found]
    sightings, promote = prior.get('sightings', 0) + 1, setting('triage_promote_sightings')
    reasons = []
    if name in ALWAYS:
        reasons.append(f'{name} input')
    reasons += [f'class {klass}' for klass in sorted(classes(event) & set(CROSS_CUTTING))]
    if name == 'base':
        reasons.append('seen on the base')
    others = [item for item in found if item != unit]
    if others:
        reasons.append('touches ' + ', '.join(others))
    if sightings >= promote:
        reasons.append(f'{sightings} sightings (planner.triage_promote_sightings {promote})')
    if prior.get('disposition') == 'candidate' or (reasons and found):
        disposition, reason = 'candidate', '; '.join(reasons) or prior['reason']
    elif reasons:
        disposition, reason = 'seen', 'touches no active unit (' + '; '.join(reasons) + ')'
    else:
        disposition = 'seen'
        reason = f'touches only {unit or "no unit"}; {sightings} of {promote} sightings'
    raw = prior.get('unit') or (program.unit_event_id(unit) if unit else None)
    result = {'repo': payload.get('repo') or config.get('forge-events.repo'), 'pr': None, 'sha': None, 'unit': raw,
              'premises': list(dict.fromkeys(prior.get('premises', []) + list(payload.get('premises') or []))),
              'program': plan['program'], 'signature': key, 'disposition': disposition, 'reason': reason,
              'source': prior.get('source') or name, 'inputs': list(dict.fromkeys(prior.get('inputs', []) + [ref(event)])),
              'sightings': sightings, 'affected': found, 'partition': prior.get('partition') or partition(name, plan, unit, found)}
    seen[key] = result
    return result


def overrun_input(unit, event):
    """The derived input for a unit found over its estimate when `event` arrived."""
    repo = event['payload'].get('repo') or config.get('forge-events.repo')
    payload = forge_events.subject(repo, None, None, (), program.unit_event_id(unit))
    return {'type': OVERRUN, 'occurred_at': event.get('occurred_at'), 'event_id': f'{OVERRUN}:{ref(event)}', 'payload': payload}


def relevant(event, plan):
    """Triage reads the input types of design 1.1 and, for notes and rulings, only the program's own."""
    if source(event) is None:
        return False
    return event['payload'].get('program', plan['program']) == plan['program']


def triage_all(events, plan, seen=None):
    """Replay a log in order: every input, split per signature, plus the derived overrun inputs. Returns {signature:
    payload} with the latest disposition, sightings and affected set of each signature."""
    seen = {} if seen is None else seen
    for index, event in enumerate(events):
        history = events[:index + 1]
        if relevant(event, plan):
            for part in inputs(event):
                triage(part, plan, seen, history)
        unit = producer(event, plan) if event.get('payload') else None
        if unit and f'{OVERRUN}:{program.unit_event_id(unit)}' not in seen and overrun(unit, plan, history):
            triage(overrun_input(unit, event), plan, seen, history)
    return seen


UNIT_ID = re.compile(r'^[a-z0-9][a-z0-9-]*$')  # contracts/events/defs.v1.json unit
PRODUCER = 'plan'
HELP = """Live planning (D-071): pass information on to the planner and keep going; triage of plan inputs.

The Padrão rule: fix what is yours; for anything that touches other units, run `plan note` the moment you know, then
keep going. Nobody waits for an answer: the planner reads the candidates triage produces (plan.candidate).

  plan note --program P --from UNIT --affects UNITS|AREAS|all --kind blocker|lesson|premise|estimate|engine
            --evidence REF "one line"        emit one plan.note (a running session's finding) and return
  plan input --program P --by "Daniel"|"A Torre" [--at RFC3339] [--ref WHERE] "ruling"
                                             turn an owner ruling into one plan.input
  plan triage --program P [--events FILE] [--plan FILE] [--publish]
                                             triage the program's inputs (the repository log and its units' PR logs,
                                             or FILE: a JSON array or JSON Lines of envelopes) and print one JSON
                                             line per signature; --publish emits each candidate as plan.candidate
                                             (once per signature: later sightings show in the printed lines)

Every event goes through the forge_events port (the registry's forge-events.adapter, or --log-dir DIR for a local file
log). Thresholds: planner.triage_promote_sightings, planner.overrun_factor."""


def port(args, command):
    adapter = forge_events.FileAdapter(args.log_dir) if args.log_dir else forge_events.adapter_from_config()
    return forge_events.ForgeEvents(adapter, forge_events.clock_from_config(), PRODUCER, f'{PRODUCER}-{command}')


def unit_of(name):
    raw = program.unit_event_id(name or '')
    return raw if UNIT_ID.match(raw) else None


def listed(values):
    return [item for value in values for item in value.split(',') if item]


def head(args, unit=None):
    return forge_events.subject(args.repo or config.get('forge-events.repo'), args.pr, args.sha, listed(args.premises), unit)


def note(args):
    """`plan note`: emit one plan.note and return at once."""
    payload = dict(head(args, unit_of(args.from_unit)), program=args.program, from_unit=args.from_unit,
                   affects=listed(args.affects), kind=args.kind, evidence=args.evidence, text=args.text)
    return port(args, 'note').emit('plan.note', payload)


def owner_input(args):
    """`plan input`: turn an owner ruling into one plan.input."""
    events = port(args, 'input')
    at = args.at or forge_events.rfc3339(events.clock.now())
    payload = dict(head(args), program=args.program, by=args.by, at=at, text=args.text, ref=args.ref)
    return events.emit('plan.input', payload)


def read_events(path):
    text = Path(path).read_text()
    return json.loads(text) if text.lstrip().startswith('[') else [json.loads(line) for line in text.splitlines() if line.strip()]


def run_triage(args):
    """`plan triage`: triage events from the forge log (or --events FILE) and print the candidates."""
    plan = json.loads(Path(args.plan).read_text()) if args.plan else program.load(args.program)
    events = port(args, 'triage')
    if args.events:
        log = read_events(args.events)
    else:
        repo = args.repo or config.get('forge-events.repo')
        log = events.read_recent(repo)  # D-085: the shared window of the repository channel
        for number in sorted({unit['pr'] for unit in plan['units'] if unit.get('pr')}):
            log += events.read(repo, number)
        log.sort(key=lambda event: event['occurred_at'])
    found = list(triage_all(log, plan).values())
    if args.publish:
        events.publish([events.build('plan.candidate', item) for item in found if item['disposition'] == 'candidate'])
    return found


def parser():
    top = argparse.ArgumentParser(prog='plan', description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--program', required=True)
    common.add_argument('--log-dir', help='local file log (forge_events.FileAdapter) instead of the registry adapter')
    common.add_argument('--repo', help='default forge-events.repo')
    common.add_argument('--pr', type=int, help='the channel (PR) to write on; default the repository log')
    common.add_argument('--sha')
    common.add_argument('--premises', action='append', default=[], help='P-ids, repeatable or comma separated')
    commands = top.add_subparsers(dest='command', required=True)
    item = commands.add_parser('note', parents=[common], help='pass a finding on to the planner and keep going')
    item.add_argument('--from', dest='from_unit', required=True)
    item.add_argument('--affects', action='append', required=True, help='unit ids, areas or all; repeatable or comma separated')
    item.add_argument('--kind', required=True, help='blocker, lesson, premise, estimate or engine')
    item.add_argument('--evidence', required=True, help='a ref: PR, commit, event id, log path')
    item.add_argument('text')
    item = commands.add_parser('input', parents=[common], help='record an owner ruling')
    item.add_argument('--by', required=True, help='Daniel or A Torre')
    item.add_argument('--at', help='RFC 3339 time of the ruling; default now')
    item.add_argument('--ref', help='where it was said')
    item.add_argument('text')
    item = commands.add_parser('triage', parents=[common], help='triage the inputs and print one line per signature')
    item.add_argument('--events', help='JSON array or JSON Lines of envelopes instead of the forge log')
    item.add_argument('--plan', help='program.v1 JSON (e.g. a folded live plan) instead of the program plan.md')
    item.add_argument('--publish', action='store_true', help='emit each candidate as plan.candidate')
    return top


def main(argv=None):
    """CLI entry of scripts/plan."""
    args = parser().parse_args(argv)
    try:
        if args.command == 'triage':
            for item in run_triage(args):
                print(json.dumps(item, sort_keys=True))
        else:
            print((note if args.command == 'note' else owner_input)(args)['event_id'])
    except (event_contracts.ContractError, forge_events.ForgeEventsError, program.ProgramError, OSError, ValueError) as error:
        print(f'plan {args.command}: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
