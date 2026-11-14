"""D-260: gate-noite lists every lock.lifted since the regime began (lock, sha, lane, time). Fixture events, no forge."""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import regime_lifts  # noqa: E402


def lift(lock, when, sha='sha-a', lane='lane-11', kind=regime_lifts.KIND):
    return {'type': kind, 'occurred_at': when, 'payload': {'lock': lock, 'sha': sha, 'lane': lane}}


class Lifted(unittest.TestCase):
    def test_only_lock_lifted_events_are_listed_in_log_order(self):
        events = [lift('gate', '2026-11-01T07:00:00Z'), {'type': 'pr.ready', 'occurred_at': '2026-11-01T06:00:00Z', 'payload': {}},
                  lift('merger', '2026-11-01T06:30:00Z')]
        self.assertEqual([row['lock'] for row in regime_lifts.lifted(events)], ['merger', 'gate'])

    def test_since_keeps_the_events_from_the_start_of_the_regime_on(self):
        events = [lift('gate', '2026-11-01T06:00:00Z'), lift('forge', '2026-11-01T07:00:00Z')]
        self.assertEqual([row['lock'] for row in regime_lifts.lifted(events, '2026-11-01T06:30:00Z')], ['forge'])

    def test_instants_compare_by_time_not_by_their_text(self):
        # 08:00 at +02:00 is 06:00 UTC: before a 07:00Z start, though its text sorts after it.
        events = [lift('gate', '2026-11-01T08:00:00+02:00'), lift('forge', '2026-11-01T07:30:00Z')]
        self.assertEqual([row['lock'] for row in regime_lifts.lifted(events, '2026-11-01T07:00:00Z')], ['forge'])

    def test_a_row_names_the_lock_the_sha_the_lane_and_the_time(self):
        row = regime_lifts.lifted([lift('gate', '2026-11-01T07:00:00Z', sha='sha-c', lane='lane-6')])[0]
        self.assertEqual(row, {'lock': 'gate', 'sha': 'sha-c', 'lane': 'lane-6', 'time': '2026-11-01T07:00:00Z'})

    def test_a_payload_without_a_field_is_listed_with_a_question_mark_not_dropped(self):
        row = regime_lifts.lifted([{'type': regime_lifts.KIND, 'occurred_at': '2026-11-01T07:00:00Z', 'payload': {}}])[0]
        self.assertEqual((row['lock'], row['sha'], row['lane']), ('?', '?', '?'))

    def test_no_lifted_lock_says_so(self):
        self.assertEqual(regime_lifts.render([], '2026-11-01T06:00:00Z'),
                         ['Locks lifted by the exception regime since 2026-11-01T06:00:00Z: 0', '(none)'])

    def test_the_listing_is_a_table_of_every_row(self):
        rows = regime_lifts.lifted([lift('gate', '2026-11-01T07:00:00Z', sha='sha-d'), lift('people', '2026-11-01T07:05:00Z')])
        lines = regime_lifts.render(rows)
        self.assertEqual(lines[0], f'Locks lifted by the exception regime since its start: {len(rows)}')
        self.assertIn('| gate | sha-d | lane-11 | 2026-11-01T07:00:00Z |', lines)
        self.assertEqual(lines[-1], '| people | sha-a | lane-11 | 2026-11-01T07:05:00Z |')


class ReadEvents(unittest.TestCase):
    def test_a_line_that_is_not_an_event_is_an_error_not_a_skipped_lock(self):
        import tempfile
        import gate_noite
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'events.jsonl'
            path.write_text('{"type": "lock.lifted", "occurred_at": "2026-11-01T07:00:00Z", "payload": {}}\nnot json\n')
            with self.assertRaisesRegex(RuntimeError, 'is not an event'):
                gate_noite.read_events(path)


if __name__ == '__main__':
    unittest.main()
