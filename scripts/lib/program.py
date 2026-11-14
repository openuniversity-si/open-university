"""Programs as first-class objects (D-069 CO1): the registry, the plan graph and the status folded from events.

A program is docs/programs/<program>/{brief,audit,plan,retro}.md; one created after D-077 also carries intake.md and research.md. plan.md carries the PR graph as a fenced data block
(contracts/programs/program.v1.json). Status is never written down: status() folds the forge events of the program's
units, so the same log gives the same view. Every location and name is a coordinator.* registry entry.

CLI: program.py list | check [PROGRAM] | graph PROGRAM | status PROGRAM [--events FILE] | new PROGRAM
     | migrate-queue FILE PROGRAM | plan PROGRAM [--at N] | log PROGRAM
`plan` prints the live plan folded at version N (default the head; scripts/lib/plan_live.py, D-071) and `log` one line
per version (version, parent, decided_by, intention, digest). Both read the plan log from <push-guard.remote>/
<planner.log_branch> (--ref another ref, --worktree the checkout's file); a missing log is version 0. Read-only.
"""
import argparse
import json
from pathlib import Path
import re
import sys

import config
import json_schema

ROOT = Path(__file__).resolve().parents[2]
STAGES = ('pending', 'running', 'open', 'ready', 'merged', 'failed')
LAUNCHABLE, BLOCKED = 'launchable', 'blocked'


class ProgramError(ValueError):
    pass


def setting(name, root=None):
    """A coordinator.* registry value; the registry is always this checkout's, root only moves the program files."""
    return config.get(f'coordinator.{name}')


def base(root=None):
    return Path(root or ROOT)


def programs_dir(root=None):
    return base(root) / setting('programs_dir', root)


def names(root=None):
    """Program folder names, the template excluded."""
    folder, template = programs_dir(root), setting('template_dir', root)
    return sorted(path.name for path in folder.iterdir() if path.is_dir() and path.name != template) if folder.is_dir() else []


def plan_block(text, fence):
    found = re.search(r'^```' + re.escape(fence) + r'[ \t]*\n(.*?)^```[ \t]*$', text, re.M | re.S)
    if not found:
        raise ProgramError(f'no ```{fence} block')
    return json.loads(found.group(1))


def schema(root=None):
    return json.loads((base(root) / setting('program_schema', root)).read_text())


def graph_problems(program):
    """Problems of the graph beyond the schema: unique ids, known dependencies, no cycle, dependencies in an earlier or
    equal wave."""
    units = {unit['id']: unit for unit in program['units']}
    problems = []
    if len(units) != len(program['units']):
        problems.append('duplicate unit id')
    for unit in program['units']:
        for dep in unit['depends_on']:
            if dep not in units:
                problems.append(f'{unit["id"]} depends on unknown {dep}')
            elif units[dep]['wave'] > unit['wave']:
                problems.append(f'{unit["id"]} (wave {unit["wave"]}) depends on {dep} (wave {units[dep]["wave"]})')
    state = {}

    def visit(name, trail):
        if state.get(name) == 'done' or name not in units:
            return
        if state.get(name) == 'open':
            problems.append('cycle: ' + ' -> '.join(trail + [name]))
            return
        state[name] = 'open'
        for dep in units[name]['depends_on']:
            visit(dep, trail + [name])
        state[name] = 'done'

    for name in units:
        visit(name, [])
    return problems


def load(name, root=None):
    """The validated plan of a program; ProgramError names every problem."""
    folder = programs_dir(root) / name
    plan = folder / setting('plan_file', root)
    if not plan.is_file():
        raise ProgramError(f'{name}: {plan.name} is missing')
    program = plan_block(plan.read_text(), setting('plan_fence', root))
    errors = json_schema.validate(schema(root), program)
    errors = [str(error) for error in errors] if errors else []
    if program.get('program') != name:
        errors.append(f'program is {program.get("program")!r}, the folder is {name!r}')
    if not errors:
        errors = graph_problems(program)
    if errors:
        raise ProgramError(f'{name}: ' + '; '.join(errors))
    return program


def check(name, root=None):
    """Problems of a program folder (empty when sound): its files, then its plan."""
    folder, problems = programs_dir(root) / name, []
    for file in setting('program_files', root):
        if not (folder / file).is_file():
            problems.append(f'{name}: {file} is missing')
    try:
        load(name, root)
    except (ProgramError, ValueError) as error:
        problems.append(str(error))
    return problems


def unit_event_id(unit_id):
    return unit_id.lower()


def fold(unit_id, events, root=None, unit_pr=None):
    """The stage and PR of one unit from its events, in log order. A merge is evidence by the unit's id or by its PR
    (unit_pr, the plan's pr): a unit done outside the launch carries a manifest id in pr.merged (F1, D-204)."""
    kinds = {name: setting(f'event_{name}', root) for name in ('assigned', 'opened', 'ready', 'merged', 'ended', 'failed')}
    stage, pr = 'pending', None
    for event in events:
        payload = event['payload']
        kind = event['type']
        by_pr = unit_pr is not None and kind == kinds['merged'] and payload.get('pr') == unit_pr
        if payload.get('unit') != unit_event_id(unit_id) and not by_pr:
            continue
        if payload.get('pr') is not None:
            pr = payload['pr']
        if stage == 'merged':
            continue
        if kind == kinds['assigned']:
            stage = 'running'
        elif kind == kinds['opened']:
            stage = 'open'
        elif kind == kinds['ready']:
            stage = 'ready'
        elif kind == kinds['merged']:
            stage = 'merged'
        elif kind == kinds['failed'] and stage in ('pending', 'running'):
            stage = 'failed'
        elif kind == kinds['ended'] and stage == 'running':
            stage = 'pending'
    return stage, pr


def status(program, events, root=None):
    """One row per unit: stage, PR, and for a pending unit whether it can launch or what blocks it."""
    rows = {}
    for unit in program['units']:
        stage, pr = fold(unit['id'], events, root, unit.get('pr'))
        rows[unit['id']] = {'id': unit['id'], 'wave': unit['wave'], 'owner': unit['owner'], 'stage': stage,
                            'pr': pr if pr is not None else unit.get('pr'), 'blocked_by': []}
    for unit in program['units']:
        row = rows[unit['id']]
        if row['stage'] in ('pending', 'failed'):
            row['blocked_by'] = [dep for dep in unit['depends_on'] if rows[dep]['stage'] != 'merged']
    return list(rows.values())


def render_status(program, rows):
    merged = sum(row['stage'] == 'merged' for row in rows)
    lines = [f'{program["program"]}: {merged}/{len(rows)} merged',
             f'goal: {program["complaint"]["goal"]["metric"]} {program["complaint"]["goal"]["comparator"]} '
             f'{program["complaint"]["goal"]["target"]} {program["complaint"]["goal"]["unit"]}']
    for row in sorted(rows, key=lambda item: (item['wave'], item['id'])):
        note = f' blocked by {",".join(row["blocked_by"])}' if row['blocked_by'] else ''
        pr = f' #{row["pr"]}' if row['pr'] else ''
        lines.append(f'  w{row["wave"]} {row["id"]:<6} {row["stage"]:<8}{pr}{note}')
    return '\n'.join(lines)


def template(root=None):
    return programs_dir(root) / setting('template_dir', root)


def create(name, root=None):
    """A new program folder from the template."""
    target = programs_dir(root) / name
    if target.exists():
        raise ProgramError(f'{name} exists')
    target.mkdir(parents=True)
    for file in [item['file'] for item in config.get('intake.program_files')] + list(setting('program_files', root)):  # v8 files first, D-115
        text = (template(root) / file).read_text().replace('<program>', name)
        (target / file).write_text(text)
    return target


def migrate_queue(queue, name):
    """Units of a program draft from a v3 queue.json: a list (or {"units": [...]}) of items with id, depends_on, wave,
    owner and model; absent fields become the fields the contract requires, to be edited."""
    items = queue['units'] if isinstance(queue, dict) else queue
    units = []
    for item in items:
        units.append({'id': item['id'], 'depends_on': list(item.get('depends_on', [])), 'owner': item.get('owner', 'unassigned'),
                      'model': item.get('model', 'unassigned'), 'wave': int(item.get('wave', 1)),
                      'done': item.get('done') or ['merged to the base with the gate green']})
    return {'contract': 'program.v1', 'program': name, 'units': units}


def dump(value):
    """The JSON a subcommand prints for a person to read."""
    return json.dumps(value, indent=2)


def read_events(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('list')
    sub.add_parser('check').add_argument('program', nargs='?')
    sub.add_parser('graph').add_argument('program')
    show = sub.add_parser('status')
    show.add_argument('program')
    show.add_argument('--events', help='JSON-lines file of event envelopes; default: the forge port')
    sub.add_parser('new').add_argument('program')
    migrate = sub.add_parser('migrate-queue')
    migrate.add_argument('queue')
    migrate.add_argument('program')
    for command, text in (('plan', 'the live plan at version N (default the head)'), ('log', 'the plan versions')):
        live = sub.add_parser(command, help=text)
        live.add_argument('program')
        if command == 'plan':
            live.add_argument('--at', type=int, help='version to fold up to; 0 is plan.md')
        source = live.add_mutually_exclusive_group()
        source.add_argument('--ref', help='git ref holding the plan log; default <push-guard.remote>/<planner.log_branch>')
        source.add_argument('--worktree', action='store_true', help="read the checkout's plan log file")
        live.add_argument('--root', help='checkout to read (default this one)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'list':
            print('\n'.join(names()))
        elif args.command == 'check':
            problems = [problem for name in ([args.program] if args.program else names()) for problem in check(name)]
            print('\n'.join(problems) or 'programs ok')
            return 1 if problems else 0
        elif args.command == 'graph':
            program = load(args.program)
            for unit in sorted(program['units'], key=lambda item: (item['wave'], item['id'])):
                print(f'w{unit["wave"]} {unit["id"]} <- {",".join(unit["depends_on"]) or "-"}')
        elif args.command == 'status':
            program = load(args.program)
            events = read_events(args.events) if args.events else live_events(program)
            print(render_status(program, status(program, events)))
        elif args.command == 'new':
            print(create(args.program))
        elif args.command == 'migrate-queue':
            print(dump(migrate_queue(json.loads(Path(args.queue).read_text()), args.program)))
        elif args.command in ('plan', 'log'):
            return live_plan(args)
    except ProgramError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def live_plan(args):
    """`plan` and `log`: the live plan folded from the plan log (plan_live.py)."""
    import plan_live
    ref = None if args.worktree else args.ref or f"{config.get('push-guard.remote')}/{config.get('planner.log_branch')}"
    try:
        if args.command == 'plan':
            print(dump(plan_live.plan_at(args.program, args.at, args.root, ref)))
        else:
            for change in plan_live.read_log(args.program, args.root, ref):
                print('\t'.join(str(field) for field in (change['version'], change['parent']['version'], change['decided_by'],
                                                          change['intention'], change['digest'])))
    except plan_live.PlanError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def live_events(program):
    """The repository channel plus the channel of every PR the program's units name or the base has open."""
    import forge_events
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(), 'program', 'program-status')
    repo = config.get('forge-events.repo')
    numbers = {unit['pr'] for unit in program['units'] if unit.get('pr')}
    events = port.read_recent(repo)  # D-085: the shared window of the repository channel
    for number in sorted(numbers):
        events += port.read(repo, number)
    return events


if __name__ == '__main__':
    sys.exit(main())
