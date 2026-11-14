"""GATE-SPEED F11 (N6): memory_git answers the train fixture's git as git does.

One script of commands runs twice, on real repositories and on a MemoryGit; every answer (exit code, output) must be
the same once object ids are named by their order of first appearance (the two stores hash differently)."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
import memory_git  # noqa: E402

STAMP = f'{memory_git.EPOCH} +0000'
ENV = {'GIT_AUTHOR_NAME': 'fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid', 'GIT_COMMITTER_NAME': 'fixture',
       'GIT_COMMITTER_EMAIL': 'fixture@example.invalid', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
       'GIT_AUTHOR_DATE': STAMP, 'GIT_COMMITTER_DATE': STAMP}
OBJECT = re.compile(r'\b[0-9a-f]{40}\b')


class Transcript:
    """Runs git commands in a folder and keeps (command, exit code, normalized output)."""

    def __init__(self, folder):
        self.folder, self.lines, self.names = Path(folder), [], {}

    def git(self, where, *args, stdin=None):
        done = subprocess.run(['git', '-C', str(self.folder / where), *args], capture_output=True, text=True,
                              input=stdin, env=dict(os.environ, **ENV))
        out = OBJECT.sub(lambda found: self.names.setdefault(found.group(), f'<{len(self.names)}>'), done.stdout)
        self.lines.append((args[0], done.returncode != 0, out))
        return done.stdout.strip()

    def write(self, where, files):
        for name, text in files.items():
            target = self.folder / where / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)


def scenario(run):
    """The commands the train's fixture, its forge and its workspace give git."""
    run.git('.', 'init', '--quiet', '--bare', 'origin.git')
    run.git('origin.git', 'symbolic-ref', 'HEAD', 'refs/heads/main')
    run.git('.', 'init', '--quiet', '-b', 'seed', 'seed')
    run.write('seed', {'README': 'one\ntwo\nthree\nfour\nfive\n', 'dir/a.txt': 'a\n'})
    run.git('seed', 'add', '-A')
    run.git('seed', 'commit', '--quiet', '-m', 'base')
    base = run.git('seed', 'rev-parse', 'HEAD')
    run.git('seed', 'push', '--quiet', '../origin.git', f'{base}:refs/heads/main')
    heads = {}
    for name, files in (('left', {'README': 'ONE\ntwo\nthree\nfour\nfive\n', 'left.txt': 'l\n'}),
                        ('right', {'README': 'one\ntwo\nthree\nfour\nFIVE\n'}),
                        ('clash', {'README': 'uno\ntwo\nthree\nfour\nfive\n'})):
        run.git('seed', 'checkout', '--quiet', '-B', name, base)
        run.write('seed', files)
        run.git('seed', 'commit', '--quiet', '-am', name)
        heads[name] = run.git('seed', 'rev-parse', 'HEAD')
        run.git('seed', 'push', '--quiet', '../origin.git', f'{heads[name]}:refs/heads/{name}')
    run.git('.', 'clone', '--quiet', 'origin.git', 'work')
    for ref in ('left', 'right', 'clash'):
        run.git('work', 'fetch', '--quiet', 'origin', f'+refs/heads/{ref}:refs/remotes/origin/{ref}')
    run.git('work', 'rev-parse', '--verify', 'refs/remotes/origin/main^{commit}')
    run.git('work', 'rev-parse', '--verify', f'{base}^{{tree}}')
    clean = run.git('work', 'merge-tree', '--write-tree', '--name-only', '--no-messages', heads['left'], heads['right'])
    run.git('work', 'merge-tree', '--write-tree', '--name-only', '--no-messages', heads['left'], heads['clash'])
    merged = run.git('work', 'commit-tree', clean.splitlines()[0], '-p', heads['left'], '-p', heads['right'], '-m', 'm')
    piped = run.git('work', 'commit-tree', clean.splitlines()[0], '-p', heads['left'], stdin='message on stdin')  # no -m, no -F
    run.git('work', 'show', '-s', '--format=%B', piped)
    run.git('work', 'show', f'{merged}:README')
    run.git('work', 'show', '-s', '--format=%ct', merged)
    run.git('work', 'show', '-s', '--format=%B', merged)
    run.git('work', 'ls-tree', '-r', '--name-only', merged)
    run.git('work', 'diff', '--name-only', f'{heads["right"]}...{merged}')
    run.git('work', 'diff', '--no-renames', '--name-only', '-z', f'{base}...{heads["left"]}')
    run.git('work', 'rev-list', '--count', f'{base}..{merged}')
    run.git('work', 'rev-list', '--first-parent', '--count', f'{base}..{merged}')
    run.git('work', 'rev-list', '--reverse', f'{base}..{merged}')
    run.git('work', 'merge-base', heads['left'], heads['right'])
    run.git('work', 'merge-base', '--is-ancestor', base, merged)
    run.git('work', 'merge-base', '--is-ancestor', merged, base)
    run.git('work', 'cat-file', '-e', f'{merged}:left.txt')
    run.git('work', 'cat-file', '-e', f'{merged}:absent.txt')
    run.git('work', 'cat-file', '--batch', stdin=f'{merged}:README\n{merged}:absent\n')
    run.git('work', 'cat-file', '--batch-check=%(objectname)', stdin=f'{merged}^{{commit}}\n')
    run.git('work', 'update-ref', 'refs/keep/one', merged)
    run.git('work', 'rev-parse', 'refs/keep/one')
    run.git('work', 'push', '--quiet', 'origin', f'{merged}:refs/heads/main')
    run.git('work', 'push', '--quiet', 'origin', f'{heads["clash"]}:refs/heads/main')
    run.git('origin.git', 'rev-parse', 'refs/heads/main')
    blob = run.git('work', 'hash-object', '-w', '--stdin', stdin='record\n')
    tree = run.git('work', 'mktree', stdin=f'100644 blob {blob}\trecord.json\n')
    run.git('work', 'ls-tree', '-r', '--name-only', tree)
    run.git('work', 'status', '--porcelain', '--untracked-files=all')
    run.write('work', {'new.txt': 'n\n', 'README': 'changed\n'})
    run.git('work', 'status', '--porcelain', '--untracked-files=all')


class SameAnswers(unittest.TestCase):
    def test_memory_git_answers_the_scenario_as_git_does(self):
        transcripts = []
        for memory in (False, True):
            with tempfile.TemporaryDirectory() as folder:
                run = Transcript(folder)
                if memory:
                    with memory_git.MemoryGit().intercept():
                        scenario(run)
                else:
                    scenario(run)
                transcripts.append(run.lines)
        real, emulated = transcripts
        self.assertEqual(len(real), len(emulated))
        for want, got in zip(real, emulated):
            self.assertEqual(want, got)

    def test_a_same_size_rewrite_in_one_coarse_tick_is_committed(self):
        # The runner's disk (04/11): a rewrite of the same size in one tick of a coarse clock keeps the file's whole
        # stat; a read kept by its stat committed the old bytes, and train-role's ownership tests refused nothing
        with tempfile.TemporaryDirectory() as folder, memory_git.MemoryGit().intercept():
            run = Transcript(folder)
            run.git('.', 'init', '--quiet', 'work')
            run.write('work', {'a.txt': 'a\n'})
            run.git('work', 'add', '-A')
            run.git('work', 'commit', '--quiet', '-m', 'first')
            path = Path(folder) / 'work' / 'a.txt'
            stat = path.stat()
            run.write('work', {'a.txt': 'b\n'})
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # the same size, inode and stamp
            self.assertEqual(path.stat().st_ino, stat.st_ino)
            run.git('work', 'add', '-A')
            run.git('work', 'commit', '--quiet', '-m', 'second')
            self.assertEqual(run.git('work', 'show', 'HEAD:a.txt'), 'b')

    def test_an_unknown_command_is_refused_never_half_answered(self):
        with tempfile.TemporaryDirectory() as folder, memory_git.MemoryGit().intercept():
            subprocess.run(['git', '-C', folder, 'init', '--quiet', 'repo'], check=True)
            with self.assertRaises(memory_git.UnknownCommand):
                subprocess.run(['git', '-C', str(Path(folder) / 'repo'), 'gc'])

    def test_a_repository_it_does_not_hold_runs_real_git(self):
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run(['git', 'init', '--quiet', folder], check=True, env=dict(os.environ, **ENV))
            with memory_git.MemoryGit().intercept():
                done = subprocess.run(['git', '-C', folder, 'rev-parse', '--git-dir'], capture_output=True, text=True)
            self.assertEqual(done.stdout.strip(), '.git')


if __name__ == '__main__':
    unittest.main()
