"""Requirements come from the existing consumer declaration, not adapter intersection."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / 'lib'))
import forge_requirements as requirements
import operation_demands


class Requirements(unittest.TestCase):
    def test_train_composes_role_and_conditional_ownership(self):
        demand = requirements.for_consumers(['scripts/lib/train.py', 'scripts/lib/engine_role.py'])
        self.assertTrue({'lock', 'unlock', 'change', 'merge'} <= demand.active())
        self.assertNotIn('calls', demand.active())
        self.assertNotIn('approvals', demand.active())
        self.assertIn('approvals', demand.active({'foreign-ownership'}))
        self.assertEqual(demand.optional, {'calls'})
        self.assertEqual(demand.journal, {'append', 'read'})

    def test_every_declared_operation_has_an_obligation(self):
        for consumer, operations in operation_demands.load()['consumers'].items():
            demand = requirements.for_consumers([consumer])
            self.assertEqual(set(operations), demand.required | demand.optional | {op for op, _ in demand.conditional})

    def test_contract_coverage_follows_required_demand(self):
        consumers = ['scripts/lib/train.py']
        requirements.require_coverage(consumers, {'change', 'merge'})
        with self.assertRaisesRegex(operation_demands.CompatibilityError, 'approvals'):
            requirements.require_coverage(consumers, {'change', 'merge'}, {'foreign-ownership'})


if __name__ == '__main__':
    unittest.main()
