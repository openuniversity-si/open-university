"""Agent execution environments (AGENT-ENV, D-341): each declaration validates, keeps its secrets under its own prefix
and names nothing the engine never sends to a cloud agent; the deny list is the registry's.

Verifies: REQ-agent-env-single-source
"""
import copy
import json
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import agent_env  # noqa: E402
import config  # noqa: E402

STEM = 'sample'
BASE = {
    'id': STEM,
    'provider': 'claude-code',
    'variables': {'TOWER_MODE': 'cloud'},
    'secrets': [{'name': 'TOWER_SAMPLE_KEY', 'store': 'ssm', 'ref': f'/tower/agent-env/{STEM}/sample-key'}],
    'network': {'hosts': []},
    'starting_credential': {'kind': 'bearer-env', 'variable': 'TOWER_EVENTS_TOKEN'},
}


def a_vendor_name():
    """A variable name one retired vendor term matches, built from the registry so no vendor is named here."""
    term = re.sub(r'\(\?<?[!=][^)]*\)', '', config.get('structure.retired_vendor_terms')[0])
    return f'{term.upper()}_API_TOKEN'


class AgentEnvTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads((ROOT / agent_env.SCHEMA).read_text())
        self.patterns, self.terms = agent_env.denied_patterns(ROOT), agent_env.vendor_terms(ROOT)

    def errors(self, declaration):
        return agent_env.validate(declaration, STEM, self.schema, self.patterns, self.terms)

    def test_a_valid_declaration_passes(self):
        self.assertEqual(self.errors(BASE), [])

    def test_delivery_refuses_denied_names(self):
        for name in ('TEST_DATABASE_URL', 'R2_SECRET_ACCESS_KEY', 'AUTH_SECRET', 'OU_GOOGLE_CLIENT_SECRET',
                     'MUX_TOKEN_ID', 'FIGMA_TOKEN', 'SITE_BLOB_TOKEN', a_vendor_name()):
            as_variable = copy.deepcopy(BASE)
            as_variable['variables'][name] = 'x'
            as_secret = copy.deepcopy(BASE)
            as_secret['secrets'][0]['name'] = name
            for declaration in (as_variable, as_secret):
                with self.subTest(name=name):
                    self.assertTrue(any(error.startswith('denied:') and name in error
                                        for error in self.errors(declaration)), self.errors(declaration))
        self.assertIsNone(agent_env.refused('TOWER_EVENTS_TOKEN', self.patterns, self.terms))

    def test_schema_rejects_paths_outside_env_prefix(self):
        for store, ref in (('ssm', '/tower/agent-env/other/key'), ('ssm', 'tower/agent-env/sample/key'),
                           ('secretsmanager', '/tower/agent-env/sample/key'), ('secretsmanager', 'tower/torre-webhook-key'),
                           ('ssm', '/tower/agent-env/sample/')):
            declaration = copy.deepcopy(BASE)
            declaration['secrets'][0].update(store=store, ref=ref)
            with self.subTest(store=store, ref=ref):
                self.assertTrue(any(error.startswith('prefix:') for error in self.errors(declaration)))
        inside = copy.deepcopy(BASE)
        inside['secrets'][0].update(store='secretsmanager', ref=f'tower/agent-env/{STEM}/key')
        self.assertEqual(self.errors(inside), [])

    def test_an_unknown_provider_is_refused(self):
        declaration = dict(BASE, provider='unknown-provider')
        self.assertTrue(any(error.startswith('schema') and 'provider' in error for error in self.errors(declaration)))

    def test_a_host_that_is_not_an_exact_lowercase_name_is_refused(self):
        for host in ('*.example.com', 'API.example.com', 'Example.Com'):
            with self.subTest(host=host):
                self.assertTrue(self.errors(dict(BASE, network={'hosts': [host]})))

    def test_an_id_other_than_the_file_name_is_refused(self):
        self.assertTrue(self.errors(dict(BASE, id='another')))

    def test_the_repositorys_own_declarations_pass(self):
        self.assertTrue(agent_env.declarations(ROOT))
        self.assertEqual(agent_env.check(ROOT), [])

    def test_the_deny_list_read_is_the_registrys(self):
        owner = json.loads((ROOT / 'config/registry/agent-env/agent-env.denied_names.json').read_text())
        self.assertEqual(agent_env.denied_patterns(ROOT), owner['default'])
        self.assertEqual(agent_env.denied_patterns(ROOT), config.get('agent-env.denied_names'))


if __name__ == '__main__':
    unittest.main()
