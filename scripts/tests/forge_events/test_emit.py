"""forge_events port (D-065, M2): emit (TX24: one file per feature; fixtures in scripts/tests/test_forge_events.py)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_forge_events import FakeClock, LATEST, MERGE, NEXT, REPO, gate, port  # noqa: E402,F401
import config  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402


class Emit(unittest.TestCase):
    def test_envelope_from_injected_clock(self):
        event = port().emit(*gate('passed'))
        self.assertEqual(event['occurred_at'], '2026-10-26T18:00:00.000Z')
        self.assertEqual((event['type'], event['version'], event['producer'], event['correlation_id']),
                         ('gate.passed', config.get('gate-contracts.gate_passed_version'), 'gate_report', 'run-1'))  # the pinned version is the default
        self.assertEqual(event['payload']['unit'], None)
        self.assertEqual(event['payload']['premises'], ['P-02'])

    def test_naive_clock_is_refused(self):
        class Naive:
            def now(self):
                return datetime(2026, 10, 26, 18, 0)
        with self.assertRaises(forge_events.ForgeEventsError):
            port(clock=Naive()).emit(*gate('passed'))

    def test_invalid_payload_is_refused_and_nothing_is_written(self):
        adapter = forge_events.MemoryAdapter()
        kind, payload = gate('passed')
        del payload['premises']
        with self.assertRaises(event_contracts.ContractError):
            port(adapter).emit(kind, payload)
        with self.assertRaises(forge_events.ForgeEventsError):
            port(adapter).emit('gate.green', payload)
        self.assertEqual(adapter.logs, {})

    def test_re_emitting_is_a_no_op(self):
        adapter = forge_events.MemoryAdapter()
        first = port(adapter).emit(*gate('passed'))
        again = port(adapter, clock=FakeClock(step=timedelta(hours=1)), correlation='run-2').emit(*gate('passed'))
        self.assertEqual(first['event_id'], again['event_id'])
        self.assertEqual(len(adapter.logs[(REPO, 7)]), 1)
        self.assertEqual(adapter.appends, 1)

    def test_one_write_per_channel_and_repository_channel(self):
        adapter = forge_events.MemoryAdapter()
        events = port(adapter)
        built = [events.build(*gate('passed')), events.build(*gate('failed', sha=NEXT)),
                 events.build('train.queue.empty', forge_events.subject(REPO, None, MERGE))]
        events.publish(built + built[:1])
        self.assertEqual(adapter.appends, 2)
        self.assertEqual(len(adapter.logs[(REPO, 7)]), 2)
        self.assertEqual(adapter.logs[(REPO, None)][0]['type'], 'train.queue.empty')

    def test_explicit_version(self):
        self.assertEqual(port().emit(*gate('passed'), version=1)['version'], 1)
        self.assertEqual(port().emit(*gate('passed'), version=2)['version'], 2)
        with self.assertRaises(event_contracts.ContractError):
            port().emit(*gate('passed'), version=LATEST['gate.passed'] + 1)


class Read(unittest.TestCase):
    def test_duplicates_from_concurrent_producers_are_detected(self):
        adapter = forge_events.MemoryAdapter()
        event = port(adapter).emit(*gate('passed'))
        adapter.append(forge_events.Channel(REPO, 7), [event])
        events = port(adapter)
        unique, duplicates = forge_events.dedupe(adapter.read(forge_events.Channel(REPO, 7)))
        self.assertEqual((len(unique), len(duplicates)), (1, 1))
        self.assertEqual(len(events.read(REPO, 7)), 1)

    def test_ordering_is_detectable(self):
        adapter = forge_events.MemoryAdapter()
        late = port(adapter, clock=FakeClock(start=datetime(2026, 10, 26, 19, 0, tzinfo=timezone.utc))).emit(*gate('failed'))
        early = port(adapter).emit(*gate('passed'))
        events = port(adapter).read(REPO, 7)
        self.assertEqual([e['event_id'] for e in events], [late['event_id'], early['event_id']])
        self.assertEqual(forge_events.ordering_violations(events), [(late, early)])

    def test_forged_and_corrupt_entries_are_rejected_on_read(self):
        adapter = forge_events.MemoryAdapter()
        event = port(adapter).emit(*gate('failed'))
        forged = dict(event, type='gate.passed')
        tampered = dict(event, payload=dict(event['payload'], sha=NEXT))
        adapter.append(forge_events.Channel(REPO, 7), [forged, tampered, {'unreadable': 'x'}])
        reader = port(adapter)
        self.assertEqual([e['type'] for e in reader.read(REPO, 7)], ['gate.failed'])
        self.assertEqual(len(reader.rejected), 3)
        with self.assertRaises(Exception):
            port(adapter).read(REPO, 7, strict=True)


class FileLog(unittest.TestCase):
    def test_append_only_jsonl(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        adapter = forge_events.FileAdapter(directory)
        port(adapter).emit(*gate('failed'))
        path = adapter.path(forge_events.Channel(REPO, 7))
        before = path.read_bytes()
        port(adapter).emit(*gate('passed'))
        port(adapter).emit(*gate('passed'))
        after = path.read_bytes()
        self.assertTrue(after.startswith(before))
        self.assertEqual(len(after.splitlines()), 2)
        self.assertEqual([e['type'] for e in port(adapter).read(REPO, 7)], ['gate.failed', 'gate.passed'])
        self.assertEqual(port(adapter).read(REPO, 8), [])


if __name__ == '__main__':
    unittest.main()
