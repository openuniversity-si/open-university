"""The schema compat gate stage (D-068 (5), D-069 item 2, P-07): every contract changes by expand->contract.

check(root, base) returns the errors of:
  shape        every JSON file under contracts.schema_dir is a schema named <area>/<name>.v<N>.json
               (contracts.schema_file_pattern), identified by its path, in JSON Schema 2020-12 and in the subset the
               validator implements (a lock or manifest beside the schemas is not a schema and is skipped);
  additive     against the base, an existing version changes only additively (json_schema.compatible: no field
               removed or newly required, no type, enum, range, pattern or $defs entry narrowed or removed);
               a breaking change is a new version file;
  succession   a new version file v<N> (N > 1) follows v<N-1>, which the base or the tree holds (expand);
  retirement   a version file leaves only when nothing but generated files still names it (contract, D-029);
  registry     a config/registry/<owner>.json parameter leaves when nothing in the tree names it any more, and its
               type only widens. A parameter that still has a reader needs the revision that marked it deprecated
               first (expand->contract): the proof of absence is what decides, not the ceremony (D-289).
The event schemas are stricter still: event_contracts locks each file's hash (M2), so an event changes only by a new
version. Without a base only the shape is judged.

  scripts/schema-compat [--base REF] [--root DIR]
"""
import argparse
import json
from pathlib import Path
import re
import sys

import config
from config_check import _at_base, _git, _listed_at_base
import generate
import json_schema
import registry_readers

VERSION = re.compile(r'^(?P<stem>.+)\.v(?P<version>[1-9][0-9]*)\.json$')


def _contract_paths(root):
    listed = _git(root, 'ls-files', '--', config.get('contracts.schema_dir', root))
    return [path for path in (listed.stdout.split() if listed.returncode == 0 else []) if path.endswith('.json')]


def _generated_outputs(root):
    """The outputs of committed generate targets: a generated file naming a contract is not one of its consumers."""
    return tuple(target['output'] for target in generate.targets(root).values() if target['committed'])


def check_shape(root, path, document):
    errors = []
    if not re.match(config.get('contracts.schema_file_pattern', root), path):
        errors.append(f'{path}: a contract is named contracts/<area>/<name>.v<N>.json (D-068 (5))')
    if document.get('$schema') != json_schema.DIALECT:
        errors.append(f'{path}: $schema is not JSON Schema 2020-12')
    if document.get('$id') != path:
        errors.append(f'{path}: $id is {document.get("$id")!r}, not its path')
    return errors + [f'{path}: {error}' for error in json_schema.check_schema(document)]


def check_succession(root, base, paths):
    """A new v<N> (N > 1) follows v<N-1> in the base or the tree."""
    before = set(_listed_at_base(root, base, config.get('contracts.schema_dir', root)))
    known = before | set(paths)
    errors = []
    for path in paths:
        match = VERSION.match(path)
        if not match or path in before or int(match['version']) == 1:
            continue
        previous = f'{match["stem"]}.v{int(match["version"]) - 1}.json'
        if previous not in known:
            errors.append(f'{path}: a new version follows {previous}, which neither the base nor the tree holds '
                          '(expand→contract)')
    return errors


def check_retired(root, base):
    errors = []
    generated = _generated_outputs(root)
    for path in _listed_at_base(root, base, config.get('contracts.schema_dir', root)):
        if path.endswith('.json') and not (root / path).is_file():
            users = _git(root, 'grep', '-l', '-F', path, '--', '.').stdout.split()
            users = [user for user in users if not user.startswith(generated)]
            if users:
                errors.append(f'{path}: deleted while {_some(users)} still reference it; '
                              'migrate every consumer first (expand→contract)')
    return errors


def check_contracts(root, base=None):
    errors, schemas = [], []
    for path in _contract_paths(root):
        if not (root / path).is_file():
            continue
        try:
            document = json.loads((root / path).read_text(encoding='utf-8'))
        except json.JSONDecodeError as error:
            errors.append(f'{path}: not JSON ({error.msg})')
            continue
        if not isinstance(document, dict):
            continue  # a lock or manifest beside the schemas (contracts/events/schemas.lock.json), not a schema
        schemas.append(path)
        errors += check_shape(root, path, document)
        if base:
            old = _at_base(root, base, path)
            if old is not None:
                errors += [f'{path}: incompatible change ({reason}); add a new version file instead (expand→contract)'
                           for reason in json_schema.compatible(json.loads(old), document)]
    if base:
        errors += check_succession(root, base, schemas)
        errors += check_retired(root, base)
        errors += check_registry_compatible(root, base)
    return errors


def _shape(document):
    """A registry file reduced to what removal and type narrowing judge; ranges and defaults may change."""
    return {'type': 'object', 'properties': {
        name: {key: item[key] for key in ('type', 'deprecated') if key in item}
        for name, item in (document.get('properties') or {}).items()}}


def _some(paths, limit=3):
    """A few of the files that still name something: enough to act on, never the whole list."""
    return ', '.join(paths[:limit])


def _named_in_the_tree(root, name):
    """The source files that still spell a key's full name, with the same definition of a reader the registry uses
    (D-100, D-153): prose, records and generated modules are not readers (D-289)."""
    return registry_readers.names(root, [name]).get(name, set())


def check_registry_compatible(root, base):
    """A key leaves in one revision when the tree proves nothing reads it; otherwise only after being deprecated.

    The registry has no reader outside this tree: its readers are source files, so absence is measurable and a prior
    revision adds nothing to the measurement (D-289). A key still named somewhere keeps the expand->contract rule."""
    errors = []
    folder = config._registry_dir(root).relative_to(root).as_posix()
    for path in _listed_at_base(root, base, folder):
        # The reader loads owner documents at this level. Split parameter fragments are not registry owners:
        # an object's nested properties describe its value, not independently removable registry parameters.
        if not path.endswith('.json') or Path(path).parent.as_posix() != folder:
            continue
        old = _at_base(root, base, path)
        if old is None:
            continue
        current = root / path
        new = json.loads(current.read_text(encoding='utf-8')) if current.is_file() else {}
        gone = set((json.loads(old).get('properties') or {})) - set((new.get('properties') or {}))
        errors += [f'{path}: {reason}' for reason in json_schema.compatible(
            _shape(json.loads(old)), _shape(new), removal_needs_deprecation=False)]
        for name in sorted(gone):
            users = sorted(_named_in_the_tree(root, name))
            if users:
                errors.append(f'{path}: {name}: removed while {_some(users)} still name it; '
                              'migrate every reader first (expand->contract)')
    return errors


def check(root, base=None):
    return check_contracts(Path(root), base)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/schema-compat', description=__doc__.splitlines()[0])
    parser.add_argument('--base', help='the commit every existing schema is compared with (the PR base)')
    parser.add_argument('--root', type=Path, help='repository to check (default: the current checkout)')
    args = parser.parse_args(argv)
    root = (args.root or generate.default_root()).resolve()
    errors = check(root, args.base)
    for line in errors:
        print('FAIL ' + line)
    print(f'schema compat: {len(_contract_paths(root))} contract file(s)'
          f'{" against " + args.base[:12] if args.base else " (no base: shape only)"}; {len(errors)} error(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
