"""Gate failure classes (D-027): every red stage is code, env or contract. No network."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import gate_classify  # noqa: E402


class Classify(unittest.TestCase):
    def test_env_failures(self):
        for stage, log in [('script tests', "OSError: [Errno 26] Text file busy: '.toolchain/bin/node'"),
                           ('script tests', "ModuleNotFoundError: No module named 'encodings'"),
                           ('secret scan (tree)', 'SecurityFatalError: next requires a security upgrade'),
                           ('local database', 'anything'),
                           ('shellcheck', 'error while loading shared libraries: libgtk-4.so.1'),
                           ('script tests', 'FAIL scripts/tests/root-identity.test.sh: runuser: failed to execute '
                                            'ou-root-pg-ab12/bin/initdb: Permission denied'),
                           ('structure check', 'gh: exit 429 (rate-limited); GitHub secondary rate limit after 1 wait(s)')]:
            with self.subTest(log=log):
                self.assertEqual(gate_classify.classify(stage, log), 'env')

    def test_a_permission_fault_of_the_service_account_beside_an_assertion_stays_code(self):
        log = 'runuser: failed to execute ou-root-pg-x/bin/initdb: Permission denied\nAssertionError: 2 != 3'
        self.assertEqual(gate_classify.classify('script tests', log), 'code')

    def test_contract_failures(self):
        self.assertEqual(gate_classify.classify('structure check', 'D-016 and D-024 contradict: two rules for one row'), 'contract')
        self.assertEqual(gate_classify.classify('script tests', 'FAIL conflicting rules: D-054 and D-065'), 'contract')

    def test_code_failures_by_default(self):
        self.assertEqual(gate_classify.classify('script tests', 'AssertionError: expected 2 to be 3'), 'code')
        self.assertEqual(gate_classify.classify('schema compat', 'violates check constraint "courses_published_area" 23514'), 'code')

    def test_only_a_driver_stage_is_env_whatever_its_log(self):
        """F46: the browser stages that were env by name left with Open University; every stage the gate runs is
        judged by its log, and the stages env by name are exactly the driver's."""
        import gate_policy
        self.assertEqual(gate_classify.ENV_STAGES, gate_classify.DRIVER_STAGES)
        for stage in gate_policy.FULL_STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(gate_classify.classify(stage, 'anything'), 'code')

    def test_f8_a_code_failure_beside_an_env_failure_is_code(self):
        e2e = ('Error: browserType.launch:\n  Host system is missing dependencies to run browsers.\n'
               '  1) [chromium-desktop] › e2e/catalog-routing.spec.ts:13:3\n'
               '    Error: expect(received).toBe(expected) // Object.is equality\n    Expected: 308\n    Received: 404\n')
        self.assertEqual(gate_classify.classify('script tests', e2e), 'code')
        self.assertIn('env evidence too: "Host system is missing"', gate_classify.line('script tests', e2e))
        missing = "ModuleNotFoundError: No module named 'release_policy'\nmissing GH_TOKEN"
        self.assertEqual(gate_classify.classify('script tests', missing), 'code')

    def test_f8_an_env_failure_alone_stays_env(self):
        webkit = ('  1) [webkit-mobile-390] › e2e/home.spec.ts:4:1\n    Error: browserType.launch:\n'
                  '    ║ Host system is missing dependencies to run browsers. ║\n    ║     libavif.so.16 ║\n')
        self.assertEqual(gate_classify.classify('script tests', webkit), 'env')
        self.assertNotIn('env evidence too', gate_classify.line('script tests', webkit))
        self.assertEqual(gate_classify.classify('script tests', "ModuleNotFoundError: No module named 'encodings'"), 'env')

    def test_the_runner_prints_the_class_and_action_of_a_red_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = f'''logs={tmp}; verbose=0; source {ROOT}/scripts/lib/gate-runner.sh
step "secret scan" {tmp} bash -c 'echo "gitleaks: command not found"; exit 1' || true
step "script tests" {tmp} bash -c 'echo AssertionError; exit 1' || true'''
            out = subprocess.run(['bash', '-c', script], capture_output=True, text=True).stdout
        self.assertIn('class: env — open an env patch PR first', out)
        self.assertIn("class: code — fix this PR's change and rerun the gate", out)
        # GX-01: one machine line per red stage, `<prefix> <stage>\t<class>`.
        prefix = config.get('gate.class_line_prefix', ROOT)
        lines = [line for line in out.splitlines() if line.startswith(prefix + ' ')]
        self.assertEqual(lines, [f'{prefix} secret scan\tenv', f'{prefix} script tests\tcode'])


class DriverAborts(unittest.TestCase):
    """GX-01: the driver's abort strings are env, and an abort prints the FAIL line and one machine line."""

    def test_driver_abort_strings_are_env(self):
        for message in ('FAIL local postgres did not start', 'FAIL could not create the local test database',
                        'FAIL could not reset the local test database', 'FAIL missing TEST_DATABASE_URL',
                        'FAIL env: missing toolchain: postgres'):
            with self.subTest(message=message):
                self.assertRegex(message, gate_classify.ENV)
                self.assertEqual(gate_classify.classify('script tests', message), 'env')

    def test_driver_stages_are_env_whatever_the_message(self):
        for stage in sorted(gate_classify.DRIVER_STAGES):
            with self.subTest(stage=stage):
                self.assertEqual(gate_classify.classify(stage, 'cannot read PR #7'), 'env')

    def test_every_driver_abort_stage_is_a_driver_stage(self):
        """Fix the class (GATE-API F7): every stage gate-local and its hooks abort with is env, so no abort site reaches
        the train as the PR's own failure."""
        texts = [(ROOT / 'scripts/gate-local').read_text()]
        texts += [path.read_text() for path in sorted((ROOT / 'scripts/lib/gate-hooks').glob('*.sh'))]
        stages = {name for text in texts for name in re.findall(r'driver_abort "([^"]+)"', text)}
        self.assertIn('gate pin', stages)
        self.assertEqual(stages - gate_classify.DRIVER_STAGES, set())

    def test_a_pin_that_cannot_read_its_input_is_env(self):
        """Measured on 069145b9: classify('gate pin', 'GnuTLS handshake failed') returned code."""
        for message in ('GnuTLS handshake failed', 'cannot read PR #7 head/base (exit 1)', 'unknown commit abc1234'):
            with self.subTest(message=message):
                self.assertEqual(gate_classify.classify('gate pin', message), 'env')
        prefix = config.get('gate.class_line_prefix', ROOT)
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/gate_classify.py'), 'abort', 'gate pin',
                               'cannot read PR #7 head/base (exit 1)'], capture_output=True, text=True, check=True)
        self.assertEqual(done.stdout.splitlines(), ['FAIL cannot read PR #7 head/base (exit 1)',
                                                    f'{prefix} gate pin\tenv'])

    def test_abort_prints_fail_lines_and_one_class_line(self):
        prefix = config.get('gate.class_line_prefix', ROOT)
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/gate_classify.py'), 'abort', 'gate preflight',
                               'FAIL env: missing toolchain: node\nFAIL env: missing browser library: nss3'],
                              capture_output=True, text=True, check=True)
        self.assertEqual(done.stdout.splitlines(), ['FAIL env: missing toolchain: node',
                                                    'FAIL env: missing browser library: nss3',
                                                    f'{prefix} gate preflight\tenv'])
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/gate_classify.py'), 'abort', 'local database',
                               'local postgres did not start'], capture_output=True, text=True, check=True)
        self.assertEqual(done.stdout.splitlines(), ['FAIL local postgres did not start', f'{prefix} local database\tenv'])

    def test_class_line_is_one_line_with_one_tab(self):
        self.assertEqual(gate_classify.class_line('a\tb\nc', 'code'), f"{config.get('gate.class_line_prefix', ROOT)} a b c\tcode")


if __name__ == '__main__':
    unittest.main(verbosity=1)
