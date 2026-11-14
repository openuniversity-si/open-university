"""TX10 (T6, hermetic; T4, attribution): a script test shares no machine state with its siblings or with the gate that
runs it, and the stage runner says what really happened to a stage.

The cache cases drive the real runner (gate_test_cache.run through gate_graph) over throwaway tests in a temp repo: a
private TMPDIR per test, removed after the run, and no gate variable or gate state file in the test's environment except
the slot contract a nested gate shares. The runner cases source the real scripts/lib/gate-runner.sh with a stage limit
of one second: a failure log stays in the run's own logs, a stage record that cannot be written fails the stage, and a
stage is labelled timed out only when its limit killed it (B8). The entry cases run a copy of the real scripts/run: a test
runs as the gate runs it, with bash (no exec bit), the local configuration pin and the hermetic harness. Hermetic: temp
repos and temp stores, no network."""
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import config  # noqa: E402
import gate_test_cache as cache  # noqa: E402

TWO = 1 + 1  # two tests at once, built from 1 so no new literal enters the census
A, B = "scripts/tests/a.test.sh", "scripts/tests/b.test.sh"
MAPPING = {"tests": ({"script": A, "covers": ()}, {"script": B, "covers": ()})}
# A gate run's own variables, as gate-local and hermetic.shell_env export them, and the slot contract it keeps.
GATE_STATE = ("OU_GATE_TIER", "OU_GATE_PROOF", "OU_GATE_BASE_SHA", "OU_GATE_OFFLINE", "GATE_PLAN_FILE",
              "GATE_SELECTION_FILE", "OU_SUBJECT_ROOT")
SLOT = tuple(config.get("gate.test_env_keep"))


class Run(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self._tmp.name)
        self.root = self.base / "repo"
        self.out = self.base / "out"
        self.out.mkdir()
        (self.root / "scripts" / "tests").mkdir(parents=True)
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        env = mock.patch.dict(os.environ, {"OUT": str(self.out)})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, rel, text):
        (self.root / rel).write_text(text)

    def go(self, scripts):
        results = cache.run(scripts, self.root, self.base / "store", "run-1", ROOT, concurrency=TWO, mapping=MAPPING)
        self.assertEqual([r["result"] for r in results], ["PASS"] * len(scripts), results)
        return results


class PrivateTmpdir(Run):
    def test_two_tests_writing_the_same_relative_temp_name_in_parallel_do_not_see_each_other(self):
        # Each writes probe in its effective temp dir (mktemp's), waits until the other has written its own, then reads it back: a shared TMPDIR
        # would give one of them the other's word.
        for name, other in (("a", "b"), ("b", "a")):
            self.write(f"scripts/tests/{name}.test.sh",
                       f'tmp=$(dirname "$(mktemp -u)")\necho {name} >"$tmp/probe"\n: >"$OUT/{name}.wrote"\n'
                       f'until [ -e "$OUT/{other}.wrote" ]; do :; done\n'
                       f'cat "$tmp/probe" >"$OUT/{name}.read"\nls -A "$tmp" >"$OUT/{name}.ls"\n'
                       f'printf %s "$tmp" >"$OUT/{name}.dir"\nstat -c %a "$tmp" >"$OUT/{name}.mode"\n')
        self.go([A, B])
        read = {name: (self.out / f"{name}.read").read_text().strip() for name in "ab"}
        self.assertEqual(read, {"a": "a", "b": "b"})
        self.assertEqual({(self.out / f"{name}.ls").read_text().split()[0] for name in "ab"}, {"probe"})
        dirs = {(self.out / f"{name}.dir").read_text() for name in "ab"}
        self.assertEqual(len(dirs), TWO)
        for path in dirs:
            self.assertEqual(pathlib.Path(path).parent, pathlib.Path(config.get("gate.test_tmp_root")))
            self.assertFalse(pathlib.Path(path).exists(), f"{path} outlived its run")
        want = format(int(config.get("gate.test_tmp_mode"), 0), "o")
        self.assertEqual({(self.out / f"{name}.mode").read_text().strip() for name in "ab"}, {want})

    def test_a_failed_test_also_loses_its_tmpdir(self):
        self.write("scripts/tests/a.test.sh", 'printf %s "$TMPDIR" >"$OUT/a.dir"\nfalse\n')
        results = cache.run([A], self.root, self.base / "store", "run-1", ROOT, concurrency=TWO, mapping=MAPPING)
        self.assertEqual(results[0]["result"], "FAIL")
        self.assertFalse(pathlib.Path((self.out / "a.dir").read_text()).exists())


class ScrubbedEnvironment(Run):
    def test_no_gate_variable_or_state_file_reaches_a_test(self):
        gate = {name: "from-the-gate" for name in (*GATE_STATE, *SLOT)}
        self.write("scripts/tests/a.test.sh", 'env >"$OUT/a.env"\n')
        with mock.patch.dict(os.environ, gate):
            self.go([A])
        seen = dict(line.split("=", 1) for line in (self.out / "a.env").read_text().splitlines() if "=" in line)
        leaked = sorted(name for name in seen if name.startswith(tuple(config.get("gate.test_env_scrub_prefixes"))))
        self.assertEqual(leaked, sorted(SLOT))  # the slot contract only
        for name in GATE_STATE:
            self.assertNotIn(name, seen)
        self.assertEqual({name: seen.get(name) for name in SLOT}, {name: "from-the-gate" for name in SLOT})
        self.assertEqual(seen["OUT"], str(self.out))  # everything else passes through

    def test_the_scrub_list_is_the_gate_state_and_never_the_slot(self):
        environ = {"OU_GATE_TIER": "", "GATE_PLAN_FILE": "p", "OU_SUBJECT_ROOT": "r", "PATH": "p", "OU_PYTHON": "p",
                   **{name: "s" for name in SLOT}}
        self.assertEqual(cache.scrubbed(environ), sorted(["OU_GATE_TIER", "GATE_PLAN_FILE", "OU_SUBJECT_ROOT"]))

    def test_the_command_removes_names_and_sets_tmpdir(self):
        command = cache.isolated("bash scripts/tests/a.test.sh", "some dir", ["GATE_X", "OU_GATE_TIER"])
        self.assertEqual(command, "env -u GATE_X -u OU_GATE_TIER 'TMPDIR=some dir' bash scripts/tests/a.test.sh")


# gate_gc.py limits, for a one-second stage limit with no TERM-to-KILL grace; every other call is the real Python.
LIMIT_S = 1
STUB = (f'if [[ "${{2:-}}" == limits ]]; then printf "{LIMIT_S}\\t0\\t%s\\t1\\n" "$TIMEOUT_RC"; exit 0; fi\n'
        'exec python3 "$@"\n')
# B8 probe: after the runner signals anything but the watcher itself (step's local, visible here), hold it while the
# watcher runs on, until it has marked the stage or ended, so the race the old kill order lost now and then is lost
# every time. A stopped watcher (the frozen tree) runs nothing, so it is not waited for.
HOLD = ('kill() {\n  builtin kill "$@"; local rc=$?\n'
        '  if [[ -n "${watcher:-}" && "${*: -1}" != "$watcher" && "$1" != -STOP && "$1" != -CONT ]]; then\n'
        '    while [[ "$(ps -o stat= -p "$watcher" 2>/dev/null)" == [^ZT]* && ! -f "$log.timedout" ]]; do :; done\n'
        '  fi\n  return "$rc"\n}\n')
# gate-gc probe: after a TERM to a `sleep`, hold the runner while that sleep's shell runs on, until it has printed its
# next line or ended. A stopped shell runs nothing, so it is not waited for.
FORCE = ('kill() {\n  local target="${*: -1}" parent="" rc\n'
         '  if [[ "$1" == -TERM && "$(ps -o comm= -p "$target" 2>/dev/null)" == sleep ]]; then\n'
         '    parent=$(ps -o ppid= -p "$target" | tr -d " ")\n  fi\n  builtin kill "$@"; rc=$?\n'
         '  if [[ -n "$parent" ]]; then\n'
         '    while [[ "$(ps -o stat= -p "$parent" 2>/dev/null)" == [^ZT]* ]] && ! grep -q never "$log"; do :; done\n'
         '  fi\n  return "$rc"\n}\n')


class Runner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self._tmp.name)
        self.logs = self.base / "logs"
        self.logs.mkdir()
        stub = self.base / "python"
        stub.write_text(STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.rc_timeout = config.get("gate-gc.timeout_exit_code")
        self.env = {**os.environ, "OU_PYTHON": str(stub), "TIMEOUT_RC": str(self.rc_timeout),
                    "logs": str(self.logs), "RUNNER": str(ROOT / "scripts" / "lib" / "gate-runner.sh")}

    def tearDown(self):
        self._tmp.cleanup()

    def step(self, command, prelude=""):
        script = f'source "$RUNNER"\n{prelude}step probe "$logs" {command}\n'
        done = subprocess.run(["bash", "-c", script], env=self.env, capture_output=True, text=True)
        return done.returncode, done.stdout + done.stderr

    def result(self):
        return (self.logs / "probe.log.result").read_text()

    def test_a_stage_killed_by_its_own_limit_is_labelled_timed_out(self):
        rc, _ = self.step("sleep infinity")
        self.assertEqual(rc, self.rc_timeout)
        self.assertIn(f'ran past gate-gc.stage_timeout_s ({LIMIT_S}s) and was killed', self.result())
        self.assertEqual(json.loads((self.logs / "probe.stage.json").read_text())["exit"], self.rc_timeout)

    def test_a_stage_that_fails_before_its_limit_is_never_labelled_timed_out(self):
        rc, _ = self.step("false", prelude=HOLD)
        self.assertEqual(rc, 1)
        self.assertNotIn("ran past", self.result())
        self.assertFalse((self.logs / "probe.log.timedout").exists())

    def test_a_stage_that_passes_before_its_limit_is_never_labelled_timed_out(self):
        rc, _ = self.step("true", prelude=HOLD)
        self.assertEqual(rc, 0)
        self.assertTrue(self.result().startswith("PASS probe"))
        self.assertFalse((self.logs / "probe.log.timedout").exists())

    def test_a_timed_out_stage_runs_nothing_more_after_its_sleep_is_killed(self):
        # gate-gc's "never" (train, 07:50Z): a shell whose sleep died before it did ran its next command.
        rc, _ = self.step("bash -c 'echo before-the-hang; sleep infinity; echo never'", prelude=FORCE)
        self.assertEqual(rc, self.rc_timeout)
        log = (self.logs / "probe.log").read_text()
        self.assertIn("before-the-hang", log)
        self.assertNotIn("never", log)

    def test_the_failure_log_stays_in_the_runs_own_logs(self):
        rc, out = self.step("bash -c 'echo deliberate probe; false'")
        self.assertEqual(rc, 1)
        [named] = [line.rsplit("; log: ", 1)[1].rstrip(")") for line in out.splitlines() if line.startswith("FAIL probe")]
        self.assertEqual(pathlib.Path(named).parent, self.logs)
        self.assertIn("deliberate probe", pathlib.Path(named).read_text())

    def test_a_stage_record_that_cannot_be_written_fails_the_stage_and_names_its_path(self):
        record = self.logs / "probe.stage.json"
        record.mkdir()  # a directory where the record goes: the write fails, as root too
        rc, out = self.step("true")
        self.assertNotEqual(rc, 0)
        self.assertIn(f"stage record not written: {record}", out)


class Entry(unittest.TestCase):
    """scripts/run test <name>, from a copy of the real script in a temp root (its env.sh is an empty stand-in)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        for rel in ("scripts/cloud", "scripts/tests", "scripts/lib/hermetic"):
            (self.root / rel).mkdir(parents=True)
        (self.root / "scripts" / "run").write_bytes((ROOT / "scripts" / "run").read_bytes())
        (self.root / "scripts" / "cloud" / "env.sh").write_text("")
        probe = self.root / "scripts" / "tests" / "probe.test.sh"
        probe.write_text('printf "%s|%s|%s\\n" "$OU_CONFIG_STORE" "${PYTHONPATH%%:*}" "$*"\n')
        probe.chmod(stat.S_IRUSR | stat.S_IWUSR)  # no exec bit, like 24 of the repository's *.test.sh

    def tearDown(self):
        self._tmp.cleanup()

    def run_test(self, *args, env=None):
        return subprocess.run(["bash", str(self.root / "scripts" / "run"), "test", *args], capture_output=True, text=True,
                              env={**os.environ, **(env or {})})

    def test_a_test_without_the_exec_bit_runs_with_the_gates_pin_and_harness(self):
        done = self.run_test("probe", "one", "two", env={"OU_CONFIG_STORE": "", "PYTHONPATH": "elsewhere"})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), f"file|{self.root / 'scripts' / 'lib' / 'hermetic'}|one two")

    def test_print_and_an_unknown_test_are_unchanged(self):
        printed = subprocess.run(["bash", str(self.root / "scripts" / "run"), "--print", "test", "probe"],
                                 capture_output=True, text=True)
        self.assertEqual(printed.stdout.strip(), "scripts/tests/probe.test.sh")
        self.assertNotEqual(self.run_test("nonesuch").returncode, 0)


if __name__ == "__main__":
    unittest.main()
