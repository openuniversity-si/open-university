"""Required incompatibility propagates; explicitly optional accounting may degrade."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent / 'lib'))
import flow_check
import engine_role
import forge_events as events
import forge_origin
import gate_report
import gate_status
import prepush
import train
import train_ownership


class Consumers(unittest.TestCase):
    def test_role_inherits_required_coordination_at_construction(self):
        role = engine_role.LockedRole()
        role.adapter = forge_origin.OriginAdapter.__new__(forge_origin.OriginAdapter)
        role.clock, role.producer = events.SystemClock(), 'fixture'
        with mock.patch.object(forge_origin.OriginAdapter, 'lock', None):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'OriginAdapter.*lock'):
                role.port('before-queue')

    def test_flow_report_cannot_turn_missing_open_pulls_into_none(self):
        with mock.patch.object(events, 'adapter_from_config', return_value=object()):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'open_pulls'):
                flow_check.idle_report(subjects=[], runner=lambda *a: (True, ''))

    def test_overlap_cannot_skip_missing_required_capability(self):
        out = []
        with mock.patch.object(prepush, 'overlap', side_effect=events.ForgeCompatibilityError('open_pulls')):
            with self.assertRaisesRegex(events.ForgeCompatibilityError, 'open_pulls'):
                prepush.overlap_part(Path('.'), 'base', ['file'], out.append, lambda: 0)
        self.assertEqual(out, [])

    def test_io_failure_can_still_skip_overlap(self):
        out = []
        with mock.patch.object(prepush, 'overlap', side_effect=OSError('offline')):
            self.assertEqual(prepush.overlap_part(Path('.'), 'base', ['file'], out.append, lambda: 0), 0)
        self.assertIn('overlap: skipped (offline)', out[0])

    def test_optional_calls_degrade_but_required_construction_does_not(self):
        adapter = forge_origin.OriginAdapter.__new__(forge_origin.OriginAdapter)
        with mock.patch.object(forge_origin.OriginAdapter, 'calls', None):
            port = events.ForgeEvents(adapter, events.SystemClock(), 'test', 'accounting',
                                      consumer='scripts/lib/train.py')
            role = SimpleNamespace(port=lambda _: port)
            self.assertIsNone(train.forge_calls(role))
        role = SimpleNamespace(port=mock.Mock(side_effect=events.ForgeCompatibilityError('lock')))
        with self.assertRaisesRegex(events.ForgeCompatibilityError, 'lock'):
            train.forge_calls(role)

    def test_approvals_conditional_foreign_ownership_fixture(self):
        adapter = forge_origin.OriginAdapter.__new__(forge_origin.OriginAdapter)
        port = events.ForgeEvents(adapter, events.SystemClock(), 'test', 'ownership',
                                  consumer='scripts/lib/train.py')
        workspace = SimpleNamespace(changed_files=lambda *a: ['owned/file'])
        ownership = train_ownership.UnitOwnership(workspace)
        role = train.Train.__new__(train.Train)
        role.ownership, role.workspace, role.repo = ownership, workspace, 'o/r'
        entry = SimpleNamespace(sha='head', lane_id='visitor', pr=1)
        manifest = {'id': 'fixture', 'owner': 'owner', 'paths': ['owned/**']}
        with (mock.patch.object(ownership, 'retired', return_value=set()),
              mock.patch.object(ownership, 'manifests', return_value=[manifest]),
              mock.patch.object(adapter, 'approvals', return_value=['owner']) as approvals):
            self.assertTrue(role.owned(port, 'base', entry))
            approvals.assert_called_once_with('o/r', 1)
            entry.lane_id = 'owner'
            approvals.reset_mock()
            self.assertTrue(role.owned(port, 'base', entry))
            approvals.assert_not_called()

    def test_gate_metadata_does_not_swallow_required_incompatibility(self):
        port = SimpleNamespace(change=mock.Mock(side_effect=events.ForgeCompatibilityError('change')))
        with self.assertRaisesRegex(events.ForgeCompatibilityError, 'change'):
            gate_report.emit_evidence({}, 'dev', 1, '.', port)
        publisher = SimpleNamespace(port=port, repo='o/r')
        with self.assertRaisesRegex(events.ForgeCompatibilityError, 'change'):
            gate_status.publish_started(publisher, {'mode': 'dev', 'pr': 1, 'sha': 'head'}, 0)


if __name__ == '__main__':
    unittest.main()
