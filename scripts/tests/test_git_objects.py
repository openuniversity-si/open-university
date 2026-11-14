"""The batched, sha-keyed reader of a commit's files (GATE-SPEED R2, D-092) on a fixture repository: the texts equal
`git show`, a missing path is absent, a second read of the same commit runs one git process (the sha), a ref that moves
is read at its new commit, and a path with spaces or non-ASCII text survives. No network."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import git_objects  # noqa: E402

IDENTITY = ('-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false')


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *IDENTITY, *args], capture_output=True, text=True,
                          check=True).stdout.strip()


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.addCleanup(git_objects.forget)
        git_objects.forget()
        git(self.dir, 'init', '-q')
        (self.dir / 'units' / 'a').mkdir(parents=True)
        (self.dir / 'units' / 'a' / 'unit.json').write_text('{"id": "a"}\n')
        (self.dir / 'units' / 'with space.json').write_text('{"name": "café"}\n')
        git(self.dir, 'add', '.')
        git(self.dir, 'commit', '-q', '-m', 'first')
        self.first = git(self.dir, 'rev-parse', 'HEAD')

    def test_texts_equal_git_show_and_a_missing_path_is_absent(self):
        paths = ['units/a/unit.json', 'units/with space.json', 'units/none.json']
        found = git_objects.files(self.dir, 'HEAD', paths)
        self.assertEqual(sorted(found), paths[:-1])
        for path in paths[:-1]:
            self.assertEqual(found[path], git(self.dir, 'show', f'HEAD:{path}') + '\n')

    def test_a_commit_is_read_once_and_a_moved_ref_is_read_again(self):
        path = 'units/a/unit.json'
        git_objects.files(self.dir, 'HEAD', [path])
        runs = self.enterContext(mock.patch.object(subprocess, 'run', wraps=subprocess.run))
        self.assertEqual(git_objects.files(self.dir, self.first, [path])[path], '{"id": "a"}\n')
        self.assertEqual([[part for part in call.args[0] if part in ('rev-parse', 'cat-file')] for call in runs.call_args_list],
                         [['rev-parse']])  # the sha, and nothing read again
        (self.dir / path).write_text('{"id": "b"}\n')
        git(self.dir, 'commit', '-q', '-am', 'second')
        self.assertEqual(git_objects.files(self.dir, 'HEAD', [path])[path], '{"id": "b"}\n')
        self.assertEqual(git_objects.files(self.dir, self.first, [path])[path], '{"id": "a"}\n')

    def test_an_unknown_commit_is_an_error(self):
        with self.assertRaises(git_objects.GitObjectsError):
            git_objects.files(self.dir, 'no-such-ref', ['units/a/unit.json'])


if __name__ == '__main__':
    unittest.main()
