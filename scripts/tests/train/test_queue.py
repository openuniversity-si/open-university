"""The merge train v0 (plan v3 M3): queue (TX24: one file per feature; fixtures in scripts/tests/test_train.py)."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import FakeClock, FakeForge, Fixture, READS_PER_PR, REPO, setUpModule  # noqa: E402,F401
import engine_role  # noqa: E402
import forge_events  # noqa: E402
import train  # noqa: E402


class Queue(Fixture):
    def test_fifo_by_ready_and_only_exact_heads_with_a_passed_gate(self):
        first = self.pr(3, {'c.txt': 'c\n'})
        self.pr(1, {'d.txt': 'd\n'}, ready=False)
        second = self.pr(2, {'e.txt': 'e\n'})
        self.assertEqual([(e.pr, e.sha) for e in self.train.queue()], [(3, first), (2, second)])

    def test_a_push_after_ready_leaves_the_queue(self):
        self.pr(4, {'c.txt': 'c\n'})
        self.run_git(self.seed, 'checkout', '--quiet', 'pr-4')
        self.write({'c.txt': 'c2\n'})
        self.commit('push after ready')
        self.run_git(self.seed, 'push', '--quiet', str(self.origin), 'HEAD:refs/heads/pr-4')
        self.assertEqual(self.train.queue(), [])

    def test_ready_without_the_gate_it_names_is_not_queued(self):
        head = self.pr(5, {'c.txt': 'c\n'}, ready=False, gate=False)
        self.ready(5, head, evidence='e' * 64)
        self.assertEqual(self.train.queue(), [])

    def test_out_of_queue_events_for_the_head_remove_it(self):
        head = self.pr(6, {'c.txt': 'c\n'})
        port = self.train.port('b-test')
        port.emit('pr.conflicted', dict(forge_events.subject(REPO, 6, head, ['P-02']), files=['c.txt'],
                                        tip_sha=self.base, cause='textual', detail='c.txt conflicts'))
        self.assertEqual(self.train.queue(), [])

    def test_the_queue_is_rebuilt_from_the_log_alone(self):
        self.pr(7, {'c.txt': 'c\n'})
        replica = forge_events.MemoryAdapter()
        replica.logs = {key: list(value) for key, value in self.forge.logs.items()}
        rebuilt = FakeForge(self.origin)
        rebuilt.logs, rebuilt.open = replica.logs, list(self.forge.open)
        again = train.Train(rebuilt, FakeClock(), self.workspace, self.gate, REPO)
        self.assertEqual(again.queue(), self.train.queue())


class QueueIndex(Fixture):
    """GX-30, G-09/G-10: after the first build of a run, a queue build reads only the PRs with new events."""

    def waiting(self, count):
        return self.make(*[{f'w{index}.txt': 'x\n'} for index in range(count)], ready=False)

    def test_a_rebuild_costs_two_reads_plus_two_per_new_ready_pr(self):
        waiting = self.waiting(engine_role.setting('train.batch_size'))
        queued = self.make({'q.txt': 'x\n'})
        self.forge.calls.clear()
        self.assertEqual([e.pr for e in self.train.queue()], [pr.number for pr in queued])
        opened = len(waiting) + len(queued)
        self.assertEqual(sum(self.forge.calls.values()), 1 + len(READS_PER_PR) * opened, 'the first build replays all')
        late = self.make({'n.txt': 'x\n'})
        self.forge.calls.clear()
        self.assertEqual([e.pr for e in self.train.queue()], [pr.number for pr in queued + late])
        self.assertEqual(dict(self.forge.calls), dict.fromkeys(('open_changes', 'events_since', *READS_PER_PR), len(late)))
        self.assertEqual(self.train.index.last_build, 'since')
        self.forge.calls.clear()
        self.train.queue()
        self.assertEqual(dict(self.forge.calls), {'open_changes': 1, 'events_since': 1}, 'nothing new: no PR is read')

    def test_new_events_on_known_prs_update_the_index(self):
        first, second = self.make({'a.txt': 'x\n'}, {'b.txt': 'x\n'})
        third, fourth = self.make({'c.txt': 'x\n'}, {'d.txt': 'x\n'}, ready=False)
        self.train.queue()
        self.ready(third.number, third.head)
        port = self.train.port('b-test')
        port.emit('pr.conflicted', dict(forge_events.subject(REPO, first.number, first.head, ['P-02']), files=[],
                                        tip_sha=self.base, cause='forge-refused', detail='head moved'))
        self.forge.open.remove(fourth.number)
        self.assertEqual([e.pr for e in self.train.queue()], [second.number, third.number])

    def test_the_index_equals_the_full_replay_after_a_batch(self):
        *batch, kept = self.make({'a.txt': 'x\n'}, {'b.txt': 'x\n'}, {'c.txt': 'x\n'})
        self.waiting(len(batch))
        self.train.run_batch(self.train.queue()[:len(batch)])
        [late] = self.make({'n.txt': 'x\n'})
        indexed = self.train.queue()
        replay = train.Train(self.forge, FakeClock(), self.workspace, self.gate, REPO).queue()
        self.assertEqual(indexed, replay)
        self.assertEqual([e.pr for e in indexed], [kept.number, late.number])

    def test_without_the_switch_or_the_capability_every_build_is_the_full_replay(self):
        opened = self.make({'a.txt': 'x\n'}) + self.waiting(len(READS_PER_PR))
        self.train.index.incremental = False
        for _ in ('first build', 'rebuild'):
            self.forge.calls.clear()
            self.train.queue()
            self.assertEqual(sum(self.forge.calls.values()), 1 + len(READS_PER_PR) * len(opened))
        self.assertTrue(engine_role.setting('train.queue_since_last_batch'))
        plain = forge_events.MemoryAdapter()
        self.assertIsNone(getattr(plain, 'events_since', None), 'GitHub and memory adapters fall back to the replay')


class RunOne(Fixture):
    """GATE-ON-PUSH R3: `scripts/train run --pr <n>` is one wake: that PR's log and head, nothing else."""

    def test_the_queue_is_one_log_and_one_head(self):
        first, second, third = self.make({'a.txt': 'x\n'}, {'b.txt': 'x\n'}, {'c.txt': 'x\n'})
        self.train.only = second.number
        self.forge.calls.clear()
        self.assertEqual([(e.pr, e.sha) for e in self.train.queue()], [(second.number, second.head)])
        self.assertEqual(dict(self.forge.calls), dict.fromkeys(READS_PER_PR, 1), 'no open_changes, no other PR')

    def test_a_pr_not_waiting_or_not_open_on_the_base_is_an_empty_queue(self):
        ready, waiting = self.make({'a.txt': 'x\n'}) + self.make({'b.txt': 'x\n'}, ready=False)
        for number in (waiting.number, ready.number):
            with self.subTest(pr=number):
                self.train.only = number
                if number == ready.number:
                    self.forge.open.remove(number)  # closed with its pr.ready still live
                self.assertEqual(self.train.queue(), [])
        self.train.only = waiting.number
        self.forge.change = lambda repo, number: dict(FakeForge.change(self.forge, repo, number), base_ref='main')
        self.ready(waiting.number, waiting.head)
        self.assertEqual(self.train.queue(), [], 'a PR on another base is not this train\'s')

    def test_the_run_merges_that_pr_only_never_bootstraps_and_does_not_look_again(self):
        first, second = self.make({'a.txt': 'x\n'}, {'b.txt': 'x\n'})
        self.train.only = second.number
        self.train.bootstrap = lambda port: self.fail('run --pr never bootstraps')
        self.assertEqual(self.train.run('role-1'), 'drained')
        self.assertEqual(self.forge.merges, [second.number])
        self.assertFalse(self.train.pending(), 'the look after the release is the sweep\'s')
        self.train.only = None
        self.assertEqual([e.pr for e in self.train.queue()], [first.number], 'the sweep still takes the rest')

    def test_the_command_passes_the_pr_to_the_role(self):
        [made], seen = self.make({'a.txt': 'x\n'}), {}

        class Role:
            only = None

            def run(self, owner):
                seen.update(only=self.only, owner=owner)
                return 'drained'
        with mock.patch.object(train, 'from_config', Role), mock.patch.object(train, 'local_override', lambda: None):
            self.assertEqual(train.main(['run', '--pr', str(made.number), '--owner', 'role-1']), 0)
        self.assertEqual(seen, {'only': made.number, 'owner': 'role-1'})


if __name__ == '__main__':
    unittest.main()
