"""The observed relation of the engine's forge operations (D-285, C2; ARQ-OPERATIONS R1 A2): the declaration reads, the
confrontation with the tree exposes an undeclared operation, a stale site, a consumer no unit owns and an implementation
that does not define what the declaration claims, and implementation is never read as responsibility.

Fixture trees in a temporary directory: a port that dispatches through `_operation` and one direct `adapter.change`, a
consumer per case, and one unit manifest, so a file outside it is an unknown unit instead of a guess. No network, no clock.
"""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import operation_relations  # noqa: E402
import units  # noqa: E402

COPIED = ('config/registry/config.json', 'config/registry/units.json', 'contracts/units/unit.v1.json',
          'docs/domain/DECISIONS.md')
OWNER = 'engine-lane'
PORT = '''
class ForgeEvents:
    """A port of the fixture."""

    def lock(self, name):
        return self._operation('lock')(name)

    def merge(self, name):
        return self._operation('merge')(name)

    def change(self, **fields):
        return self.adapter.change(**fields)

    def _operation(self, name):
        return getattr(self.adapter, name)
'''
ADAPTER = '''
class OriginAdapter:
    def lock(self, name):
        return name
'''
CONSUMER = '''
def run(port):
    return port.lock('a') and port.change(fields=[])
'''


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        for name in COPIED:
            (self.base / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.base / name)
        self.unit('consumer-a', ['scripts/lib/consumer.py'])
        self.write('scripts/lib/forge_events.py', PORT)
        self.write('scripts/lib/forge_origin.py', ADAPTER)
        self.write('scripts/lib/consumer.py', CONSUMER)
        units.reset()

    def tearDown(self):
        units.reset()
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.base / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text if isinstance(text, str) else json.dumps(text), encoding='utf-8')
        return path

    def unit(self, name, paths):
        self.write(f'units/{name}/unit.json', {'id': name, 'purpose': f'The {name} unit.', 'cell': 'engine',
                                               'owner': OWNER, 'paths': paths})

    def declare(self, operations, **extra):
        document = {'version': 1, 'operations': operations}
        document.update(extra)
        self.write('scripts/lib/operation_relations.json', document)
        return document

    def matching(self, names=None):
        """The declaration this fixture's own tree spells: every measured site, responsible unknown. The tests below
        break one piece of it at a time, so a finding they expect is the piece they broke."""
        tree = operation_relations.measured(self.base)
        surface = operation_relations.surface(self.base)
        rows = []
        for name in (surface if names is None else names):
            row = tree.get(name) or {'sites': [], 'consumers': []}
            rows.append({'name': name, 'dispatch': surface.get(name, 'operation'), 'responsible': 'unknown',
                         'consumers': row['consumers'],
                         'sites': [{key: site[key] for key in ('file', 'line', 'consumer', 'crossing')}
                                   for site in row['sites']]})
        self.declare(rows)
        return rows

    def kinds(self):
        return [kind for kind, _ in operation_relations.confront(self.base)]

    def findings(self):
        return dict(operation_relations.confront(self.base))

    def row(self, rows, name):
        return next(item for item in rows if item['name'] == name)


class SurfaceTest(Fixture):
    def test_a_dispatched_name_is_an_operation_and_the_direct_call_is_named_too(self):
        self.assertEqual(operation_relations.surface(self.base),
                         {'lock': 'operation', 'merge': 'operation', 'change': 'direct'})

    def test_a_private_method_is_not_part_of_the_surface(self):
        self.assertNotIn('_operation', operation_relations.surface(self.base))

    def test_the_reading_names_the_consumer_and_the_crossing(self):
        found = operation_relations.sites(self.base)
        self.assertEqual([(site['operation'], site['file'], site['consumer'], site['crossing']) for site in found],
                         [('change', 'scripts/lib/consumer.py', 'run', 'port'),
                          ('lock', 'scripts/lib/consumer.py', 'run', 'port')])

    def test_the_reading_points_at_the_line_the_call_is_on(self):
        source = (self.base / 'scripts/lib/consumer.py').read_text().splitlines()
        for site in operation_relations.sites(self.base):
            self.assertIn(f'.{site["operation"]}(', source[site['line'] - 1])

    def test_a_call_past_the_port_is_a_reach_through(self):
        self.write('scripts/lib/gate.py', 'def report(publisher):\n    return publisher.port.adapter.change([])\n')
        crossings = {site['crossing'] for site in operation_relations.sites(self.base)
                     if site['file'] == 'scripts/lib/gate.py'}
        self.assertEqual(crossings, {'reach-through'})

    def test_a_call_built_from_configuration_is_a_factory_crossing(self):
        self.write('scripts/lib/flow.py', 'def check(forge_events):\n'
                                           '    return forge_events.adapter_from_config().merge([])\n')
        crossings = {site['crossing'] for site in operation_relations.sites(self.base)
                     if site['file'] == 'scripts/lib/flow.py'}
        self.assertEqual(crossings, {'factory'})

    def test_the_adapter_modules_are_not_consumers_of_themselves(self):
        self.write('scripts/lib/forge_origin.py', ADAPTER + '\ndef helper(adapter):\n    return adapter.lock("a")\n')
        files = {site['file'] for site in operation_relations.sites(self.base)}
        self.assertNotIn('scripts/lib/forge_origin.py', files)

    def test_a_test_file_is_not_a_consumer(self):
        self.write('scripts/lib/tests/test_thing.py', 'def run(port):\n    return port.lock("a")\n')
        files = {site['file'] for site in operation_relations.sites(self.base)}
        self.assertFalse([name for name in files if '/tests/' in name])


class DeclarationTest(Fixture):
    def test_the_declaration_reads_by_operation_name(self):
        self.declare([{'name': 'lock'}, {'name': 'change'}])
        self.assertEqual(list(operation_relations.load(self.base)['operations']), ['lock', 'change'])

    def test_the_declaration_keeps_its_counters(self):
        self.declare([{'name': 'lock'}], census={'operations': 1})
        self.assertEqual(operation_relations.load(self.base)['census'], {'operations': 1})

    def test_a_declaration_without_operations_is_refused(self):
        self.declare([])
        with self.assertRaises(operation_relations.RelationError):
            operation_relations.load(self.base)

    def test_the_same_operation_twice_is_refused(self):
        self.declare([{'name': 'lock'}, {'name': 'lock'}])
        with self.assertRaises(operation_relations.RelationError):
            operation_relations.load(self.base)

    def test_an_operation_without_a_name_is_refused(self):
        self.declare([{'dispatch': 'operation'}])
        with self.assertRaises(operation_relations.RelationError):
            operation_relations.load(self.base)

    def test_a_missing_declaration_is_refused(self):
        with self.assertRaises(operation_relations.RelationError):
            operation_relations.load(self.base)

    def test_an_unreadable_port_is_refused(self):
        self.write('scripts/lib/forge_events.py', 'class ForgeEvents(:\n')
        with self.assertRaises(operation_relations.RelationError):
            operation_relations.surface(self.base)

    def test_a_port_without_the_class_is_refused(self):
        self.write('scripts/lib/forge_events.py', 'class Other:\n    pass\n')
        with self.assertRaises(operation_relations.RelationError):
            operation_relations.surface(self.base)


class ConfrontationTest(Fixture):
    def test_the_declaration_matching_the_tree_has_no_finding(self):
        self.matching()
        self.assertEqual(operation_relations.confront(self.base), [])

    def test_an_operation_the_port_dispatches_and_the_relation_omits_is_exposed(self):
        self.matching(['lock', 'change'])
        findings = self.findings()
        self.assertIn('undeclared-operation', findings)
        self.assertIn('merge', findings['undeclared-operation'])

    def test_an_operation_the_relation_declares_and_the_port_dropped_is_exposed(self):
        rows = self.matching() + [{'name': 'push', 'responsible': 'unknown', 'consumers': [], 'sites': []}]
        self.declare(rows)
        findings = self.findings()
        self.assertIn('stale-operation', findings)
        self.assertIn('push', findings['stale-operation'])

    def test_a_declared_site_the_tree_no_longer_calls_is_exposed(self):
        rows = self.matching()
        self.row(rows, 'lock')['sites'].append({'file': 'scripts/lib/gone.py', 'line': 1, 'consumer': 'run',
                                                'crossing': 'port'})
        self.declare(rows)
        findings = self.findings()
        self.assertIn('stale-site', findings)
        self.assertIn('scripts/lib/gone.py', findings['stale-site'])

    def test_a_call_whose_line_moved_is_not_a_finding(self):
        self.matching()
        self.write('scripts/lib/consumer.py', '# a line added above the calls\n\n' + CONSUMER)
        self.assertEqual(operation_relations.confront(self.base), [])

    def test_a_call_the_relation_omits_is_exposed_as_a_site(self):
        rows = self.matching()
        self.row(rows, 'lock')['sites'] = []
        self.declare(rows)
        self.assertIn('undeclared-site', self.kinds())

    def test_a_consumer_the_relation_omits_is_exposed(self):
        self.write('scripts/lib/other.py', 'def send(port):\n    return port.lock("b")\n')
        rows = self.matching()
        lock = self.row(rows, 'lock')
        lock['sites'] = [site for site in lock['sites'] if site['file'] != 'scripts/lib/other.py']
        lock['consumers'] = [name for name in lock['consumers'] if name != 'scripts/lib/other.py']
        self.declare(rows)
        findings = self.findings()
        self.assertIn('undeclared-consumer', findings)
        self.assertIn('scripts/lib/other.py', findings['undeclared-consumer'])

    def test_a_consumer_no_unit_owns_is_an_unknown_and_not_a_discarded_line(self):
        self.write('scripts/lib/unowned.py', 'def send(port):\n    return port.lock("b")\n')
        self.matching()
        self.assertIn('unowned-consumer', self.kinds())
        self.assertIn('scripts/lib/unowned.py', self.findings()['unowned-consumer'])
        self.assertNotIn('scripts/lib/consumer.py', self.findings()['unowned-consumer'])

    def test_a_consumer_the_unit_map_owns_is_not_an_unknown(self):
        self.matching()
        self.assertNotIn('unowned-consumer', self.kinds())

    def test_a_crossing_the_relation_misdeclares_is_exposed(self):
        rows = self.matching()
        self.row(rows, 'lock')['sites'][0]['crossing'] = 'reach-through'
        self.declare(rows)
        findings = self.findings()
        self.assertIn('crossing', findings)
        self.assertIn('port', findings['crossing'])

    def test_the_declared_census_is_confronted_with_the_tree(self):
        rows = self.matching()
        self.declare(rows, census={'operations': len(rows) + 1})
        findings = self.findings()
        self.assertIn('census-operations', findings)
        self.assertTrue(findings['census-operations'].endswith(f'spells {len(rows)}'))

    def test_a_census_the_tree_meets_has_no_finding(self):
        tree = operation_relations.measured(self.base)
        rows = self.matching()
        self.declare(rows, census={'operations': len(operation_relations.surface(self.base)),
                                   'sites': sum(len(row['sites']) for row in tree.values())})
        self.assertEqual(operation_relations.confront(self.base), [])

    def test_an_adapter_that_does_not_define_what_the_relation_claims_is_exposed(self):
        self.declare(self.matching(), adapters=[{'adapter': 'origin', 'implements': ['lock', 'merge'], 'missing': []}])
        findings = self.findings()
        self.assertIn('stale-implementation', findings)
        self.assertIn('merge', findings['stale-implementation'])

    def test_an_adapter_the_relation_names_as_missing_a_method_it_defines_is_exposed(self):
        self.declare(self.matching(), adapters=[{'adapter': 'origin', 'implements': ['lock'], 'missing': ['lock']}])
        self.assertIn('false-gap', self.kinds())

    def test_an_adapter_no_module_of_the_tree_holds_is_exposed(self):
        self.declare(self.matching(), adapters=[{'adapter': 'forge-of-nothing', 'implements': []}])
        self.assertIn('unknown-adapter', self.kinds())

    def test_the_adapters_of_the_tree_are_read_without_their_private_methods(self):
        self.assertEqual(operation_relations.adapters(self.base), {'origin': ['lock']})


class ResponsibilityTest(Fixture):
    def test_implementation_is_not_responsibility(self):
        self.declare(self.matching(), adapters=[{'adapter': 'origin', 'implements': ['lock'], 'missing': []}])
        self.assertEqual(operation_relations.confront(self.base), [])
        counts = operation_relations.status(operation_relations.load(self.base))
        self.assertEqual((counts['responsible'], counts['unknown']),
                         (0, len(operation_relations.load(self.base)['operations'])))

    def test_an_accepted_responsible_is_counted_and_absent_from_the_unknown(self):
        rows = self.matching()
        self.row(rows, 'lock')['responsible'] = OWNER
        self.declare(rows)
        counts = operation_relations.status(operation_relations.load(self.base))
        self.assertEqual(counts['responsible'], 1)
        self.assertEqual(sorted(counts['unknown_operations']), ['change', 'merge'])


class ReportTest(Fixture):
    def test_the_report_counts_the_declaration_and_prints_every_unknown(self):
        rows = self.matching()
        self.declare(rows, unknowns=[{'id': 'reach', 'what': 'textual reach only'}])
        text = operation_relations.report(self.base)
        self.assertIn(f'operations: {len(rows)}; responsible: 0; unknown: {len(rows)}', text)
        self.assertIn('unknown reach: textual reach only', text)
        self.assertIn('confrontation: 0 finding(s)', text)

    def test_the_report_prints_the_crossing_of_each_operation(self):
        self.matching()
        self.assertIn('crossing port', operation_relations.report(self.base))

    def test_the_command_prints_the_relation_and_leaves_with_zero(self):
        rows = self.matching()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(operation_relations.main(['--root', str(self.base)]), 0)
        self.assertIn(f'operations: {len(rows)}', out.getvalue())

    def test_a_declaration_that_cannot_be_read_leaves_with_one_and_says_why(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(operation_relations.main(['--root', str(self.base)]), 1)
        self.assertIn('cannot read the operation relation', err.getvalue())


class TreeTest(unittest.TestCase):
    """This checkout: the declaration agrees with the tree it describes, and records its declared responsible."""

    def test_the_declaration_of_this_checkout_has_no_finding(self):
        self.assertEqual(operation_relations.confront(ROOT), [])

    def test_every_operation_of_this_checkout_declares_engine_lane_responsibility(self):
        document = operation_relations.load(ROOT)
        counts = operation_relations.status(document)
        self.assertEqual(counts['responsible'], counts['operations'])
        self.assertEqual(counts['unknown'], 0)
        self.assertEqual({row['responsible'] for row in document['operations'].values()}, {'engine-lane'})
        self.assertEqual(counts['operations'], len(document['operations']))

    def test_the_declared_surface_is_the_port_dispatch_plus_the_direct_change(self):
        declared = set(operation_relations.load(ROOT)['operations'])
        self.assertEqual(declared, set(operation_relations.surface(ROOT)))

    def test_the_declared_engine_names_are_operations_of_the_relation(self):
        document = operation_relations.load(ROOT)
        self.assertTrue(set(document['engine']['names']) <= set(document['operations']))

    def test_the_unknowns_the_relation_carries_are_declared_with_an_id_and_what(self):
        unknowns = operation_relations.load(ROOT)['unknowns']
        self.assertTrue(unknowns)
        for item in unknowns:
            self.assertTrue(item['id'])
            self.assertTrue(item['what'])


if __name__ == '__main__':
    unittest.main()
