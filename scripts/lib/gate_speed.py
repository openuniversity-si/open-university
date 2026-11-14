#!/usr/bin/env python3
"""Cache keys and the incremental secret scan for the delivery gate.

Keys live here so the shell stages do not invent their own. A key changes when
the tool, its config, or (for tsc) the checkout path changes. The same key
reuses a directory outside the worktree, which is thrown away after every PR.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import config

ROOT = Path(__file__).resolve().parents[2]


def _digest(parts):
    digest = hashlib.sha256()
    for part in parts:
        data = part if isinstance(part, bytes) else str(part).encode()
        digest.update(data)
        digest.update(b'\0')
    return digest.hexdigest()[:20]


def _read(path):
    file = Path(path)
    return file.read_bytes() if file.is_file() else b''


def _package_versions(web, names):
    package = json.loads(_read(Path(web) / 'package.json') or b'{}')
    deps = {}
    deps.update(package.get('dependencies') or {})
    deps.update(package.get('devDependencies') or {})
    return [str(deps.get(name, '')) for name in names]


def _node_version():
    try:
        completed = subprocess.run(['node', '-v'], capture_output=True, text=True,
                                   timeout=config.get('gate.tool_probe_timeout_s'), check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    text = (completed.stdout or completed.stderr or '').strip()
    return text.splitlines()[0] if completed.returncode == 0 and text else 'unknown'


def lint_dir(web, cache, node_version=None):
    """Directory for the eslint and stylelint content caches.

    Both caches key every entry by absolute path, and the typed eslint config hashes
    tsconfigRootDir (an absolute path) into every entry. One cache file shared by
    several checkouts was rewritten by each and hit by none (D-064 (f): 70 s lint
    on every new worktree). The checkout path is part of the key; the gate keeps
    that path fixed per slot, so the caches stay warm across worktrees.
    """
    web = Path(web)
    versions = _package_versions(web, ('eslint', 'stylelint'))
    key = _digest([
        node_version or _node_version(), *versions,
        _read(web / 'eslint.config.mjs'), _read(web / 'stylelint.config.mjs'),
    ])
    directory = Path(cache) / 'lint' / key / _digest([str(web.resolve())])
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def typecheck_info(web, cache, node_version=None):
    """tsBuildInfoFile outside the worktree. The path is part of the key.

    tsc records absolute paths. A info file from another checkout is not a hit.
    """
    web = Path(web)
    versions = _package_versions(web, ('typescript',))
    key = _digest([
        node_version or _node_version(), *versions, str(web.resolve()),
        _read(web / 'tsconfig.json'),
    ])
    directory = Path(cache) / 'typecheck'
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f'{key}.tsbuildinfo'


def _git(root, args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, timeout=config.get('gate.git_timeout_s'), check=False)


def _gitleaks_version():
    try:
        completed = subprocess.run(['gitleaks', 'version'], capture_output=True, text=True,
                                       timeout=config.get('gate.tool_probe_timeout_s'), check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 'unknown'
    text = (completed.stdout or completed.stderr or '').strip()
    return text.splitlines()[0] if completed.returncode == 0 and text else 'unknown'


GITLEAKS_CONFIG = '.gitleaks.toml'


def _config_hash(root):
    return hashlib.sha256(_read(Path(root) / GITLEAKS_CONFIG)).hexdigest()


def _state_path(cache):
    return Path(cache) / 'secret-scan' / 'state.json'


def _load_state(cache):
    path = _state_path(cache)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _head(root):
    completed = _git(root, ['rev-parse', 'HEAD'])
    if completed.returncode != 0:
        raise RuntimeError('secret scan could not read HEAD')
    return completed.stdout.strip()


def secret_plan(root, cache, base='', scope='full'):
    """log-opts for gitleaks, or 'skip' when this commit was already scanned.

    A stored base is reused only when it is an ancestor and the gitleaks
    version and config hash still match. Else, with scope `change` and the
    PR's base (GATE-SPEED R1, D-092), the PR's own commits: merge-base..HEAD,
    unless the PR changes the gitleaks config. Anything else scans all of HEAD.
    """
    head = _head(root)
    state = _load_state(cache)
    version = _gitleaks_version()
    config = _config_hash(root)
    previous = state.get('sha') if isinstance(state.get('sha'), str) else ''
    same_tool = state.get('gitleaks') == version and state.get('config') == config
    if same_tool and previous and _ancestor(root, previous, head):
        if previous == head:
            return 'skip'
        return f'{previous}..{head}'
    fork = change_base(root, base, scope)
    if fork:
        return 'skip' if fork == head else f'{fork}..{head}'
    return 'HEAD'


def change_base(root, base, scope):
    """The merge-base of HEAD with the PR's base when a scan may judge only the change; '' when it must be full: scope
    `full`, no base, no merge-base, or a diff that touches the gitleaks config (a config change re-judges everything)."""
    if scope != 'change' or not base:
        return ''
    found = _git(root, ['merge-base', base, 'HEAD'])
    fork = found.stdout.strip() if found.returncode == 0 else ''
    if not fork:
        return ''
    changed = _git(root, ['diff', '--name-only', fork, 'HEAD', '--', GITLEAKS_CONFIG])
    return '' if changed.returncode != 0 or changed.stdout.strip() else fork


def changed_files(root, base, scope):
    """GATE-SPEED R1: the files a change-scoped tree scan reads, NUL-separated on stdout by main(): what the PR changes
    against its merge-base (deletions aside), what the working tree changes and what is untracked; None when the scan
    must read the whole tree (change_base is '')."""
    fork = change_base(root, base, scope)
    if not fork:
        return None
    names = set()
    for args in (['diff', '--name-only', '--diff-filter=d', '-z', fork, 'HEAD'], ['diff', '--name-only', '--diff-filter=d', '-z'],
                 ['ls-files', '--others', '--exclude-standard', '-z']):
        listed = _git(root, args)
        if listed.returncode != 0:
            return None
        names.update(name for name in listed.stdout.split('\0') if name)
    return sorted(names)


def _ancestor(root, older, newer):
    if older == newer:
        return True
    completed = _git(root, ['merge-base', '--is-ancestor', older, newer])
    return completed.returncode == 0


def secret_record(root, cache):
    """Remember a successful scan. A failed scan must not call this."""
    path = _state_path(cache)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'sha': _head(root), 'gitleaks': _gitleaks_version(), 'config': _config_hash(root)}
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(payload) + '\n')
    os.replace(temporary, path)


def copy_if_absent(source, dest):
    """Copy files that are not already at dest. Do not use cp -n (non-portable)."""
    source, dest = Path(source), Path(dest)
    if not source.is_dir():
        return 0
    copied = 0
    for path in sorted(source.rglob('*')):
        if path.is_dir() and not path.is_symlink():
            continue
        target = dest / path.relative_to(source)
        if target.exists() or target.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            target.symlink_to(os.readlink(path))
        else:
            shutil.copy2(path, target, follow_symlinks=False)
        copied += 1
    return copied


def main(argv):
    command = argv[1] if len(argv) > 1 else ''
    if command == 'lint-dir' and len(argv) == 4:
        print(lint_dir(argv[2], argv[3]))
        return 0
    if command == 'typecheck-info' and len(argv) == 4:
        print(typecheck_info(argv[2], argv[3]))
        return 0
    arguments = argv[1:][1:]
    if command == 'secret-plan':
        print(secret_plan(*arguments))  # root cache [base scope]; another count is a TypeError: exit 1
        return 0
    if command == 'secret-files':
        root, base, scope, listing = arguments  # another count is a ValueError: exit 1
        names = changed_files(root, base, scope)
        if names is not None:
            Path(listing).write_text(''.join(name + '\0' for name in names))
        print('full' if names is None else 'change')
        return 0
    if command == 'secret-record' and len(argv) == 4:
        secret_record(argv[2], argv[3])
        return 0
    if command == 'copy-if-absent' and len(argv) == 4:
        copy_if_absent(argv[2], argv[3])
        return 0
    print('usage: gate_speed.py lint-dir|typecheck-info|secret-plan|secret-files|secret-record|copy-if-absent <a> <b>', file=sys.stderr)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except Exception as error:
        print(str(error) if isinstance(error, RuntimeError) else 'gate_speed failed', file=sys.stderr)
        sys.exit(1)
