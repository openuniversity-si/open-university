"""Local declaration -> construction -> journal + forge + conditional contract."""
from pathlib import Path
import sys
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / 'lib'))
import test_forge_contract as contract
import forge_events as events
import forge_requirements as requirements
import operation_demands


class FlowCompatibility(unittest.TestCase):
    def setUp(self):
        fixture = contract.OriginContract('test_change_names_the_head_the_base_and_the_body')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture

    def test_routed_train_flow_retains_journal_and_forge_responsibilities(self):
        adapter = self.fixture.adapter
        journal = events.MemoryAdapter()
        routed = events.RoutingAdapter(adapter, {}, default=journal)
        consumers = ['scripts/lib/train.py', 'scripts/lib/engine_role.py', 'scripts/lib/train_queue.py']
        demand = requirements.for_consumers(consumers)
        requirements.require_coverage(consumers, operation_demands.load()['proofs']['origin'], {'foreign-ownership'})
        requirements.require_surface(routed, demand.active({'foreign-ownership'}), 'local train flow')
        port = events.ForgeEvents(routed, events.SystemClock(), 'test', 'flow', consumer='scripts/lib/train.py', conditions={'foreign-ownership'})
        self.assertEqual(port.change(contract.REPO, contract.PR)['head'], contract.HEAD)
        self.assertEqual(port.approvals(contract.REPO, contract.PR), ['alice'])
        self.assertTrue(port.lock(contract.REPO, 'train', 'fixture', 1))
        port.unlock(contract.REPO, 'train', 'fixture')
        self.assertEqual(port.read(contract.REPO, contract.PR), [])
        self.assertEqual(self.fixture.forge.comment_records, [])

    def test_partial_provider_is_rejected_even_when_evidence_names_the_real_forge(self):
        # The concrete identity/evidence still matches; the implementation has lost
        # a required method. Neither journal nor first forge effect may run.
        with mock.patch.object(type(self.fixture.adapter), 'merge', None):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'OriginAdapter.*merge'):
                events.ForgeEvents(self.fixture.adapter, events.SystemClock(), 'test', 'partial',
                                   consumer='scripts/lib/train.py')
        self.assertEqual(self.fixture.forge.merged, [])
        self.assertEqual(self.fixture.forge.comment_records, [])

    def test_active_conditional_requirement_is_checked_at_construction(self):
        with mock.patch.object(type(self.fixture.adapter), 'approvals', None):
            # Inactive ownership does not demand approvals.
            events.ForgeEvents(self.fixture.adapter, events.SystemClock(), 'test', 'local',
                               consumer='scripts/lib/train.py')
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'OriginAdapter.*approvals'):
                events.ForgeEvents(self.fixture.adapter, events.SystemClock(), 'test', 'foreign',
                                   consumer='scripts/lib/train.py', conditions={'foreign-ownership'})
        self.assertEqual(self.fixture.forge.merged, [])

    def test_contract_gap_refuses_even_when_the_provider_method_exists(self):
        document = operation_demands.load()
        proofs = dict(document['proofs'], origin=dict(document['proofs']['origin']))
        del proofs['origin']['merge']
        with mock.patch.object(operation_demands, 'load', return_value=dict(document, proofs=proofs)):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'operation merge, adapter origin'):
                events.ForgeEvents(self.fixture.adapter, events.SystemClock(), 'test', 'unproven',
                                   consumer='scripts/lib/train.py')
        self.assertEqual(self.fixture.forge.merged, [])


if __name__ == '__main__':
    unittest.main()
