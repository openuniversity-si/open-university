"""A branch starts from the base in one command (F2, D-211): a clean tree and a fresh name start the branch at the base; a dirty
tree and a name already on the remote are refused, and nothing is created. A bare remote in a temporary directory; no network.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import branch_start  # noqa: E402

IDENTITY = {'GIT_AUTHOR_NAME': 'T', 'GIT_AUTHOR_EMAIL': 't@example.test', 'GIT_COMMITTER_NAME': 'T', 'GIT_COMMITTER_EMAIL': 't@example.test'}


def run(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, check=True,
                          env={**os.environ, **IDENTITY})


class Start(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name)
        self.remote = base / 'remote.git'
        seed = base / 'seed'
        seed.mkdir()
        run(seed, 'init', '-q', '-b', branch_start.BASE_BRANCH)
        (seed / 'a.txt').write_text('one\n')
        run(seed, 'add', '-A')
        run(seed, 'commit', '-q', '-m', 'base')
        subprocess.run(['git', 'init', '-q', '--bare', str(self.remote)], check=True)
        run(seed, 'push', '-q', str(self.remote), branch_start.BASE_BRANCH)
        self.work = base / 'work'
        subprocess.run(['git', 'clone', '-q', str(self.remote), str(self.work)], check=True, capture_output=True)
        run(self.work, 'checkout', '-q', '-B', 'local-only', 'origin/' + branch_start.BASE_BRANCH)
        self.patch = mock.patch.object(branch_start, 'BASE', 'origin/' + branch_start.BASE_BRANCH)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_a_clean_tree_and_a_fresh_name_start_the_branch_at_the_base(self):
        ok, message = branch_start.start(self.work, 'topic-one')
        self.assertTrue(ok, message)
        self.assertEqual(run(self.work, 'rev-parse', 'HEAD').stdout, run(self.work, 'rev-parse', 'origin/' + branch_start.BASE_BRANCH).stdout)
        self.assertEqual(run(self.work, 'branch', '--show-current').stdout.strip(), 'topic-one')

    def test_a_dirty_tree_is_refused_and_nothing_is_created(self):
        (self.work / 'a.txt').write_text('changed\n')
        ok, message = branch_start.start(self.work, 'topic-two')
        self.assertFalse(ok)
        self.assertIn('changes', message)
        self.assertEqual(run(self.work, 'branch', '--show-current').stdout.strip(), 'local-only')

    def test_a_name_already_on_the_remote_is_refused(self):
        run(self.work, 'push', '-q', 'origin', 'HEAD:refs/heads/taken-name')
        ok, message = branch_start.start(self.work, 'taken-name')
        self.assertFalse(ok)
        self.assertIn('already on the remote', message)


if __name__ == '__main__':
    unittest.main()
