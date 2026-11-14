"""Gate hygiene (GX-19): per-stage timeouts, report and build-cache retention. Hermetic: temp dirs.
Every number comes from the registry or from the fixture's own shape (D-068: the census counts tests too)."""
import fcntl
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import string
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import config  # noqa: E402
import gate_gc as gc  # noqa: E402

SHA = hashlib.sha1(b"").hexdigest()
OTHER_SHA = hashlib.sha1(b"other").hexdigest()


def key(index):
    return hashlib.sha256(bytes([index])).hexdigest()


def touch_dir(path, age):
    path.mkdir(parents=True)
    stamp = path.stat().st_mtime - age
    os.utime(path, (stamp, stamp))


class Timeout(unittest.TestCase):
    def test_a_listed_stage_has_its_own_limit_and_others_the_star_entry(self):
        limits = [{"stage": "lint", "timeout_s": 1}, {"stage": "*", "timeout_s": 0}]
        self.assertEqual(gc.stage_timeout("lint", limits), 1)
        self.assertEqual(gc.stage_timeout("anything else", limits), 0)

    def test_the_registry_default_orders_the_stages_the_plan_names(self):
        limit = gc.stage_timeout
        self.assertGreater(limit("script tests"), limit("shellcheck"))
        self.assertEqual(limit("shellcheck"), limit("no such stage"))

    def test_every_named_limit_is_a_stage_the_gate_runs(self):
        """F46: a limit for a stage that left the gate (Open University's lint, builds, e2e) is dead configuration."""
        import gate_policy
        named = {item["stage"] for item in config.get("gate-gc.stage_timeout_s")} - {"*"}
        self.assertEqual(named - set(gate_policy.FULL_STAGES), set())

    def run_step(self, command):
        """Run `step` of gate-runner.sh on a stage limited to one second; returns (rc, seconds, output)."""
        with tempfile.TemporaryDirectory() as tmp:
            logs = pathlib.Path(tmp) / "logs"
            logs.mkdir()
            lib = pathlib.Path(tmp) / "lib"
            lib.mkdir()
            for name in ("gate_classify.py", "gate_status.py", "config.py", "json_schema.py"):
                (lib / name).symlink_to(ROOT / "scripts" / "lib" / name)
            # The fixture's own shape (D-068): a 1 s grace, so the hang test does not wait out the registry's 5 s.
            # The registry value is read by gate-runner.sh in the real gate, not here.
            fields = [1, 1, config.get("gate-gc.timeout_exit_code"), config.get("gate-gc.log_tail_lines")]
            (lib / "gate_gc.py").write_text("print(%r)\n" % "\t".join(str(field) for field in fields))
            script = f'logs="$1"; source "{ROOT}/scripts/lib/gate-runner.sh"; gate_lib_dir="$2"; step fixture "$3" bash -c "$4"'
            done = subprocess.run(["bash", "-c", script, "x", str(logs), str(lib), tmp, command],
                                  capture_output=True, text=True, env={**os.environ, "OU_CONFIG_STORE": "file"})
            seconds = json.loads((logs / "fixture.stage.json").read_text())["seconds"]  # measured by step itself
            return done.returncode, seconds, done.stdout + done.stderr

    def test_a_stage_that_sleeps_past_its_limit_ends_red_with_class_env_and_its_log_tail(self):
        rc, seconds, out = self.run_step("echo before-the-hang; sleep infinity; echo never")
        self.assertEqual(rc, config.get("gate-gc.timeout_exit_code"))
        self.assertLess(seconds, 1 + 1 + 1)  # limit + fixture grace + slack
        self.assertIn("FAIL fixture", out)
        self.assertIn("before-the-hang", out)
        self.assertIn("gate-gc.stage_timeout_s (" + str(1) + "s)", out)
        self.assertRegex(out, r"\tenv\b")
        self.assertNotIn("never", out)

    def test_a_stage_inside_its_limit_keeps_its_own_exit_code(self):
        rc, _, out = self.run_step("echo ok")
        self.assertEqual(rc, 0)
        self.assertIn("PASS fixture", out)
        rc, _, _ = self.run_step("exit 1")
        self.assertEqual(rc, 1)


class Retention(unittest.TestCase):
    def test_reports_keep_the_newest_per_sha_and_mode(self):
        keep = config.get("gate-gc.reports_keep")
        with tempfile.TemporaryDirectory() as tmp:
            reports = pathlib.Path(tmp)
            runs = [f"dev-20261027T10000{index}" for index in range(keep + keep)]
            for index, name in enumerate(runs):  # the later the name, the newer the directory
                touch_dir(reports / SHA / name, len(runs) - index)
            touch_dir(reports / SHA / "noite-20261027T100000", len(runs) + 1)
            touch_dir(reports / OTHER_SHA / "dev-20261027T100000", len(runs) + 1)
            touch_dir(reports / "working-tree" / "dev-20261027T100000", len(runs) + 1)
            removed = gc.collect_reports(reports, keep)
            kept = sorted(p.name for p in (reports / SHA).iterdir() if p.name.startswith("dev-"))
            self.assertEqual(kept, runs[-keep:])
            self.assertEqual(len(removed), len(runs) - keep)
            self.assertTrue((reports / SHA / "noite-20261027T100000").is_dir())
            self.assertTrue((reports / OTHER_SHA / "dev-20261027T100000").is_dir())
            self.assertTrue((reports / "working-tree" / "dev-20261027T100000").is_dir())

    def test_the_folder_keeps_the_newest_shas_however_many_pushes_added(self):
        keep = len(string.digits)  # the audit's case: a bound of ten over a hundred pushes, one run each
        with tempfile.TemporaryDirectory() as tmp:
            reports = pathlib.Path(tmp)
            shas = [hashlib.sha1(bytes([index])).hexdigest() for index in range(keep * keep)]
            for index, sha in enumerate(shas):  # index 0 is the newest push
                touch_dir(reports / sha / "dev-20261027T100000", index + 1)
            touch_dir(reports / "working-tree" / "dev-20261027T100000", len(shas) + 1)
            removed = gc.collect_shas(reports, keep)
            kept = sorted(p.name for p in reports.iterdir() if gc.SHA.match(p.name))
            self.assertEqual(kept, sorted(shas[:keep]))
            self.assertEqual(len(removed), len(shas) - keep)
            self.assertTrue((reports / "working-tree").is_dir())

    def test_the_two_bounds_compose_per_key_inside_the_folder(self):
        keep = config.get("gate-gc.reports_keep")
        shas_keep = config.get("gate-gc.reports_shas_keep")
        with tempfile.TemporaryDirectory() as tmp:
            reports = pathlib.Path(tmp) / "reports"
            shas = [hashlib.sha1(bytes([index])).hexdigest() for index in range(shas_keep + 1)]
            runs = [f"dev-20261027T10000{index}" for index in range(keep + 1)]
            for age, sha in enumerate(shas, start=1):  # shas[0] is the newest sha; inside it, the later name is newer
                for index, name in enumerate(runs):
                    touch_dir(reports / sha / name, age * len(runs) - index)
            removed = gc.collect(reports, None)
            self.assertEqual(sorted(p.name for p in reports.iterdir()), sorted(shas[:-1]))
            for sha in shas[:-1]:
                self.assertEqual(sorted(p.name for p in (reports / sha).iterdir()), runs[-keep:])
            self.assertIn(reports / shas[-1], removed)

    def test_the_advisory_folder_has_its_own_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = pathlib.Path(tmp)
            total = config.get("gate-gc.reports_shas_keep") + config.get("gate-gc.report_only_shas_keep")
            for index in range(total):
                touch_dir(reports / hashlib.sha1(bytes([index])).hexdigest() / "dev-20261027T100000", index + 1)
            gc.collect(reports, None, report_only=True)
            self.assertEqual(sum(1 for _ in reports.iterdir()), config.get("gate-gc.report_only_shas_keep"))

    def pushes(self, reports, count):
        """`count` shas of one run each, the first the newest; returns their names."""
        shas = [hashlib.sha1(bytes([index])).hexdigest() for index in range(count)]
        for index, sha in enumerate(shas):
            touch_dir(reports / sha / "dev-20261027T100000", index + 1)
        return shas

    def test_a_sha_a_held_lock_names_is_never_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = pathlib.Path(tmp) / "reports"
            shas = self.pushes(reports, 1 + 1 + 1)
            lock = pathlib.Path(tmp) / "gate.lock"
            lock.write_text(shas[-1] + "\n")
            with open(lock) as holder:  # a live gate holds the lock that names the oldest sha
                fcntl.flock(holder, fcntl.LOCK_EX)
                removed = gc.collect_shas(reports, 1, lock=lock)
            self.assertTrue((reports / shas[-1]).is_dir())
            self.assertEqual(removed, [])  # and nothing newer than the sha it writes

    def test_a_lock_nobody_holds_protects_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = pathlib.Path(tmp) / "reports"
            shas = self.pushes(reports, 1 + 1)
            lock = pathlib.Path(tmp) / "gate.lock"
            lock.write_text(shas[-1])
            self.assertEqual(gc.collect_shas(reports, 1, lock=lock), [reports / shas[-1]])
            self.assertEqual(gc.held_lock_shas(None), set())

    def test_nothing_as_recent_as_a_sha_a_gate_writes_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = pathlib.Path(tmp)
            shas = self.pushes(reports, 1 + 1 + 1 + 1)
            removed = gc.collect_shas(reports, 1, writing=[shas[-1 - 1]])
            self.assertEqual(removed, [reports / shas[-1]])

    @unittest.skipUnless(pathlib.Path(config.get("gate-gc.proc_dir")).is_dir(), "no process table here: open handles are not readable")
    def test_a_sha_a_live_process_holds_open_is_never_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            reports = pathlib.Path(tmp)
            shas = self.pushes(reports, 1 + 1)
            handle = os.open(reports / shas[-1] / "dev-20261027T100000", os.O_RDONLY)  # a reader; it writes nothing
            try:
                self.assertEqual(gc.held_open_shas(reports), {shas[-1]})
                self.assertEqual(gc.collect_shas(reports, 1), [])
            finally:
                os.close(handle)
            self.assertEqual(gc.collect_shas(reports, 1), [reports / shas[-1]])

    def test_the_folder_bound_keeps_what_the_readers_need(self):
        self.assertGreaterEqual(config.get("gate-gc.reports_shas_keep"), config.get("gate.status_history_runs"))

    def test_build_entries_keep_the_most_recently_used_per_target(self):
        keep = config.get("gate-gc.build_cache_keep")
        with tempfile.TemporaryDirectory() as tmp:
            cache = pathlib.Path(tmp)
            total = keep + keep
            for index in range(total):  # index 0 is the most recently used
                touch_dir(cache / f"test-{key(index)}", index + 1)
                touch_dir(cache / f"production-{key(index)}", index + 1)
            touch_dir(cache / "lint", total)
            touch_dir(cache / "tmpabc123", total)
            touch_dir(cache / ".replaced-dead", 1)
            gc.collect_build_cache(cache, keep)
            names = sorted(p.name for p in cache.iterdir())
            for target in ("test", "production"):
                self.assertEqual(sorted(n for n in names if n.startswith(target + "-")),
                                 sorted(f"{target}-{key(index)}" for index in range(keep)))
            self.assertIn("lint", names)
            self.assertIn("tmpabc123", names)
            self.assertNotIn(".replaced-dead", names)

    def test_collect_reads_the_keep_bounds_from_the_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            keep = config.get("gate-gc.reports_keep")
            for index in range(keep + 1):
                touch_dir(root / "reports" / SHA / f"dev-20261027T10000{index}", keep + 1 - index)
            self.assertEqual(len(gc.collect(root / "reports", None)), 1)

    def test_missing_directories_are_not_an_error(self):
        self.assertEqual(gc.collect(None, None), [])
        self.assertEqual(gc.collect_reports(pathlib.Path("/nonexistent-gx19"), 1), [])


if __name__ == "__main__":
    unittest.main()
