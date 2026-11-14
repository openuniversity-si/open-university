"""The program gate and program retro (D-069 CO1): the complaint measured as solved, and the unit retros aggregated.

The gate passes when every unit of the program is merged (program.status over the event log) and the program's measurable
goal holds, measured from pr.merged events over the trailing coordinator.goal_window_s. The retro aggregates each unit's
retro (docs/units/<unit>/retro.md, its Lessons section) and lists the lessons marked padrao_candidate through the
lessons port (LR1; empty when the registry is absent).

CLI: program_gate.py check PROGRAM [--events FILE] [--now RFC3339]     exit 0 when the program gate passes
     program_gate.py retro PROGRAM [--write]                            print (or write retro.md of) the program retro
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys

import config
import coordinator
import coordinator_launch
import program as programs

ROOT = programs.ROOT


class GateError(ValueError):
    pass


def merged_in_window(events, now):
    since = now - timedelta(seconds=config.get('coordinator.goal_window_s'))
    kind = config.get('coordinator.event_merged')
    return [event for event in events if event['type'] == kind and since <= coordinator.moment(event['occurred_at']) <= now]


def measure(metric, events, now):
    """The metric's value over the trailing window. Per-hour is the window count scaled to an hour; per-day to a day."""
    if metric not in config.get('coordinator.metrics'):
        raise GateError(f'unknown metric {metric}; registered: {config.get("coordinator.metrics")}')
    count, window = len(merged_in_window(events, now)), config.get('coordinator.goal_window_s')
    unit_seconds = 3600 if metric.endswith('per_hour') else 86400
    return count * unit_seconds / window


def holds(value, goal):
    return value >= goal['target'] if goal['comparator'] == 'gte' else value <= goal['target']


def evaluate(plan, events, now):
    """{merged, total, unmerged, metric, value, target, goal_met, passed}."""
    rows = programs.status(plan, events)
    unmerged = sorted(row['id'] for row in rows if row['stage'] != 'merged')
    goal = plan['complaint']['goal']
    value = measure(goal['metric'], events, now)
    met = holds(value, goal)
    return {'merged': len(rows) - len(unmerged), 'total': len(rows), 'unmerged': unmerged, 'metric': goal['metric'],
            'value': round(value, 3), 'target': goal['target'], 'goal_met': met, 'passed': not unmerged and met}


def render_gate(plan, result):
    verdict = 'PASS' if result['passed'] else 'FAIL'
    lines = [f'program gate {plan["program"]}: {verdict}',
             f'units: {result["merged"]}/{result["total"]} merged' + (f'; waiting: {", ".join(result["unmerged"])}' if result['unmerged'] else ''),
             f'goal: {result["metric"]} = {result["value"]} (target {plan["complaint"]["goal"]["comparator"]} {result["target"]}): '
             + ('met' if result['goal_met'] else 'not met')]
    return '\n'.join(lines)


def lessons_section(text, limit):
    """The Lessons section of a unit retro (up to the next heading of the same or higher level), cut at limit lines."""
    heading = re.compile(config.get('coordinator.retro_heading'), re.M)
    found = heading.search(text)
    if not found:
        return None
    level = len(re.match(r'#+', found.group(0)).group(0))
    body = []
    for line in text[found.end():].splitlines()[1:]:
        match = re.match(r'(#+)\s', line)
        if match and len(match.group(1)) <= level:
            break
        body.append(line)
    lines = [line for line in body if line.strip()]
    return lines[:limit]


def retro(plan, lessons=None, root=None):
    """The program retro as Markdown: one section per unit retro, then the padrao_candidate lessons."""
    lessons = lessons or coordinator_launch.NullLessons()
    base = Path(root or ROOT)
    limit, marker = config.get('coordinator.retro_section_lines'), config.get('coordinator.retro_marker')
    out = [f'# Program {plan["program"]}: retro', '',
           'Aggregated from the unit retros; lessons that should change the Padrão carry the marker.', '']
    missing = []
    for unit in plan['units']:
        path = base / config.get('coordinator.unit_retro_path').format(unit=unit['id'])
        if not path.is_file():
            missing.append(unit['id'])
            continue
        section = lessons_section(path.read_text(), limit)
        out += [f'## {unit["id"]}' + (f': {unit["title"]}' if unit.get('title') else ''), '']
        out += section if section else [f'No Lessons section in {path.relative_to(base)}.']
        out.append('')
    out += ['## Units without a retro', ''] + ([f'- {name}' for name in missing] or ['None.']) + ['']
    candidates = lessons.candidates([unit['id'] for unit in plan['units']])
    out += [f'## Padrão candidates ({marker})', ''] + ([f'- {marker}: {line}' for line in candidates] or ['None.']) + ['']
    return '\n'.join(out)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/program-gate', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    check = sub.add_parser('check')
    check.add_argument('program')
    check.add_argument('--events')
    check.add_argument('--now', help='RFC3339 instant the window ends at (default: now)')
    summary = sub.add_parser('retro')
    summary.add_argument('program')
    summary.add_argument('--write', action='store_true', help='write retro.md of the program instead of printing')
    args = parser.parse_args(argv)
    try:
        plan = programs.load(args.program)
        if args.command == 'check':
            events = programs.read_events(args.events) if args.events else programs.live_events(plan)
            now = coordinator.moment(args.now) if args.now else datetime.now(timezone.utc)
            result = evaluate(plan, events, now)
            print(render_gate(plan, result))
            return 0 if result['passed'] else 1
        text = retro(plan, coordinator_launch.lessons_port(ROOT))
        if args.write:
            target = programs.programs_dir() / args.program / config.get('coordinator.program_files')[-1]
            target.write_text(text)
            print(target)
        else:
            print(text)
    except (programs.ProgramError, GateError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
