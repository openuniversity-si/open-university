"""The gate's "measurement checks" stage (D-322): the absolute baseline, the census, the shared literals and the budgets
of the tree, and the PR body's effort block; the structure check imports none of them. Fixture repositories, no network."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import census  # noqa: E402
import measurement_checks  # noqa: E402

ASSETS = {'version': 1, 'entries': [
    {'category': 'doc', 'paths': ['docs/**'], 'protects': ['D-001'], 'retire': 'never: the constitution'},
    {'category': 'script', 'paths': ['scripts/lib/absolute-literals-baseline/*.json'], 'protects': ['D-001'],
     'retire': 'never: x'}]}
BLOCK = ('## Cheapest useful effort\nAction: the gate run.\nCost: 5 min.\nRequirement: Daniel, to merge it.\n'
         'Cheaper rejected: the unit tests alone (they skip the stage).\n\n')


def write(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class Tree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        write(self.root, {'docs/structure/assets.json': json.dumps(ASSETS)})

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@x', GIT_COMMITTER_NAME='t',
                                GIT_COMMITTER_EMAIL='t@x', GIT_CONFIG_NOSYSTEM='1', HOME=str(self.root)))

    def commit_base(self):
        self.git('init', '-q')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.git('tag', 'base')

    def check(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = measurement_checks.main(['check', '--root', str(self.root), *args])
        return code, out.getvalue()

    def assert_fails(self, needle, *args):
        code, out = self.check(*args)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL ' , out)
        self.assertIn(needle, out)

    def baseline(self, files):
        folder = self.root / 'scripts/lib/absolute-literals-baseline'
        for stale in folder.glob('*.json') if folder.is_dir() else []:
            stale.unlink()
        areas = {}
        for path, values in files.items():
            areas.setdefault(census.area(path), {})[path] = values
        write(self.root, {f'scripts/lib/absolute-literals-baseline/{area}.json': json.dumps({'description': 'd', 'files': found})
                          for area, found in areas.items()})

    def shared(self, values, reasons=('two-areas',)):
        write(self.root, {'scripts/lib/shared-literals.json': json.dumps(
            {'description': 'd', 'reasons': {reason: 'why' for reason in reasons}, 'values': values})})

    def test_an_empty_tree_is_green_and_says_its_scope(self):
        code, out = self.check()
        self.assertEqual(code, 0, out)
        self.assertIn('measurement checks (check, no base): 0 error(s), 0 warning(s)', out)

    def test_d063_refuses_an_absolute_exception_list_that_grows_against_the_base(self):
        self.baseline({'products/demo/src/x/a.ts': {'number "0"': 2, 'string "x"': 1}})
        self.commit_base()
        self.baseline({'products/demo/src/x/a.ts': {'number "0"': 3, 'string "x"': 1}})
        self.assert_fails('number "0" allowed 2 times in base, 3 here; the list only shrinks per area (D-063, D-064 a)', '--base', 'base')
        self.baseline({'products/demo/src/x/a.ts': {'number "0"': 2, 'string "x"': 1, 'boolean "true"': 1}})
        self.assert_fails('boolean "true" allowed 0 times in base, 1 here', '--base', 'base')
        self.baseline({'products/demo/src/x/a.ts': {'number "0"': 1}, 'products/demo/src/x/moved.ts': {'number "0"': 1}})
        code, out = self.check('--base', 'base')
        self.assertEqual(code, 0, out)

    def test_d064a_the_exception_list_shrinks_per_area_and_value(self):
        self.baseline({'products/demo/src/admin/a.ts': {'boolean "true"': 1}, 'products/demo/scripts/b.ts': {'boolean "true"': 1}})
        self.commit_base()
        self.baseline({'products/demo/src/admin/a.ts': {'boolean "true"': 2}})
        self.assert_fails('absolute-literals-baseline/admin.json: boolean "true" allowed 1 times in base, 2 here; '
                          'the list only shrinks per area (D-063, D-064 a)', '--base', 'base')
        self.baseline({'products/demo/src/admin/moved.ts': {'boolean "true"': 1}})
        code, out = self.check('--base', 'base')
        self.assertEqual(code, 0, out)

    def test_d064_refuses_a_value_of_two_areas_outside_the_common_catalog(self):
        self.baseline({'products/demo/src/admin/a.ts': {'string "lesson"': 1, 'number "0"': 1},
                       'products/demo/scripts/b.ts': {'string "lesson"': 1, 'number "0"': 1}, 'products/demo/src/admin/c.ts': {'string "x"': 1}})
        self.assert_fails('string "lesson" is written in 2 areas (admin, scripts) and is not in the common catalog')
        self.shared({'string "lesson"': 'unknown'})
        self.assert_fails('string "lesson" names the unknown reason "unknown"')
        self.shared({'string "lesson"': 'two-areas'})
        code, out = self.check()
        self.assertEqual(code, 0, out)

    def test_d064_the_registered_list_only_shrinks_and_a_fixed_value_only_warns(self):
        self.baseline({'products/demo/src/admin/a.ts': {'string "lesson"': 1}, 'products/demo/scripts/b.ts': {'string "lesson"': 1}})
        self.shared({'string "lesson"': 'two-areas'})
        self.commit_base()
        self.shared({'string "lesson"': 'two-areas', 'string "course"': 'two-areas'})
        self.assert_fails('string "course" is not registered in base; the list only shrinks (D-064 c)', '--base', 'base')
        self.baseline({'products/demo/src/admin/a.ts': {'string "lesson"': 1}})
        self.shared({'string "lesson"': 'two-areas'})
        code, out = self.check('--base', 'base')
        self.assertEqual(code, 0, out)
        self.assertIn('WARN scripts/lib/shared-literals.json: string "lesson" no longer spans 2+ areas', out)

    def test_the_budget_check_runs_in_the_stage(self):
        found = []
        real = measurement_checks.budget_check.check
        try:
            measurement_checks.budget_check.check = lambda root, base=None: (found.append(base) or ['budgets: looser'], ['b'])
            self.assert_fails('budgets: looser', '--base', 'B')
        finally:
            measurement_checks.budget_check.check = real
        self.assertEqual(found, ['B'])


class Body(unittest.TestCase):
    BODY = 'Summary.\n\nPremises: none\nFit-Review: not reviewed (Daniel 2026-10-25: no review step)\n'

    def run_main(self, *args, fetch=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = measurement_checks.main(['body', '--root', str(ROOT), *args],
                                           **({'fetch': fetch} if fetch else {}))
        return code, out.getvalue()

    def test_a_body_file_without_the_block_is_red_and_with_it_green(self):
        with tempfile.NamedTemporaryFile('w', suffix='.md') as handle:
            handle.write(self.BODY)
            handle.flush()
            code, out = self.run_main('--pr-body', handle.name)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL effort: the PR body has no `## Cheapest useful effort` block', out)
        with tempfile.NamedTemporaryFile('w', suffix='.md') as handle:
            handle.write(BLOCK + self.BODY)
            handle.flush()
            code, out = self.run_main('--pr-body', handle.name)
        self.assertEqual(code, 0, out)
        self.assertIn('measurement checks (body, PR body file): 0 error(s)', out)

    def test_a_pr_is_judged_on_what_was_fetched_and_an_unreadable_one_is_red(self):
        asked = []

        def fetch(root, number, sha=None, observation=None):
            asked.append((number, sha, observation))
            return {'body': BLOCK + self.BODY, 'base': {}, 'created_at': None}
        code, out = self.run_main('--pr', '7', '--sha', 'abc', fetch=fetch)
        self.assertEqual((code, asked), (0, [(7, 'abc', None)]), out)

        def unreadable(*_, **__):
            raise RuntimeError('origin answered 503')
        code, out = self.run_main('--pr', '7', fetch=unreadable)
        self.assertEqual(code, 1, out)
        self.assertIn('FAIL measurement: PR #7 not readable (origin answered 503)', out)

    def test_without_a_pr_nothing_is_judged(self):
        code, out = self.run_main('--base', 'B')
        self.assertEqual(code, 0, out)
        self.assertIn('measurement checks (body, no PR): 0 error(s)', out)


class Wiring(unittest.TestCase):
    def test_the_structure_check_imports_no_measurement_module(self):
        source = (ROOT / 'scripts/lib/structure.py').read_text()
        for name in ('budget_check', 'census', 'effort', 'measurement_checks'):
            self.assertNotRegex(source, rf'(?m)^import {name}$')

    def test_the_gate_runs_the_stage_and_the_pr_metadata_runs_the_body(self):
        self.assertIn('"measurement checks") "$py" "$root/scripts/lib/measurement_checks.py" check',
                      (ROOT / 'scripts/gate-check').read_text())
        self.assertIn('measurement_checks.py" check', (ROOT / 'scripts/gate-local').read_text())
        self.assertIn('measurement_checks.py" body', (ROOT / 'scripts/lib/gate-hooks/prereq.sh').read_text())


if __name__ == '__main__':
    unittest.main()
