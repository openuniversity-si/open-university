"""GATE-SPEED F5: the train's workspace asks git about an object once (TX24: one file per feature)."""
import hashlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, setUpModule  # noqa: E402,F401
import train_git  # noqa: E402

A, B = hashlib.sha1(b'a').hexdigest(), hashlib.sha1(b'b').hexdigest()  # two object ids, of no object


class PureReads(unittest.TestCase):
    def test_only_reads_of_object_ids_are_remembered(self):
        pure = [('rev-parse', '--verify', f'{A}^{{tree}}'), ('ls-tree', '-r', '--name-only', A),
                ('diff', '--name-only', f'{A}...{B}'), ('merge-base', A, B), ('merge-base', '--is-ancestor', A, B),
                ('show', '-s', '--format=%ct', A), ('cat-file', '-e', f'{A}:units/x/unit.json'),
                ('rev-list', '--count', f'{A}..{B}'), ('rev-list', '--first-parent', '--count', f'{A}..{B}')]
        moving = [('rev-parse', '--verify', 'refs/remotes/origin/main^{commit}'), ('ls-tree', '-r', '--name-only', 'HEAD'),
                  ('diff', '--name-only', f'{A}...main'), ('merge-base', A), ('fetch', '--quiet', 'origin', A),
                  ('push', '--quiet', 'origin', f'{A}:refs/heads/main'), ('commit-tree', A, '-m', 'x'),
                  ('rev-parse', '--verify', A[:-1])]
        self.assertEqual([train_git._pure(args) for args in pure], [True] * len(pure))
        self.assertEqual([train_git._pure(args) for args in moving], [False] * len(moving))


class Answers(Fixture):
    memory = False  # the subject is the workspace's own git: real repositories
    def calls(self):
        real = subprocess.run
        made = []

        def counting(command, *args, **kwargs):
            made.append(tuple(command[len(['git', '-C', 'root']):]))
            return real(command, *args, **kwargs)
        patch = mock.patch.object(train_git.subprocess, 'run', side_effect=counting)
        patch.start()
        self.addCleanup(patch.stop)
        return made

    def setUp(self):
        """A checkout of its own, cloned before any PR exists (the fixture's shares the origin's objects): here fetch is
        the subject, so a PR head is not in it until fetched."""
        super().setUp()
        self.own = self.dir / 'own'
        self.run_git(self.dir, 'clone', '--quiet', '--no-local', str(self.origin), str(self.own))

    def fresh(self):
        workspace = train_git.GitWorkspace(self.own)
        workspace.fetch(f'+refs/heads/{self.base_branch}:refs/remotes/{workspace.remote}/{self.base_branch}')
        return workspace

    def test_a_question_about_objects_runs_git_once(self):
        [made] = self.make({"c.txt": "one\n"})
        entry = made.head
        workspace = self.fresh()
        workspace.fetch(entry)
        made = self.calls()
        first = workspace.tree(entry)
        self.assertEqual(workspace.tree(entry), first)
        self.assertEqual(workspace.changed_files(self.base, entry), workspace.changed_files(self.base, entry))
        self.assertEqual(len(made), len(['rev-parse', 'diff']))

    def test_a_definite_no_is_remembered_and_a_missing_object_is_not(self):
        [made] = self.make({"c.txt": "one\n"})
        entry = made.head
        workspace = self.fresh()
        workspace.fetch(entry)
        made = self.calls()
        for _ in range(len('twice')):
            self.assertEqual(workspace.git('merge-base', '--is-ancestor', entry, self.base, check=False).returncode, 1)
            self.assertNotEqual(workspace.git('cat-file', '-e', f'{entry}:absent.txt', check=False).returncode, 0)
        self.assertEqual(made.count(('merge-base', '--is-ancestor', entry, self.base)), 1)
        self.assertEqual(made.count(('cat-file', '-e', f'{entry}:absent.txt')), len('twice'))

    def test_a_commit_already_here_is_not_fetched_again(self):
        [made] = self.make({"c.txt": "one\n"})
        entry = made.head
        workspace = self.fresh()
        workspace.fetch(entry)
        made = self.calls()
        workspace.fetch(entry)
        workspace.fetch(entry)
        self.assertEqual([call[0] for call in made], ['cat-file'])  # one look, no fetch, then remembered
        workspace.fetch(f'+refs/heads/{self.base_branch}:refs/remotes/{workspace.remote}/{self.base_branch}')
        self.assertEqual(made[-1][0], 'fetch')  # a ref can move: always fetched

    def test_a_commit_not_here_is_fetched(self):
        [made] = self.make({"c.txt": "one\n"})
        entry = made.head
        workspace = self.fresh()
        made = self.calls()
        workspace.fetch(entry)
        self.assertEqual([call[0] for call in made], ['cat-file', 'fetch'])
        self.assertEqual(workspace.tree(entry), self.run_git(self.seed, 'rev-parse', f'{entry}^{{tree}}'))


if __name__ == '__main__':
    unittest.main()
