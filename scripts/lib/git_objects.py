"""Files of a commit, read in one git process and remembered by the commit's sha (GATE-SPEED R2, D-092).

A commit never changes, so what it holds can be read once: `files(root, commit, paths)` resolves the commit to its sha,
asks `git cat-file --batch` for every path not yet held in one process, and keeps the answers per (repository, sha,
path). A ref is resolved on every call and is never a key: only the sha is. Reading 110 unit manifests went from 110
`git show` processes per call (and 54 calls in one train test) to one process per commit.

  files(root, commit, paths, timeout=None)   {path: text} of the paths that exist at the commit (a missing one is absent)
  forget()                                   drop everything held (tests)
  changed_paths(root, base, head)            the paths of the diff base...head, renames on both sides (D-322: the
                                             gate's diff, here so a layer-0 tool reads it without importing the gate;
                                             gate_policy re-exports it)
  Tree(root, timeout=None)                   read-only questions about one repository's commits (paths, has_path,
                                             files, changed_files): the reads train_git.GitWorkspace inherits, here so
                                             the gate's lane rule (pr_ready, train_ownership) reads a commit without
                                             the train's workspace (D-322)
"""
from pathlib import Path
import subprocess

_HELD = {}


class GitObjectsError(RuntimeError):
    pass


def _git(root, *args, data=None, timeout=None):
    done = subprocess.run(['git', '-C', str(root), *args], input=data, capture_output=True, timeout=timeout)
    if done.returncode:
        raise GitObjectsError(f'git {args[0]}: {done.stderr.decode(errors="replace").strip()}')
    return done.stdout


def files(root, commit, paths, timeout=None):
    """{path: text} for each path that exists in the commit's tree; one `cat-file --batch` for the paths not held."""
    repo = str(Path(root).resolve())
    sha = _git(root, 'rev-parse', '--verify', f'{commit}^{{commit}}', timeout=timeout).decode().strip()
    wanted = list(dict.fromkeys(paths))
    missing = [path for path in wanted if (repo, sha, path) not in _HELD]
    if missing:
        answer = _git(root, 'cat-file', '--batch', data=''.join(f'{sha}:{path}\n' for path in missing).encode(),
                      timeout=timeout)
        for path, body in zip(missing, _objects(answer, len(missing))):
            _HELD[(repo, sha, path)] = body
    return {path: _HELD[(repo, sha, path)] for path in wanted if _HELD[(repo, sha, path)] is not None}


def _objects(answer, count):
    """The bodies of a `cat-file --batch` answer in request order, as text; None for a `missing` object."""
    at, found = 0, []
    for _ in range(count):
        end = answer.index(b'\n', at)
        header = answer[at:end].split()
        at = end + 1
        if header[-1] == b'missing':
            found.append(None)
            continue
        size = int(header[-1])
        found.append(answer[at:at + size].decode())
        at += size + 1  # the body and the newline after it
    return found


def forget():
    _HELD.clear()


class Tree:
    """Read-only questions about the commits of one local repository; train_git.GitWorkspace adds the train's writes
    and its remembered answers to these same reads."""

    def __init__(self, root, timeout=None):
        self.root, self.timeout = Path(root), timeout

    def git(self, *args, check=True):
        done = subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True, timeout=self.timeout)
        if check and done.returncode != 0:
            raise GitObjectsError(f'git {args[0]} failed: {done.stderr.strip()}')
        return done

    def paths(self, commit):
        """Every file path of the commit's tree (GATE-SPEED F11, N8: the train asks its port, never git directly)."""
        return self.git('ls-tree', '-r', '--name-only', commit).stdout.split()

    def has_path(self, commit, path):
        return self.git('cat-file', '-e', f'{commit}:{path}', check=False).returncode == 0

    def files(self, commit, paths):
        """{path: text} of the paths that exist in the commit (one batched read per commit, remembered)."""
        return files(self.root, commit, paths, timeout=self.timeout)

    def changed_files(self, base, head):
        """Files the head changes against its merge base with `base` (what the PR itself touches)."""
        return sorted(self.git('diff', '--name-only', f'{base}...{head}').stdout.split())


def changed_paths(root, base, head):
    if not base or not head:
        raise RuntimeError('Missing diff identity; full battery required')
    return subprocess.check_output(['git', '-C', str(root), 'diff', '--no-renames', '--name-only', '-z',
                                    base + '...' + head], stderr=subprocess.DEVNULL).decode().strip('\0').split('\0')
