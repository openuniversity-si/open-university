#!/usr/bin/env python3
"""TX21: companion ownership is derived (units.companions): scripts/tests/covers/<t>.json belongs to the unit of
scripts/tests/<t>.test.sh. A claim by that unit is allowed, a claim by another unit is an error naming the manifest
line to remove; the checks that failed before still fail.

Fixture git repositories (the Fixture of test_unit_check.py, manifests written one path per line); no network.
"""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_unit_check as base  # noqa: E402
import units  # noqa: E402

COMPANIONS = [{'companion': 'scripts/tests/covers/*.json', 'primary': 'scripts/tests/*.test.sh'}]


class Companion(base.Fixture):
    def setUp(self):
        super().setUp()
        self.registry({**base.SMALL, 'units.production_globs': ['app/src/**', 'tools/**', 'scripts/**'],
                       'units.test_globs': ['**/*.test.*', 'scripts/tests/**'], 'units.companions': COMPANIONS})
        self.write('scripts/tests/report.test.sh', '#!/usr/bin/env bash\n')
        self.write('scripts/tests/covers/report.json', '{}\n')
        self.write('scripts/tests/loose.test.sh', '#!/usr/bin/env bash\n')
        self.write('scripts/tests/covers/loose.json', '{}\n')
        self.unit('report', ['scripts/tests/report.test.sh'])

    def unit(self, unit, paths, **extra):
        self.write(f'units/{unit}/unit.json', json.dumps({'id': unit, 'purpose': f'The {unit} unit.', 'cell': 'demo',
                                                          'owner': base.OWNER, 'paths': paths, **extra}, indent='  '))

    def line(self, unit, glob):
        rows = (self.root / f'units/{unit}/unit.json').read_text().splitlines()
        return next(index for index, row in enumerate(rows, 1) if f'"{glob}"' in row)

    def test_a_companion_belongs_to_the_unit_of_its_primary_without_a_claim(self):
        self.assertEqual(self.check()[0], [])
        self.assertEqual(units.unit_of('scripts/tests/covers/report.json', self.root), 'report')
        self.assertEqual(units.claims_of('scripts/tests/covers/report.json', self.root), [])

    def test_a_claim_by_the_same_unit_is_allowed(self):
        self.unit('report', ['scripts/tests/report.test.sh', 'scripts/tests/covers/report.json'])
        self.assertEqual(self.check()[0], [])
        self.assertEqual(units.unit_of('scripts/tests/covers/report.json', self.root), 'report')

    def test_a_claim_by_another_unit_names_the_line_to_remove_and_the_rule(self):
        # #740's shape: a central glob of one unit, the test and its sidecar listed by another
        self.unit('plan', ['tools/run', 'scripts/tests/covers/**'])
        self.unit('tools', ['tools/other'])
        self.unit('report', ['scripts/tests/report.test.sh', 'scripts/tests/covers/report.json'])
        errors = self.check()[0]
        self.assertEqual(errors, [
            'scripts/tests/covers/report.json belongs to report, the unit of scripts/tests/report.test.sh '
            '(units.companions: scripts/tests/covers/*.json follows scripts/tests/*.test.sh); remove '
            f'units/plan/unit.json:{self.line("plan", "scripts/tests/covers/**")} "scripts/tests/covers/**" (D-067 (6))'])
        self.assertEqual(units.unit_of('scripts/tests/covers/report.json', self.root), 'report')

    def test_a_companion_whose_primary_has_no_unit_keeps_its_claims_and_two_claims_still_fail(self):
        self.assertEqual(units.unit_of('scripts/tests/covers/loose.json', self.root), None)
        self.unit('plan', ['tools/run', 'scripts/tests/covers/loose.json'])
        self.unit('tools', ['tools/other'])
        self.assertEqual(self.check()[0], [])
        self.assertEqual(units.unit_of('scripts/tests/covers/loose.json', self.root), 'plan')
        self.unit('other', ['scripts/tests/covers/loose.json'])
        errors = self.check()[0]
        self.assertEqual(len(errors), 1)
        self.assertIn('scripts/tests/covers/loose.json belongs to 2 units (other, plan)', errors[0])
        self.assertIn(f'units/plan/unit.json:{self.line("plan", "scripts/tests/covers/loose.json")}', errors[0])

    def test_a_path_that_only_looks_like_a_companion_is_not_one(self):
        self.write('scripts/tests/covers/deep/report.json', '{}\n')
        self.assertEqual(units.primary_of('scripts/tests/covers/deep/report.json', self.root), None)
        self.assertEqual(units.primary_of('scripts/tests/covers/report.json', self.root), 'scripts/tests/report.test.sh')
        self.assertEqual(self.check()[0], [])


class Siblings(base.Fixture):
    def test_an_unowned_production_file_names_the_unit_of_its_siblings(self):
        self.write('app/src/two/c.ts', 'export const c = 1;\n')
        self.unit('two', ['app/src/two/b.ts'])
        self.assertEqual(self.check()[0], ['app/src/two/c.ts is a production file of no unit; add it to the manifest '
                                           'of the unit that owns it; the other files of its directory belong to two '
                                           '(D-067 (6))'])


class Unchanged(base.Fixture):
    """CRITICAL premise: the checks that failed before the companion rule still fail."""

    def test_a_production_file_of_no_unit_still_fails(self):
        self.write('app/src/three/c.ts', 'export const c = 1;\n')
        self.assertEqual(self.check()[0], ['app/src/three/c.ts is a production file of no unit; add it to the '
                                           'manifest of the unit that owns it (D-067 (6))'])

    def test_a_file_of_two_units_still_fails(self):
        self.unit('also', ['app/src/one/a.test.ts'])
        errors = self.check()[0]
        self.assertEqual(len(errors), 1)
        self.assertIn('app/src/one/a.test.ts belongs to 2 units (also, one)', errors[0])


if __name__ == '__main__':
    unittest.main()
