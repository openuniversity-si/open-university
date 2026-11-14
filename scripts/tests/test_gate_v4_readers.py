"""gate.passed|failed v4 readers (GX-09, D-070): every reader accepts v3 and v4, the accepted versions come from the
locked contracts (gate_verdicts), and the train queue rests on a v4 pass without a train edit (plan-v2 E11). No network.
"""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent / 'lib'))
sys.path.insert(0, str(TESTS))

import config  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge_doubles  # noqa: E402
import gate_digest  # noqa: E402
import gate_verdicts  # noqa: E402
import pr_ready  # noqa: E402
import slo  # noqa: E402
import stall_report  # noqa: E402
import train  # noqa: E402
from test_plan_tick import FIXED, REPO, SHA, FixedClock, gate_passed  # noqa: E402 - the shared v3 fixture

PR = gate_passed()['pr']  # the plan-tick fixture's PR
KINDS = gate_verdicts.TYPES
DIGEST = hashlib.sha256(b'selection').hexdigest()
STAGE_MS = gate_passed()['stages'][0]['duration_ms']  # one stage time for every fixture, so the SLO values compare
BATCH_TIER = 1 + 1  # tier 2: a batch verdict, published on the repository channel with pr null


def version_with(field, newest):
    """The locked gate.passed version whose payload requires `field`: the newest one (v3 and input_hash) or the
    first one (v4 and input_digest). Versions are read from the contracts, never written here."""
    found = [version for version, name in event_contracts.catalog()['gate.passed'].items()
             if field in json.loads((event_contracts.directory() / name).read_text())['required']]
    return max(found) if newest else min(found)


V3 = version_with('input_hash', newest=True)
V4 = version_with('input_digest', newest=False)


def v4_payload(sha=SHA, pr=PR, tier=1, passed=True):
    """A v4 verdict as GX-10's producer will build it: the v3 subject plus the GA2 §6 proof-binding fields."""
    payload = forge_events.subject(REPO, pr, sha, ['P-42'])
    payload.update(
        tier=tier, plan='dev', missing_stages=[], head_tree=SHA, base_sha=SHA, base_tree=SHA, gate_version='g',
        toolchain_id='tc', selection={'kind': 'all', 'digest': DIGEST}, lane_id=None,
        input_digest=gate_digest.input_digest(head_tree=sha, base_sha=SHA, plan='dev', selection_digest=DIGEST,
                                              toolchain_id='tc', gate_version='g'),
        cost={'wall_s': 1, 'cpu_s': 0, 'rest_calls': 0, 'queue_wait_s': 0, 'cache_hits': 0, 'cache_misses': 1},
        stages=[{'name': 'lint', 'result': 'PASS' if passed else 'FAIL', 'duration_ms': STAGE_MS,
                 'class': None if passed else 'code', 'cached': False, 'inputs_digest': DIGEST}])
    return payload


def v3_payload(sha=SHA, passed=True):
    payload = gate_passed(sha, 'dev', PR)
    if not passed:
        payload['stages'] = [dict(payload['stages'][0], result='FAIL', **{'class': 'code'})]
    return payload


PAYLOADS = {V3: v3_payload, V4: v4_payload}


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def now(self):
        return self.moment


def gate_port(adapter, clock=None):
    return forge_events.ForgeEvents(adapter, clock or FixedClock(), config.get('forge-events.gate_producer'), 'gate:dev')


class AcceptedVersions(unittest.TestCase):
    def test_the_accepted_versions_are_the_locked_contracts(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                locked = tuple(sorted(event_contracts.catalog()[kind]))
                self.assertEqual(gate_verdicts.accepted_versions(kind), locked)
                self.assertIn(V3, locked)
                self.assertIn(V4, locked)
                self.assertLess(V3, V4)
        self.assertEqual(gate_verdicts.accepted_versions('pr.ready'), ())

    def test_v3_and_v4_round_trip_through_the_contracts(self):
        for kind in KINDS:
            for version, build in PAYLOADS.items():
                with self.subTest(kind=kind, version=version):
                    adapter = forge_events.MemoryAdapter()
                    port = gate_port(adapter)
                    sent = port.emit(kind, build(passed=kind == 'gate.passed'), version=version)
                    [read] = port.read(REPO, PR, strict=True)
                    self.assertEqual(read, sent)
                    self.assertEqual(read['version'], version)
                    event_contracts.validate(read, event_contracts.registry())
                    self.assertTrue(gate_verdicts.is_verdict(read))

    def test_an_unlocked_version_is_refused_by_the_read_and_by_the_readers(self):
        port = gate_port(forge_events.MemoryAdapter())
        envelope = port.build('gate.passed', v4_payload(), version=V4)
        future = dict(envelope, version=max(gate_verdicts.accepted_versions('gate.passed')) + 1)
        self.assertFalse(gate_verdicts.is_verdict(future))
        other = {'type': 'pr.ready', 'version': 1}
        self.assertEqual(gate_verdicts.accepted([future, envelope, other]), [envelope, other])
        self.assertEqual(gate_verdicts.verdicts([future, envelope, other]), [envelope])
        port.adapter.append(forge_events.Channel(REPO, PR), [future])
        self.assertEqual(port.read(REPO, PR), [])
        self.assertEqual(len(port.rejected), 1)


class ReadyAndQueue(unittest.TestCase):
    """pr.ready cites a v3 or v4 pass of the head, and train.queue_entry (unedited) queues it."""

    def test_pr_ready_and_the_train_queue_accept_v3_and_v4(self):
        for version, build in PAYLOADS.items():
            with self.subTest(version=version):
                adapter = forge_events.MemoryAdapter()
                passed = gate_port(adapter).emit('gate.passed', build(), version=version)
                session = forge_events.ForgeEvents(adapter, FixedClock(), config.get('plan-tick.event_producer'),
                                                   f'pr-{PR}')
                ready = pr_ready.emit_ready(session, REPO, PR, SHA, ['P-42'], 'dev', 'engine-lane')
                self.assertEqual(ready['payload']['evidence'], passed['event_id'])
                entry = train.queue_entry(session.read(REPO, PR), SHA)
                self.assertIsNotNone(entry)
                self.assertEqual((entry.pr, entry.sha, entry.evidence), (PR, SHA, passed['event_id']))
                self.assertEqual(entry.lane_id, 'engine-lane')

    def test_a_v4_failure_is_not_evidence(self):
        adapter = forge_events.MemoryAdapter()
        gate_port(adapter).emit('gate.failed', v4_payload(passed=False), version=V4)
        session = forge_events.ForgeEvents(adapter, FixedClock(), config.get('plan-tick.event_producer'), f'pr-{PR}')
        with self.assertRaises(pr_ready.GateNotPassed):
            pr_ready.emit_ready(session, REPO, PR, SHA, ['P-42'], 'dev')

    def test_a_tier2_v4_verdict_names_no_pr_and_is_no_pr_evidence(self):
        adapter = forge_events.MemoryAdapter()
        batch = gate_port(adapter).emit('gate.passed', v4_payload(pr=None, tier=BATCH_TIER), version=V4)
        self.assertEqual(gate_port(adapter).read(REPO), [batch])  # the repository channel
        session = forge_events.ForgeEvents(adapter, FixedClock(), config.get('plan-tick.event_producer'), f'pr-{PR}')
        with self.assertRaises(pr_ready.GateNotPassed):
            pr_ready.emit_ready(session, REPO, PR, SHA, ['P-42'], 'dev')


class Slo(unittest.TestCase):
    def test_the_tier1_series_counts_v3_and_v4_and_not_tier2(self):
        port = gate_port(forge_events.MemoryAdapter())
        events = [port.build('gate.passed', v3_payload(SHA.replace('a', 'b')), version=V3),
                  port.build('gate.failed', v4_payload(SHA.replace('a', 'c'), passed=False), version=V4),
                  port.build('gate.passed', v4_payload(SHA.replace('a', 'd'), pr=None, tier=BATCH_TIER), version=V4)]
        tier1 = slo.fold(events)['tier1']
        self.assertEqual([(item['event_id'], item['passed']) for item in tier1],
                         [(events[0]['event_id'], True), (events[1]['event_id'], False)])
        self.assertEqual(tier1[0]['value'], tier1[-1]['value'])  # v3 and v4 stages are summed the same way
        self.assertGreater(tier1[0]['value'], 0)


class StallForge(forge_events.MemoryAdapter):
    def __init__(self, head, branch, pushed):
        super().__init__()
        self.head, self.branch, self.pushed = head, branch, pushed

    def pull(self, repo, number):
        return {'number': number, 'head_ref': self.branch, 'head_sha': self.head, 'state': 'open'}

    def pushes(self, repo, branch):
        return [{'before': SHA.replace('a', '0'), 'after': self.head, 'timestamp': self.pushed}]

    def comments(self, repo, number):
        return []

    def open_changes(self, *_):
        raise AssertionError('a single-PR stall check must not discover the open queue')


class Stall(unittest.TestCase):
    def setUp(self):
        # The stall reader is exercised with a local double; compatibility is proved by test_forge_events.
        self.enterContext(mock.patch.object(forge_events, '_require_compatibility'))

    def stalls(self, version, kind):
        red = config.get('push-guard.stall_red_gate_s')
        gated = FIXED + timedelta(minutes=1)  # pushed at FIXED, gated after it
        now = gated + timedelta(seconds=red)
        forge = forge_doubles.with_surface(StallForge(SHA, f'mod/pr-{PR}', forge_events.rfc3339(FIXED)),
                                           'scripts/lib/stall_report.py')
        gate_port(forge, Clock(gated)).emit(
            kind, PAYLOADS[version](passed=kind == 'gate.passed'), version=version)
        port = forge_events.ForgeEvents(forge, Clock(now), 'test', 'stall')
        return [(item['reason'], item['last_gate']) for item in stall_report.stalls(port, REPO, PR, now)]

    def test_the_latest_v3_or_v4_verdict_drives_the_stall(self):
        for version in PAYLOADS:
            with self.subTest(version=version):
                self.assertIn(('red_gate', 'failed'), self.stalls(version, 'gate.failed'))
                self.assertNotIn('red_gate', [reason for reason, _ in self.stalls(version, 'gate.passed')])
                self.assertNotIn('no_push', [reason for reason, _ in self.stalls(version, 'gate.passed')])


if __name__ == '__main__':
    unittest.main(verbosity=1)
