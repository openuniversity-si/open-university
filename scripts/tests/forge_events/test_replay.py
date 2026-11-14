"""forge_events port (D-065, M2): replay (TX24: one file per feature; fixtures in scripts/tests/test_forge_events.py)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_forge_events import FakeClock, HEAD, MERGE, NEXT, REPO, gate, port  # noqa: E402,F401
import config  # noqa: E402
import forge_events  # noqa: E402
import forge_origin  # noqa: E402


class Replay(unittest.TestCase):
    def log(self):
        adapter = forge_events.MemoryAdapter()
        events = port(adapter)
        failed = events.emit(*gate('failed'))
        passed = events.emit(*gate('passed'))
        events.emit('pr.ready', dict(forge_events.subject(REPO, 7, HEAD, ['P-02']), lane_id='motor-1',
                                     evidence=passed['event_id']))
        events.emit('pr.conflicted', dict(forge_events.subject(REPO, 7, HEAD), files=['a.py'], tip_sha=NEXT,
                                          cause='textual', detail='a.py conflicts'))
        events.emit('pr.merged', dict(forge_events.subject(REPO, 7, HEAD), merge_sha=MERGE, batch_id='b1'))
        events.emit(*gate('failed', pr=8, sha=NEXT))
        return adapter, failed, passed

    def test_rebuilds_per_pr_gate_and_merge_state(self):
        adapter, failed, passed = self.log()
        events = port(adapter).read(REPO, 7) + port(adapter).read(REPO, 8)
        state = forge_events.replay(events)
        self.assertEqual(state[7]['gates'][HEAD]['dev']['verdict'], 'passed')
        self.assertEqual(state[7]['ready'], HEAD)
        self.assertEqual(state[7]['merged'], MERGE)
        self.assertEqual(state[7]['conflicted'], [NEXT])
        self.assertEqual(state[8]['gates'][NEXT]['dev']['verdict'], 'failed')
        self.assertEqual(forge_events.replay(events), state, 'same log, same state')
        self.assertEqual(forge_events.replay(events + events), state, 'duplicates do not change state')

    def test_live_fold_equals_replay(self):
        adapter, live = forge_events.MemoryAdapter(), {}
        events = port(adapter)
        for kind, payload in [gate('failed'), gate('passed'), gate('passed', sha=NEXT, pr=8),
                              ('pr.merged', dict(forge_events.subject(REPO, 7, HEAD), merge_sha=MERGE, batch_id=None))]:
            forge_events.apply(live, events.emit(kind, payload))
        log = port(adapter).read(REPO, 7) + port(adapter).read(REPO, 8)
        self.assertEqual(forge_events.replay(log), live)

    def test_the_log_has_no_rewrite_or_delete(self):
        for owner in (forge_events.ForgeEvents, forge_events.MemoryAdapter, forge_events.FileAdapter, forge_origin.OriginAdapter):
            public = {name for name in vars(owner) if not name.startswith('_')}
            self.assertFalse({n for n in public if re.search(r'delete|remove|rewrite|update|edit|truncate', n)}, owner)

    def test_gate_slow_from_the_registry_window(self):
        window, limit_ms = config.get('gate.slow_window_events'), config.get('gate.slow_median_s') * 1000
        events = port()

        def verdict(ms, n):
            kind, payload = gate('passed', sha=f'{n:040x}')
            payload['stages'] = [{'name': 'unit tests', 'result': 'PASS', 'duration_ms': ms, 'class': None},
                                 {'name': 'lint', 'result': 'PASS', 'duration_ms': 1, 'class': None}]
            return events.build(kind, payload)
        fast = [verdict(limit_ms - 1, n) for n in range(window)]
        slow = [verdict(limit_ms * 2, n) for n in range(window)]
        self.assertIsNone(forge_events.gate_slow(slow[:window - 1]), 'fewer verdicts than the window')
        self.assertIsNone(forge_events.gate_slow(slow + fast))
        found = forge_events.gate_slow(fast + slow)
        self.assertEqual((found['median_ms'], found['window'], found['slowest_stages']),
                         (limit_ms * 2 + 1, window, ['unit tests', 'lint']))
        port().build('gate.slow', dict(forge_events.subject(REPO, None, HEAD), **found))

    def test_gate_evidence_is_exact_head_and_plan(self):
        adapter, _, passed = self.log()
        state = forge_events.replay(port(adapter).read(REPO, 7) + port(adapter).read(REPO, 8))
        self.assertEqual(forge_events.gate_evidence(state, 7, HEAD, 'dev'), passed['event_id'])
        self.assertIsNone(forge_events.gate_evidence(state, 7, NEXT, 'dev'))
        self.assertIsNone(forge_events.gate_evidence(state, 7, HEAD, 'db'))
        self.assertIsNone(forge_events.gate_evidence(state, 8, NEXT, 'dev'))
        self.assertIsNone(forge_events.gate_evidence(state, 9, HEAD, 'dev'))


class Measured(unittest.TestCase):
    def test_times_a_step_from_the_injected_clock(self):
        adapter = forge_events.MemoryAdapter()
        events = port(adapter, clock=FakeClock(step=timedelta(milliseconds=1500)))
        with forge_events.measured(events, 'gate:lint', forge_events.subject(REPO, 7, HEAD, ['P-02'])) as step:
            step.model, step.provider, step.tokens_in, step.tokens_out = 'model-x', 'claude', 10, 20
        [event] = adapter.logs[(REPO, 7)]
        self.assertEqual(event['type'], 'engine.step.measured')
        self.assertEqual({k: event['payload'][k] for k in ('step', 'duration_ms', 'result', 'retries', 'tokens_in',
                                                            'tokens_out', 'model', 'provider', 'unit', 'pr')},
                         {'step': 'gate:lint', 'duration_ms': 1500, 'result': 'ok', 'retries': 0, 'tokens_in': 10,
                          'tokens_out': 20, 'model': 'model-x', 'provider': 'claude', 'unit': None, 'pr': 7})

    def test_failure_is_emitted_then_raised(self):
        adapter = forge_events.MemoryAdapter()
        with self.assertRaises(ZeroDivisionError):
            with forge_events.measured(port(adapter), 'train:merge', forge_events.subject(REPO, None, HEAD)) as step:
                step.retries = 2
                1 / 0
        [event] = adapter.logs[(REPO, None)]
        self.assertEqual((event['payload']['result'], event['payload']['retries']), ('fail', 2))

    def test_blocked_and_decorator_form(self):
        adapter = forge_events.MemoryAdapter()
        events = port(adapter)

        @forge_events.measured(events, 'lane:item', forge_events.subject(REPO, 7, HEAD))
        def work():
            return 'done'
        self.assertEqual(work(), 'done')
        with forge_events.measured(events, 'lane:wait', forge_events.subject(REPO, 7, HEAD)) as step:
            step.result = 'blocked'
        self.assertEqual([e['payload']['result'] for e in adapter.logs[(REPO, 7)]], ['ok', 'blocked'])

    def test_each_run_measures_again_but_a_replayed_run_does_not(self):
        adapter = forge_events.MemoryAdapter()
        for correlation in ('run-1', 'run-1', 'run-2'):
            port(adapter, correlation=correlation).emit('engine.step.measured', forge_events.step_payload(
                forge_events.subject(REPO, 7, HEAD), 'gate:lint', 900, 'ok'))
        self.assertEqual(len(adapter.logs[(REPO, 7)]), 2)


if __name__ == '__main__':
    unittest.main()
