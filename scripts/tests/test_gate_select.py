"""Per-unit selection (GS1): it never under-tests, and anything it cannot attribute is the full battery. Hermetic: temp repos."""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import config  # noqa: E402
import gate_policy  # noqa: E402
import gate_select as select  # noqa: E402
import units  # noqa: E402
from gate_areas import glob_match  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

CLASSES = config.get("gate.full_battery_globs")
TOOLING = config.get("gate.reader_scoped_globs")
KEPT = config.get("gate.reader_scoped_exclude")


def concrete(glob):
    """A path that matches the glob."""
    return glob.replace("**", "x/y").replace("*", "z")


class Fixture(unittest.TestCase):
    """A checkout with the real registry and unit schema and three synthetic units: base <- mid, other."""

    # OU-DECOUPLE F5 (D-113): the engine registry scopes no product path (gate.scoped_globs is empty); the fixture's own
    # registry scopes its product, so the selection rules are exercised as before.
    SCOPED = ["products/demo/src/**"]

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        # VAZÃO F53: only what the selection reads (the registry, the unit schema); a copy of docs/domain read every
        # decision record and the trace reported them as covers holes, though no record can change the selection.
        fixture_copy.folders(self.root, ("config/registry", "contracts/units"))
        self.registry("gate.scoped_globs", self.SCOPED)
        self.manifest("base", ["products/demo/src/base/**"], {})
        self.manifest("mid", ["products/demo/src/mid/**"], {"base": "^1"})
        self.manifest("other", ["products/demo/src/other/**"], {})
        units.reset()

    def tearDown(self):
        units.reset()
        self._tmp.cleanup()

    def manifest(self, unit, paths, requires):
        folder = self.root / "units" / unit
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "unit.json").write_text(json.dumps({
            "id": unit, "purpose": "fixture", "cell": "engine", "owner": "engine-lane", "paths": paths, "requires": requires}))

    def pick(self, paths):
        return select.select(paths, self.root)

    def registry(self, name, value):
        path = self.root / "config/registry/gate.json"
        data = json.loads(path.read_text())
        data["properties"][name]["default"] = value
        path.write_text(json.dumps(data))

    def disable(self):
        self.registry("gate.select_enabled", False)


class ScopeTest(Fixture):
    def test_one_unit_affects_itself_and_its_dependents_only(self):
        result = self.pick(["products/demo/src/base/a.ts"])
        self.assertEqual(result["kind"], "scoped")
        self.assertEqual(result["units"], ["base"])
        self.assertEqual(result["affected"], ["base", "mid"])
        # OU-DECOUPLE F5 (D-113): no web test, `vitest related` or lint arguments any more.
        self.assertFalse({"tests", "related", "lint"} & set(result))

    def test_a_leaf_unit_affects_only_itself(self):
        result = self.pick(["products/demo/src/mid/b.ts"])
        self.assertEqual((result["units"], result["affected"]), (["mid"], ["mid"]))

    def test_many_units_take_the_union(self):
        result = self.pick(["products/demo/src/mid/b.ts", "products/demo/src/other/c.ts"])
        self.assertEqual(result["affected"], ["mid", "other"])

    def test_documentation_changes_nothing(self):
        result = self.pick(["docs/a.md", "README.md"])
        self.assertEqual((result["kind"], result["reason"]), ("scoped", "documentation only"))
        self.assertEqual((result["units"], result["affected"]), ([], []))

    def test_documentation_beside_a_unit_path_still_scopes_the_unit(self):
        result = self.pick(["docs/a.md", "products/demo/src/other/c.ts"])
        self.assertEqual(result["affected"], ["other"])

    def test_a_rename_counts_both_names(self):
        result = self.pick(["products/demo/src/mid/b.ts", "products/demo/src/other/b.ts"])
        self.assertEqual(result["affected"], ["mid", "other"])

    def test_a_deleted_path_the_map_still_attributes_stays_scoped(self):
        result = self.pick(["products/demo/src/mid/removed.ts"])
        self.assertEqual(result["kind"], "scoped")
        self.assertEqual(result["affected"], ["mid"])


class FailClosedTest(Fixture):
    def assertFull(self, paths, fragment=""):
        result = self.pick(paths)
        self.assertEqual(result["kind"], "full", result)
        self.assertIn(fragment, result["reason"])
        self.assertEqual((result["units"], result["affected"]), ([], []))
        return result

    def test_every_full_battery_class_runs_everything(self):
        """Except a tooling path (D-076), which TOOLING_TEST covers."""
        for glob in CLASSES:
            path = concrete(glob)
            if any(glob_match(path, g) for g in TOOLING) and not any(glob_match(path, g) for g in KEPT):
                continue
            with self.subTest(glob=glob):
                self.assertFull(["products/demo/src/other/c.ts", path], "full-battery class")

    def test_the_excluded_tooling_keeps_the_full_battery(self):
        for path in ("scripts/cloud/toolchain.json", "scripts/check-architecture.mjs", "scripts/lib/architecture/x.mjs"):
            with self.subTest(path=path):
                self.assertFull(["products/demo/src/other/c.ts", path])

    def test_the_classes_name_the_registry_contracts_engine_shared_lockfiles_and_the_ownership_map(self):
        for needle in ("config/**", "contracts/**", "scripts/lib/**", "scripts/gate*", ".githooks/**", "pnpm-lock.yaml",
                       "units/**"):
            self.assertIn(needle, CLASSES)
        # OU-DECOUPLE F5 (D-113): no class names Open University's web package any more.
        self.assertFalse([glob for glob in CLASSES if glob.startswith("apps/")])
        self.assertEqual(config.get("gate.scoped_globs"), [])

    def test_an_unattributed_path_is_full(self):
        self.assertFull(["products/demo/src/stray/d.ts"], "unattributed")
        self.assertFull(["products/demo/src/other/c.ts", "products/demo/src/stray/new.ts"], "unattributed")

    def test_a_path_outside_the_scoped_globs_is_full(self):
        self.assertFull(["products/demo/content/catalog/a.json"], "outside the scoped paths")
        self.assertFull(["products/demo/public/x.png"], "outside the scoped paths")
        self.assertFull(["something/else.bin"], "outside the scoped paths")

    def test_a_deleted_path_the_map_no_longer_attributes_is_full(self):
        self.assertFull(["products/demo/src/gone/x.ts"], "unattributed")

    def test_no_paths_is_full(self):
        self.assertFull([], "no changed paths")

    def test_one_full_path_beside_scoped_ones_makes_the_run_full(self):
        # OU-DECOUPLE F4 (D-111): a full-battery class outside the tooling paths.
        self.assertFull(["products/demo/src/other/c.ts", "config/registry/units.json"], "config/registry/units.json")

    def test_switching_selection_off_is_full(self):
        self.disable()
        self.assertFull(["products/demo/src/other/c.ts"], "selection is off")


class ClassifyTest(Fixture):
    def test_a_checkout_whose_registry_lacks_the_selection_entries_is_full_not_an_error(self):
        path = self.root / "config/registry/gate.json"
        data = json.loads(path.read_text())
        for name in [name for name in data["properties"] if name in (
                "gate.scoped_globs", "gate.select_enabled", "gate.full_battery_globs")]:
            del data["properties"][name]
        path.write_text(json.dumps(data))
        result = gate_policy.selection_for(["products/demo/src/other/c.ts"], self.root)
        self.assertEqual(result["kind"], "full")
        self.assertIn("could not be computed", result["reason"])

    def test_a_readable_checkout_gets_its_selection(self):
        # OU-DECOUPLE F5 (D-113): the selection reads the registry and the unit manifests only; the tracked-file listing
        # it needed for Open University's web test arguments left, so a checkout without git is judged the same way.
        result = gate_policy.selection_for(["products/demo/src/other/c.ts"], self.root)
        self.assertEqual((result["kind"], result["affected"]), ("scoped", ["other"]))


class ToolingTest(Fixture):
    """D-076 (GATE-FAST): a tooling path runs its unit's tests and its dependents', never the whole battery."""

    def test_a_tooling_path_nobody_owns_affects_no_unit(self):
        result = self.pick(["scripts/gate-dev", "docs/a.md"])
        self.assertEqual((result["kind"], result["affected"]), ("scoped", []))
        self.assertIn("tooling", result["reason"])

    def test_a_tooling_path_beside_a_unit_path_adds_no_unit_of_its_own(self):
        result = self.pick(["scripts/lib/x.py", "products/demo/src/mid/b.ts"])
        self.assertEqual(result["affected"], ["mid"])

    def test_the_unit_that_owns_a_tooling_path_brings_its_dependents(self):
        self.manifest("tool", ["scripts/tool/**"], {})
        self.manifest("user", ["products/demo/src/stray/**"], {"tool": "^1"})
        units.reset()
        result = self.pick(["scripts/tool/run.py"])
        self.assertEqual((result["units"], result["affected"]), (["tool"], ["tool", "user"]))

    def test_an_empty_list_is_the_rollback(self):
        path = self.root / "config/registry/gate.json"
        data = json.loads(path.read_text())
        data["properties"]["gate.reader_scoped_globs"]["default"] = []
        path.write_text(json.dumps(data))
        result = self.pick(["scripts/lib/gate_keys.py"])
        self.assertEqual(result["kind"], "full")
        self.assertIn("full-battery class", result["reason"])


if __name__ == "__main__":
    unittest.main()
