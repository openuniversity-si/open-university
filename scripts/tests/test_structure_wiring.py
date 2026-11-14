"""The structure check is run by the tools, not by hand (lane 4, D-236): the local checks (commit-check --local, the pre-push
hook) carry it as an enabled entry, so no push skips it (lane-ship ran it too until F9). The test fails without its wiring."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent


class LocalChecks(unittest.TestCase):
    def test_the_local_checks_carry_the_structure_check_enabled(self):
        found = []

        def walk(node):
            if isinstance(node, dict):
                if node.get('id') == 'structure_fast':
                    found.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(json.loads((ROOT / 'config' / 'registry' / 'local-checks.json').read_text()))
        self.assertEqual(len(found), 1, 'the local checks lost structure_fast')
        self.assertIs(found[0]['enabled'], True)
        self.assertEqual(found[0]['handler'], 'structure_fast')


if __name__ == '__main__':
    unittest.main()
