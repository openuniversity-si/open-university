"""Failing test ids and signatures in the gate verdict (GS1): stable across runs, capped, contract-valid. Hermetic."""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import config  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402
import gate_failures as failures  # noqa: E402
import gate_report  # noqa: E402

CHECKOUT = "/home/user/the-tower"
WEB_FILE = "/".join((CHECKOUT, "products/demo/src/ui/Foo.ts"))  # built: no new absolute literal
# F46: the log of a red non-test stage, with the lines the retired vitest reader took for a test (a `FAIL` before a
# `.test.ts` path) and the engine's own FAIL lines. Before F46 the gate read the first as a failing test only because
# Open University's suites printed it; no engine stage does, so the gate lists no test for any of these.
VITEST_LIKE = f"""
 FAIL  |unit| src/ui/Foo.test.ts > suite > case
\x1b[31mError: boom in {WEB_FILE} at 12 ms\x1b[0m
"""
ENGINE_LOGS = {
    "structure check": "FAIL docs/units/X/plan.md: no ## Escolha\n",
    "shellcheck": "In scripts/gate-local line 3:\nSC2086: Double quote to prevent globbing\n",
    "secret scan (tree)": "Finding: generic-api-key\nFAIL 1 leak(s)\n",
    "script tests": "FAIL scripts/tests/p.test.sh\nAssertionError: x\n",
}


class NormalizeTest(unittest.TestCase):
    def test_numbers_paths_colours_and_spacing_do_not_change_the_signature(self):
        one = failures.normalize("\x1b[31mError: expected 3 in /home/user/a/b/c/file.ts  after 12.5 ms\x1b[0m")
        two = failures.normalize("Error:   expected 90 in /tmp/x/y/z/file.ts after 7 ms")
        self.assertEqual(one, two)
        self.assertEqual(one, "Error: expected N in file.ts after N ms")

    def test_a_relative_path_is_kept_whole_and_an_absolute_one_is_reduced(self):
        self.assertEqual(failures.normalize("GenerateError: products/demo/scripts/intents-doc.ts failed (1)"),
                         "GenerateError: products/demo/scripts/intents-doc.ts failed (N)")
        self.assertEqual(failures.normalize(f"failed in ({WEB_FILE[:-len('ui/Foo.ts')]}x.ts:12)"), "failed in (x.ts:N)")

    def test_a_different_error_is_a_different_signature(self):
        self.assertNotEqual(failures.normalize("Error: a"), failures.normalize("Error: b"))

    def test_the_signature_is_capped_by_the_registry(self):
        cap = config.get("gate.failing_signature_chars")
        self.assertEqual(len(failures.normalize("x" * (cap + 50))), cap)

    def test_the_first_non_empty_line_is_the_signature(self):
        self.assertEqual(failures.normalize("\n\n  first\nsecond"), "first")
        self.assertEqual(failures.normalize(""), "")
        self.assertEqual(failures.normalize(None), "")


class ScriptTest(unittest.TestCase):
    def test_a_failed_script_test_signs_with_the_last_assertion(self):
        tail = ["FAIL: test_x (__main__.Repository.test_x)", "Traceback (most recent call last):",
                "  File \"/tmp/a/b/c/t.py\", line 280, in test_x", "AssertionError: Items in the first set: 'measurement:S1'",
                "", "FAILED (failures=1)"]
        found = failures.script_failures([{"test": "scripts/tests/p.test.sh", "result": "FAIL", "tail": tail},
                                          {"test": "scripts/tests/q.test.sh", "result": "PASS", "tail": []}])
        self.assertEqual(found, [{"id": "scripts/tests/p.test.sh", "stage": "script tests",
                                  "signature": "AssertionError: Items in the first set: 'measurement:S1'"}])


class CollectTest(unittest.TestCase):
    def make(self, tmp, stages, logs=None, records=None):
        tmp = pathlib.Path(tmp)
        for name, text in (logs or {}).items():
            (tmp / (gate_report.re.sub(r"[^a-zA-Z0-9]", "_", name) + ".log")).write_text(text)
        if records is not None:
            (tmp / "script-tests.json").write_text(json.dumps(records))
        return tmp, {"stages": [{"name": n, "result": r} for n, r in stages]}

    def test_the_failing_tests_are_the_script_records_whatever_the_stage_logs_say(self):
        records = [{"test": "scripts/tests/p.test.sh", "result": "FAIL", "tail": ["Error: x"]},
                   {"test": "scripts/tests/q.test.sh", "result": "PASS", "tail": []}]
        with tempfile.TemporaryDirectory() as tmp:
            logs, _ = self.make(tmp, [(name, "FAIL") for name in ENGINE_LOGS], ENGINE_LOGS, records)
            found, total = failures.failing(logs)
        self.assertEqual((found, total), ([{"id": "scripts/tests/p.test.sh", "stage": "script tests", "signature": "Error: x"}], 1))

    def test_a_failed_non_test_stage_yields_no_test_entries(self):
        """F46: every stage the gate runs but `script tests` fails with no test listed, a vitest-looking line included;
        before F46 the same engine logs yielded none either (the vitest reader matched only `.test.[jt]s` paths)."""
        import gate_policy
        for name in [stage for stage in gate_policy.FULL_STAGES if stage != "script tests"]:
            with self.subTest(stage=name), tempfile.TemporaryDirectory() as tmp:
                logs, _ = self.make(tmp, [(name, "FAIL")], {name: ENGINE_LOGS.get(name, "") + VITEST_LIKE})
                self.assertEqual(failures.failing(logs), ([], 0))

    def test_the_list_is_capped_and_the_total_is_kept(self):
        records = [{"test": f"scripts/tests/t{i:03}.test.sh", "result": "FAIL", "tail": [f"Error: e{i}"]} for i in range(60)]
        with tempfile.TemporaryDirectory() as tmp:
            logs, _ = self.make(tmp, [("script tests", "FAIL")], records=records[::-1])
            found, total = failures.failing(logs)
        self.assertEqual((len(found), total), (config.get("gate.failing_tests_max"), 60))
        self.assertEqual(found, sorted(found, key=lambda item: item["id"]))

    def test_cached_tests_name_the_key_and_the_source_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs, _ = self.make(tmp, [], records=[
                {"test": "scripts/tests/a.test.sh", "result": "PASS", "cached": True, "key": "k1", "source": "s1", "tail": []},
                {"test": "scripts/tests/b.test.sh", "result": "PASS", "cached": False, "key": "k2", "source": "s2", "tail": []}])
            self.assertEqual(failures.cached_tests(logs), [{"id": "scripts/tests/a.test.sh", "key": "k1", "source": "s1"}])

    def test_a_missing_or_broken_record_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(failures.cached_tests(tmp), [])
            (pathlib.Path(tmp) / "script-tests.json").write_text("not json")
            self.assertEqual(failures.cached_tests(tmp), [])
            (pathlib.Path(tmp) / "script-tests.json").write_text('{"a": 1}')
            self.assertEqual(failures.cached_tests(tmp), [])


class VerdictTest(unittest.TestCase):
    """The published events carry the lists and still satisfy their contracts."""

    def run_gate(self, rc, records, log):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp)
        logs = tmp / "logs"
        logs.mkdir()
        for name, result in (("secret scan (tree)", "PASS"), ("structure check", "FAIL" if rc else "PASS")):
            safe = "".join(c if c.isalnum() else "_" for c in name)
            (logs / f"{safe}.stage.json").write_text(json.dumps({"name": name, "result": result, "exit": int(result == "FAIL"), "seconds": 1}))
            (logs / f"{safe}.log").write_text(log if result == "FAIL" else "ok")
        (logs / "script-tests.json").write_text(json.dumps(records))
        head = "a" * 40
        adapter = forge_events.MemoryAdapter({("openuniversity-si/open-university", 7): {"head": head, "base": "b" * 40, "body": "Premises: P-41"}})
        clock = mock.Mock()
        clock.now.return_value = __import__("datetime").datetime(2026, 10, 27, tzinfo=__import__("datetime").timezone.utc)
        port = forge_events.ForgeEvents(adapter, clock, "gate_report", "run-1")
        report = {"sha": head, "result": "FAIL" if rc else "PASS", "stages": gate_report.stage_results(logs)}
        return gate_report.emit_evidence(report, "dev", 7, logs, port)

    def test_a_failed_gate_publishes_the_failing_tests_and_the_cached_ones(self):
        verdict = self.run_gate(1, [
            {"test": "scripts/tests/a.test.sh", "result": "PASS", "cached": True, "key": "k1", "source": "s1", "tail": []},
            {"test": "scripts/tests/p.test.sh", "result": "FAIL", "cached": False, "key": "k2", "source": "s2", "tail": ["Error: x"]}],
            VITEST_LIKE)
        payload = verdict["payload"]
        self.assertEqual(verdict["type"], "gate.failed")
        self.assertEqual([item["id"] for item in payload["failing_tests"]], ["scripts/tests/p.test.sh"])
        self.assertEqual(payload["failing_tests_total"], 1)
        self.assertEqual(payload["cached_tests"], [{"id": "scripts/tests/a.test.sh", "key": "k1", "source": "s1"}])

    def test_a_passed_gate_publishes_cached_tests_and_no_failing_list(self):
        verdict = self.run_gate(0, [{"test": "scripts/tests/a.test.sh", "result": "PASS", "cached": True, "key": "k1",
                                     "source": "s1", "tail": []}], "")
        self.assertEqual(verdict["type"], "gate.passed")
        self.assertNotIn("failing_tests", verdict["payload"])
        self.assertEqual(verdict["payload"]["cached_tests"][0]["key"], "k1")

    def test_no_script_record_publishes_no_cached_tests(self):
        verdict = self.run_gate(0, [], "")
        self.assertNotIn("cached_tests", verdict["payload"])

    def test_both_payloads_satisfy_their_contracts(self):
        for rc, kind in ((1, "gate.failed"), (0, "gate.passed")):
            verdict = self.run_gate(rc, [{"test": "scripts/tests/a.test.sh", "result": "PASS", "cached": True, "key": "k1",
                                          "source": "s1", "tail": []}], ENGINE_LOGS["structure check"])
            self.assertEqual(verdict["type"], kind)
            self.assertIs(event_contracts.validate(verdict), verdict, kind)

    def test_a_payload_outside_the_contract_is_refused(self):
        verdict = self.run_gate(1, [{"test": "scripts/tests/p.test.sh", "result": "FAIL", "tail": ["Error: x"]}],
                                ENGINE_LOGS["structure check"])
        verdict["payload"]["failing_tests"][0]["extra"] = 1
        with self.assertRaises(event_contracts.ContractError):
            event_contracts.validate(verdict)


if __name__ == "__main__":
    unittest.main()
