#!/usr/bin/env python3
"""The decision table of THIS checkout has no row written by hand: after the first record, every row has its record or is
grandfathered (docs/domain/decisions/handwritten.txt). It reads the live table, so it has its own wrapper and covers."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import decision_table  # noqa: E402


class Repository(unittest.TestCase):
    def test_this_repository_has_no_row_written_by_hand(self):
        table = (ROOT / 'docs/domain/DECISIONS.md').read_text()
        self.assertEqual(decision_table.handwritten(table, decision_table.load(ROOT), decision_table.grandfathered(ROOT)), [])


if __name__ == '__main__':
    unittest.main()
