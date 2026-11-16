"""Per-test script cache (GS1): a key covers the test and its covers files; unknown or unhashable inputs always run. Hermetic."""
import contextlib
import datetime
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import config  # noqa: E402
import gate_test_cache as cache  # noqa: E402

TWO = 1 + 1  # small counts for the sizing tests, built from 1 so no new literal enters the census
THREE = TWO + 1
A, B, C = "scripts/tests/a.test.sh", "scripts/tests/b.test.sh", "scripts/tests/c.test.sh"
MAPPING = {"tests": (
    {"script": A, "covers": ("scripts/lib/dep.py", "scripts/tests/a.test.sh")},
    {"script": B, "covers": ("scripts/lib/dep.py", "config/registry/*.json")},
    {"script": C, "covers": ()},
)}


class Repo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self._tmp.name)
        self.root = self.base / "repo"
        self.store = self.base / "store"
        self.write(A, 'echo a >>"$RUNLOG"\n')
        self.write(B, 'echo b >>"$RUNLOG"\nexit 3\n')
        self.write(C, 'echo c >>"$RUNLOG"\n')
        self.write("scripts/lib/dep.py", "x = 1\n")
        self.write("scripts/lib/other.py", "y = 1\n")
        self.write("scripts/lib/hermetic/h.py", "h = 1\n")
        self.write("config/registry/gate.json", "{}\n")
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        self.runlog = self.base / "runlog"
        self.runlog.write_text("")
        env = mock.patch.dict(os.environ, {"RUNLOG": str(self.runlog), cache.gate_tier.ENV: ""})
        env.start()
        self.addCleanup(env.stop)
        node = mock.patch.object(cache, "_node_version", return_value="v0")
        node.start()
        self.addCleanup(node.stop)
        # F128: these tests exercise keys and the cache, not the fork server (ForkServerTest covers it); starting one per run cost ~0.4 s each
        forks = mock.patch.object(cache, "forks", side_effect=lambda *a, **k: contextlib.nullcontext({}))
        forks.start()
        self.addCleanup(forks.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def stage(self):
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)

    def key(self, script=A, files=None):
        return cache.key(script, self.root, MAPPING, files, node="v0")

    def ran(self):
        return self.runlog.read_text().split()

    def go(self, scripts, now=1000, source="run-1"):
        return cache.run(scripts, self.root, self.store, source, ROOT, concurrency=2, mapping=MAPPING, now=now)


class KeyTest(Repo):
    def test_the_same_inputs_give_the_same_key(self):
        self.assertTrue(self.key())
        self.assertEqual(self.key(), self.key())
        self.assertNotEqual(self.key(A), self.key(B))

    def test_a_changed_covered_file_changes_the_key(self):
        before = self.key()
        self.write("scripts/lib/dep.py", "x = 2\n")
        self.assertNotEqual(self.key(), before)

    def test_a_changed_covered_glob_match_changes_the_key(self):
        before = self.key(B)
        self.write("config/registry/gate.json", '{"a": 1}\n')
        self.assertNotEqual(self.key(B), before)

    def test_a_changed_test_script_changes_the_key(self):
        before = self.key()
        self.write(A, 'echo a >>"$RUNLOG"\necho more\n')
        self.assertNotEqual(self.key(), before)

    def test_a_new_file_matching_a_covered_glob_changes_the_key(self):
        before = self.key(B)
        self.write("config/registry/new.json", "{}\n")
        self.assertNotEqual(self.key(B), before)

    def test_a_deleted_covered_file_changes_the_key(self):
        before = self.key()
        (self.root / "scripts/lib/dep.py").unlink()
        self.assertNotEqual(self.key(), before)

    def test_a_file_the_test_does_not_cover_does_not_change_the_key(self):
        before = self.key()
        self.write("scripts/lib/other.py", "y = 2\n")
        self.assertEqual(self.key(), before)

    def test_a_common_input_changes_every_key(self):
        before = (self.key(A), self.key(B))
        self.write("scripts/lib/hermetic/h.py", "h = 2\n")
        # the hermetic wrapper is a common input only when the registry names it
        self.assertEqual(config.get("gate.test_cache_common_inputs")[0], "scripts/lib/hermetic/**")
        self.assertNotEqual((self.key(A), self.key(B)), before)

    def test_a_toolchain_pin_changes_the_key(self):
        before = self.key()
        real = config.get
        for name in cache.TOOLCHAIN_PINS:
            with self.subTest(pin=name):
                with mock.patch.object(config, "get", side_effect=lambda n, *a, _n=name: real(n, *a) + ".1" if n == _n else real(n, *a)):
                    self.assertNotEqual(self.key(), before)

    def test_the_node_version_and_the_registry_key_version_change_the_key(self):
        before = self.key()
        self.assertNotEqual(cache.key(A, self.root, MAPPING, None, node="v1"), before)
        real = config.get
        with mock.patch.object(config, "get", side_effect=lambda n, *a: real(n, *a) + 1 if n == "gate.test_cache_version" else real(n, *a)):
            self.assertNotEqual(self.key(), before)

    def test_a_different_covers_declaration_changes_the_key(self):
        other = {"tests": ({"script": A, "covers": ("scripts/lib/dep.py", "scripts/lib/other.py")},)}
        self.assertNotEqual(cache.key(A, self.root, other, None, node="v0"), self.key())

    def test_unknown_inputs_have_no_key(self):
        self.assertEqual(self.key("scripts/tests/unknown.test.sh"), "")
        self.assertEqual(self.key(C), "")  # no covers
        (self.root / A).unlink()
        self.assertEqual(self.key(A), "")  # the script itself is gone

    def test_an_input_that_cannot_be_hashed_has_no_key(self):
        os.symlink(self.root / "scripts/lib/other.py", self.root / "scripts/lib/link.py")
        self.stage()
        mapping = {"tests": ({"script": A, "covers": ("scripts/lib/link.py",)},)}
        self.assertEqual(cache.key(A, self.root, mapping, None, node="v0"), "")
        (self.root / "scripts/lib/adir").mkdir()
        files = ["scripts/lib/adir", A]
        mapping = {"tests": ({"script": A, "covers": ("scripts/lib/adir",)},)}
        self.assertEqual(cache.key(A, self.root, mapping, files, node="v0"), "")

    def test_the_flag_switches_the_cache_off(self):
        real = config.get
        with mock.patch.object(config, "get", side_effect=lambda n, *a: False if n == "gate.test_cache_enabled" else real(n, *a)):
            self.assertEqual(self.key(), "")


class MarkerTest(Repo):
    def test_a_recorded_pass_is_found_until_it_expires(self):
        ttl = config.get("gate.test_cache_ttl_s")
        cache.record(self.store, "k", A, "run-1", now=1000)
        self.assertEqual(cache.lookup(self.store, "k", now=1000)["source"], "run-1")
        self.assertIsNotNone(cache.lookup(self.store, "k", now=1000 + ttl))
        self.assertIsNone(cache.lookup(self.store, "k", now=1000 + ttl + 1))
        self.assertIsNone(cache.lookup(self.store, "k", now=999))

    def test_corrupt_markers_are_misses(self):
        for name, blob in (("empty", b""), ("garbage", b"\x00\xff"), ("list", b"[]"),
                           ("no-source", b'{"key": "m-no-source", "stored_at": 1000}'),
                           ("other-key", b'{"key": "x", "stored_at": 1000, "source": "s"}'),
                           ("text-time", b'{"key": "m-text-time", "stored_at": "1", "source": "s"}')):
            with self.subTest(case=name):
                cache.storage.open_store(self.store).put(f"script-tests/m-{name}", blob)
                self.assertIsNone(cache.lookup(self.store, f"m-{name}", now=1000))

    def test_an_empty_key_is_never_stored_or_found(self):
        with self.assertRaises(ValueError):
            cache.record(self.store, "", A, "run-1")
        self.assertIsNone(cache.lookup(self.store, "", now=1000))


class RunTest(Repo):
    def test_a_passed_test_is_cached_and_a_failed_one_runs_again(self):
        first = self.go([A, B], source="run-1")
        self.assertEqual([(r["test"], r["result"], r["cached"]) for r in first], [(A, "PASS", False), (B, "FAIL", False)])
        self.assertEqual(sorted(self.ran()), ["a", "b"])
        second = self.go([A, B], now=1010, source="run-2")
        self.assertEqual([(r["test"], r["result"], r["cached"]) for r in second], [(A, "PASS", True), (B, "FAIL", False)])
        self.assertEqual(second[0]["source"], "run-1")
        self.assertEqual(second[0]["key"], self.key(A))
        self.assertEqual(sorted(self.ran()), ["a", "b", "b"])  # a was not run again, b was
        self.assertIsNone(cache.lookup(self.store, self.key(B), now=1010))  # a failure is never recorded

    def test_a_process_tree_that_names_its_workers_runs_that_many_tests_at_once(self):
        # FULL-RUN-BATCH-ONE: a full run's batch runs its tests one at a time in its slot
        from unittest import mock
        with mock.patch.dict(os.environ, {cache.WORKERS_ENV: '1'}):
            self.assertEqual(cache.script_tests_workers(cpus=8), 1)
        with mock.patch.dict(os.environ, {cache.WORKERS_ENV: 'many'}):
            self.assertEqual(cache.script_tests_workers(cpus=8), cache.script_tests_workers.__wrapped__(8)
                             if hasattr(cache.script_tests_workers, '__wrapped__') else
                             max(1, min(cache.setting('script_tests_concurrency'), int(8 * cache.setting('script_tests_per_vcpu')))))

    def test_with_the_store_off_every_test_runs_and_nothing_is_recorded(self):
        # FULL-RUN-NO-CACHE: the base's full run asked `gate-check test` in a slot whose store answered it by a key that did
        # not cover the stack the test reads (infra-autodeploy at c8d1fa3f, 13/11)
        self.go([A], source="run-1")
        from unittest import mock
        with mock.patch.dict(os.environ, {cache.OFF_ENV: '1'}):
            again = self.go([A], now=1010, source="run-2")
            self.go([B], now=1020, source="run-3")
        self.assertEqual([(r["test"], r["result"], r["cached"]) for r in again], [(A, "PASS", False)])
        self.assertEqual(self.ran(), ["a", "a", "b"])
        self.assertEqual(cache.lookup(self.store, self.key(A), now=1030)["source"], "run-1")  # run-2 recorded nothing

    def test_a_changed_covered_file_runs_the_test_again(self):
        self.go([A])
        self.write("scripts/lib/dep.py", "x = 2\n")
        again = self.go([A], now=1010)
        self.assertFalse(again[0]["cached"])
        self.assertEqual(self.ran(), ["a", "a"])

    def test_a_file_the_test_does_not_cover_leaves_it_cached(self):
        self.go([A])
        self.write("scripts/lib/other.py", "y = 2\n")
        self.assertTrue(self.go([A], now=1010)[0]["cached"])
        self.assertEqual(self.ran(), ["a"])

    def test_a_corrupt_entry_runs_the_test(self):
        self.go([A])
        cache.storage.open_store(self.store).put(f"script-tests/{self.key(A)}", b"garbage")
        self.assertFalse(self.go([A], now=1010)[0]["cached"])
        self.assertEqual(self.ran(), ["a", "a"])

    def test_an_expired_entry_runs_the_test(self):
        self.go([A], now=1000)
        later = 1000 + config.get("gate.test_cache_ttl_s") + 1
        self.assertFalse(self.go([A], now=later)[0]["cached"])

    def test_a_test_without_a_key_always_runs_and_is_never_recorded(self):
        self.go([C])
        self.assertFalse(self.go([C], now=1010)[0]["cached"])
        self.assertEqual(self.ran(), ["c", "c"])
        self.assertEqual(cache.storage.open_store(self.store).keys("script-tests") if (self.store / "script-tests").exists() else [], [])

    def test_the_report_names_the_key_and_the_source_run(self):
        self.go([A], source="run-1")
        results = self.go([A, B], now=1010, source="run-2")
        with mock.patch("builtins.print") as printed:
            status = cache.report(results)
        lines = [call.args[0] for call in printed.call_args_list]
        self.assertEqual(status, 1)
        self.assertIn(f"PASS {A} (cached: key {self.key(A)[:12]}, source run-1)", lines)
        self.assertIn(f"FAIL {B}", lines)

    def test_the_report_ends_with_the_summary_inside_a_2000_character_tail(self):
        noise = [f"noise {n}" for n in range(40)]
        item = {"test": "scripts/tests/y.test.sh", "result": "FAIL", "cached": False, "tail": noise,
                "failure": ["FAIL: test_b (test_x.T.test_b)", "AssertionError: False is not true"]}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cache.report([item]), 1)
        text = out.getvalue()
        self.assertIn("FAILURE SUMMARY (1 failed)", text[-2000:])
        self.assertTrue(text.rstrip().endswith("AssertionError: False is not true"))

    def test_a_test_that_ran_says_its_seconds_and_a_cached_one_does_not(self):
        # GATE-PACE: the batch's walls reach verify-commit's pace line through gate-check's answer
        [ran] = self.go([A])
        self.assertIsInstance(ran["seconds"], float)
        self.assertGreaterEqual(ran["seconds"], 0.0)
        [cached] = self.go([A], now=1010)
        self.assertTrue(cached["cached"])
        self.assertNotIn("seconds", cached)

    def test_the_results_follow_the_order_of_the_list(self):
        self.go([A])
        self.assertEqual([r["test"] for r in self.go([B, A], now=1010)], [B, A])

    def test_the_command_line_writes_the_record_of_the_run(self):
        listing = self.base / "list"
        listing.write_text(f"{A}\n")
        logs = self.base / "logs"
        logs.mkdir()
        with mock.patch.object(cache.gate_script_tests, "load", return_value=MAPPING), \
                mock.patch.dict(os.environ, {"GATE_TEST_CACHE_DIR": str(self.store)}):
            self.assertEqual(cache.main(["gate_test_cache.py", "run", str(listing), "--root", str(self.root),
                                         "--tool-root", str(ROOT), "--logs", str(logs), "--source", "run-9"]), 0)
        self.assertEqual(json.loads((logs / "script-tests.json").read_text())[0]["test"], A)


class OneTestTest(Repo):
    """CHECK-ENVELOPE: one test (a check job's) reads and records no durations; a list still does."""

    def test_one_test_reads_and_records_no_durations_and_a_list_does(self):
        logs = self.base / "logs"
        logs.mkdir()
        for listed, read in (([A], False), ([A, B], True)):
            listing = self.base / "listing"
            listing.write_text("".join(f"{each}\n" for each in listed))
            durations = mock.Mock(return_value={})
            with mock.patch.object(cache, "run", return_value=[]) as run, \
                    mock.patch.object(cache, "measured_durations", durations), \
                    mock.patch.object(cache, "store_location", return_value=self.store), \
                    contextlib.redirect_stdout(io.StringIO()):
                cache.main(["gate_test_cache", "run", str(listing), "--root", str(self.root), "--tool-root", str(ROOT),
                            "--logs", str(logs)])
            self.assertEqual((durations.called, run.call_args.kwargs['measure']), (read, read), listed)
            if not read:
                self.assertEqual(run.call_args.kwargs['durations'], {})


class DeletedTest(Repo):
    """OU-DECOUPLE F2 (D-107): a test the change deletes together with its covers manifest is not run."""

    def manifest(self, script):
        return cache.gate_script_tests.manifest_path(script, self.root)

    def test_d107_only_a_test_deleted_with_its_manifest_is_left_out(self):
        for script in (A, B, C):
            target = self.manifest(script)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}\n")
        (self.root / B).unlink()
        self.manifest(B).unlink()
        (self.root / C).unlink()
        self.assertEqual(cache.deleted([A, B, C], self.root), [B])

    def test_d107_the_run_command_names_the_deleted_test_and_runs_the_rest(self):
        self.manifest(A).parent.mkdir(parents=True, exist_ok=True)
        self.manifest(A).write_text("{}\n")
        (self.root / B).unlink()
        listing = self.base / "listing"
        listing.write_text(f"{A}\n{B}\n")
        logs = self.base / "logs"
        logs.mkdir()
        out = io.StringIO()
        with mock.patch.object(cache, "run", return_value=[{"test": A, "result": "PASS", "cached": False, "key": "",
                                                           "source": "s", "tail": []}]) as run, \
                mock.patch.object(cache, "measured_durations", return_value={}), \
                mock.patch.object(cache, "store_location", return_value=self.store), \
                contextlib.redirect_stdout(out):
            code = cache.main(["gate_test_cache", "run", str(listing), "--root", str(self.root), "--tool-root", str(ROOT),
                               "--logs", str(logs)])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[0], [A])
        self.assertIn(f"SKIP {B} (this change deletes it with its covers manifest; D-107)", out.getvalue())


class TierTest(Repo):
    """GX-11 as amended by D-076 (P-56): tier 2 reuses a PASS by its content key, tier 3 (the battery) never reads or
    writes a marker; with gate.content_cache_enabled off, tier 2 is uncached again (D-065 (5))."""

    def at(self, name):
        return mock.patch.dict(os.environ, {cache.gate_tier.ENV: cache.gate_tier.bind(config.get(f"gate-tier.{name}"))})

    def content(self, enabled):
        real = config.get
        return mock.patch.object(config, "get", lambda name, *rest: enabled if name == "gate.content_cache_enabled"
                                 else real(name, *rest))

    def warm(self):
        with self.at("per_pr"):
            self.go([A, C], source="run-1")
            self.assertNotEqual(self.key(A), "")
        self.assertTrue([p for p in self.store.rglob("*") if p.is_file()])  # the store is warm: A's marker

    def test_a_tier_2_run_reuses_by_content_and_tier_3_runs_every_test_and_records_nothing(self):
        self.warm()
        with self.at("batch"):
            again = self.go([A, C], source="run-batch")
            self.assertEqual([(r["test"], r["cached"], r["source"]) for r in again],
                             [(A, True, "run-1"), (C, False, "run-batch")])
        with self.at("battery"):
            markers = sorted(p.name for p in self.store.rglob("*") if p.is_file())
            again = self.go([A, C], source="run-battery")
            self.assertEqual([(r["test"], r["cached"], r["key"]) for r in again], [(A, False, ""), (C, False, "")])
            self.assertEqual(self.key(A), "")
            self.assertEqual(sorted(p.name for p in self.store.rglob("*") if p.is_file()), markers)
        self.assertEqual(sorted(self.ran()), ["a", "a", "c", "c", "c"])  # tier 2 reused a; the battery ran both

    def test_with_the_content_cache_off_a_tier_2_run_runs_every_test_and_records_nothing(self):
        self.warm()
        with self.content(False):
            for name in ("batch", "battery"):
                with self.subTest(tier=name), self.at(name):
                    markers = sorted(p.name for p in self.store.rglob("*") if p.is_file())
                    again = self.go([A, C], source=f"run-{name}")
                    self.assertEqual([(r["test"], r["cached"], r["key"]) for r in again],
                                     [(A, False, ""), (C, False, "")])
                    self.assertEqual(self.key(A), "")
                    self.assertEqual(sorted(p.name for p in self.store.rglob("*") if p.is_file()), markers)
            self.assertEqual(sorted(self.ran()), ["a", "a", "a", "c", "c", "c"])  # every run ran both
            with self.at("per_pr"):
                hit = self.go([A], source="run-4")
                self.assertEqual((hit[0]["cached"], hit[0]["source"]), (True, "run-1"))
            self.assertEqual(sorted(self.ran()), ["a", "a", "a", "c", "c", "c"])  # the tier-1 hit did not run a

    def test_the_key_covers_the_judging_runner(self):
        """D-076: a change to how the gate runs a test (gate.content_runner_inputs) is a change to every key."""
        before = self.key(A)
        with mock.patch.object(cache.gate_keys, "runner_id", return_value="another runner"):
            self.assertNotEqual(self.key(A), before)

    def test_the_tests_run_without_the_gates_tier(self):
        self.write(A, 'echo "tier=${OU_GATE_TIER:-unset}" >>"$RUNLOG"\n')
        with self.at("batch"):
            self.go([A])
        self.assertEqual(self.ran(), ["tier=unset"])

    def test_the_key_covers_the_proof_key_parts(self):
        before = self.key(A)
        with mock.patch.object(cache.gate_keys, "key_parts", return_value=["base:x"]):
            self.assertNotEqual(self.key(A), before)


class ParallelTest(unittest.TestCase):
    """D-076 (GATE-FAST): each running script test gets its share of the vCPUs; parallel_tests runs its files side by
    side within it, output in the given order."""

    BOX = config.get("gate.script_tests_concurrency")  # a box as wide as the cap: every test may run at once
    PAIR = len((A, C))

    def test_the_share_is_the_vcpus_over_the_tests_running_at_once(self):
        box = self.BOX
        self.assertEqual(cache.test_cpus(1, box, cpus=box), box)
        self.assertEqual(cache.test_cpus(self.PAIR, box, cpus=box), box // self.PAIR)
        self.assertEqual(cache.test_cpus(box * box, box, cpus=box), 1)
        self.assertEqual(cache.test_cpus(0, box, cpus=box), box)
        self.assertEqual(cache.test_cpus(box, 1, cpus=1), 1)

    def test_every_started_test_sees_its_share(self):
        captured = {}

        def commands(todo, workers, env, cwd, timings, ended=None):
            captured.update(env)
            timings.update({script: 0 for script, _ in todo})
            return [{"name": script, "result": cache.gate_graph.PASS, "output": ""} for script, _ in todo]

        with tempfile.TemporaryDirectory() as store, \
                mock.patch.object(cache.gate_graph, "run_commands", side_effect=commands), \
                mock.patch.object(cache, "key", return_value=""), mock.patch.object(cache, "vcpus", return_value=self.BOX):
            cache.run([A], ROOT, pathlib.Path(store), "run-1", ROOT, concurrency=self.BOX, mapping={"tests": []})
        self.assertEqual(captured[cache.parallel_tests.ENV], str(self.BOX))

    def test_every_started_test_sees_the_hermetic_git_configuration_and_never_the_box(self):
        """GATE-SPEED F1 (D-118): GIT_CONFIG_GLOBAL names the judge's file and the system configuration is off."""
        captured = {}

        def commands(todo, workers, env, cwd, timings, ended=None):
            captured.update(env)
            timings.update({script: 0 for script, _ in todo})
            return [{"name": script, "result": cache.gate_graph.PASS, "output": ""} for script, _ in todo]

        with tempfile.TemporaryDirectory() as store, \
                mock.patch.object(cache.gate_graph, "run_commands", side_effect=commands), \
                mock.patch.object(cache, "key", return_value=""):
            cache.run([A], ROOT, pathlib.Path(store), "run-1", ROOT, concurrency=self.BOX, mapping={"tests": []})
        self.assertEqual(captured["GIT_CONFIG_GLOBAL"], str(ROOT / config.get("gate.test_git_config")))
        self.assertEqual(captured["GIT_CONFIG_NOSYSTEM"], "1")
        # GATE-SPEED F5: the overrides reach a process whose fixture points GIT_CONFIG_GLOBAL at /dev/null
        blanked = {**os.environ, **captured, "GIT_CONFIG_GLOBAL": os.devnull}
        seen = subprocess.run(["git", "config", "--get", "maintenance.auto"], env=blanked, capture_output=True,
                              text=True, check=True).stdout.strip()
        self.assertEqual(seen, "false")
        self.assertEqual(int(captured["GIT_CONFIG_COUNT"]), len(config.get("gate.test_git_overrides")))

    def test_the_hermetic_git_configuration_has_an_identity_and_signs_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, **cache.hermetic_git(ROOT), HOME=folder)
            subprocess.run(["git", "init", "-q", folder], check=True, env=env)
            subprocess.run(["git", "-C", folder, "commit", "-q", "--allow-empty", "-m", "x"], check=True, env=env)
            shown = subprocess.run(["git", "-C", folder, "log", "-1", "--format=%an <%ae> %G?"], check=True,
                                   capture_output=True, text=True, env=env).stdout.strip()
        self.assertEqual(shown, "Tower Test <test@example.invalid> N")

    def test_parallel_tests_runs_every_file_and_fails_when_one_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            good, bad = pathlib.Path(folder) / "good.py", pathlib.Path(folder) / "bad.py"
            good.write_text("print('good ran')\n")
            bad.write_text("import sys\nprint('bad ran')\nsys.exit(1)\n")
            code, results = cache.parallel_tests.run([str(good), str(bad)], workers=self.PAIR)
        self.assertEqual(code, 1)
        self.assertEqual([(path.endswith("good.py"), status, out.strip()) for path, status, out in results],
                         [(True, 0, "good ran"), (False, 1, "bad ran")])

    def test_the_jobserver_hands_a_freed_slot_over_only_once_no_test_waits(self):
        """GATE-SPEED F1 (D-118): three tests on two workers of one CPU each; the first end starts the third test, the
        second end frees a CPU nobody queued takes, so it becomes a token."""
        three, two = len((A, C, A)), self.PAIR
        poll = config.get("gate.jobserver_poll_s")
        with cache.parallel_tests.jobserver(three, two, 1, two, poll) as (env, ended):
            fd = os.open(env[cache.parallel_tests.JOBSERVER], os.O_RDWR | os.O_NONBLOCK)
            try:
                self.assertFalse(cache.parallel_tests._take(fd))
                ended("first")
                self.assertFalse(cache.parallel_tests._take(fd))
                ended("second")
                self.assertTrue(cache.parallel_tests._take(fd))
                self.assertFalse(cache.parallel_tests._take(fd))
            finally:
                os.close(fd)
            self.assertEqual(float(env[cache.parallel_tests.POLL]), poll)
        self.assertFalse(os.path.exists(env[cache.parallel_tests.JOBSERVER]))

    def test_a_box_no_wider_than_the_share_has_no_jobserver(self):
        with cache.parallel_tests.jobserver(1, self.BOX, self.BOX, self.BOX, config.get("gate.jobserver_poll_s")) as made:
            self.assertEqual(made, ({}, None))

    def test_a_test_at_its_share_runs_another_file_on_a_token_and_gives_it_back(self):
        """One worker and one token: both files run at once (each waits for the other at a barrier), the token returns."""
        two = self.PAIR
        meet = threading.Barrier(two, timeout=datetime.timedelta(milliseconds=config.get("tests.script_timeout_ms")).total_seconds())

        def run_one(path):
            meet.wait()
            return 0, f"{path} ran\n"
        with cache.parallel_tests.jobserver(two, 1, 1, two, config.get("gate.jobserver_poll_s")) as (env, _):
            with mock.patch.object(cache.parallel_tests, "run_one", side_effect=run_one):
                code, results = cache.parallel_tests.run(["a.py", "b.py"], workers=1, environ=env)
            fd = os.open(env[cache.parallel_tests.JOBSERVER], os.O_RDWR | os.O_NONBLOCK)
            try:
                self.assertTrue(cache.parallel_tests._take(fd))
            finally:
                os.close(fd)
        self.assertEqual(code, 0)
        self.assertEqual([(path, out.strip()) for path, _, out in results], [("a.py", "a.py ran"), ("b.py", "b.py ran")])

    def test_a_box_without_durations_runs_the_longest_committed_hint_first(self):
        """GATE-SPEED F2 (D-120): no recorded duration, so the committed cost hints order the run; a recorded duration
        wins over them."""
        started = []

        def commands(todo, workers, env, cwd, timings, ended=None):
            started.extend(script for script, _ in todo)
            timings.update({script: 0 for script, _ in todo})
            return [{"name": script, "result": cache.gate_graph.PASS, "output": ""} for script, _ in todo]

        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as store, \
                mock.patch.object(cache.gate_graph, "run_commands", side_effect=commands), \
                mock.patch.object(cache, "key", return_value=""):
            hints = pathlib.Path(root) / config.get("gate.test_costs_file")
            hints.parent.mkdir(parents=True)
            hints.write_text(json.dumps({A: 1, C: len((A, C))}))
            cache.run([A, C], root, pathlib.Path(store), "run-1", ROOT, concurrency=1, mapping={"tests": []})
            self.assertEqual(started, [C, A])
            started.clear()
            cache.run([A, C], root, pathlib.Path(store), "run-2", ROOT, concurrency=1, mapping={"tests": []},
                      durations={A: len((A, C)), C: 1})
            self.assertEqual(started, [A, C])
        self.assertEqual(cache.costs(ROOT / "absent"), {})

    def test_a_run_lists_the_tree_and_asks_node_once_and_keys_as_before(self):
        """GATE-SPEED F3: every key of a run shares one listing of the tree and one node version (each key ran git
        and node itself); the keys are the ones a key computed alone gives."""
        listing = cache.tracked(ROOT)
        with mock.patch.object(cache, "tracked", return_value=listing) as listed, \
                mock.patch.object(cache, "_node_version", return_value="v0") as node, \
                tempfile.TemporaryDirectory() as store, \
                mock.patch.object(cache.gate_graph, "run_commands",
                                  side_effect=lambda todo, workers, env, cwd, timings, ended=None: [
                                      timings.update({s: 0 for s, _ in todo}) or
                                      {"name": s, "result": cache.gate_graph.PASS, "output": ""} for s, _ in todo]):
            results = cache.run([A, C], ROOT, pathlib.Path(store), "run-1", ROOT, concurrency=1)
            self.assertEqual((listed.call_count, node.call_count), (1, 1))
            self.assertEqual([item["key"] for item in results],
                             [cache.key(script, ROOT, node="v0") for script in (A, C)])

    def test_without_the_variable_one_file_runs_at_a_time(self):
        self.assertEqual(cache.parallel_tests.cpus({}), 1)
        self.assertEqual(cache.parallel_tests.cpus({cache.parallel_tests.ENV: str(self.BOX)}), self.BOX)
        self.assertEqual(cache.parallel_tests.cpus({cache.parallel_tests.ENV: "zero"}), 1)


class RealMapTest(unittest.TestCase):
    def test_every_script_test_of_the_repository_has_a_key(self):
        mapping = cache.gate_script_tests.load()
        files = cache.tracked(ROOT)
        hashes = {}
        for entry in mapping["tests"]:
            with self.subTest(test=entry["script"]):
                self.assertTrue(cache.key(entry["script"], ROOT, mapping, files, node="v0", hashes=hashes))

    def test_changing_a_covered_file_of_the_real_map_changes_that_tests_key(self):
        mapping = cache.gate_script_tests.load()
        files = cache.tracked(ROOT)
        script = "scripts/tests/gate-select.test.sh"
        entry = next(item for item in mapping["tests"] if item["script"] == script)
        patterns = [script, *entry["covers"], *config.get("gate.test_cache_common_inputs"), "scripts/lib/forge_events.py"]
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            for name in files:
                if (ROOT / name).is_file() and any(cache.glob_match(name, pattern) for pattern in patterns):
                    (tmp / name).parent.mkdir(parents=True, exist_ok=True)
                    (tmp / name).write_bytes((ROOT / name).read_bytes())
            listed = sorted(str(p.relative_to(tmp)) for p in tmp.rglob("*") if p.is_file())
            before = cache.key(script, tmp, mapping, listed, node="v0")
            self.assertTrue(before)
            covered = tmp / "scripts/lib/gate_select.py"
            covered.write_text(covered.read_text() + "\n# changed\n")
            changed = cache.key(script, tmp, mapping, listed, node="v0")
            self.assertNotEqual(changed, before)
            other = tmp / "scripts/lib/forge_events.py"
            other.write_text(other.read_text() + "\n# not covered by gate-select\n")
            self.assertEqual(cache.key(script, tmp, mapping, listed, node="v0"), changed)


class SizingTest(Repo):
    """GX-03: the concurrency and the slot count follow the vCPUs; the longest measured test starts first."""

    def setting(self, **values):
        patched = mock.patch.object(cache, "setting", side_effect=lambda name: {
            "script_tests_concurrency": TWO, "script_tests_per_vcpu": 1, "slots": 0, "slots_per_vcpu": 1 / TWO / TWO,
            **values}[name])
        patched.start()
        self.addCleanup(patched.stop)

    def test_workers_are_the_cap_or_the_vcpus_whichever_is_lower(self):
        self.setting()
        self.assertEqual([cache.script_tests_workers(n) for n in (1, TWO, TWO + 1, TWO * TWO * TWO)], [1, TWO, TWO, TWO])

    def test_workers_follow_the_ratio_and_never_drop_below_one(self):
        self.setting(script_tests_per_vcpu=1 / TWO, script_tests_concurrency=TWO * TWO)
        self.assertEqual([cache.script_tests_workers(n) for n in (1, TWO, TWO + 1, TWO * TWO)], [1, 1, 1, TWO])

    def test_slots_follow_the_ratio_with_a_floor_of_one(self):
        self.setting()
        self.assertEqual([cache.gate_slots(n) for n in (1, TWO, TWO * TWO, TWO * TWO * TWO)], [1, 1, 1, TWO])

    def test_a_positive_slots_override_wins_over_the_vcpus(self):
        self.setting(slots=TWO + 1)
        self.assertEqual([cache.gate_slots(n) for n in (1, TWO * TWO, TWO * TWO * TWO * TWO)], [TWO + 1] * THREE)

    def test_the_registry_derives_by_default(self):
        registry = json.loads((ROOT / "config" / "registry" / "gate.json").read_text())["properties"]
        self.assertEqual(registry["gate.slots"]["default"], 0)

    def test_the_latest_measured_duration_of_each_test_wins(self):
        def event(script, ms, result="ok", kind="engine.step.measured"):
            return {"type": kind, "payload": {"step": cache.STEP_PREFIX + script, "duration_ms": ms, "result": result}}
        events = [event(A, 1), event(A, TWO), event(B, 1, "fail"), event(C, 1, kind="other"),
                  {"type": "engine.step.measured", "payload": {"step": "train:tier2", "duration_ms": 1, "result": "ok"}}]
        self.assertEqual(cache.last_durations(events), {A: TWO})

    def test_longest_first_then_the_unmeasured_in_declared_order(self):
        self.assertEqual(cache.longest_first([A, B, C], {C: TWO, A: 1}), [C, A, B])
        self.assertEqual(cache.longest_first([A, B, C], {}), [A, B, C])

    def test_the_run_starts_the_longest_measured_test_first(self):
        self.go([A, B, C])
        self.runlog.write_text("")
        cache.run([A, B, C], self.root, self.base / "other", "run-TWO", ROOT, concurrency=1, mapping=MAPPING,
                  durations={C: TWO, A: 1})
        self.assertEqual(self.ran(), ["c", "a", "b"])

    def test_the_run_without_durations_keeps_the_declared_order(self):
        self.go([A, B, C])
        self.assertEqual(sorted(self.ran()), ["a", "b", "c"])
        self.runlog.write_text("")
        cache.run([A, B, C], self.root, self.base / "other", "run-TWO", ROOT, concurrency=1, mapping=MAPPING)
        self.assertEqual(self.ran(), ["a", "b", "c"])

    def test_the_results_stay_in_test_order_whatever_ran_first(self):
        results = cache.run([A, B, C], self.root, self.store, "run-1", ROOT, concurrency=1, mapping=MAPPING,
                            durations={C: TWO})
        self.assertEqual([r["test"] for r in results], [A, B, C])


class ForkServerTest(unittest.TestCase):
    """GATE-SPEED F4 (D-122): a run with tests to start runs them under one fork server, unless gate.fork_server is off."""

    def enough(self):
        return [(A, "bash " + A)] * config.get("gate.fork_server_min_tests")

    def forks(self, enabled, todo, tool_root=None):
        with mock.patch.object(cache, "setting", side_effect=lambda name: enabled if name == "fork_server"
                               else config.get(f"gate.{name}")), \
                mock.patch.object(cache.fork_server, "started",
                                  return_value=contextlib.nullcontext({"OU_FORK_SERVER": "d"})) as started:
            with cache.forks({"PYTHONPATH": "h"}, todo, tool_root) as overlay:
                return overlay, started

    def test_the_run_starts_one_server_for_the_tests_it_runs(self):
        overlay, started = self.forks(True, self.enough())
        self.assertEqual(overlay, {"OU_FORK_SERVER": "d"})
        environ = started.call_args.args[0]
        self.assertEqual(environ["PYTHONPATH"], "h")  # the tests' own environment: the gate's plus the overlay
        self.assertEqual(started.call_args.args[1], config.get("gate.fork_server_preload"))

    def test_the_client_execs_the_tool_roots_toolchain(self):
        # base red 03/11: a runner started without env.sh handed the tests the host python3 behind the client
        _, started = self.forks(True, self.enough(), "/tool")
        self.assertEqual(started.call_args.kwargs["toolchain"], os.path.join("/tool", ".toolchain"))

    def test_no_server_below_the_minimum_of_tests(self):
        # VAZÃO F102: the server costs ~1 s to start; a run of fewer tests than the minimum starts fresh interpreters
        few = [(A, "bash " + A)] * (config.get("gate.fork_server_min_tests") - 1)
        overlay, started = self.forks(True, few)
        self.assertEqual(overlay, {})
        started.assert_not_called()

    def test_no_server_when_it_is_off_or_nothing_runs(self):
        for enabled, todo in ((False, self.enough()), (True, [])):
            overlay, started = self.forks(enabled, todo)
            self.assertEqual(overlay, {})
            started.assert_not_called()


class SuiteTest(unittest.TestCase):
    """GATE-SPEED (D-092): the whole suite is judged, every discovered test, and the wall is reported, never failed."""

    def judge(self, results, seconds):
        ticks = iter([0, seconds])
        lines = []
        with mock.patch.object(cache.gate_script_tests, "discover", return_value=tuple(r["test"] for r in results)), \
                mock.patch.object(cache, "run", return_value=results) as ran:
            cache.suite("checkout", "checkout", "store", "src", clock=lambda: next(ticks), out=lines.append)
        self.assertEqual(ran.call_args.args[0], [r["test"] for r in results])  # every test, not a selection
        return lines[-1]

    def result(self, name, cached, passed=True):
        return {"test": name, "result": "PASS" if passed else "FAIL", "cached": cached, "key": "k", "source": "s", "tail": []}

    def test_counts_and_the_three_wall_verdicts(self):
        goal, warn = config.get("gate.suite_wall_goal_s"), config.get("gate.suite_wall_warn_s")
        results = [self.result("a.test.sh", True), self.result("b.test.sh", False, passed=False)]
        line = self.judge(results, goal + warn)
        self.assertIn("2 script tests judged, 1 by key, 1 ran, 1 failed", line)
        self.assertIn("MISS", line)
        self.assertIn("WARN", self.judge(results, goal))
        self.assertTrue(self.judge(results, warn).endswith(": ok"))

    def test_one_pass_matcher_agrees_with_glob_match(self):
        patterns = ("scripts/lib/*.py", "docs/**", "a/**/b.json", "x?.sh")
        names = ["scripts/lib/a.py", "scripts/lib/sub/a.py", "docs/x/y.md", "a/b.json", "a/c/d/b.json", "xy.sh", "xyz.sh"]
        matches = cache._matcher(patterns)
        for name in names:
            self.assertEqual(bool(matches(name)), any(cache.glob_match(name, p) for p in patterns), name)


class ChangedTest(unittest.TestCase):
    """VAZÃO F50: `suite --changed` judges what the PR gate selects for the checkout's diff, through the gate's own
    functions (gate_policy.select_dev_plan, gate_script_tests.select_plan), and a docs-only diff runs nothing."""

    DOCS = "docs/units/f50-fixture/notes.md"  # a docs path no script test covers: the dev plan has no script tests stage

    def git(self, *args):
        env = dict(os.environ, **cache.hermetic_git(ROOT), HOME=str(self.repo))
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, env=env, capture_output=True,
                              text=True).stdout.strip()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name)
        self.git("init", "-q")
        (self.repo / "README.md").write_text("base\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")

    def commit(self, name, text="x\n"):
        (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
        (self.repo / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", name)

    def test_the_diff_is_the_gates_plus_what_is_not_committed(self):
        self.commit("scripts/lib/committed.py")
        (self.repo / "README.md").write_text("edited\n")
        (self.repo / "untracked.md").write_text("new\n")
        self.assertEqual(cache.changed(self.repo, self.base), ["README.md", "scripts/lib/committed.py", "untracked.md"])

    def test_the_selection_is_the_gates_through_the_same_functions(self):
        import gate_policy
        paths = ["scripts/lib/gate_test_cache.py", "scripts/lib/gate_policy.py"]
        plan = gate_policy.select_dev_plan(paths, "base", "HEAD", ROOT)
        expected = list(cache.gate_script_tests.select_plan(plan)[0])
        with mock.patch.object(gate_policy, "select_dev_plan", wraps=gate_policy.select_dev_plan) as planned, \
                mock.patch.object(cache.gate_script_tests, "select_plan",
                                  wraps=cache.gate_script_tests.select_plan) as selected:
            chosen, _reason = cache.selection(paths, "base", ROOT)
        planned.assert_called_once_with(paths, "base", "HEAD", ROOT)
        selected.assert_called_once()
        self.assertEqual(chosen, expected)
        self.assertIn("scripts/tests/gate-test-cache.test.sh", chosen)
        self.assertLess(len(chosen), len(cache.gate_script_tests.discover(ROOT)))  # a selection, not the suite

    def run_changed(self):
        out = io.StringIO()
        argv = ["gate_test_cache", "suite", "--changed", "--root", str(self.repo), "--base", self.base,
                "--lock", str(self.repo / "box.lock")]
        with mock.patch.object(cache, "run") as ran, mock.patch.object(cache, "hold") as box, \
                mock.patch.object(cache, "slot") as held, mock.patch.object(cache, "niced") as niced, \
                contextlib.redirect_stdout(out):
            code = cache.main(argv)
        self.niced = niced
        box.assert_not_called()  # F65: a --changed suite never takes the box lock, which stays the deliveries'
        return code, ran, held, out.getvalue()

    def test_a_docs_only_diff_runs_nothing_and_takes_no_lock(self):
        self.commit(self.DOCS)
        code, ran, held, out = self.run_changed()
        self.assertEqual(code, 0)
        ran.assert_not_called()
        held.assert_not_called()
        self.assertIn("1 path(s)", out)
        self.assertIn("0 script test(s) selected", out)

    def test_a_scripts_diff_runs_the_selection_under_the_lock(self):
        self.commit("scripts/lib/gate_test_cache.py")
        # the fixture repository has none of the selected tests; the checkout `--changed` judges always has them
        with mock.patch.object(cache, "deleted", return_value=[]):
            code, ran, held, out = self.run_changed()
            expected, _reason = cache.selection(["scripts/lib/gate_test_cache.py"], self.base, self.repo)
        self.assertEqual(code, 0)
        held.assert_called_once()  # one slot of gate.changed_suite_slots, under nice
        self.niced.assert_called_once_with()
        self.assertTrue(expected)
        self.assertEqual(ran.call_args.args[0], expected)


class BoxLogTest(unittest.TestCase):
    """F58: a suite's hold of the box lock is a line of the box's lock log, as a delivery's is (F38)."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.lock, self.log = self.dir / "box" / "gate.lock", self.dir / "logs" / "gate-lock.jsonl"

    def rows(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_a_free_box_logs_a_suite_line_with_its_hold_and_no_wait(self):
        ticks = iter([float(TWO), float(TWO + THREE)])
        with cache.hold(str(self.lock), str(self.log), clock=lambda: next(ticks), wall=lambda: float(THREE)):
            pass
        self.assertEqual(self.rows(), [{"pr": None, "kind": "suite", "waited_s": 0.0, "held_s": float(THREE),
                                        "at": THREE}])

    def test_a_busy_box_logs_the_wait(self):
        held, err = threading.Event(), io.StringIO()
        self.lock.parent.mkdir(parents=True)

        def other():
            with open(self.lock, "a") as handle:
                cache.fcntl.flock(handle, cache.fcntl.LOCK_EX)
                held.set()
                released.wait()

        released = threading.Event()
        holder = threading.Thread(target=other)
        holder.start()
        held.wait()
        threading.Timer(0.2, released.set).start()
        with cache.hold(str(self.lock), str(self.log), err=err):
            pass
        holder.join()
        row, = self.rows()
        self.assertIn("a gate or a suite holds the box", err.getvalue())
        self.assertGreater(row["waited_s"], 0.0)
        self.assertEqual((row["pr"], row["kind"]), (None, "suite"))

    def test_no_log_writes_nothing_and_an_unwritable_log_never_fails_the_suite(self):
        with cache.hold(str(self.lock)):
            pass
        self.assertFalse(self.log.exists())
        self.log.parent.mkdir(parents=True)
        self.log.mkdir()  # a directory where the log should be: the write fails, the suite does not
        with cache.hold(str(self.lock), str(self.log)):
            pass

    def test_the_whole_suite_runs_under_the_box_lock_and_logs_to_the_registry_log(self):
        argv = ["gate_test_cache", "suite", "--root", str(self.dir), "--lock", str(self.lock)]
        with mock.patch.object(cache, "suite", return_value=[]) as ran, \
                mock.patch.object(cache.config, "get", return_value=str(self.log)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cache.main(argv), 0)
        ran.assert_called_once()
        self.assertEqual([row["kind"] for row in self.rows()], ["suite"])


class SlotTest(unittest.TestCase):
    """F65: a --changed suite takes one of N slot locks beside the box lock, never the box lock, and logs its own kind."""

    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        self.lock, self.log = self.dir / "box" / "gate.lock", self.dir / "gate-lock.jsonl"

    def rows(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_a_slot_leaves_the_box_lock_free_and_logs_a_suite_slot_line(self):
        with cache.slot(str(self.lock), str(self.log), slots=TWO):
            self.lock.parent.mkdir(parents=True, exist_ok=True)
            with open(self.lock, "a") as box:
                cache.fcntl.flock(box, cache.fcntl.LOCK_EX | cache.fcntl.LOCK_NB)  # a delivery is not kept waiting
        row, = self.rows()
        self.assertEqual((row["pr"], row["kind"], row["waited_s"]), (None, cache.SLOT_KIND, 0.0))

    def test_n_suites_run_at_once_and_the_next_one_waits_for_a_slot(self):
        err = io.StringIO()
        with cache.slot(str(self.lock), slots=TWO), cache.slot(str(self.lock), slots=TWO):  # both slots taken
            done = threading.Event()

            def third():
                with cache.slot(str(self.lock), str(self.log), slots=TWO, err=err):
                    done.set()

            waiting = threading.Thread(target=third)
            waiting.start()
            self.assertFalse(done.wait(0.2), "a third suite waits while N=2 hold the slots")
        waiting.join()
        self.assertTrue(done.is_set())
        self.assertIn("hold every slot", err.getvalue())
        self.assertGreater(self.rows()[0]["waited_s"], 0.0)

    def test_the_slot_count_is_the_registry_key_and_niced_lowers_the_priority(self):
        self.assertEqual(config.get("gate.changed_suite_slots"), TWO)
        with mock.patch.object(cache.os, "nice") as nice:
            cache.niced()
        nice.assert_called_once_with(config.get("gate.changed_suite_nice"))
        with mock.patch.object(cache.os, "nice", side_effect=OSError):
            cache.niced()  # a box that refuses the change still runs the suite

    def test_the_whole_suite_still_holds_the_box_lock(self):
        argv = ["gate_test_cache", "suite", "--root", str(self.dir), "--lock", str(self.lock)]
        with mock.patch.object(cache, "suite", return_value=[]), mock.patch.object(cache, "slot") as slots, \
                mock.patch.object(cache.config, "get", return_value=str(self.log)), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cache.main(argv), 0)
        slots.assert_not_called()
        self.assertEqual([row["kind"] for row in self.rows()], ["suite"])


if __name__ == "__main__":
    unittest.main()
