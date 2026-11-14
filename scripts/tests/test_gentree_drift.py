"""The live tree has no generator drift (D-173). The fixture tests of the generator are in test_generate.py; this one reads the
repository itself, so its covers are the whole registry, the units and the generated files."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import generate  # noqa: E402


class Tree(unittest.TestCase):
    def test_the_repository_has_no_drift(self):
        self.assertEqual(generate.drift(ROOT), [])


if __name__ == '__main__':
    unittest.main()
