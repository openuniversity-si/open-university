import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/lib"))
import gate_policy as policy

# OU-DECOUPLE F2 (D-108), F5 (D-113): the engine gate orders the prerequisites and the script tests only; a path no
# engine area maps (a product fixture under products/demo) plans the always stages.
ENGINE = list(policy.PREREQUISITES) + ["script tests"]
ALWAYS = list(policy.PREREQUISITES)
PRODUCT = "products/demo/src/catalog/domain/slug.ts"


class DevPlan(unittest.TestCase):
    def setUp(self):
        self.policy = policy

    def test_invalid_identity_stays_full(self):
        plan = self.policy.select_dev_plan([PRODUCT], "", "abc")
        self.assertEqual(plan["kind"], "full")
        self.assertEqual(plan["stages"], ENGINE)
        self.assertIn("invalid diff identity", plan["reason"])

    def test_unknown_is_the_always_stages(self):
        unknown = self.policy.select_dev_plan(["mystery/file.ts"], "base", "head", ROOT)
        self.assertEqual(unknown["kind"], "scoped")
        self.assertIn("structure check", unknown["stages"])
        self.assertNotIn("script tests", unknown["stages"])
        self.assertIn("unmapped path: mystery/file.ts", unknown["reason"])
        product = self.policy.select_dev_plan([PRODUCT, "products/demo/src/app/page.tsx"], "base", "head", ROOT)
        self.assertEqual(product["kind"], "scoped")
        self.assertEqual(product["stages"], ALWAYS)

    def test_engine_tooling_selects_the_script_tests(self):
        plan = self.policy.select_dev_plan(["scripts/lib/gate_policy.py"], "base", "head", ROOT)
        self.assertEqual(plan["kind"], "scoped")
        self.assertEqual(plan["stages"], ENGINE)
        self.assertEqual(plan["areas"], ["delivery"])
        self.assertEqual(plan["policyVersion"], policy.POLICY_VERSION)
        self.assertEqual((plan["base"], plan["head"]), ("base", "head"))

    def test_a_unit_manifest_change_is_scoped_to_the_units_area(self):
        plan = self.policy.select_dev_plan(["units/engine-gate-plan/unit.json"], "base", "head", ROOT)
        self.assertEqual(plan["kind"], "scoped")
        self.assertIn("engine-units", plan["areas"])
        self.assertIn("generated drift", plan["stages"])

    def test_rename_uses_both_sides(self):
        plan = self.policy.select_dev_plan(["scripts/lib/old.py", "services/runner/new.py"], "base", "head", ROOT)
        self.assertEqual(plan["kind"], "scoped")
        self.assertEqual(plan["paths"], ["scripts/lib/old.py", "services/runner/new.py"])
        self.assertEqual(plan["areas"], ["delivery", "engine-services"])
        self.assertEqual(plan["stages"], ENGINE)


if __name__ == "__main__":
    unittest.main()
