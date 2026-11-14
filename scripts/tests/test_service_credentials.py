"""Which runner holds which secret (D-291 (5), TRAIN-DEFINITIVE R6): the inventory service.token_holders, a missing
variable named with what it must equal and where it is held, a refused token named as the rotated secret. No value is
ever read or printed. Numbers come from HTTPStatus or from 1 (the literal census of a new unit allows no other)."""
from http import HTTPStatus
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1].parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))

import config  # noqa: E402
import service_credentials  # noqa: E402

KINDS = ('box', 'vm', 'actions', 'session', 'other')  # contracts/service/api.v1.json runner.kind
VALUE = 'value-that-must-never-be-printed'


def full(entries, kind):
    """An environment that holds every variable `kind` needs."""
    return {item['variable']: VALUE for item in entries if kind in item['kinds']}


class Inventory(unittest.TestCase):
    def setUp(self):
        self.entries = service_credentials.entries()

    def test_every_secret_the_engine_reads_is_in_the_inventory_by_the_name_the_engine_reads(self):
        names = {item['variable'] for item in self.entries}
        self.assertIn(config.get('service.runner_token_env'), names)
        self.assertIn(config.get('forge-events.control_token_env'), names)
        self.assertIn(config.get('service.deploy_token_env'), names)
        self.assertIn('GH_TOKEN', names)
        self.assertIn('GITHUB_TOKEN', service_credentials.entry('GH_TOKEN')['aliases'])

    def test_each_entry_says_what_it_equals_who_needs_it_where_it_is_held_and_what_for(self):
        for item in self.entries:
            for field in ('equals', 'holder', 'used_for'):
                self.assertTrue(item[field].strip(), (item['variable'], field))
            self.assertTrue(set(item['kinds']) <= set(KINDS), item['variable'])
        runner = service_credentials.entry(config.get('service.runner_token_env'))
        self.assertIn('RUNNER_TOKEN', runner['equals'])
        self.assertIn('tower/runner.env', runner['holder'])
        events = service_credentials.entry(config.get('forge-events.control_token_env'))
        self.assertIn('EVENTS_TOKEN', events['equals'])

    def test_only_a_vm_needs_the_deploy_token(self):
        self.assertEqual(service_credentials.entry(config.get('service.deploy_token_env'))['kinds'], ['vm'])

    def test_the_unit_reads_the_holder_the_inventory_names(self):
        unit = (ROOT / 'services' / 'runner' / 'tower-runner.service.tmpl').read_text()
        line = next(line for line in unit.splitlines() if line.startswith('EnvironmentFile='))
        self.assertNotIn('=-', line)  # a missing secrets file stops the unit loudly (F18)
        path = line.split('%h/', 1)[1]
        for item in self.entries:
            self.assertIn(path, item['holder'], item['variable'])

    def test_the_inventory_lines_name_every_variable(self):
        lines = service_credentials.inventory_lines()
        self.assertEqual(len(lines), len(self.entries))
        for item, line in zip(self.entries, lines):
            self.assertTrue(line.startswith(item['variable']), line)
            self.assertIn(item['holder'], line)


class Missing(unittest.TestCase):
    def setUp(self):
        self.entries = service_credentials.entries()

    def test_nothing_is_missing_from_a_full_environment(self):
        for kind in KINDS:
            self.assertEqual(service_credentials.missing(full(self.entries, kind), kind), [], kind)

    def test_one_sentence_per_absent_variable_naming_what_it_must_equal_and_its_holder(self):
        variable = config.get('service.runner_token_env')
        environ = full(self.entries, 'vm')
        del environ[variable]
        sentences = service_credentials.missing(environ, 'vm')
        self.assertEqual(len(sentences), 1)
        item = service_credentials.entry(variable)
        for part in (variable, item['equals'], item['holder']):
            self.assertIn(part, sentences[0])
        self.assertNotIn(VALUE, sentences[0])

    def test_an_empty_value_is_absent_and_an_alias_counts(self):
        environ = full(self.entries, 'vm')
        environ['GH_TOKEN'] = ''
        self.assertEqual(len(service_credentials.missing(environ, 'vm')), 1)
        environ['GITHUB_TOKEN'] = VALUE
        self.assertEqual(service_credentials.missing(environ, 'vm'), [])

    def test_a_kind_is_judged_on_its_own_entries_only(self):
        deploy = config.get('service.deploy_token_env')
        box = full(self.entries, 'box')
        self.assertNotIn(deploy, box)
        self.assertEqual(service_credentials.missing(box, 'box'), [])
        self.assertTrue(any(deploy in sentence for sentence in service_credentials.missing(box, 'vm')))

    def test_injected_entries_replace_the_registry(self):
        entries = [{'variable': 'ONLY_ONE', 'equals': 'a thing', 'kinds': ['vm'], 'holder': 'a file', 'used_for': 'x'}]
        self.assertEqual(len(service_credentials.missing({}, 'vm', entries)), 1)
        self.assertEqual(service_credentials.missing({}, 'box', entries), [])


class Refused(unittest.TestCase):
    def test_a_refused_runner_token_is_reported_as_the_rotated_worker_secret(self):
        variable = config.get('service.runner_token_env')
        item = service_credentials.entry(variable)
        sentence = service_credentials.refused_sentence(variable, HTTPStatus.UNAUTHORIZED.value)
        for part in ('the control plane refused', variable, f'({HTTPStatus.UNAUTHORIZED.value})', 'RUNNER_TOKEN',
                     'rotated', item['holder'], 'restart the runner'):
            self.assertIn(part, sentence)

    def test_another_refuser_and_an_unknown_variable(self):
        sentence = service_credentials.refused_sentence('GITHUB_TOKEN', HTTPStatus.FORBIDDEN.value, by='GitHub')
        self.assertTrue(sentence.startswith('GitHub refused GITHUB_TOKEN'))
        self.assertIn('fine-grained', sentence)
        unknown = service_credentials.refused_sentence('NOT_LISTED', HTTPStatus.UNAUTHORIZED.value)
        self.assertIn('not in the inventory service.token_holders', unknown)


class Main(unittest.TestCase):
    def test_main_prints_the_inventory_and_fails_on_a_missing_variable_without_a_value(self):
        entries = service_credentials.entries()
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(service_credentials.main([], environ={}), 0)
        self.assertEqual(len(out.getvalue().splitlines()), len(entries))
        with mock.patch('sys.stdout', new_callable=io.StringIO), \
                mock.patch('sys.stderr', new_callable=io.StringIO) as err:
            self.assertEqual(service_credentials.main(['--kind', 'vm'], environ=full(entries, 'vm')), 0)
            self.assertEqual(service_credentials.main(['--kind', 'vm'], environ={}), 1)
        self.assertIn('missing:', err.getvalue())
        self.assertNotIn(VALUE, err.getvalue())


if __name__ == '__main__':
    unittest.main()
