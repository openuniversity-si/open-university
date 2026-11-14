"""The shadow run of the real gate (D-151). Hermetic: a stub command stands for gate-dev."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import gate_shadow  # noqa: E402


class Shadow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_a_passing_gate_is_recorded_with_its_wall_time_and_the_bypass_off(self):
        result = gate_shadow.measure(self.root, 'abc', ['bash', '-c', 'test "$GATE_BYPASS" = 0 && echo ok'])
        self.assertTrue(result['passed'])
        self.assertGreaterEqual(result['wall_s'], 0)
        self.assertEqual(json.loads((self.root / gate_shadow.FOLDER / 'abc.json').read_text())['sha'], 'abc')
        self.assertEqual(gate_shadow.latest(self.root)['sha'], 'abc')

    def test_a_failing_gate_is_recorded_as_not_passed(self):
        result = gate_shadow.measure(self.root, 'def', ['bash', '-c', 'echo broken; exit 1'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['tail'], ['broken'])

    def stub_report(self, body, exit_code):
        """A stub gate: writes its stage report into the folder it was given (GATE_REPORT_DIR), then exits with `exit_code`."""
        stub = self.root / 'stub.sh'
        stub.write_text("cat > \"$GATE_REPORT_DIR/stages.json\" <<'JSON'\n" + json.dumps(body) + f"\nJSON\nexit {exit_code}\n")
        return ['bash', str(stub)]

    def test_the_gates_own_pass_decides_not_its_exit(self):
        # e2a45feb-style case: the run's own stage report says PASS, the exit says 1 (the tail of another run said "passed").
        body = {'result': 'PASS', 'stages': [{'name': 'script tests', 'result': 'PASS'}]}
        result = gate_shadow.measure(self.root, 'ghi', self.stub_report(body, 1))
        self.assertTrue(result['passed'])
        self.assertEqual((result['verdict'], result['exit']), ('PASS', 1))
        self.assertEqual(result['failing'], [])

    def test_the_gates_own_fail_decides_and_names_its_failing_stage(self):
        body = {'result': 'FAIL', 'stages': [{'name': 'script tests', 'result': 'FAIL'}, {'name': 'secret scan', 'result': 'PASS'}]}
        result = gate_shadow.measure(self.root, 'jkl', self.stub_report(body, 0))
        self.assertFalse(result['passed'])
        self.assertEqual(result['failing'], ['script tests'])
        self.assertEqual(Path(result['report']).parent, self.root / gate_shadow.REPORTS / 'jkl')
        self.assertTrue((Path(result['report']) / 'stages.json').is_file())

    def test_a_run_with_no_report_is_judged_by_its_exit(self):
        result = gate_shadow.measure(self.root, 'mno', ['bash', '-c', 'exit 0'])
        self.assertTrue(result['passed'])
        self.assertIsNone(result['verdict'])
        self.assertIsNone(result['report'])

    def test_a_second_run_does_not_start_while_one_is_measuring(self):
        first = gate_shadow.exclusive(self.root)
        self.assertIsNotNone(first)
        self.assertIsNone(gate_shadow.exclusive(self.root))
        first.close()
        again = gate_shadow.exclusive(self.root)
        self.assertIsNotNone(again)
        again.close()

    def test_latest_is_empty_before_any_run(self):
        self.assertIsNone(gate_shadow.latest(self.root))


if __name__ == '__main__':
    unittest.main()
