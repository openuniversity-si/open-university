"""GV1 gate status: final (TX24: one file per feature; fixtures in scripts/tests/test_gate_status.py)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_gate_status import Base, SHA  # noqa: E402,F401
import config  # noqa: E402
import gate_status as status  # noqa: E402


class Final(Base):
    def report(self, result, stages, **extra):
        return dict(sha=SHA, result=result, stages=stages, **extra)

    def final(self, report, failing=(), cached=(), known=(), events=()):
        self.begin()
        status.final(self.logs, report, list(failing), len(failing), list(cached), list(known), list(events),
                     publisher=self.pub, now=1100.0)
        return self.rest.comments[0]["body"]

    def test_mergeable_all_passed_with_cache_and_events_collapsed(self):
        report = self.report("PASS", [dict(name="structure check", result="PASS", seconds=1.0), dict(name="script tests", result="PASS", seconds=2.0, cached=True)])
        body = self.final(report, cached=[dict(id="scripts/tests/x.test.sh", key="k" * 40, source="run-1")],
                          events=[dict(type="gate.passed", event_id="e1")])
        self.assertIn("**MERGEABLE** — every planned stage passed.", body)
        self.assertIn("1 test(s) reused from the cache", body)
        self.assertIn("scripts/tests/x.test.sh", body)
        self.assertLess(body.index("MERGEABLE"), body.index("<details><summary>forge_events"))
        self.assertIn('{"event_id":"e1","type":"gate.passed"}', body)

    def test_blocks_with_failing_test_and_signature(self):
        failing = [dict(id="a.test.sh", stage="script tests", signature="boom <n>"), dict(id="b.test.sh", stage="script tests", signature="bang")]
        known = [dict(id="a.test.sh", stage="script tests", signature="boom <n>", defect="KD-1")]
        report = self.report("FAIL", [dict(name="structure check", result="PASS", seconds=1.0)], known_defects=known)
        body = self.final(report, failing=failing, known=known)
        self.assertIn("**BLOCKS** — 1 failing test(s) are not known base defects (first: `b.test.sh`).", body)
        self.assertIn("| `a.test.sh` | script tests | boom <n> | yes: KD-1 |", body)
        self.assertIn("| `b.test.sh` | script tests | bang | no |", body)
        self.assertIn("script tests | ⏳ did not run", body)  # OU-DECOUPLE F5 (D-113): a planned engine stage

    def test_mergeable_when_every_failure_is_a_known_defect(self):
        known = [dict(id="a.test.sh", stage="script tests", signature="boom", defect="KD-1")]
        body = self.final(self.report("PASS", [dict(name="structure check", result="PASS", seconds=1.0)], known_defects=known), known=known)
        self.assertIn("**MERGEABLE** — 1 failing test(s) are known base defects.", body)
        self.assertIn("yes: KD-1", body)

    def test_blocks_reasons_without_test_ids(self):
        failed = self.report("FAIL", [dict(name="structure check", result="FAIL", seconds=1.0)])
        self.assertIn("stage(s) failed without a test id: structure check", status.verdict_line(failed, [], set()))
        missing = self.report("FAIL", [], missingStages=["script tests"])
        self.assertIn("did not run: script tests", status.verdict_line(missing, [], set()))

    def test_events_are_cut_before_the_table(self):
        events = [dict(type="gate.passed", pad="x" * 100)] * 3
        self.assertEqual(status.render_events(events, 10), "")
        self.assertIn("```jsonl", status.render_events(events, 10 ** 6))

    def test_disabled_writes_nothing(self):
        original = config.get
        config.get = lambda name, *a, **k: False if name == "gate.status_enabled" else original(name, *a, **k)
        try:
            self.begin()
        finally:
            config.get = original
        self.assertEqual(self.rest.writes(), [])


if __name__ == "__main__":
    unittest.main()
