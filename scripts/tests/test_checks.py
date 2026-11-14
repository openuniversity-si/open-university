"""one line per N7 check, pass/warn/fail, exit code; no session needed Hermetic: no network."""
from pathlib import Path
import contextlib
import io
import json
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import checks  # noqa: E402


def _fake_checks(*verdicts):
    return tuple((f'c{i}', (lambda v=v: v)) for i, v in enumerate(verdicts))


class ChecksTests(unittest.TestCase):
    def test_a_failing_check_exits_one(self):
        with mock.patch.object(checks, 'CHECKS', _fake_checks((checks.PASS, 'a'), (checks.FAIL, 'b'))):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(checks.main([]), 1)

    def test_warn_alone_exits_zero(self):
        with mock.patch.object(checks, 'CHECKS', _fake_checks((checks.PASS, 'a'), (checks.WARN, 'b'))):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(checks.main([]), 0)

    def test_one_line_per_check(self):
        with mock.patch.object(checks, 'CHECKS', _fake_checks((checks.PASS, 'ok'), (checks.WARN, 'tip'))):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                checks.main([])
        self.assertEqual(out.getvalue().splitlines(), ['pass c0: ok', 'warn c1: tip'])

    def test_json_list_has_each_check(self):
        with mock.patch.object(checks, 'CHECKS', _fake_checks((checks.PASS, 'ok'))):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                checks.main(['--json'])
        self.assertEqual(json.loads(out.getvalue()), [{'name': 'c0', 'status': 'pass', 'detail': 'ok'}])

    def test_slo_breach_is_a_fail_read_from_json_not_exit_code(self):
        rows = [{'slo': 'slo.x', 'state': 'breached'}]
        done = mock.Mock(returncode=1, stdout=json.dumps(rows))
        with mock.patch.object(checks, '_run', return_value=done):
            status, detail = checks.check_slo()
        self.assertEqual(status, checks.FAIL)
        self.assertIn('slo.x', detail)


if __name__ == '__main__':
    unittest.main()
