"""The push guard's hooks (X1, D-022) on fixture repositories: a bare repository is the remote, its post-receive hook
records every push as (before, after), and commit_check.push_errors judges those pushes as the gate does. No network."""
from datetime import datetime, timedelta, timezone
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/lib'))

import commit_check  # noqa: E402
import config  # noqa: E402
import forge_events  # noqa: E402
import push_guard  # noqa: E402
import replay_branch  # noqa: E402
import stall_report  # noqa: E402

RECORD = '#!/bin/sh\nwhile read old new ref; do echo "$old $new $ref" >> "$PUSH_LOG"; done\n'


def git(cwd, *args, check=True):
    done = subprocess.run(['git', '-C', str(cwd), *args], capture_output=True, text=True)
    if check and done.returncode:
        raise AssertionError(f'git {" ".join(args)}: {done.stderr}')
    return done


def commit(work, name):
    (work / f'{name}.txt').write_text(name)
    git(work, 'add', f'{name}.txt')
    done = git(work, 'commit', '--quiet', '-m', name)
    return git(work, 'rev-parse', 'HEAD').stdout.strip(), done.stderr


class Fixture(unittest.TestCase):
    """A work clone whose core.hooksPath is this checkout's .githooks, and a bare remote that logs each push. The
    repositories are built once per class (prepare) and copied for each test, which keeps the battery fast."""

    @classmethod
    def setUpClass(cls):
        saved = dict(os.environ)
        cls.addClassCleanup(lambda: (os.environ.clear(), os.environ.update(saved)))
        # no hook state (GIT_DIR, GIT_INDEX_FILE) reaches the fixtures; the suite's git configuration does (D-118)
        env = {key: value for key, value in saved.items() if not key.startswith('GIT_') or key.startswith('GIT_CONFIG_')}
        env.update(GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.invalid', GIT_COMMITTER_NAME='t',
                   GIT_COMMITTER_EMAIL='t@example.invalid')
        os.environ.clear()
        os.environ.update(env)
        cls.template = Path(tempfile.mkdtemp())
        cls.addClassCleanup(shutil.rmtree, cls.template)
        os.environ['PUSH_LOG'] = str(cls.template / 'pushes.log')
        cls.prepare(cls.template / 'remote.git', cls.template / 'work')
        (cls.template / 'pushes.log').unlink(missing_ok=True)

    @classmethod
    def prepare(cls, remote, work):
        git(remote.parent, 'init', '--quiet', '--bare', str(remote))
        (remote / 'hooks/post-receive').write_text(RECORD)
        (remote / 'hooks/post-receive').chmod(0o755)
        git(remote.parent, 'init', '--quiet', '--initial-branch=main', str(work))
        git(work, 'remote', 'add', config.get('push-guard.remote'), str(remote))
        commit(work, 'base')
        git(work, 'push', '--quiet', config.get('push-guard.remote'), 'main')
        git(work, 'fetch', '--quiet', config.get('push-guard.remote'))
        git(work, 'config', 'core.hooksPath', str(cls.hooks(remote.parent)))

    @staticmethod
    def hooks(folder):
        """The hooks under test, as the checkout ships them, without pre-push (GATE-SPEED F2): every fixture push ran
        the whole local check of commit_check and prepush, which their own tests judge, at seconds of CPU a push. A root
        whose scripts/ is this checkout's, so each hook finds push_guard.py where it looks."""
        root = folder / 'hook-root'
        shipped = ROOT / config.get('push-guard.hooks_path')
        (root / shipped.name).mkdir(parents=True, exist_ok=True)
        for hook in shipped.iterdir():
            if hook.name != 'pre-push':
                shutil.copy2(hook, root / shipped.name / hook.name)
        (root / 'scripts').symlink_to(ROOT / 'scripts')
        return root / shipped.name

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        shutil.copytree(self.template, self.tmp, symlinks=True, dirs_exist_ok=True)
        self.remote, self.work, self.log = self.tmp / 'remote.git', self.tmp / 'work', self.tmp / 'pushes.log'
        os.environ['PUSH_LOG'] = str(self.log)
        git(self.work, 'remote', 'set-url', config.get('push-guard.remote'), str(self.remote))

    def commit(self, name):
        return commit(self.work, name)

    def pushes(self):
        if not self.log.is_file():
            return []
        return [dict(zip(('before', 'after', 'ref'), line.split())) for line in self.log.read_text().splitlines()]

    def remote_tip(self, branch):
        done = git(self.remote, 'rev-parse', '--verify', '--quiet', f'refs/heads/{branch}', check=False)
        return done.stdout.strip() or None

    def assert_one_commit_per_push(self, branch, shas):
        pushes = [push for push in self.pushes() if push['ref'] == f'refs/heads/{branch}']
        self.assertEqual([push['after'] for push in pushes], shas)
        commits = [{'sha': sha} for sha in shas]
        self.assertEqual(commit_check.push_errors(commits, pushes), [])


class RefusalIncident(unittest.TestCase):
    """ORIGIN-FINISH: a refused push opens its incident in the checkout that pushed, never in the engine's own tree
    (the suite's temporary repositories wrote I-*.md files into the real checkout)."""

    def test_the_incident_lands_in_the_pushed_checkout(self):
        engine = sorted((ROOT / 'docs/operations/incidents').glob('I-*.md'))
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            result = push_guard.Result('failed', 'push of 0000000 refused', 'claude/x', [], 'error: refused')
            push_guard.report(result, stream=io.StringIO(), root=Path(tmp))
            self.assertTrue(list((Path(tmp) / 'docs/operations/incidents').glob('I-*.md')))
        self.assertEqual(sorted((ROOT / 'docs/operations/incidents').glob('I-*.md')), engine)


class Hook(Fixture):
    def test_pushes_each_commit_alone_and_sets_the_upstream(self):
        git(self.work, 'checkout', '--quiet', '-b', 'claude/x')
        first, _ = self.commit('one')
        second, _ = self.commit('two')
        self.assert_one_commit_per_push('claude/x', [first, second])
        self.assertEqual(git(self.work, 'rev-parse', '--abbrev-ref', '@{u}').stdout.strip(),
                         f'{config.get("push-guard.remote")}/claude/x')

    def test_a_branch_started_from_the_base_is_pushed_to_itself_never_to_the_base(self):
        remote = config.get('push-guard.remote')
        git(self.work, 'checkout', '--quiet', '-b', 'claude/y', '--track', f'{remote}/main')
        sha, _ = self.commit('one')
        self.assertEqual(self.remote_tip('claude/y'), sha)
        self.assertNotEqual(self.remote_tip('main'), sha)

    def test_a_failed_push_keeps_the_commit_and_the_next_commit_retries_one_per_push(self):
        git(self.work, 'checkout', '--quiet', '-b', 'claude/z')
        moved = self.tmp / 'away.git'
        self.remote.rename(moved)
        first, stderr = self.commit('one')
        self.assertIn('push-guard: claude/z: push of', stderr)
        records = list((self.work / 'docs/operations/incidents').glob('I-*.md'))
        self.assertEqual(len(records), 1)
        self.assertIn('claude/z: push of', records[0].read_text())
        self.assertEqual(git(self.work, 'rev-parse', 'HEAD').stdout.strip(), first)
        moved.rename(self.remote)
        second, _ = self.commit('two')
        self.assert_one_commit_per_push('claude/z', [first, second])

    def test_merge_commit_is_pushed_alone(self):
        git(self.work, 'checkout', '--quiet', '-b', 'claude/m')
        first, _ = self.commit('one')
        git(self.work, 'checkout', '--quiet', 'main')
        self.commit('base-moves')
        git(self.work, 'checkout', '--quiet', 'claude/m')
        git(self.work, 'merge', '--quiet', '--no-edit', 'main')
        merge = git(self.work, 'rev-parse', 'HEAD').stdout.strip()
        self.assert_one_commit_per_push('claude/m', [first, merge])

    def test_cherry_pick_pushes_each_picked_commit(self):
        git(self.work, 'checkout', '--quiet', '-b', 'side')
        picks = [self.commit('one')[0], self.commit('two')[0]]
        git(self.work, 'checkout', '--quiet', '-b', 'claude/c', 'main')
        git(self.work, 'cherry-pick', *picks)
        heads = git(self.work, 'rev-list', '--reverse', 'main..HEAD').stdout.split()
        self.assert_one_commit_per_push('claude/c', heads)

    def test_skips_detached_head_protected_branches_and_other_branches(self):
        git(self.work, 'checkout', '--quiet', '--detach')
        self.commit('detached')
        git(self.work, 'checkout', '--quiet', '-b', config.get('train.base_branch'), 'main')
        self.commit('integration')
        git(self.work, 'checkout', '--quiet', 'main')
        self.commit('main')
        git(self.work, 'checkout', '--quiet', '-b', 'feature/no-pattern')
        self.commit('other')
        self.assertEqual(self.pushes(), [])

    def test_never_force_pushes_a_rewritten_commit(self):
        git(self.work, 'checkout', '--quiet', '-b', 'claude/f')
        pushed, _ = self.commit('one')
        done = git(self.work, 'commit', '--quiet', '--amend', '-m', 'rewritten')
        self.assertIn('push of', done.stderr)
        self.assertEqual(self.remote_tip('claude/f'), pushed)


class MovedRemote(Fixture):
    """VAZÃO F30 (units/f23, 03/11): scripts/deliver merged the base into the lane's branch in its own worktree and
    pushed that merge while the lane made a commit on the older head. That commit can never reach the remote alone (it
    is a sibling of the remote's head), so the guard says to merge <remote>/<branch>, and the merge then carries it in
    one push: the remote's side is already published, so the push brings one commit of the lane plus the merge."""

    def deliver_merges_the_base(self, branch):
        """What deliver's _with_base does: in another checkout, the base moves and is merged into the branch, pushed."""
        other = self.tmp / 'deliver'
        git(self.tmp, 'clone', '--quiet', '--branch', 'main', str(self.remote), str(other))
        commit(other, 'base-moves')
        git(other, 'push', '--quiet', 'origin', 'main')
        git(other, 'checkout', '--quiet', branch)
        git(other, 'merge', '--quiet', '--no-edit', 'main')
        git(other, 'push', '--quiet', 'origin', f'HEAD:refs/heads/{branch}')
        return git(other, 'rev-parse', 'HEAD').stdout.strip()

    def test_a_commit_under_a_moved_remote_names_the_merge_and_rides_with_it(self):
        remote = config.get('push-guard.remote')
        git(self.work, 'checkout', '--quiet', '-b', 'claude/moved')
        first, _ = self.commit('one')
        base_merge = self.deliver_merges_the_base('claude/moved')
        stuck, stderr = self.commit('two')
        self.assertIn(f'git merge {remote}/claude/moved', stderr)
        self.assertEqual(self.remote_tip('claude/moved'), base_merge)
        done = git(self.work, 'merge', '--no-edit', f'{remote}/claude/moved')  # the guard fetched the moved head
        merge = git(self.work, 'rev-parse', 'HEAD').stdout.strip()
        self.assertEqual(git(self.work, 'rev-parse', 'HEAD^1', 'HEAD^2').stdout.split(), [stuck, base_merge])
        self.assertEqual(self.remote_tip('claude/moved'), merge, done.stderr)
        pushes = [push for push in self.pushes() if push['ref'] == 'refs/heads/claude/moved']
        self.assertEqual([push['after'] for push in pushes], [first, base_merge, merge])
        self.assertEqual(pushes[-1]['before'], base_merge)
        # the gate's judge, with the PR's commits in either order the forge may list them
        log = git(self.work, 'log', '--format=%H %P', 'main..HEAD').stdout.splitlines()
        commits = {line.split()[0]: {'sha': line.split()[0], 'parents': line.split()[1:]} for line in log}
        for order in ([first, base_merge, stuck, merge], [first, stuck, base_merge, merge]):
            self.assertEqual(commit_check.push_errors([commits[sha] for sha in order], pushes), [])
        self.assertEqual(push_guard.push_pending(self.work, push_guard.settings()).status, 'nothing')

    def test_a_retry_before_the_merge_still_names_the_merge(self):
        git(self.work, 'checkout', '--quiet', '-b', 'claude/retry')
        self.commit('one')
        self.deliver_merges_the_base('claude/retry')
        git(self.work, 'config', 'core.hooksPath', str(self.tmp / 'none'))
        self.commit('two')
        result = push_guard.push_pending(self.work, push_guard.settings())
        self.assertEqual(result.status, 'failed')
        self.assertIn(f'git merge {config.get("push-guard.remote")}/claude/retry', result.remedy)
        stream = io.StringIO()
        push_guard.report(result, root=self.work, stream=stream)
        self.assertIn('git merge', stream.getvalue())
        self.assertNotIn('retries it', stream.getvalue())


class ShippedHooks(Fixture):
    """The hooks exactly as the checkout ships them, pre-push included, once (GATE-SPEED F2): the other fixtures install
    only the hooks under test, so this push is the one that runs the whole chain (machine_refs, commit_check --local,
    prepush --hook) end to end."""

    def test_a_commit_is_pushed_alone_through_the_shipped_pre_push(self):
        git(self.work, 'config', 'core.hooksPath', str(ROOT / config.get('push-guard.hooks_path')))
        git(self.work, 'checkout', '--quiet', '-b', 'claude/shipped')
        sha, _ = self.commit('through every shipped hook')
        self.assert_one_commit_per_push('claude/shipped', [sha])
        self.assertEqual(self.remote_tip('claude/shipped'), sha)


class Library(Fixture):
    def options(self, **changes):
        return {**push_guard.settings(), **changes}

    def test_disabled_flag_pushes_nothing(self):
        git(self.work, 'checkout', '--quiet', '-b', 'claude/off')
        git(self.work, 'config', 'core.hooksPath', str(self.tmp / 'none'))
        self.commit('one')
        result = push_guard.push_pending(self.work, self.options(enabled=False))
        self.assertEqual((result.status, result.reason), ('skipped', 'push-guard.enabled is false'))
        self.assertIsNone(self.remote_tip('claude/off'))

    def test_push_command_pushes_what_is_pending_and_reports_nothing_after(self):
        git(self.work, 'checkout', '--quiet', '-b', 'claude/manual')
        git(self.work, 'config', 'core.hooksPath', str(self.tmp / 'none'))
        shas = [self.commit('one')[0], self.commit('two')[0]]
        self.assertEqual(push_guard.push_pending(self.work, self.options()).pushed, shas)
        self.assert_one_commit_per_push('claude/manual', shas)
        self.assertEqual(push_guard.push_pending(self.work, self.options()).status, 'nothing')

    def test_install_sets_the_hooks_path_only_when_none_is_set(self):
        (self.work / config.get('push-guard.hooks_path')).mkdir()
        git(self.work, 'config', '--unset', 'core.hooksPath')
        self.assertEqual(push_guard.install(self.work, self.options()), 'installed')
        self.assertEqual(git(self.work, 'config', 'core.hooksPath').stdout.strip(), config.get('push-guard.hooks_path'))
        git(self.work, 'config', 'core.hooksPath', 'mine')
        self.assertEqual(push_guard.install(self.work, self.options()), 'kept')

    def test_install_links_the_pre_commit_stage_to_this_checkout(self):
        """D-237: without the link the checkout's pre-commit hook never runs; after install it runs and refuses a commit
        whose generation fails. The first commit fails the test when no link is made."""
        work = self.work
        (work / '.githooks').mkdir(exist_ok=True)
        shutil.copy(ROOT / '.githooks' / 'pre-commit', work / '.githooks' / 'pre-commit')
        (work / 'scripts' / 'lib').mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / 'scripts' / 'lib' / 'generate_stage.sh', work / 'scripts' / 'lib' / 'generate_stage.sh')
        generator = work / 'scripts' / 'generate'
        generator.write_text('#!' + shutil.which('sh') + '\nexit 1\n', encoding='utf-8')
        generator.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        (work / 'unlinked.txt').write_text('one\n', encoding='utf-8')
        git(work, 'add', '-A')
        git(work, 'config', '--unset', 'core.hooksPath', check=False)
        self.assertEqual(git(work, 'commit', '-q', '-m', 'no link', check=False).returncode, 0)

        (work / 'linked.txt').write_text('two\n', encoding='utf-8')
        git(work, 'add', '-A')
        self.assertEqual(push_guard.install(work, self.options()), 'installed')
        done = git(work, 'commit', '-q', '-m', 'linked', check=False)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('the commit is refused', done.stderr)

    def test_env_sh_links_the_hooks_of_a_checkout_that_has_none(self):
        """D-237: scripts/cloud/env.sh calls install when the checkout has no hooks path, so a session that sources it
        gets the pre-commit stage. Without that line the hooks path stays unset and the test fails."""
        checkout = self.tmp / 'envcheckout'
        for name in ('scripts/cloud/env.sh', 'scripts/cloud/root-session.sh', '.githooks', 'scripts/lib', 'config/registry',
                     'contracts'):
            source = ROOT / name
            target = checkout / name
            if source.is_dir():
                shutil.copytree(source, target, symlinks=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(source, target)
        git(checkout.parent, 'init', '--quiet', '--initial-branch=main', str(checkout))
        git(checkout, 'config', '--unset', 'core.hooksPath', check=False)
        done = subprocess.run(['bash', '-c', 'source scripts/cloud/env.sh'], cwd=checkout, capture_output=True,
                              text=True, env={**os.environ, 'OU_PYTHON': sys.executable, 'OU_CONFIG_STORE': 'file'})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(git(checkout, 'config', '--get', 'core.hooksPath').stdout.strip(),
                         config.get('push-guard.hooks_path'))

    def test_the_hooks_name_no_force_flag(self):
        source = (ROOT / 'scripts/lib/push_guard.py').read_text()
        self.assertNotIn('--force', source.split('"""', 2)[2])
        self.assertNotIn("'+", source)


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def now(self):
        return self.moment


class FakeForge(forge_events.MemoryAdapter):
    """The forge operations replay-branch and stall-report use, in memory."""

    def __init__(self, pulls=None, commits=None, pushes=None, comments=None):
        super().__init__()
        self.pulls, self.commit_lists = dict(pulls or {}), dict(commits or {})
        self.push_lists, self.comment_lists = dict(pushes or {}), dict(comments or {})
        self.opened, self.closed, self.posted = [], [], []

    def pull(self, repo, number):
        return dict(self.pulls[number])

    def change_commits(self, repo, number):
        return list(self.commit_lists[number])

    def find_change(self, repo, head_ref):
        return max((n for n, pull in self.pulls.items() if pull['head_ref'] == head_ref), default=None)

    def open_change(self, repo, head_ref, base_ref, title, body):
        number = max(self.pulls) + 1
        self.pulls[number] = {'number': number, 'title': title, 'body': body, 'state': 'open', 'head_ref': head_ref,
                              'head_sha': None, 'base_ref': base_ref}
        self.opened.append(number)
        return number

    def close_change(self, repo, number):
        self.pulls[number]['state'] = 'closed'
        self.closed.append(number)

    def comment(self, repo, number, body):
        self.posted.append((number, body))

    def open_changes(self, repo, base):
        return [n for n, pull in self.pulls.items() if pull['state'] == 'open' and pull['base_ref'] == base]

    def comments(self, repo, number):
        return list(self.comment_lists.get(number, []))

    def pushes(self, repo, branch):
        return list(self.push_lists.get(branch, []))


class Replay(Fixture):
    """scripts/replay-branch on a PR whose two commits reached the remote in one push."""

    BODY = '## Commit plan\n- [ ] 1. One.\n- [ ] 2. Two.\n- [ ] 3. Three.\n'

    @classmethod
    def prepare(cls, remote, work):
        super().prepare(remote, work)
        hooks = git(work, 'config', 'core.hooksPath').stdout.strip()
        git(work, 'config', 'core.hooksPath', str(remote.parent / 'none'))
        git(work, 'checkout', '--quiet', '-b', 'claude/old')
        first, _ = commit(work, 'one')
        git(work, 'checkout', '--quiet', 'main')
        commit(work, 'base-two')
        git(work, 'push', '--quiet', config.get('push-guard.remote'), 'main')
        git(work, 'checkout', '--quiet', 'claude/old')
        git(work, 'merge', '--quiet', '--no-edit', 'main')
        cls.merge = git(work, 'rev-parse', 'HEAD').stdout.strip()
        second, _ = commit(work, 'two')
        git(work, 'push', '--quiet', config.get('push-guard.remote'), 'claude/old')
        git(work, 'checkout', '--quiet', 'main')
        git(work, 'config', 'core.hooksPath', hooks)
        cls.own = [first, second]

    def setUp(self):
        super().setUp()
        first, second = self.own
        self.forge = FakeForge(
            pulls={7: {'number': 7, 'title': 'T', 'body': self.BODY, 'state': 'open', 'head_ref': 'claude/old',
                       'head_sha': second, 'base_ref': 'main'}},
            commits={7: [{'sha': first, 'parents': ['b' * 40]}, {'sha': self.merge, 'parents': [first, 'c' * 40]},
                         {'sha': second, 'parents': [self.merge]}]})
        # A local double stands in for the forge; compatibility is proved by test_forge_events.
        self.enterContext(mock.patch.object(forge_events, '_require_compatibility'))
        self.port = forge_events.ForgeEvents(self.forge, Clock(None), 'test', 'test')

    def replay(self):
        return replay_branch.replay(7, self.port, 'o/r', self.work, replay_branch.options())

    def replayed(self, branch):
        remote = config.get('push-guard.remote')
        return git(self.work, 'rev-list', '--reverse', '--first-parent', f'{remote}/main..{remote}/{branch}').stdout.split()

    def picked_from(self, sha):
        return replay_branch.PICKED.findall(git(self.work, 'log', '-1', '--format=%B', sha).stdout)

    def test_the_old_batched_push_is_refused_and_the_replacement_passes(self):
        old = [{'sha': sha} for sha in self.own]
        self.assertTrue(commit_check.push_errors(old, [{'before': '0' * 40, 'after': self.own[-1]}], 7))
        outcome = self.replay()
        branch = 'claude/old' + config.get('push-guard.replay_suffix').format(n=1)
        self.assertEqual((outcome['branch'], outcome['new'], outcome['picked'], outcome['resumed']),
                         (branch, 8, self.own, False))
        heads = self.replayed(branch)
        self.assertEqual([self.picked_from(sha) for sha in heads], [[sha] for sha in self.own])
        self.assert_one_commit_per_push(branch, heads)
        self.assertIn(config.get('push-guard.supersedes_line').format(old=7), self.forge.pulls[8]['body'])
        self.assertTrue(self.forge.pulls[8]['body'].startswith(self.BODY.rstrip()))
        self.assertEqual((self.forge.closed, [n for n, _ in self.forge.posted]), ([7], [7]))
        self.assertIn('#8', self.forge.posted[0][1])

    def test_a_rerun_resumes_and_does_nothing_twice(self):
        self.replay()
        pushes = self.pushes()
        again = self.replay()
        self.assertEqual((again['new'], again['picked'], again['resumed']), (8, [], True))
        self.assertEqual((self.pushes(), self.forge.opened, self.forge.closed), (pushes, [8], [7]))

    def test_a_partial_replay_resumes_and_merges_the_moved_base_in_one_merge_commit(self):
        remote, branch = config.get('push-guard.remote'), 'claude/old' + config.get('push-guard.replay_suffix').format(n=1)
        git(self.work, 'checkout', '--quiet', '-b', branch, f'{remote}/main')
        git(self.work, 'cherry-pick', '-x', self.own[0])
        git(self.work, 'checkout', '--quiet', 'main')
        self.commit('base-three')
        git(self.work, 'push', '--quiet', remote, 'main')
        git(self.work, 'branch', '--quiet', '-D', branch)
        outcome = self.replay()
        self.assertEqual((outcome['picked'], outcome['merged'], outcome['resumed']), (self.own[1:], True, True))
        heads = git(self.work, 'rev-list', '--reverse', '--first-parent',
                    f'{remote}/main~1..{remote}/{branch}').stdout.split()
        self.assertEqual(len(heads), 3)
        self.assert_one_commit_per_push(branch, heads)

    def test_a_conflict_stops_with_the_way_to_finish_by_hand(self):
        remote = config.get('push-guard.remote')
        (self.work / 'two.txt').write_text('the base wrote it first')
        git(self.work, 'add', 'two.txt')
        git(self.work, 'commit', '--quiet', '-m', 'base writes two')
        git(self.work, 'push', '--quiet', remote, 'main')
        with self.assertRaisesRegex(replay_branch.ReplayError, 'cherry-pick of .* conflicts; finish it by hand'):
            self.replay()
        self.assertEqual((self.forge.opened, self.forge.closed), ([], []))
        self.assertNotIn('replay-branch-', git(self.work, 'worktree', 'list').stdout)

    def test_a_merged_pr_is_not_replayed(self):
        self.forge.pulls[7]['state'] = 'merged'
        with self.assertRaisesRegex(replay_branch.ReplayError, 'is merged'):
            self.replay()


class Heartbeat(Fixture):
    """engine.session.heartbeat for every push attempt, through the forge_events port."""

    def port(self):
        return forge_events.ForgeEvents(forge_events.MemoryAdapter(), Clock(NOW), 'test', 'test')

    def test_a_push_and_a_failed_push_each_emit_a_heartbeat(self):
        git(self.work, 'checkout', '--quiet', '-b', 'claude/hb')
        git(self.work, 'config', 'core.hooksPath', str(self.tmp / 'none'))
        sha, _ = self.commit('one')
        port = self.port()
        ok = push_guard.heartbeat(push_guard.push_pending(self.work, push_guard.settings()), self.work, port)
        self.assertEqual((ok['payload']['result'], ok['payload']['pushed'], ok['payload']['pr']), ('ok', [sha], None))
        self.remote.rename(self.tmp / 'away.git')
        self.commit('two')
        failed = push_guard.heartbeat(push_guard.push_pending(self.work, push_guard.settings()), self.work, port)
        self.assertEqual((failed['payload']['result'], failed['payload']['pushed']), ('failed', []))
        self.assertIn('refused', failed['payload']['detail'])
        self.assertEqual(len(port.read(config.get('forge-events.repo'))), 2)
        nothing = push_guard.push_pending(self.work, {**push_guard.settings(), 'enabled': False})
        self.assertIsNone(push_guard.heartbeat(nothing, self.work, port))

    def test_the_hook_records_its_heartbeat_in_the_checkout_git_directory(self):
        git(self.work, 'checkout', '--quiet', '-b', 'claude/hb')
        sha, _ = self.commit('one')
        log = forge_events.FileAdapter(self.work / '.git' / config.get('push-guard.heartbeat_log_dir'))
        [event] = log.read(forge_events.Channel(config.get('forge-events.repo'), None))
        self.assertEqual((event['type'], event['payload']['sha'], event['payload']['result']),
                         ('engine.session.heartbeat', sha, 'ok'))


NOW = datetime(2026, 10, 26, 22, 0, tzinfo=timezone.utc)
REPO = 'openuniversity-si/open-university'


def at(minutes_ago):
    return forge_events.rfc3339(NOW - timedelta(minutes=minutes_ago))


class Stall(unittest.TestCase):
    """scripts/stall-report on a fake forge: each reason, the green head that waits on the merger, --emit."""

    def setUp(self):
        # A local double stands in for the forge; compatibility is proved by test_forge_events.
        self.enterContext(mock.patch.object(forge_events, '_require_compatibility'))
        self.forge = FakeForge()
        self.port = forge_events.ForgeEvents(self.forge, Clock(NOW), 'test', 'stall')

    def pr(self, number, pushed=None, verdict=None, comments=()):
        branch, head = f'claude/pr-{number}', f'{number:x}'.rjust(40, 'a')
        self.forge.pulls[number] = {'number': number, 'title': 'T', 'body': '', 'state': 'open', 'head_ref': branch,
                                    'head_sha': head, 'base_ref': config.get('train.base_branch')}
        self.forge.push_lists[branch] = [{'before': '0' * 40, 'after': head, 'timestamp': pushed}] if pushed else []
        if verdict:
            kind, minutes = verdict
            emitter = forge_events.ForgeEvents(self.forge, Clock(NOW - timedelta(minutes=minutes)), 'gate_report', 'g')
            payload = dict(forge_events.subject(REPO, number, head), tier=1, plan='dev', missing_stages=[],
                           input_hash='d' * 64, stages=[{'name': 'lint', 'result': 'PASS' if kind == 'passed' else
                                                         'FAIL', 'duration_ms': 1, 'class': None if kind == 'passed'
                                                         else 'code'}])
            emitter.emit(f'gate.{kind}', payload)
        self.forge.comment_lists[number] = [{'body': body, 'created_at': at(minutes)} for body, minutes in comments]

    def reasons(self):
        return [(item['pr'], item['reason']) for item in stall_report.report(self.port, REPO, config.get('train.base_branch'))]

    def test_each_reason_is_found_and_an_active_pr_is_not(self):
        quiet = config.get('push-guard.stall_no_push_s') // 60 + 1
        red = config.get('push-guard.stall_red_gate_s') // 60 + 1
        self.pr(1, pushed=at(1), verdict=('failed', 2))
        self.pr(2, pushed=at(quiet))
        self.pr(3, pushed=at(red + 1), verdict=('failed', red))
        self.pr(4, pushed=at(1), comments=[('Gate red.', 3), ('BLOCKED: waiting on the base.', 2)])
        self.pr(5, pushed=at(1), comments=[('BLOCKED: refused push.', 3), ('Decision: replayed it.', 2)])
        self.pr(6, pushed=at(quiet), verdict=('passed', quiet - 1))
        self.assertEqual(self.reasons(), [(2, 'no_push'), (3, 'red_gate'), (4, 'owner_wait')])

    def test_the_report_names_since_and_the_last_signals(self):
        red = config.get('push-guard.stall_red_gate_s') // 60 + 1
        self.pr(3, pushed=at(red + 1), verdict=('failed', red))
        [item] = stall_report.report(self.port, REPO, config.get('train.base_branch'))
        self.assertEqual(item, {'pr': 3, 'branch': 'claude/pr-3', 'reason': 'red_gate', 'since': at(red),
                                'last_push': at(red + 1), 'last_gate': 'failed', 'last_gate_at': at(red),
                                'detail': None})

    def test_emit_records_each_stall_once(self):
        self.pr(4, pushed=at(1), comments=[('This is a decision for the owner.', 2)])
        for _ in range(2):
            stall_report.report(self.port, REPO, config.get('train.base_branch'), emit=True)
        [event] = [e for e in self.port.read(REPO, 4) if e['type'] == 'engine.session.stalled']
        self.assertEqual((event['payload']['reason'], event['payload']['since']), ('owner_wait', at(2)))


def parallel():
    """Each test class in its own process (every class has its own temporary repositories): the unit's battery stays
    inside battery.unit_time_limit without dropping a case."""
    names = [name for name, value in globals().items() if isinstance(value, type)
             and issubclass(value, unittest.TestCase) and value is not Fixture and value.__module__ == __name__]
    runs = [subprocess.Popen([sys.executable, __file__, name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True) for name in names]
    failed = 0
    for name, run in zip(names, runs):
        out, _ = run.communicate()
        summary = [line for line in out.splitlines() if line.startswith('Ran ')] + out.strip().splitlines()[-1:]
        print(f'{name}: {"; ".join(summary) or "no output"}')
        if run.returncode:
            failed += 1
            print(out)
    return 1 if failed else 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--parallel']:
        sys.exit(parallel())
    unittest.main(verbosity=1)
