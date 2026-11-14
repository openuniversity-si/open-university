"""The merge train v0 (plan v3 M3): flakes, the recheck of a flaky tail (split from test_flakes.py, F117)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, setUpModule  # noqa: E402,F401
import engine_role  # noqa: E402
import quarantine  # noqa: E402
import train  # noqa: E402
from test_flakes import FlakesBase  # noqa: E402


class FlakesRecheck(FlakesBase):
    """A red verdict that rests on a proven flake (a red run on a sha with a green run) ejects nobody (M7)."""

    def test_the_stabilizing_pr_ends_the_quarantine_when_it_merges(self):
        _, prefix123 = self.first_batch()
        self.gate.flaky.add(prefix123)
        self.train.run_batch(self.train.queue())
        self.forge.bodies[6] = 'Fixes the race.\nStabilizes: src/flaky.test.ts\n'
        self.pr(6, {'src/flaky.test.ts': 'stable\n'})
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1, 2, 3, 6])
        [opened] = self.events(None, 'test.quarantined')
        [ended] = self.events(None, 'test.unquarantined')
        [merged] = self.events(6, 'pr.merged')
        self.assertEqual((ended['payload']['stabilizing_pr'], ended['payload']['quarantined_event']),
                         (6, opened['event_id']))
        self.assertEqual(ended['payload']['sha'], merged['payload']['merge_sha'])
        self.assertEqual(quarantine.state(self.events(None)), {})

    def test_a_flake_on_the_last_prefix_is_rechecked_and_ejects_nobody(self):
        """D-297, case 1 of F70: the combined head is red, its shorter prefixes all pass, so the bisection names the
        last member. Before the ejection the culprit's prefix (its head on the proven prefix) runs once more; green
        there makes the red a proven flake: quarantine, and every member stays queued."""
        self.flaky_combined_head(3)
        self.assertEqual(self.train.run_batch(self.train.queue()), [])
        head = self.gate.runs[0]
        self.assertEqual(self.gate.runs[-1], head, 'the recheck runs the culprit prefix, the combined head here')
        self.assertEqual(len(self.gate.runs), 3, 'tier 2, the green probe of 1+2, the recheck')
        self.assertEqual(self.gate.envs[-1], self.gate.envs[0], 'the same plan: its base and the members it holds')
        self.assertEqual(self.ejected(), 0, 'the last member is not blamed for the flake')
        [flaked] = self.events(None, 'test.flaked')
        self.assertEqual((flaked['payload']['sha'], flaked['payload']['test']), (head, 'src/flaky.test.ts'))
        self.assertEqual(len(self.events(None, 'test.quarantined')), 1)
        self.assertEqual(self.batch_results()[-1], 'blocked')
        recheck = [e for e in self.events(None, 'engine.step.measured')
                   if e['payload']['step'] == engine_role.setting('train.step_prefix') + 'recheck']
        self.assertEqual([(e['payload']['sha'], e['payload']['result']) for e in recheck], [(head, 'ok')])
        self.assertEqual([e.pr for e in self.train.queue()], [1, 2, 3], 'every member stays queued')
        runs = len(self.gate.runs)
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1, 2, 3])
        self.assertEqual(len(self.gate.runs), runs + 1, 'the next batch runs the same content once and merges it')

    def test_the_recheck_reruns_a_test_an_earlier_member_changed(self):
        """D-297, case 2 of F70: member 1 changes a test, member 3 is the named culprit of a flake. The recheck gets the
        culprit's whole prefix (base plus the heads of 1, 2 and 3), so the union plan holds member 1's changed test and
        runs it again: a flake there is not blamed on a later PR, and no member is ejected."""
        heads = [pr.head for pr in self.make({'src/changed.test.ts': 'x\n'}, {'f2.txt': 'x\n'}, {'f3.txt': 'x\n'})]
        run = self.gate.run

        def first_red(commit, env=None):
            if not self.gate.runs:
                self.gate.flaky.add(commit)
            return run(commit, env)
        self.gate.run = first_red
        self.assertEqual(self.train.run_batch(self.train.queue()), [])
        self.assertEqual(self.gate.runs[-1], self.gate.runs[0], 'the recheck runs the culprit prefix')
        recheck = self.gate.envs[-1]
        self.assertEqual(recheck[train.BATCH_MEMBERS_ENV].split(), heads, 'the changed test rides in the plan')
        self.assertEqual(recheck[train.BATCH_BASE_ENV], self.base)
        self.assertEqual(self.ejected(), 0)

    def test_a_red_recheck_still_ejects_the_culprit(self):
        """A culprit whose prefix is red again on the recheck leaves with pr.ejected, as before (D-297)."""
        self.pr(1, {'f1.txt': 'x\n'})
        self.pr(2, {'BREAK': 'x\n'})
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1])
        self.assertEqual(self.gate.runs[-1], self.gate.runs[0], 'the recheck ran the culprit prefix')
        self.assertEqual(len(self.events(2, 'pr.ejected')), 1)
        self.assertEqual(self.events(None, 'test.flaked'), [])

    def test_the_merge_reads_only_the_newest_window_of_the_repository_log(self):
        """A channel past forge-events.github_max_pages (#548): a batch reads the window, never the whole repository
        log, and the stabilizing PR still releases the quarantine the window holds."""
        run_batch, read, windows = self.train.run_batch, self.forge.read, []

        def whole(channel):
            if channel.pr is None:
                self.fail('a batch read the whole repository channel')
            return read(channel)

        def guarded(queue):
            self.forge.read = whole
            try:
                return run_batch(queue)
            finally:
                self.forge.read = read

        self.train.run_batch = guarded
        self.forge.recent = lambda channel: windows.append(channel) or (read(channel), False)
        self.test_the_stabilizing_pr_ends_the_quarantine_when_it_merges()
        self.assertTrue(windows)
        self.assertEqual(len(self.events(None, 'integration.advanced')), 1)


if __name__ == '__main__':
    unittest.main()
