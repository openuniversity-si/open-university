"""The next free decision number (D-183): the base's last row and every number an open PR cites, the PR itself excluded.

The cases are in scripts/tests/fixtures/decision-next.json. Pure functions and a fake forge port; no network.
"""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import decision_next  # noqa: E402
from unittest import mock  # noqa: E402

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'decision-next.json').read_text())


class Reservation(unittest.TestCase):
    def test_each_case_offers_the_expected_number(self):
        for case in FIXTURE['cases']:
            with self.subTest(case=case['name']):
                self.assertEqual(f"D-{decision_next.next_free(FIXTURE['base'], case['texts'])}", case['expect'])

    def test_an_empty_base_starts_at_one(self):
        self.assertEqual(decision_next.next_free(''), 1)

    def test_the_pull_being_renumbered_does_not_reserve_its_own_number(self):
        pulls = FIXTURE['pulls']
        self.assertEqual(f"D-{decision_next.free_number(FIXTURE['base'], pulls, exclude=FIXTURE['excluded_pull'])}",
                         FIXTURE['expect_with_exclusion'])
        self.assertEqual(f"D-{decision_next.free_number(FIXTURE['base'], pulls)}", FIXTURE['expect_without_exclusion'])

    def test_base_numbers_read_only_rows(self):
        self.assertEqual(sorted(decision_next.base_numbers(FIXTURE['base'])), FIXTURE['base_numbers'])


class Clock(unittest.TestCase):
    def test_the_claim_time_is_the_brazilian_clock_of_the_machine(self):
        from datetime import datetime
        when = datetime.fromisoformat(FIXTURE['clock']['utc'])
        self.assertEqual(decision_next.brt(when), FIXTURE['clock']['brt'])


class Claims(unittest.TestCase):
    def test_the_claimed_numbers_come_from_the_claim_branches_only(self):
        lines = '\n'.join(FIXTURE['claims']['lines']) + '\n'
        done = type('Done', (), {'returncode': 0, 'stdout': lines})()
        with mock.patch.object(decision_next.subprocess, 'run', return_value=done):
            self.assertEqual(sorted(decision_next.claimed(ROOT)), FIXTURE['claims']['expect'])

    def test_an_unreadable_remote_claims_nothing(self):
        done = type('Done', (), {'returncode': 1, 'stdout': ''})()
        with mock.patch.object(decision_next.subprocess, 'run', return_value=done):
            self.assertEqual(decision_next.claimed(ROOT), set())

    def test_a_refused_claim_moves_to_the_next_number(self):
        """A race: another lane takes the number between this lane's read and its push, so the first push is refused."""
        taken = set()
        pushes = []

        def run(args, **_kwargs):
            number = int(args[-1].rsplit('-', 1)[1])
            pushes.append(number)
            refused = number in taken
            if len(pushes) == FIXTURE['claims']['race_first']:
                taken.add(number)
                refused = True
            elif not refused:
                taken.add(number)
            return type('Done', (), {'returncode': 1 if refused else 0, 'stdout': '', 'stderr': ''})()

        def claimed(*_args, **_kwargs):
            return set() if len(pushes) == FIXTURE['claims']['race_first'] - 1 else set(taken)
        with mock.patch.object(decision_next, 'open_pulls', return_value=[]), \
                mock.patch.object(decision_next, 'base_text', return_value=FIXTURE['base']), \
                mock.patch.object(decision_next, 'claimed', side_effect=claimed), \
                mock.patch.object(decision_next, 'claim_commit', return_value='sha'), \
                mock.patch.object(decision_next, '_repo', return_value='x/y'):
            number = decision_next.reserve(ROOT, run=run)
        self.assertEqual(len(pushes), FIXTURE['claims']['race_pushes'])
        self.assertEqual(pushes[1], pushes[0] + FIXTURE['claims']['race_step'])
        self.assertEqual(number, pushes[1])
        self.assertIn(number, taken)

    def test_no_claim_after_the_tries_is_none(self):
        def run(args, **_kwargs):
            return type('Done', (), {'returncode': 1, 'stdout': '', 'stderr': ''})()
        with mock.patch.object(decision_next, 'open_pulls', return_value=[]), \
                mock.patch.object(decision_next, 'base_text', return_value=FIXTURE['base']), \
                mock.patch.object(decision_next, 'claimed', return_value=set()), \
                mock.patch.object(decision_next, 'claim_commit', return_value='sha'), \
                mock.patch.object(decision_next, '_repo', return_value='x/y'):
            self.assertIsNone(decision_next.reserve(ROOT, tries=FIXTURE['claims']['tries'], run=run))


class FakePort:
    """The forge port's open_pulls and pull over a fixture listing; `fail` makes the forge refuse."""

    def __init__(self, listing, fail=False):
        self.listing, self.fail, self.seen = listing, fail, []

    def open_pulls(self, repo, base=None):
        self.seen.append(('open_pulls', repo, base))
        if self.fail:
            raise RuntimeError('forbidden')
        return [{'number': item['number'], 'head_ref': 'h', 'head_sha': 's', 'draft': False} for item in self.listing]

    def pull(self, repo, number):
        self.seen.append(('pull', repo, number))
        return next(item for item in self.listing if item['number'] == number)


class OpenPulls(unittest.TestCase):
    def test_the_open_pulls_come_from_the_port_list_and_each_change(self):
        port = FakePort(FIXTURE['listing'])
        pulls = decision_next.open_pulls('openuniversity-si/open-university', port=port)
        self.assertEqual(port.seen[0], ('open_pulls', 'openuniversity-si/open-university', None))
        self.assertEqual(len(port.seen), 1 + len(FIXTURE['listing_expect']))
        self.assertEqual(pulls, FIXTURE['listing_expect'])

    def test_an_unreadable_forge_reserves_nothing(self):
        self.assertEqual(decision_next.open_pulls('x/y', port=FakePort(FIXTURE['listing'], fail=True)), [])

    def test_the_default_port_names_this_module_as_its_consumer(self):
        import forge_events
        with mock.patch.object(forge_events, 'ForgeEvents', side_effect=lambda *args, **kwargs: kwargs) as built, \
                mock.patch.object(forge_events, 'adapter_from_config'), mock.patch.object(forge_events, 'clock_from_config'):
            self.assertEqual(decision_next.forge()['consumer'], 'scripts/lib/decision_next.py')
        built.assert_called_once()


class Regime(unittest.TestCase):
    def _refusing(self):
        def run(args, **_kwargs):
            return type('Done', (), {'returncode': 1, 'stdout': '', 'stderr': ''})()
        return run

    def _patched(self):
        return [mock.patch.object(decision_next, 'open_pulls', return_value=[]),
                mock.patch.object(decision_next, 'base_text', return_value=FIXTURE['base']),
                mock.patch.object(decision_next, 'claimed', return_value=set()),
                mock.patch.object(decision_next, 'claim_commit', return_value='sha'),
                mock.patch.object(decision_next, '_repo', return_value='x/y')]

    def test_a_refused_claim_takes_the_next_free_number_when_the_regime_lifts_the_claim(self):
        patches = self._patched()
        for patch in patches:
            patch.start()
        try:
            number = decision_next.reserve(ROOT, tries=FIXTURE['claims']['tries'], run=self._refusing(), lifted=True)
        finally:
            for patch in patches:
                patch.stop()
        self.assertIsNotNone(number)

    def test_a_refused_claim_is_none_outside_the_regime(self):
        patches = self._patched()
        for patch in patches:
            patch.start()
        try:
            number = decision_next.reserve(ROOT, tries=FIXTURE['claims']['tries'], run=self._refusing(), lifted=False)
        finally:
            for patch in patches:
                patch.stop()
        self.assertIsNone(number)


class LiftedLock(unittest.TestCase):
    def test_without_the_regime_module_the_lock_stands(self):
        with mock.patch.dict(sys.modules, {'regime': None}):
            self.assertFalse(decision_next._lifted('decision-claim'))

    def test_the_lock_follows_the_regime_module(self):
        fake = type('Regime', (), {'lifted': staticmethod(lambda lock: lock == 'decision-claim')})
        with mock.patch.dict(sys.modules, {'regime': fake}):
            self.assertTrue(decision_next._lifted('decision-claim'))
            self.assertFalse(decision_next._lifted('structure'))


if __name__ == '__main__':
    unittest.main()
