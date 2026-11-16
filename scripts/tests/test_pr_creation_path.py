"""Opening a PR has one path (lane 4, D-236): `scripts/deliver --open` (lane-ship --create until F9). It checks the body with
`structure-check --pr-body` before it opens anything, and opens the change through the forge port: only the forge adapters post to the pulls
endpoint. Each test fails without its guard."""
import ast
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import deliver  # noqa: E402

POSTS_PULLS = re.compile(r"""['"]POST['"][^\n]*/pulls['"]|/pulls['"][^\n]*-X['"],\s*['"]POST""")


class BodyCheck(unittest.TestCase):
    def test_the_body_goes_to_structure_check_pr_body_and_only_its_fail_lines_count(self):
        seen = []

        def fake(argv, **kwargs):
            seen.append(argv)
            return subprocess.CompletedProcess(argv, 1, 'PASS other\nFAIL body: no plan\nWARN x\n', '')

        self.assertEqual(deliver.body_problems('BODY.md', ROOT, fake), ['FAIL body: no plan'])
        self.assertEqual([Path(seen[0][0]).name, *seen[0][1:]], ['structure-check', '--pr-body', 'BODY.md'])


class OpenOrder(unittest.TestCase):
    def test_open_checks_the_body_before_it_opens_and_stops_on_a_problem(self):
        tree = ast.parse((ROOT / 'scripts' / 'lib' / 'deliver.py').read_text())
        opener = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'open_pr')
        guarded = next(node for node in ast.walk(opener) if isinstance(node, ast.Try))
        text = [ast.unparse(node) for node in guarded.body]
        order = {name: next(index for index, line in enumerate(text) if name in line)
                 for name in ('body_problems', "'create'")}
        self.assertLess(order['body_problems'], order["'create'"])
        refusal = guarded.body[order['body_problems'] + 1]
        self.assertIsInstance(refusal, ast.If)
        self.assertTrue(any(isinstance(node, ast.Return) for node in ast.walk(refusal)), 'a bad body does not stop --open')


class OnePath(unittest.TestCase):
    def test_only_the_forge_adapters_post_to_the_pulls_endpoint(self):
        found = sorted(str(path.relative_to(ROOT)) for path in (ROOT / 'scripts').rglob('*')
                       if path.suffix in ('.py', '.sh') and '/tests/' not in str(path) and '__pycache__' not in str(path)
                       and POSTS_PULLS.search(path.read_text(errors='ignore')))
        catalog = json.loads((ROOT / 'scripts/lib/adapters/engine-vendors.json').read_text())
        adapters = {path for vendor in catalog['vendors'] if vendor['kind'] == 'forge'
                    for path in vendor.get('adapters', [])}
        self.assertEqual(set(found) - adapters, set(),
                         'only registered forge adapters may create PRs')


if __name__ == '__main__':
    unittest.main()
