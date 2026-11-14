"""GV1 gate status: commit status (TX24: one file per feature; fixtures in scripts/tests/test_gate_status.py)."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_gate_status import Base, MODE, SHA  # noqa: E402,F401
import config  # noqa: E402
import gate_status as status  # noqa: E402


class CommitStatus(Base):
    """GX-17: the tower/gate commit status, written through the forge port."""

    def verdict(self, **payload):
        return dict(type="gate.passed", payload=dict(tier=1, plan=MODE, **payload))

    def finish(self, result="PASS", events=()):
        self.begin()
        started = json.loads((self.logs / status.STATE_FILE).read_text())["started"]
        self.wall = config.get("gate.status_min_interval_s")
        status.final(self.logs, dict(sha=SHA, result=result, stages=[]), [], 0, [], [], list(events),
                     publisher=self.pub, now=started + self.wall)

    def test_pending_at_begin_then_success_from_the_verdict(self):
        self.finish(events=[self.verdict()])
        self.assertEqual([item["state"] for item in self.rest.statuses], ["pending", "success"])
        first, last = self.rest.statuses
        self.assertEqual((first["repo"], first["sha"], first["context"]), (config.get('forge-events.repo'), SHA, "tower/gate"))
        self.assertEqual(last["description"], f"passed · tier 1 · plan {MODE} · {status.seconds_text(self.wall)}")

    def test_failure_from_a_failed_result(self):
        self.finish("FAIL", [dict(type="gate.failed", payload=dict(tier=None, plan=MODE))])
        self.assertEqual(self.rest.statuses[-1]["state"], "failure")
        self.assertIn("failed · tier - ·", self.rest.statuses[-1]["description"])

    def test_input_digest_prefix_only_when_the_verdict_has_one(self):
        digest = hashlib.sha256(SHA.encode()).hexdigest()
        self.finish(events=[self.verdict(input_digest=digest)])
        self.assertTrue(self.rest.statuses[-1]["description"].endswith(
            " · input " + digest[:config.get("forge-events.status_digest_chars")]))
        self.rest.statuses.clear()
        self.finish(events=[self.verdict()])
        self.assertNotIn("input", self.rest.statuses[-1]["description"])
        self.rest.statuses.clear()
        self.finish(events=[])  # no verdict event at all: still written
        self.assertEqual(self.rest.statuses[-1]["state"], "success")

    def test_description_is_cut_to_the_registered_length(self):
        real = config.get
        verdict = self.verdict(input_digest=hashlib.sha256(SHA.encode()).hexdigest())
        full = status.status_description("passed", dict(mode=MODE), verdict, 1.0)
        with mock.patch.object(config, "get", lambda name: len(full) - 1 if name == "forge-events.status_description_chars" else real(name)):
            text = status.status_description("passed", dict(mode=MODE), verdict, 1.0)
        self.assertEqual(len(text), len(full) - 1)
        self.assertTrue(text.endswith("…"))

    def test_a_403_is_printed_once_and_never_fails_the_run(self):
        self.rest.status_error = "403: Resource not accessible by integration"
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.finish(events=[self.verdict()])
        self.assertEqual(err.getvalue().count("status: unavailable (403)"), 1)
        self.assertEqual(self.rest.statuses, [])
        self.assertEqual(len(self.rest.comments), 1)  # the comment still published

    def test_switch_off_writes_no_status(self):
        real = config.get
        with mock.patch.object(config, "get", lambda name: False if name == "forge-events.status_enabled" else real(name)):
            self.finish(events=[self.verdict()])
        self.assertEqual(self.rest.statuses, [])
        self.assertEqual(len(self.rest.comments), 1)


if __name__ == "__main__":
    unittest.main()
