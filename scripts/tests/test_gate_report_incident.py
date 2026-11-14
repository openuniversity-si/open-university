#!/usr/bin/env python3
"""D-240: a FAIL verdict of gate_report opens its gate-refusal incident in the run's logs, a PASS writes none, and an incident
that cannot be written never changes the verdict. Hermetic: temp dirs, no forge (no mode, no PR)."""
import contextlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
import gate_incident  # noqa: E402
import gate_report  # noqa: E402

SHA = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"


def stage(logs, name, result):
    (logs / f"{name}.stage.json").write_text(json.dumps({"name": name, "result": result, "exit": int(result == "FAIL"), "seconds": 0}))


class Incident(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = pathlib.Path(self.tmp.name)

    def main(self, code):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            return gate_report.main([str(self.logs), SHA, code]), err.getvalue()

    def lines(self):
        path = self.logs / gate_report.INCIDENT_FILE
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def test_a_failed_verdict_opens_one_gate_refusal_naming_the_head_and_the_failed_stages(self):
        stage(self.logs, "lint", "PASS")
        stage(self.logs, "script tests", "FAIL")
        rc, _ = self.main("1")
        self.assertEqual(rc, 1)
        [entry] = self.lines()
        self.assertEqual((entry["type"], entry["sha"], entry["failed_stages"]), (gate_incident.INCIDENT_TYPE, SHA, ["script tests"]))

    def test_a_passed_verdict_writes_no_incident(self):
        stage(self.logs, "lint", "PASS")
        rc, _ = self.main("0")
        self.assertEqual((rc, self.lines()), (0, []))

    def test_an_incident_that_cannot_be_written_leaves_the_verdict_red_and_says_so(self):
        stage(self.logs, "script tests", "FAIL")
        with mock.patch.object(gate_incident, "record", side_effect=OSError("disk")):
            rc, err = self.main("1")
        self.assertEqual(rc, 1)
        self.assertIn("gate incident: not recorded", err)

    def test_the_incident_is_the_one_gate_incident_would_write_from_the_same_report(self):
        stage(self.logs, "script tests", "FAIL")
        self.main("1")
        report = json.loads((self.logs / "stages.json").read_text())
        self.assertEqual(self.lines(), [gate_incident.incident(report, "")])


if __name__ == "__main__":
    unittest.main()
