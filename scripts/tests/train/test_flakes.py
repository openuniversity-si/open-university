"""The merge train v0 (plan v3 M3): flakes (TX24: one file per feature; fixtures in scripts/tests/test_train.py)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, setUpModule  # noqa: E402,F401
import engine_role  # noqa: E402


class FlakesBase(Fixture):
    """A red verdict that rests on a proven flake (a red run on a sha with a green run) ejects nobody (M7)."""

    def first_batch(self):
        """Batch [1, 2, 3, 4] where 4 is the culprit: the probes 1+2 and 1+2+3 pass and stay in the log. The proven
        prefix stays queued (train.merge_proven_prefix off), so the next batch rebuilds the same content."""
        self.train.merge_proven_prefix = False
        for number in range(1, 5):
            self.pr(number, {f'f{number}.txt': 'x\n', **({'BREAK': 'x\n'} if number == 4 else {})})
        self.train.run_batch(self.train.queue())
        self.assertEqual(len(self.events(4, 'pr.ejected')), 1)
        self.assertEqual(self.events(None, 'test.flaked'), [], 'red without same-sha evidence is not a flake')
        self.train.merge_proven_prefix = True
        return self.gate.runs[1], self.gate.runs[2]

    def ejected(self):
        return sum(len(self.events(n, 'pr.ejected')) for n in range(1, 6))

    def batch_results(self):
        return [e['payload']['result'] for e in self.events(None, 'engine.step.measured')
                if e['payload']['step'] == engine_role.setting('train.step_prefix') + 'batch']

    def flaky_combined_head(self, members):
        """Batch of `members` clean PRs whose combined head fails once, on its first tier-2 run (the fake gate's
        flaky set is filled with the first commit it judges), and passes after: every shorter prefix passes."""
        for number in range(1, members + 1):
            self.pr(number, {f'f{number}.txt': 'x\n'})
        run = self.gate.run

        def first_red(commit, env=None):
            if not self.gate.runs:
                self.gate.flaky.add(commit)
            return run(commit, env)
        self.gate.run = first_red


class Flakes(FlakesBase):
    """A red verdict that rests on a proven flake (a red run on a sha with a green run) ejects nobody (M7)."""

    def test_a_red_combined_head_that_passed_before_is_a_flake(self):
        _, prefix123 = self.first_batch()
        self.gate.flaky.add(prefix123)
        runs = len(self.gate.runs)
        self.assertEqual(self.train.run_batch(self.train.queue()), [])
        self.assertEqual(self.gate.runs[runs:], [prefix123], 'the same sha as before, one run, no bisection')
        self.assertEqual(self.ejected(), 1, 'only the real culprit of the first batch')
        [flaked] = self.events(None, 'test.flaked')
        [opened] = self.events(None, 'test.quarantined')
        self.assertEqual((flaked['payload']['sha'], flaked['payload']['test']), (prefix123, 'src/flaky.test.ts'))
        self.assertEqual(opened['payload']['owner'], engine_role.setting('quarantine.unknown_owner'))
        self.assertEqual(self.batch_results()[-1], 'blocked')
        self.assertEqual([e.pr for e in self.train.queue()], [1, 2, 3], 'every member stays queued')
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1, 2, 3])

    def test_a_flaky_bisection_probe_stops_the_bisection_and_ejects_nobody(self):
        prefix12, _ = self.first_batch()
        self.pr(5, {'BREAK': 'x\n', 'f5.txt': 'x\n'})
        self.gate.flaky.add(prefix12)
        runs = len(self.gate.runs)
        self.assertEqual(self.train.run_batch(self.train.queue()), [])
        self.assertEqual(self.gate.runs[runs + 1:], [prefix12], 'the bisection stops at the flaky probe')
        self.assertEqual(self.ejected(), 1, 'neither 1 nor 2 is blamed for the flake')
        self.assertEqual(len(self.events(None, 'test.quarantined')), 1)
        self.assertEqual([e.pr for e in self.train.queue()], [1, 2, 3, 5])

    def test_the_role_stops_on_a_flake_and_never_reruns_in_the_same_invocation(self):
        _, prefix123 = self.first_batch()
        self.gate.flaky.add(prefix123)
        runs = len(self.gate.runs)
        self.assertEqual(self.train.run('role-1'), 'flaked')
        self.assertEqual(len(self.gate.runs), runs + 1)
        self.assertEqual(self.events(None, 'train.queue.empty'), [])
        self.assertEqual(self.forge.locks, {}, 'the lock is released')
        self.assertEqual(self.train.run('role-1'), 'drained', 'the next event runs the batch again')
        self.assertEqual(self.forge.merges, [1, 2, 3])
        self.assertEqual(len(self.events(None, 'test.quarantined')), 1, 'the quarantine stays open and blocking')




if __name__ == '__main__':
    unittest.main()
