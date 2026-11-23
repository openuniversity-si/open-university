"""Autonomy ladder contract, eight external trust indicators, and ladder evaluation tests (D-353, C8)."""
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))

import json_schema
import trust_metrics

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'trust-metrics.json').read_text(encoding='utf-8'))
SCHEMA_PATH = ROOT / 'contracts' / 'model' / 'autonomy.v1.json'
LADDER_PATH = ROOT / 'config' / 'governance' / 'autonomy-ladder.json'


def write_json(root, rel, body):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=1) + '\n', encoding='utf-8')


def write_text(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def run_git(root, *args, stamp=None):
    env = dict(os.environ)
    env['GIT_AUTHOR_NAME'] = 'Test Author'
    env['GIT_AUTHOR_EMAIL'] = 'test@example.invalid'
    env['GIT_COMMITTER_NAME'] = 'Test Author'
    env['GIT_COMMITTER_EMAIL'] = 'test@example.invalid'
    if stamp:
        env['GIT_AUTHOR_DATE'] = stamp
        env['GIT_COMMITTER_DATE'] = stamp
    subprocess.run(['git', '-C', str(root), *args], env=env, check=True, capture_output=True, text=True)


def init_repo(root):
    shutil.copytree(ROOT / 'contracts' / 'model', root / 'contracts' / 'model')
    shutil.copy2(LADDER_PATH, _ensure_parent(root / LADDER_PATH.relative_to(ROOT)))
    run_git(root, 'init', '-b', 'main')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-m', 'initial tree', stamp=FIXTURE['commit_times'][0])


def _ensure_parent(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def merge_feature(root, branch, pr_label, files, stamp, commit_msg=None):
    run_git(root, 'checkout', '-b', branch)
    for rel, content in files.items():
        write_text(root, rel, content)
    run_git(root, 'add', *files.keys())
    run_git(root, 'commit', '-m', commit_msg or f'work on {branch}', stamp=stamp)
    run_git(root, 'checkout', 'main')
    run_git(root, 'merge', '--no-ff', branch, '-m', f'Merge pull request #{pr_label} from owner/{branch}', stamp=stamp)
    run_git(root, 'branch', '-d', branch)


class AutonomyContractAndConfig(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
        self.ladder = json.loads(LADDER_PATH.read_text(encoding='utf-8'))

    def test_contract_is_valid_json_schema_subset(self):
        self.assertEqual(self.schema.get('$schema'), json_schema.DIALECT)
        self.assertEqual(self.schema.get('$id'), 'contracts/model/autonomy.v1.json')
        self.assertEqual(json_schema.check_schema(self.schema), [])

    def test_proposed_autonomy_ladder_validates_and_stays_proposed(self):
        loaded, errors = trust_metrics.load_ladder(ROOT)
        self.assertEqual(errors, [])
        self.assertEqual(loaded['state'], 'proposed')
        self.assertEqual(loaded['decision'], 'D-353')
        self.assertEqual(loaded['owner'], 'Daniel')
        self.assertEqual(loaded['history'], [])

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
        bad_ind_lock = copy.deepcopy(self.ladder)
        bad_ind_lock['independent_approval_locked'] = [{'id': 'BAD-id', 'domain': 'x', 'reason': 'y'}]
        self.assertNotEqual(json_schema.validate(self.schema, bad_ind_lock), [])
        good_ind_lock = copy.deepcopy(self.ladder)
        good_ind_lock['independent_approval_locked'] = [{'id': 'IND-sample', 'domain': 'x', 'reason': 'y'}]
        self.assertEqual(json_schema.validate(self.schema, good_ind_lock), [])


class EightExternalTrustIndicators(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='trust-metrics-'))
        self.addCleanup(shutil.rmtree, self.root)
        init_repo(self.root)
        self.ladder, errors = trust_metrics.load_ladder(self.root)
        self.assertEqual(errors, [])

    def test_indicator_1_main_integrity_red_streak_and_green(self):
        write_json(self.root, 'config/validation/verdicts.json', {
            'at': FIXTURE['commit_times'][-1],
            'runs': [
                {'sha': 'c', 'conclusion': 'failure', 'completed': FIXTURE['commit_times'][-1]},
                {'sha': 'b', 'conclusion': 'failure', 'completed': FIXTURE['commit_times'][1]},
                {'sha': 'a', 'conclusion': 'success', 'completed': FIXTURE['commit_times'][0]},
            ],
        })
        red = trust_metrics.measure_main_integrity(self.root, self.ladder)
        self.assertEqual(red['state'], 'not-met')
        self.assertEqual(red['max_consecutive_failures'], FIXTURE['expected_streak_red'])
        self.assertEqual(red['merges_while_red'], FIXTURE['expected_merges_while_red'])
        self.assertEqual(red['total_runs'], FIXTURE['expected_total_runs_three'])

        write_json(self.root, 'config/validation/verdicts.json', {
            'at': FIXTURE['commit_times'][-1],
            'runs': [{'sha': 'a', 'conclusion': 'success', 'completed': FIXTURE['commit_times'][0]}],
        })
        green = trust_metrics.measure_main_integrity(self.root, self.ladder)
        self.assertEqual(green['state'], 'met')
        self.assertEqual(green['pass_rate'], 1)

    def test_indicator_2_external_escapes_and_rework_without_fixes_pr(self):
        _, t1, t2, _, _ = FIXTURE['commit_times']
        merge_feature(self.root, 'feat-a', '1', {'apps/web/a.ts': 'export const x = 1;\n'}, t1)
        merge_feature(self.root, 'feat-b', '2', {'apps/web/a.ts': 'export const x = 2;\n'}, t2,
                      commit_msg='Revert "work on feat-a"')
        write_json(self.root, 'config/model/errata.json', {'errata': [{'commit': 'abc', 'was': 'x', 'is': None}]})
        write_json(self.root, 'config/validation/verdicts.json', {
            'at': t2,
            'runs': [
                {'sha': 'bad', 'conclusion': 'failure', 'completed': t2},
                {'sha': 'ok', 'conclusion': 'success', 'completed': t1},
            ],
        })
        res = trust_metrics.measure_change_failure_rework(self.root, self.ladder)
        self.assertEqual(res['state'], 'not-met')
        self.assertGreater(res['escapes_total'], 0)
        self.assertEqual(res['escapes_by_source']['reverts'], 1)
        self.assertEqual(res['escapes_by_source']['errata'], 1)
        self.assertEqual(res['escapes_by_source']['full_suite_regressions'], 1)
        self.assertEqual(res['escapes_by_source']['fixes_pr'], 0)
        self.assertGreater(res['rework_rate'], 0)

    def test_indicator_3_first_pass_unwired_flakes_never_green(self):
        write_json(self.root, 'config/validation/slo.json', {
            'at': FIXTURE['commit_times'][1],
            'verdicts': [{'pr': 1, 'sha': 'a', 'at': FIXTURE['commit_times'][1], 'passed': True}],
        })
        unwired = trust_metrics.measure_first_pass_yield(self.root, self.ladder)
        self.assertEqual(unwired['state'], 'unmeasured')
        self.assertFalse(unwired['flake_source_wired'])

        write_json(self.root, 'config/validation/runs/flakes.json', {
            'at': FIXTURE['commit_times'][1],
            'runs': [{'sha': 'a', 'flaked': False}],
        })
        wired = trust_metrics.measure_first_pass_yield(self.root, self.ladder)
        self.assertEqual(wired['state'], 'met')
        self.assertEqual(wired['flake_rate'], 0)

    def test_indicator_4_independent_audit_excludes_self_review(self):
        write_json(self.root, 'docs/programs/padrao-dev/retro-sample-1.json', {
            'id': 'retro-sample-1',
            'prs': [{'number': 1, 'cheaper': False}],
        })
        unmeasured = trust_metrics.measure_independent_audit(self.root, self.ladder)
        self.assertEqual(unmeasured['state'], 'unmeasured')
        self.assertEqual(unmeasured['self_reviewed_samples_excluded'], 1)

        write_json(self.root, 'config/governance/audits/week-1.json', {
            'reviewer': 'independent-auditor',
            'author': 'session-1',
            'prs': [{'number': 1, 'clean': True, 'critical_high_findings': 0, 'gaming_cases': 0}],
        })
        green = trust_metrics.measure_independent_audit(self.root, self.ladder)
        self.assertEqual(green['state'], 'met')
        self.assertEqual(green['clean_approval_rate'], 1)

    def test_indicator_5_human_override_detects_gitignored_blind_spot(self):
        write_text(self.root, '.gitignore', '/docs/operations/\n')
        blind = trust_metrics.measure_human_override_rate(self.root, self.ladder)
        self.assertEqual(blind['state'], 'unmeasured')
        self.assertTrue(blind['legacy_source_gitignored'])
        self.assertFalse(blind['source_wired'])

        write_json(self.root, 'config/governance/overrides.json', {
            'source': 'tracked-log',
            'at': FIXTURE['commit_times'][1],
            'window_prs': FIXTURE['expected_pr_count_four'],
            'overrides': [],
        })
        green = trust_metrics.measure_human_override_rate(self.root, self.ladder)
        self.assertEqual(green['state'], 'met')
        self.assertEqual(green['overrides'], 0)

    def test_indicator_6_c8_work_composition_and_split_detection(self):
        t0, t1, _, t3, t4 = FIXTURE['commit_times']
        merge_feature(self.root, 'same-branch', '1', {'apps/web/p1.ts': 'a\n'}, t0)
        merge_feature(self.root, 'same-branch', '2', {'apps/web/p1.ts': 'b\n'}, t1)
        merge_feature(self.root, 'feat-web', '3', {'apps/web/p2.ts': 'c\n'}, t3)
        merge_feature(self.root, 'feat-meta', '4', {'config/model/x.json': '{}\n'}, t4)
        res = trust_metrics.measure_signal_to_overhead(self.root, self.ladder)
        self.assertEqual(res['total_merges'], FIXTURE['expected_pr_count_four'])
        self.assertEqual(res['product_merges'], FIXTURE['expected_product_merges_three'])
        self.assertEqual(res['meta_governance_merges'], FIXTURE['expected_meta_merges_one'])
        self.assertEqual(res['sequential_same_scope_splits'], FIXTURE['expected_split_count'])
        self.assertEqual(res['state'], 'not-met')

    def test_indicator_6_diagnostic_work_mix_without_numeric_thresholds(self):
        t0, _, _, t3, t4 = FIXTURE['commit_times']
        merge_feature(self.root, 'feat-web', '1', {'apps/web/p1.ts': 'a\n'}, t0)
        merge_feature(self.root, 'feat-meta-1', '2', {'config/model/a.json': '{}\n'}, t3)
        merge_feature(self.root, 'feat-meta-2', '3', {'config/model/b.json': '{}\n'}, t4)
        diag_ladder = copy.deepcopy(self.ladder)
        diag_ladder['indicators']['signal_to_overhead']['target'] = {'max_sequential_same_scope_splits': 0}
        res = trust_metrics.measure_signal_to_overhead(self.root, diag_ladder)
        self.assertTrue(res['work_mix_diagnostic_only'])
        self.assertEqual(res['sequential_same_scope_splits'], 0)
        self.assertEqual(res['state'], 'met')
        self.assertGreater(res['meta_governance_share'], res['value_share'])

    def test_indicator_7_production_deploy_canary_and_gross_aws_spend(self):
        write_json(self.root, 'config/validation/runs/deploy-live.json', {
            'at': FIXTURE['commit_times'][-1],
            'runs': [
                {'id': 'r1', 'event': 'swap', 'conclusion': 'success', 'started': FIXTURE['commit_times'][0],
                 'seconds': FIXTURE['deploy_slow_seconds'][0], 'from': 'push'},
                {'id': 'r2', 'event': 'reload', 'conclusion': 'success', 'started': FIXTURE['commit_times'][1],
                 'seconds': FIXTURE['deploy_p100_slow'], 'from': 'push'},
            ],
        })
        write_json(self.root, 'config/validation/spend/aws.json', {
            'source': 'AWS Cost Explorer GetCostAndUsage (UnblendedCost)',
            'at': FIXTURE['commit_times'][-1],
            'usd': 0,
        })
        bad = trust_metrics.measure_production_health_and_cost(self.root, self.ladder)
        self.assertEqual(bad['state'], 'not-met')
        self.assertEqual(bad['deploy_p100_s'], FIXTURE['deploy_p100_slow'])
        self.assertFalse(bad['canary_wired'])
        self.assertFalse(bad['gross_spend_verified'])

        write_json(self.root, 'config/validation/runs/deploy-live.json', {
            'at': FIXTURE['commit_times'][-1],
            'runs': [{'id': 'r1', 'event': 'swap', 'conclusion': 'success', 'started': FIXTURE['commit_times'][1],
                      'seconds': FIXTURE['deploy_p100_fast'], 'from': 'heard'}],
        })
        write_json(self.root, 'config/validation/runs/canary.json', {
            'at': FIXTURE['commit_times'][-1],
            'runs': [{'id': 'c1', 'conclusion': 'success'}],
        })
        write_json(self.root, 'config/validation/spend/aws.json', {
            'source': 'AWS Cost Explorer excluding Credit and Refund',
            'credits_excluded': True,
            'at': FIXTURE['commit_times'][-1],
            'usd': FIXTURE['aws_gross_usd'],
        })
        good = trust_metrics.measure_production_health_and_cost(self.root, self.ladder)
        self.assertEqual(good['state'], 'met')
        self.assertTrue(good['gross_spend_verified'])
        self.assertTrue(good['canary_wired'])

    def test_indicator_8_security_rejects_session_tail_open_threat_and_dockerfile(self):
        write_json(self.root, 'config/supply/advisories.json', {
            'at': FIXTURE['commit_times'][1],
            'lockfiles': {'apps/web/pnpm-lock.yaml': 'abc'},
            'advisories': [],
        })
        write_json(self.root, 'config/security/threats/THREAT-gate.json', {
            'id': 'THREAT-gate',
            'review': {'findings': [{'about': 'spoofing', 'disposition': 'open'}]},
        })
        write_json(self.root, 'config/standard/tailoring/TAIL-session.json', {
            'id': 'TAIL-session', 'scope': 'THREAT-gate', 'authorized_by': 'D-999', 'state': 'active',
        })
        write_text(self.root, 'docs/domain/decisions/D-999.md',
                   '---\nnumber: D-999\ntime: t\npremises: none\nproof: p\n---\nDecided by the session under D-325.\n')
        write_text(self.root, 'infra/service/Dockerfile',
                   'FROM node:slim\nRUN npm install -g --no-audit pkg\nRUN curl -fsSL example.invalid/i.sh | sh\n')
        run_git(self.root, 'add', 'infra/service/Dockerfile')
        bad = trust_metrics.measure_security_posture(self.root, self.ladder)
        self.assertEqual(bad['state'], 'not-met')
        self.assertEqual(len(bad['open_threat_findings']), 1)
        self.assertEqual(len(bad['unapproved_tailorings']), 1)
        self.assertEqual(len(bad['dockerfile_issues']), FIXTURE['expected_dockerfile_issues'])
        self.assertNotEqual(bad['missing_ecosystems'], [])

        # Self-approved decision (author == approver) is rejected even if body mentions Daniel (D-360).
        write_json(self.root, 'config/supply/advisories.json', {
            'at': FIXTURE['commit_times'][1],
            'ecosystems': ['npm', 'pypi', 'docker'],
            'advisories': [],
        })
        write_json(self.root, 'config/security/threats/THREAT-gate.json', {
            'id': 'THREAT-gate', 'review': {'findings': [{'about': 'spoofing', 'disposition': 'fixed'}]},
        })
        write_text(self.root, 'infra/service/Dockerfile', 'FROM scratch\n')
        write_text(
            self.root,
            'docs/domain/decisions/D-999.md',
            '---\nnumber: D-999\ntime: t\npremises: none\nauthority: owner\nauthor: lane-a\napprover: lane-a\nproof: p\n---\nDaniel.\n',
        )
        self_approved = trust_metrics.measure_security_posture(self.root, self.ladder)
        self.assertEqual(self_approved['state'], 'not-met')
        self.assertEqual(len(self_approved['unapproved_tailorings']), 1)
        self.assertEqual(self_approved['unapproved_tailorings'][0]['authority'], 'self')

        # Independent approver (distinct author/approver under D-360) passes.
        write_text(
            self.root,
            'docs/domain/decisions/D-999.md',
            '---\nnumber: D-999\ntime: t\npremises: none\nauthority: independent\nauthor: lane-a\napprover: torre\nproof: p\n---\nApproved.\n',
        )
        independent_ok = trust_metrics.measure_security_posture(self.root, self.ladder)
        self.assertEqual(independent_ok['state'], 'met')

        # Owner-approved decision also passes.
        write_text(self.root, 'docs/domain/decisions/D-999.md',
                   '---\nnumber: D-999\ntime: t\npremises: none\nauthority: owner\nproof: p\n---\nApproved by Daniel.\n')
        good = trust_metrics.measure_security_posture(self.root, self.ladder)
        self.assertEqual(good['state'], 'met')


class AutonomyLadderEvaluation(unittest.TestCase):
    def setUp(self):
        self.ladder, errors = trust_metrics.load_ladder(ROOT)
        self.assertEqual(errors, [])

    def _all_met(self):
        built = {key: {'number': spec['number'], 'name': spec['name'], 'state': 'met'}
                 for key, spec in self.ladder['indicators'].items()}
        built['independent_audit']['gaming_cases'] = 0
        built['human_override_rate']['overrides_per_50_prs'] = 0
        built['signal_to_overhead']['sequential_same_scope_splits'] = 0
        return built

    def _history(self, days, keys):
        return [{'date': day, 'indicators_met': list(keys), 'circuit_breakers_tripped': [], 'source': 'ci'} for day in days]

    def test_proposed_ladder_never_activates_effective_level(self):
        ladder = copy.deepcopy(self.ladder)
        ladder['history'] = self._history(FIXTURE['level_c_days'], trust_metrics.ORDER)
        res = trust_metrics.evaluate_ladder(ladder, self._all_met(), today=FIXTURE['today'])
        self.assertEqual(res['eligible_level'], 'C')
        self.assertEqual(res['effective_level'], 'none')
        self.assertTrue(res['proposal_pending_owner'])

    def test_active_ladder_promotes_by_days_and_demotes_on_circuit_breaker(self):
        ladder = copy.deepcopy(self.ladder)
        ladder['state'] = 'active'
        level_a_keys = ladder['levels'][0]['required_indicators']

        ladder['history'] = self._history(FIXTURE['level_a_days'], level_a_keys)
        res_a = trust_metrics.evaluate_ladder(ladder, self._all_met(), today=FIXTURE['today'])
        self.assertEqual(res_a['effective_level'], 'A')

        ladder['history'] = self._history(FIXTURE['level_b_days'], trust_metrics.ORDER)
        res_b = trust_metrics.evaluate_ladder(ladder, self._all_met(), today=FIXTURE['today'])
        self.assertEqual(res_b['effective_level'], 'B')

        ladder['history'] = self._history(FIXTURE['level_c_days'], trust_metrics.ORDER)
        res_c = trust_metrics.evaluate_ladder(ladder, self._all_met(), today=FIXTURE['today'])
        self.assertEqual(res_c['effective_level'], 'C')

        # Tripping security circuit breaker immediately demotes to none.
        broken = self._all_met()
        broken['security_posture']['state'] = 'not-met'
        demoted = trust_metrics.evaluate_ladder(ladder, broken, today=FIXTURE['today'])
        self.assertTrue(demoted['demoted'])
        self.assertEqual(demoted['eligible_level'], 'none')
        self.assertEqual(demoted['effective_level'], 'none')


class LiveRepoSmoke(unittest.TestCase):
    def test_scripts_model_trust_runs_on_head_and_reports_honest_state(self):
        result = trust_metrics.measure(ROOT, today=FIXTURE['today'])
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['indicator_count'], FIXTURE['expected_indicator_count'])
        self.assertEqual(result['ladder']['eligible_level'], 'none')
        self.assertEqual(result['ladder']['effective_level'], 'none')
        self.assertTrue(result['ladder']['demoted'])
        self.assertEqual(result['indicators']['human_override_rate']['state'], 'unmeasured')
        self.assertEqual(result['indicators']['independent_audit']['state'], 'unmeasured')
        self.assertEqual(result['indicators']['security_posture']['unapproved_tailorings'], [])
        cli = subprocess.run([str(ROOT / 'scripts' / 'model'), 'trust', '--check'],
                             capture_output=True, text=True, check=False)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)

    def test_decision_d353_is_accepted_with_owner_authority(self):
        ladder, errors = trust_metrics.load_ladder(ROOT)
        self.assertEqual(errors, [])
        authorities = trust_metrics.read_decision_authorities(ROOT, ladder)
        self.assertIn('D-353', authorities)
        self.assertEqual(authorities['D-353']['status'], 'accepted')
        self.assertEqual(authorities['D-353']['authority'], 'owner')
        d353_text = (ROOT / 'docs' / 'domain' / 'decisions' / 'D-353.md').read_text(encoding='utf-8')
        self.assertIn('Torre por delegação do Daniel 22/11/2026', d353_text)
        self.assertEqual(ladder['decision'], 'D-353')


if __name__ == '__main__':
    unittest.main()
