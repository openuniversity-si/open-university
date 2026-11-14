#!/usr/bin/env python3
"""The generated unit status has one row for every manifest of THIS checkout (moved from test_aggregates.py, D-225: it
reads the live units, so it runs with generate-tree.test.sh and not with the fixture half)."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import generate_status  # noqa: E402


class Status(unittest.TestCase):
    def test_this_repository_has_a_row_for_every_manifest(self):
        text = generate_status.render(ROOT, None)[generate_status.PATH]
        self.assertEqual(text.count('\n| `'), len(list((ROOT / 'units').glob('*/unit.json'))))


if __name__ == '__main__':
    unittest.main()
