"""The train takes the ready PRs left behind the tip on its own (TRAIN-VERDICT-FIX B2, D-075): train_verdict.bootstrap
and train_queue.resync_candidate. A PR that was ready, left the queue (a conflict at an older tip, a head pushed after
its pr.ready) and whose last gate judged an older base is resynced, re-verdicted and admitted with no owner session.
"""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import REPO, setUpModule  # noqa: E402,F401
from test_verdict import Verdict  # noqa: E402
import forge_events  # noqa: E402
import train_queue  # noqa: E402


class Bootstrap(Verdict):
    def left_the_queue(self, number, head, tip):
        """What the batch train of 28/10 left on #774: pr.conflicted for its head at an older tip."""
        subject = forge_events.subject(REPO, number, head, ['P-02'])
        self.lane_port.emit('pr.conflicted', dict(subject, files=['CODEOWNERS'], tip_sha=tip), 1)  # v1, as then

    def test_a_ready_pr_left_behind_the_tip_is_resynced_reverdicted_and_merged(self):
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, head = self.verdict_pr({'d.txt': 'two\n'})
        self.left_the_queue(second, head, self.base)
        outcome, printed = self.drain()
        self.assertEqual((outcome, self.forge.merges, self.gate.runs), ('drained', [first, second], []))
        self.assertIn(f'#{second} bootstrap: {head}', printed)
        resynced = self.run_git(self.origin, 'rev-parse', f'refs/heads/pr-{second}')
        self.assertEqual(self.gate_api.calls, [(second, resynced)])
        self.assertEqual(self.parents(second)[0], head, 'the tip merged into the head, never a rebase')

    def test_a_pr_behind_the_tip_is_not_taken_in_batch_mode_or_under_tier2(self):
        for settings in ({'train.admit_mode': 'batch'}, {'train.verdict_fallback': 'tier2'}):
            with self.subTest(**settings):
                self.use(**dict(self.settings, **settings))
                self.assertFalse(self.train.bootstrap(self.train.port('test')))

    def test_a_head_is_tried_once_per_run(self):
        self.gate_api.answer = 'FAILED'
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, head = self.verdict_pr({'d.txt': 'two\n'})
        self.left_the_queue(second, head, self.base)
        self.assertEqual(self.drain()[0], 'drained')
        self.assertEqual((self.forge.merges, len(self.gate_api.calls)), ([first], 1))
        self.assertEqual(len(self.events(second, 'pr.ejected')), 1)


class Candidate(unittest.TestCase):
    """train_queue.resync_candidate on hand-made logs (the payload fields it reads)."""

    number = len(REPO)  # any PR number; LT1: no number written in a test

    def event(self, kind, sha, **payload):
        return {'type': kind, 'occurred_at': '2026-10-29T12:00:00Z', 'event_id': f'{kind}-{sha}',
                'payload': dict({'pr': self.number, 'sha': sha, 'unit': 'ui-tokens', 'premises': ['P-02'],
                                 'lane_id': None}, **payload)}

    def log(self, *extra):
        return [self.event('gate.passed', 'old', base_sha='b0'),
                self.event('pr.ready', 'old', evidence='gate.passed-old'),
                self.event('gate.failed', 'head', base_sha='b1'), *extra]

    def test_a_ready_pr_whose_head_was_gated_on_an_older_base_is_a_candidate(self):
        entry = train_queue.resync_candidate(self.log(), 'head', 'tip')
        self.assertEqual((entry.pr, entry.sha, entry.unit, entry.premises, entry.evidence),
                         (self.number, 'head', 'ui-tokens', ('P-02',), None))

    def test_refusals(self):
        cases = {
            'never ready': ([self.event('gate.failed', 'head', base_sha='b1')], 'tip'),
            'its head never gated': ([event for event in self.log() if event['payload']['sha'] != 'head'], 'tip'),
            'last gate on the tip': (self.log(), 'b1'),
            'conflicted at this tip': (self.log(self.event('pr.conflicted', 'head', tip_sha='tip')), 'tip'),
            'red on the train re-verdict': (self.log(self.event('pr.ejected', 'head', batch_id='r-head')), 'tip'),
            'merged': (self.log(self.event('pr.merged', 'head')), 'tip'),
            'queued': ([self.event('gate.passed', 'head', base_sha='b1'),
                        self.event('pr.ready', 'head', evidence='gate.passed-head')], 'tip'),
        }
        for name, (events, tip) in cases.items():
            with self.subTest(name):
                self.assertIsNone(train_queue.resync_candidate(events, 'head', tip))

    def test_a_conflict_at_an_older_tip_or_a_batch_ejection_is_tried_again(self):
        for extra in (self.event('pr.conflicted', 'head', tip_sha='b1'),
                      self.event('pr.ejected', 'head', batch_id='b-1')):
            with self.subTest(extra['type']):
                self.assertIsNotNone(train_queue.resync_candidate(self.log(extra), 'head', 'tip'))


if __name__ == '__main__':
    unittest.main()
