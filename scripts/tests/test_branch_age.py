"""A branch older than process.branch_max_age_h is stale, evaluated only on a trigger event (D-069 item 11; P-32).

Pure rule with an injected instant: no clock, no network. Offsets are taken from the registry, not written as numbers.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import branch_age  # noqa: E402
import config  # noqa: E402
import forge_events  # noqa: E402

MAX_AGE = config.get('process.branch_max_age_h')
TRIGGERS = config.get('process.branch_trigger_types')
NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
SUBJECT = {'repo': 'openuniversity-si/open-university', 'pr': 504, 'sha': 'a' * 40, 'unit': None, 'premises': ['P-32']}


def stamp(moment):
    return moment.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def event(kind, moment, pr=504):
    return {'type': kind, 'occurred_at': stamp(moment), 'payload': {**SUBJECT, 'pr': pr}}


class BranchAge(unittest.TestCase):
    def age_before_now(self, hours):
        return NOW - timedelta(hours=hours)

    def test_a_branch_older_than_the_limit_is_stale_on_a_trigger(self):
        opened = event('pr.opened', self.age_before_now(MAX_AGE + 1))
        trigger = event('pr.pushed', NOW)
        payload = branch_age.evaluate([opened, trigger], trigger, NOW)
        self.assertEqual(payload['opened_at'], opened['occurred_at'])
        self.assertEqual(payload['max_age_h'], MAX_AGE)
        self.assertGreater(payload['age_h'], MAX_AGE)
        self.assertEqual({key: payload[key] for key in SUBJECT}, SUBJECT)

    def test_a_branch_exactly_at_the_limit_is_not_yet_stale(self):
        opened = event('pr.opened', self.age_before_now(MAX_AGE))
        trigger = event('pr.pushed', NOW)
        self.assertIsNone(branch_age.evaluate([opened, trigger], trigger, NOW))

    def test_a_young_branch_is_not_stale(self):
        opened = event('pr.opened', self.age_before_now(0))
        trigger = event('pr.pushed', NOW)
        self.assertIsNone(branch_age.evaluate([opened, trigger], trigger, NOW))

    def test_age_is_counted_from_the_first_event_not_the_last(self):
        opened = event('pr.opened', self.age_before_now(MAX_AGE + 1))
        pushed = event('pr.pushed', self.age_before_now(0))
        trigger = event('pr.ready', NOW)
        self.assertIsNotNone(branch_age.evaluate([opened, pushed, trigger], trigger, NOW))

    def test_an_event_that_is_not_a_trigger_is_never_evaluated(self):
        opened = event('pr.opened', self.age_before_now(MAX_AGE + 1))
        self.assertIsNone(branch_age.evaluate([opened], opened, NOW))

    def test_the_triggers_are_the_registered_types(self):
        self.assertTrue(TRIGGERS)
        for kind in TRIGGERS:
            trigger = event(kind, NOW)
            self.assertIsNotNone(branch_age.evaluate([event('pr.opened', self.age_before_now(MAX_AGE + 1))],
                                                     trigger, NOW), kind)
        self.assertNotIn('pr.opened', TRIGGERS)

    def test_a_trigger_that_names_no_pr_has_no_branch(self):
        opened = event('pr.opened', self.age_before_now(MAX_AGE + 1))
        trigger = event('integration.advanced', NOW, pr=None)
        self.assertIsNone(branch_age.evaluate([opened, trigger], trigger, NOW))

    def test_a_channel_with_no_events_has_no_age(self):
        trigger = event('pr.pushed', NOW)
        self.assertIsNone(branch_age.evaluate([], trigger, NOW))

    def test_the_age_in_hours_is_exact(self):
        opened = event('pr.opened', self.age_before_now(MAX_AGE + 2))
        self.assertAlmostEqual(branch_age.age_hours(opened['occurred_at'], NOW), MAX_AGE + 2)


class FrozenClock:
    def __init__(self, at):
        self.at = at

    def now(self):
        return self.at


class OnThePort(unittest.TestCase):
    """The port evaluates branch age when a trigger is appended, and only then (forge_events.publish)."""

    def setUp(self):
        self.clock = FrozenClock(NOW - timedelta(hours=MAX_AGE + 1))
        self.port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), self.clock, 'maestro', 'corr-k1')

    def emit_opened(self):
        return self.port.emit('pr.opened', {**SUBJECT, 'base_sha': 'b' * 40, 'lane_id': 'lane-k1', 'units': []})

    def stale_events(self):
        return [event for event in self.port.read(SUBJECT['repo'], SUBJECT['pr']) if event['type'] == 'branch.stale']

    def test_non_trigger_publication_does_not_read_branch_history(self):
        with patch.object(self.port, 'read', wraps=self.port.read) as read:
            self.emit_opened()
        read.assert_not_called()

    def test_a_trigger_batch_reads_history_once_and_still_reports_staleness(self):
        self.emit_opened()
        self.clock.at = NOW
        with patch.object(self.port, 'read', wraps=self.port.read) as read:
            with self.port.batched():
                self.port.emit('pr.pushed', {**SUBJECT, 'sha': 'a' * 40})
                self.port.emit('pr.pushed', {**SUBJECT, 'sha': 'c' * 40})
        self.assertEqual(read.call_count, 1)
        self.assertEqual(len(self.stale_events()), 1)

    def test_a_stale_branch_is_reported_once_when_a_trigger_is_appended(self):
        opened = self.emit_opened()
        self.clock.at = NOW
        self.port.emit('pr.pushed', {**SUBJECT, 'sha': 'a' * 40})
        self.port.emit('pr.pushed', {**SUBJECT, 'sha': 'c' * 40})
        stale = self.stale_events()
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]['payload']['opened_at'], opened['occurred_at'])
        self.assertEqual(stale[0]['payload']['max_age_h'], MAX_AGE)

    def test_a_fresh_branch_emits_nothing(self):
        self.emit_opened()
        self.port.emit('pr.pushed', {**SUBJECT, 'sha': 'a' * 40})
        self.assertEqual(self.stale_events(), [])

    def test_an_event_that_is_not_a_trigger_emits_nothing(self):
        self.emit_opened()
        self.clock.at = NOW
        self.port.emit('pr.conflicted', {**SUBJECT, 'files': ['src/a.ts'], 'tip_sha': 'd' * 40,
                                         'cause': 'textual', 'detail': 'src/a.ts conflicts'})
        self.assertEqual(self.stale_events(), [])


if __name__ == '__main__':
    unittest.main(verbosity=1)
