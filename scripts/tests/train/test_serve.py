"""GATE-ON-PUSH R2 (plan commit 5): `scripts/train serve` waits on train.wake_ref and runs one admission per wake, a
sweep at start and per interval, and exits at train.serve_max_s. Fake refs, clock and runs; the refresh on a local bare
repository. No network."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import setUpModule  # noqa: E402,F401
import engine_role  # noqa: E402
import forge_git_ref  # noqa: E402
import train  # noqa: E402
import train_serve  # noqa: E402

NAME = engine_role.setting('train.wake_ref')
POLL, SWEEP, MAX = (engine_role.setting(name) for name in ('train.wake_poll_s', 'train.sweep_interval_s',
                                                            'train.serve_max_s'))
PR = 1  # the first PR a wake names


class FakeRefs:
    """train.wake_ref as a list of (sha, record); counts tip and log reads. `fail` tip reads raise first."""

    def __init__(self, fail=0):
        self.records, self.tips, self.logs, self.fail = [], 0, 0, fail

    def wake(self, pr):
        self.records.append((f'wake-{len(self.records)}', {'pr': pr, 'sha': f'head-{pr}', 'event_id': f'event-{pr}'}))

    def tip(self, name):
        self.tips += 1
        if self.fail:
            self.fail -= 1
            raise forge_git_ref.GitRefError('ls-remote failed')
        return self.records[-1][0] if self.records else None

    def log(self, name, since):
        self.logs += 1
        shas = [sha for sha, _ in self.records]
        return self.records[shas.index(since) + 1:] if since in shas else list(self.records)


class Harness:
    """A Serve whose sleep advances the clock and fires the wakes scheduled at or before the new time."""

    def __init__(self, refs, max_s=MAX, wakes=()):
        self.now, self.runs, self.lines, self.refs = 0, [], [], refs
        self.wakes = sorted(wakes)  # [(at seconds, pr)]
        self.serve = train_serve.Serve(refs, self.runs.append, NAME, POLL, SWEEP, max_s, clock=lambda: self.now,
                                       sleep=self.sleep, out=self.lines.append)

    def sleep(self, seconds):
        self.now += seconds
        while self.wakes and self.wakes[0][0] <= self.now:
            self.refs.wake(self.wakes.pop(0)[1])

    def prs(self):
        return [pr for pr in self.runs if pr is not None]

    def sweeps(self):
        return self.runs.count(None)


class Serve(unittest.TestCase):
    def test_a_wake_runs_one_run_pr_and_a_pr_woken_twice_runs_once(self):
        refs = FakeRefs()
        harness = Harness(refs, max_s=SWEEP, wakes=[(POLL, PR), (POLL, PR + 1), (POLL, PR)])
        harness.serve.serve()
        self.assertEqual(harness.prs(), [PR, PR + 1])
        self.assertEqual(refs.logs, 1, 'one log read for the moved tip')

    def test_wakes_before_start_are_left_to_the_starting_sweep(self):
        refs = FakeRefs()
        refs.wake(PR)
        harness = Harness(refs, max_s=SWEEP)
        harness.serve.serve()
        self.assertEqual(harness.runs, [None], 'the sweep at start covers the old wake; no run --pr for it')
        self.assertEqual(refs.logs, 0)

    def test_no_wake_and_no_sweep_due_costs_no_log_read_and_no_run(self):
        refs = FakeRefs()
        harness = Harness(refs, max_s=SWEEP)
        harness.serve.serve()
        self.assertEqual(harness.runs, [None], 'only the starting sweep')
        self.assertEqual(refs.logs, 0)
        self.assertEqual(refs.tips, 1 + SWEEP // POLL, 'one ls-remote at start and one per poll')

    def test_the_sweep_runs_at_start_and_once_per_interval(self):
        harness = Harness(FakeRefs())
        harness.serve.serve()
        self.assertEqual(harness.runs[0], None, 'a sweep at start')
        self.assertGreaterEqual(harness.sweeps(), MAX // SWEEP)
        self.assertLessEqual(harness.sweeps(), 1 + MAX // SWEEP)

    def test_serve_exits_at_serve_max_s_and_asks_to_be_started_again(self):
        harness = Harness(FakeRefs(), wakes=[(POLL, PR)])
        line = harness.serve.serve()
        self.assertEqual(harness.now, MAX)
        self.assertIn('served 1 wake(s)', line)
        self.assertIn('start `scripts/train serve` again', line)

    def test_a_failed_wait_is_printed_and_retried(self):
        refs = FakeRefs(fail=1 + 1)  # the start read and the first poll
        harness = Harness(refs, max_s=SWEEP, wakes=[(POLL, PR)])
        harness.serve.serve()
        self.assertEqual(harness.runs, [None, PR], 'the wake is still served on the next poll')
        self.assertTrue(harness.lines and 'not read (ls-remote failed)' in harness.lines[0])

    def test_the_cli_dispatches_serve_without_building_the_train(self):
        with mock.patch.object(train_serve, 'main', return_value=0) as serve, \
                mock.patch.object(train, 'from_config', side_effect=AssertionError('serve builds no train')):
            self.assertEqual(train.main(['serve']), 0)
        serve.assert_called_once_with()


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, input='', capture_output=True, text=True, check=True).stdout.strip()


class Refresh(unittest.TestCase):
    """Before each run the checkout on train.base_branch is fast-forwarded to the remote tip; any other branch is left."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.base = engine_role.setting('train.base_branch')
        git('init', '-q', '--bare', 'remote.git', cwd=self.root)
        for name in ('writer', 'train'):
            git('init', '-q', name, cwd=self.root)
            git('remote', 'add', engine_role.setting('train.git_remote'), str(self.root / 'remote.git'),
                cwd=self.root / name)
        self.commit('first')
        git('fetch', '-q', engine_role.setting('train.git_remote'), cwd=self.root / 'train')
        git('checkout', '-q', '-b', self.base, 'FETCH_HEAD', cwd=self.root / 'train')

    def commit(self, message):
        writer = self.root / 'writer'
        git('-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-q', '--allow-empty', '-m', message,
            cwd=writer)
        git('push', '-q', engine_role.setting('train.git_remote'), f'HEAD:refs/heads/{self.base}', cwd=writer)
        return git('rev-parse', 'HEAD', cwd=writer)

    def test_the_base_checkout_is_fast_forwarded_to_the_remote_tip(self):
        tip = self.commit('second')
        self.assertIsNone(train_serve.refresh(self.root / 'train'))
        self.assertEqual(git('rev-parse', 'HEAD', cwd=self.root / 'train'), tip)

    def test_another_branch_is_not_refreshed(self):
        git('checkout', '-q', '-b', 'other', cwd=self.root / 'train')
        before = git('rev-parse', 'HEAD', cwd=self.root / 'train')
        self.commit('second')
        self.assertIn('not refreshed', train_serve.refresh(self.root / 'train'))
        self.assertEqual(git('rev-parse', 'HEAD', cwd=self.root / 'train'), before)


if __name__ == '__main__':
    unittest.main()
