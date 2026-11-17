"""GX-25 gate status: gate.started, the ETA from the ledger and the verdict hooks (fixtures in scripts/tests/test_gate_status.py)."""
import contextlib
import io
import json
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from test_gate_status import Base, MODE, SHA, T0  # noqa: E402,F401

DATA = json.loads((pathlib.Path(__file__).resolve().parents[1] / 'fixtures' / 'gate-eta.json').read_text())['started']
PLANNED = ("structure check", "script tests")  # the stages of the fixture plan (test_gate_status.Base)
import config  # noqa: E402
import forge_events  # noqa: E402
import gate_status as status  # noqa: E402
import gate_eta  # noqa: E402
import slo  # noqa: E402


class Started(Base):
    """GX-25: gate.started at begin, with the ETA from the ledger; the verdict hooks; the one-key switch."""

    def started(self):
        return [event for items in self.ledger.logs.values() for event in items if event["type"] == "gate.started"]

    def pr(self):
        return json.loads((self.logs / status.STATE_FILE).read_text())["pr"]

    def measure(self, stage_name, millis):
        prefix = config.get("forge-events.gate_step_prefix")
        for index, ms in enumerate(millis):
            subject = forge_events.subject(config.get("forge-events.repo"), index + 1, SHA.replace("a", "b"))
            self.pub.events.emit("engine.step.measured", forge_events.step_payload(subject, prefix + stage_name, ms, "ok"))

    def test_published_at_begin_with_a_fresh_container_fallback_eta(self):
        self.begin()
        (event,) = self.started()
        payload = event["payload"]
        planned = json.loads((self.logs / status.STATE_FILE).read_text())["planned"]
        self.assertEqual((payload["pr"], payload["sha"], payload["plan"], payload["tier"]), (self.pr(), SHA, MODE, 1))
        self.assertGreater(payload["expected_wall_s"], 0)
        self.assertLessEqual(payload["expected_wall_s"], len(planned) * config.get("gate-eta.fallback_stage_s"))  # never "no history"
        self.assertTrue(set(payload["critical_path"]) <= set(planned))

    def test_eta_is_the_critical_path_over_the_ledger_quantile_not_the_sum(self):
        # OU-DECOUPLE F5 (D-113): the fixture's two ledger stages are measured under the two planned engine stages.
        first, second = PLANNED
        for name, millis in zip(PLANNED, DATA["ledger_ms"].values()):
            self.measure(name, millis)
        with mock.patch.object(status, "stage_needs", return_value={second: [first]}):
            self.begin()
        payload = self.started()[0]["payload"]
        self.assertEqual((payload["expected_wall_s"], payload["critical_path"]), (DATA["wall_s"], [first, second]))
        with mock.patch.object(status, "stage_needs", return_value={}):
            independent = status.wall_estimate({first: DATA["wall_s"] - DATA["independent_wall_s"], second: float(DATA["independent_wall_s"])})
        self.assertEqual(independent[0], DATA["independent_wall_s"])  # independent stages: the longest, not the sum

    def test_the_second_begin_publishes_nothing_more(self):
        self.begin()
        self.begin(T0 + config.get("gate.status_min_interval_s"))
        self.assertEqual(len(self.started()), 1)

    def test_switch_off_publishes_nothing_and_the_verdict_path_is_unchanged(self):
        real = config.get
        with mock.patch.object(config, "get", side_effect=lambda name, *a: False if name == "gate-eta.started_enabled" else real(name, *a)):
            self.begin()
            with mock.patch.object(slo, "run") as run, mock.patch.object(gate_eta, "collect") as collect:
                status.verdict_hooks(self.pub, dict(type="gate.passed", event_id="e", payload=dict(tier=1, pr=self.pr())))
        self.assertEqual(self.started(), [])
        run.assert_not_called()
        collect.assert_not_called()
        self.assertEqual([item["state"] for item in self.rest.statuses], ["pending"])  # the status of the run is untouched

    def test_a_tier_1_verdict_calls_gate_slow_once_and_never_the_slo_evaluation(self):
        # D-322: the gate may not depend on measurement; the SLOs are evaluated by their consumer (scripts/slo run).
        verdict = dict(type="gate.failed", event_id="e1", payload=dict(tier=1, pr=1, plan=MODE))
        with mock.patch.object(gate_eta, "collect", return_value=[]) as collect, mock.patch.object(slo, "run") as run, \
                mock.patch.object(forge_events, "gate_slow", return_value=DATA["slow"]) as slow, \
                mock.patch.object(forge_events.ForgeEvents, "emit") as emit:
            status.verdict_hooks(self.pub, verdict)
        collect.assert_called_once()
        slow.assert_called_once()
        run.assert_not_called()
        self.assertEqual(emit.call_args.args[0], "gate.slow")
        self.assertEqual(emit.call_args.args[1]["median_ms"], DATA["slow"]["median_ms"])

    def test_only_tier_1_verdicts_trigger_the_hooks_and_failures_never_raise(self):
        with mock.patch.object(gate_eta, "collect", side_effect=RuntimeError("down")) as collect:
            status.verdict_hooks(self.pub, dict(type="gate.passed", event_id="e", payload=dict(tier=DATA["other_tier"])))
            collect.assert_not_called()
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                status.verdict_hooks(self.pub, dict(type="gate.passed", event_id="e", payload=dict(tier=1, pr=1)))
        self.assertIn("gate verdict hooks: down", err.getvalue())

    def test_final_calls_the_hooks_after_the_comment(self):
        self.begin()
        with mock.patch.object(status, "verdict_hooks") as hooks:
            status.final(self.logs, dict(sha=SHA, result="PASS", stages=[]), [], 0, [], [], [dict(type="gate.passed", payload=dict(tier=1))],
                         publisher=self.pub, now=T0 + config.get("gate.status_min_interval_s"))
        hooks.assert_called_once()
        self.assertEqual(len(self.rest.comments), 1)


if __name__ == '__main__':
    unittest.main()
