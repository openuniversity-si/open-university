"""The push guard (X1, D-022): every new commit of a work branch reaches its remote alone, right after it is made.

D-022 refuses a push that brings several commits of a PR at once (commit_check.push_errors), and a batched push cannot
be undone without rewriting pushed history. The versioned hooks .githooks/post-commit (git also runs it for
cherry-pick and revert) and .githooks/post-merge (the merge commit of `git merge origin/<base>`) call
`push_guard.py hook`, which pushes every unpushed first-parent commit of HEAD one by one, oldest first, each in its
own `git push <remote> <sha>:refs/heads/<branch>`. A push that failed earlier is retried by the next commit and still
goes out one commit per push. Never a force-push: a rewritten branch is refused by the remote and reported. When
another checkout pushed a merge into the branch (scripts/deliver merges the base) under a commit made here, that commit
can never go out alone: the refusal names `git merge <remote>/<branch>`, and the merge then carries it in one push of
one commit plus a merge of published history (VAZÃO F30), as commit_check.push_errors accepts.

The hook does nothing on a detached HEAD (rebase, bisect), on a protected branch (push-guard.protected_branches and
the integration branch train.base_branch), while push-guard.enabled is false, and on a branch without its own
upstream unless it matches push-guard.work_branch_patterns (it then gets <remote>/<branch> as its upstream; a branch
that tracks the base it started from is never pushed to that base). A failure never fails the commit: the hook
prints it to stderr and exits 0. Each push attempt (ok or failed) is recorded as engine.session.heartbeat through the
forge_events port, on push-guard.heartbeat_adapter (by default a file log in the checkout's git directory).

  push_guard.py hook post-commit|post-merge   the hooks; always exit 0
  push_guard.py push [--dir DIR]              push what is pending by hand; exit 1 when a push fails
  push_guard.py install [--root DIR]          set core.hooksPath when the checkout has none (hooks_path.py's rule)
"""
import argparse
from collections import namedtuple
import fnmatch
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import forge_events  # noqa: E402
import hooks_path  # noqa: E402 - D-322: the install step is the bootstrap's (engine-cloud)

ROOT = Path(__file__).resolve().parents[2]
KEYS = ('enabled', 'remote', 'protected_branches', 'work_branch_patterns', 'push_timeout_s', 'hooks_path')
Result = namedtuple('Result', 'status reason branch pushed error remedy', defaults=(None,))


def settings(root=None):
    """The guard's registry values; the integration branch is the train's (one value, one name)."""
    values = {key: config.get(f'push-guard.{key}', root) for key in KEYS}
    values['integration_branch'] = config.get('train.base_branch', root)
    return values


def git(cwd, *args, timeout=None):
    return subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True, timeout=timeout)


def current_branch(cwd):
    done = git(cwd, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    return done.stdout.strip() if done.returncode == 0 else None


def protected(branch, options):
    return branch == options['integration_branch'] or branch in options['protected_branches']


def work_branch(branch, options):
    return any(fnmatch.fnmatchcase(branch, pattern) for pattern in options['work_branch_patterns'])


def own_upstream(cwd, branch, remote):
    """True when the branch tracks <remote>/<branch> itself, not the base it was started from."""
    tracked_remote = git(cwd, 'config', '--get', f'branch.{branch}.remote').stdout.strip()
    tracked_ref = git(cwd, 'config', '--get', f'branch.{branch}.merge').stdout.strip()
    return tracked_remote == remote and tracked_ref == f'refs/heads/{branch}'


def pending(cwd, remote):
    """First-parent commits of HEAD that no ref of the remote holds yet, oldest first (a merge commit counts once)."""
    done = git(cwd, 'rev-list', '--reverse', '--first-parent', 'HEAD', '--not', f'--remotes={remote}')
    if done.returncode:
        raise RuntimeError(done.stderr.strip() or 'git rev-list failed')
    return done.stdout.split()


def remote_head(cwd, remote, branch):
    """The branch's head as this checkout last saw it on the remote (refs/remotes/<remote>/<branch>), else None."""
    done = git(cwd, 'rev-parse', '--verify', '--quiet', f'refs/remotes/{remote}/{branch}^{{commit}}')
    return done.stdout.strip() or None


def contains(cwd, ancestor, sha):
    return git(cwd, 'merge-base', '--is-ancestor', ancestor, sha).returncode == 0


def pushes(cwd, shas, head):
    """The pushes for the pending commits: each commit alone, oldest first, except the commits that do not contain the
    remote's head (made on an older head while another checkout, scripts/deliver, pushed a merge of the base): they
    can never reach the remote alone, so they ride with the first pending commit that contains it, the merge of
    <remote>/<branch>: one push of that commit and a merge of already published history (F30)."""
    if head is None or not shas or contains(cwd, head, shas[0]):
        return [[sha] for sha in shas]
    carrier = next((index for index, sha in enumerate(shas) if contains(cwd, head, sha)), None)
    if carrier is None:
        return [[sha] for sha in shas]
    return [shas[:carrier + 1]] + [[sha] for sha in shas[carrier + 1:]]


def moved_remedy(cwd, remote, branch, sha, timeout):
    """After a refused push: fetch the branch's remote head; when the refused commit does not contain it, the remote
    moved under the branch (a pushed merge of the base) and only a merge brings the commit out. The remedy, else None."""
    try:
        if git(cwd, 'fetch', '--quiet', remote, f'refs/heads/{branch}:refs/remotes/{remote}/{branch}',
               timeout=timeout).returncode:
            return None
    except subprocess.TimeoutExpired:
        return None
    head = remote_head(cwd, remote, branch)
    if head is None or contains(cwd, head, sha):
        return None
    return (f'{remote}/{branch} moved to a head this commit does not contain (a merge pushed by another checkout, as '
            f'scripts/deliver does); run `git merge {remote}/{branch}` (fetched) before the next commit: '
            f'the guard then pushes that merge with the commit it carries, one push, never a force push or a rebase')


def push_pending(cwd, options):
    """Push each pending commit of the current branch alone, in order; stop at the first failure. A commit made under a
    remote head that moved rides with the merge of that head (pushes); a refusal because of such a move names the merge."""
    branch = current_branch(cwd)
    if branch is None:
        return Result('skipped', 'detached HEAD', None, [], None)
    if not options['enabled']:
        return Result('skipped', 'push-guard.enabled is false', branch, [], None)
    if protected(branch, options):
        return Result('skipped', 'protected branch', branch, [], None)
    remote = options['remote']
    tracked = own_upstream(cwd, branch, remote)
    if not tracked and not work_branch(branch, options):
        return Result('skipped', 'no upstream of its own and not a work branch', branch, [], None)
    try:
        shas = pending(cwd, remote)
    except RuntimeError as error:
        return Result('failed', 'pending commits unreadable', branch, [], str(error))
    pushed = []
    for group in pushes(cwd, shas, remote_head(cwd, remote, branch)):
        sha = group[-1]
        try:
            done = git(cwd, 'push', '--quiet', remote, f'{sha}:refs/heads/{branch}', timeout=options['push_timeout_s'])
        except subprocess.TimeoutExpired:
            return Result('failed', f'push of {sha[:8]} exceeded push-guard.push_timeout_s', branch, pushed, None)
        if done.returncode:
            remedy = moved_remedy(cwd, remote, branch, sha, options['push_timeout_s'])
            return Result('failed', f'push of {sha[:8]} refused', branch, pushed, done.stderr.strip(), remedy)
        pushed.extend(group)
    if pushed and not tracked:
        git(cwd, 'config', f'branch.{branch}.remote', remote)
        git(cwd, 'config', f'branch.{branch}.merge', f'refs/heads/{branch}')
    return Result('pushed' if pushed else 'nothing', f'{len(pushed)} commit(s), one per push', branch, pushed, None)


def report(result, root, stream=sys.stderr):
    """Report a push attempt and record a refusal in the checkout that attempted it."""
    if result.status == 'failed':
        if result.remedy:
            print(f'push-guard: {result.branch}: {result.reason}; the commit stays local: {result.remedy}', file=stream)
        else:
            print(f'push-guard: {result.branch}: {result.reason}; the commit stays local and the next commit '
                  f'(or `python3 scripts/lib/push_guard.py push`) retries it one commit per push', file=stream)
        if result.error:
            print(f'push-guard: {result.error.splitlines()[-1]}', file=stream)
        try:
            import incident  # D-234: every refused push is an incident
            incident.open_incident(Path(git(root, 'rev-parse', '--show-toplevel').stdout.strip()), 'push-refusal',
                                   f'{result.branch}: {result.reason}: ' + (result.error.splitlines()[-1] if result.error else ''))
        except (ImportError, OSError):
            pass
    elif result.status == 'pushed':
        print(f'push-guard: {result.branch}: pushed {", ".join(sha[:8] for sha in result.pushed)} one per push',
              file=stream)


def heartbeat(result, cwd, port=None):
    """engine.session.heartbeat of a push attempt (ok or failed); None for a skip or nothing to push."""
    if result.status not in ('pushed', 'failed'):
        return None
    if port is None:
        kind = config.get('push-guard.heartbeat_adapter')
        if kind == 'file':
            common = Path(cwd) / git(cwd, 'rev-parse', '--git-common-dir').stdout.strip()
            adapter = forge_events.FileAdapter(common / config.get('push-guard.heartbeat_log_dir'))
        else:
            adapter = forge_events.construct_adapter(kind, {'append', 'read'}, 'push heartbeat')
        forge_events.checked_adapter(adapter, {'append', 'read'}, 'push heartbeat')
        port = forge_events.ForgeEvents(adapter, forge_events.clock_from_config(),
                                        config.get('push-guard.event_producer'), result.branch)
    ok = result.status == 'pushed'
    detail = None if ok else ': '.join([result.reason] + (result.error or '').splitlines()[-1:])
    head = git(cwd, 'rev-parse', 'HEAD').stdout.strip()
    payload = dict(forge_events.subject(config.get('forge-events.repo'), None, head), branch=result.branch,
                   source='push', result='ok' if ok else 'failed', pushed=list(result.pushed), detail=detail)
    return port.emit('engine.session.heartbeat', payload)


def install(root, options):
    """Point core.hooksPath at the versioned hooks unless the checkout already has its own hooks path (hooks_path, the
    machine bootstrap's step, D-322)."""
    return hooks_path.install(root, options['hooks_path'])


def main(argv=None):
    parser = argparse.ArgumentParser(prog='push_guard.py', description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('hook').add_argument('event', choices=('post-commit', 'post-merge'))
    sub.add_parser('push').add_argument('--dir', type=Path, default=Path(os.getcwd()))
    sub.add_parser('install').add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if args.command == 'install':
        print(f'push-guard: {install(args.root, settings())}')
        return 0
    cwd = Path(os.getcwd()) if args.command == 'hook' else args.dir
    result = push_pending(cwd, settings())
    report(result, root=cwd)
    try:
        heartbeat(result, cwd)
    except Exception as error:  # the record of a push never fails the commit
        print(f'push-guard: heartbeat not recorded ({error})', file=sys.stderr)
    return 1 if args.command == 'push' and result.status == 'failed' else 0


if __name__ == '__main__':
    sys.exit(main())
