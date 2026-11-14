"""A refused gate report becomes one gate-refusal incident; a pass writes none (D-240). Hermetic: temp files."""
import hashlib
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import gate_incident  # noqa: E402

SHA = hashlib.sha1(b"head").hexdigest()

FAILED = {"sha": SHA, "result": "FAIL",
          "stages": [{"name": "lint", "result": "PASS"}, {"name": "script tests", "result": "FAIL"}],
          "failingTests": [{"id": "scripts/tests/x.test.sh", "stage": "script tests", "signature": "boom"}]}


class Incident(unittest.TestCase):
    def test_a_refused_report_names_its_head_mode_pr_stages_and_tests(self):
        entry = gate_incident.incident(FAILED, "dev")
        self.assertEqual(entry["type"], "gate-refusal")
        self.assertEqual((entry["sha"], entry["mode"], entry["pr"]), (SHA, "dev", None))
        self.assertEqual(entry["failed_stages"], ["script tests"])
        self.assertEqual(entry["failing_tests"], [{"id": "scripts/tests/x.test.sh", "stage": "script tests"}])

    def test_a_passed_report_writes_no_incident(self):
        self.assertIsNone(gate_incident.incident({"sha": hashlib.sha1(b"pass").hexdigest(), "result": "PASS", "stages": []}, "dev", None))

    def test_the_cli_appends_one_line_per_refusal_and_none_for_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = pathlib.Path(tmp) / "report.json"
            out = pathlib.Path(tmp) / "incidents.jsonl"
            report.write_text(json.dumps(FAILED))
            self.assertEqual(gate_incident.main(["--report", str(report), "--mode", "dev", "--out", str(out)]), 0)
            report.write_text(json.dumps({"sha": hashlib.sha1(b"pass").hexdigest(), "result": "PASS", "stages": []}))
            gate_incident.main(["--report", str(report), "--mode", "dev", "--out", str(out)])
            lines = out.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["type"], "gate-refusal")


if __name__ == "__main__":
    unittest.main()
