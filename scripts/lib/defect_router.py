"""The known-defect router (KD1, D-069 items 4, 8 and 9): price a defect by what it does to the PR queue, then open its fix unit.

Priority is impact on the queue and never a clock or a deadline: nothing here reads the time to rank. A defect's weight
is defects.weight_touching_unit for every open PR whose units include the defect's unit, defects.weight_dependent_unit
for every unit that (transitively) requires it, and defects.weight_masked_test for every script test that covers its
area or its own test. The class comes from the two thresholds.

  queue(port, repo, base)               [{pr, units}] of the open changes, from their latest queue event
  impact(record, queue, root)           priority, class, touching PRs, dependent units, masked tests
  route(root, port, repo, base_sha, queue, by, clock)
                                        for every open defect at or above defects.fix_unit_min_priority: work.assigned to
                                        the owner, the record to `fixing` with its fix object, defect.routed. Idempotent.

scripts/defects route|priority call main() here.
"""
import argparse
from pathlib import Path
import sys

import config
import defect_detect
import defects
import forge_events
import gate_areas
import gate_script_tests
import units

ROOT = Path(__file__).resolve().parents[2]


def setting(name):
    return config.get(f'defects.{name}')


def queue(port, repo, base_branch):
    """[{pr, units}] of every open change whose latest event of a defects.queue_events type names units."""
    kinds, found = setting('queue_events'), []
    for number in port.open_changes(repo, base_branch):
        events = [event for event in port.read(repo, number) if event['type'] in kinds]
        named = events[-1]['payload'].get('units') if events else None
        if named:
            found.append({'pr': number, 'units': sorted(named)})
    return sorted(found, key=lambda item: item['pr'])


def dependents(unit, root):
    """Units whose requires closure reaches `unit`."""
    manifests = units.manifests(root)
    reached, grew = set(), True
    while grew:
        grew = False
        for name, manifest in manifests.items():
            if name not in reached and any(need == unit or need in reached for need in manifest.get('requires') or {}):
                reached.add(name)
                grew = True
    return sorted(reached)


def masked(record, mapping):
    """Script tests whose covers match a path glob of the defect's area or the defect's own test file."""
    paths = list(record['area']) + record['test'].split(' > ', 1)[0].split()
    return sum(1 for item in mapping['tests']
               if any(gate_areas.glob_match(path, cover) or gate_areas.glob_match(cover, path)
                      for cover in item['covers'] for path in paths))


def impact(record, queue, root, mapping=None):
    unit = record['unit']
    touching = sorted(item['pr'] for item in queue if unit and unit in item['units'])
    needing = dependents(unit, root) if unit else []
    covered = masked(record, mapping or gate_script_tests.load(root=root)) if unit else 0
    priority = (setting('weight_touching_unit') * len(touching) + setting('weight_dependent_unit') * len(needing)
                + setting('weight_masked_test') * covered)
    names = setting('priority_classes')
    level = len(names) - 1 if priority >= setting('critical_priority') else \
        len(names) - 2 if priority >= setting('high_priority') else 0
    return {'priority': priority, 'class': names[level], 'touching': touching, 'dependent_units': needing,
            'masked': covered, 'units': [unit] if unit else []}


def priced(root, queue_, mapping=None):
    """[(record, impact)] of every open defect, highest priority first, ties by id."""
    records, errors = defects.load(root)
    if errors:
        raise defects.DefectError('; '.join(errors))
    rows = [(record, impact(record, queue_, root, mapping)) for record in records.values()
            if record['status'] == setting('statuses')[0]]
    return sorted(rows, key=lambda row: (-row[1]['priority'], row[0]['id']))


def route(root, port, repo, base_sha, queue, by, clock=None):
    """The routed [{id, priority, class}], highest priority first. A defect already fixing is not open and is skipped."""
    routed = []
    with port.batched():  # GX-FIX-forge-rate: one append for every routed defect
        for record, cost in priced(root, queue):
            if cost['priority'] < setting('fix_unit_min_priority'):
                continue
            item = setting('fix_item').format(id=record['id'])
            assigned = port.emit('work.assigned', dict(
                forge_events.subject(repo, None, base_sha, (), record['unit']),
                lane_id=record['owner'], units=cost['units'], item=item))
            fix = {'lane': record['owner'], 'item': item, 'work_event': assigned['event_id'], 'pr': None, 'merge_sha': None}
            note = setting('route_note').format(priority=cost['priority'], **{'class': cost['class']})
            defects.transition(root, record['id'], setting('statuses')[1], by, note, fix=fix, clock=clock)
            waiting = cost['touching'] if cost['priority'] >= setting('depends_min_priority') else []
            defects.emit(port, 'defect.routed', record, root, base_sha, {
                'priority': cost['priority'], 'class': cost['class'], 'fix_item': item, 'work_event': assigned['event_id'],
                'touching': cost['touching'], 'dependents': waiting, 'masked': cost['masked']})
            routed.append({'id': record['id'], 'priority': cost['priority'], 'class': cost['class']})
    return routed


def base_sha_of(root):
    found = defect_detect.resolve_base(root)
    if found is None:
        raise defects.DefectError(f'cannot resolve {config.get("gate.batch_base_ref")}; pass --base-sha')
    return found


def main(argv=None, root=ROOT, port=None):
    parser = argparse.ArgumentParser(prog='scripts/defects', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    walk = sub.add_parser('route')
    walk.add_argument('--base-sha')
    walk.add_argument('--by', default=setting('router_by'))
    sub.add_parser('priority')
    args = parser.parse_args(argv)
    try:
        if port is None:
            port = defects._port(setting('producer'), f'{setting("producer")}:{args.command}')
        waiting = queue(port, config.get('forge-events.repo'), config.get('train.base_branch'))
        if args.command == 'priority':
            for record, cost in priced(root, waiting):
                print(record['id'], cost['class'], cost['priority'], 'touching=' + (','.join(map(str, cost['touching'])) or '-'),
                      'dependents=' + (','.join(cost['dependent_units']) or '-'))
            return 0
        for item in route(root, port, config.get('forge-events.repo'), args.base_sha or base_sha_of(root), waiting, args.by):
            print(item['id'], item['class'], item['priority'])
    except (defects.DefectError, forge_events.ForgeEventsError) as error:
        print(f'defects: {error}', file=sys.stderr)
        return 2
    return 0
