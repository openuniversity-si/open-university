"""The launch adapter of the coordinator (D-069 CO1): render a unit's brief and hand it to the launcher port.

brief = the unit brief (program complaint, unit, done criteria, dependencies)
      + the Padrão rules of the active version (docs/padrao/<version>/padrao.json)
      + the applied lessons for the unit's area (LR1, through the lessons port)
      + the live plan's notes for the unit (plan.changed brief_lines, section 'Live plan notes')
      + the known defects (KD1's register).
Ports: lessons (for_area(paths) -> lines, candidates(unit_ids) -> lines) with the LR1 adapter (scripts/lib/lessons*.py);
launcher (scripts/lib/adapters/launcher.py). This module reads the Padrão and renders; it never edits lessons or defects.
"""
import json
from pathlib import Path

import config
import program as programs

ROOT = programs.ROOT


class LaunchError(RuntimeError):
    pass


def setting(name):
    return config.get(f'coordinator.{name}')


def padrao(root=None):
    """(version, [(rule id, text)]) of the active Padrão version."""
    folder = Path(root or ROOT) / setting('padrao_dir') / setting('padrao_version')
    manifest = json.loads((folder / setting('padrao_manifest')).read_text())
    if manifest['version'] != setting('padrao_version'):
        raise LaunchError(f'{folder.name}: manifest says {manifest["version"]}')
    return manifest['version'], [(rule['id'], (folder / rule['file']).read_text().strip()) for rule in manifest['rules']]


class NullLessons:
    """No lessons: the default of a render that is given no port."""
    def for_area(self, paths):
        return []

    def candidates(self, unit_ids):
        return []


class Lr1Lessons:
    """LR1's lessons registry (scripts/lib/lessons.py, lessons_brief.py): applied lessons for a unit's paths and the
    lessons marked padrao_candidate that came from a program's units."""
    def __init__(self, root=None):
        import lessons
        import lessons_brief
        self.lessons, self.brief = lessons, lessons_brief
        self.records, _ = lessons.load(Path(root or ROOT))

    def for_area(self, paths):
        return self.brief.render(self.brief.for_area(self.records, paths))

    def candidates(self, unit_ids):
        wanted = {name.lower() for name in unit_ids}
        found = [record for record in self.records.values()
                 if record.get('padrao_candidate') and str(record['source']['unit']).lower() in wanted]
        return self.brief.render(sorted(found, key=lambda record: record['id']))


def lessons_port(root=None):
    """The LR1 adapter over the checkout's lessons register."""
    return Lr1Lessons(root)


def defect_lines(root=None, limit=None):
    """One line per known defect that is not yet resolved (KD1's register), at most coordinator.brief_defects_limit."""
    import defects
    found, _ = defects.load(Path(root or ROOT))
    closed = set(config.get('defects.statuses')[-2:])
    lines = [f'{record["id"]} {record["test"]} [{record["status"]}] owner {record["owner"]}'
             for record in sorted(found.values(), key=lambda record: record['id']) if record['status'] not in closed]
    return lines[:setting('brief_defects_limit') if limit is None else limit]


def section(title, lines):
    return f'## {title}\n' + ('\n'.join(lines) if lines else 'None.')


def render_brief(plan, unit, attempt, lessons=None, root=None):
    """The launch brief of one unit attempt, as text."""
    lessons = lessons or NullLessons()
    version, rules = padrao(root)
    complaint, goal = plan['complaint'], plan['complaint']['goal']
    head = [f'# Unit {unit["id"]}' + (f': {unit["title"]}' if unit.get('title') else ''),
            f'Program {plan["program"]}, wave {unit["wave"]}, attempt {attempt}, model {unit["model"]}, lane {unit["owner"]}.',
            f'Complaint: {complaint["symptom"]}. Evidence: {complaint["evidence"]}. '
            f'Goal: {goal["metric"]} {goal["comparator"]} {goal["target"]} {goal["unit"]}.',
            'Depends on: ' + (', '.join(unit['depends_on']) or 'nothing') + '.']
    parts = ['\n'.join(head), section('Done criteria', [f'- {item}' for item in unit['done']])]
    parts.append(f'## Padrão {version}\n' + '\n\n'.join(text for _, text in rules))
    parts.append(section('Applied lessons', [f'- {line}' for line in lessons.for_area(unit.get('area', []))]))
    parts.append(section('Live plan notes', [f'- {line}' for line in (plan.get('brief_lines') or {}).get(unit['id'], [])]))
    parts.append(section('Known defects', [f'- {line}' for line in defect_lines(root)]))
    return '\n\n'.join(parts) + '\n'


def briefs_for(plan, rows, lessons=None, root=None):
    """{unit id: brief} for every unit of the status rows that is not merged (B1, D-204): a unit that started keeps its
    brief printed, so a lane can read it after the launch. The attempt is 1: a relaunch's brief is the same text."""
    by_id = {unit['id']: unit for unit in plan['units']}
    return {row['id']: render_brief(plan, by_id[row['id']], 1, lessons, root)
            for row in rows if row['stage'] != 'merged'}


def build_ports(plan, launcher, lessons, root=None):
    """The ports run() applies actions through: launch (renders and starts), route (KD1's router), notify (stderr)."""
    import defect_router
    import forge_events
    import sys
    from adapters.launcher import LaunchRequest
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    setting('producer'), f'{setting("producer")}:{plan["program"]}')
    repo = config.get('forge-events.repo')
    base_sha = defect_router.base_sha_of(Path(root or ROOT))

    def launch(unit, attempt):
        return launcher.launch(LaunchRequest(unit['id'], attempt, unit['model'], render_brief(plan, unit, attempt, lessons, root)))

    def route():
        waiting = defect_router.queue(port, repo, config.get('train.base_branch'))
        return defect_router.route(Path(root or ROOT), port, repo, base_sha, waiting, setting('router_by'))

    def notify(text):
        print(text, file=sys.stderr)

    def emit(kind, payload):
        payload = dict(payload)
        name = payload.pop('unit')
        return port.emit(kind, dict(forge_events.subject(repo, None, base_sha, (), name), **payload))

    return {'launch': launch, 'route': route, 'notify': notify}, emit
