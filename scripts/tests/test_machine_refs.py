"""Machine-internal ref pushes (GATE-SPEED, D-091) on fixture repositories: record commits pushed to train/lock,
train/wake or service/control skip the pre-push checks; a code branch, a record ref carrying code, a delete or a mixed
push runs them. The hook itself runs from a fixture checkout whose commit_check and prepush are stand-ins that leave a
mark, so the test sees which path the hook took without running the real checks. No network."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import machine_refs  # noqa: E402

IDENTITY = ('-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false')
ZERO = '0' * len(hashlib.sha1().hexdigest())  # git's name of a ref that does not exist
LOCK, WAKE = (f'refs/heads/{config.get(key)}' for key in ('train.lock_ref', 'train.wake_ref'))
MARK = 'import sys\nfrom pathlib import Path\nPath(sys.argv[0]).with_suffix(".ran").write_text(sys.stdin.read() if "--stdin-refs" in sys.argv else "")\n'


def git(cwd, *args, stdin=None):
    done = subprocess.run(['git', '-C', str(cwd), *IDENTITY, *args], capture_output=True, text=True, input=stdin)
    if done.returncode:
        raise AssertionError(f'git {" ".join(args)}: {done.stderr}')
    return done.stdout.strip()


def record(cwd, data, parent=None):
    blob = git(cwd, 'hash-object', '-w', '--stdin', stdin=json.dumps(data))
    tree = git(cwd, 'mktree', stdin=f'100644 blob {blob}\t{machine_refs.RECORD_FILE}\n')
    return git(cwd, 'commit-tree', tree, *(['-p', parent] if parent else []), '-m', json.dumps(data))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        git(self.dir, 'init', '-q')
        (self.dir / 'app.py').write_text('print()\n')
        git(self.dir, 'add', 'app.py')
        git(self.dir, 'commit', '-q', '-m', 'code')
        self.code = git(self.dir, 'rev-parse', 'HEAD')

    def lines(self, *pushes):
        return [f'{local} {sha} {remote} {old}' for local, sha, remote, old in pushes]


class MachineOnly(Fixture):
    def test_a_new_lock_record_is_machine(self):
        sha = record(self.dir, {'owner': 'train'})
        self.assertTrue(machine_refs.machine_only(self.lines((sha, sha, LOCK, ZERO)), self.dir))

    def test_an_advance_of_the_wake_log_is_machine(self):
        first = record(self.dir, {'pr': 'a'})
        second = record(self.dir, {'pr': 'b'}, first)
        self.assertTrue(machine_refs.machine_only(self.lines((second, second, WAKE, first)), self.dir))

    def test_a_code_branch_is_checked(self):
        lines = self.lines(('refs/heads/work', self.code, 'refs/heads/work', ZERO))
        self.assertFalse(machine_refs.machine_only(lines, self.dir))

    def test_code_pushed_to_a_lock_ref_is_checked(self):
        self.assertFalse(machine_refs.machine_only(self.lines((self.code, self.code, LOCK, ZERO)), self.dir))

    def test_a_record_on_top_of_code_is_checked(self):
        sha = record(self.dir, {'owner': 'train'}, self.code)
        self.assertFalse(machine_refs.machine_only(self.lines((sha, sha, LOCK, ZERO)), self.dir))

    def test_a_mixed_push_is_checked(self):
        sha = record(self.dir, {'owner': 'train'})
        lines = self.lines((sha, sha, LOCK, ZERO), ('refs/heads/work', self.code, 'refs/heads/work', ZERO))
        self.assertFalse(machine_refs.machine_only(lines, self.dir))

    def test_a_delete_and_no_line_are_checked(self):
        sha = record(self.dir, {'owner': 'train'})
        self.assertFalse(machine_refs.machine_only(self.lines(('(delete)', ZERO, LOCK, sha)), self.dir))
        self.assertFalse(machine_refs.machine_only([], self.dir))


class Hook(Fixture):
    """.githooks/pre-push from a checkout whose two checks are stand-ins that mark that they ran."""

    def setUp(self):
        super().setUp()
        lib = self.dir / 'scripts' / 'lib'
        (self.dir / '.githooks').mkdir()
        lib.mkdir(parents=True)
        shutil.copy(ROOT / '.githooks' / 'pre-push', self.dir / '.githooks' / 'pre-push')
        os.symlink(ROOT / 'scripts' / 'lib' / 'machine_refs.py', lib / 'machine_refs.py')
        for name in ('commit_check.py', 'prepush.py'):
            (lib / name).write_text(MARK)

    def hook(self, *pushes):
        done = subprocess.run(['sh', str(self.dir / '.githooks' / 'pre-push'), 'origin', 'url'], cwd=self.dir,
                              input=''.join(line + '\n' for line in self.lines(*pushes)), capture_output=True, text=True)
        lib = self.dir / 'scripts' / 'lib'
        return done.returncode, {name for name in ('commit_check', 'prepush') if (lib / f'{name}.ran').exists()}, lib

    def test_a_lock_record_push_runs_no_check(self):
        sha = record(self.dir, {'owner': 'train'})
        self.assertEqual(self.hook((sha, sha, LOCK, ZERO))[:-1], (0, set()))

    def test_a_code_branch_runs_both_checks_with_git_lines(self):
        line = ('refs/heads/work', self.code, 'refs/heads/work', ZERO)
        code, ran, lib = self.hook(line)
        self.assertEqual((code, ran), (0, {'commit_check', 'prepush'}))
        self.assertEqual((lib / 'commit_check.ran').read_text().split(), list(line))


if __name__ == '__main__':
    unittest.main()
