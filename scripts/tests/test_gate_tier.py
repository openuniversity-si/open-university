"""GX-11 (D-070): the gate tier is explicit (OU_GATE_TIER from gate-hooks/tier.sh) and every reader keys on it. Hermetic."""
import json
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import config  # noqa: E402
import gate_tier  # noqa: E402

HOOK = ROOT / 'scripts' / 'lib' / 'gate-hooks' / 'tier.sh'
DEV = ('dev',)  # the deprecated forge-events.tier1_gate_modes default, as gate_report passes it in
SHA = '0123456789abcdef0123456789abcdef01234567'


def default(name):
    owner = name.split('.', 1)[0]
    return json.loads((ROOT / 'config' / 'registry' / f'{owner}.json').read_text())['properties'][name]['default']


PR, BATCH, BATTERY, TREE = (default(f'gate-tier.{name}') for name in ('per_pr', 'batch', 'battery', 'working_tree'))
REGISTRY = {'gate-tier.per_pr': PR, 'gate-tier.batch': BATCH, 'gate-tier.battery': BATTERY, 'gate-tier.working_tree': TREE,
            'gate-tier.cacheable_tiers': [PR],
            'forge-events.adjudicated_tiers': [PR, BATCH],
            # D-076's rollback state, so the D-065 (5) cases below keep their meaning; Content covers the default
            'gate.content_cache_enabled': False, 'gate-tier.content_cacheable_tiers': [PR, BATCH]}


def tier(value):
    """Run with OU_GATE_TIER set to value (None: unset)."""
    env = {key: item for key, item in os.environ.items() if key != gate_tier.ENV}
    if value is not None:
        env[gate_tier.ENV] = gate_tier.bind(value)
    return mock.patch.dict(os.environ, env, clear=True)


def registry(changed=None):
    values = {**REGISTRY, **(changed or {})}
    return mock.patch.object(config, 'get', side_effect=values.__getitem__)


def hooked(script, env=None):
    return subprocess.run(['bash', '-c', f'set -u; source "$1"; {script}gate_hook_tier; printf %s "$OU_GATE_TIER"',
                           '_', str(HOOK)], capture_output=True, text=True, check=True, stdin=subprocess.DEVNULL,
                          env={**(env or os.environ), 'OU_CONFIG_STORE': 'file'}).stdout


def derived(**names):
    """OU_GATE_TIER after gate_hook_tier with gate-local's parsed variables (`pr`, `sha`, `tier3`) set as given."""
    env = {key: item for key, item in os.environ.items() if key != gate_tier.ENV}
    return hooked(''.join(f'{name}={value!r}; ' for name, value in names.items()), env)


class Registry(unittest.TestCase):
    def test_the_defaults_cache_tier_1_only_and_adjudicate_tiers_1_and_2(self):
        self.assertEqual((PR, BATCH, BATTERY, TREE), tuple(sorted({PR, BATCH, BATTERY})) + (PR,))
        self.assertEqual(default('gate-tier.cacheable_tiers'), [PR])
        self.assertEqual(default('forge-events.adjudicated_tiers'), [PR, BATCH])

    def test_the_defaults_reuse_by_content_at_tiers_1_and_2_never_3(self):
        """D-076 (P-56): tier 3, the battery, is the periodic full net and never reuses."""
        self.assertIs(default('gate.content_cache_enabled'), True)
        self.assertEqual(default('gate-tier.content_cacheable_tiers'), [PR, BATCH])

    def test_the_old_kd1_key_stays_readable_for_the_callers_that_pass_it_in(self):
        self.assertEqual(default('forge-events.tier1_gate_modes'), list(DEV))


class Derive(unittest.TestCase):
    def test_first_match_wins(self):
        with registry():
            self.assertEqual(gate_tier.derive('', SHA, True), BATTERY)
            self.assertEqual(gate_tier.derive('N', SHA, False), PR)
            self.assertEqual(gate_tier.derive('', SHA, False), BATCH)
            self.assertEqual(gate_tier.derive('', '', False), TREE)


class Explicit(unittest.TestCase):
    def test_only_a_positive_integer_bound_to_this_tooling_is_explicit(self):
        for value in (PR, BATCH, BATTERY):
            self.assertEqual(gate_tier.explicit({gate_tier.ENV: f' {gate_tier.bind(value)} '}), value)
        for value in ('', '0', 'x', '-1', 'one'):
            self.assertIsNone(gate_tier.explicit({gate_tier.ENV: f'{value}@{gate_tier.LIB}'}), value)
        self.assertIsNone(gate_tier.explicit({}))

    def test_a_tier_of_another_tooling_or_unbound_is_ignored(self):
        """A pinned run: the invoker's tier must not reach the code under test, a checkout of its own."""
        self.assertIsNone(gate_tier.explicit({gate_tier.ENV: str(BATCH)}))
        self.assertIsNone(gate_tier.explicit({gate_tier.ENV: f'{BATCH}@/elsewhere/scripts/lib'}))
        with mock.patch.dict(os.environ, {gate_tier.ENV: f'{BATCH}@/elsewhere/scripts/lib'}):
            self.assertIsNone(gate_tier.current('tier3', DEV))
            self.assertTrue(gate_tier.cacheable('dev', DEV))


class Current(unittest.TestCase):
    def test_the_verdict_tier_is_the_explicit_tier_whatever_the_mode(self):
        for value in (PR, BATCH, BATTERY):
            for mode in ('dev', 'db', 'tier3', 'noite', 'pr'):
                with tier(value):
                    self.assertEqual(gate_tier.current(mode, DEV), value)

    def test_without_a_tier_the_mode_decides_as_before(self):
        with tier(None):
            self.assertEqual(gate_tier.current('dev', DEV), PR)
            self.assertIsNone(gate_tier.current('tier3', DEV))


class Cacheable(unittest.TestCase):
    def test_with_the_content_cache_off_tier_1_caches_and_tiers_2_and_3_never_do(self):
        with registry():
            for value, expected in ((PR, True), (BATCH, False), (BATTERY, False)):
                with tier(value):
                    self.assertIs(gate_tier.cacheable('dev', DEV), expected, value)
                    self.assertIs(gate_tier.script_tests_cacheable(), expected, value)

    def test_by_content_tiers_1_and_2_cache_and_tier_3_never_does(self):
        with registry({'gate.content_cache_enabled': True}):
            for value, expected in ((PR, True), (BATCH, True), (BATTERY, False)):
                with tier(value):
                    self.assertIs(bool(gate_tier.content_cacheable()), value in (PR, BATCH), value)
                    self.assertIs(gate_tier.cacheable('dev', DEV), expected, value)
                    self.assertIs(gate_tier.script_tests_cacheable(), expected, value)

    def test_content_reuse_never_reaches_another_mode_or_an_unknown_tier(self):
        with registry({'gate.content_cache_enabled': True}):
            with tier(BATCH):
                self.assertFalse(gate_tier.cacheable('noite', DEV))
            with tier(None):
                self.assertFalse(gate_tier.content_cacheable())

    def test_no_mode_gains_the_result_cache(self):
        with registry(), tier(PR):
            self.assertFalse(gate_tier.cacheable('db', DEV))
            self.assertFalse(gate_tier.cacheable('noite', DEV))

    def test_the_rollback_key_lets_tier_2_cache_again(self):
        with registry({'gate-tier.cacheable_tiers': [PR, BATCH]}), tier(BATCH):
            self.assertTrue(gate_tier.cacheable('dev', DEV))
            self.assertTrue(gate_tier.script_tests_cacheable())

    def test_without_a_tier_the_mode_decides_and_script_tests_cache(self):
        with tier(None):
            self.assertTrue(gate_tier.cacheable('dev', DEV))
            self.assertFalse(gate_tier.cacheable('tier3', DEV))
            self.assertTrue(gate_tier.script_tests_cacheable())


class Adjudicated(unittest.TestCase):
    def test_the_kd1_switch_keys_on_the_tier_not_the_mode(self):
        with registry():
            for value, expected in ((PR, True), (BATCH, True), (BATTERY, False)):
                with tier(value):
                    # the mode list says the opposite, so only the tier can decide
                    self.assertIs(gate_tier.adjudicated('tier3' if expected else 'dev', DEV), expected, value)

    def test_adjudicated_tiers_is_the_switch(self):
        with registry({'forge-events.adjudicated_tiers': [PR]}), tier(BATCH):
            self.assertFalse(gate_tier.adjudicated('dev', DEV))

    def test_without_a_tier_the_modes_passed_in_still_decide(self):
        """GX-13 #729 reads the old key through gate_adjudicate: its calls keep working unchanged."""
        with tier(None):
            self.assertTrue(gate_tier.adjudicated('dev', DEV))
            self.assertFalse(gate_tier.adjudicated('db', DEV))
            self.assertTrue(gate_tier.adjudicated('db', ('dev', 'db')))


class Hook(unittest.TestCase):
    """D-B5 on the real invocations, through the hook gate-local calls; the train and battery commands are unchanged."""

    def test_the_per_pr_gate_is_tier_1(self):
        self.assertEqual(derived(pr='N'), gate_tier.bind(PR))                     # gate-dev --pr, gate-db --pr
        self.assertEqual(derived(pr='N', sha=SHA), gate_tier.bind(PR))            # gate_noite: --noite --sha --pr

    def test_a_sha_without_a_pr_is_tier_2(self):
        self.assertEqual(derived(sha=SHA), gate_tier.bind(BATCH))                 # train.tier2_command: gate-batch, --dev --sha

    def test_tier3_is_tier_3(self):
        self.assertEqual(derived(sha=SHA, tier3='1'), gate_tier.bind(BATTERY))    # battery.tier3_command: --tier3 --sha

    def test_the_working_tree_is_tier_1_and_unset_variables_do_not_fail(self):
        self.assertEqual(derived(), gate_tier.bind(TREE))         # gate-quiet; set -u with nothing parsed

    def test_the_hook_overrides_a_tier_inherited_from_an_outer_run(self):
        self.assertEqual(hooked('pr=N; ', {**os.environ, gate_tier.ENV: gate_tier.bind(BATCH)}), gate_tier.bind(PR))

    def test_a_tier_that_cannot_be_derived_stops_the_gate(self):
        done = subprocess.run(['bash', '-c', 'source "$1"; py=false; gate_hook_tier; echo continued', '_', str(HOOK)],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertNotEqual(done.returncode, 0)
        self.assertNotIn('continued', done.stdout)
        self.assertIn('cannot derive the tier', done.stderr)


if __name__ == '__main__':
    unittest.main()
