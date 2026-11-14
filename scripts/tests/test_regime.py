"""The exception regime (D-260): the recorded state answers every lock, a lifted lock warns and emits lock.lifted, and the kept
locks (money, other people) never lift, whatever the state says."""
from datetime import datetime
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import forge_events  # noqa: E402
import regime  # noqa: E402

REPO = 'openuniversity-si/open-university'
SHA = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'


class Clock:
    def now(self):
        return datetime.fromisoformat('2026-11-01T07:30:00+00:00')


def recorded(active, kept=None):
    state = dict(regime.state(), active=active)
    if kept is not None:
        state['kept'] = kept
    return state


class Lifted(unittest.TestCase):
    def test_nothing_lifts_while_the_regime_is_off(self):
        self.assertFalse(regime.lifted('gate', recorded(False)))

    def test_an_active_regime_in_the_registry_names_who_granted_it_and_keeps_money_and_people(self):
        live = regime.state()
        if live['active']:
            self.assertTrue(live['granted_by'] and live['granted_at'] and live['exit'])
        self.assertEqual(sorted(live['kept']), ['money', 'people'])

    def test_an_ordinary_lock_lifts_in_an_active_regime(self):
        for lock in ('gate', 'merger', 'commit-plan', 'count-guards', 'structure', 'decision-claim', 'forge', 'literals'):
            self.assertTrue(regime.lifted(lock, recorded(True)), lock)

    def test_money_and_people_never_lift_in_any_regime(self):
        for active in (True, False):
            for lock in ('money', 'people'):
                self.assertFalse(regime.lifted(lock, recorded(active)), (lock, active))

    def test_the_kept_locks_are_those_of_the_record_and_the_default_keeps_money_and_people(self):
        self.assertEqual(sorted(regime.state()['kept']), ['money', 'people'])
        self.assertFalse(regime.lifted('secrets', recorded(True, kept=['money', 'people', 'secrets'])))
        self.assertTrue(regime.lifted('secrets', recorded(True)))


class Shared(unittest.TestCase):
    """The gate pins its store to `file`; the regime it judges by is read from the shared store (I-ddaca17c)."""

    def test_the_shared_state_reads_the_shared_store_and_a_kept_gate_does_not_lift(self):
        import config
        from unittest import mock
        live = {f'regime.exception_{f}': v for f, v in regime.state().items()}
        live.update({'regime.exception_active': True, 'regime.exception_kept': ['money', 'people', 'gate']})
        with mock.patch.object(config, 'shared', side_effect=lambda name, root=None: live[name]):
            shared = regime.state(shared=True)
            self.assertEqual(shared['kept'], ['money', 'people', 'gate'])
            self.assertFalse(regime.lifted('gate', shared))
            import gate_bypass
            self.assertFalse(gate_bypass.by_regime())


class Lift(unittest.TestCase):
    def setUp(self):
        self.adapter = forge_events.MemoryAdapter()
        self.port = forge_events.ForgeEvents(self.adapter, Clock(), regime.PRODUCER, 'run-1')
        self.said = []

    def lift(self, lock, active):
        state = dict(recorded(active), granted_by='Daniel', granted_at='01/11 04:11 BRT', exit='the flow is no longer limited')
        return regime.lift(lock, SHA, 'lane-4', self.port, REPO, recorded=state, out=self.said.append)

    def test_a_lifted_lock_warns_and_emits_lock_lifted(self):
        self.assertTrue(self.lift('gate', True))
        self.assertIn("the lock 'gate' is lifted", self.said[0])
        self.assertIn('Daniel', self.said[0])
        events = self.port.read(REPO)
        self.assertEqual([event['type'] for event in events], [regime.EVENT])
        payload = events[0]['payload']
        self.assertEqual((payload['lock'], payload['sha'], payload['lane']), ('gate', SHA, 'lane-4'))
        self.assertEqual(payload['time'], '2026-11-01T07:30:00.000Z')

    def test_a_kept_lock_or_an_inactive_regime_says_nothing_and_emits_nothing(self):
        self.assertFalse(self.lift('money', True))
        self.assertFalse(self.lift('people', True))
        self.assertFalse(self.lift('gate', False))
        self.assertEqual((self.said, self.port.read(REPO)), ([], []))


if __name__ == '__main__':
    unittest.main()
