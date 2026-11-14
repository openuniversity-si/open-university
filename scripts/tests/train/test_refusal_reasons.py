"""The merge train names why a PR waiting for it is not merged (incident of 2026-11-01): a dirty PR is never dropped silently."""
from pathlib import Path
import contextlib
import io
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, setUpModule  # noqa: E402,F401
import train_queue  # noqa: E402


class Reasons(Fixture):
    def test_a_dirty_pr_is_named_not_drained(self):
        number = len('abcdefg')
        dirty = self.pr(number, {'dirty.txt': 'x\n'})
        output = io.StringIO()
        with mock.patch.object(self.forge, 'merge', side_effect=RuntimeError('Pull Request is not mergeable (dirty)')):
            with contextlib.redirect_stdout(output):
                self.train.run_batch(self.train.queue())
        self.assertIn(f'#{number} not merged: dirty: the base conflicts with this head', output.getvalue(), dirty)

    def test_a_head_that_moved_after_ready_is_named(self):
        events = [{'type': 'pr.ready', 'event_id': 'e1', 'payload': {'sha': 'old', 'evidence': 'g'}}]
        self.assertIn('head moved to new', train_queue.skip_reason(events, 'new'))

    def test_a_pr_without_a_passed_gate_of_its_head_is_named(self):
        events = [{'type': 'pr.ready', 'event_id': 'e1', 'payload': {'sha': 'h', 'evidence': 'g'}}]
        self.assertIn('no passed real gate', train_queue.skip_reason(events, 'h'))

    def test_another_refusal_says_it_stays_queued(self):
        events = [{'type': 'pr.ready', 'event_id': 'e1', 'payload': {'sha': 'h', 'evidence': 'g'}},
                  {'type': 'gate.passed', 'event_id': 'g', 'payload': {'sha': 'h'}}]
        self.assertIn('stays queued', train_queue.skip_reason(events, 'h', 'rate limited'))


if __name__ == '__main__':
    unittest.main()
