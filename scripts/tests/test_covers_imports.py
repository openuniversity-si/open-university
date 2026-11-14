"""COVERS-IMPORTS (docs/operations/aws-revisao-arquitetura.md, finding 29): a test runs when what it imports changes.

The gate runs the script tests whose covers match the paths a PR changes. A manifest that did not name a module its
test imports left that test out of the PRs that changed the module: config-port went red on the base for a day when
the port's status changed (#491), and two more were found only by the box's whole suite (11/11). On 11/11, 33 of the
189 manifests missed 106 such paths. The rule, checked here for every manifest: each module of the engine
(infra/service/tower_infra) and each test helper (scripts/tests) that the manifest's Python tests import, directly or
through the test modules they import, is named by one of its covers patterns. Hermetic: it reads the checkout.
"""
import ast
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from gate_areas import glob_match  # noqa: E402

TESTS, ENGINE = ROOT / 'scripts' / 'tests', ROOT / 'infra' / 'service' / 'tower_infra'
MODULE = re.compile(r'(test_[A-Za-z0-9_]+\.py)')


def imported(path, seen):
    """The engine modules and test helpers a test module imports, through the test modules it imports."""
    if path in seen or not path.is_file():
        return set()
    seen.add(path)
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.ImportFrom) and node.module == 'tower_infra':
            names = [f'tower_infra.{alias.name}' for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        elif isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        else:
            continue
        for name in names:
            head, _, rest = name.partition('.')
            engine, helper = ENGINE / f"{rest.partition('.')[0]}.py", TESTS / f'{head}.py'
            if head == 'tower_infra' and rest and engine.is_file():
                found.add(str(engine.relative_to(ROOT)))
            elif helper.is_file():
                found.add(str(helper.relative_to(ROOT)))
                found |= imported(helper, seen)
    return found


def missing(manifest):
    """The imports of a manifest's Python tests that none of its covers patterns names."""
    spec = json.loads(manifest.read_text(encoding='utf-8'))
    script = ROOT / spec['script']
    if not script.is_file():
        return []
    need = set()
    for module in set(MODULE.findall(script.read_text(encoding='utf-8'))):
        need |= imported(TESTS / module, set())
    return sorted(path for path in need if not any(glob_match(path, pattern) for pattern in spec['covers']))


class CoversNameTheImports(unittest.TestCase):
    def test_every_manifest_names_what_its_tests_import(self):
        found = {manifest.name: missing(manifest) for manifest in sorted((TESTS / 'covers').glob('*.json'))}
        found = {name: paths for name, paths in found.items() if paths}
        self.assertEqual(found, {}, 'add these paths to the covers of each manifest: a change to one of them must run the test')

    def test_the_rule_sees_an_engine_module_a_helper_and_what_the_helper_imports(self):
        seen = imported(TESTS / 'test_infra_stall.py', set())  # it imports tower_infra.stall and, in its Postgres class, runner_world
        self.assertIn('infra/service/tower_infra/stall.py', seen)
        self.assertIn('scripts/tests/runner_world.py', seen)
        self.assertIn('infra/service/tower_infra/runner.py', seen)  # through runner_world
        self.assertNotIn('scripts/tests/test_infra_stall.py', seen)
        self.assertNotIn('scripts/tests/test_infra_runner.py', seen)  # RUNNER-WORLD: the world, not the runner's tests

    def test_only_the_runners_suite_runs_on_a_change_of_the_runners_tests(self):
        # RUNNER-WORLD: 18 suites imported RunnerWorld from test_infra_runner.py, so their covers named it and a new runner
        # test brought them all into the gate (48 of the selections of #640 to #649 came from that file)
        naming = sorted(manifest.name for manifest in (TESTS / 'covers').glob('*.json')
                        if 'scripts/tests/test_infra_runner.py' in json.loads(manifest.read_text()).get('covers', []))
        self.assertEqual(naming, ['infra-runner.json'])
        line = re.compile(r'^\s*(from test_infra_runner import|import test_infra_runner)', re.M)
        importing = sorted(path.name for path in TESTS.glob('test_*.py')
                           if path.name != 'test_infra_runner.py' and line.search(path.read_text()))
        self.assertEqual(importing, [])


if __name__ == '__main__':
    unittest.main()
