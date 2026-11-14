"""The lane-briefs target of scripts/generate (D-236, lane 12): the start brief of every unit of a program.

The program's plan.md carries its units in one `program.v1` block. Each unit becomes docs/programs/<program>/briefs/<id>.md:
its title, owner, wave, what it depends on, and its done criteria as a checklist. A lane starts from its brief, not from a
message written by hand (the repeated action "writing a lane's start message by hand", docs/process/repeats.md). The target
is committed, so `scripts/generate --check` refuses a brief that is missing or stale, and `scripts/generate lane-briefs` writes them.
"""
import json
from pathlib import Path
import re

PLAN = 'docs/programs/fluxo-amplo/plan.md'
BLOCK = re.compile(r'```json program\.v1\n(.*?)```', re.S)


class BriefError(ValueError):
    pass


def units_of(text):
    """The units of the plan's program.v1 block, in plan order."""
    match = BLOCK.search(text)
    if match is None:
        raise BriefError(f'{PLAN} has no program.v1 block')
    units = json.loads(match.group(1)).get('units')
    if not isinstance(units, list) or not units:
        raise BriefError(f'{PLAN}: the program.v1 block names no units')
    return units


def brief(unit):
    """The brief of one unit, as markdown."""
    deps = ', '.join(unit.get('depends_on') or []) or 'none'
    done = unit.get('done') or []
    checklist = ''.join(f'- [ ] {item}\n' for item in done) or '- [ ] (the plan names no done criteria)\n'
    return (
        f'# {unit["id"]}: {unit["title"]}\n\n'
        f'- Owner: {unit["owner"]}, model {unit.get("model", "unset")}, wave {unit.get("wave", "unset")}\n'
        f'- Depends on: {deps}\n'
        f'- Source: `{PLAN}`\n\n'
        f'## Done criteria\n\n{checklist}'
    )


def render(root, target):
    """{repository path: text} for every unit: docs/process/briefs/fluxo-amplo/<id>.md under the target's output."""
    source = Path(root) / PLAN
    if not source.is_file():
        return {}  # a checkout without the program expects no briefs (a fixture root); the live tree has the plan
    text = source.read_text(encoding='utf-8')
    out = target['output']
    return {f'{out}/{unit["id"]}.md': brief(unit) for unit in units_of(text)}
