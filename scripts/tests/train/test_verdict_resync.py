"""Verdict admission: the train's resync of a moved tip (split from test_verdict.py, F117: the file was the slowest of the train suite).
"""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import REPO, Fixture, setUpModule  # noqa: E402,F401
from test_verdict import FakeReverdict, FakeSelfHost, Verdict, PASSED, FAILED, ROOT  # noqa: E402,F401
import train  # noqa: E402
import train_verdict  # noqa: E402


class Resync(Verdict):
    """(b) requeue, the default: the train merges the tip into the head, asks the gate API, admits on PASSED."""

    def test_a_moved_tip_is_merged_into_the_head_reverdicted_and_admitted_by_the_train(self):
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, head = self.verdict_pr({'d.txt': 'two\n'})
        outcome, printed = self.drain()
        self.assertEqual((outcome, self.forge.merges, self.gate.runs), ('drained', [first, second], []))
        first_tip = self.run_git(self.origin, 'rev-parse', f'{self.base_branch}^1')
        resynced = self.run_git(self.origin, 'rev-parse', f'refs/heads/pr-{second}')
        self.assertEqual(self.parents(second), [head, first_tip], 'a merge commit of the tip, never a rebase')
        message = self.run_git(self.origin, 'log', '-1', '--format=%B', resynced)
        self.assertIn(f'{train_verdict.RESYNC_TRAILER}: {first_tip}', message)
        self.assertIn('Decision: D-075', message)
        self.assertEqual(self.gate_api.calls, [(second, resynced)])
        self.assertTrue(all(bid.startswith(train_verdict.VERDICT) for bid in self.batch_ids('pr.merged')))
        self.assertEqual(self.events(second, 'pr.conflicted'), [], 'the owner session does nothing')
        self.assertEqual(self.measured('reverdict'), ['ok'])
        self.assertIn(f'#{second} resynced', printed)

    def test_a_textual_conflict_goes_back_to_the_owner_with_its_files(self):
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, head = self.verdict_pr({'c.txt': 'other\n'})
        _, printed = self.drain()
        [conflicted] = self.events(second, 'pr.conflicted')
        self.assertEqual((conflicted['payload']['cause'], conflicted['payload']['files']), ('textual', ['c.txt']))
        self.assertEqual((self.forge.merges, self.gate_api.calls), ([first], []))
        self.assertEqual(self.run_git(self.origin, 'rev-parse', f'refs/heads/pr-{second}'), head, 'nothing pushed')
        self.assertIn('handed back to its owner', printed)

    def test_a_red_reverdict_goes_back_to_the_owner(self):
        self.gate_api.answer = FAILED
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, _ = self.verdict_pr({'d.txt': 'two\n'})
        _, printed = self.drain()
        self.assertIn(f'#{second}   FAIL test_x: expected 3', printed)
        [ejected] = self.events(second, 'pr.ejected')
        resynced = self.run_git(self.origin, 'rev-parse', f'refs/heads/pr-{second}')
        self.assertEqual((ejected['payload']['stage'], ejected['payload']['cause'], ejected['payload']['sha']),
                         ('unit tests', 'culprit', resynced))
        self.assertEqual((self.forge.merges, self.measured('reverdict')), ([first], ['fail']))

    def test_an_unobservable_reverdict_halts_and_blames_nobody(self):
        self.gate_api.answer = None
        self.verdict_pr({'c.txt': 'one\n'})
        second, _ = self.verdict_pr({'d.txt': 'two\n'})
        with self.assertRaisesRegex(train.TrainHalt, 'did not judge the code'):
            self.drain()
        self.assertEqual(self.events(second, 'pr.ejected'), [])

    def test_a_red_reverdict_of_a_halting_class_halts(self):
        self.gate_api.answer, self.gate_api.red = FAILED, [('install', 'env')]
        self.verdict_pr({'c.txt': 'one\n'})
        second, _ = self.verdict_pr({'d.txt': 'two\n'})
        with self.assertRaisesRegex(train.TrainHalt, 'red install'):
            self.drain()
        self.assertEqual(self.events(second, 'pr.ejected'), [])

    def test_a_verdict_with_cache_hits_is_admitted_by_content_without_a_reverdict(self):
        """D-076 (P-56): the tip's tooling keys every cached result by content, so hits are this tree's results."""
        number, head = self.verdict_pr({'c.txt': 'one\n'}, cache_hits=len(self.forge.open) + 1)
        _, printed = self.drain()
        self.assertIn('merged alone on its verdict (strict)', printed)
        self.assertEqual((self.gate_api.calls, self.forge.merges), ([], [number]))

    def test_a_warm_verdict_on_the_tip_gets_a_new_sha_so_its_cold_verdict_is_a_new_event(self):
        """With gate.content_cache_enabled off (D-076's rollback): the same head and tip give the same input_digest,
        hence the same gate.passed event id: the train makes a merge commit with the head's tree, and the cold verdict
        of that sha is admitted."""
        self.train.content_reuse = False
        number, head = self.verdict_pr({'c.txt': 'one\n'}, cache_hits=len(self.forge.open) + 1)
        _, printed = self.drain()
        self.assertIn('not cold', printed)
        refreshed = self.run_git(self.origin, 'rev-parse', f'refs/heads/pr-{number}')
        self.assertEqual(self.parents(number), [head, self.base])
        self.assertEqual(self.workspace.tree(refreshed), self.workspace.tree(head))
        self.assertEqual((self.gate_api.calls, self.forge.merges), ([(number, refreshed)], [number]))

    def test_a_cold_rerun_of_an_unchanged_input_is_the_same_event(self):
        """Why the warm case needs a new sha: the forge keeps one gate.passed per natural key."""
        number, head = self.verdict_pr({'c.txt': 'one\n'}, cache_hits=len(self.forge.open) + 1)
        self.publish(number, head, self.base)
        self.assertEqual(len(self.events(number, 'gate.passed')), 1)

    def test_a_passed_reverdict_that_still_refuses_halts_and_blames_nobody(self):
        """D-078: the train's own cold verdict on its own machine is refused, so the machine or the rules are wrong;
        the PR is neither handed back nor touched."""
        self.train.verified_source = lambda adapter: None
        number, head = self.verdict_pr({'c.txt': 'one\n'})
        with self.assertRaisesRegex(train.TrainHalt, 'passed but does not admit .*verified source'):
            self.drain()
        self.assertEqual(self.gate_api.calls, [(number, head)])
        self.assertEqual(self.run_git(self.origin, 'rev-parse', f'refs/heads/pr-{number}'), head, 'nothing pushed')
        self.assertEqual((self.forge.merges, self.events(number, 'pr.conflicted')), ([], []))

    def test_a_head_that_contains_the_tip_refused_for_its_toolchain_is_reverdicted_as_it_is_and_merges(self):
        """#805 (29/10): the head contained the tip and its verdict came from another toolchain. The re-verdict of the
        same sha published a pr.ready with the refused one's event_id, so the forge kept the refused evidence and the
        train handed the PR back with pr.conflicted and no file. D-078: the train re-verdicts the same sha (its cold
        verdict has another input_digest, so it is a new gate.passed), admits it in the same pass, pushes nothing."""
        number, head = self.toolchain_pr()
        _, printed = self.drain()
        self.assertEqual(self.gate_api.calls, [(number, head)], 'the same head, cold, on the tip')
        self.assertEqual(self.run_git(self.origin, 'rev-parse', f'refs/heads/pr-{number}'), head, 'nothing pushed')
        self.assertEqual((self.forge.merges, self.events(number, 'pr.conflicted')), ([number], []))
        self.assertEqual([event['payload']['sha'] for event in self.events(number, 'pr.merged')], [head])
        self.assertIn('toolchain another-box', printed)
        self.assertIn(f're-verdict of the same head {head}', printed)
        self.assertEqual(self.workspace.tree(self.workspace.tip(self.base_branch)), self.workspace.tree(head))
        self.assertEqual(self.measured('reverdict'), ['ok'])
        self.assertEqual(self.train.queue(), [])

    def test_a_fork_refused_for_its_toolchain_merges_too_since_nothing_is_pushed(self):
        number, head = self.toolchain_pr()
        real = self.forge.change
        fork = lambda repo, pr: dict(real(repo, pr), head_repo='someone/fork')  # noqa: E731
        with mock.patch.object(self.forge, 'change', side_effect=fork):
            self.drain()
        self.assertEqual((self.gate_api.calls, self.forge.merges), ([(number, head)], [number]))

    def test_a_branch_the_train_cannot_push_takes_the_tier2_batch_of_one(self):
        """D-078: not a conflict; tier 2 merges the pinned head without pushing to the fork."""
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, _ = self.verdict_pr({'d.txt': 'two\n'})
        real = self.forge.change
        fork = lambda repo, number: dict(real(repo, number), head_repo='someone/fork')  # noqa: E731
        with mock.patch.object(self.forge, 'change', side_effect=fork):
            _, printed = self.drain()
        self.assertEqual((self.forge.merges, self.gate_api.calls, len(self.gate.runs)), ([first, second], [], 1))
        self.assertEqual(self.events(second, 'pr.conflicted'), [])
        self.assertIn('cannot push to someone/fork', printed)

if __name__ == '__main__':
    unittest.main()
