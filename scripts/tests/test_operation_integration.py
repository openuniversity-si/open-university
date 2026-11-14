"""Independent local C5 oracles: relation, configuration and compatibility coexist.

Small source fixtures spell merge and a configuration key independently of JSON.
No adapters are imported, no network or external configuration store is used.
"""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.tests.test_forge_events import EXPECTED_OPERATIONS
sys.path.insert(0, str(ROOT / 'scripts/lib'))
sys.path.insert(0, str(ROOT / 'scripts/tests'))  # a sibling test module, imported the way the runner sees it
from test_forge_events import EXPECTED_OPERATIONS  # noqa: E402
import operation_demands
import unit_check
import operation_relations
import python_source


class RepositoryResponsibility(unittest.TestCase):
    def setUp(self):
        self.enterContext(python_source.snapshot())

    def test_d287_accepts_the_surface_and_removing_acceptance_restores_23_refusals(self):
        document = operation_relations.load(ROOT)
        evidence = 'docs/domain/decisions/D-287.md'
        self.assertTrue((ROOT / evidence).is_file())
        self.assertEqual(set(document['operations']), EXPECTED_OPERATIONS)
        self.assertEqual(set(document['responsibility']['accepted']), set(document['operations']))
        for name, row in document['operations'].items():
            self.assertEqual(row['responsible'], 'engine-lane', name)
            self.assertEqual(document['responsibility']['accepted'][name], [
                {'responsible': 'engine-lane', 'accepted_by': 'engine-lane', 'evidence': evidence}])

        # Reconstruct the pre-decision declaration without changing the real tree.
        original_load = operation_relations.load

        def without_acceptance(root):
            baseline = original_load(root)
            baseline['responsibility']['accepted'] = {}
            for row in baseline['operations'].values():
                row['responsible'] = 'unknown'
            return baseline

        for adapter in ('origin',):
            with self.subTest(adapter=adapter):
                findings, refused = unit_check.operation_check(ROOT, adapter)
                # Every consumer demand of the active forge is proven: origin's push history is answered from the journal
                # (ORIGIN-PUSH-HISTORY), so no compatibility refusal is left for Origin.
                self.assertEqual(refused, [])
                with patch.object(operation_relations, 'load', side_effect=without_acceptance):
                    before, before_refused = unit_check.operation_check(ROOT, adapter)
                missing = [row for row in before_refused if row[1] == 'missing-responsibility']
                self.assertEqual(len(missing), len(EXPECTED_OPERATIONS))
                self.assertEqual({detail for _, _, detail in missing},
                                 {f'{name}: no accepted responsible' for name in document['operations']})
                self.assertEqual([row for row in before if row not in missing], findings)
                self.assertEqual([row for row in before_refused if row not in missing], refused)


class OperationIntegration(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.accepted = {'responsible': 'release-role', 'accepted_by': 'release-role',
                         'evidence': 'fixture: release-role explicitly accepts merge'}
        self.relation = {'operations': [{'name': 'merge', 'responsible': 'unknown',
                         'consumers': ['scripts/lib/consumer.py'], 'sites': [
                             {'file': 'scripts/lib/consumer.py', 'line': 2,
                              'consumer': 'run', 'crossing': 'port'}]}],
                         'responsibility': {'accepted': {'merge': [self.accepted]}}}
        self.write('scripts/lib/forge_events.py',
                   "class ForgeEvents:\n    def merge(self): return self._operation('merge')()\n")
        self.write('scripts/lib/forge_origin.py', 'class OriginAdapter:\n    def merge(self): pass\n')
        self.write('scripts/lib/consumer.py', "def run(port):\n    port.merge()\nLIMIT = 'demo.limit'\n")
        self.write('scripts/tests/proof.py',
                   'class Proof:\n    def test_merge(self):\n        self.adapter.merge()\n')
        self.write('scripts/lib/operation_relations.json', self.relation)
        self.write('config/registry/forge-events/demo.limit.json', {'x-readers': ['scripts/lib/consumer.py']})
        self.config = {'keys': [{'name': 'demo.limit', 'kind': 'operation', 'operations': ['merge'],
                                'consumers': ['scripts/lib/consumer.py'], 'reason': 'Bounds merge.'}]}
        self.write('scripts/lib/operation_config_relations.json', self.config)
        self.demands = {'consumers': {'scripts/lib/consumer.py': ['merge']},
                        'proofs': {'origin': {'merge': 'scripts/tests/proof.py::Proof::test_merge'}}}
        self.declare_demands()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value))

    def declare_demands(self):
        operation_demands.load.cache_clear()
        operation_demands._evidence.cache_clear()
        self.write('scripts/lib/operation_demands.json', self.demands)

    def refusals(self):
        return unit_check.operation_check(self.root, 'origin')[1]

    def break_all(self):
        self.relation['responsibility']['accepted'] = {}
        self.write('scripts/lib/operation_relations.json', self.relation)
        self.write('config/registry/forge-events/demo.orphan.json', {'x-readers': []})
        self.demands['proofs']['origin'] = {}
        self.declare_demands()

    def test_unique_accepted_owner_and_compatible_demand_with_bounded_config_pass(self):
        self.assertEqual(self.refusals(), [])

    def test_three_refusals_coexist_and_repairing_one_preserves_the_others(self):
        self.break_all()
        expected = {('relation', 'missing-responsibility'), ('configuration', 'orphan-key'),
                    ('compatibility', 'unproven-demand')}
        self.assertEqual({row[:2] for row in self.refusals()}, expected)
        self.relation['responsibility']['accepted'] = {'merge': [self.accepted]}
        self.write('scripts/lib/operation_relations.json', self.relation)
        self.assertEqual({row[:2] for row in self.refusals()}, expected - {('relation', 'missing-responsibility')})
        (self.root / 'config/registry/forge-events/demo.orphan.json').unlink()
        self.assertEqual({row[:2] for row in self.refusals()}, {('compatibility', 'unproven-demand')})
        self.demands['proofs']['origin']['merge'] = 'scripts/tests/proof.py::Proof::test_merge'
        self.declare_demands()
        self.assertEqual(self.refusals(), [])

    def test_conflict_does_not_hide_configuration_or_compatibility_refusals(self):
        self.break_all()
        other = dict(self.accepted, responsible='other-role', accepted_by='other-role')
        self.relation['responsibility']['accepted'] = {'merge': [self.accepted, other]}
        self.write('scripts/lib/operation_relations.json', self.relation)
        self.assertEqual({row[:2] for row in self.refusals()},
                         {('relation', 'conflicting-responsibility'), ('configuration', 'orphan-key'),
                          ('compatibility', 'unproven-demand')})

    def test_broken_declaration_does_not_short_circuit_other_checks(self):
        self.break_all()
        self.write('scripts/lib/operation_config_relations.json', '{broken')
        self.assertEqual({row[:2] for row in self.refusals()},
                         {('relation', 'missing-responsibility'), ('configuration', 'invalid-declaration'),
                          ('compatibility', 'unproven-demand')})

    def test_unknown_configuration_and_stale_reader_are_exposed_without_refusal(self):
        self.config['keys'][0].update(kind='unknown', operations=[], reason='Unknown boundary.')
        self.write('scripts/lib/operation_config_relations.json', self.config)
        self.write('scripts/lib/consumer.py', 'def run(port):\n    port.merge()\n')
        findings, refused = unit_check.operation_check(self.root, 'origin')
        self.assertEqual(refused, [])
        self.assertTrue({('configuration', 'unknown-key'), ('configuration', 'stale-consumer')}
                        <= {row[:2] for row in findings})

    def test_explicit_unknown_consumer_is_refused(self):
        _, refused = unit_check.operation_check(self.root, 'origin', ['undeclared.py'])
        self.assertEqual([row[:2] for row in refused], [('compatibility', 'unknown-consumer')])

    def test_cli_reports_all_refusals_and_returns_nonzero(self):
        self.break_all()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = unit_check.main(['--operations', '--root', str(self.root), '--adapter', 'origin'])
        self.assertEqual(code, 1)
        for kind in ('missing-responsibility', 'orphan-key', 'unproven-demand'):
            self.assertIn('REFUSE: ', output.getvalue())
            self.assertIn(kind, output.getvalue())
        self.assertIn('3 refusal(s)', output.getvalue())


if __name__ == '__main__':
    unittest.main()
