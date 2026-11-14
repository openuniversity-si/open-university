"""GATE-API (D-070): scripts/gate-verdict, the gate as an API that runs the tests and returns the result.

Hermetic: the input, the binding, the metadata check and the gate run are faked through gate_verdict.Seams; the record
store and the reports are temporary directories. Every number comes from the registry or the os module (LT1)."""
import contextlib
import hashlib
import io
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
os.environ["OU_CONFIG_STORE"] = "file"

import config  # noqa: E402
import gate_pin  # noqa: E402
import hermetic  # noqa: E402
import gate_tier  # noqa: E402
import gate_verdict  # noqa: E402
from gate_verdict import FAILED, PASSED, UNOBSERVABLE  # noqa: E402

PR = "800"
# A gate that runs this test exports its own hand-off; the fixture is a fresh caller.
HANDOFF = ("GATE_RECORD_DIR", "GATE_REPORT_DIR", gate_tier.ENV)


def sha(name):
    return hashlib.sha1(name.encode()).hexdigest()


def digest_of(head, base):
    return hashlib.sha256(f"{head} {base}".encode()).hexdigest()


def slug(name):
    return re.sub(r"[^a-zA-Z0-9]", "_", name)


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = pathlib.Path(temp.name)
        scrub = mock.patch.dict(os.environ)
        scrub.start()
        self.addCleanup(scrub.stop)
        for name in HANDOFF:
            os.environ.pop(name, None)
        self.head, self.base, self.moved = sha("head"), sha("base"), sha("moved")
        self.now = int(hermetic.clock().timestamp())
        self.runs, self.slept, self.bound = [], [], []
        self.pr_head = self.head
        self.unreadable = 0  # PR reads that fail before one succeeds; -1: every read fails
        self.meta = (0, "structure-check (metadata, PR #800): 0 error(s), 0 warning(s)")
        self.run_as = {"code": 0, "result": "PASS", "stages": [("lint", "PASS", "")]}
        self.seams = gate_verdict.Seams(
            fetch=lambda root, value: value, identity=self.identity, tip=lambda root, ref: self.base,
            batch_tip=lambda root: self.base, tool=lambda root, base: (root, None), bind=self.bind,
            metadata=lambda root, tool, head, base, pr: self.meta, gate=self.gate, now=lambda: self.now,
            sleep=self.slept.append)

    # --- the seams ----------------------------------------------------------------------------------------------------
    def identity(self, root, pr):
        if self.unreadable:
            self.unreadable -= 1
            raise gate_pin.PinError(f"cannot read PR #{pr} head/base (exit 1)")
        return self.pr_head, self.base, "main"

    def bind(self, root, tool, head, base):
        self.bound.append(base)
        return {"sha": head, "base_sha": base, "input_digest": digest_of(head, base), "toolchain_id": "toolchain",
                "gate_version": "version"}

    def gate(self, root, head, pr, logs):
        """A finished gate-local run as self.run_as describes it: report, .pass record of a pass, pin line."""
        self.runs.append((head, pr))
        run, logs = self.run_as, pathlib.Path(logs)
        logs.mkdir(parents=True, exist_ok=True)
        for name, result, log in run.get("stages", []):
            (logs / f"{slug(name)}.log").write_text(log)
            (logs / f"{slug(name)}.stage.json").write_text(json.dumps({"name": name, "result": result}))
        if run.get("abort"):
            (logs / "abort.json").write_text(json.dumps({"stage": run["abort"], "exit": run["code"]}))
        if run.get("result"):
            report = {"sha": run.get("sha", head), "result": run["result"], "missingStages": run.get("missing", []),
                      "stages": [{"name": name, "result": result} for name, result, _ in run.get("stages", [])],
                      "skippedStages": []}
            if run.get("abort"):
                report["aborted"] = {"stage": run["abort"], "exit": run["code"]}
            (logs / "stages.json").write_text(json.dumps(report))
        pinned = run.get("pinned", self.base)
        if run.get("result") == "PASS" and run["code"] == 0:
            records = gate_verdict.record_dir(root)
            records.mkdir(parents=True, exist_ok=True)
            bound = run.get("pass_digest", digest_of(head, pinned))
            (records / f"{head}.dev.pass").write_text(
                f"sha={head}\nkind=dev\nbase_sha={pinned}\ninput_digest={bound}\n")
        return run["code"], (f"gate: pinned to {pinned}\n" if pinned else "") + run.get("output", "")

    # --- helpers ------------------------------------------------------------------------------------------------------
    def ask(self, **options):
        options.setdefault("pr", int(PR))
        return gate_verdict.answer(self.head, root=self.root, seams=self.seams, **options)

    def store_keys(self):
        directory = self.root / config.get("gate.verdict_store_dir")
        return sorted(str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()) \
            if directory.is_dir() else []

    def put_record(self, **fields):
        record = {"version": gate_verdict.RECORD_VERSION, "head": self.head, "base": self.base,
                  "input_digest": digest_of(self.head, self.base), "verdict": PASSED, "report": "", "red": [],
                  "recorded_at": self.now, **fields}
        gate_verdict.records(self.root).put(gate_verdict.record_key(self.head, digest_of(self.head, self.base)),
                                            json.dumps(record).encode())

    def unobservable(self, found, *words):
        self.assertEqual(found.verdict, UNOBSERVABLE, found.lines())
        self.assertEqual(found.code, config.get("gate.verdict_unobservable_exit_code"))
        for word in words:
            self.assertIn(word, found.reason)


class Contract(Fixture):
    ROW = re.compile(r"^\| (\d+) \| (\w+) \| (.+) \|$", re.M)

    def test_the_exit_table_of_the_docstring_and_of_the_padrao_rule_is_the_code(self):
        """One rule, one place: the docstring and docs/padrao/v5/gate-verdict.md hold one table, and it is the code."""
        rows = self.ROW.findall(gate_verdict.__doc__)
        self.assertEqual({verdict: int(code) for code, verdict, _ in rows}, gate_verdict.exits())
        self.assertEqual(self.ROW.findall((ROOT / "docs/padrao/v5/gate-verdict.md").read_text()), rows)
        self.assertEqual(gate_verdict.exits()[gate_verdict.USAGE], os.EX_USAGE)
        self.assertEqual(len(set(gate_verdict.exits().values())), len(gate_verdict.exits()))
        rule = json.loads((ROOT / "docs/padrao/v5/padrao.json").read_text())
        self.assertIn({"id": "gate-verdict", "file": "gate-verdict.md"}, rule["rules"])

    def test_the_printed_lines_are_the_tables(self):
        printed = {verdict: text for _, verdict, text in self.ROW.findall(gate_verdict.__doc__)}
        answers = {PASSED: gate_verdict.Answer(PASSED, "<head>", "<base>", "<digest>"),
                   FAILED: gate_verdict.Answer(FAILED, "<head>", "<base>", "<digest>", red=[("<stage>", "<class>")]),
                   UNOBSERVABLE: gate_verdict.Answer(UNOBSERVABLE, "<head>", reason="<reason>")}
        for verdict, found in answers.items():
            with self.subTest(verdict):
                for line in found.lines():
                    self.assertIn(f"`{line}`", printed[verdict])

    def test_a_usage_error_exits_ex_usage_and_prints_no_verdict(self):
        for argv in ([], ["--head", "xyz"], ["--head", self.head, "--pr", "0"], ["--head", self.head, "--pr", "x"],
                     ["--head", self.head, "--base", "HEAD"]):
            out, err = io.StringIO(), io.StringIO()
            with self.subTest(argv=argv), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                with self.assertRaises(SystemExit) as raised:
                    gate_verdict.main(argv, self.seams, self.root)
                self.assertEqual(raised.exception.code, os.EX_USAGE)
                self.assertEqual(out.getvalue(), "")
        done = subprocess.run([str(ROOT / "scripts/gate-verdict"), "--head", "xyz"], capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (os.EX_USAGE, ""))
        self.assertEqual(self.runs, [])

    def test_the_json_answer_is_one_object_with_the_same_exit(self):
        self.run_as = {"code": 1, "result": "FAIL", "stages": [("unit tests", "FAIL", "AssertionError: no")]}
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = gate_verdict.main(["--head", self.head, "--pr", PR, "--json"], self.seams, self.root)
        payload = json.loads(out.getvalue())
        self.assertEqual((payload["verdict"], payload["exit"], code), (FAILED, code, gate_verdict.exits()[FAILED]))
        self.assertEqual(payload["red"], [{"stage": "unit tests", "class": "code"}])
        self.assertEqual((payload["head"], payload["base"], payload["digest"]),
                         (self.head, self.base, digest_of(self.head, self.base)))

    def test_a_fault_of_the_api_is_unobservable_never_exit_1(self):
        def broken(*args):
            raise RuntimeError("boom")
        self.seams.bind = broken
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gate_verdict.main(["--head", self.head, "--pr", PR], self.seams, self.root)
        self.assertEqual(code, config.get("gate.verdict_unobservable_exit_code"))
        self.assertTrue(out.getvalue().startswith(f"verdict {UNOBSERVABLE} {self.head} the API failed"))


class Answers(Fixture):
    def test_a_pass_runs_once_and_is_answered_again_from_its_record(self):
        found = self.ask()
        self.assertEqual((found.verdict, found.code), (PASSED, 0))
        self.assertEqual(found.lines(), [f"verdict PASSED {self.head} {self.base} {digest_of(self.head, self.base)}"])
        again = self.ask()
        self.assertEqual((again.verdict, again.recorded_at, again.lines()), (PASSED, self.now, found.lines()))
        self.assertEqual(self.runs, [(self.head, int(PR))])

    def test_a_failure_names_each_red_stage_with_its_class_and_is_answered_again_from_its_record(self):
        self.run_as = {"code": 1, "result": "FAIL",
                       "stages": [("lint", "PASS", ""), ("unit tests", "FAIL", "AssertionError: expected 3")]}
        found = self.ask()
        self.assertEqual((found.verdict, found.code), (FAILED, 1))
        self.assertEqual(found.lines()[1:], ["red unit tests: code"])
        again = self.ask()
        self.assertEqual((again.verdict, again.red, again.recorded_at), (FAILED, found.red, self.now))
        self.assertEqual(len(self.runs), 1)

    def cold_environments(self, enabled):
        seen = []
        warm = self.gate

        def gate(root, head, pr, logs):
            seen.append({name: os.environ.get(name) for name in
                         ("GATE_BUILD_CACHE_DIR", "GATE_TEST_CACHE_DIR", "GATE_STAGE_CACHE_DIR",
                          gate_verdict.COLD_ENV)})
            return warm(root, head, pr, logs)

        real = config.get
        self.seams.gate = gate
        with mock.patch.object(config, "get", lambda name, *rest: enabled if name == "gate.content_cache_enabled"
                               else real(name, *rest)):
            self.ask()
            found = self.ask(cold=True)
        self.assertEqual((found.verdict, found.recorded_at, found.cold), (PASSED, None, True))
        self.assertEqual(self.runs, [(self.head, int(PR))] * len(seen), "the record of the warm run is never read")
        self.assertIsNone(os.environ.get(gate_verdict.COLD_ENV), "the environment is restored")
        self.assertIsNone(os.environ.get("GATE_STAGE_CACHE_DIR"), "the environment is restored")
        self.assertIs(found.payload()["cold"], True)
        return seen

    def test_cold_never_reads_a_record_or_carries_and_reuses_only_by_content(self):
        """D-076 (amends D-075): --cold is "no result of another tree": a fresh build cache, no record, no carry-over,
        and the content-keyed stores stay (P-56)."""
        warm_env, cold_env = self.cold_environments(True)
        self.assertIsNone(warm_env[gate_verdict.COLD_ENV])
        self.assertEqual(cold_env[gate_verdict.COLD_ENV], "1")
        self.assertTrue(cold_env["GATE_BUILD_CACHE_DIR"].startswith(tempfile.gettempdir()))
        self.assertFalse(os.path.exists(cold_env["GATE_BUILD_CACHE_DIR"]), "the fresh cache is removed after the run")
        self.assertEqual(cold_env["GATE_TEST_CACHE_DIR"], warm_env["GATE_TEST_CACHE_DIR"], "the per-test store stays")
        self.assertEqual(cold_env["GATE_STAGE_CACHE_DIR"],
                         os.path.expanduser(config.get("gate.content_stage_cache_dir")))

    def test_cold_with_the_content_cache_off_reuses_nothing(self):
        """The rollback of D-076: every store of the cold run is fresh (D-075 as merged)."""
        _warm_env, cold_env = self.cold_environments(False)
        self.assertEqual(cold_env["GATE_TEST_CACHE_DIR"], os.path.join(cold_env["GATE_BUILD_CACHE_DIR"], "test-cache"))
        self.assertEqual(cold_env["GATE_STAGE_CACHE_DIR"], cold_env["GATE_BUILD_CACHE_DIR"])

    def test_cold_cannot_be_combined_with_no_run(self):
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            gate_verdict.main(["--head", self.head, "--pr", PR, "--cold", "--no-run"], self.seams, self.root)
        self.assertEqual(raised.exception.code, os.EX_USAGE)
        self.assertEqual(self.runs, [])

    def test_the_plan_hook_decides_no_carry_for_a_cold_run(self):
        def carry_file(cold):
            script = (f'source "{ROOT}/scripts/lib/gate-hooks/plan.sh"; py=true dev=1 pr=1 OU_GATE_PROOF=1 '
                      f'logs=/nowhere OU_GATE_COLD={cold}; gate_hook_plan; echo "${{OU_GATE_CARRY_FILE:-none}}"')
            return subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=True).stdout.strip()

        self.assertEqual(carry_file(0), "/nowhere/carry-decision.json", "a warm run asks gate_carry")
        self.assertEqual(carry_file(1), "none")

    def test_no_run_answers_a_record_or_unobservable_and_never_starts_the_gate(self):
        self.unobservable(self.ask(no_run=True), "no recorded result")
        self.assertEqual(self.runs, [])
        self.ask()
        self.assertEqual(self.ask(no_run=True).verdict, PASSED)
        self.assertEqual(len(self.runs), 1)

    def test_no_run_never_invents_a_pass_from_a_bad_record(self):
        ttl = config.get("gate.verdict_ttl_s")
        bad = {"another base": {"base": self.moved}, "another digest": {"input_digest": sha("other")},
               "another head": {"head": self.moved}, "another version": {"version": "0"},
               "expired": {"recorded_at": self.now - ttl - 1}, "from the future": {"recorded_at": self.now + 1},
               "a time that is no integer": {"recorded_at": "now"}, "a pass with red stages":
               {"red": [{"stage": "lint", "class": "code"}]}, "a failure with none": {"verdict": FAILED},
               "an unknown verdict": {"verdict": "GREEN"},
               "a red stage without its class": {"verdict": FAILED, "red": [{"stage": "unit tests"}]}}
        for name, fields in bad.items():
            with self.subTest(name):
                self.put_record(**fields)
                self.unobservable(self.ask(no_run=True), "no recorded result")
        gate_verdict.records(self.root).put(gate_verdict.record_key(self.head, digest_of(self.head, self.base)), b"{")
        self.unobservable(self.ask(no_run=True), "no recorded result")
        self.assertEqual(self.runs, [])

    def test_tier_2_and_3_neither_read_nor_write_the_store(self):
        self.run_as = dict(self.run_as, pass_digest="")  # a bare --sha run: the gate binds nothing (no base)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            found = self.ask(pr=None)
        self.assertNotIn("not recorded", err.getvalue())  # nothing is recorded in tier 2, so nothing to explain
        self.assertEqual((found.verdict, found.tier), (PASSED, config.get("gate-tier.batch")))
        self.assertEqual(found.lines(), [f"verdict PASSED {self.head} {self.base} {gate_verdict.UNBOUND}"])
        self.assertEqual((self.store_keys(), self.bound), ([], []))
        self.assertEqual(self.ask(pr=None).recorded_at, None)
        self.unobservable(self.ask(pr=None, no_run=True), "never recorded")
        os.environ[gate_tier.ENV] = gate_tier.bind(config.get("gate-tier.per_pr"))
        self.unobservable(self.ask(pr=None, no_run=True), "never recorded")  # no base: nothing to key it on
        os.environ.pop(gate_tier.ENV)
        self.put_record()
        os.environ[gate_tier.ENV] = gate_tier.bind(config.get("gate-tier.battery"))
        self.assertEqual(self.ask().recorded_at, None)
        self.unobservable(self.ask(no_run=True), "never reads")
        self.assertEqual(len(self.runs), len(["tier 2", "tier 2 again", "tier 3"]))

    def test_an_env_or_flake_failure_is_answered_and_not_recorded(self):
        self.run_as = {"code": 1, "result": "FAIL", "stages": [("local database", "FAIL", "local postgres did not start")]}
        found = self.ask()
        self.assertEqual((found.verdict, found.red), (FAILED, [["local database", "env"]]))
        self.assertEqual(self.store_keys(), [])
        self.ask()
        self.assertEqual(len(self.runs), len(["first", "again"]))

    def test_a_live_stage_is_answered_and_never_recorded(self):
        self.run_as = {"code": 1, "result": "FAIL", "stages": [("pr metadata", "FAIL", "FAIL plan: item 3 not ticked")]}
        self.assertEqual(self.ask().red, [["pr metadata", "code"]])
        self.assertEqual(self.store_keys(), [])
        self.run_as = {"code": 1, "result": "FAIL", "stages": [("pr metadata", "FAIL", "FAIL plan"),
                                                               ("unit tests", "FAIL", "AssertionError")]}
        self.ask()
        record = json.loads(gate_verdict.records(self.root).get(gate_verdict.record_key(
            self.head, digest_of(self.head, self.base))))
        self.assertEqual(record["red"], [{"stage": "unit tests", "class": "code"}])


class Metadata(Fixture):
    def test_a_red_metadata_check_is_answered_without_starting_the_gate(self):
        self.meta = (1, "FAIL plan: item(s) 3 not ticked by a commit\nstructure-check (metadata, PR #800): 1 error(s)")
        found = self.ask()
        self.assertEqual((found.verdict, found.red, self.runs), (FAILED, [["pr metadata", "code"]], []))
        self.assertEqual(self.store_keys(), [])
        self.put_record(verdict=FAILED, red=[{"stage": "unit tests", "class": "code"}])
        self.assertEqual(self.ask().red, [["pr metadata", "code"], ["unit tests", "code"]])

    def test_a_red_verdict_names_its_cause_in_the_reason_and_the_lines(self):
        self.meta = (1, "FAIL plan: item(s) 3 not ticked by a commit\nFAIL plan: item(s) 3 not ticked by a commit\n"
                        "FAIL lane: undecidable (engine-config, site-text)\nstructure-check (metadata): 2 error(s)")
        found = self.ask()
        self.assertEqual(found.reason.splitlines(), ["plan: item(s) 3 not ticked by a commit",
                                                     "lane: undecidable (engine-config, site-text)"])
        self.assertEqual(found.lines()[1:], ["red pr metadata: code", "reason plan: item(s) 3 not ticked by a commit",
                                             "reason lane: undecidable (engine-config, site-text)"])
        self.assertEqual(found.payload()["reason"], found.reason)
        self.meta = (0, "")
        self.run_as = {"code": 1, "result": "FAIL", "stages": [("unit tests", "FAIL", "FAIL test_x: expected 3")]}
        self.assertEqual(self.ask().reason, "test_x: expected 3")

    def test_a_recorded_pass_still_needs_the_live_metadata_check(self):
        self.put_record()
        self.meta = (1, "FAIL decision: a comment waits on the owner")
        for no_run in (False, True):
            self.assertEqual(self.ask(no_run=no_run).verdict, FAILED)
        self.assertEqual(self.runs, [])

    def test_a_metadata_check_that_cannot_read_the_pr_or_crashes_is_unobservable(self):
        self.meta = (1, "FAIL commit-check: PR #800 not readable (GitHub REST: 502)")
        self.unobservable(self.ask(), "cannot be read")
        self.meta = (os.EX_SOFTWARE, "Traceback (most recent call last)")
        self.unobservable(self.ask(), "metadata check exited")
        self.assertEqual(self.runs, [])


class Input(Fixture):
    def test_an_unreadable_pr_is_retried_with_a_doubling_wait_then_unobservable(self):
        attempts, wait = config.get("gate.verdict_read_attempts"), config.get("gate.verdict_read_backoff_s")
        self.unreadable = -1
        self.unobservable(self.ask(), f"PR #{PR} cannot be read")
        waits = [wait]
        while len(waits) < attempts - 1:
            waits.append(waits[-1] + waits[-1])
        self.assertEqual(self.slept, waits)
        self.slept.clear()
        self.unreadable = 1
        self.assertEqual(self.ask().verdict, PASSED)
        self.assertEqual(self.slept, [wait])

    def test_a_pr_whose_head_is_not_the_asked_head_is_unobservable(self):
        self.pr_head = self.moved
        self.unobservable(self.ask(), f"head is {self.moved}")
        self.assertEqual(self.runs, [])

    def test_an_unknown_head_is_unobservable(self):
        def unknown(root, value):
            raise gate_pin.PinError(f"unknown commit {value}")
        self.seams.fetch = unknown
        self.unobservable(self.ask(), "unknown commit")

    def test_a_base_other_than_the_tip_is_answered_from_a_record_or_not_at_all(self):
        self.seams.tip = lambda root, ref: self.moved
        self.unobservable(self.ask(base=self.base), f"base tip {self.moved}")
        self.assertEqual(self.runs, [])
        self.put_record()
        self.assertEqual(self.ask(base=self.base).verdict, PASSED)

    def test_a_moved_base_is_bound_again_and_recorded_for_it(self):
        self.run_as = dict(self.run_as, pinned=self.moved)
        found = self.ask()
        self.assertEqual((found.base, found.digest), (self.moved, digest_of(self.head, self.moved)))
        self.assertEqual(self.bound, [self.base, self.moved])
        self.assertEqual(self.store_keys(), [f"{self.head}/{digest_of(self.head, self.moved)}"])


class Runs(Fixture):
    def test_an_abort_is_unobservable_never_a_failure(self):
        self.run_as = {"code": 1, "result": "FAIL", "abort": "local database",
                       "stages": [("local database", "FAIL", "local postgres did not start")]}
        self.unobservable(self.ask(), "local database", "local postgres did not start")
        self.assertEqual(self.store_keys(), [])

    def test_a_run_without_a_readable_or_consistent_report_is_unobservable(self):
        other = {"code": 0, "result": "PASS", "sha": self.moved}
        cases = {"no report": {"code": os.EX_USAGE, "result": None, "output": "FAIL gate preflight: no node\n"},
                 "exit 0, failed report": {"code": 0, "result": "FAIL", "stages": [("lint", "FAIL", "x")]},
                 "exit 1, passed report": {"code": 1, "result": "PASS"}, "another head": other,
                 "a failure naming no stage": {"code": 1, "result": "FAIL", "stages": [("lint", "PASS", "")]}}
        for name, run in cases.items():
            with self.subTest(name):
                self.run_as = run
                self.unobservable(self.ask())
        self.assertEqual(self.store_keys(), [])

    def test_a_pass_whose_gate_record_disagrees_is_answered_and_not_recorded(self):
        self.run_as = dict(self.run_as, pass_digest=sha("another binding"))
        self.assertEqual(self.ask().verdict, PASSED)
        self.assertEqual(self.store_keys(), [])

    def test_a_run_without_a_pin_line_is_answered_and_not_recorded(self):
        self.run_as = {"code": 1, "result": "FAIL", "pinned": "", "stages": [("unit tests", "FAIL", "AssertionError")]}
        self.assertEqual(self.ask().verdict, FAILED)
        self.assertEqual(self.store_keys(), [])

    def test_a_gate_that_cannot_start_is_unobservable(self):
        with self.assertRaises(gate_verdict.Unobservable):
            gate_verdict.gate(self.root, self.head, None, self.root / "logs")

    def test_stdout_holds_only_the_answer(self):
        """The real run seam: a stub gate-local prints to stdout and writes its report; the API passes it to stderr."""
        stub = self.root / "scripts/gate-local"
        stub.parent.mkdir(parents=True)
        stub.write_text("#!/usr/bin/env bash\n"
                        "echo 'gate: pinned to %s'\necho 'GATE: PASSED'\nmkdir -p \"$GATE_REPORT_DIR\"\n"
                        "printf '{\"sha\": \"%s\", \"result\": \"PASS\", \"stages\": []}' "
                        ">\"$GATE_REPORT_DIR/stages.json\"\n"
                        % (self.base, self.head))
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
        self.seams.gate = gate_verdict.gate
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = gate_verdict.main(["--head", self.head, "--pr", PR], self.seams, self.root)
        self.assertEqual((code, out.getvalue().splitlines()),
                         (0, [f"verdict PASSED {self.head} {self.base} {digest_of(self.head, self.base)}"]))
        self.assertIn("GATE: PASSED", err.getvalue())


if __name__ == "__main__":
    unittest.main()
