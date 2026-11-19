"""Runs one script test in a throwaway worktree without the files a covers pattern would stop covering: PASS means the pattern can go (D-178).

Fixture git repositories in a temporary directory; no network.
"""
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import covers_prove  # noqa: E402

IDENTITY = {'GIT_AUTHOR_NAME': 'T', 'GIT_AUTHOR_EMAIL': 't@example.test', 'GIT_COMMITTER_NAME': 'T', 'GIT_COMMITTER_EMAIL': 't@example.test'}


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'repo'
        self.root.mkdir()
        self.git('init', '--quiet')
        self.write('keep.txt', 'kept\n')
        self.write('drop/one.txt', 'one\n')
        self.write('scripts/tests/reads-keep.test.sh', '#!/usr/bin/env bash\nset -e\ncat keep.txt >/dev/null\n')
        self.write('scripts/tests/reads-drop.test.sh', '#!/usr/bin/env bash\nset -e\ncat drop/one.txt >/dev/null\n')
        self.git('add', '-A')
        self.git('commit', '--quiet', '-m', 'fixture')

    def git(self, *args):
        subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True, env={**os.environ, **IDENTITY})

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def prove(self, test, *globs):
        return covers_prove.prove(self.root, test, list(globs))


class Prove(Repo):
    def test_a_test_that_does_not_read_the_dropped_files_passes(self):
        self.assertEqual(self.prove('reads-keep', 'drop/**')[0], covers_prove.PASS)

    def test_a_test_that_reads_a_dropped_file_fails_and_says_which_line(self):
        verdict, _names, tail = self.prove('reads-drop', 'drop/*.txt')
        self.assertEqual(verdict, covers_prove.FAIL)
        self.assertIn('drop/one.txt', tail)

    def test_a_glob_that_matches_nothing_is_refused_by_name(self):
        verdict, names, _tail = self.prove('reads-keep', 'drop/**', 'typo/**')
        self.assertEqual((verdict, names), (covers_prove.REFUSED, ['typo/**']))

    def test_a_glob_that_names_the_test_itself_is_refused(self):
        self.assertEqual(self.prove('reads-keep', 'scripts/tests/*.sh')[0], covers_prove.REFUSED)

    def test_an_unknown_test_is_refused(self):
        self.assertEqual(self.prove('nothing', 'drop/**')[0], covers_prove.REFUSED)

    def test_the_repository_is_left_as_it_was(self):
        self.prove('reads-keep', 'drop/**')
        self.assertTrue((self.root / 'drop' / 'one.txt').is_file())
        listed = subprocess.run(['git', '-C', str(self.root), 'worktree', 'list'], capture_output=True, text=True).stdout
        self.assertEqual(len(listed.strip().splitlines()), len(['main']))


class Scratch(unittest.TestCase):
    def mode(self, euid):
        path = covers_prove.scratch(euid=lambda: euid)
        self.addCleanup(path.rmdir)
        return path.stat().st_mode & 0o777

    def test_under_uid_0_the_directory_is_readable_by_an_unprivileged_child(self):
        self.assertEqual(self.mode(0), 0o755)

    def test_another_user_keeps_the_private_mode(self):
        self.assertEqual(self.mode(1000), 0o700)


class Main(Repo):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = covers_prove.main(list(argv), root=self.root)
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes_tell_pass_fail_and_refused_apart(self):
        passed = self.run_main('reads-keep', '--without', 'drop/**')
        failed = self.run_main('reads-drop', '--without', 'drop/**')
        refused = self.run_main('reads-keep', '--without', 'typo/**')
        self.assertEqual([passed[0], failed[0], refused[0]], [covers_prove.PASS, covers_prove.FAIL, covers_prove.REFUSED_EXIT])
        self.assertTrue(passed[1].startswith('PASS reads-keep'))
        self.assertTrue(failed[1].startswith('FAIL reads-drop'))
        _code, _out, said = refused
        self.assertIn('REFUSED reads-keep', said)


class ProvedCovers(unittest.TestCase):
    """The covers that covers-prove showed a test never loads stay out of its manifest (D-182, D-213): a pattern
    that comes back makes the test run on files it does not read, the miss the proof removed."""

    DROPPED = {
        'gate-status': ['scripts/gate-local', 'units/engine-gate-report/unit.json'],  # D-182
        'gate-test-cache-env': ['scripts/lib/gate-budget.sh', 'scripts/lib/gate_status.py', 'scripts/lib/gate_gc.py',
                                'scripts/lib/adapters/__init__.py', 'scripts/lib/registry_readers.py'],  # D-182
        'gate-shadow': ['scripts/gate-shadow'],  # D-213
    }

    def test_d182_d213_a_pattern_proved_unneeded_is_not_in_the_manifest(self):
        import json
        from gate_areas import glob_match
        for name, dropped in self.DROPPED.items():
            covers = json.loads((ROOT / 'scripts' / 'tests' / 'covers' / f'{name}.json').read_text())['covers']
            for path in dropped:
                with self.subTest(test=name, path=path):
                    self.assertEqual([pattern for pattern in covers if glob_match(path, pattern)], [])


if __name__ == '__main__':
    unittest.main()
