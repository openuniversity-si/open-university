"""Offline regression checks for delivery policy, inventories and nightly attribution."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import gate_policy as policy
import gate_noite as noite


class ForgeIdentityMigration(unittest.TestCase):
    def test_identity_uses_selected_adapter_and_configured_repository(self):
        import forge_doubles
        asked = []
        adapter = forge_doubles.origin(change=lambda repo, number: asked.append((repo, number)) or
                                       {'head': 'h', 'base': 'b', 'body': ''})
        with patch.object(policy.forge_events, 'adapter_from_config', return_value=adapter):
            info = policy.identity(1, 'owner/repository')
        self.assertEqual((info['head'], info['base']), ('h', 'b'))
        self.assertEqual(asked, [('owner/repository', 1)])

    def test_shell_identity_cli_preserves_tab_separated_fields(self):
        import contextlib
        import io
        import runpy
        import forge_doubles
        adapter = forge_doubles.origin(change=lambda repo, number: {'head': 'h', 'base': 'b'})
        for options, expected in [([], 'h\tb\n'), (['--head-only'], 'h\n')]:
            output = io.StringIO()
            with patch.object(sys, 'argv', ['gate_policy.py', 'identity', '--pr', '1', *options]), \
                    patch.object(policy.forge_events, 'adapter_from_config', return_value=adapter), \
                    contextlib.redirect_stdout(output):
                runpy.run_path(str(ROOT / 'scripts/lib/gate_policy.py'), run_name='__main__')
            self.assertEqual(output.getvalue(), expected)


class SplitTests(unittest.TestCase):
    def test_actual_diff_both_sides_of_rename(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args): return subprocess.check_output(['git', '-C', directory, *args], text=True).strip()
            git('init', '-q'); git('config', 'user.email', 'test@example.test'); git('config', 'user.name', 'test'); git('config', 'commit.gpgsign', 'false')
            f = root / 'scripts/lib/old_name.py'; f.parent.mkdir(parents=True); f.write_text('x = 1\n')
            git('add', '.'); git('commit', '-qm', 'base'); base = git('rev-parse', 'HEAD')
            f.rename(root / 'safe.txt'); git('add', '-A'); git('commit', '-qm', 'rename')
            paths = policy.changed_paths(root, base, 'HEAD')
            self.assertIn('safe.txt', paths); self.assertIn('scripts/lib/old_name.py', paths)

    def test_classifier_refuses_racing_head_and_missing_diff(self):
        with patch.object(policy, 'identity', return_value={'base': 'base', 'head': 'new'}):
            with self.assertRaisesRegex(RuntimeError, 'head changed'): policy.classify_pr(7, 'old')
        with self.assertRaises(RuntimeError): policy.changed_paths(ROOT, '', 'HEAD')

    def test_classifier_reuses_fresh_view_without_another_github_call(self):
        with patch.object(policy, 'identity') as github, patch.object(policy.subprocess, 'run'), patch.object(policy, 'changed_paths', return_value=['README.md']):
            result = policy.classify_pr(7, 'head', base='base')
            github.assert_not_called()
        self.assertEqual((result['head'], result['base'], result['devPlan']['kind']), ('head', 'base', 'scoped'))
        self.assertFalse({'db', 'paths'} & set(result))  # OU-DECOUPLE F5 (D-113): no database classification

    def test_the_full_battery_keeps_every_engine_stage_of_the_pre_split_nightly(self):
        # OU-DECOUPLE F5 (D-113): the baseline lists the engine's stages of the pre-split nightly; the smoke manifest,
        # the browser arguments, the Neon PR stages, the DB gate and the factory bench left with Open University.
        original = json.loads((ROOT / 'scripts/lib/gate-stages-baseline.json').read_text())
        self.assertFalse(set(original) - set(policy.FULL_STAGES))
        self.assertEqual(policy.PLANS['noite'], policy.FULL_STAGES)
        self.assertEqual(policy.PLANS['full'], policy.FULL_STAGES)
        for stage in ('shellcheck', 'script tests'):
            self.assertIn(stage, policy.FULL_STAGES)
        self.assertEqual(policy.DEV_STAGES, policy.PREREQUISITES)
        self.assertEqual(policy.DB_STAGES, [])
        self.assertNotIn('db', policy.PLANS)

    def test_nightly_failure_maps_to_source_and_falls_back_honestly(self):
        changes = [{'pr': 7, 'files': ['scripts/lib/gate_policy.py']},
                   {'pr': 8, 'files': ['docs/operations/local-gate.md']}]
        self.assertEqual(noite.candidates('script tests', changes), [7])
        self.assertEqual(noite.candidates('shellcheck', changes[1:]), [8])
        self.assertEqual(noite.candidates('script tests', [{'pr': None, 'files': ['scripts/run']}]), [])
        self.assertEqual(noite.candidates('script tests', []), [])

    def test_tier3_is_the_full_battery(self):
        # D-065 (5): tier 3 runs every full-plan stage on an integration tip.
        self.assertEqual(policy.PLANS['tier3'], policy.FULL_STAGES)

    def test_tier3_needs_a_sha_and_stands_alone(self):
        gate = str(ROOT / 'scripts/gate-local')
        listed = subprocess.run(['bash', gate, '--tier3', '--list'], capture_output=True, text=True, check=False)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual(json.loads(listed.stdout)['stages'], policy.PLANS['tier3'])
        for extra in ([], ['--sha', 'a' * 40, '--pr', '1'], ['--sha', 'a' * 40, '--dev'], ['--sha', 'a' * 40, '--noite']):
            with self.subTest(extra=extra):
                done = subprocess.run(['bash', gate, '--tier3', *extra], capture_output=True, text=True, check=False)
                self.assertEqual(done.returncode, 2, done.stderr)

    def test_reports_failed_stages_and_unreached_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            (logs / 'script_tests.stage.json').write_text(json.dumps({'name': 'script tests', 'result': 'FAIL', 'seconds': 1.2}))
            result = noite.report(logs, 'sha', [{'pr': 7, 'files': ['scripts/lib/gate_noite.py']},
                                                {'pr': 8, 'files': ['docs/a.md']}], 1, 'base')
            self.assertEqual(result['result'], 'FAIL')
            failed = next(f for f in result['failures'] if f['stage'] == 'script tests')
            self.assertEqual(failed['candidatePRs'], [7])
            self.assertIn('NOT RUN', (logs / 'noite.md').read_text())
            self.assertTrue((logs / 'noite.json').is_file())

    def test_noite_uses_main_and_advances_state_only_after_complete_success(self):
        for fail in (False, True):
            with self.subTest(fail=fail), tempfile.TemporaryDirectory() as directory:
                record = Path(directory); logs = record / 'report'
                def fake_git(*args):
                    if args[0] == 'rev-parse':
                        self.assertEqual(args[-1], 'origin/main^{commit}'); return 'head'
                    if args[0] == 'rev-list': return 'root'
                    raise AssertionError(args)
                def fake_run(command, **kwargs):
                    if str(command[0]).endswith('gate-local'):
                        self.assertIn('--noite', command)
                        self.assertIn('--sha', command)
                        self.assertIn('head', command)
                        self.assertNotIn('--pr', command)  # OU-DECOUPLE F5 (D-113): no Neon branch to borrow
                        self.assertNotIn('--merge', command)
                        self.assertNotIn('ship-verify', command)
                        logs.mkdir(parents=True, exist_ok=True)
                        for i, stage in enumerate(policy.FULL_STAGES):
                            if fail and i == 0: continue
                            (logs / f'{i}.stage.json').write_text(json.dumps({'name': stage, 'result': 'PASS', 'seconds': .01}))
                    return subprocess.CompletedProcess(command, 0)
                with patch.dict('os.environ', {'GATE_RECORD_DIR': directory, 'GATE_REPORT_DIR': str(logs)}), patch.object(sys, 'argv', ['gate-noite']), patch.object(noite, 'git', side_effect=fake_git), patch.object(noite, 'merges', return_value=[{'pr': 7, 'sha': 'merge', 'files': []}]), patch.object(noite.subprocess, 'run', side_effect=fake_run):
                    if fail:
                        with self.assertRaisesRegex(RuntimeError, 'verification failed'): noite.main()
                        self.assertFalse((record / 'last-noite-sha').exists())
                        self.assertFalse((record / 'head.noite.pass').exists())
                    else:
                        noite.main()
                        self.assertEqual((record / 'last-noite-sha').read_text().strip(), 'head')
                    self.assertTrue((logs / 'noite.json').is_file())


if __name__ == '__main__': unittest.main()
