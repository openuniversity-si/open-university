"""The merge train v0 (plan v3 M3). Fake forge, fake gate, real local git, injected clock.

No network: the "remote" is a bare repository in a temporary directory, and the forge is an in-memory adapter.
Every tunable comes from the registry (config.get); nothing here restates a registry value.
"""
from collections import Counter, namedtuple
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import engine_role  # noqa: E402
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
import memory_git  # noqa: E402
import forge_events  # noqa: E402
import train  # noqa: E402
import train_git  # noqa: E402
import train_base_gate  # noqa: E402
import train_queue  # noqa: E402

REPO = 'openuniversity-si/open-university'
Made = namedtuple('Made', 'number head')
READS_PER_PR = ('read', 'change')  # a queue build reads each PR it looks at: its log and its head
CHAIN = {'core': {'requires': {}}, 'mid': {'requires': {'core': '^1'}}, 'top': {'requires': {'mid': '^1'}}, 'side': {}}
GIT_ENV = {'GIT_AUTHOR_NAME': 'fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
           'GIT_COMMITTER_NAME': 'fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
           'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}


def setUpModule():
    """An empty change store chosen explicitly: registry values only, never the forge (D-069 item 5)."""
    unittest.enterModuleContext(config.use_adapter(forge_events.MemoryAdapter()))


class FixtureWorkspace(train_git.GitWorkspace):
    """The train's workspace in the fixture (GATE-SPEED F8): the checkout and the forge's origin read each other's
    objects in place (objects/info/alternates), so a fetch copies the origin's ref and a push sets it, and no git
    transport runs (a fetch was about five processes, 222 of them in train/test_verdict.py alone). The workspace's own
    fetch and push are judged against a real remote in train/test_git_answers.py."""

    def __init__(self, root, forge):
        super().__init__(root)
        self.forge = forge

    def fetch(self, *revisions):
        for revision in revisions:
            if ':' not in revision:
                continue  # a commit: the checkout already reads every object of the origin
            source, target = revision.lstrip('+').split(':', 1)
            try:
                commit = self.forge.ref(source)
            except subprocess.CalledProcessError as error:
                raise train_git.GitError(f'git fetch failed: {source} is not on the remote') from error
            self.git('update-ref', target, commit)

    def push(self, commit, branch, verify=True):
        """Never forced, as `git push` without --force: a commit that does not contain the branch's tip is refused."""
        target = f'refs/heads/{branch}'
        tip = self.forge.held(target)
        if tip and self.git('merge-base', '--is-ancestor', tip, commit, check=False).returncode != 0:
            raise train_git.GitError(f'git push failed: {target} is not an ancestor of {commit}')
        self.forge.git('update-ref', target, commit)


class FakeClock:
    def __init__(self, start=datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc), step=timedelta(seconds=1)):
        self.moment, self.step = start, step

    def now(self):
        current = self.moment
        self.moment += self.step
        return current


class FakeForge(forge_events.MemoryAdapter):
    """The forge: event logs in memory, changes from the bare repository's branches pr-<n>."""

    def __init__(self, origin):
        super().__init__()
        self.origin = origin
        self.open, self.refuse, self.merges = [], set(), []
        self.locks, self.lock_calls = {}, []
        self.bodies = {}
        self.calls = Counter()  # forge reads by kind: each one a REST round trip on GitHub

    def read(self, channel):
        self.calls['read'] += 1
        return super().read(channel)

    def events_since(self, repo, since):
        """Every event of the repository at or after `since` (the queue index's capability, train_queue)."""
        self.calls['events_since'] += 1
        return [event for (owner, _), events in self.logs.items() if owner == repo for event in events
                if train_queue.moment(event['occurred_at']) >= train_queue.moment(since)]

    def git(self, *args, env=None):
        return subprocess.run(['git', '-C', str(self.origin), *args], capture_output=True, text=True, check=True,
                              env=dict(os.environ, **GIT_ENV, **(env or {}))).stdout.strip()

    def ref(self, name):
        """The sha a ref of the bare origin holds, read from its file as the forge would answer it (GATE-SPEED F3: a
        git process per forge read was most of the train tests' 18,600 git processes); a packed ref asks git."""
        try:
            held = (self.origin / name).read_text().strip()
        except OSError:
            held = ''
        return held if re.fullmatch(r'[0-9a-f]{40}', held) else self.git('rev-parse', name)

    def held(self, name):
        """The ref's sha, or None when the origin has no such ref."""
        try:
            return self.ref(name)
        except subprocess.CalledProcessError:
            return None

    def change(self, repo, number):
        self.calls['change'] += 1
        return {'head': self.ref(f'refs/heads/pr-{number}'), 'base': None,
                'body': self.bodies.get(number, ''), 'head_ref': f'pr-{number}', 'head_repo': None,
                'open': number in self.open, 'base_ref': engine_role.setting('train.base_branch')}

    def open_changes(self, repo, base):
        self.calls['open_changes'] += 1
        return list(self.open)

    def merge(self, repo, number, head_sha):
        """A merge commit of the PR head on the base branch, refused when the head moved (--match-head-commit)."""
        if number in self.refuse or self.change(repo, number)['head'] != head_sha:
            raise RuntimeError(f'#{number}: head is not {head_sha}')
        branch = f'refs/heads/{engine_role.setting("train.base_branch")}'
        tip = self.ref(branch)
        tree = self.git('merge-tree', '--write-tree', tip, head_sha).splitlines()[0]
        commit = self.git('commit-tree', tree, '-p', tip, '-p', head_sha, '-m', f'Merge #{number}')
        self.git('update-ref', branch, commit, tip)
        self.open.remove(number)
        self.merges.append(number)
        return commit


    def lock(self, repo, name, owner, now, expires):
        self.lock_calls.append(owner)
        held = self.locks.get(name)
        if held and held['owner'] != owner and held['expires'] > now:
            return False
        self.locks[name] = {'owner': owner, 'expires': expires}
        return True

    def unlock(self, repo, name, owner, died=None):
        if self.locks.get(name, {}).get('owner') == owner:
            del self.locks[name]
            if died:  # the reason a run that raised leaves on the release record (TRAIN-TEMP-FIX R1)
                self.deaths = getattr(self, 'deaths', []) + [(name, owner, died)]


class FakeGate:
    """Tier 2: red when the commit's tree holds a file named BREAK, or once for each commit in `flaky` (a test that
    fails then passes on the same content); records every commit it judged. `machine` is the (FAIL line, stage, class)
    of a red run whatever the content, from run index `machine_from` on (a broken machine, contradictory rules). Red
    results are read from the output's class line, as engine_role.CommandGate reads the real gate's."""

    def __init__(self, workspace):
        self.workspace, self.runs, self.flaky, self.machine, self.machine_from = workspace, [], set(), None, 0
        self.envs = []

    @staticmethod
    def red(fail, stage, kind, tests=()):
        log = f'{fail}\n{engine_role.setting("gate.class_line_prefix")} {stage}\t{kind}\n'
        read_stage, read_kind = engine_role.failed_stage(log)
        return train_git.Tier2Result(False, read_stage, log, tests, read_kind)

    def run(self, commit, env=None):
        self.runs.append(commit)
        self.envs.append(env)
        if commit in self.flaky:
            self.flaky.discard(commit)
            return self.red('FAIL unit tests', 'unit tests', 'code', ('src/flaky.test.ts',))
        if self.machine and len(self.runs) > self.machine_from:
            return self.red(*self.machine)
        files = self.workspace.git('ls-tree', '-r', '--name-only', commit).stdout.split()
        if 'BREAK' in files:
            return self.red('FAIL unit tests', 'unit tests', 'code')
        return train_git.Tier2Result(True, None, '')


class Fixture(unittest.TestCase):
    """A bare origin with the integration branch and one branch per PR, and a local clone for the train.

    GATE-SPEED F11 (N6): git is answered in memory (memory_git) unless a test's subject is git itself; such a class
    sets `memory = False` and gets real repositories."""

    memory = True

    def setUp(self):
        # Consumer unit tests inject local doubles; compatibility is exercised by test_forge_events.
        self.enterContext(mock.patch.object(forge_events, '_require_compatibility'))
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        # The train's tests judge the train as it is without the exception regime (D-260): the live registry may hold it on.
        self.enterContext(mock.patch.object(train.regime, 'lift', lambda *args, **kwargs: False))
        if self.memory:
            self.enterContext(memory_git.MemoryGit().intercept())
        os.environ.update(GIT_ENV)
        self.base_branch = engine_role.setting('train.base_branch')
        self.origin = self.dir / 'origin.git'
        self.run_git(self.dir, 'init', '--quiet', '--bare', str(self.origin))
        self.run_git(self.origin, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
        self.run_git(self.origin, 'symbolic-ref', 'HEAD', f'refs/heads/{self.base_branch}')
        self.run_git(self.origin, 'config', 'receive.autogc', 'false')  # a push into it starts no gc (F7)
        self.seed = self.dir / 'seed'
        self.run_git(self.dir, 'init', '--quiet', '-b', 'seed', str(self.seed))
        self.write({'README': 'base\n', 'a.txt': 'a\n', 'b.txt': 'b\n', **self.base_files()})
        self.base = self.commit('base')
        self.set_origin_ref(f'refs/heads/{self.base_branch}', self.base)
        self.work = self.dir / 'work'
        self.run_git(self.dir, 'clone', '--quiet', '--shared', str(self.origin), str(self.work))
        if not self.memory:  # in memory every repository reads one object store
            with (self.origin / 'objects' / 'info' / 'alternates').open('a') as alternates:
                alternates.write(f'{self.work / ".git" / "objects"}\n')  # the train's commits, seen by the forge
        self.forge = FakeForge(self.origin)
        self.clock = FakeClock()
        self.workspace = FixtureWorkspace(self.work, self.forge)
        self.gate = FakeGate(self.workspace)
        self.train = train.Train(self.forge, self.clock, self.workspace, self.gate, REPO)
        self.gate_port = forge_events.ForgeEvents(self.forge, self.clock, 'gate_report', 'run-1')
        self.lane_port = forge_events.ForgeEvents(self.forge, self.clock, 'pr-ready', 'lane-1')

    def base_files(self):
        return {}

    def set_origin_ref(self, ref, commit):
        """Point the origin's ref at a commit of the seed, as a push would (GATE-SPEED F7): the origin reads the seed's
        objects in place (objects/info/alternates), so no transport runs; a local push is seven processes."""
        alternates = self.origin / 'objects' / 'info' / 'alternates'
        if not self.memory and not alternates.exists():
            alternates.write_text(f'{self.seed / ".git" / "objects"}\n')
        self.run_git(self.origin, 'update-ref', ref, commit)

    def run_git(self, where, *args):
        return subprocess.run(['git', '-C', str(where), *args], capture_output=True, text=True, check=True,
                              env=dict(os.environ, **GIT_ENV)).stdout.strip()

    def write(self, files):
        """Write each file; a None text deletes it (D-112: a change that retires a unit)."""
        for name, text in files.items():
            if text is None:
                (self.seed / name).unlink()
                continue
            (self.seed / name).parent.mkdir(parents=True, exist_ok=True)
            (self.seed / name).write_text(text)

    def commit(self, message):
        self.run_git(self.seed, 'add', '-A')
        self.run_git(self.seed, 'commit', '--quiet', '-m', message)
        return self.run_git(self.seed, 'rev-parse', 'HEAD')

    def pr(self, number, files, ready=True, gate=True, unit=None):
        """Branch pr-<number> from the base with `files`, pushed; gate.passed and pr.ready on its log."""
        self.run_git(self.seed, 'checkout', '--quiet', '-B', f'pr-{number}', self.base)
        self.write(files)
        head = self.commit(f'pr {number}')
        self.set_origin_ref(f'refs/heads/pr-{number}', head)
        self.forge.open.append(number)
        if gate:
            self.passed(number, head)
        if ready:
            self.ready(number, head, unit=unit)
        return head

    def make(self, *specs, ready=True):
        """One PR per spec (its files, or (files, unit)), numbered after every PR the forge has seen; never a number
        written in a test, so a test names PRs by what they are (LT1)."""
        made = []
        for spec in specs:
            files, unit = spec if isinstance(spec, tuple) else (spec, None)
            number = max(self.forge.open + self.forge.merges + [made[-1].number if made else 0], default=0) + 1
            made.append(Made(number, self.pr(number, files, ready=ready, unit=unit)))
        return made

    def passed(self, number, head):
        payload = forge_events.subject(REPO, number, head, ['P-02'])
        payload.update({'tier': 1, 'plan': 'dev', 'missing_stages': [], 'input_hash': 'd' * 64, 'stages': []})
        return self.gate_port.emit('gate.passed', payload)

    def ready(self, number, head, evidence=None, unit=None):
        if evidence is None:
            evidence = [e for e in self.gate_port.read(REPO, number) if e['type'] == 'gate.passed'][-1]['event_id']
        payload = dict(forge_events.subject(REPO, number, head, ['P-02'], unit), lane_id=None, evidence=evidence)
        return self.lane_port.emit('pr.ready', payload)

    def events(self, pr=None, kind=None):
        found = forge_events.ForgeEvents(self.forge, self.clock, 'reader', 'test').read(REPO, pr)
        return [event for event in found if kind is None or event['type'] == kind]


class GreenRuns(Fixture):
    """Flake evidence comes from the newest window of the repository log, never the whole channel (#548 outgrew it)."""

    def measured_green(self, sha):
        port = forge_events.ForgeEvents(self.forge, self.clock, 'train', 'run-1')
        with forge_events.measured(port, self.train.step_prefix + 'tier2', forge_events.subject(REPO, None, sha, [], None)):
            pass

    def test_green_runs_read_only_the_newest_window(self):
        old = self.base
        self.write({'c.txt': 'c\n'})
        new = self.commit('second green')
        self.measured_green(old)
        self.measured_green(new)
        newest = self.forge.read(forge_events.Channel(REPO, None))[-1:]
        windows = []
        self.forge.recent = lambda channel: windows.append(channel) or (newest, False)
        self.forge.read = lambda channel: self.fail('green_runs read the whole channel')
        port = forge_events.ForgeEvents(self.forge, self.clock, 'train', 'run-2')
        self.assertEqual([run.sha for run in self.train.green_runs(port)], [new])
        self.assertEqual(windows, [forge_events.Channel(REPO, None)])


class Registry(unittest.TestCase):
    def test_every_train_entry_is_typed_documented_and_read(self):
        document = config.files(ROOT)['train'][1]
        self.assertEqual(document['x-owner'], 'train')
        for name, item in document['properties'].items():
            with self.subTest(name=name):
                self.assertTrue(name.startswith('train.'))
                self.assertTrue(item['description'].strip() and item['x-unit'] and item['x-readers'])
                self.assertTrue(all((ROOT / reader).is_file() for reader in item['x-readers']))


class BaseHold(Fixture):
    """Unit R1 (docs/units/R1/plan.md): a red real result of the base tip holds the queue while train.base_hold is on.
    Green, unknown and released tips run, and a switch that is off never holds."""

    def shadow(self, passed, failing=(), claimed=None):
        tip = self.workspace.tip(self.base_branch)
        path = train_base_gate.result_path(self.workspace.root, tip)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'sha': claimed or tip, 'passed': passed, 'failing': list(failing)}), encoding='utf-8')
        return tip

    def test_a_red_result_of_the_base_tip_holds_the_queue_while_the_switch_is_on(self):
        self.train.base_hold = True
        self.shadow(False, ['script tests'])
        self.assertTrue(self.train.base_held())

    def test_a_green_result_runs(self):
        self.train.base_hold = True
        self.shadow(True)
        self.assertFalse(self.train.base_held())

    def test_no_result_is_unknown_and_runs(self):
        self.train.base_hold = True
        self.assertFalse(self.train.base_held())

    def test_a_result_that_names_another_sha_is_unknown_and_runs(self):
        self.train.base_hold = True
        self.shadow(False, ['script tests'], claimed='0' * 40)
        self.assertFalse(self.train.base_held())

    def test_a_released_tip_runs(self):
        self.train.base_hold = True
        tip = self.shadow(False, ['script tests'])
        self.train.base_release = tip
        self.assertFalse(self.train.base_held())

    def test_the_switch_off_never_holds(self):
        self.train.base_hold = False
        self.shadow(False, ['script tests'])
        self.assertFalse(self.train.base_held())


if __name__ == '__main__':
    unittest.main()
