"""Scaffold of a new script (FLUXO-AMPLO F1.2, D-146): `scripts/scaffold script NAME --unit UNIT ...`.

A new script needs, to be structure-clean, six things that no one command knew together: the wrapper `scripts/NAME`,
the library `scripts/lib/NAME_with_underscores.py`, its test `scripts/tests/test_NAME_with_underscores.py` and the test's
wrapper `scripts/tests/NAME.test.sh`, the covers manifest `scripts/tests/covers/NAME.json`, the paths of the owning
unit's `unit.json` (the assets inventory left with D-292, CODEOWNERS with VAZÃO F17). The command writes them
from templates and refuses to overwrite anything. The generated library and test are a stub that passes; the author
writes the logic.

`scripts/scaffold config-key OWNER KEY --reader FILE --type T --default JSON --unit U --description D [--text]`
(VAZÃO F74) writes one registry key, `config/registry/OWNER/OWNER.KEY.json`, with its `x-readers` (each reader must
exist and be a reader file, registry_readers.reader_file), checks it against the meta-schema's parameter and its own
default, and rewrites the owner's aggregate (generate_registry.assemble). An object key is user-facing text (the
meta-schema), so with --text or --type object it writes `x-text: true`, `required` naming the default locale,
`propertyNames` (l10n.locales) and `additionalProperties`, and refuses an owner other than l10n.text_owner.
"""
import argparse
import json
from pathlib import Path
import re
import stat
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
NAME = re.compile(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$')

WRAPPER = '''#!/usr/bin/env bash
# Usage: scripts/{name} [--help]
# {purpose}
set -euo pipefail
exec "${{OU_PYTHON:-python3}}" "$(dirname "$0")/lib/{module}.py" "$@"
'''
LIBRARY = '''"""{purpose}"""
import argparse
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/{name}', description=__doc__)
    parser.parse_args(argv)
    return 0


if __name__ == '__main__':
    sys.exit(main())
'''
TEST = '''"""{purpose} Hermetic: no network."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import {module}  # noqa: E402


class {klass}Tests(unittest.TestCase):
    def test_main_returns_success(self):
        self.assertEqual({module}.main([]), 0)


if __name__ == '__main__':
    unittest.main()
'''
TEST_WRAPPER = '''#!/usr/bin/env bash
# {purpose} Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_{module}.py"
'''


def plan(root, name, unit, purpose):
    """{relative path: text} of the new files, and the unit/asset edits as (path, new text)."""
    module = name.replace('-', '_')
    klass = ''.join(part.capitalize() for part in name.split('-'))
    values = {'name': name, 'module': module, 'klass': klass, 'purpose': purpose}
    files = {f'scripts/{name}': WRAPPER.format(**values), f'scripts/lib/{module}.py': LIBRARY.format(**values),
             f'scripts/tests/test_{module}.py': TEST.format(**values),
             f'scripts/tests/{name}.test.sh': TEST_WRAPPER.format(**values)}
    covers = {'script': f'scripts/tests/{name}.test.sh',
              'covers': [f'scripts/tests/{name}.test.sh', f'scripts/tests/test_{module}.py', f'scripts/{name}',
                         f'scripts/lib/{module}.py']}
    files[f'scripts/tests/covers/{name}.json'] = json.dumps(covers, indent='  ') + '\n'
    unit_path = Path(root) / 'units' / unit / 'unit.json'
    manifest = json.loads(unit_path.read_text())
    manifest['paths'] = sorted(set(manifest['paths']) | {f'scripts/{name}', f'scripts/lib/{module}.py',
                                                         f'scripts/tests/{name}.test.sh', f'scripts/tests/test_{module}.py'})
    edits = {str(unit_path.relative_to(root)): json.dumps(manifest, indent='  ') + '\n'}
    return files, edits


def check(root, name, unit):
    if not NAME.match(name):
        raise SystemExit(f'scaffold: {name!r} is not a kebab-case script name')
    if not (Path(root) / 'units' / unit / 'unit.json').exists():
        raise SystemExit(f'scaffold: unit {unit!r} has no units/{unit}/unit.json')


def write(root, name, unit, purpose):
    check(root, name, unit)
    files, edits = plan(root, name, unit, purpose)
    clash = [path for path in files if (Path(root) / path).exists()]
    if clash:
        raise SystemExit(f'scaffold: refuses to overwrite {", ".join(clash)}')
    for path, text in files.items():
        target = Path(root) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        if path in (f'scripts/{name}', f'scripts/tests/{name}.test.sh'):
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    for path, text in edits.items():
        (Path(root) / path).write_text(text)
    return sorted(files) + sorted(edits)


def config_key(root, owner, key, readers, kind, default, unit, description, text=False, source=None):
    """F74: write config/registry/OWNER/OWNER.KEY.json and the owner's aggregate; returns the written paths."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import config
    import generate_registry
    import json_schema
    import registry_readers
    name = f'{owner}.{key}'
    folder = Path(root) / 'config' / 'registry' / owner
    target = folder / f'{name}.json'
    if not (folder / generate_registry.HEADER).is_file():
        raise SystemExit(f'scaffold: owner {owner!r} has no config/registry/{owner}/{generate_registry.HEADER}')
    if target.exists():
        raise SystemExit(f'scaffold: refuses to overwrite {target.relative_to(root)}')
    wrong = [path for path in readers if not (Path(root) / path).is_file() or not registry_readers.reader_file(path)]
    if not readers or wrong:
        raise SystemExit(f'scaffold: --reader names no existing reader file: {", ".join(wrong) or "none given"}')
    item = {'type': kind, 'default': default, 'x-unit': unit, 'description': description,
            'x-readers': sorted(set(readers))}
    if text or kind == 'object':  # the meta-schema: an object parameter is x-text, and x-text names its locales
        locale, owner_of_text = config.get('l10n.default_locale'), config.get('l10n.text_owner')
        if owner != owner_of_text:
            raise SystemExit(f'scaffold: an object or --text key is user-facing text and lives in owner '
                             f'{owner_of_text!r} (l10n.text_owner); use another type for {name}')
        if not isinstance(default, dict) or locale not in default:
            raise SystemExit(f'scaffold: a --text default is keyed by locale and carries {locale!r}')
        item.update({'type': 'object', 'x-text': True, 'required': [locale],
                     'propertyNames': {'enum': config.get('l10n.locales')},
                     'additionalProperties': {'type': 'string', 'minLength': 1}})
    if source:
        item['x-source'] = source
    meta = json.loads((Path(root) / 'contracts' / 'config' / 'registry.v1.json').read_text())
    errors = json_schema.validate(meta['$defs']['parameter'], item, root=meta)
    errors += json_schema.validate(config.parameter_schema(item), default)
    if errors:
        raise SystemExit(f'scaffold: {name} does not pass the meta-schema: {"; ".join(errors)}')
    target.write_text(generate_registry._text(item))
    aggregate = folder.with_suffix('.json')
    aggregate.write_text(generate_registry.assemble(root, owner))
    return [str(target.relative_to(root)), str(aggregate.relative_to(root))]


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/scaffold', description=__doc__.splitlines()[0])
    parser.add_argument('kind', choices=['script', 'config-key'])
    parser.add_argument('name', help='script: the script name; config-key: the owner')
    parser.add_argument('key', nargs='?', help='config-key: the key after the owner prefix (snake_case)')
    parser.add_argument('--unit', help='script: the owning unit; config-key: the x-unit (s, count, path, ...)')
    parser.add_argument('--purpose', default='A new script (scaffold).')
    parser.add_argument('--reader', action='append', default=[], help='config-key: a file that reads it; repeatable')
    parser.add_argument('--type', dest='kind_of', default='string', help='config-key: the JSON type')
    parser.add_argument('--default', help='config-key: the default, as JSON')
    parser.add_argument('--description', help='config-key: what the value controls')
    parser.add_argument('--source', help='config-key: x-source, the decision or document behind the default')
    parser.add_argument('--text', action='store_true', help='config-key: user-facing text keyed by locale (x-text)')
    args = parser.parse_args(argv)
    if args.kind == 'config-key':
        if not (args.key and args.unit and args.default is not None and args.description):
            parser.error('config-key needs OWNER KEY --reader FILE --unit U --default JSON --description D')
        try:
            default = json.loads(args.default)
        except ValueError as error:
            parser.error(f'--default is not JSON: {error}')
        written = config_key(ROOT, args.name, args.key, args.reader, args.kind_of, default, args.unit,
                             args.description, args.text, args.source)
        print('\n'.join(f'wrote {path}' for path in written))
        return 0
    if not args.unit:
        parser.error('script needs --unit')
    written = write(ROOT, args.name, args.unit, args.purpose)
    print('\n'.join(f'wrote {path}' for path in written))
    return 0


if __name__ == '__main__':
    sys.exit(main())
