"""The remedy of a D-022 batched push (X1): `scripts/replay-branch <pr>` replays the PR one push per commit.

A push that brought several commits at once cannot be undone without rewriting pushed history, which the rules forbid.
This command leaves the old branch alone and builds a replacement instead:
  1. reads the PR, its own commits and its base through the forge_events port (GitHub REST today);
  2. picks the branch <head><push-guard.replay_suffix> with the first free number, or the one that already replays
     this PR (its commits carry `(cherry picked from commit <sha>)` of one of the PR's commits);
  3. in a temporary worktree started from <remote>/<base> (or from that branch when it exists), cherry-picks -x each
     own commit not yet replayed, in order, and pushes after each one through push_guard (one commit per push);
     the base merges of the old PR are not replayed: if the base moved since the branch started, one
     `git merge <remote>/<base>` merge commit closes the replay. Never a rebase, never a force-push;
  4. opens the replacement PR with the same title and body plus push-guard.supersedes_line, then comments
     push-guard.replaced_comment on the old PR and closes it.
Rerunning finds the replacement and resumes: nothing already replayed, pushed, opened or closed is done twice. A
cherry-pick or merge conflict stops the replay and says how to finish it by hand; the rerun resumes after it.
"""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import forge_events  # noqa: E402
import push_guard  # noqa: E402

PICKED = re.compile(r'^\(cherry picked from commit ([0-9a-f]{40})\)$', re.M)


class ReplayError(RuntimeError):
    pass


def options(root=None):
    found = push_guard.settings(root)
    for key in ('git_timeout_s', 'replay_suffix', 'replay_max', 'event_producer', 'replay_step', 'supersedes_line',
                'replaced_comment'):
        found[key] = config.get(f'push-guard.{key}', root)
    return found


class Git:
    def __init__(self, cwd, timeout):
        self.cwd, self.timeout = cwd, timeout

    def run(self, *args, check=True):
        try:
            done = push_guard.git(self.cwd, *args, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            raise ReplayError(f'git {args[0]} exceeded push-guard.git_timeout_s; rerun scripts/replay-branch') from None
        if check and done.returncode:
            raise ReplayError(f'git {" ".join(args)}: {done.stderr.strip() or done.stdout.strip()}')
        return done

    def out(self, *args):
        return self.run(*args).stdout.strip()

    def exists(self, ref):
        return self.run('rev-parse', '--verify', '--quiet', ref, check=False).returncode == 0


def replayed(git, base_ref, ref):
    """The original shas a branch already replays, from the -x lines of base..ref."""
    return set(PICKED.findall(git.out('log', '--format=%B', f'{base_ref}..{ref}')))


def choose_branch(git, remote, head_ref, base_ref, own, opts):
    """(branch, exists): the branch that already replays this PR, else the first free replay number."""
    taken = []
    for number in range(1, opts['replay_max'] + 1):
        branch = head_ref + opts['replay_suffix'].format(n=number)
        if not git.exists(f'refs/remotes/{remote}/{branch}'):
            return branch, False
        if replayed(git, f'{remote}/{base_ref}', f'{remote}/{branch}') & set(own):
            return branch, True
        taken.append(branch)
    raise ReplayError(f'no free replacement branch up to push-guard.replay_max: {", ".join(taken)}')


def replay(number, port, repo, cwd, opts):
    """Replay change `number`; returns {old, new, branch, picked, merged, resumed}."""
    pull = port.pull(repo, number)
    if pull['state'] == 'merged':
        raise ReplayError(f'#{number} is merged; there is nothing to replay')
    own = [commit['sha'] for commit in port.change_commits(repo, number) if len(commit.get('parents') or []) < 2]
    remote, base_ref, head_ref = opts['remote'], pull['base_ref'], pull['head_ref']
    git = Git(cwd, opts['git_timeout_s'])
    git.run('fetch', '--quiet', remote, base_ref, head_ref)
    git.run('fetch', '--quiet', remote, f'refs/heads/{head_ref}{opts["replay_suffix"].format(n="*")}:'
            f'refs/remotes/{remote}/{head_ref}{opts["replay_suffix"].format(n="*")}')
    branch, resumed = choose_branch(git, remote, head_ref, base_ref, own, opts)
    start = f'{remote}/{branch}' if resumed else f'{remote}/{base_ref}'
    tree = Path(tempfile.mkdtemp(prefix='replay-branch-'))
    shutil.rmtree(tree)
    git.run('worktree', 'add', '--quiet', '-B', branch, str(tree), start)
    work = Git(tree, opts['git_timeout_s'])
    picked, merged = [], False
    try:
        work.run('config', f'branch.{branch}.remote', remote)
        work.run('config', f'branch.{branch}.merge', f'refs/heads/{branch}')
        done = replayed(work, f'{remote}/{base_ref}', 'HEAD')
        for sha in own:
            if sha in done:
                continue
            step = work.run('cherry-pick', '-x', '--keep-redundant-commits', sha, check=False)
            if step.returncode:
                work.run('cherry-pick', '--abort', check=False)
                raise ReplayError(f'cherry-pick of {sha[:8]} onto {branch} conflicts; finish it by hand: '
                                  f'`git checkout {branch} && git cherry-pick -x {sha}`, resolve, '
                                  f'`git cherry-pick --continue` (the hook pushes it), then rerun scripts/replay-branch {number}')
            _push(tree, opts, branch)
            picked.append(sha)
        if work.run('merge-base', '--is-ancestor', f'{remote}/{base_ref}', 'HEAD', check=False).returncode:
            step = work.run('merge', '--no-ff', '--no-edit', f'{remote}/{base_ref}', check=False)
            if step.returncode:
                work.run('merge', '--abort', check=False)
                raise ReplayError(f'merging {remote}/{base_ref} into {branch} conflicts; finish it by hand: '
                                  f'`git checkout {branch} && git merge {remote}/{base_ref}`, resolve, commit '
                                  f'(the hook pushes it), then rerun scripts/replay-branch {number}')
            _push(tree, opts, branch)
            merged = True
    finally:
        git.run('worktree', 'remove', '--force', str(tree), check=False)
    new = port.find_change(repo, branch)
    if new is None:
        body = pull['body'].rstrip() + '\n\n' + opts['supersedes_line'].format(old=number) + '\n'
        new = port.open_change(repo, branch, base_ref, pull['title'], body)
    if pull['state'] == 'open':
        port.comment(repo, number, opts['replaced_comment'].format(new=new, branch=branch))
        port.close_change(repo, number)
    return {'old': number, 'new': new, 'branch': branch, 'picked': picked, 'merged': merged, 'resumed': resumed}


def _push(tree, opts, branch):
    """push_guard's one-commit-per-push, also while the hooks' flag is off: this is an explicit command."""
    result = push_guard.push_pending(tree, {**opts, 'enabled': True})
    if result.status not in ('pushed', 'nothing'):
        raise ReplayError(f'{branch}: {result.reason} ({result.error or "no detail"}); rerun scripts/replay-branch')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/replay-branch', description=__doc__.splitlines()[0])
    parser.add_argument('pr', type=int, help='the PR whose batched push D-022 refused')
    parser.add_argument('--dir', type=Path, default=Path.cwd(), help='a checkout of the repository')
    args = parser.parse_args(argv)
    opts = options()
    repo = config.get('forge-events.repo')
    port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                    opts['event_producer'], f'replay-{args.pr}')
    try:
        with forge_events.measured(port, opts['replay_step'], forge_events.subject(repo, args.pr, None)):
            outcome = replay(args.pr, port, repo, args.dir, opts)
    except (ReplayError, RuntimeError) as error:
        print(f'FAIL replay-branch: {error}')
        return 1
    print(f'replay-branch: #{outcome["old"]} -> #{outcome["new"]} on {outcome["branch"]}: '
          f'{len(outcome["picked"])} commit(s) replayed one per push'
          f'{", base merged" if outcome["merged"] else ""}{", resumed" if outcome["resumed"] else ""}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
