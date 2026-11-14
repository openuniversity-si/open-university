"""The merge train's local git workspace (plan v3 M3): plain git plumbing, no checkout, no forge API.

The combined head of a batch is built with `git merge-tree --write-tree` and `git commit-tree`, so the session's
working tree and index are never touched. Heads and the integration tip arrive with `git fetch` from the remote the
registry names (train.git_remote): plain git, the same for GitHub today and Origin later. Merging into the
integration branch is the forge's job and goes through the forge_events port, never through this module.

Tier 2 (Tier2Gate) is the full dev plan on the combined head: the registry's command with the commit appended, no PR
scope (so no impact selection), and a fresh build cache directory for every run, so no tier-1 result is reused. A red
run reports its first failed stage and the test files the output names failing (the quarantine's test ids, M7).
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import config
import engine_role
import gate_bypass
import git_objects
import merge_composition

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = Path('scripts/lib/generate.py')  # the merged tree's own `scripts/generate` (D-069 items 1 and 2)
DRIFT = re.compile(r'^FAIL (\S+): .*scripts/generate (\S+)', re.M)  # generate.drift: the file and the target to rerun
MARKER = re.compile(r'^(<{7}|>{7}) ', re.M)  # a textual conflict git left in a file
Tier2Result = engine_role.GateResult
failing_test_files = engine_role.failing_test_files


OID = re.compile(r'^[0-9a-f]{40}(?:[0-9a-f]{24})?$')  # a full object id (SHA-1 or SHA-256)
# GATE-SPEED F5: an expression made of object ids alone names the same objects forever
_OBJECT = r'[0-9a-f]{40}(?:[0-9a-f]{24})?'
PURE_ARGUMENT = re.compile(rf'^{_OBJECT}(?:\^\{{(?:tree|commit)\}}|:.+|\.{{2,3}}{_OBJECT})?$')
# reads whose answer is a function of the objects they name; the train asks them again and again (one train step
# asked `ls-tree` of the same tip per PR, `merge-base --is-ancestor` per verdict)
PURE_READS = (('rev-parse', '--verify'), ('ls-tree', '-r'), ('diff', '--name-only'), ('merge-base', '--is-ancestor'),
              ('show', '-s'), ('cat-file', '-e'), ('rev-list', '--count'), ('rev-list', '--first-parent'))
DEFINITE_NO = (('merge-base', '--is-ancestor'),)  # exit 1 is an answer ("no"), not a failure


def _starts(args, commands):
    return any(tuple(args[:len(command)]) == command for command in commands)


def _pure(args):
    """True when `git args` reads only what the object ids it names hold (a branch or HEAD can move: never)."""
    if not _starts(args, PURE_READS) and not (args[:1] == ('merge-base',) and len(args) == len(('merge-base', 'a', 'b'))):
        return False
    operands = [arg for arg in args[1:] if not arg.startswith('-')]
    return bool(operands) and all(PURE_ARGUMENT.match(arg) for arg in operands)


class GitError(RuntimeError):
    pass


def failure(command, done):
    """The GitError of a git command that failed, with the tail of its stderr."""
    return GitError(f'git {command} failed: {done.stderr.strip()[-300:]}')


class GitWorkspace:
    """Objects and refs of one local repository (the train's checkout, or a test repository)."""

    def __init__(self, root=None):
        self.root = Path(root or ROOT)
        self.remote = config.get('train.git_remote')
        self.timeout = config.get('train.git_timeout_s')
        name, email = config.get('train.git_author_name'), config.get('train.git_author_email')
        self.identity = {'GIT_AUTHOR_NAME': name, 'GIT_AUTHOR_EMAIL': email,
                         'GIT_COMMITTER_NAME': name, 'GIT_COMMITTER_EMAIL': email}
        self._answers, self._present = {}, set()  # GATE-SPEED F5: answers about objects, commits known to be here

    def git(self, *args, check=True, env=None, input=None):
        key = args if env is None and input is None and _pure(args) else None
        done = self._answers.get(key) if key else None
        if done is None:
            done = subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True, input=input,
                                  timeout=self.timeout, env=dict(os.environ, **(env or {})))
            if key and (done.returncode == 0 or (done.returncode == 1 and _starts(args, DEFINITE_NO))):
                self._answers[key] = done  # GATE-SPEED F5: a question about objects has one answer
        if check and done.returncode != 0:
            raise failure(args[0], done)
        return done

    def fetch(self, *revisions):
        """Make each commit (sha or remote branch) available locally; a sha already here is not fetched again."""
        wanted = [revision for revision in revisions if not (OID.match(revision) and revision in self._present)]
        named = [revision for revision in wanted if OID.match(revision)]
        if named:
            found = self.git('cat-file', '--batch-check=%(objectname)', check=False,
                             input=''.join(f'{oid}^{{commit}}\n' for oid in named))
            self._present.update(line for line in found.stdout.split() if OID.match(line))
            wanted = [revision for revision in wanted if revision not in self._present]
        if wanted:
            self.git('fetch', '--no-tags', '--quiet', self.remote, *wanted)

    def tip(self, branch):
        """The remote branch's current commit, fetched now."""
        self.fetch(f'+refs/heads/{branch}:refs/remotes/{self.remote}/{branch}')
        return self.git('rev-parse', '--verify', f'refs/remotes/{self.remote}/{branch}^{{commit}}').stdout.strip()

    def tree(self, commit):
        return self.git('rev-parse', '--verify', f'{commit}^{{tree}}').stdout.strip()

    def merge_tree(self, onto, head):
        """(merge-tree output lines, conflicted files). A conflict exit that names no file is a git failure, never an
        empty conflict (#805: a conflict is reported only with its files)."""
        return merge_composition.merge_tree(self.git, onto, head, failure)

    def combine(self, onto, head, message):
        """(merge commit of head onto `onto`, []) or (None, conflicted files).

        Dated from its parents (the later committer date), never from a clock, so the same parents and message always
        give the same commit: a later batch that rebuilds content it already judged re-runs it on the same sha, which
        is how the quarantine (M7) sees a test fail and pass on the same sha without an extra run.
        """
        lines, conflicted = self.merge_tree(onto, head)
        if conflicted:
            return None, conflicted
        return self.merge_commit(lines[0], onto, head, message), []

    def merge_commit(self, tree, onto, head, message):
        seconds = max(int(self.git('show', '-s', '--format=%ct', parent).stdout) for parent in (onto, head))
        stamp = f'{seconds} +0000'
        env = dict(self.identity, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
        return merge_composition.merge_commit(self.git, tree, onto, head, message, env=env)

    def combine_regenerated(self, onto, head, message):
        """(merge commit, [], regenerated targets) or (None, conflicted files, []): `combine` whose tree has its
        generated files regenerated (TRAIN-VERDICT-FIX B1). The merged tree is checked out as a throwaway worktree,
        its own `scripts/generate --check` names the drifting files, and only the targets it names run; the merge
        commit is then made from that tree, one commit. A textual conflict only in files the check names (a registry aggregate)
        is resolved by the same regeneration; any other conflict, or a drift the targets do not clear, stays as
        `combine` answers it (the gate's generated drift stage judges what is left)."""
        lines, conflicted = self.merge_tree(onto, head)
        tree, names = self.regenerate(lines[0], conflicted)
        if tree is None:
            return (None, conflicted, []) if conflicted else (self.merge_commit(lines[0], onto, head, message), [], [])
        return self.merge_commit(tree, onto, head, message), [], names

    def regenerate(self, tree, conflicted):
        """(regenerated tree, target names), (tree, []) when nothing drifts, or (None, []) when the generators cannot
        clear it: a conflict outside generated files, a generator that fails, or a drift left after them."""
        scratch = self.git('commit-tree', tree, '-m', 'train: the merged tree to regenerate', env=self.identity)
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder) / 'tree'
            self.git('worktree', 'add', '--detach', '--quiet', str(work), scratch.stdout.strip())
            try:
                return self.regenerate_in(work, tree, conflicted)
            finally:
                self.git('worktree', 'remove', '--force', str(work), check=False)

    def regenerate_in(self, work, tree, conflicted):
        if not (work / GENERATOR).is_file():
            return None, []
        code, output = self.generate(work, '--check')
        drifting = dict(DRIFT.findall(output)) if code == 1 else {}
        if code not in (0, 1) or (code == 1 and not drifting) or not set(conflicted) <= set(drifting):
            return None, []
        if not drifting:
            return tree, []
        names = list(dict.fromkeys(drifting.values()))
        if any(self.generate(work, name)[0] for name in names) or self.generate(work, '--check')[0] \
                or any(MARKER.search((work / path).read_text(errors='replace')) for path in conflicted
                       if (work / path).is_file()):
            return None, []
        self.git('-C', str(work), 'add', '--all')
        return self.git('-C', str(work), 'write-tree').stdout.strip(), names

    def generate(self, work, *args):
        """(exit code, output) of the worktree's own generator, pinned to the file store like the merge driver."""
        env = dict(os.environ, OU_CONFIG_STORE='file')
        done = subprocess.run([os.environ.get('OU_PYTHON') or sys.executable, str(work / GENERATOR), *args, '--root',
                               str(work)], cwd=work, capture_output=True, text=True, timeout=self.timeout, env=env)
        return done.returncode, done.stdout + done.stderr

    def paths(self, commit):
        """Every file path of the commit's tree (GATE-SPEED F11, N8: the train asks its port, never git directly)."""
        return self.git('ls-tree', '-r', '--name-only', commit).stdout.split()

    def has_path(self, commit, path):
        return self.git('cat-file', '-e', f'{commit}:{path}', check=False).returncode == 0

    def files(self, commit, paths):
        """{path: text} of the paths that exist in the commit (git_objects: one batched read per commit, remembered)."""
        return git_objects.files(self.root, commit, paths, timeout=self.timeout)

    def count(self, base, tip, first_parent=False):
        """How many commits tip has that base does not (first-parent only when asked)."""
        return int(self.git('rev-list', *(['--first-parent'] if first_parent else []), '--count',
                            f'{base}..{tip}').stdout)

    def is_ancestor(self, ancestor, commit):
        return self.git('merge-base', '--is-ancestor', ancestor, commit, check=False).returncode == 0

    def changed_files(self, base, head):
        """Files the head changes against its merge base with `base` (what the PR itself touches)."""
        return sorted(self.git('diff', '--name-only', f'{base}...{head}').stdout.split())

    def push(self, commit, branch, verify=True):
        """Push `commit` to the remote branch, never forced: a branch `commit` does not contain refuses (GitError).
        verify=False skips the pre-push hook, as deliver's base merge does (F33): the push carries the base, already
        gated, onto a branch already checked at its own pushes, and the gate judges the result next."""
        self.git('push', '--quiet', *(() if verify else ('--no-verify',)), self.remote, f'{commit}:refs/heads/{branch}')

    def keep(self, ref, commit):
        self.git('update-ref', ref, commit)


class Tier2Gate(engine_role.CommandGate):
    """Runs tier 2 on one commit and reports (ok, first failed stage, output tail, failing test files)."""

    def __init__(self, root=None):
        super().__init__(root or ROOT, config.get('train.tier2_command'), config.get('train.tier2_timeout_s'),
                         config.get('train.tier2_log_chars'), 'tier 2', 'train.tier2_timeout_s',
                         config.get('train.tier2_test_cache'))

    def run(self, commit, env=None):
        """The train's tier 2 runs the real command, bypass or not: a bypassed verdict is never a head the train merges (D-259)."""
        return super().run(commit, env)
