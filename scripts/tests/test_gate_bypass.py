"""The explicit, reversible gate bypass (D-151). Hermetic: throwaway repository and record directory, no network."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import engine_role  # noqa: E402
import gate_bypass  # noqa: E402
import train_git  # noqa: E402


class Enabled(unittest.TestCase):
    def test_the_environment_wins_for_the_run_in_both_directions(self):
        self.assertTrue(gate_bypass.enabled({gate_bypass.ENV: '1'}))
        with mock.patch.object(gate_bypass.config, 'shared', return_value=True):
            self.assertFalse(gate_bypass.enabled({gate_bypass.ENV: '0'}))
            self.assertTrue(gate_bypass.enabled({}))

    def test_it_is_off_by_default_and_when_the_store_cannot_be_read(self):
        default = json.loads((ROOT / 'config/registry/gate/gate.bypass.json').read_text())['default']
        self.assertIs(default, False)  # the registry's default, whatever the shared store holds today
        with mock.patch.object(gate_bypass.config, 'shared', side_effect=RuntimeError('store down')):
            self.assertFalse(gate_bypass.enabled({}))


class Announce(unittest.TestCase):
    def test_the_port_is_built_with_a_correlation_id_and_lock_lifted_is_emitted(self):
        sha = 'a' * 40
        with mock.patch.object(gate_bypass, 'by_regime', return_value=True), \
                mock.patch.object(gate_bypass.config, 'get', return_value='x'), \
                mock.patch.object(gate_bypass.forge_events, 'adapter_from_config'), \
                mock.patch.object(gate_bypass.forge_events, 'clock_from_config'), \
                mock.patch.object(gate_bypass.forge_events, 'ForgeEvents') as port, \
                mock.patch.object(gate_bypass.regime, 'lift', return_value=True) as lift, \
                mock.patch('builtins.print') as shown:
            self.assertTrue(gate_bypass.announce(Path('.'), sha, 7))
            self.assertEqual(port.call_args[0][3], 'pr-7')
            gate_bypass.announce(Path('.'), sha, None)
            self.assertEqual(port.call_args[0][3], f'gate-{sha}')
        self.assertEqual(lift.call_count, 2)
        shown.assert_not_called()  # no "(lock.lifted not emitted: ...)" warning


class Run(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        env = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@t', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@t')
        for args in (['init', '-q', '-b', 'main'], ['commit', '-q', '--allow-empty', '-m', 'seed']):
            subprocess.run(['git', '-C', str(self.repo), *args], check=True, env=env, capture_output=True)
        self.sha = subprocess.run(['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        self.records = Path(self.tmp.name) / 'records'

    def test_a_bypassed_gate_marks_every_stage_and_the_record(self):
        with mock.patch.object(gate_bypass.gate_report, 'main', return_value=0) as report, \
                mock.patch.object(gate_bypass, 'run_script_tests', return_value=0):
            code = gate_bypass.run(self.repo, 'dev', '', self.sha, self.records)
        self.assertEqual(code, 0)
        record = (self.records / f'{self.sha}.dev.pass').read_text()
        self.assertIn(gate_bypass.MARK, record)
        logs = Path(report.call_args[0][0][0])
        stages = [json.loads(path.read_text()) for path in logs.glob('*.stage.json')]
        self.assertTrue(stages)
        self.assertTrue(all(stage['result'] == 'PASS' for stage in stages))
        self.assertTrue(all(stage['bypass'] == gate_bypass.MARK for stage in stages if stage['name'] != 'script tests'))
        self.assertNotIn('bypass', next(stage for stage in stages if stage['name'] == 'script tests'))  # D-302: really run
        self.assertIn('script tests', [stage['name'] for stage in stages])
        self.assertEqual(json.loads((logs / 'bypass.json').read_text())['bypass'], gate_bypass.MARK)

    def test_a_red_selected_test_fails_the_bypassed_gate_even_when_it_is_red_on_the_base_too(self):
        # D-302 (03/11: #196, #204, #208 merged with a selected test red): the regime lifts every stage but this one.
        def excuse(report, logs, mode):  # what KD1 / F73 do to a test red on the base too: the stage turns green
            for stage in report['stages']:
                stage['result'] = 'PASS'
            report['result'] = 'PASS'
        with mock.patch.object(gate_bypass, 'run_script_tests', return_value=1), \
                mock.patch.object(gate_bypass.gate_report, 'adjudicate_known_defects', side_effect=excuse) as adjudicate, \
                mock.patch.object(gate_bypass.gate_report.gate_publish, 'should_publish', return_value=False), \
                mock.patch.object(gate_bypass.gate_report, 'apply_coverage'):
            code = gate_bypass.run(self.repo, 'dev', '', self.sha, self.records)
        self.assertEqual(code, 1)  # scripts/deliver merges only on a green gate: exit 1 stops it
        adjudicate.assert_not_called()
        self.assertFalse(list(self.records.glob('*.pass')))

    def test_the_head_of_a_pr_is_the_forges_record_not_refs_pull(self):
        # D-302: Origin's refs/pull/<n>/head is imported from GitHub; #214 was judged at bf9154b9b, an unrelated commit.
        with mock.patch.object(gate_bypass.subprocess, 'run', side_effect=AssertionError('no git fetch of refs/pull')), \
                mock.patch('gate_pin.pr_identity', return_value=(self.sha, 'b' * 40, 'main')), \
                mock.patch('gate_pin.fetch_commit', side_effect=lambda root, sha: sha):
            self.assertEqual(gate_bypass.head_of(self.repo, '214', ''), self.sha)

    def test_the_script_tests_stage_keeps_its_true_result(self):
        logs = Path(self.tmp.name) / 'logs'
        with mock.patch.object(gate_bypass.gate_report, 'expected_stages', return_value=['structure check']):
            gate_bypass.write_stages(logs, 'dev', 3)
        stage = json.loads((logs / 'script_tests.stage.json').read_text())
        self.assertEqual((stage['result'], stage['exit']), ('FAIL', 3))
        self.assertEqual(json.loads((logs / 'structure_check.stage.json').read_text())['bypass'], gate_bypass.MARK)

    def test_tests_that_cannot_run_are_a_fail_not_a_pass(self):
        logs = Path(self.tmp.name) / 'logs2'
        logs.mkdir()
        with mock.patch.object(gate_bypass, '_git', side_effect=RuntimeError('no git')):
            self.assertEqual(gate_bypass.run_script_tests(self.repo, self.sha, logs), 1)
        self.assertIn('FAIL script tests', (logs / 'script_tests.log').read_text())

    def test_the_checkout_dir_is_traversable_by_another_uid(self):
        # GR2: mkdtemp is 0700; a test that drops to uid 65534 (root-identity) could not read the bypass checkout.
        seen = []
        real = gate_bypass._git

        def spy(root, *args):
            if args[:1] == ('worktree',) and args[1:2] == ('add',):
                seen.append(os.stat(Path(args[-2]).parent).st_mode & 0o005)
            return real(root, *args)
        logs = Path(self.tmp.name) / 'logs3'
        logs.mkdir()
        with mock.patch.object(gate_bypass, '_git', side_effect=spy):
            gate_bypass.run_script_tests(self.repo, self.sha, logs)
        self.assertEqual(seen, [0o005])

    def test_a_report_that_refuses_is_not_a_pass_and_writes_no_record(self):
        with mock.patch.object(gate_bypass.gate_report, 'main', return_value=1):
            self.assertEqual(gate_bypass.run(self.repo, 'dev', '', self.sha, self.records), 1)
        self.assertFalse(list(self.records.glob('*.pass')))

    def test_a_bypassed_verdict_binds_no_v4_proof_so_the_train_never_admits_it(self):
        # D-259: the #973 merge went through on this pass; no proof is bound, so the train's admission refuses it.
        with mock.patch.dict(os.environ, {'OU_GATE_PROOF': 'stale'}), \
                mock.patch.object(gate_bypass.gate_report, 'main', return_value=0) as report:
            self.assertEqual(gate_bypass.run(self.repo, 'dev', '', self.sha, self.records), 0)
            self.assertNotIn('OU_GATE_PROOF', os.environ)
        self.assertEqual(report.call_count, 1)

    def test_the_whole_report_is_written_for_a_real_dev_run(self):
        code = gate_bypass.run(self.repo, 'dev', '', self.sha, self.records)
        self.assertEqual(code, 0)
        self.assertTrue((self.records / f'{self.sha}.dev.pass').is_file())


class TierTwo(unittest.TestCase):
    def test_the_trains_tier_two_runs_for_real_even_while_the_bypass_is_on(self):
        gate = train_git.Tier2Gate(ROOT)
        with mock.patch.object(train_git.gate_bypass, 'enabled', return_value=True), \
                mock.patch.object(train_git.engine_role.subprocess, 'run', side_effect=FileNotFoundError('ran')):
            with self.assertRaises(FileNotFoundError):
                gate.run('abc')

    def test_no_other_gate_command_is_bypassed_tier_three_and_a_tests_gate_always_run(self):
        gate = engine_role.CommandGate(ROOT, ['scripts/does-not-exist'], 1, 1, 'tier 3', 'train.tier2_timeout_s')
        with mock.patch.object(gate_bypass, 'enabled', return_value=True), \
                mock.patch.object(engine_role.subprocess, 'run', side_effect=FileNotFoundError('ran')):
            with self.assertRaises(FileNotFoundError):
                gate.run('abc')

    def test_a_gate_on_the_working_tree_is_never_bypassed(self):
        source = (ROOT / 'scripts' / 'gate-local').read_text()
        self.assertIn('( -n "$pr" || -n "$sha" )', source)


if __name__ == '__main__':
    unittest.main()
