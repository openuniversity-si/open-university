"""The unit manifests (D-067, plan v3 §4.2): read them, validate them, and answer who owns a path or a unit.

A unit is units/<id>/unit.json, shaped by contracts/units/unit.v1.json (D-069 item 2). Every location and rule this
module uses is a units.* registry entry (D-068); the size budget is units.size_target, units.size_ceiling and
units.context_budget, and a manifest may override one only by citing a decision (D-069 items 1 and 3).

Library (the ownership refusal of the train, M3, calls these; the CODEOWNERS target of the generator, G1b, left with VAZÃO F17):
  unit_of(path)        the id of the unit whose paths match a repository-relative path, else None
  units_of(path)       every unit that owns it (more than one is an ownership error, scripts/lib/unit_check.py): the
                       unit of its primary when it is a companion (units.companions, TX21), else the units whose paths
                       match it
  claims_of(path)      the units whose manifest paths match it, companion rule aside
  primary_of(path)     the primary file a companion follows (units.companions), else None
  owner_of(unit)       the lane that owns a unit (units.owners), KeyError for an unknown unit
  owner_of_path(path)  owner_of(unit_of(path)), else None
  budget(unit, name)   the unit's value of a size-budget registry entry: its cited override, else the registry value
  home(manifest)       the unit's home: the deepest directory that holds every one of its paths
Each takes an optional `root` (default: this checkout) and reads the manifests once per root.

scripts/units owner <path>... | who <unit>... | list | check | propose | measure (scripts/lib/unit_map.py)
"""
import argparse
from functools import lru_cache
from itertools import takewhile
from operator import eq
import json
from pathlib import Path
import re
import sys

import config
import json_schema

ROOT = Path(__file__).resolve().parents[2]
DECISION_ROW = re.compile(r'^\| (D-\d{3}) \|', re.M)


class UnitError(ValueError):
    pass


def setting(name, root=None):
    """A units.* registry value; read once per checkout until reset()."""
    return _setting(name, None if root is None else str(Path(root).resolve()))


@lru_cache(maxsize=None)
def _setting(name, root):
    return config.get(f'units.{name}', None if root is None else Path(root))


def _root(root):
    return ROOT if root is None else Path(root).resolve()


def match(pattern, path):
    """Whether a repository-relative path matches a manifest glob: `*` stays inside a segment, `**` spans any
    segments (`a/**` is `a` and everything under it); every other character is literal (`[slug]` names a folder)."""
    return bool(compile_glob(pattern).fullmatch(path))


@lru_cache(maxsize=None)
def compile_glob(pattern):
    parts = pattern.split('/')
    out, joined = [], False  # joined: the previous `**/` already supplied the separator
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == '**':
            out.append(('.*' if index == 0 else '(?:/.*)?') if last else
                       ('(?:[^/]+/)*' if index == 0 else '(?:/[^/]+)*'))
            joined = index == 0
            continue
        separator = '' if index == 0 or joined else '/'
        out.append(separator + '[^/]*'.join(re.escape(piece) for piece in part.split('*')))
        joined = False
    return re.compile(''.join(out))


def matcher(patterns):
    """One compiled expression for a list of globs."""
    return re.compile('|'.join(f'(?:{compile_glob(pattern).pattern})' for pattern in patterns))


def production(files, root=None):
    """(production files, test files) among repository-relative paths: units.production_globs minus units.test_globs."""
    inside, tests = matcher(setting('production_globs', root)), matcher(setting('test_globs', root))
    chosen = [path for path in files if inside.fullmatch(path)]
    return [path for path in chosen if not tests.fullmatch(path)], [path for path in chosen if tests.fullmatch(path)]


@lru_cache(maxsize=None)
def _schema(root):
    return schema(root)


def schema(root=None):
    root = _root(root)
    path = root / setting('manifest_schema', root)
    if not path.is_file():
        path = ROOT / setting('manifest_schema', root)
    return json.loads(path.read_text(encoding='utf-8'))


def manifest_files(root=None):
    root = _root(root)
    folder = root / setting('manifest_dir', root)
    return sorted(folder.glob(f'*/{setting("manifest_file", root)}')) if folder.is_dir() else []


def decisions(root=None):
    """The D-NNN ids recorded in the decision register."""
    root = _root(root)
    register = root / setting('decision_register', root)
    return set(DECISION_ROW.findall(register.read_text(encoding='utf-8'))) if register.is_file() else set()


def validate(manifest, where, root=None, known=None):
    """The errors of one manifest: its schema, then what the schema cannot state."""
    root = _root(root)
    errors = [f'{where}: {error}' for error in json_schema.validate(_schema(root), manifest)]
    if errors or not isinstance(manifest, dict):
        return errors
    folder = Path(where).parent.name
    if manifest['id'] != folder:
        errors.append(f'{where}: id is {manifest["id"]!r}, not its directory {folder!r}')
    owners = setting('owners', root)
    if manifest['owner'] not in owners:
        errors.append(f'{where}: owner {manifest["owner"]!r} is not one of units.owners (scripts/config describe units.owners)')
    known = decisions(root) if known is None else known
    for name, override in sorted((manifest.get('budget') or {}).items()):
        if override['decision'] not in known:
            errors.append(f'{where}: the {name} override cites {override["decision"]}, which is not in '
                          f'{setting("decision_register", root)}; an override needs a recorded decision (D-067)')
    for name in sorted(manifest.get('decisions') or []):
        if name not in known:
            errors.append(f'{where}: decisions names {name}, which is not in {setting("decision_register", root)}')
    for glob in manifest.get('shared') or []:
        if glob not in manifest['paths']:
            errors.append(f'{where}: shared names {glob!r}, which is not one of its paths; a shared path is still '
                          'owned, so it is listed in paths too')
    return errors


def read(root=None):
    """(manifests by id, errors) of every units/<id>/unit.json."""
    root = _root(root)
    manifests, errors, known = {}, [], decisions(root)
    for path in manifest_files(root):
        where = path.relative_to(root).as_posix()
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as error:
            errors.append(f'{where}: not JSON ({error.msg})')
            continue
        found = validate(manifest, where, root, known)
        errors += found
        if not found:
            manifests[manifest['id']] = manifest
    return manifests, errors


@lru_cache(maxsize=None)
def _cached(root):
    manifests, errors = read(root)
    if errors:
        raise UnitError('; '.join(errors[:3]))
    return manifests, {unit: matcher(manifest['paths']) for unit, manifest in manifests.items()}


def manifests(root=None):
    """Valid manifests by id; UnitError when any manifest is invalid, so no caller decides on a broken map."""
    return _cached(_root(root))[0]


def reset():
    """Forget the manifests and settings read so far (a caller that rewrites them in the same process)."""
    _cached.cache_clear()
    _setting.cache_clear()
    _schema.cache_clear()


def claims_of(path, root=None):
    return sorted(unit for unit, pattern in _cached(_root(root))[1].items() if pattern.fullmatch(path))


@lru_cache(maxsize=None)
def _companion(pattern):
    return re.compile('([^/]+)'.join(re.escape(piece) for piece in pattern.split('*')))


def companion_rule(path, root=None):
    """(the units.companions rule a path is a companion of, the `*` it fills), else (None, None)."""
    for rule in setting('companions', root):
        found = _companion(rule['companion']).fullmatch(path)
        if found:
            return rule, found.group(1)
    return None, None


def primary_of(path, root=None):
    """The primary path a companion follows: `scripts/tests/covers/<t>.json` → `scripts/tests/<t>.test.sh`."""
    rule, name = companion_rule(path, root)
    return rule['primary'].replace('*', name) if rule else None


def units_of(path, root=None):
    """The units that own a path: its primary's units when it is a companion of an owned primary, else its claims."""
    primary = primary_of(path, root)
    derived = claims_of(primary, root) if primary else []
    return derived or claims_of(path, root)


def unit_of(path, root=None):
    found = units_of(path, root)
    if len(found) > 1:
        raise UnitError(f'{path} matches {len(found)} units: {", ".join(found)}')
    return found[0] if found else None


def owner_of(unit, root=None):
    return manifests(root)[unit]['owner']


def owner_of_path(path, root=None):
    unit = unit_of(path, root)
    return None if unit is None else owner_of(unit, root)


def budget(unit, name, root=None):
    """A size-budget entry's value for one unit: the manifest's cited override, else the registry."""
    override = (manifests(root)[unit].get('budget') or {}).get(name)
    return override['value'] if override else setting(name.split('.', 1)[1], root)  # the budget names are units.*


def home(manifest):
    """The deepest directory that holds every path of a manifest: a glob counts up to its first wildcard segment,
    a file counts as its directory. It anchors the manifest's contract entry (scripts/lib/unit_battery.py); the
    `@ou/<id>` address map it once rooted left with Open University's TypeScript project (OU-DECOUPLE F4 (D-111))."""
    common = None
    for glob in manifest['paths']:
        parts = glob.split('/')
        wild = next((index for index, part in enumerate(parts) if '*' in part), None)
        folder = parts[:wild] if wild is not None else parts[:-1]
        common = folder if common is None else [mine for mine, _ in takewhile(lambda pair: eq(*pair), zip(common, folder))]
    return '/'.join(common or [])


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/units', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, help='repository (default: this checkout)')
    commands = parser.add_subparsers(dest='command', required=True)
    owner = commands.add_parser('owner', help='the unit and owner of each path')
    owner.add_argument('paths', nargs='+')
    who = commands.add_parser('who', help='the owner of each unit')
    who.add_argument('units', nargs='+')
    commands.add_parser('list', help='every unit with its cell and owner')
    check = commands.add_parser('check', help='validate every manifest')
    check.add_argument('--fix-requires', action='store_true',
                       help='rewrite each manifest\'s requires to the measured import graph, then check')
    for name, text in (('propose', 'the generator\'s cut of the production files (scripts/lib/unit_map.py)'),
                       ('measure', 'each manifest\'s lines, closure and cohesion against its budget')):
        command = commands.add_parser(name, help=text)
        command.add_argument('--json', action='store_true', help='print JSON rows')
        if name == 'measure':
            command.add_argument('--emit', action='store_true',
                                 help='publish engine.step.measured and unit.oversize through the forge_events port')
            command.add_argument('--pr', type=int, help='the change the events are about (default: the repository)')
    args = parser.parse_args(argv)
    root = args.root
    if args.command in ('propose', 'measure'):
        import unit_map  # the generator reads the git log; the lookups above never need it
        return unit_map.main(args.command, args.json, root, getattr(args, 'pr', None), getattr(args, 'emit', False))
    if args.command == 'check':
        if args.fix_requires:
            import unit_check  # reads the git tree and the import graph; plain validation never needs it
            for line in unit_check.fix_requires(root or ROOT):
                print('FIXED ' + line)
        found, errors = read(root)
        for line in errors:
            print('FAIL ' + line)
        print(f'units: {len(found)} valid manifest(s), {len(errors)} error(s)')
        return 1 if errors else 0
    try:
        if args.command == 'owner':
            for path in args.paths:
                unit = unit_of(path, root)
                print(f'{path}\t{unit or "-"}\t{owner_of(unit, root) if unit else "-"}')
        elif args.command == 'who':
            for unit in args.units:
                print(f'{unit}\t{owner_of(unit, root)}')
        else:
            for unit, manifest in sorted(manifests(root).items()):
                print(f'{unit}\t{manifest["cell"]}\t{manifest["owner"]}')
    except KeyError as error:
        print(f'units: unknown unit {error}', file=sys.stderr)
        return 2
    except UnitError as error:
        print(f'units: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
