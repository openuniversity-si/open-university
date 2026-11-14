"""The derived census of unregistered engine literals (LT1, TX22): the allowed counts are the census of the base tree,
computed at check time; no list is committed. The same fixtures fail as with the committed list: a new literal in a new
file, a file that gains one, a value moved to another unit; a value moved between files of one unit passes.

Fixture git checkouts in a temporary directory (the Checkout of test_literal_census.py); no network, no clock.
"""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_literal_census import CASES, Checkout, ROOT  # noqa: E402
import literal_census  # noqa: E402

REFUSED = {case['name']: case for case in CASES['refused']}
CLEAN = CASES['allowed'][0]['source']


def by_folder(path, root=None):
    """The unit of a fixture path: its folder name (the fixture has no manifests)."""
    return Path(path).parent.name


class Derived(Checkout):
    def stage(self):
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)  # the scan reads tracked files

    def based(self, files):
        for name, source in files.items():
            self.write(name, source)
        return self.commit()

    def errors(self, base):
        self.stage()
        return '\n'.join(literal_census.check(self.root, base)[0])

    def test_lt1_a_new_literal_in_a_new_file_fails_and_names_its_line(self):
        base = self.based({'scripts/lib/lane.py': CLEAN})
        case = REFUSED['a url']
        self.write('scripts/lib/fresh.py', CLEAN + case['source'])
        errors = self.errors(base)
        found = literal_census.key(*case['found'][0])
        self.assertIn(f'{found} is written 1 times and the census of {base}', errors)
        self.assertIn(f'allows 0, at scripts/lib/fresh.py:{len(CLEAN.splitlines()) + 1};', errors)
        self.assertIn(literal_census.FIX, errors)

    def test_lt1_a_file_that_gains_a_literal_fails(self):
        case = REFUSED['a python number']
        base = self.based({'scripts/lib/lane.py': case['source']})
        self.write('scripts/lib/lane.py', case['source'] + case['source'])
        self.assertIn(f'{literal_census.key(*case["found"][0])} is written ', self.errors(base))

    def test_lt1_the_lines_are_named_in_file_order(self):
        case = REFUSED['a python number']
        base = self.based({'scripts/lib/lane.py': CLEAN})
        self.write('scripts/lib/lane.py', 'def nested():\n    ' + case['source'] + case['source'])  # the AST meets 3 before 2
        self.assertIn('allows 0, at scripts/lib/lane.py:2, scripts/lib/lane.py:3;', self.errors(base))

    def test_lt1_a_unit_never_allows_a_value_more_times_than_the_base(self):
        case = REFUSED['a python number']
        base = self.based({'scripts/lib/lane.py': case['source']})
        self.write('scripts/lib/lane.py', case['source'] + case['source'])
        self.assertIn('allows 1, at scripts/lib/lane.py:1, scripts/lib/lane.py:', self.errors(base))
        self.write('scripts/lib/lane.py', CLEAN)
        self.assertEqual(self.errors(base), '')

    def test_lt1_a_removed_literal_passes_with_nothing_to_rewrite(self):
        case = REFUSED['a python number']
        base = self.based({'scripts/lib/lane.py': case['source']})
        self.write('scripts/lib/lane.py', CLEAN)
        self.assertEqual(self.errors(base), '')
        self.write('scripts/lib/lane.py', case['source'])
        self.assertEqual(self.errors(base), '')

    def test_lt1_a_value_moved_between_files_of_one_unit_passes(self):
        case = REFUSED['a host']
        base = self.based({'scripts/lib/lane_a/one.py': case['source'], 'scripts/lib/lane_a/two.py': CLEAN})
        self.write('scripts/lib/lane_a/one.py', CLEAN)
        self.write('scripts/lib/lane_a/two.py', case['source'])
        with mock.patch.object(literal_census.units, 'unit_of', by_folder):
            self.assertEqual(self.errors(base), '')

    def test_lt1_a_value_moved_to_another_unit_fails(self):
        case = REFUSED['a host']
        base = self.based({'scripts/lib/lane_a/one.py': case['source'], 'scripts/lib/lane_b/two.py': CLEAN})
        self.write('scripts/lib/lane_a/one.py', CLEAN)
        self.write('scripts/lib/lane_b/two.py', case['source'])
        with mock.patch.object(literal_census.units, 'unit_of', by_folder):
            errors = self.errors(base)
        self.assertIn(f'lane_b: {literal_census.key(*case["found"][0])} is written 1 times', errors)
        self.assertIn('at scripts/lib/lane_b/two.py:', errors)

    def test_lt1_a_renamed_file_keeps_its_literals(self):
        case = REFUSED['a python number']
        base = self.based({'scripts/lib/lane.py': case['source']})
        subprocess.run(['git', '-C', str(self.root), 'mv', 'scripts/lib/lane.py', 'scripts/lib/renamed.py'], check=True)
        self.assertEqual(self.errors(base), '')

    def test_lt1_tests_are_scanned_and_generated_types_are_not(self):
        base = self.based({'scripts/lib/lane.py': CLEAN})
        case = CASES['refused'][0]
        self.write('scripts/tests/test_lane.py', case['source'])
        self.write('scripts/lib/generated/lane.py', case['source'])
        errors = self.errors(base)
        self.assertIn('at scripts/tests/test_lane.py:', errors)
        self.assertNotIn('generated', errors)

    def test_lt1_an_unknown_base_fails_closed(self):
        self.based({'scripts/lib/lane.py': CLEAN})
        errors = self.errors('origin/absent')
        self.assertIn('literals: no merge-base of origin/absent and HEAD', errors)
        self.assertIn('nothing is allowed (fail closed)', errors)

    def test_lt1_the_repository_spells_no_value_more_times_than_its_base(self):
        head = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout
        self.assertEqual(literal_census.check(ROOT, head.strip())[0], [])


if __name__ == '__main__':
    unittest.main()
