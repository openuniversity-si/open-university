"""Registry thresholds only tighten (TH1, D-069 item 14): each refusal and each allowed case of the threshold check, and
its structure-check wiring. Fixture registries in a temporary git repository; no network, no clock, no random source.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import threshold_check  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

REGISTRY = 'config/registry/demo.json'
DECISIONS = '| ID | When | Decision |\n|---|---|---|\n| D-069 | x | thresholds |\n'


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True,
                          capture_output=True, text=True).stdout


def parameter(default, **extra):
    return {'type': 'integer', 'default': default, 'x-unit': 'ms', 'description': 'd', 'x-readers': ['x.py'], **extra}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        fixture_copy.registry(self.dir)
        (self.dir / 'docs/domain').mkdir(parents=True)
        (self.dir / 'docs/domain/DECISIONS.md').write_text(DECISIONS)
        git(self.dir, 'init', '-q')
        self.params({'demo.run_timeout_ms': parameter(1000), 'demo.retry_budget': parameter(3),
                     'demo.coverage_floor': parameter(80, **{'x-monotonic': 'min'}), 'demo.batch_size': parameter(8),
                     'demo.name_limit': {**parameter(1), 'type': 'string', 'default': 'a'}})
        self.base = self.commit('base')

    def params(self, properties):
        path = self.dir / REGISTRY
        data = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': REGISTRY, 'x-owner': 'demo',
                'x-schema-version': 1, 'type': 'object', 'additionalProperties': False, 'properties': properties}
        path.write_text(json.dumps(data, indent=2) + '\n')

    def edit(self, name, value):
        path = self.dir / REGISTRY
        data = json.loads(path.read_text())
        data['properties'][name]['default'] = value
        path.write_text(json.dumps(data, indent=2) + '\n')

    def commit(self, message):
        git(self.dir, 'add', '-A')
        git(self.dir, 'commit', '-q', '-m', message)
        return git(self.dir, 'rev-parse', 'HEAD').strip()

    def errors(self, body='', message='change'):
        self.commit(message)
        return threshold_check.check(self.dir, self.base, body, threshold_check.messages(self.dir, self.base))


class Refusals(Fixture):
    def test_a_raised_timeout_fails(self):
        self.edit('demo.run_timeout_ms', 2000)
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn('demo.run_timeout_ms raises the ceiling 1000 -> 2000', errors[0])

    def test_a_raised_budget_fails(self):
        self.edit('demo.retry_budget', 4)
        self.assertIn('demo.retry_budget', self.errors()[0])

    def test_a_lowered_floor_fails(self):
        self.edit('demo.coverage_floor', 70)
        self.assertIn('lowers the floor 80 -> 70', self.errors()[0])

    def test_a_citation_in_the_body_only_fails(self):
        self.edit('demo.run_timeout_ms', 2000)
        self.assertTrue(self.errors(body='Loosens: demo.run_timeout_ms D-069'))

    def test_a_citation_in_a_commit_only_fails(self):
        self.edit('demo.run_timeout_ms', 2000)
        self.assertTrue(self.errors(message='raise\n\nLoosens: demo.run_timeout_ms D-069'))

    def test_an_unrecorded_decision_does_not_authorize(self):
        self.edit('demo.run_timeout_ms', 2000)
        line = 'Loosens: demo.run_timeout_ms D-999'
        self.assertTrue(self.errors(body=line, message=f'raise\n\n{line}'))

    def test_a_citation_of_another_name_does_not_authorize(self):
        self.edit('demo.run_timeout_ms', 2000)
        line = 'Loosens: demo.retry_budget D-069'
        self.assertTrue(self.errors(body=line, message=f'raise\n\n{line}'))

    def test_flipping_the_direction_does_not_hide_a_loosening(self):
        path = self.dir / REGISTRY
        data = json.loads(path.read_text())
        data['properties']['demo.coverage_floor'].update({'default': 70, 'x-monotonic': 'max'})
        path.write_text(json.dumps(data))
        self.assertIn('lowers the floor', self.errors()[0])

    def test_dropping_a_pattern_fails(self):
        path = self.dir / 'config/registry/config.json'
        data = json.loads(path.read_text())
        data['properties']['config.monotonic_patterns']['default'].remove('*_budget*')
        path.write_text(json.dumps(data))
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn('config.monotonic_patterns drops the pattern(s) *_budget*', errors[0])


class Allowed(Fixture):
    def test_tightening_passes(self):
        self.edit('demo.run_timeout_ms', 500)
        self.edit('demo.coverage_floor', 90)
        self.assertEqual(self.errors(), [])

    def test_an_unmatched_name_is_not_judged(self):
        self.edit('demo.batch_size', 80)
        self.assertEqual(self.errors(), [])

    def test_a_non_numeric_default_is_not_judged(self):
        self.edit('demo.name_limit', 'zzz')
        self.assertEqual(self.errors(), [])

    def test_a_new_key_passes(self):
        path = self.dir / REGISTRY
        data = json.loads(path.read_text())
        data['properties']['demo.wait_timeout_s'] = parameter(9999)
        path.write_text(json.dumps(data))
        self.assertEqual(self.errors(), [])

    def test_a_cited_decision_in_body_and_commit_passes(self):
        self.edit('demo.run_timeout_ms', 2000)
        line = 'Loosens: demo.run_timeout_ms D-069'
        self.assertEqual(self.errors(body=f'summary\n{line}\n', message=f'raise\n\n{line}'), [])

    def test_adding_a_pattern_passes(self):
        path = self.dir / 'config/registry/config.json'
        data = json.loads(path.read_text())
        data['properties']['config.monotonic_patterns']['default'].append('*_window*')
        path.write_text(json.dumps(data))
        self.assertEqual(self.errors(), [])

    def test_no_base_is_not_judged(self):
        self.edit('demo.run_timeout_ms', 2000)
        self.commit('raise')
        self.assertEqual(threshold_check.check(self.dir, None), [])


class Report(Fixture):
    def test_each_edited_default_is_one_config_changed_envelope(self):
        self.edit('demo.run_timeout_ms', 500)
        self.edit('demo.batch_size', 16)
        self.commit('edit')
        envelopes = threshold_check.report(self.dir, self.base, 598, 'Premises: P-41')
        self.assertEqual([(e['type'], e['payload']['name'], e['payload']['old'], e['payload']['new']) for e in envelopes],
                         [('config.changed', 'demo.batch_size', 8, 16), ('config.changed', 'demo.run_timeout_ms', 1000, 500)])
        payload = envelopes[0]['payload']
        self.assertEqual((payload['pr'], payload['premises'], payload['actor']), (598, ['P-41'], 't'))
        self.assertEqual(payload['reason'], threshold_check.REASON)
        self.assertEqual(envelopes[0]['producer'], threshold_check.PRODUCER)

    def test_a_loosening_is_reported_and_refused_apart(self):
        self.edit('demo.run_timeout_ms', 2000)
        self.assertTrue(self.errors())
        self.assertEqual(len(threshold_check.report(self.dir, self.base)), 1)

    def test_no_edit_reports_nothing(self):
        path = self.dir / REGISTRY
        data = json.loads(path.read_text())
        data['properties']['demo.wait_timeout_s'] = parameter(5)
        path.write_text(json.dumps(data))
        self.commit('add')
        self.assertEqual(threshold_check.report(self.dir, self.base), [])


class Wiring(unittest.TestCase):
    def test_structure_check_runs_the_module_with_a_base(self):
        text = (ROOT / 'scripts/lib/structure.py').read_text()
        self.assertIn('threshold_check.check(root, args.base', text)
        self.assertIn("print('EVENT ' + json.dumps(envelope", text)


if __name__ == '__main__':
    unittest.main()
