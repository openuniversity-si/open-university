"""Composition checked against real Git objects, without the train's in-memory Git fixture."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1].parent  # the train/ folder's parent is tests/, whose parent is scripts/
sys.path.insert(0, str(SCRIPTS / 'lib'))
import merge_composition
import train_git
import gate_batch


class CompositionTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.env = dict(os.environ, GIT_AUTHOR_NAME='test', GIT_AUTHOR_EMAIL='test@example.com',
                        GIT_COMMITTER_NAME='test', GIT_COMMITTER_EMAIL='test@example.com',
                        GIT_AUTHOR_DATE='1700000000 +0000', GIT_COMMITTER_DATE='1700000000 +0000')
        self.git('init', '-q')
        (self.root / 'shared').write_text('base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD').stdout.strip()
        self.a = self.member('a', 'shared', 'a\n')
        self.b = self.member('b', 'other', 'b\n')
        self.c = self.member('c', 'shared', 'c\n')

    def git(self, *args, check=True, env=None, input=None):
        return subprocess.run(['git', '-C', str(self.root), *args], check=check, text=True, capture_output=True,
                              input=input, env=dict(self.env, **(env or {})))

    def member(self, name, path, content):
        self.git('checkout', '-q', '-B', name, self.base)
        (self.root / path).write_text(content)
        self.git('add', '.')
        self.git('commit', '-qm', name)
        return self.git('rev-parse', 'HEAD').stdout.strip()

    def test_clean_composition_order_and_deterministic_sha_against_git(self):
        workspace = train_git.GitWorkspace(self.root)
        workspace.git = self.git
        for members in ((self.a, self.b), (self.b, self.a)):
            tip = self.base
            for member in members:
                expected_tree = self.git('merge-tree', '--write-tree', tip, member).stdout.splitlines()[0]
                seconds = max(int(self.git('show', '-s', '--format=%ct', p).stdout) for p in (tip, member))
                dates = dict(workspace.identity, GIT_AUTHOR_DATE=f'{seconds} +0000',
                             GIT_COMMITTER_DATE=f'{seconds} +0000')
                expected = self.git('commit-tree', expected_tree, '-p', tip, '-p', member, '-m', 'merge', env=dates).stdout.strip()
                first, conflicts = workspace.combine(tip, member, 'merge')
                with mock.patch.dict(self.env, GIT_AUTHOR_DATE='1800000000 +0000', GIT_COMMITTER_DATE='1800000000 +0000'):
                    second, _ = workspace.combine(tip, member, 'merge')
                self.assertEqual((first, second, conflicts), (expected, expected, []))
                self.assertEqual(self.git('show', '-s', '--format=%P', first).stdout.strip(), f'{tip} {member}')
                tip = first
            self.assertEqual(self.git('show', f'{tip}:shared').stdout, 'a\n')
            self.assertEqual(self.git('show', f'{tip}:other').stdout, 'b\n')

    def test_named_conflict_matches_git_and_train_stops(self):
        oracle = self.git('merge-tree', '--write-tree', '--name-only', '--no-messages', self.a, self.c, check=False)
        lines, files = merge_composition.merge_tree(self.git, self.a, self.c, train_git.failure)
        self.assertEqual(oracle.returncode, 1)
        self.assertEqual(lines, oracle.stdout.splitlines())
        self.assertEqual(files, ['shared'])
        workspace = train_git.GitWorkspace(self.root)
        workspace.git = self.git
        self.assertEqual(workspace.combine(self.a, self.c, 'conflict'), (None, ['shared']))

    def test_git_failure_is_not_an_empty_conflict(self):
        with self.assertRaises(train_git.GitError):
            merge_composition.merge_tree(self.git, self.base, 'missing-revision', train_git.failure)
        for code, output in ((1, self.base + '\n'), (0, ''), (1 + 1, self.base + '\n')):
            done = subprocess.CompletedProcess([], code, output, 'fatal')
            with self.subTest(code=code, output=output), mock.patch.object(gate_batch, 'git', return_value=done):
                with self.assertRaises(gate_batch.BatchError):
                    gate_batch.merge_union(self.root, self.base, [self.a])
            with self.assertRaises(train_git.GitError):
                merge_composition.merge_tree(lambda *a, **k: done, self.base, self.a, train_git.failure)


if __name__ == '__main__':
    unittest.main()
