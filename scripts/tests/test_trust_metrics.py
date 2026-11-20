"""Autonomy ladder contract and proposed configuration tests (D-353, C8)."""
import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))

import json_schema

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'trust-metrics.json').read_text(encoding='utf-8'))
SCHEMA_PATH = ROOT / 'contracts' / 'model' / 'autonomy.v1.json'
LADDER_PATH = ROOT / 'config' / 'governance' / 'autonomy-ladder.json'


class AutonomyContractAndConfig(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
        self.ladder = json.loads(LADDER_PATH.read_text(encoding='utf-8'))

    def test_contract_is_valid_json_schema_subset(self):
        self.assertEqual(self.schema.get('$schema'), json_schema.DIALECT)
        self.assertEqual(self.schema.get('$id'), 'contracts/model/autonomy.v1.json')
        self.assertEqual(json_schema.check_schema(self.schema), [])

    def test_proposed_autonomy_ladder_validates_and_stays_proposed(self):
        self.assertEqual(json_schema.validate(self.schema, self.ladder), [])
        self.assertEqual(self.ladder['state'], 'proposed')
        self.assertEqual(self.ladder['decision'], 'D-353')
        self.assertEqual(self.ladder['owner'], 'Daniel')
        self.assertEqual(self.ladder['history'], [])

    def test_ladder_defines_eight_indicators_with_full_targets(self):
        indicators = self.ladder['indicators']
        self.assertEqual(len(indicators), FIXTURE['expected_indicator_count'])
        numbers = sorted(item['number'] for item in indicators.values())
        self.assertEqual(numbers, FIXTURE['expected_indicator_numbers'])
        self.assertEqual(indicators['main_integrity']['target']['min_pass_rate'], 1)
        self.assertEqual(indicators['main_integrity']['target']['max_merges_while_red'], 0)
        self.assertEqual(indicators['change_failure_rework']['target']['max_escape_rate'], 0)
        self.assertEqual(indicators['first_pass_yield']['target']['min_first_pass_rate'], 1)
        self.assertEqual(indicators['first_pass_yield']['target']['max_flake_rate'], 0)
        self.assertEqual(indicators['independent_audit']['target']['min_clean_approval_rate'], 1)
        self.assertEqual(indicators['independent_audit']['target']['max_gaming_cases'], 0)
        self.assertEqual(indicators['human_override_rate']['target']['max_overrides'], 0)
        self.assertEqual(indicators['signal_to_overhead']['target']['min_value_share'],
                         FIXTURE['portfolio_targets']['min_value_share'])
        self.assertEqual(indicators['signal_to_overhead']['target']['max_meta_governance_share'],
                         FIXTURE['portfolio_targets']['max_meta_governance_share'])
        self.assertEqual(indicators['signal_to_overhead']['target']['max_sequential_same_scope_splits'], 0)
        self.assertEqual(indicators['production_health_and_cost']['target']['max_deploy_p100_s'], 1)
        self.assertEqual(indicators['production_health_and_cost']['target']['min_canary_pass_rate'], 1)
        self.assertEqual(indicators['production_health_and_cost']['target']['max_aws_monthly_usd'],
                         FIXTURE['aws_ceiling_usd'])
        self.assertEqual(indicators['security_posture']['target']['max_unapproved_tailorings'], 0)

    def test_levels_circuit_breakers_and_owner_locks(self):
        actual_levels = [
            {'level': item['level'], 'promotion_days': item['promotion_days'],
             'required_count': len(item['required_indicators'])}
            for item in self.ladder['levels']
        ]
        self.assertEqual(actual_levels, FIXTURE['expected_levels'])
        breakers = [item['indicator'] for item in self.ladder['circuit_breakers']]
        self.assertEqual(breakers, FIXTURE['expected_circuit_breakers'])
        self.assertEqual(len(self.ladder['always_owner_locked']), FIXTURE['expected_owner_locks'])

    def test_schema_refuses_invalid_level_or_missing_indicator(self):
        bad_level = copy.deepcopy(self.ladder)
        bad_level['levels'][0]['level'] = 'F'
        self.assertNotEqual(json_schema.validate(self.schema, bad_level), [])
        missing_indicator = copy.deepcopy(self.ladder)
        del missing_indicator['indicators']['security_posture']
        self.assertNotEqual(json_schema.validate(self.schema, missing_indicator), [])


if __name__ == '__main__':
    unittest.main()
