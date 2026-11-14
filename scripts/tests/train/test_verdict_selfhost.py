"""Verdict admission: reverdicts ahead and self-hosting gate changes (split from test_verdict.py, F117: the file was the slowest of the train suite).
"""
import contextlib
import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import REPO, Fixture, setUpModule  # noqa: E402,F401
from test_verdict import FakeReverdict, FakeSelfHost, Verdict, PASSED, FAILED, ROOT  # noqa: E402,F401
import train  # noqa: E402
import train_verdict  # noqa: E402


class Ahead(Verdict):
    """D-076 (GATE-FAST): the resync of the oldest PR runs the verdicts of the next behind-the-tip PRs beside it;
    admission stays one PR at a time from the queue."""

    def setUp(self):
        super().setUp()
        self.use(**dict(self.settings, **{'train.reverdict_parallel': len(('oldest', 'ahead'))}))

    def test_two_behind_prs_are_reverdicted_in_one_round_and_merge_in_queue_order(self):
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, _ = self.verdict_pr({'d.txt': 'two\n'})
        third, _ = self.verdict_pr({'e.txt': 'three\n'})
        outcome, printed = self.drain()
        self.assertEqual((outcome, self.forge.merges, self.gate.runs), ('drained', [first, second, third], []))
        rounds = [pr for pr, _head in self.gate_api.calls]
        self.assertEqual(rounds[:len((second, third))], [second, third], 'the first round judges #2 and, ahead, #3')
        self.assertIn(f'#{third} verdict PASSED ahead', printed)
        self.assertEqual(self.events(third, 'pr.conflicted'), [], 'a speculative verdict never hands a PR back')

    def test_a_red_verdict_ahead_goes_back_to_its_owner_early(self):
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, _ = self.verdict_pr({'d.txt': 'two\n'})
        third, _ = self.verdict_pr({'e.txt': 'three\n'})
        self.gate_api.answers[third] = FAILED
        self.drain()
        [ejected] = self.events(third, 'pr.ejected')
        self.assertEqual(ejected['payload']['cause'], 'culprit')
        self.assertEqual(self.forge.merges, [first, second])

    def test_an_unobservable_verdict_ahead_leaves_the_pr_queued_without_a_halt(self):
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, _ = self.verdict_pr({'d.txt': 'two\n'})
        third, _ = self.verdict_pr({'e.txt': 'three\n'})
        self.gate_api.answers[third] = None
        printed = io.StringIO()
        with self.assertRaisesRegex(train.TrainHalt, f're-verdict of #{third}'), contextlib.redirect_stdout(printed):
            self.train.drain(self.train.port('test'))  # #3's own turn halts, as any UNOBSERVABLE re-verdict does
        self.assertIn(f'#{third} verdict ahead', printed.getvalue())
        self.assertIn(f'#{second} re-verdict PASSED', printed.getvalue(), 'the verdict ahead did not stop #2')
        self.assertEqual((self.events(third, 'pr.ejected'), self.events(third, 'pr.conflicted')), ([], []))


class SelfHosting(Verdict):
    """D-079 (TRAIN-ADMIT-GATE-CHANGE, #804 29/10 20:38Z): a PR that changes the toolchain set brings its own
    toolchain_id; the train admits it on the dual verdict (the pinned gate's cold gate.passed on the tip and the head's
    own toolchain on the same head), never on one leg."""
    settings = dict(Verdict.settings, **{'train.verdict_fallback': 'tier2'})
    GATE_CHANGE = {'scripts/lib/gate_example.py': 'FAST = True\n'}

    def foreign_pr(self, files):
        return self.verdict_pr(files, toolchain='the-head-own-toolchain')

    def test_a_gate_changing_pr_is_admitted_on_dual_green(self):
        number, head = self.foreign_pr(self.GATE_CHANGE)
        outcome, printed = self.drain()
        self.assertEqual(outcome, 'drained')
        self.assertEqual((self.forge.merges, self.gate.runs, self.gate_api.calls), ([number], [], []))
        self.assertEqual(self.head_leg.calls, [head])
        self.assertTrue(self.batch_ids('pr.merged')[0].startswith(train_verdict.VERDICT))
        self.assertEqual(self.measured('self-host'), ['ok'])
        self.assertIn('self-host', printed)

    def test_a_red_head_toolchain_is_refused_and_takes_the_fallback(self):
        self.head_leg.passed = False
        number, _ = self.foreign_pr(self.GATE_CHANGE)
        _, printed = self.drain()
        self.assertIn('dual verdict', printed)
        self.assertEqual(self.measured('self-host'), ['fail'])
        self.assertEqual(len(self.gate.runs), 1)  # the tier-2 batch of one, never the verdict merge
        self.assertFalse(any(bid.startswith(train_verdict.VERDICT) for bid in self.batch_ids('pr.merged')))

    def test_under_requeue_a_red_head_toolchain_goes_back_to_the_owner_and_never_halts(self):
        self.use(**dict(self.settings, **{'train.verdict_fallback': 'requeue'}))
        self.head_leg.passed = False
        number, head = self.foreign_pr(self.GATE_CHANGE)
        outcome, printed = self.drain()
        self.assertEqual(outcome, 'drained')
        [ejected] = self.events(number, 'pr.ejected')
        self.assertEqual((ejected['payload']['stage'], ejected['payload']['cause'], ejected['payload']['sha']),
                         ('self-host', 'culprit', head))
        self.assertEqual((self.forge.merges, self.gate.runs, self.gate_api.calls, self.head_leg.calls),
                         ([], [], [], [head]))
        self.assertIn('handed back to its owner', printed)

    def test_a_red_head_toolchain_ejection_carries_the_tail_of_its_whole_output(self):
        """D-082: #804, #809 and #810 were handed back with only the leg's last line; the event carries the tail."""
        self.use(**dict(self.settings, **{'train.verdict_fallback': 'requeue'}))
        self.head_leg.passed = False
        number, head = self.foreign_pr(self.GATE_CHANGE)
        self.drain()
        [ejected] = self.events(number, 'pr.ejected')
        self.assertIn('exit 1: FAIL unit tests', ejected['payload']['log'])
        self.assertTrue(ejected['payload']['log'].endswith(self.head_leg.output[head]))

    def test_a_foreign_toolchain_without_a_toolchain_change_is_refused_as_before(self):
        self.foreign_pr({'c.txt': 'one\n'})
        _, printed = self.drain()
        self.assertIn('toolchain the-head-own-toolchain is not the attested', printed)
        self.assertEqual(self.head_leg.calls, [])
        self.assertEqual(self.measured('self-host'), [])

    def test_a_non_gate_pr_with_the_attested_toolchain_is_unchanged(self):
        number, _ = self.verdict_pr({'c.txt': 'one\n'})
        self.drain()
        self.assertEqual((self.forge.merges, self.head_leg.calls), ([number], []))

    def test_off_refuses_every_foreign_toolchain(self):
        self.use(**dict(self.settings, **{'train.self_host': 'off'}))
        self.foreign_pr(self.GATE_CHANGE)
        _, printed = self.drain()
        self.assertIn('is not the attested', printed)
        self.assertEqual(self.head_leg.calls, [])

if __name__ == '__main__':
    unittest.main()
