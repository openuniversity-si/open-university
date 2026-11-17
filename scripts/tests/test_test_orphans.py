"""The orphan-test check (TX25, D-070): every test_*.py is run by exactly one *.test.sh wrapper. Hermetic: temp dirs."""
import contextlib
import io
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import test_orphans  # noqa: E402

COPIED = ('contracts/config/registry.v1.json', 'contracts/events/config.changed.v1.json', 'config/registry/config.json',
          'config/registry/test-orphans.json')
HEAD = '#!/usr/bin/env bash\nset -euo pipefail\nroot="$(cd "$(dirname "$0")/../.." && pwd)"\n'


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in COPIED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        self.tests = self.root / config.get('test-orphans.tests_dir', ROOT)

    def tearDown(self):
        self.tmp.cleanup()

    def add_test(self, name):
        path = self.tests / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('import unittest\n')
        return path

    def wrapper(self, name, *lines):
        self.tests.mkdir(parents=True, exist_ok=True)
        (self.tests / f'{name}.test.sh').write_text(HEAD + ''.join(line + '\n' for line in lines))

    def errors(self):
        return test_orphans.check(self.root)

    def one_error(self):
        errors = self.errors()
        self.assertEqual(len(errors), 1, errors)
        return errors[0]


class Runs(Repo):
    def test_each_test_run_by_its_own_wrapper_passes(self):
        self.add_test('test_alpha.py')
        self.add_test('test_beta.py')
        self.wrapper('alpha', 'python3 "$root/scripts/tests/test_alpha.py"')
        self.wrapper('beta', 'python3 "$(dirname "$0")/test_beta.py"')
        self.assertEqual(self.errors(), [])

    def test_a_module_glob_runs_its_split_files(self):
        for name in ('test_alpha.py', 'test_alpha_split.py', 'test_alphabet.py'):
            self.add_test(name)
        self.wrapper('alpha', 'for test in "$root"/scripts/tests/test_alpha*.py; do python3 "$test"; done')
        self.assertEqual(self.errors(), [])

    def test_forms_in_use_on_the_base_are_read(self):
        for name in ('test_discover.py', 'test_here.py', 'test_listed.py', 'test_brace.py'):
            self.add_test(name)
        self.wrapper('discover', """python3 -m unittest discover -s "$root/scripts/tests" -p 'test_discover.py'""")
        self.wrapper('here', 'here="$(dirname "$0")"', 'python3 "$here/test_here.py"')
        self.wrapper('listed', 'for test in test_listed.py; do python3 "$root/scripts/tests/$test"; done')
        self.wrapper('brace', 'python3 "${here}/test_brace.py"')
        self.assertEqual(self.errors(), [])

    def test_the_tx24_directory_form_is_accepted(self):
        self.add_test('train/test_lease.py')
        self.add_test('train/test_queue.py')
        self.add_test('test_train.py')
        self.wrapper('train',
                     'for test in "$root"/scripts/tests/train/test_*.py "$root"/scripts/tests/test_train.py; do',
                     '  python3 "$test"', 'done')
        self.assertEqual(self.errors(), [])

    def test_a_discover_line_is_scoped_to_its_directory(self):
        self.add_test('train/test_lease.py')
        self.add_test('test_other.py')
        self.wrapper('train', """python3 -m unittest discover -s "$root/scripts/tests/train" -p 'test_*.py'""")
        self.wrapper('other', 'python3 "$root/scripts/tests/test_other.py"')
        self.assertEqual(self.errors(), [])

    def test_fixture_directories_hold_no_tests(self):
        for skipped in config.get('test-orphans.skip_dirs', ROOT):
            self.add_test(f'{skipped}/test_fixture.py')
        self.assertEqual(self.errors(), [])

    def test_a_repository_without_the_key_is_not_checked(self):
        (self.root / 'config/registry/test-orphans.json').unlink()
        self.add_test('test_alone.py')
        self.assertEqual(self.errors(), [])


class Orphans(Repo):
    def test_a_test_no_wrapper_runs_fails_and_names_the_wrapper_to_add(self):
        self.add_test('test_gate_gc.py')
        self.assertEqual(self.one_error(), 'scripts/tests/test_gate_gc.py: run by no wrapper; add '
                         'scripts/tests/gate-gc.test.sh running "$root"/scripts/tests/test_gate_gc*.py, '
                         'with its covers manifest')

    def test_a_split_of_an_exact_name_fails_and_names_the_glob_to_widen(self):
        self.add_test('test_program.py')
        self.add_test('test_program_split.py')
        self.wrapper('program', 'python3 "$root/scripts/tests/test_program.py"')
        self.assertEqual(self.one_error(), 'scripts/tests/test_program_split.py: run by no wrapper; widen '
                         '"test_program.py" in scripts/tests/program.test.sh:4 to "test_program*.py"')

    def test_a_name_in_a_comment_does_not_run_it(self):
        self.add_test('test_quiet.py')
        self.wrapper('quiet', '# test_quiet.py runs elsewhere', 'echo ok  # not test_quiet.py either')
        self.assertIn('scripts/tests/test_quiet.py: run by no wrapper', self.one_error())

    def test_a_module_test_needs_a_module_glob(self):
        self.add_test('train/test_lease.py')
        self.wrapper('train', 'for test in "$root"/scripts/tests/test_*.py; do python3 "$test"; done')
        errors = self.errors()
        self.assertIn('scripts/tests/train/test_lease.py: run by no wrapper; add scripts/tests/train.test.sh running '
                      '"$root"/scripts/tests/train/test_lease*.py, with its covers manifest', errors)


class Doubles(Repo):
    def test_a_test_two_wrappers_run_fails_and_names_both_globs(self):
        self.add_test('test_db_migrate.py')
        wrappers = {'cloud-tail': 'python3 "$(dirname "$0")/test_db_migrate.py"',
                    'db': 'for test in "$(dirname "$0")"/test_db*.py; do python3 "$test"; done'}
        for name, line in wrappers.items():
            self.wrapper(name, line)
        self.assertEqual(self.one_error(), f'scripts/tests/test_db_migrate.py: run by {len(wrappers)} wrappers '
                         '(scripts/tests/cloud-tail.test.sh:4 "test_db_migrate.py", '
                         'scripts/tests/db.test.sh:4 "test_db*.py"); '
                         'narrow every glob but the one of the wrapper that owns it')

    def test_wrappers_that_each_run_a_shard_of_their_own_own_the_test_together(self):
        # SHARD-OWNERS: deploy-slow-a/b/c run test_deploy_sh.py in three parts (DEPLOY_TEST_SHARD)
        self.add_test('test_deploy_sh.py')
        for part in ('slow-a', 'slow-b', 'slow-c'):
            self.wrapper(f'deploy-{part}', f'DEPLOY_TEST_SHARD={part} python3 "$root/scripts/tests/test_deploy_sh.py"')
        self.assertEqual(self.errors(), [])
        self.wrapper('deploy-slow-d', 'DEPLOY_TEST_SHARD=slow-a python3 "$root/scripts/tests/test_deploy_sh.py"')
        self.assertIn('run by 4 wrappers', self.one_error())  # two lines on one part: it runs twice
        self.wrapper('deploy-slow-d', 'python3 "$root/scripts/tests/test_deploy_sh.py"')
        self.assertIn('run by 4 wrappers', self.one_error())  # a whole run beside the parts: it runs twice

    def test_one_wrapper_naming_a_test_twice_runs_it_once(self):
        self.add_test('test_twice.py')
        self.wrapper('twice', 'python3 "$root/scripts/tests/test_twice.py"', 'echo "$root/scripts/tests/test_tw*.py"')
        self.assertEqual(self.errors(), [])


class Dangling(Repo):
    def test_a_glob_that_matches_no_test_fails(self):
        self.add_test('test_kept.py')
        self.wrapper('kept', 'python3 "$root/scripts/tests/test_kept.py"',
                     """python3 -m unittest discover -s "$root/scripts/tests" -p 'test_renamed.py'""")
        self.assertEqual(self.one_error(), 'scripts/tests/kept.test.sh:5: "test_renamed.py" matches no test under '
                         'scripts/tests; point it at the renamed test or drop it')


class Cli(unittest.TestCase):
    def test_the_cli_exits_on_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in COPIED:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(ROOT / name, root / name)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(test_orphans.main(['--root', str(root)]), 0)
                (root / 'scripts/tests').mkdir(parents=True)
                (root / 'scripts/tests/test_lost.py').write_text('')
                self.assertEqual(test_orphans.main(['--root', str(root)]), 1)
            self.assertIn('ERROR scripts/tests/test_lost.py: run by no wrapper', out.getvalue())


if __name__ == '__main__':
    unittest.main()
