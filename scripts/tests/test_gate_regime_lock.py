#!/usr/bin/env python3
"""D-260: the gate lock asks the exception regime, on both sides. While the regime lifts 'gate' the bypass answers yes and the
train's tier 2 gives a marked green after printing the warning and emitting lock.lifted; while it does not, or while the lock is
kept, both behave as before. Fixtures only: no forge, no gate run."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import engine_role  # noqa: E402
import gate_bypass  # noqa: E402
import regime  # noqa: E402
import train  # noqa: E402

SHA = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'
REPO = 'openuniversity-si/open-university'


class Clock:
    def now(self):
        return datetime.fromisoformat('2026-11-01T07:30:00+00:00')


class Port:
    def __init__(self):
        self.clock, self.emitted = Clock(), []

    def emit(self, kind, payload, **_):
        self.emitted.append((kind, payload))


def state(active, kept=('money', 'people')):
    return dict(regime.state(), active=active, kept=list(kept), granted_by='Daniel', granted_at='01/11', exit='test')


def under(active, kept=('money', 'people')):
    return mock.patch.object(regime, 'state', return_value=state(active, kept))


class Bypass(unittest.TestCase):
    def enabled(self):
        with mock.patch.object(gate_bypass.config, 'shared', return_value=False):
            return gate_bypass.enabled({})

    def test_the_bypass_is_on_when_only_the_regime_lifts_the_gate_lock(self):
        with under(True):
            self.assertTrue(self.enabled())

    def test_the_bypass_is_off_when_the_regime_is_off(self):
        with under(False):
            self.assertFalse(self.enabled())

    def test_the_bypass_is_off_when_the_gate_lock_is_kept(self):
        with under(True, kept=('money', 'people', 'gate')):
            self.assertFalse(self.enabled())

    def test_an_unreadable_regime_lifts_nothing(self):
        with mock.patch.object(regime, 'state', side_effect=RuntimeError('store')):
            self.assertFalse(self.enabled())

    def test_the_environment_still_wins_over_the_regime(self):
        with under(True):
            self.assertFalse(gate_bypass.enabled({gate_bypass.ENV: '0'}))

    def test_announce_prints_and_emits_when_only_the_regime_lifted_it(self):
        port = Port()
        events = SimpleNamespace(ForgeEvents=lambda *args: port, adapter_from_config=lambda: None, clock_from_config=lambda: None)
        with under(True), mock.patch.object(gate_bypass, 'forge_events', events):
            self.assertTrue(gate_bypass.announce(ROOT, SHA, '12'))
        self.assertEqual([kind for kind, _ in port.emitted], ['lock.lifted'])
        self.assertEqual(port.emitted[0][1]['lock'], 'gate')

    def test_announce_does_nothing_while_the_regime_is_off(self):
        with under(False), mock.patch.object(regime, 'lift') as lift:
            self.assertFalse(gate_bypass.announce(ROOT, SHA, '12'))
        lift.assert_not_called()

    def test_an_event_that_cannot_be_emitted_never_turns_the_lifted_gate_red(self):
        def broken():
            raise RuntimeError('no forge')
        events = SimpleNamespace(adapter_from_config=broken)
        with under(True), mock.patch.object(gate_bypass, 'forge_events', events):
            self.assertTrue(gate_bypass.announce(ROOT, SHA, '12'))


class TierTwo(unittest.TestCase):
    def stub(self):
        recorded = []
        return SimpleNamespace(owner='train@lane-1', repo=REPO, renew=lambda port: None, last_run_ms=None, last_verdict=None,
                               record=lambda step, commit, result: recorded.append((step, commit, result.ok)), recorded=recorded)

    def test_tier_two_is_green_and_marked_while_the_regime_lifts_the_gate_lock(self):
        port, stub = Port(), self.stub()
        with under(True):
            result = train.Train.lifted_by_regime(stub, port, 'tier2', SHA)
        self.assertTrue(result.ok)
        self.assertIn('lifted by the exception regime', result.log)
        self.assertEqual(stub.recorded, [('tier2', SHA, True)])
        self.assertEqual([kind for kind, _ in port.emitted], ['lock.lifted'])
        self.assertEqual((port.emitted[0][1]['lock'], port.emitted[0][1]['lane']), ('gate', 'train@lane-1'))

    def test_tier_two_runs_as_before_while_the_regime_is_off(self):
        port, stub = Port(), self.stub()
        with under(False):
            self.assertIsNone(train.Train.lifted_by_regime(stub, port, 'tier2', SHA))
        self.assertEqual((port.emitted, stub.recorded), ([], []))

    def test_tier_two_runs_as_before_while_the_gate_lock_is_kept(self):
        port, stub = Port(), self.stub()
        with under(True, kept=('money', 'people', 'gate')):
            self.assertIsNone(train.Train.lifted_by_regime(stub, port, 'tier2', SHA))
        self.assertEqual(port.emitted, [])

    def test_an_unreadable_regime_leaves_tier_two_to_run(self):
        with mock.patch.object(regime, 'lift', side_effect=RuntimeError('store')):
            self.assertIsNone(train.Train.lifted_by_regime(self.stub(), Port(), 'tier2', SHA))

    def test_the_trains_gate_command_itself_is_untouched(self):
        self.assertIs(train.engine_role.CommandGate, engine_role.CommandGate)


if __name__ == '__main__':
    unittest.main()
