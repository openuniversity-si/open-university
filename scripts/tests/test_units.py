"""The unit manifests (D-067): the contract contracts/units/unit.v1.json, the owner, the budget override that must cite
a decision, the glob matcher and the ownership lookups M3 and G1b call.

Fixture repositories in a temporary directory with copies of the registry and the contract; no network, no clock.
"""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import units  # noqa: E402

COPIED = ('contracts/units/unit.v1.json', 'contracts/config/registry.v1.json', 'config/registry/units.json',
          'config/registry/config.json', 'config/registry/forge-events.json')
OWNER = config.get('units.owners')[0]


def manifest(unit, paths, **extra):
    return {'id': unit, 'purpose': f'The {unit} unit.', 'cell': 'demo', 'owner': OWNER, 'paths': paths, **extra}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        for name in COPIED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        self.write('docs/domain/DECISIONS.md', '| Id | Date |\n|---|---|\n| D-067 | today |\n')
        units.reset()

    def tearDown(self):
        units.reset()
        self.tmp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))

    def unit(self, data):
        self.write(f'units/{data["id"]}/unit.json', data)

    def errors(self):
        units.reset()
        return units.read(self.root)[1]


class Contract(Fixture):
    def test_d067_a_manifest_with_its_owner_and_paths_is_valid(self):
        self.unit(manifest('progress', ['products/demo/src/progress/**'], requires={'kernel-errors': '^1'},
                           decisions=['D-067'], premises=['P-03'], invariants=['INV-R3']))
        self.assertEqual(self.errors(), [])

    def test_d067_the_owner_is_required(self):
        data = manifest('progress', ['a/**'])
        del data['owner']
        self.unit(data)
        self.assertIn('"owner" is required', ' '.join(self.errors()))

    def test_d067_the_owner_must_be_a_registered_lane(self):
        self.unit(dict(manifest('progress', ['a/**']), owner='nobody-lane'))
        self.assertIn('is not one of units.owners', ' '.join(self.errors()))

    def test_d067_the_id_equals_its_directory(self):
        self.write('units/other/unit.json', manifest('progress', ['a/**']))
        self.assertIn("not its directory 'other'", ' '.join(self.errors()))

    def test_d067_a_literal_budget_is_refused(self):
        self.unit(manifest('progress', ['a/**'], budget={'prodLines': 1500, 'contextTokens': 50000}))
        self.assertTrue(self.errors())

    def test_d067_an_override_without_a_decision_is_refused(self):
        self.unit(manifest('progress', ['a/**'], budget={'units.size_ceiling': {'value': 2000}}))
        self.assertIn('"decision" is required', ' '.join(self.errors()))

    def test_d067_an_override_citing_an_unrecorded_decision_is_refused(self):
        self.unit(manifest('progress', ['a/**'], budget={'units.size_ceiling': {'value': 2000, 'decision': 'D-999'}}))
        self.assertIn('an override needs a recorded decision', ' '.join(self.errors()))

    def test_d067_the_budget_is_the_registry_value_unless_a_cited_override_replaces_it(self):
        self.unit(manifest('progress', ['a/**']))
        self.unit(manifest('catalog', ['b/**'], budget={'units.size_ceiling': {'value': 2000, 'decision': 'D-067'}}))
        self.assertEqual(self.errors(), [])
        self.assertEqual(units.budget('progress', 'units.size_ceiling', self.root), config.get('units.size_ceiling'))
        self.assertEqual(units.budget('catalog', 'units.size_ceiling', self.root), 2000)
        self.assertEqual(units.budget('catalog', 'units.context_budget', self.root), config.get('units.context_budget'))

    def test_d067_a_path_glob_has_no_leading_slash_or_negation(self):
        self.unit(manifest('progress', ['/abs/**', '!a/b']))
        self.assertEqual(len([line for line in self.errors() if 'does not match' in line]), 2)

    def test_lane_own_a_shared_path_is_one_of_its_paths(self):
        self.unit(manifest('census', ['scripts/lib/census/**', 'config/census.json'], shared=['config/census.json']))
        self.assertEqual(self.errors(), [])

    def test_lane_own_a_shared_path_outside_its_paths_is_refused(self):
        self.unit(manifest('census', ['scripts/lib/census/**'], shared=['config/census.json']))
        self.assertIn("shared names 'config/census.json', which is not one of its paths",
                      ' '.join(self.errors()))

    def test_lane_own_a_shared_path_follows_the_path_glob_rules(self):
        self.unit(manifest('census', ['a/**', 'a/b'], shared=['/a/**', 'a/b', 'a/b']))
        found = ' '.join(self.errors())
        self.assertIn("$.shared[0]: '/a/**' does not match", found)
        self.assertIn('$.shared: items are not unique', found)


class Lookups(Fixture):
    def setUp(self):
        super().setUp()
        self.unit(manifest('progress', ['products/demo/src/progress/**']))
        self.unit(dict(manifest('engine-gate', ['scripts/gate-*', 'scripts/lib/gate_*.py']),
                       owner=config.get('units.owners')[-1]))

    def test_d067_the_glob_keeps_a_star_inside_one_segment(self):
        self.assertTrue(units.match('products/demo/src/progress/**', 'products/demo/src/progress/server/a.ts'))
        self.assertTrue(units.match('products/demo/src/progress/**', 'products/demo/src/progress/a.ts'))
        self.assertFalse(units.match('products/demo/src/progress/**', 'products/demo/src/progressive/a.ts'))
        self.assertTrue(units.match('scripts/gate-*', 'scripts/gate-dev'))
        self.assertFalse(units.match('scripts/*', 'scripts/lib/gate_plan.py'))
        self.assertTrue(units.match('**/*.test.ts', 'products/demo/src/x/y.test.ts'))

    def test_d067_unit_of_and_owner_of_path_answer_which_unit_and_lane_own_a_path(self):
        self.assertEqual(units.unit_of('products/demo/src/progress/contract.ts', self.root), 'progress')
        self.assertEqual(units.owner_of_path('scripts/lib/gate_plan.py', self.root), config.get('units.owners')[-1])
        self.assertIsNone(units.unit_of('README.md', self.root))
        self.assertIsNone(units.owner_of_path('README.md', self.root))
        self.assertEqual(units.owner_of('progress', self.root), OWNER)
        with self.assertRaises(KeyError):
            units.owner_of('missing', self.root)

    def test_d067_a_path_of_two_units_is_an_error_not_a_guess(self):
        self.unit(manifest('gate-too', ['scripts/gate-dev']))
        units.reset()
        self.assertEqual(units.units_of('scripts/gate-dev', self.root), ['engine-gate', 'gate-too'])
        with self.assertRaises(units.UnitError):
            units.unit_of('scripts/gate-dev', self.root)

    def test_d067_lookups_refuse_a_broken_map(self):
        self.unit(dict(manifest('progress', ['a/**']), owner='nobody-lane'))
        units.reset()
        with self.assertRaises(units.UnitError):
            units.unit_of('a/b', self.root)

    def test_d067_the_cli_prints_unit_and_owner(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = units.main(['--root', str(self.root), 'owner', 'products/demo/src/progress/a.ts', 'README.md'])
        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue().splitlines(), [f'products/demo/src/progress/a.ts\tprogress\t{OWNER}', 'README.md\t-\t-'])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(units.main(['--root', str(self.root), 'who', 'missing']), 2)
            self.assertEqual(units.main(['--root', str(self.root), 'check']), 0)


class Home(unittest.TestCase):
    # Moved from test_unit_addresses.py with units.home (OU-DECOUPLE F4 (D-111)): it anchors a contract entry.
    def test_d067_the_home_is_the_deepest_directory_holding_every_path(self):
        self.assertEqual(units.home({'paths': ['a/b/**']}), 'a/b')
        self.assertEqual(units.home({'paths': ['a/b/c.ts', 'a/b/d/**']}), 'a/b')
        self.assertEqual(units.home({'paths': ['a/b/c.ts', 'a/e/*.ts']}), 'a')
        self.assertEqual(units.home({'paths': ['a/b/[slug]/**']}), 'a/b/[slug]')
        self.assertEqual(units.home({'paths': ['a/x.ts', 'b/y.ts']}), '')


class Repository(unittest.TestCase):
    def test_d067_every_manifest_of_this_checkout_is_valid(self):
        units.reset()
        self.assertEqual(units.read()[1], [])

    def test_lane_own_the_census_and_the_web_config_are_shared(self):
        """Every lane regenerates the literal census: it decides no lane (LANE-OWN). The web config and the literal
        catalogs left with Open University (OU-DECOUPLE F4 (D-111))."""
        units.reset()
        found = units.read()[0]
        self.assertEqual(found['engine-structure']['shared'], ['scripts/lib/absolute-literals-baseline/**'])

    def test_lane_own_the_generated_registry_types_and_site_text_are_shared(self):
        """Every registry change regenerates scripts/lib/generated: the sources decide the lane, never their outputs
        (TRAIN-VERDICT-FIX). The x-text module (#649) left with Open University (OU-DECOUPLE F4 (D-111))."""
        units.reset()
        found = units.read()[0]
        self.assertEqual(found['engine-config']['shared'], ['scripts/lib/generated/**'])

if __name__ == '__main__':
    unittest.main()
