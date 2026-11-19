"""GX-05 pinned gate (B-09, GA-PG1, D-070): base resolution, tool worktree, reuse, eviction, gate-change detection,
gate_version and the run orchestration. Hermetic: temp git repositories, no network, the driver call is faked."""
import fcntl
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
os.environ["OU_CONFIG_STORE"] = "file"

import config  # noqa: E402
import forge_events  # noqa: E402
import gate_pin  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": "/dev/null"}


HANDOFF = ("GATE_RECORD_DIR", "GATE_LOCK_FILE", "GATE_REPORT_DIR", "OU_GATE_PINNED", "OU_GATE_RECORD_ROOT",
           "OU_GATE_PR_IDENTITY", "OU_GATE_VERSION")


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


class Fixture(unittest.TestCase):
    """origin (bare) <- clone `repo`: base commit, then a head that changes scripts/gate-local and app.txt."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        patch = mock.patch.dict(os.environ, {**GIT_ENV, "GATE_SLOT_DIR": str(self.tmp / "slots")})
        patch.start()
        self.addCleanup(patch.stop)
        # A gate that runs this test (pinned or report-only) exports its own hand-off; the fixture is a fresh caller.
        for name in HANDOFF:
            os.environ.pop(name, None)
        self.repo = self.tmp / "repo"
        (self.repo / "scripts").mkdir(parents=True)
        git(self.tmp, "init", "-q", "--bare", "origin.git")
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "commit.gpgsign", "false")
        git(self.repo, "remote", "add", "origin", str(self.tmp / "origin.git"))
        self.base = self.commit({"scripts/gate-local": "base gate\n", "app.txt": "ok\n", "docs.md": "a\n"}, "base")
        git(self.repo, "push", "-q", "origin", "main")
        self.head = self.commit({"scripts/gate-local": "head gate\n", "app.txt": "broken\n"}, "head")
        (self.repo / ".toolchain/bin").mkdir(parents=True)
        self.addCleanup(self._tmp.cleanup)
        values = {"gate.batch_base_ref": "origin/main"}
        real = config.get
        get = mock.patch.object(config, "get", side_effect=lambda name, *a, **k: values.get(name, real(name, *a, **k)))
        get.start()
        self.addCleanup(get.stop)
        self.values = values

    def commit(self, files, message):
        for name, text in files.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", message)
        return git(self.repo, "rev-parse", "HEAD")


class Options(unittest.TestCase):
    def test_modes(self):
        cases = {("--dev", "--pr", "7"): "dev", ("--db", "--pr", "7"): "db", ("--pr", "7"): "pr",
                 ("--sha", "abc"): "pr-sha", ("--tier3", "--sha", "abc"): "tier3", ("--noite", "--sha", "a"): "noite"}
        for args, mode in cases.items():
            self.assertEqual(gate_pin.options(args)["mode"], mode, args)
        found = gate_pin.options(["--dev", "--sha", "abc", "--plan-file", "/p.json"])
        self.assertEqual((found["sha"], found["plan_file"], found["pr"]), ("abc", "/p.json", None))


class PrIdentity(unittest.TestCase):
    """ORIGIN-FINISH: the PR identity is one change read through the forge port, never a github_cli.py subprocess."""

    HEAD, BASE = hashlib.sha1(b"head").hexdigest(), hashlib.sha1(b"base").hexdigest()
    PR = "9"  # the PR as the command line spells it; the port is asked for int(PR)

    def port(self, change=None):
        repo = gate_pin.setting("forge-events.repo")
        return forge_events.MemoryAdapter({(repo, int(self.PR)): change} if change is not None else {})

    def read(self, port, pr="9"):
        with mock.patch("subprocess.run", side_effect=AssertionError("no subprocess")):
            return gate_pin.pr_identity(ROOT, pr, port=port)

    def test_head_base_and_base_ref_come_from_the_ports_change(self):
        change = {"head": self.HEAD, "base": self.BASE, "base_ref": "mod/roadmap-integration", "head_ref": "x",
                  "body": "", "open": True, "head_repo": "o/r"}
        self.assertEqual(self.read(self.port(change)), (self.HEAD, self.BASE, "mod/roadmap-integration"))

    def test_a_port_or_adapter_failure_is_a_pin_error(self):
        with self.assertRaisesRegex(gate_pin.PinError, r"cannot read PR #9 head/base: unknown change"):
            self.read(self.port())  # forge_events.ForgeEventsError
        broken = mock.Mock(change=mock.Mock(side_effect=RuntimeError("gh: exit 1 (network); GitHub API request failed")))
        with self.assertRaisesRegex(gate_pin.PinError, r"network"):
            self.read(broken)
        with self.assertRaises(gate_pin.PinError):
            self.read(self.port(), pr="nine")

    def test_an_invalid_head_base_or_ref_is_a_pin_error(self):
        for change in ({"head": self.HEAD, "base": self.BASE}, {"head": "short", "base": self.BASE, "base_ref": "main"},
                       {"head": self.HEAD, "base": self.BASE, "base_ref": "-main"}, {"head": None, "base": None}):
            with self.assertRaises(gate_pin.PinError, msg=change):
                self.read(self.port(change))

    def test_the_default_port_is_the_configured_adapter_under_this_modules_demand(self):
        change = {"head": self.HEAD, "base": self.BASE, "base_ref": "main"}
        repo = gate_pin.setting("forge-events.repo")  # read before the port is faked: the config store uses it too
        with mock.patch.object(gate_pin, "setting", side_effect={"forge-events.repo": repo}.__getitem__), \
                mock.patch.object(forge_events, "adapter_from_config", return_value="adapter"), \
                mock.patch.object(forge_events, "clock_from_config", return_value="clock"), \
                mock.patch.object(forge_events, "ForgeEvents") as built:
            built.return_value.change.return_value = change
            self.assertEqual(gate_pin.pr_identity(ROOT, "9"), (self.HEAD, self.BASE, "main"))
        built.assert_called_once_with("adapter", "clock", "gate-pin", "pr-9", consumer="scripts/lib/gate_pin.py")
        built.return_value.change.assert_called_once_with(repo, int(self.PR))

    def test_no_github_cli_path_is_left(self):
        self.assertNotIn("github_cli", pathlib.Path(gate_pin.__file__).read_text())


class Resolve(Fixture):
    def test_sha_pins_to_the_fetched_tip_of_the_batch_base_ref(self):
        head, base, pair = gate_pin.resolve(self.repo, gate_pin.options(["--dev", "--sha", self.head]))
        self.assertEqual((head, base, pair), (self.head, self.base, None))

    def test_a_batch_plan_names_its_base(self):
        plan = self.tmp / "plan.json"
        plan.write_text(json.dumps({"base": self.base}))
        _, base, _ = gate_pin.resolve(self.repo, gate_pin.options(["--sha", self.head, "--plan-file", str(plan)]))
        self.assertEqual(base, self.base)

    def test_pr_reads_head_and_base_in_one_call_and_hands_the_pair_on(self):
        calls = []
        identity = lambda root, pr: calls.append(pr) or (self.head, self.base)  # noqa: E731
        head, base, pair = gate_pin.resolve(self.repo, gate_pin.options(["--dev", "--pr", "9"]), identity)
        self.assertEqual((head, base, pair, calls), (self.head, self.base, f"{self.head}\t{self.base}", ["9"]))

    def test_an_unknown_commit_is_a_pin_error(self):
        with self.assertRaises(gate_pin.PinError):
            gate_pin.resolve(self.repo, gate_pin.options(["--sha", "f" * len(self.base)]))


class StaleBaseSha(Fixture):
    """GX-FIX-forge-rate-2 (D-070), the root cause of the post-#718 per-test comments: GitHub's base.sha of a PR lags the
    tip of its base branch, so a pin that trusts it runs an older base's tooling. The pin takes the fetched tip."""

    def advance_origin(self):
        tip = git(self.repo, "commit-tree", f"{self.base}^{{tree}}", "-p", self.base, "-m", "newer base")
        git(self.repo, "push", "-q", "origin", f"{tip}:refs/heads/main")
        return tip

    def test_a_lagging_base_sha_pins_to_the_fetched_tip_of_the_base_ref(self):
        tip = self.advance_origin()
        identity = lambda root, pr: (self.head, self.base, "main")  # noqa: E731 - GitHub still reports the old base
        head, base, pair = gate_pin.resolve(self.repo, gate_pin.options(["--dev", "--pr", "9"]), identity)
        self.assertEqual((head, base, pair), (self.head, tip, f"{self.head}\t{tip}"))

    def test_a_base_ref_that_cannot_be_fetched_is_a_pin_error_never_a_stale_ref(self):
        identity = lambda root, pr: (self.head, self.base, "gone")  # noqa: E731
        with self.assertRaises(gate_pin.PinError):
            gate_pin.resolve(self.repo, gate_pin.options(["--dev", "--pr", "9"]), identity)

    def test_a_head_behind_the_base_tip_never_runs_its_older_tooling(self):
        tip = self.advance_origin()
        git(self.repo, "fetch", "-q", "origin")
        calls, lines = [], []
        rc = gate_pin.report(self.repo, ["--dev", "--pr", "9"], gate_pin.options(["--dev", "--pr", "9"]), tip,
                             self.head, 0, dict(os.environ), lambda argv, env: calls.append(argv) or 0,
                             lambda *item: None, lines.append)
        self.assertIsNone(rc)
        self.assertEqual(calls, [])
        self.assertIn("does not contain the base tip", lines[-1])


class Worktree(Fixture):
    def test_the_tool_worktree_is_the_base_with_the_callers_toolchain(self):
        tool, held = gate_pin.ensure(self.repo, self.base)
        self.addCleanup(held.close)
        self.assertEqual(tool, gate_pin.pin_root(self.repo) / self.base)
        self.assertEqual((tool / "scripts/gate-local").read_text(), "base gate\n")
        self.assertTrue((tool / ".toolchain").is_symlink())
        self.assertEqual((tool / ".toolchain").resolve(), (self.repo / ".toolchain").resolve())
        self.assertTrue(str(tool).startswith(os.environ["GATE_SLOT_DIR"] + "/" + gate_pin.setting("gate-pin.dir") + "/"))

    def test_a_second_run_on_the_same_base_reuses_the_worktree(self):
        tool, held = gate_pin.ensure(self.repo, self.base)
        held.close()
        (tool / "warm").write_text("kept")
        again, held = gate_pin.ensure(self.repo, self.base)
        held.close()
        self.assertEqual(again, tool)
        self.assertEqual((tool / "warm").read_text(), "kept")

    def test_a_clean_checkout_of_the_base_is_its_own_tool_root(self):
        git(self.repo, "checkout", "-q", self.base)
        tool, held = gate_pin.ensure(self.repo, self.base)
        self.assertEqual((tool, held), (self.repo, None))
        (self.repo / "app.txt").write_text("dirty\n")
        tool, held = gate_pin.ensure(self.repo, self.base)
        held.close()
        self.assertNotEqual(tool, self.repo)

    def test_eviction_keeps_the_newest_base_shas_and_never_one_in_use(self):
        shas = [self.base]
        for index in range(gate_pin.setting("gate-pin.keep_worktrees") + 1):
            shas.append(self.commit({"docs.md": f"{index}\n"}, f"c{index}"))
        (self.repo / "app.txt").write_text("dirty\n")
        held_first = None
        for index, sha in enumerate(shas):
            tool, held = gate_pin.ensure(self.repo, sha)
            os.utime(gate_pin.pin_root(self.repo) / f"{sha}.use", (index + 1, index + 1))
            if index == 0:
                held_first = held
            else:
                held.close()
        self.addCleanup(held_first.close)
        root = gate_pin.pin_root(self.repo)
        present = {sha for sha in shas if (root / sha).is_dir()}
        keep = gate_pin.setting("gate-pin.keep_worktrees")
        self.assertIn(shas[0], present, "a worktree a run holds is never removed")
        self.assertIn(shas[-1], present)
        self.assertNotIn(shas[1], present)
        self.assertLessEqual(len(present - {shas[0]}), keep)

    def test_the_head_tooling_is_a_throwaway_worktree_unless_the_caller_is_the_clean_head(self):
        tool, throwaway = gate_pin.head_tooling(self.repo, self.head)
        self.assertEqual((tool, throwaway), (self.repo, None))
        git(self.repo, "checkout", "-q", self.base)
        tool, throwaway = gate_pin.head_tooling(self.repo, self.head)
        self.assertEqual((tool / "scripts/gate-local").read_text(), "head gate\n")
        gate_pin.drop(self.repo, throwaway)
        self.assertFalse(throwaway.exists())


class GateFiles(unittest.TestCase):
    def test_the_gate_is_its_stages_its_registry_keys_and_its_github_entry_point(self):
        """GATE-FILE-REACH (D-335): the files whose change asks a decision and is judged by the base's tooling."""
        for name in ("scripts/gate-local", "scripts/lib/gate_pin.py", "scripts/structure-check", "scripts/lib/structure.py",
                     "scripts/commit-check", "scripts/lib/commit_check.py", "scripts/verify-commit",
                     "scripts/lib/verify_commit.py", "config/registry/gate/gate.allowed_workflows.json",
                     "config/registry/gate.json"):
            self.assertTrue(gate_pin.GATE_FILE.match(name), name)
        for name in ("scripts/plan", "scripts/lib/config.py", "config/registry/gate-carry/x.json", "config/registry/gate-carry.json",
                     "config/registry/gate/sub/x.json", "docs/scripts/gate-local", "scripts/verify-commit.bak/x"):
            self.assertFalse(gate_pin.GATE_FILE.match(name), name)


class Version(Fixture):
    def test_gate_change_and_version(self):
        self.assertEqual(gate_pin.gate_changed(self.repo, self.base, self.head), ["scripts/gate-local"])
        docs = self.commit({"docs.md": "b\n"}, "docs")
        self.assertEqual(gate_pin.gate_changed(self.repo, self.head, docs), [])
        self.assertEqual(gate_pin.gate_version(self.repo, self.head), gate_pin.gate_version(self.repo, docs))
        self.assertNotEqual(gate_pin.gate_version(self.repo, self.base), gate_pin.gate_version(self.repo, self.head))


class Run(Fixture):
    def drive(self, args, rc_of=lambda argv: 1 if "--report-only" not in argv else 0):
        calls, lines, posts = [], [], []

        def call(argv, env):
            calls.append((argv, env))
            return rc_of(argv)
        identity = lambda root, pr: (self.head, self.base)  # noqa: E731
        rc = gate_pin.run(self.repo, args, environ=dict(os.environ), identity=identity, call=call,
                          post=lambda *item: posts.append(item), out=lines.append)
        return rc, calls, lines, posts

    def test_pinned_red_while_the_heads_own_report_only_run_is_green(self):
        git(self.repo, "checkout", "-q", self.base)
        rc, calls, lines, posts = self.drive(["--dev", "--pr", "9"])
        self.assertEqual(rc, 1, "the exit code is the pinned run's")
        self.assertEqual(lines[0], f"gate: pinned to {self.base}")
        self.assertEqual(lines[1], f"gate: version {gate_pin.gate_version(self.repo, self.base)}")
        (pinned, env), (own, own_env) = calls
        self.assertEqual(pinned[0], str(self.repo / "scripts/gate-local"), "the clean base checkout is the tool root")
        self.assertEqual(env["OU_GATE_PINNED"], self.base)
        self.assertEqual(env["OU_GATE_PR_IDENTITY"], f"{self.head}\t{self.base}")
        self.assertEqual(env["GATE_RECORD_DIR"], str(self.repo.resolve() / ".gate/records"))
        self.assertEqual(own[-1], "--report-only")
        self.assertTrue(own[0].endswith("/scripts/gate-local") and own[0] != pinned[0])
        self.assertNotIn("OU_GATE_PINNED", own_env)
        self.assertNotEqual(own_env["GATE_RECORD_DIR"], env["GATE_RECORD_DIR"], "report-only never writes the record")
        self.assertIn("gate: advisory (head tooling, report-only): PASSED; the verdict is the pinned gate: FAILED (exit 1)",
                      lines)
        (pr, state, body), = posts
        self.assertEqual((pr, state["sha"], state["mode"]), ("9", self.head, "dev+advisory"))
        self.assertTrue(body.splitlines()[0].endswith(f"sha={self.head} mode=dev+advisory"))
        self.assertFalse(list((gate_pin.pin_root(self.repo) / gate_pin.HEADS).glob(f"{self.head}-*")),
                         "the throwaway head worktree is removed")

    def test_the_tool_worktree_runs_when_the_caller_is_not_the_base(self):
        rc, calls, lines, _ = self.drive(["--dev", "--sha", self.head], rc_of=lambda argv: 0)
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0][0][0], str(gate_pin.pin_root(self.repo) / self.base / "scripts/gate-local"))
        self.assertNotIn("OU_GATE_PR_IDENTITY", calls[0][1])
        self.assertEqual(calls[1][0][0], str(self.repo / "scripts/gate-local"), "the clean head caller is its own tooling")

    def test_no_report_only_run_without_a_gate_change_or_with_the_switch_off(self):
        docs = self.commit({"docs.md": "c\n"}, "docs")
        _, calls, _, _ = self.drive(["--dev", "--sha", docs, "--plan-file", self.plan(self.head)])
        self.assertEqual(len(calls), 1)
        self.values["gate-pin.report_only_on_gate_change"] = False
        _, calls, _, _ = self.drive(["--dev", "--sha", self.head])
        self.assertEqual(len(calls), 1)

    def test_a_mode_that_reaches_an_outside_database_gets_no_report_only_run(self):
        _, calls, lines, _ = self.drive(["--db", "--pr", "9"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(line.startswith("gate: advisory skipped (mode db") for line in lines))

    def test_the_switch_off_runs_the_callers_own_tooling_unpinned(self):
        self.values["gate-pin.enabled"] = False
        rc, calls, lines, _ = self.drive(["--dev", "--pr", "9"])
        self.assertEqual((rc, lines, len(calls)), (1, [], 1))
        self.assertEqual(calls[0][0][0], str(self.repo / "scripts/gate-local"))
        self.assertEqual(calls[0][1]["OU_GATE_PINNED"], gate_pin.UNPINNED)

    def test_a_pin_error_goes_to_the_abort_file(self):
        abort = self.tmp / "abort"
        rc = gate_pin.run(self.repo, ["--sha", "e" * len(self.base)], call=lambda *a, **k: self.fail("no run"), abort_file=abort)
        self.assertNotEqual(rc, 0)
        self.assertIn("unknown commit", abort.read_text())

    def plan(self, base):
        path = self.tmp / "plan.json"
        path.write_text(json.dumps({"base": base}))
        return str(path)


class OwnRegistry(unittest.TestCase):
    """The pinned tooling's hermetic sitecustomize imports its own config first; gate_pin reads this checkout's keys."""

    def test_keys_are_read_from_this_checkouts_registry(self):
        with mock.patch.object(config, "get", side_effect=lambda name, root=None: (name, root)):
            self.assertEqual(gate_pin.setting("gate-pin.dir"), ("gate-pin.dir", ROOT))


class Registry(unittest.TestCase):
    def test_defaults(self):
        self.assertIs(gate_pin.setting("gate-pin.enabled"), True)
        self.assertIs(gate_pin.setting("gate-pin.report_only_on_gate_change"), True)
        self.assertGreaterEqual(gate_pin.setting("gate-pin.keep_worktrees"), 1)
        self.assertTrue(gate_pin.setting("gate-pin.dir"))

    def test_the_use_lock_is_shared(self):
        with tempfile.NamedTemporaryFile() as handle:
            first = gate_pin.lock(handle.name, fcntl.LOCK_SH)
            second = gate_pin.lock(handle.name, fcntl.LOCK_SH | fcntl.LOCK_NB)
            first.close()
            second.close()


if __name__ == "__main__":
    unittest.main(verbosity=1)
