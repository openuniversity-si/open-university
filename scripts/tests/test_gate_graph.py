"""The stage graph and its runner (GS1): sound, deterministic, bounded; parallel gives the verdict and report of serial."""
import copy
import json
import pathlib
import sys
import tempfile
import threading
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import gate_graph as graph  # noqa: E402
import gate_policy  # noqa: E402

STAGES = graph.load()


class ShippedGraphTest(unittest.TestCase):
    def test_the_shipped_graph_is_sound_and_covers_the_dev_plan(self):
        self.assertEqual(graph.check(), [])

    def test_every_dev_stage_is_declared(self):
        self.assertFalse(set(gate_policy.DEV_STAGES) - set(STAGES))

    def test_no_engine_stage_holds_a_scarce_resource(self):
        # OU-DECOUPLE F5 (D-113): the heavy database stages (integration tests, smoke database, db schema/migrations) left
        # with Open University; the cap itself (ou_gate_heavy_db_run) is tested by gate-heavy-db.test.sh.
        self.assertEqual(sorted(name for name, spec in STAGES.items() if spec["resources"]), [])

    def test_cheap_stages_come_first_and_pr_metadata_leads(self):
        # GATE-VERDICT-API (D-070): the declared, planned and displayed order puts the cheap checks before install and
        # the suites, `pr metadata` (about 5 s, the most frequent red) first; the three lists move together.
        cheap = ["pr metadata", "no GitHub Actions workflows", "secret scan (tree)", "structure check",
                 "generated drift", "schema compat", "secret scan (history)"]
        self.assertEqual(list(STAGES)[:len(cheap)], cheap)
        self.assertEqual(gate_policy.PREREQUISITES, cheap)
        self.assertEqual(gate_policy.DEV_STAGES[:len(cheap)], cheap)
        areas = json.loads((ROOT / "scripts" / "lib" / "gate-areas.json").read_text())
        self.assertEqual(areas["always"], cheap)
        self.assertEqual(areas["order"][:len(cheap)], cheap)
        # Display order is stable; independent tests do not consume any prerequisite's output (D-291).
        self.assertEqual(list(STAGES).index("script tests"), len(cheap))
        self.assertEqual(STAGES["script tests"]["needs"], [])
        self.assertFalse(STAGES["script tests"]["deterministic"])


class ValidateTest(unittest.TestCase):
    def test_an_unknown_need_a_self_need_and_a_cycle_are_errors(self):
        self.assertIn("a: needs ghost, which is not declared", graph.validate({"a": {"needs": ["ghost"]}}))
        self.assertIn("a: needs itself", graph.validate({"a": {"needs": ["a"]}}))
        cyclic = graph.validate({"a": {"needs": ["b"]}, "b": {"needs": ["a"]}})
        self.assertTrue(any(error.startswith("cycle") for error in cyclic))

    def test_an_unknown_stage_or_resource_and_an_incomplete_deterministic_stage_are_errors(self):
        self.assertTrue(graph.validate({"x": {"needs": []}}, known={"y"}))
        self.assertTrue(graph.validate({"x": {"needs": [], "resources": ["gpu"]}}))
        self.assertTrue(graph.validate({"x": {"needs": [], "deterministic": True}}))
        self.assertTrue(graph.validate({"x": {"needs": [], "deterministic": True, "inputs": ["**"], "version": "1"}}))

    def test_a_cycle_in_the_shipped_graph_is_refused(self):
        broken = copy.deepcopy(STAGES)
        broken["pr metadata"]["needs"].append("script tests")
        broken["script tests"]["needs"].append("pr metadata")
        self.assertTrue(graph.validate(broken))


DIAMOND = {"b": ["a"], "c": ["a"], "d": ["b", "c"]}
NAMES = ["a", "b", "c", "d", "e"]


class ScheduleTest(unittest.TestCase):
    def run_with(self, concurrency, failing=(), names=NAMES, needs=DIAMOND, order=None):
        started, peak, live, lock = [], [0], [0], threading.Lock()

        def work(name):
            with lock:
                started.append(name)
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            try:
                if order:
                    order(name)
                return name not in failing
            finally:
                with lock:
                    live[0] -= 1

        return graph.schedule(names, needs, work, concurrency), started, peak[0]

    def test_parallel_and_serial_report_the_same(self):
        for failing in ((), ("a",), ("b",), ("d",), ("e",), ("b", "c")):
            with self.subTest(failing=failing):
                serial, _, _ = self.run_with(1, failing)
                for concurrency in (2, 3, 8):
                    parallel, _, _ = self.run_with(concurrency, failing)
                    self.assertEqual(parallel, serial)
                    self.assertEqual([r["name"] for r in parallel], NAMES)

    def test_a_failing_stage_fails_and_skips_what_needs_it(self):
        report, started, _ = self.run_with(4, failing=("b",))
        self.assertEqual({r["name"]: r["result"] for r in report},
                         {"a": "PASS", "b": "FAIL", "c": "PASS", "d": "SKIPPED", "e": "PASS"})
        self.assertNotIn("d", started)

    def test_a_crashing_stage_is_a_failed_stage(self):
        report = graph.schedule(["x", "y"], {"y": ["x"]}, lambda name: 1 / 0, 2)
        self.assertEqual([r["result"] for r in report], ["FAIL", "SKIPPED"])

    def test_a_need_runs_before_what_needs_it(self):
        _, started, _ = self.run_with(8)
        self.assertLess(started.index("a"), started.index("b"))
        self.assertLess(started.index("a"), started.index("c"))
        self.assertLess(max(started.index("b"), started.index("c")), started.index("d"))

    def test_the_concurrency_cap_is_never_exceeded_and_is_used(self):
        gate = threading.Barrier(3, timeout=5)
        names = [f"t{i}" for i in range(9)]
        peak = [0]
        live = [0]
        lock = threading.Lock()

        def work(name):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            try:
                gate.wait() if name in ("t0", "t1", "t2") else None
                return True
            finally:
                with lock:
                    live[0] -= 1

        report = graph.schedule(names, {}, work, 3)
        self.assertEqual(peak[0], 3)
        self.assertTrue(all(r["result"] == "PASS" for r in report))

    def test_the_report_order_does_not_depend_on_the_finishing_order(self):
        # NANO-UNBLOCK (D-070): each job finishes only after the one declared next to it, so the finishing order is the
        # reverse of the declared one by construction. Releasing every job at once left the order to the thread
        # scheduler, which under a loaded gate woke them in declaration order (red on #592 #622 #635 #662).
        finished = {name: threading.Event() for name in NAMES}
        done, lock = [], threading.Lock()

        def order(name):
            later = NAMES[NAMES.index(name) + 1:]
            if later:
                finished[later[0]].wait(5)
            with lock:
                done.append(name)
            finished[name].set()

        report, _, _ = self.run_with(len(NAMES), needs={}, order=order)
        self.assertEqual([r["name"] for r in report], NAMES)
        self.assertEqual(done, NAMES[::-1])

    def test_a_need_outside_the_run_counts_as_met(self):
        report = graph.schedule(["b"], {"b": ["a"]}, lambda name: True, 1)
        self.assertEqual(report, [{"name": "b", "result": "PASS"}])

    def test_a_cycle_is_a_deadlock_error_not_a_hang(self):
        with self.assertRaises(graph.GraphError):
            graph.schedule(["a", "b"], {"a": ["b"], "b": ["a"]}, lambda name: True, 2)

    def test_a_name_twice_is_refused(self):
        with self.assertRaises(graph.GraphError):
            graph.schedule(["a", "a"], {}, lambda name: True, 1)

    def test_a_cap_below_one_is_refused(self):
        with self.assertRaises(graph.GraphError):
            graph.schedule(["a"], {}, lambda name: True, 0)


class CommandsTest(unittest.TestCase):
    def test_commands_report_in_order_with_their_output(self):
        results = graph.run_commands([("one", "echo first"), ("two", "echo oops >&2; exit 3"), ("three", "echo third")], 3)
        self.assertEqual([(r["name"], r["result"], r["exit"]) for r in results],
                         [("one", "PASS", 0), ("two", "FAIL", 3), ("three", "PASS", 0)])
        self.assertIn("oops", results[1]["output"])

    def test_ended_hears_every_command_once_after_it_ends(self):
        """GATE-SPEED F1 (D-118): the suite's jobserver learns of each end through `ended`."""
        heard = []
        graph.run_commands([("a", "true"), ("b", "exit 1")], 1, ended=heard.append)
        self.assertEqual(heard, ["a", "b"])

    def test_the_serial_and_parallel_reports_are_equal(self):
        commands = [("a", "true"), ("b", "exit 1"), ("c", "true")]
        self.assertEqual(graph.run_commands(commands, 1), graph.run_commands(commands, 3))

    def test_the_command_line_runs_a_list_and_fails_when_one_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            listing = pathlib.Path(tmp) / "commands"
            listing.write_text("ok\ttrue\nbad\techo boom; false\n")
            self.assertEqual(graph.main(["gate_graph.py", "run-commands", str(listing)]), 1)
            listing.write_text("ok\ttrue\n")
            self.assertEqual(graph.main(["gate_graph.py", "run-commands", str(listing)]), 0)



class FailureSummary(unittest.TestCase):
    """AWS7: the last lines of a check's output name the failures, whatever the 2000-character tail cuts."""
    UNITTEST = (
        "." * 5 + "\n" + "=" * 70 + "\nFAIL: test_a (test_x.T.test_a) (script='service')\n" + "-" * 70 + "\n"
        "Traceback (most recent call last):\n  File \"x.py\", line 1, in test_a\nAssertionError: 1 != 0 : box:\nrunner: boom\n\n"
        + "=" * 70 + "\nFAIL: test_b (test_x.T.test_b)\n" + "-" * 70 + "\nTraceback (most recent call last):\nAssertionError: False is not true\n\n"
        + "-" * 70 + "\nRan 8 tests in 1.0s\n\nFAILED (failures=2)\n")

    def test_it_names_each_unittest_failure_with_its_first_assertion_lines(self):
        lines = graph.failure_lines(self.UNITTEST)
        self.assertEqual(lines[0], "FAIL: test_a (test_x.T.test_a) (script='service')")
        self.assertEqual(lines[1], "AssertionError: 1 != 0 : box:")
        self.assertIn("AssertionError: False is not true", lines)
        self.assertNotIn("Traceback (most recent call last):", lines)

    def test_a_non_unittest_output_gives_its_last_error_lines(self):
        self.assertEqual(graph.failure_lines("ok\nnot ok 3 thing\nmore\n"), ["not ok 3 thing"])
        self.assertEqual(graph.failure_lines("a\nlast words\n"), ["last words"])

    def test_the_summary_is_capped_and_empty_without_failures(self):
        self.assertEqual(graph.summary([]), "")
        big = graph.summary([(f"t{n}", ["x" * 150] * 6) for n in range(10)])
        self.assertLessEqual(len(big), graph.SUMMARY_CHARS)
        self.assertTrue(big.startswith("FAILURE SUMMARY (10 failed)\nFAIL t0"))


if __name__ == "__main__":
    unittest.main()
