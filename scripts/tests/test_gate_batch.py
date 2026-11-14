"""Batch gate (GS1): the union of several PRs gated once, with per-PR attribution. Hermetic: temp git repositories."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import config  # noqa: E402
import gate_batch as batch  # noqa: E402
import units  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_GLOBAL": "/dev/null"}


class Repo(unittest.TestCase):
    """base <- mid, other (units); one commit on main, then a branch per PR."""

    _template = None  # built once per process: the fixture repository after its base commit (F127)

    @classmethod
    def template(cls):
        if Repo._template is None:
            Repo._template = tempfile.TemporaryDirectory()
            with mock.patch.dict(os.environ, GIT_ENV):
                cls.build(pathlib.Path(Repo._template.name))
        return pathlib.Path(Repo._template.name)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        patch = mock.patch.dict(os.environ, GIT_ENV)
        patch.start()
        self.addCleanup(patch.stop)
        shutil.copytree(self.template(), self.root, symlinks=True, dirs_exist_ok=True)
        units.reset()

    @classmethod
    def build(cls, root):
        self = cls.__new__(cls)
        self.root = root
        fixture_copy.folders(self.root, ("config/registry", "contracts/units", "contracts/config", "docs/domain"))
        # OU-DECOUPLE F5 (D-113): the engine registry scopes no product path; the fixture's registry scopes its product.
        registry = self.root / "config/registry/gate.json"
        data = json.loads(registry.read_text())
        data["properties"]["gate.scoped_globs"]["default"] = ["products/demo/src/**"]
        registry.write_text(json.dumps(data))
        for unit, paths, requires in (("base", ["products/demo/src/base/**"], {}), ("mid", ["products/demo/src/mid/**"], {"base": "^1"}),
                                      ("other", ["products/demo/src/other/**"], {})):
            folder = self.root / "units" / unit
            folder.mkdir(parents=True)
            (folder / "unit.json").write_text(json.dumps({"id": unit, "purpose": "fixture", "cell": "engine",
                                                         "owner": "engine-lane", "paths": paths, "requires": requires}))
        self.write("products/demo/src/base/a.ts", "one\ntwo\nthree\n")
        self.write("products/demo/src/base/a.test.ts", "t\n")
        self.write("products/demo/src/mid/b.ts", "b\n")
        self.write("products/demo/src/mid/b.test.ts", "t\n")
        self.write("products/demo/src/other/c.ts", "c\n")
        self.write("products/demo/src/other/c.test.ts", "t\n")
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.git("repack", "-a", "-d", "-q")  # one pack instead of ~150 object folders: cheap to copy and to remove per test
        self.git("prune-packed")

    def tearDown(self):
        units.reset()
        self._tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, check=True).stdout.strip()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def pr(self, name, edits):
        """A branch from main with the edits committed (one `git fast-import`, no checkout); returns its head."""
        lines = [f"commit refs/heads/{name}", "committer t <t@example.com> 1700000000 +0000", f"data {len(name)}", name,
                 "from refs/heads/main"]
        for rel, text in edits.items():
            lines += [f"M 100644 inline {rel}", f"data {len(text.encode())}", text]
        lines += ["done", ""]
        subprocess.run(["git", "-C", str(self.root), "fast-import", "--quiet", "--done"], input="\n".join(lines),
                       text=True, capture_output=True, check=True)
        return self.git("rev-parse", name)


class UnionTest(Repo):
    def test_independent_prs_merge_into_one_commit_with_both_changes(self):
        a = self.pr("a", {"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"})
        b = self.pr("b", {"products/demo/src/other/c.ts": "C\n"})
        head, included, conflicts = batch.merge_union(self.root, self.git("rev-parse", "main"), [a, b])
        self.assertEqual((included, conflicts), ([a, b], []))
        self.assertEqual(self.git("show", f"{head}:products/demo/src/base/a.ts"), "ONE\ntwo\nthree")
        self.assertEqual(self.git("show", f"{head}:products/demo/src/other/c.ts"), "C")
        self.assertEqual(self.git("rev-parse", "--abbrev-ref", "HEAD"), "main")
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_a_conflicting_pr_is_reported_and_left_out(self):
        a = self.pr("a", {"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"})
        c = self.pr("c", {"products/demo/src/base/a.ts": "uno\ntwo\nthree\n"})
        b = self.pr("b", {"products/demo/src/other/c.ts": "C\n"})
        head, included, conflicts = batch.merge_union(self.root, self.git("rev-parse", "main"), [a, c, b])
        self.assertEqual(included, [a, b])
        self.assertEqual(conflicts, [{"sha": c, "files": ["products/demo/src/base/a.ts"]}])
        self.assertEqual(self.git("show", f"{head}:products/demo/src/other/c.ts"), "C")
        self.assertEqual(self.git("show", f"{head}:products/demo/src/base/a.ts"), "ONE\ntwo\nthree")

    def test_member_order_and_wrong_supplied_tree(self):
        a = self.pr("a", {"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"})
        b = self.pr("b", {"products/demo/src/other/c.ts": "C\n"})
        base = self.git("rev-parse", "main")
        for members in ([a, b], [b, a]):
            head, included, conflicts = batch.merge_union(self.root, base, members)
            self.assertEqual(included, members)
            self.assertEqual(self.git("show", "-s", "--format=%P", head).split()[1], members[-1])
            self.assertEqual(self.git("show", "-s", "--format=%P", head + "^1").split(), [base, members[0]])
            self.assertEqual(conflicts, [])
        with self.assertRaisesRegex(batch.BatchError, "does not have the tree"):
            batch.plan(self.root, base, [a, b], head=a)


class PlanTest(Repo):
    def make(self):
        a = self.pr("a", {"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"})
        b = self.pr("b", {"products/demo/src/other/c.ts": "C\n"})
        d = self.pr("d", {"products/demo/src/base/a.ts": "one\ntwo\nTHREE\n"})
        return a, b, d

    def test_the_union_plan_selects_the_union_and_each_pr_keeps_its_own_selection(self):
        a, b, _ = self.make()
        result = batch.plan(self.root, "main", [a, b])
        self.assertEqual(result["selection"]["kind"], "scoped")
        self.assertEqual(result["selection"]["affected"], ["base", "mid", "other"])
        self.assertEqual([pr["selection"]["affected"] for pr in result["prs"]], [["base", "mid"], ["other"]])
        self.assertEqual(result["overlap"], [])
        self.assertEqual(result["devPlan"]["head"], result["head"])
        self.assertEqual(result["included"], [a, b])

    def test_paths_two_prs_change_are_reported_as_overlap(self):
        a, _, d = self.make()
        result = batch.plan(self.root, "main", [a, d])
        self.assertEqual(result["overlap"], ["products/demo/src/base/a.ts"])
        self.assertEqual(result["included"], [a, d])

    def test_one_full_battery_pr_makes_the_union_full(self):
        a = self.pr("a", {"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"})
        e = self.pr("e", {"contracts/extra.json": "{}\n"})
        self.assertEqual(batch.plan(self.root, "main", [a, e])["selection"]["kind"], "full")

    def test_an_unattributed_path_makes_the_union_full(self):
        a = self.pr("a", {"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"})
        f = self.pr("f", {"products/demo/src/stray/x.ts": "x\n"})
        self.assertEqual(batch.plan(self.root, "main", [a, f])["selection"]["kind"], "full")

    def test_a_batch_is_bounded_unique_and_made_of_commits(self):
        a, b, _ = self.make()
        with self.assertRaises(batch.BatchError):
            batch.plan(self.root, "main", [])
        with self.assertRaises(batch.BatchError):
            batch.plan(self.root, "main", [a, a])
        with self.assertRaises(batch.BatchError):
            batch.plan(self.root, "main", [a, b] * (config.get("gate.batch_max_prs") + 1))
        with self.assertRaises(batch.BatchError):
            batch.resolve(self.root, "no-such-ref")


class AttributionTest(Repo):
    FILES = ["products/demo/src/base/a.ts", "products/demo/src/base/a.test.ts", "products/demo/src/mid/b.ts", "products/demo/src/mid/b.test.ts",
             "products/demo/src/other/c.ts", "products/demo/src/other/c.test.ts", "scripts/tests/x.test.sh"]

    def attribute(self, plan, failures, stage_failures=()):
        return batch.attribute(plan, failures, stage_failures, files=self.FILES, root=self.root)

    def planned(self, *edits):
        heads = [self.pr(f"p{i}", edit) for i, edit in enumerate(edits)]
        return batch.plan(self.root, "main", heads), heads

    def test_a_failure_implicates_the_prs_whose_change_can_reach_it(self):
        plan, (a, b) = self.planned({"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"}, {"products/demo/src/other/c.ts": "C\n"})
        failure = {"id": "|unit| products/demo/src/mid/b.test.ts > works", "stage": "script tests", "signature": "Error"}
        result = self.attribute(plan, [failure])
        self.assertEqual(result["verdict"], "fail")
        self.assertEqual(result["prs"][a]["implicated"], [failure["id"]])  # mid requires base
        self.assertEqual(result["prs"][b], {"implicated": [], "clear": True, "conflict": None})
        self.assertEqual(result["unplaced"], [])

    def test_a_failure_in_a_file_a_pr_changed_implicates_it(self):
        plan, (a, b) = self.planned({"products/demo/src/other/c.ts": "C\n"}, {"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"})
        result = self.attribute(plan, [{"id": "|unit| products/demo/src/other/c.test.ts", "stage": "script tests", "signature": ""}])
        self.assertEqual((result["prs"][a]["clear"], result["prs"][b]["clear"]), (False, True))

    def test_a_failure_that_cannot_be_placed_implicates_every_pr(self):
        plan, (a, b) = self.planned({"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"}, {"products/demo/src/other/c.ts": "C\n"})
        result = self.attribute(plan, [{"id": "|unit| products/demo/src/ghost/x.test.ts", "stage": "script tests", "signature": ""}])
        self.assertFalse(result["prs"][a]["clear"] or result["prs"][b]["clear"])
        self.assertEqual(result["unplaced"], ["|unit| products/demo/src/ghost/x.test.ts"])

    def test_a_failed_stage_without_tests_implicates_every_pr(self):
        plan, (a, b) = self.planned({"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"}, {"products/demo/src/other/c.ts": "C\n"})
        result = self.attribute(plan, [], ["shellcheck"])
        self.assertEqual((result["prs"][a]["implicated"], result["prs"][b]["implicated"]), (["shellcheck"], ["shellcheck"]))
        self.assertEqual(result["unplaced"], ["shellcheck"])

    def test_a_full_battery_pr_is_implicated_by_any_failure(self):
        plan, (a, e) = self.planned({"products/demo/src/other/c.ts": "C\n"}, {"contracts/extra.json": "{}\n"})
        result = self.attribute(plan, [{"id": "|unit| products/demo/src/other/c.test.ts", "stage": "script tests", "signature": ""}])
        self.assertFalse(result["prs"][e]["clear"])

    def test_a_green_run_clears_every_included_pr_and_a_conflict_is_not_clear(self):
        a = self.pr("a", {"products/demo/src/base/a.ts": "ONE\ntwo\nthree\n"})
        c = self.pr("c", {"products/demo/src/base/a.ts": "uno\ntwo\nthree\n"})
        result = self.attribute(batch.plan(self.root, "main", [a, c]), [])
        self.assertEqual(result["verdict"], "pass")
        self.assertTrue(result["prs"][a]["clear"])
        self.assertEqual(result["prs"][c], {"implicated": [], "clear": False, "conflict": ["products/demo/src/base/a.ts"]})

    def test_the_file_of_a_failing_test_id(self):
        files = set(self.FILES)
        self.assertEqual(batch.file_of("|unit| products/demo/src/mid/b.test.ts > a > b", files), "products/demo/src/mid/b.test.ts")
        self.assertEqual(batch.file_of("scripts/tests/x.test.sh", files), "scripts/tests/x.test.sh")
        self.assertEqual(batch.file_of("label products/demo/src/other/c.test.ts > t", files), "products/demo/src/other/c.test.ts")
        self.assertIsNone(batch.file_of("|unit| products/demo/src/none.test.ts", files))
        # OU-DECOUPLE F5 (D-113): a path relative to Open University's web package is no longer resolved.
        self.assertIsNone(batch.file_of("|unit| src/mid/b.test.ts", files))


if __name__ == "__main__":
    unittest.main()
