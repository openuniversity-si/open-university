"""Table-driven area plans. An unmapped path or an empty diff is the always stages (D-106)."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/lib"))
import gate_areas
import gate_policy as policy
import gate_report


# T2 (TX23): the stage groups are read from the registry the plans are built from, so adding a stage edits no list here.
# Which path selects which group stays spelled out in the case tables below; what a group contains does not.
AREAS = gate_areas.load()
SECRETS = list(AREAS.always)
SCRIPTS = list(AREAS.groups["script-tests"])
# OU-DECOUPLE F5 (D-113): Open University's areas and stages left with it; a path outside every area (a product
# fixture under products/demo) is unmapped and plans the always stages (D-106).
PRODUCT = "products/demo/src/app/page.tsx"


def stages(paths):
    return gate_areas.plan_for(paths)


def picked(*groups):
    wanted = set()
    for group in groups:
        wanted.update(group)
    return [stage for stage in gate_areas.load().order if stage in wanted]


class AreaPlans(unittest.TestCase):
    def assert_plan(self, paths, expected, *, kind="scoped"):
        plan = stages(paths)
        self.assertEqual(plan["kind"], kind, plan["reason"])
        self.assertEqual(plan["stages"], expected)
        self.assertEqual(set(plan["reasons"]), set(expected))
        if kind == "scoped":
            skipped = {item["stage"] for item in plan["skipped"]}
            self.assertFalse(skipped & set(expected))
            self.assertEqual(skipped | set(expected), set(gate_areas.load().full_stages))

    def test_table(self):
        cases = {
            "scripts-only": (["scripts/cloud/setup.sh"], picked(SECRETS, SCRIPTS)),
            "engine-config": (
                ["config/registry/premises.json", "contracts/premises/premise.v1.json"],
                picked(SECRETS, SCRIPTS),
            ),
            "docs-only": (["docs/operations/local-gate.md"], picked(SECRETS)),  # GX-18: an uncovered doc
            "units": (["units/engine-gate-plan/unit.json"], picked(SECRETS, SCRIPTS)),
            "services": (["services/runner/tower-runner.service.tmpl"], picked(SECRETS, SCRIPTS)),
            "repo-config": ([".githooks/pre-push"], picked(SECRETS, SCRIPTS)),
        }
        for name, (paths, expected) in cases.items():
            with self.subTest(name=name):
                self.assert_plan(paths, expected)

    def test_d106_unmapped_and_empty_are_the_always_stages_and_invalid_identity_is_the_full_battery(self):
        mapping = gate_areas.load()
        full = list(mapping.full_stages)
        always = [stage for stage in full if stage in mapping.always]
        for paths in ([], ["mystery/file.ts"], [PRODUCT, "mystery/file.ts"]):
            plan = stages(paths)
            self.assertEqual(plan["kind"], "scoped", plan["reason"])
            self.assertEqual(plan["stages"], always)
            self.assertEqual({item["stage"] for item in plan["skipped"]}, set(full) - set(always))
        self.assertIn("D-106", stages([])["reason"])
        self.assertIn("unmapped path: mystery/file.ts; the structure check refuses it", stages(["mystery/file.ts"])["reason"])
        changed = stages(["mystery/file.ts", "scripts/lib/gate-areas.json"])
        self.assertEqual(changed["kind"], "full", changed["reason"])
        self.assertEqual(changed["stages"], full)
        self.assertIn("the area map changed", changed["reason"])
        invalid = policy.select_dev_plan([PRODUCT], "", "abc")
        self.assertEqual(invalid["kind"], "full")
        self.assertIn("invalid diff identity", invalid["reason"])
        self.assertEqual(invalid["policyVersion"], policy.POLICY_VERSION)
        self.assertEqual(invalid["stages"], full)

    def test_f5_the_engine_map_has_only_engine_areas_and_a_product_path_is_unmapped(self):
        # OU-DECOUPLE F5 (D-113): the plan carries no production deploy, database gate or subject install flag.
        plan = stages([PRODUCT])
        self.assertEqual(plan["stages"], SECRETS)
        self.assertEqual(plan["areas"], [])
        self.assertIn(f"unmapped path: {PRODUCT}", plan["reason"])
        self.assertFalse({"deploy", "dbRequired", "nodeRequired"} & set(plan))
        self.assertEqual({area.id for area in AREAS.areas},
                         {"docs", "delivery", "engine-config", "engine-units", "engine-services", "engine-infra",
                          "repo-config", "web"})

    def test_d319_the_site_is_an_area_of_its_own_that_runs_no_engine_script_test(self):
        # D-319: apps/web is judged by its own commands in the Torre's workflow; the engine gate runs its always stages.
        plan = stages(["apps/web/src/app/page.tsx"])
        self.assertEqual(plan["stages"], SECRETS)
        self.assertEqual(plan["areas"], ["web"])
        self.assertFalse({"deploy", "dbRequired", "nodeRequired"} & set(plan))

    def test_the_always_stages_and_the_groups_name_every_ordered_stage_exactly_once(self):
        # T2: the case tables read their stage lists from the registry, so this is what keeps a stage from being dropped,
        # duplicated or left in no group by a registry edit that the derived lists would follow silently.
        named = list(AREAS.always) + [stage for group in AREAS.groups.values() for stage in group]
        self.assertEqual(sorted(named), sorted(AREAS.full_stages))
        self.assertEqual(len(named), len(set(named)))
        self.assertEqual(picked(named), list(AREAS.full_stages))
        # D-109, OU-DECOUPLE F5 (D-113): the map orders no stage outside the always stages and the groups any more.
        self.assertEqual(list(AREAS.order), list(AREAS.full_stages))
        # The always stages agree with the prerequisites gate_policy spells independently of the area registry, and the
        # engine gate orders nothing else but the script tests (OU-DECOUPLE F2, D-108).
        self.assertEqual(SECRETS, list(policy.PREREQUISITES))
        self.assertEqual(list(AREAS.full_stages), list(policy.PREREQUISITES) + SCRIPTS)

    def test_d109_an_ordered_stage_no_group_names_is_never_selected(self):
        # D-109: a map may order a stage outside every group (for a pinned base's loader); no plan selects it.
        data = json.loads(gate_areas.DEFAULT.read_text())
        data["order"].append("retired stage")
        mapping = gate_areas.AreaMap(data)
        self.assertIn("retired stage", mapping.order)
        self.assertNotIn("retired stage", mapping.full_stages)

    def test_the_map_needs_the_docs_area(self):
        data = json.loads(gate_areas.DEFAULT.read_text())
        data["areas"] = [area for area in data["areas"] if area["id"] != "docs"]
        with self.assertRaisesRegex(gate_areas.AreaMapError, "missing required area docs"):
            gate_areas.AreaMap(data)

    def test_dry_run_text_names_a_reason_per_stage(self):
        text = gate_areas.format_plan(stages(["scripts/cloud/setup.sh"]))
        self.assertIn("area plan: scoped", text)
        self.assertIn("secret scan (history): always", text)
        self.assertIn("script tests: delivery tooling under scripts/: scripts/cloud/setup.sh", text)
        doc = gate_areas.format_plan(stages(["docs/operations/local-gate.md"]))
        self.assertIn("script tests: skipped (not required by docs)", doc)

    def test_scoped_report_does_not_require_stages_the_plan_skipped(self):
        plan = stages(["docs/operations/local-gate.md"])
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            (logs / "plan.json").write_text(json.dumps(plan))
            self.assertEqual(gate_report.expected_stages("dev", logs), SECRETS)
            self.assertNotIn("script tests", gate_report.expected_stages("dev", logs))
            self.assertEqual(gate_report.expected_stages("noite", logs), list(policy.PLANS["noite"]))


class AreaCoverage(unittest.TestCase):
    """OU-DECOUPLE F1 (D-106): every tracked path belongs to an area of the judged checkout's own map."""

    def repo(self, files):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        target = root / "scripts/lib/gate-areas.json"
        target.parent.mkdir(parents=True)
        target.write_text((ROOT / "scripts/lib/gate-areas.json").read_text())
        for name in files:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x\n")
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        return root

    def test_d106_a_tracked_path_with_no_area_is_refused_by_name(self):
        root = self.repo(["scripts/x.py", "mystery/file.ts", "docs/a.md"])
        self.assertEqual(gate_areas.coverage_errors(root),
                         ["mystery/file.ts: no area of scripts/lib/gate-areas.json claims it; add it to one (D-106)"])

    def test_d106_the_judged_checkouts_own_map_decides(self):
        root = self.repo(["mystery/file.ts"])
        target = root / "scripts/lib/gate-areas.json"
        data = json.loads(target.read_text())
        data["areas"].append({"id": "mystery", "title": "a new area", "paths": ["mystery/**"], "groups": ["script-tests"]})
        target.write_text(json.dumps(data))
        self.assertEqual(gate_areas.coverage_errors(root), [])

    def test_d106_this_checkout_has_no_path_without_an_area(self):
        self.assertEqual(gate_areas.coverage_errors(ROOT), [])


class DocsScriptTests(unittest.TestCase):
    """GX-18: the docs area runs the script tests whose declared covers meet the diff, and no others."""

    def chosen(self, paths):
        plan = gate_areas.plan_for(paths)
        self.assertEqual(plan["kind"], "scoped", plan["reason"])
        if "script tests" not in plan["stages"]:
            return None
        import gate_script_tests
        return sorted(Path(item).name for item in gate_script_tests.select_plan(plan)[0])

    def covering(self, path, mapping=None):
        import gate_script_tests
        mapping = mapping if mapping is not None else gate_script_tests.load()
        return sorted(Path(test["script"]).name for test in mapping["tests"]
                      if any(gate_areas.glob_match(path, glob) for glob in test["covers"]))

    def test_events_doc_selects_the_tests_that_read_it(self):
        # Which tests cover EVENTS.md evolves with scripts/tests/covers/*.json (D-359); derive the exact set from
        # the mapping and anchor only on event-contracts.test.sh.
        expected = self.covering("docs/process/EVENTS.md")
        chosen = self.chosen(["docs/process/EVENTS.md"])
        self.assertEqual(chosen, expected)
        self.assertIn("event-contracts.test.sh", chosen)

    def test_each_covered_doc_selects_exactly_the_covering_tests(self):
        import gate_script_tests
        mapping = gate_script_tests.load()
        for path in ("docs/units/GX18/retro.md", "docs/programs/gate-excellence/plan.md",
                     "docs/process/premises/P-42.yml"):
            with self.subTest(path=path):
                expected = self.covering(path, mapping)
                self.assertTrue(expected)
                self.assertEqual(self.chosen([path]), expected)
        self.assertIn("lessons.test.sh", self.chosen(["docs/units/GX18/retro.md"]))
        self.assertIn("program.test.sh", self.chosen(["docs/programs/gate-excellence/plan.md"]))
        # The decisions register is covered only by the tests that read it (D-175); which they are changes with
        # the covers, so the selection is asserted against the mapping, never a name.
        self.assertEqual(self.chosen(["docs/domain/DECISIONS.md"]),
                         self.covering("docs/domain/DECISIONS.md", mapping) or None)
        self.assertIn("premises.test.sh", self.chosen(["docs/process/premises/P-42.yml"]))

    def test_an_uncovered_doc_runs_no_script_test(self):
        self.assertIsNone(self.chosen(["docs/operations/local-gate.md"]))

    def test_a_covered_doc_beside_an_uncovered_one_selects_only_the_covered_tests(self):
        expected = self.covering("docs/process/EVENTS.md")
        self.assertTrue(expected)
        self.assertEqual(self.covering("docs/operations/local-gate.md"), [])
        self.assertEqual(self.chosen(["docs/operations/local-gate.md", "docs/process/EVENTS.md"]), expected)

    def test_doc_selection_follows_the_covers_map_hermetically(self):
        import gate_script_tests
        mapping = {
            "fallback": (),
            "scripts": ("scripts/tests/a.test.sh", "scripts/tests/b.test.sh", "scripts/tests/c.test.sh"),
            "tests": (
                {"script": "scripts/tests/a.test.sh", "covers": ("scripts/tests/a.test.sh", "docs/process/EVENTS.md")},
                {"script": "scripts/tests/b.test.sh", "covers": ("scripts/tests/b.test.sh", "docs/process/*.md")},
                {"script": "scripts/tests/c.test.sh", "covers": ("scripts/tests/c.test.sh", "docs/other.md")},
            ),
        }
        with mock.patch.object(gate_script_tests, "load", return_value=mapping):
            self.assertEqual(self.chosen(["docs/process/EVENTS.md"]), ["a.test.sh", "b.test.sh"])
            self.assertEqual(self.chosen(["docs/uncovered.md", "docs/process/EVENTS.md"]), ["a.test.sh", "b.test.sh"])
            self.assertIsNone(self.chosen(["docs/uncovered.md"]))

    def test_unreadable_covers_still_run_the_script_tests(self):
        import gate_script_tests
        with mock.patch.object(gate_script_tests, "load", side_effect=gate_script_tests.ScriptTestMapError("no manifest")):
            plan = gate_areas.plan_for(["docs/operations/local-gate.md"])
        self.assertIn("script tests", plan["stages"])

    def test_the_covered_groups_must_name_known_groups(self):
        data = json.loads(gate_areas.DEFAULT.read_text())
        data["areas"][0]["coveredGroups"] = ["nope"]
        with self.assertRaises(gate_areas.AreaMapError):
            gate_areas.AreaMap(data)


if __name__ == "__main__":
    unittest.main()
