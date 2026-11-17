"""Typed loader for the delivery area map. Stage names live in gate-areas.json only."""
import json
import subprocess
from pathlib import Path

from globs import _compile_glob, glob_match  # noqa: F401 - D-322: the matcher is layer 0 (engine-config); callers keep this name

DEFAULT = Path(__file__).with_name('gate-areas.json')
_CACHE = {}
# OU-DECOUPLE F5 (D-113): the `database` area, its import rule (AR1), the package.json database surface and the Next
# build rule left with Open University's database gate and builds; the engine map holds the documentation area and the
# engine's own areas, whose only stages are the always stages and the script tests. The import rule's registry keys
# and their owner left the registry (VAZÃO F43, D-068 (3) expand then contract).


class AreaMapError(ValueError):
    pass


class Area:
    def __init__(self, raw, groups):
        if not isinstance(raw, dict):
            raise AreaMapError('area entries must be objects')
        self.id = raw.get('id')
        self.title = raw.get('title') or self.id
        self.paths = raw.get('paths')
        names = raw.get('groups')
        if not isinstance(self.id, str) or not self.id:
            raise AreaMapError('area id must be a non-empty string')
        if not isinstance(self.title, str):
            raise AreaMapError(f'{self.id}: title must be a string')
        if not isinstance(self.paths, list) or not self.paths or not all(isinstance(item, str) and item for item in self.paths):
            raise AreaMapError(f'{self.id}: paths must be a non-empty list of globs')
        if not isinstance(names, list) or not all(isinstance(item, str) for item in names):
            raise AreaMapError(f'{self.id}: groups must be a list of group ids')
        unknown = [item for item in names if item not in groups]
        if unknown:
            raise AreaMapError(f'{self.id}: unknown group {unknown[0]}')
        self.groups = tuple(names)
        covered = raw.get('coveredGroups', [])
        if not isinstance(covered, list) or not all(isinstance(item, str) for item in covered):
            raise AreaMapError(f'{self.id}: coveredGroups must be a list of group ids')
        unknown = [item for item in covered if item not in groups]
        if unknown:
            raise AreaMapError(f'{self.id}: unknown coveredGroups group {unknown[0]}')
        self.covered_groups = tuple(covered)

    def matches(self, path):
        return any(glob_match(path, pattern) for pattern in self.paths)

    def stages(self, groups, covered=False):
        """The stages of the area's groups; `covered` adds the coveredGroups (GX-18) for a path a script test declares."""
        stages = []
        for name in self.groups + (self.covered_groups if covered else ()):
            for stage in groups[name]:
                if stage not in stages:
                    stages.append(stage)
        return stages


class AreaMap:
    def __init__(self, data):
        if not isinstance(data, dict):
            raise AreaMapError('area map must be an object')
        if data.get('version') != 1:
            raise AreaMapError('area map version must be 1')
        order = data.get('order')
        always = data.get('always')
        groups = data.get('groups')
        areas = data.get('areas')
        docs = data.get('documentation')
        if not isinstance(order, list) or not order or not all(isinstance(item, str) for item in order):
            raise AreaMapError('order must list every stage')
        if len(order) != len(set(order)):
            raise AreaMapError('order contains a duplicate stage')
        if not isinstance(always, list) or not all(item in order for item in always):
            raise AreaMapError('always must list stages from order')
        if not isinstance(groups, dict):
            raise AreaMapError('groups must be an object')
        parsed_groups = {}
        for name, stages in groups.items():
            if not isinstance(stages, list) or not stages or not all(isinstance(item, str) and item in order for item in stages):
                raise AreaMapError(f'group {name} must list stages from order')
            parsed_groups[name] = tuple(stages)
        if not isinstance(areas, list) or not areas:
            raise AreaMapError('areas must be a non-empty list')
        if not isinstance(docs, dict):
            raise AreaMapError('documentation must name prefixes and suffixes')
        prefixes, suffixes = docs.get('prefixes'), docs.get('suffixes')
        if not isinstance(prefixes, list) or not isinstance(suffixes, list):
            raise AreaMapError('documentation prefixes and suffixes must be lists')
        if not all(isinstance(item, str) and item for item in prefixes + suffixes):
            raise AreaMapError('documentation prefixes and suffixes must be non-empty strings')
        self.order = tuple(order)
        self.always = tuple(always)
        self.groups = parsed_groups
        self.doc_prefixes = tuple(prefixes)
        self.doc_suffixes = tuple(suffixes)
        self.areas = tuple(Area(raw, parsed_groups) for raw in areas)
        ids = [area.id for area in self.areas]
        if len(ids) != len(set(ids)):
            raise AreaMapError('duplicate area id')
        self.by_id = {area.id: area for area in self.areas}
        if 'docs' not in self.by_id:
            raise AreaMapError('missing required area docs')
        # OU-DECOUPLE F2 (D-108, D-109): a stage no group names and that is not `always` is never selected by any plan,
        # full or scoped; OU-DECOUPLE F5 (D-113): the engine map orders no such stage any more.
        named = set(self.always) | {stage for stages in self.groups.values() for stage in stages}
        self.full_stages = tuple(stage for stage in self.order if stage in named)

    def is_documentation(self, path):
        return path.startswith(self.doc_prefixes) or path.endswith(self.doc_suffixes)

    def areas_for(self, path):
        if self.is_documentation(path):
            return (self.by_id['docs'],)
        return tuple(area for area in self.areas if area.id != 'docs' and area.matches(path))


def coverage_errors(root):
    """OU-DECOUPLE F1 (D-106): every tracked path of the checkout belongs to an area, refused by name otherwise. The map
    read is the judged checkout's own, not the tool's: under the pin (P-46) the tool's map would refuse a path that the
    change maps in an area it adds. A checkout without a map (a test fixture) has no areas to judge against."""
    root = Path(root)
    relative = DEFAULT.relative_to(DEFAULT.parent.parent.parent)
    if not (root / relative).is_file():
        return []
    # D-109: only the globs are read, never the stage graph, so a map a newer loader accepts is judged by an older one.
    data = json.loads((root / relative).read_text())
    docs = data.get('documentation') or {}
    prefixes, suffixes = tuple(docs.get('prefixes') or ()), tuple(docs.get('suffixes') or ())
    globs = [pattern for area in data.get('areas') or () for pattern in area.get('paths') or ()]
    listed = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True, check=True).stdout
    paths = [path for path in listed.decode().split('\0') if path]
    return [f'{path}: no area of {relative} claims it; add it to one (D-106)' for path in paths
            if not path.startswith(prefixes) and not path.endswith(suffixes)
            and not any(glob_match(path, pattern) for pattern in globs)]


def load(path=None):
    target = Path(path) if path else DEFAULT
    key = str(target.resolve()) if target.exists() else str(target)
    cached = _CACHE.get(key)
    if cached is None:
        try:
            data = json.loads(target.read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise AreaMapError(f'cannot read area map: {error}') from None
        cached = _CACHE[key] = AreaMap(data)
    return cached


def _ordered(mapping, selected, reason):
    stages = [stage for stage in mapping.order if stage in selected and stage in mapping.full_stages]
    reasons = {stage: reason for stage in stages}
    return stages, reasons


class ScriptTestCovers:
    """GX-18: whether a script test declares a path in its covers (gate_script_tests.load(), GX-08 headers/sidecars).

    Fail closed (P-10): when the covers cannot be read the path counts as covered, so the area runs the tests.
    """

    def __init__(self):
        self._mapping = False

    def covers(self, path):
        if self._mapping is False:
            try:
                import gate_script_tests  # lazy: gate_script_tests imports glob_match from this module
                self._mapping = gate_script_tests.load()
            except Exception:  # noqa: BLE001 - any failure to read the covers keeps the tests
                self._mapping = None
        if self._mapping is None:
            return True
        return any(glob_match(path, pattern) for test in self._mapping['tests'] for pattern in test['covers'])


def full_plan(paths, reason):
    mapping = load()
    stages, reasons = _ordered(mapping, set(mapping.full_stages), reason)
    return _finish(mapping, list(paths), 'full', reason, [], stages, reasons)


def always_plan(paths, reason):
    """OU-DECOUPLE F1 (D-106): the `always` stages only. An empty diff has nothing else to judge, and an unmapped path
    is refused by the structure check (an `always` stage), so its verdict needs nothing more."""
    mapping = load()
    stages, reasons = _ordered(mapping, set(mapping.always), reason)
    return _finish(mapping, list(paths), 'scoped', reason, [], stages, reasons)


def plan_for(paths):
    """Union of every matched area. An empty diff or an unmapped path is the `always` stages (D-106): the structure check
    refuses the unmapped path, and only a diff that changes the area map itself keeps the full battery for it."""
    mapping = load()
    paths = [str(path) for path in paths]
    if not paths:
        return always_plan(paths, 'empty diff; the always stages (D-106)')
    matched = []
    script_covers = ScriptTestCovers()
    for path in paths:
        areas = mapping.areas_for(path)
        if not areas:
            if str(DEFAULT.relative_to(DEFAULT.parent.parent.parent)) in paths:
                return full_plan(paths, f'unmapped path: {path}; the area map changed, so the full battery judges it')
            return always_plan(paths, f'unmapped path: {path}; the structure check refuses it (D-106)')
        matched.append((path, areas))
    selected = set(mapping.always)
    reasons = {stage: 'always' for stage in mapping.always}
    area_ids = []
    titles = []
    for path, areas in matched:
        for area in areas:
            if area.id not in area_ids:
                area_ids.append(area.id)
                titles.append(area.title)
            for stage in area.stages(mapping.groups, bool(area.covered_groups) and script_covers.covers(path)):
                if stage not in reasons:
                    selected.add(stage)
                    reasons[stage] = f'{area.title}: {path}'
    stages, _ignored = _ordered(mapping, selected, '')
    for stage in stages:
        reasons.setdefault(stage, 'always')
    summary = f"{len(paths)} mapped file(s) in {', '.join(titles)}"
    return _finish(mapping, paths, 'scoped', summary, area_ids, stages, reasons)


def _finish(mapping, paths, kind, reason, area_ids, stages, reasons):
    """OU-DECOUPLE F5 (D-113): the plan says which stages run and why; the production deploy, database gate and subject
    install flags left with Open University (`deploy`, `dbRequired`, `nodeRequired`)."""
    chosen = set(stages)
    reasons = {stage: why for stage, why in reasons.items() if stage in chosen}  # a stage the map no longer orders
    skipped = [{'stage': stage, 'reason': 'not required by ' + (', '.join(area_ids) if area_ids else 'this diff')}
               for stage in mapping.full_stages if stage not in chosen]
    if kind == 'full':
        skipped = []
        reasons = {stage: reason for stage in stages}
    return {
        'kind': kind,
        'reason': reason,
        'areas': area_ids,
        'paths': paths,
        'stages': stages,
        'reasons': reasons,
        'skipped': skipped,
    }


def format_plan(plan):
    lines = [f"area plan: {plan['kind']} ({plan['reason']})"]
    skipped = {item['stage']: item['reason'] for item in plan['skipped']}
    chosen = set(plan['stages'])
    for stage in load().order:
        if stage in chosen:
            lines.append(f"  {stage}: {plan['reasons'][stage]}")
        elif stage in skipped:
            lines.append(f"  {stage}: skipped ({skipped[stage]})")
    return '\n'.join(lines)


if __name__ == '__main__':
    import argparse
    import sys
    parser = argparse.ArgumentParser(description='Print the delivery plan for a list of paths')
    parser.add_argument('paths', nargs='*')
    args = parser.parse_args()
    try:
        print(format_plan(plan_for(args.paths)))
    except AreaMapError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
