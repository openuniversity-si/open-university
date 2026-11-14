"""GX-26 (D-070, P-46): gate_explain.py prints the plan without running a stage, and says why a red gate failed."""
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import config  # noqa: E402
import forge_events  # noqa: E402
import gate_carry  # noqa: E402
import gate_explain  # noqa: E402


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


class ExplainTest(unittest.TestCase):
    def repo(self, files):
        root = Path(tempfile.mkdtemp(prefix='gate-explain-'))
        git(root, 'init', '-q')
        git(root, 'config', 'user.email', 't@t')
        git(root, 'config', 'user.name', 't')
        (root / 'README.md').write_text('base\n')
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'base')
        base = git(root, 'rev-parse', 'HEAD')
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
        git(root, 'add', '-A')
        git(root, 'commit', '-qm', 'head')
        return root, git(root, 'rev-parse', 'HEAD'), base

    def test_docs_only_plan_runs_nothing_and_degrades_unknowns(self):
        root, head, base = self.repo({'docs/note.md': 'text\n'})
        with unittest.mock.patch.object(gate_carry, 'read_events', return_value=[]), \
                unittest.mock.patch('subprocess.run', wraps=subprocess.run) as spy:
            out = gate_explain.explain(1, root, head, base)
        self.assertIn('nothing is run', out)
        self.assertIn('plan: scoped', out)
        self.assertIn('script tests: none selected', out)
        self.assertNotIn('not merged', out)
        self.assertIn('preflight:', out)
        called = [' '.join(map(str, call.args[0])) for call in spy.call_args_list if call.args]
        self.assertFalse([cmd for cmd in called if 'pnpm' in cmd or 'gate-local' in cmd or 'vitest' in cmd])

    def test_identity_failure_is_an_error_not_a_crash(self):
        broken = unittest.mock.Mock(change=unittest.mock.Mock(side_effect=RuntimeError('gh: exit 1 (network)')))
        for port in (forge_events.MemoryAdapter(), broken):  # the port's ForgeEventsError, an adapter's RuntimeError
            with self.assertRaises(RuntimeError):
                gate_explain.identity(1, ROOT, port=port)
        repo = config.get('forge-events.repo', ROOT)
        with self.assertRaisesRegex(RuntimeError, 'no head and base'):
            gate_explain.identity(1, ROOT, port=forge_events.MemoryAdapter({(repo, 1): {'head': '', 'base': 'b'}}))

    def test_identity_reads_the_ports_change_with_no_subprocess(self):
        repo = config.get('forge-events.repo', ROOT)
        head, base, pr = hashlib.sha1(b'head').hexdigest(), hashlib.sha1(b'base').hexdigest(), '7'
        port = forge_events.MemoryAdapter({(repo, int(pr)): {'head': head, 'base': base, 'base_ref': 'main'}})
        with unittest.mock.patch('subprocess.run', side_effect=AssertionError('no subprocess')):
            self.assertEqual(gate_explain.identity(pr, ROOT, port=port), (head, base))
            self.assertEqual(gate_explain.identity(int(pr), ROOT, 'x', 'y', port=port), ('x', 'y'))

    def test_the_default_port_is_the_configured_adapter_under_this_modules_demand(self):
        repo = config.get('forge-events.repo', ROOT)  # read before the port is faked: the config store uses it too
        with unittest.mock.patch.object(gate_explain.config, 'get',
                                        side_effect=lambda name, root=None: {'forge-events.repo': repo}[name]), \
                unittest.mock.patch.object(forge_events, 'adapter_from_config', return_value='adapter'), \
                unittest.mock.patch.object(forge_events, 'clock_from_config', return_value='clock'), \
                unittest.mock.patch.object(forge_events, 'ForgeEvents') as built:
            built.return_value.change.return_value = {'head': 'h', 'base': 'b'}
            self.assertEqual(gate_explain.identity('3', ROOT), ('h', 'b'))
        built.assert_called_once_with('adapter', 'clock', 'gate-explain', 'pr-3',
                                      consumer='scripts/lib/gate_explain.py')
        built.return_value.change.assert_called_once_with(repo, int('3'))
        self.assertNotIn('github_cli', Path(gate_explain.__file__).read_text())

    def test_why_names_stage_class_log_and_base_status(self):
        logs = Path(tempfile.mkdtemp(prefix='gate-why-'))
        head = git(ROOT, 'rev-parse', 'HEAD')
        (logs / 'stages.json').write_text(json.dumps({'sha': head, 'result': 'FAIL', 'stages': [
            {'name': 'lint', 'result': 'FAIL', 'exit': 1}], 'failingTests': []}))
        (logs / 'lint.log').write_text('error: no-unused-vars\n')
        (logs / 'script-tests.json').write_text(json.dumps([{'test': 'scripts/tests/x.test.sh', 'result': 'FAIL'}]))
        out = gate_explain.why(logs)
        self.assertIn('failing stage: lint (exit 1)', out)
        self.assertIn('class: code', out)
        self.assertIn(str(logs / 'lint.log'), out)
        self.assertIn('failing script test: scripts/tests/x.test.sh', out)
        self.assertNotIn('not merged', out)

    def test_why_without_report_and_with_a_pass(self):
        empty = Path(tempfile.mkdtemp(prefix='gate-why-'))
        self.assertIn('no stages.json', gate_explain.why(empty))
        (empty / 'stages.json').write_text(json.dumps({'result': 'PASS', 'stages': []}))
        self.assertIn('nothing failed', gate_explain.why(empty))

    def test_why_on_a_run_the_folder_bound_removed_says_it_is_gone(self):
        gone = Path(tempfile.mkdtemp(prefix='gate-why-')) / 'removed'
        out = gate_explain.why(gone)
        self.assertIn(f'{gone} is gone', out)
        self.assertIn('gate-gc.reports_shas_keep', out)
        self.assertNotIn('did not reach its report', out)

    def test_latest_picks_the_newest_report(self):
        root = Path(tempfile.mkdtemp(prefix='gate-latest-'))
        self.assertIsNone(gate_explain.latest(root))
        older = root / '.gate/records/reports/aaa/dev-1'
        newer = root / '.gate/records/reports/bbb/dev-2'
        older.mkdir(parents=True)
        newer.mkdir(parents=True)
        import os
        os.utime(older, (1, 1))
        self.assertEqual(gate_explain.latest(root), newer)

    def test_gate_dev_flags_never_reach_gate_local(self):
        logs = Path(tempfile.mkdtemp(prefix='gate-why-'))
        (logs / 'stages.json').write_text(json.dumps({'result': 'PASS', 'stages': []}))
        why = subprocess.run([str(ROOT / 'scripts/gate-dev'), '--why', str(logs)], capture_output=True, text=True)
        self.assertEqual((why.returncode, 'nothing failed' in why.stdout), (0, True))
        bare = subprocess.run([str(ROOT / 'scripts/gate-dev'), '--explain'], capture_output=True, text=True)
        self.assertEqual(bare.returncode, preflight_exit())
        self.assertIn('--pr', bare.stderr)


def preflight_exit():
    import preflight
    return preflight.SETUP_EXIT


class RedTailTest(unittest.TestCase):
    """D-258: a red local run asks `why` about the report it was given, never about the newest report on disk."""

    def test_a_red_run_asks_why_about_its_own_report_not_the_latest(self):
        root = Path(tempfile.mkdtemp(prefix='gate-dev-tail-'))
        self.addCleanup(lambda: __import__('shutil').rmtree(root, ignore_errors=True))
        (root / 'scripts' / 'lib').mkdir(parents=True)
        dev = root / 'scripts' / 'gate-dev'
        dev.write_text((ROOT / 'scripts' / 'gate-dev').read_text())
        dev.chmod(dev.stat().st_mode | stat.S_IXUSR)
        local = root / 'scripts' / 'gate-local'
        local.write_text('#!/usr/bin/env bash\nmkdir -p "$GATE_REPORT_DIR"\necho FAIL > "$GATE_REPORT_DIR/stages.json"\nexit 1\n')
        local.chmod(local.stat().st_mode | stat.S_IXUSR)
        (root / 'scripts' / 'lib' / 'gate_explain.py').write_text('import sys\nprint("WHY " + " ".join(sys.argv[1:]), file=sys.stderr)\n')
        env = {key: value for key, value in __import__('os').environ.items() if key != 'GATE_REPORT_DIR'}
        done = subprocess.run(['bash', str(dev)], capture_output=True, text=True, cwd=str(root), env={**env, 'OU_PYTHON': sys.executable})
        self.assertEqual(done.returncode, 1)
        line = [text for text in done.stderr.splitlines() if text.startswith('WHY ')]
        self.assertEqual(len(line), 1, done.stderr)
        self.assertNotIn('--latest', line[0])
        named = Path(line[0].split()[-1])
        self.assertTrue((named / 'stages.json').is_file(), line[0])


if __name__ == '__main__':
    unittest.main()
