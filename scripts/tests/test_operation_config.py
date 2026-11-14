"""Independent local oracles for configuration boundaries (D-285 R4 A2)."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import operation_config as relation


class Fixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write('scripts/lib/operation_relations.json', {'operations': [{'name': 'pull'}, {'name': 'merge'}]})
        self.write('config/registry/forge-events/_owner.json', {})
        self.key('demo.limit')
        source = self.root / 'scripts/lib/consumer.py'
        source.write_text("config.get('demo.limit')\n")
        self.row = {'name': 'demo.limit', 'kind': 'operation', 'operations': ['pull'],
                    'consumers': ['scripts/lib/consumer.py'], 'reason': 'Bounds the pull request.'}
        self.declare([self.row])

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    def key(self, name):
        self.write(f'config/registry/forge-events/{name}.json', {'x-readers': ['scripts/lib/consumer.py']})

    def declare(self, rows):
        self.write(relation.DECLARATION, {'keys': rows})

    def kinds(self):
        return [kind for kind, _ in relation.confront(self.root)]

    def test_independent_registry_orphan_is_rejected_as_a_finding(self):
        self.assertEqual(self.kinds(), [])
        self.key('demo.orphan')
        self.assertEqual(self.kinds(), ['orphan-key'])
        self.assertEqual(relation.status(self.root)['orphans'], 1)
        # C4 exposes; C5 closes the flow. The observational CLI succeeds.
        from contextlib import redirect_stdout
        import io
        with redirect_stdout(io.StringIO()):
            self.assertEqual(relation.main(['--root', str(self.root)]), 0)

    def test_sharing_requires_explicit_declaration(self):
        self.row['operations'] = ['pull', 'merge']
        self.declare([self.row])
        self.assertEqual(self.kinds(), ['implicit-sharing'])
        self.row['shared'] = True
        self.declare([self.row])
        self.assertEqual(self.kinds(), [])
        self.assertEqual(relation.status(self.root)['shared'], 1)

    def test_selection_is_separate_from_operational_configuration(self):
        rows = [self.row]
        for suffix in ('adapter', 'log_adapter'):
            name = 'forge-events.' + suffix
            self.key(name)
            with (self.root / 'scripts/lib/consumer.py').open('a') as stream:
                stream.write(f'config.get({name!r})\n')
            rows.append({'name': name, 'kind': 'selection', 'operations': [],
                         'consumers': ['scripts/lib/consumer.py'], 'reason': 'Selects the forge, not an operation.'})
        self.declare(rows)
        self.assertEqual(self.kinds(), [])
        self.assertEqual(relation.status(self.root)['operational'], 1)
        self.assertEqual(relation.status(self.root)['without_operation'], len(('adapter', 'log_adapter')))
        rows[-1]['operations'] = ['pull']
        self.declare(rows)
        self.assertIn('kind-conflict', self.kinds())

    def test_missing_key_reader_drift_and_stale_source_are_exposed(self):
        self.write('config/registry/forge-events/demo.limit.json', {'x-readers': ['scripts/lib/other.py']})
        self.assertEqual(self.kinds(), ['readers'])
        (self.root / 'scripts/lib/consumer.py').write_text('pass\n')
        self.assertIn('stale-consumer', self.kinds())
        (self.root / 'config/registry/forge-events/demo.limit.json').unlink()
        self.assertEqual(self.kinds(), ['stale-key'])

    def test_unknown_and_unowned_operational_key_remain_visible(self):
        self.row.update(kind='unknown', operations=[], reason='No proven operational use.')
        self.declare([self.row])
        self.assertEqual(self.kinds(), ['unknown-key'])
        self.row['kind'] = 'operation'
        self.declare([self.row])
        self.assertEqual(self.kinds(), ['orphan-key'])
        self.row['operations'] = ['unproven']
        self.declare([self.row])
        self.assertEqual(self.kinds(), ['unknown-operation'])

    def test_literal_read_not_declared_is_exposed(self):
        (self.root / 'scripts/lib/other.py').write_text("config.get('demo.limit')\n")
        self.assertEqual(self.kinds(), ['undeclared-consumer'])

    def test_invalid_and_duplicate_rows_are_not_silently_overwritten(self):
        self.declare([self.row, self.row])
        with self.assertRaises(relation.RelationError):
            relation.load(self.root)
        self.row['kind'] = 'invented'
        self.declare([self.row])
        with self.assertRaises(relation.RelationError):
            relation.load(self.root)


class Repository(unittest.TestCase):
    def test_measured_census_is_complete_and_fully_classified(self):
        """D-289: the 17 forge-events.origin_* keys had no reader left and left the registry with the rule that used to
        demand a deprecated revision first, so the census a reader sees is the whole census, with nothing unknown."""
        counts = relation.status(ROOT)
        registry_keys = {path.stem for path in (ROOT / 'config/registry/forge-events').glob('*.json')
                         if path.name != '_owner.json'}
        self.assertEqual(counts['keys'], len(registry_keys))
        self.assertEqual(counts['covered'], len(registry_keys))
        self.assertEqual(counts['orphans'], 0)
        expected_shared = {'forge-events.' + name for name in
                           ('repo',)}
        findings = relation.confront(ROOT)
        self.assertEqual(findings, [])
        self.assertEqual(counts['unknown'], 0)
        retired = {'forge-events.origin_' + name for name in (
            'api_base', 'app_audience', 'app_id', 'app_id_env', 'app_jwt_ttl_s', 'app_key_path',
            'app_key_path_env', 'branch_prefix', 'installation_id', 'installation_id_env',
            'installation_prefix', 'repo', 'timeout_s', 'token_env', 'token_margin_s',
            'token_scopes', 'user_agent')}
        self.assertEqual(retired & (registry_keys | set(relation.load(ROOT)['keys'])), set())
        # the three keys the origin client still reads stay, and they keep their declared boundary
        kept = {'forge-events.origin_status_map', 'forge-events.origin_check_suite_key',
                'forge-events.origin_check_suite_name'}
        self.assertEqual((retired | kept) & registry_keys, kept)
        rows = relation.load(ROOT)['keys']
        self.assertEqual({name for name, row in rows.items() if row.get('shared') is True}, expected_shared)
        for suffix in ('adapter', 'log_adapter'):
            self.assertEqual(rows['forge-events.' + suffix]['kind'], 'selection')
        self.assertEqual(rows['forge-events.clock']['operations'], ['lock'])
        self.assertEqual(rows['forge-events.control_token_env']['kind'], 'adjacent')


if __name__ == '__main__':
    unittest.main()
