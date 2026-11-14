"""What the unit manifests claim in this checkout (D-064 (d), TX21): every production file belongs to exactly one unit, and every
covers file to at most its primary's unit. The two tests of the unit tests that read the whole tree, apart from the fixture tests
(D-175) so that their wide covers do not make those miss.
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import unit_check  # noqa: E402
import units  # noqa: E402


class Production(unittest.TestCase):
    def test_d064d_every_production_file_of_this_checkout_belongs_to_exactly_one_unit(self):
        units.reset()
        self.assertEqual(unit_check.check(ROOT)[0], [])


class Covers(unittest.TestCase):
    def test_every_covers_file_of_this_checkout_has_at_most_its_primarys_unit(self):
        units.reset()
        root = ROOT
        for path in sorted((root / 'scripts' / 'tests' / 'covers').glob('*.json')):
            relative = path.relative_to(root).as_posix()
            primary = units.primary_of(relative, root)
            self.assertTrue(primary and (root / primary).is_file(), relative)
            self.assertEqual(units.units_of(relative, root), units.claims_of(primary, root) or
                             units.claims_of(relative, root))


if __name__ == '__main__':
    unittest.main()
