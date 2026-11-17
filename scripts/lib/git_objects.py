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


def changed_paths(root, base, head):
    if not base or not head:
        raise RuntimeError('Missing diff identity; full battery required')
    return subprocess.check_output(['git', '-C', str(root), 'diff', '--no-renames', '--name-only', '-z',
                                    base + '...' + head], stderr=subprocess.DEVNULL).decode().strip('\0').split('\0')
