"""The ownership check (D-067 (6), (7); D-064 (d)): every production file belongs to exactly one unit, no file to two,
stale globs warn, an oversize unit warns until units.oversize_fails flips, an import between units follows a declared
`requires` (U2), and the structure-check wiring.

Fixture git repositories in a temporary directory with copies of the registry and the contract; no network, no clock.
"""
import contextlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import regime  # noqa: E402
import structure  # noqa: E402
import unit_check  # noqa: E402
import units  # noqa: E402

COPIED = ('contracts/units/unit.v1.json', 'contracts/config/registry.v1.json', 'config/registry/config.json',
          'config/registry/forge-events.json')
SMALL = {'units.size_ceiling': 10, 'units.production_globs': ['app/src/**', 'tools/**'],
         'units.test_globs': ['**/*.test.*'], 'units.size_exempt_globs': ['**/*.json']}
OWNER = config.get('units.owners')[0]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        for name in COPIED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        self.registry(SMALL)
        self.write('docs/domain/DECISIONS.md', '| D-067 | today |\n')
        self.write('app/src/one/a.ts', 'export const a = 1;\n')
        self.write('app/src/one/a.test.ts', 'import { a } from "./a";\n')
        self.write('app/src/two/b.ts', 'export const b = 1;\n')
        self.write('tools/run', '#!/usr/bin/env bash\n')
        self.write('README.md', '# fixture\n')
        self.unit('one', ['app/src/one/**'])
        self.unit('two', ['app/src/two/**'])
        self.unit('tools', ['tools/run'])
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        units.reset()

    def tearDown(self):
        units.reset()
        self.tmp.cleanup()

    def registry(self, values):
        registry = json.loads((ROOT / 'config/registry/units.json').read_text())
        for name, value in values.items():
            registry['properties'][name]['default'] = value
        for item in registry['properties'].values():
            item['x-readers'] = []
        self.write('config/registry/units.json', registry)

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))

    def unit(self, unit, paths, **extra):
        self.write(f'units/{unit}/unit.json', {'id': unit, 'purpose': f'The {unit} unit.', 'cell': 'demo',
                                               'owner': OWNER, 'paths': paths, **extra})

    def check(self):
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        units.reset()
        return unit_check.check(self.root)


class Ownership(Fixture):
    def test_d067_every_production_file_in_exactly_one_unit_passes(self):
        self.assertEqual(self.check(), ([], []))

    def test_d067_a_production_file_of_no_unit_fails(self):
        self.write('app/src/three/c.ts', 'export const c = 1;\n')
        errors, _ = self.check()
        self.assertEqual(errors, ['app/src/three/c.ts is a production file of no unit; add it to the manifest of the '
                                  'unit that owns it (D-067 (6))'])

    def test_d067_a_file_of_two_units_fails_test_files_included(self):
        self.unit('also', ['app/src/one/a.test.ts'])
        errors, _ = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn('app/src/one/a.test.ts belongs to 2 units (also, one)', errors[0])

    def test_d067_a_test_file_or_a_file_outside_the_production_globs_may_have_no_unit(self):
        self.unit('one', ['app/src/one/a.ts'])
        self.assertEqual(self.check()[0], [])  # a.test.ts and README.md belong to no unit

    def test_d067_an_untracked_file_is_not_judged(self):
        self.write('app/src/three/c.ts', 'export const c = 1;\n')
        units.reset()
        self.assertEqual(unit_check.check(self.root)[0], [])  # git ls-files: only what a commit would carry

    def test_d067_a_glob_that_matches_nothing_warns(self):
        self.unit('tools', ['tools/run', 'tools/gone.py'])
        errors, warnings = self.check()
        self.assertEqual(errors, [])
        self.assertEqual(warnings, ['units/tools: path tools/gone.py matches no tracked file; remove or update it'])

    def test_d067_an_invalid_manifest_fails_before_ownership_is_judged(self):
        self.unit('two', ['app/src/two/**'], owner='nobody-lane')
        errors, _ = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn('is not one of units.owners', errors[0])

    def test_d067_a_checkout_without_manifests_is_not_judged(self):
        shutil.rmtree(self.root / 'units')
        self.assertEqual(self.check(), ([], []))


class Oversize(Fixture):
    def setUp(self):
        super().setUp()
        self.write('app/src/two/b.ts', ''.join(f'export const b{index} = {index};\n' for index in range(12)))
        self.write('app/src/two/data.json', '[\n' + '1,\n' * 40 + '1\n]\n')

    def test_d067_a_unit_above_its_ceiling_warns_while_the_flag_is_off(self):
        errors, warnings = self.check()
        self.assertEqual(errors, [])
        self.assertEqual(warnings, ['units/two: 12 production lines above its ceiling of 10 (unit.oversize; split it, '
                                    'D-067 (7))'])

    def test_d067_the_flag_turns_oversize_into_an_error(self):
        self.registry(dict(SMALL, **{'units.oversize_fails': True}))
        errors, _ = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn('units/two: 12 production lines', errors[0])

    def test_d067_a_cited_override_is_the_unit_ceiling(self):
        self.unit('two', ['app/src/two/**'], budget={'units.size_ceiling': {'value': 20, 'decision': 'D-067'}})
        self.assertEqual(self.check(), ([], []))


class Requires(Fixture):
    """U2: a unit imports another only through a declared `requires`, measured by the graph that seeded it."""

    def test_dynamic_selections_do_not_require_vendor_units_but_are_verified(self):
        self.write('tools/port.py', "import importlib\nDYNAMIC_IMPORTS = ('load',)\n"
                   "def load(): return importlib.import_module('vendor')\n")
        self.write('tools/vendor.py', 'VALUE = 1\n')
        self.unit('tools', ['tools/run', 'tools/port.py'])
        self.unit('vendor', ['tools/vendor.py'])
        self.assertEqual(self.check(), ([], []))
        self.write('tools/port.py', "import importlib\nDYNAMIC_IMPORTS = ('load',)\n"
                   "def load(): return importlib.import_module('vendor')\n"
                   "def extra(): return importlib.import_module('other')\n")
        self.assertTrue(any('undeclared dynamic selection other' in error for error in self.check()[0]))
        self.write('tools/port.py', "import importlib\n"
                   "def load(): return importlib.import_module('vendor')\n")
        self.assertTrue(any('undeclared dynamic selection vendor' in error for error in self.check()[0]))
        self.write('tools/port.py', "import importlib\nDYNAMIC_IMPORTS = ('load',)\n"
                   "def load(): return importlib.import_module('gone')\n")
        self.assertTrue(any('target absent: gone' in error for error in self.check()[0]))
        self.write('tools/port.py', "import importlib\nDYNAMIC_IMPORTS = ('load',)\n"
                   "def load(name): return importlib.import_module(name)\n")
        errors, _ = self.check()
        self.assertTrue(any('must name a literal module' in error for error in errors))
        self.assertTrue(any('declared but not loaded' in error for error in errors))

    def importing(self, **extra):
        self.write('app/src/one/a.ts', 'import { b } from "../two/b";\nexport const a = b;\n')
        self.unit('one', ['app/src/one/**'], **extra)

    def test_u2_an_undeclared_import_between_units_fails(self):
        self.importing()
        errors, _ = self.check()
        self.assertEqual(len(errors), 1)
        self.assertIn('units/one: imports unit two without declaring it', errors[0])

    def test_u2_a_declared_import_passes(self):
        self.importing(requires={'two': '^1'})
        self.assertEqual(self.check(), ([], []))

    def test_u2_a_test_file_import_is_not_a_dependency(self):
        self.write('app/src/one/a.test.ts', 'import { b } from "../two/b";\n')
        self.assertEqual(self.check(), ([], []))

    def test_u2_requiring_an_unknown_unit_fails_and_an_unused_one_warns(self):
        self.unit('one', ['app/src/one/**'], requires={'ghost': '^1', 'two': '^1'})
        errors, warnings = self.check()
        self.assertEqual(errors, ['units/one: requires unknown unit ghost'])
        self.assertEqual(warnings, ['units/one: requires two, which it no longer imports; remove it'])


    def fixed(self):
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        units.reset()
        return unit_check.fix_requires(self.root)

    def test_f107_fix_requires_adds_the_undeclared_import_and_the_check_passes(self):
        self.importing()
        self.unit('two', ['app/src/two/**'])
        self.write('app/src/two/b.ts', 'export const b = 1;\n')
        self.assertEqual(len(self.fixed()), 1)
        manifest = json.loads((self.root / 'units/one/unit.json').read_text())
        self.assertEqual(manifest['requires'], {'two': '^1'})
        self.assertEqual(self.check(), ([], []))

    def test_f107_fix_requires_drops_an_unused_unit_keeps_ranges_and_unknown_units(self):
        self.importing(requires={'two': '^2', 'three': '^1', 'ghost': '^1'})
        self.unit('two', ['app/src/two/**'])
        self.unit('three', ['app/src/three/**'])
        self.write('app/src/two/b.ts', 'export const b = 1;\n')
        self.write('app/src/three/c.ts', 'export const c = 1;\n')
        self.fixed()
        manifest = json.loads((self.root / 'units/one/unit.json').read_text())
        self.assertEqual(manifest['requires'], {'ghost': '^1', 'two': '^2'})

    def test_f107_fix_requires_leaves_a_correct_manifest_untouched(self):
        self.importing(requires={'two': '^1'})
        self.unit('two', ['app/src/two/**'])
        self.write('app/src/two/b.ts', 'export const b = 1;\n')
        before = (self.root / 'units/one/unit.json').read_text()
        self.assertEqual(self.fixed(), [])
        self.assertEqual((self.root / 'units/one/unit.json').read_text(), before)


class StructureCheckWiring(Fixture):
    def setUp(self):
        super().setUp()
        regime.pin(False)  # a direct run judges as the runner does: no live exception regime lifting the lock (D-272)
        self.addCleanup(regime.pin, None)

    def test_d064d_structure_check_fails_on_a_file_of_no_unit(self):
        self.write('app/src/three/c.ts', 'export const c = 1;\n')
        self.check()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = structure.main(['--root', str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn('FAIL app/src/three/c.ts is a production file of no unit', out.getvalue())


class OperationalResponsibility(unittest.TestCase):
    def document(self, records=None, **row):
        return {'operations': {'merge': {'name': 'merge', **row}},
                'responsibility': {'accepted': {} if records is None else {'merge': records}}}

    def acceptance(self, owner='release-role'):
        return {'responsible': owner, 'accepted_by': owner, 'evidence': 'local fixture acceptance'}

    def test_absence_is_refused_even_with_path_lane_or_implementation(self):
        document = self.document(responsible='engine-lane', adapters=['github'], units=['engine-events'])
        self.assertEqual(unit_check.operation_responsibility(document),
                         [('missing-responsibility', 'merge: no accepted responsible')])

    def test_competing_accepted_responsibles_are_refused(self):
        findings = unit_check.operation_responsibility(self.document(
            [self.acceptance(), self.acceptance('other-role')]))
        self.assertEqual([kind for kind, _ in findings], ['conflicting-responsibility'])

    def test_one_explicit_accepted_responsible_passes(self):
        self.assertEqual(unit_check.operation_responsibility(self.document([self.acceptance()])), [])

    def test_attribution_without_matching_acceptance_is_refused(self):
        for record in ({'responsible': 'engine-lane'}, self.acceptance('unknown'),
                       dict(self.acceptance(), accepted_by='someone-else'),
                       dict(self.acceptance(), evidence='')):
            with self.subTest(record=record):
                kinds = [kind for kind, _ in unit_check.operation_responsibility(self.document([record]))]
                self.assertEqual(kinds, ['invalid-responsibility', 'missing-responsibility'])

    def test_malformed_unknown_and_observational_conflict_are_refused(self):
        document = self.document([self.acceptance()], responsible='different-role')
        document['responsibility']['accepted']['typo'] = [self.acceptance()]
        self.assertEqual([kind for kind, _ in unit_check.operation_responsibility(document)],
                         ['unknown-responsibility', 'conflicting-responsibility'])
        document['responsibility']['accepted'] = []
        self.assertEqual(unit_check.operation_responsibility(document)[0][0], 'invalid-responsibility')
        document = self.document('release-role')
        self.assertEqual([kind for kind, _ in unit_check.operation_responsibility(document)],
                         ['invalid-responsibility', 'missing-responsibility'])


if __name__ == '__main__':
    unittest.main()
