"""The flake class (TX11, D-070): a stage whose every re-run test passed is flake; one with any test that failed again
or was not re-run stays what the runner said. No network."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import gate_classify  # noqa: E402

ASSERTION = 'AssertionError: expected [N] got [N]: a corrupt marker runs the stage again'


class FlakeClass(unittest.TestCase):
    def test_a_stage_whose_every_rerun_test_passed_is_flake_even_with_the_assertion_still_in_the_log(self):
        log = '\n'.join([ASSERTION, gate_classify.flake_passed('scripts/tests/a.test.sh'),
                         gate_classify.flake_passed('scripts/tests/b.test.sh')])
        self.assertEqual(gate_classify.classify('script tests', log), 'flake')

    def test_the_717_case_an_env_looking_line_that_passed_on_the_rerun_is_flake_not_env(self):
        log = 'ECONNRESET while reading the marker\n' + gate_classify.flake_passed('scripts/tests/gate-result-cache.test.sh')
        self.assertEqual(gate_classify.classify('script tests', log), 'flake')

    def test_one_test_that_failed_again_keeps_the_stage_code(self):
        log = '\n'.join([ASSERTION, gate_classify.flake_passed('scripts/tests/a.test.sh'),
                         gate_classify.flake_own('scripts/tests/b.test.sh', 'it failed again on the one re-run')])
        self.assertEqual(gate_classify.classify('script tests', log), 'code')

    def test_a_test_the_pr_changed_is_not_rerun_and_keeps_the_stage_its_own_class(self):
        log = '\n'.join([ASSERTION, gate_classify.flake_passed('scripts/tests/a.test.sh'),
                         gate_classify.flake_own('scripts/tests/b.test.sh', 'the PR changed it, not re-run')])
        self.assertEqual(gate_classify.classify('script tests', log), 'code')

    def test_without_any_rerun_line_nothing_changes(self):
        self.assertEqual(gate_classify.classify('script tests', ASSERTION), 'code')
        self.assertEqual(gate_classify.classify('script tests', 'ECONNRESET'), 'env')

    def test_a_line_that_only_mentions_flake_is_not_the_marker(self):
        self.assertEqual(gate_classify.classify('script tests', ASSERTION + '\nsome text: flake: x passed'), 'code')

    def test_the_human_and_machine_lines_name_the_flake_action(self):
        log = gate_classify.flake_passed('scripts/tests/a.test.sh')
        self.assertTrue(gate_classify.line('script tests', log).startswith('class: flake — nothing to fix in this PR'))
        self.assertEqual(gate_classify.class_line('script tests', 'flake'),
                         f"{config.get('gate.class_line_prefix')} script tests\tflake")

    def test_the_cli_prints_the_flake_machine_line(self):
        with tempfile.NamedTemporaryFile('w', suffix='.log') as handle:
            handle.write(ASSERTION + '\n' + gate_classify.flake_passed('scripts/tests/a.test.sh') + '\n')
            handle.flush()
            done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'lib' / 'gate_classify.py'), 'script tests', handle.name],
                                  capture_output=True, text=True, check=True)
        self.assertEqual(done.stdout.splitlines()[-1].rsplit('\t', 1)[1], 'flake')


if __name__ == '__main__':
    unittest.main()
