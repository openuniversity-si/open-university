"""The engine vendor check (D-069 item 7): a vendor call from scripts/ outside its adapter fails. No network."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import json_schema  # noqa: E402
import source_facts  # noqa: E402
import vendor_check  # noqa: E402

VENDOR = {'name': 'acme', 'kind': 'forge', 'status': 'active', 'endpoints': ['api.acme.test'], 'clis': ['acme'],
          'modules': ['acme_api', '@acme/sdk'], 'adapters': ['scripts/lib/adapters/forge_acme.py'],
          'selectors': ['scripts/lib/forge_port.py'], 'baseline': [], 'note': 'fixture'}
CATALOG = {'description': 'fixture', 'vendors': [VENDOR]}


def vendor_url(name, suffix):
    catalog, _ = vendor_check.load(ROOT)
    vendor = next(v for v in catalog['vendors'] if v['name'] == name)
    return 'https://' + vendor['endpoints'][0] + suffix


def py(text):
    return vendor_check.python_calls(vendor_check.parse(textwrap.dedent(text)), VENDOR)


class Recognize(unittest.TestCase):
    def test_python_endpoint_cli_and_import(self):
        found = py('''
            """Talks to api.acme.test in prose only."""
            import acme_api
            from acme_api import rest
            URL = "https://api.acme.test/v1"
            run(["acme", "pr", "view"])
            # api.acme.test in a comment
            ''')
        self.assertEqual(sorted((how, token) for _, token, how in found),
                         [('cli', 'acme'), ('endpoint', 'api.acme.test'), ('module', 'acme_api'), ('module', 'acme_api')])

    def test_python_process_that_runs_a_module_file_is_a_call(self):
        # ORIGIN-FINISH R1: the subprocess form the shrink-only baseline did not see (six GitHub calls at 98cf1db5)
        found = py('''
            import subprocess
            import sys
            tool = Path(root) / 'scripts/lib/acme_api.py'
            subprocess.run([sys.executable, str(Path(root) / 'scripts' / 'lib' / 'acme_api.py'), 'api'])
            other = 'scripts/lib/not_acme_api.py'
            ''')
        self.assertEqual([(how, token) for _, token, how in found], [('module', 'acme_api')] * len({'tool', 'argv'}))
        self.assertEqual(len({line for line, _, _ in found}), len(found))  # the two lines that name it, not the third

    def test_python_that_starts_no_process_only_names_a_module_file(self):
        self.assertEqual(py('import ast\nADAPTERS = {"acme": "scripts/lib/acme_api.py"}\n'), [])

    def test_python_ordinary_code_is_not_a_call(self):
        self.assertEqual(py('TOOLS = ("acme", "node")\nname = "acme"\nimport acme_apis\n'), [])

    def test_shell_command_words_endpoints_and_module_files(self):
        text = textwrap.dedent('''
            # acme pr view (a comment)
            acme pr view 1
            sha="$(acme api repos/x --jq .sha)"
            if acme auth status; then :; fi
            python3 "$lib/acme_api.py" get
            curl https://api.acme.test/v1
            echo acmes; my-acme run
            ''')
        found = sorted((line, how) for line, _, how in vendor_check.text_calls(text, VENDOR, shell=True))
        self.assertEqual(found, [(3, 'cli'), (4, 'cli'), (5, 'cli'), (6, 'module'), (7, 'endpoint')])

    def test_javascript_imports_and_spawns(self):
        text = "import { Client } from '@acme/sdk';\nconst c = require('@acme/sdk');\nspawn('acme', ['x']);\n// '@acme/sdk'\n"
        found = sorted((line, how) for line, _, how in vendor_check.text_calls(text, VENDOR, shell=False))
        self.assertEqual(found, [(1, 'module'), (2, 'module'), (3, 'cli')])


class Judge(unittest.TestCase):
    def test_adapters_selectors_and_baseline(self):
        catalog = copy.deepcopy(CATALOG)
        catalog['vendors'][0]['baseline'] = ['scripts/old.py:acme_api', 'scripts/gone.py:acme']
        found = [('scripts/lib/adapters/forge_acme.py', 1, 'acme', 'api.acme.test', 'endpoint'),
                 ('scripts/lib/forge_port.py', 2, 'acme', 'acme_api', 'module'),
                 ('scripts/lib/forge_port.py', 3, 'acme', 'acme', 'cli'),
                 ('scripts/old.py', 4, 'acme', 'acme_api', 'module'),
                 ('scripts/new.py', 5, 'acme', 'api.acme.test', 'endpoint')]
        errors, warnings = vendor_check.judge(found, catalog)
        self.assertEqual(len(errors), 2)
        self.assertTrue(errors[0].startswith('scripts/lib/forge_port.py:3: cli call to acme'), errors[0])
        self.assertTrue(errors[1].startswith('scripts/new.py:5: endpoint call to acme'), errors[1])
        self.assertEqual(warnings, ['acme: baseline lists scripts/gone.py:acme, which no longer calls it; remove the site'])

    def test_a_forbidden_vendor_has_no_adapter_and_no_baseline(self):
        catalog = copy.deepcopy(CATALOG)
        catalog['vendors'][0].update(status='forbidden', adapters=[], selectors=[], baseline=['scripts/x.py:acme'])
        self.assertIn('forbidden', ' '.join(vendor_check.catalog_errors(ROOT, catalog)))


class Shrink(unittest.TestCase):
    def test_the_baseline_only_shrinks_against_a_base_catalog(self):
        before = copy.deepcopy(CATALOG)
        before['vendors'][0]['baseline'] = ['scripts/old.py:acme_api']
        now = copy.deepcopy(before)
        now['vendors'][0]['baseline'] = []
        self.assertEqual(vendor_check.shrink_errors(now, before, lambda path: 'import acme_api', 'scripts/lib/adapters'), [])
        now['vendors'][0]['baseline'] = ['scripts/old.py:acme_api', 'scripts/new.py:acme']
        errors = vendor_check.shrink_errors(now, before, lambda path: 'acme', 'scripts/lib/adapters')
        self.assertEqual(len(errors), 1)
        self.assertIn('baseline gains scripts/new.py:acme', errors[0])

    def test_first_catalog_lists_only_calls_the_base_had(self):
        now = copy.deepcopy(CATALOG)
        now['vendors'][0]['baseline'] = ['scripts/old.py:acme_api']
        self.assertEqual(vendor_check.shrink_errors(now, None, lambda path: 'import acme_api', 'scripts/lib/adapters'), [])
        self.assertEqual(len(vendor_check.shrink_errors(now, None, lambda path: None, 'scripts/lib/adapters')), 1)

    def test_first_registration_can_declare_existing_adapters_only(self):
        now = copy.deepcopy(CATALOG)
        now['vendors'][0]['adapters'] = ['scripts/lib/old_adapter.py']
        before = {'vendors': []}
        self.assertEqual(vendor_check.shrink_errors(now, before, lambda path: 'existing', 'scripts/lib/adapters'), [])
        errors = vendor_check.shrink_errors(now, before, lambda path: None, 'scripts/lib/adapters')
        self.assertEqual(len(errors), 1)
        self.assertIn('new adapter', errors[0])
        now['vendors'][0]['baseline'] = ['scripts/old.py:acme']
        errors = vendor_check.shrink_errors(now, before, lambda path: 'acme', 'scripts/lib/adapters')
        self.assertEqual(len(errors), 1)
        self.assertIn('baseline gains', errors[0])

    def test_a_new_adapter_lives_in_the_adapter_directory(self):
        before = copy.deepcopy(CATALOG)
        now = copy.deepcopy(CATALOG)
        now['vendors'][0]['adapters'].append('scripts/lib/anywhere.py')
        errors = vendor_check.shrink_errors(now, before, lambda path: '', 'scripts/lib/adapters')
        self.assertEqual(errors, ['acme: new adapter scripts/lib/anywhere.py is outside scripts/lib/adapters/ (D-069 item 7)'])


class Repository(unittest.TestCase):
    def test_the_catalog_satisfies_its_schema(self):
        catalog, errors = vendor_check.load(ROOT)
        self.assertEqual(errors, [])
        schema = json.loads((ROOT / config.get('providers.vendor_catalog_schema')).read_text())
        self.assertEqual(json_schema.check_schema(schema), [])
        names = {vendor['name']: vendor for vendor in catalog['vendors']}
        self.assertEqual(names['github-actions']['status'], 'forbidden')
        self.assertEqual({names[slot]['status'] for slot in ('codex', 'cursor')}, {'slot'})
        self.assertEqual(names['claude']['adapters'], ['scripts/lib/adapters/agent_claude.py', 'scripts/lib/adapters/launcher_claude.py'])

    def test_the_repository_is_green_today(self):
        self.assertEqual(vendor_check.check(ROOT), ([], []))

    def fixture_calls(self, source, suffix='.py', path=None):
        path = path or 'scripts/lib/caller' + suffix
        catalog, errors = vendor_check.load(ROOT)
        self.assertEqual(errors, [])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source)
            found = vendor_check.calls(tmp, [(path, suffix)], catalog)
        errors, _ = vendor_check.judge(found, catalog)
        return found, errors

    def test_origin_url_argv_and_shell_are_refused_once_as_origin(self):
        for source, suffix, how in [
                ('PROBE = ' + repr(vendor_url('origin', '/agents')), '.py', 'endpoint'),
                ('run(["origin", "api", "GET", "/v1/origin/agents"])', '.py', 'cli'),
                ('origin api GET /v1/origin/agents', '.sh', 'cli')]:
            with self.subTest(source=source):
                found, errors = self.fixture_calls(source, suffix)
                self.assertEqual([(name, how) for _, _, name, _, how in found], [('origin', how)])
                self.assertEqual(len(errors), 1)
                self.assertIn(how + ' call to origin', errors[0])

    def test_cursor_agent_host_and_cli_still_fail(self):
        for source, suffix in [('URL = ' + repr(vendor_url('cursor', '/v0/agents')), '.py'),
                               ('run(["cursor-agent", "run"])', '.py'),
                               ('cursor-agent run', '.sh')]:
            with self.subTest(source=source):
                found, errors = self.fixture_calls(source, suffix)
                self.assertEqual([name for _, _, name, _, _ in found], ['cursor'])
                self.assertEqual(len(errors), 1)
                self.assertIn('no adapter (slot)', errors[0])

    def test_endpoint_ownership_is_per_occurrence_and_catalog_order_independent(self):
        source = 'URL = ' + repr(vendor_url('origin', '/agents') + ' ' + vendor_url('cursor', '/v0/agents'))
        for suffix in ('.py', '.sh'):
            found, errors = self.fixture_calls(source, suffix)
            self.assertEqual(sorted(name for _, _, name, _, _ in found), ['cursor', 'origin'])
            self.assertEqual(len(errors), len(('cursor', 'origin')))
        catalog, _ = vendor_check.load(ROOT)
        catalog['vendors'].reverse()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'caller.py'
            target.write_text('URL = ' + repr(vendor_url('origin', '/agents')))
            found = vendor_check.calls(tmp, [('caller.py', '.py')], catalog)
        self.assertEqual([name for _, _, name, _, _ in found], ['origin'])
        found, errors = self.fixture_calls('URL = ' + repr(vendor_url('github', '/repos')))
        self.assertEqual([name for _, _, name, _, _ in found], ['github', 'github'])
        self.assertEqual(len(errors), len(found))  # Same-vendor overlapping tokens keep their behavior.

    def test_origin_modules_and_adapters_and_selector_permissions(self):
        catalog, _ = vendor_check.load(ROOT)
        origin = next(v for v in catalog['vendors'] if v['name'] == 'origin')
        self.assertEqual(origin['status'], 'active')
        self.assertEqual(origin['baseline'], [])
        self.assertEqual(origin['adapters'], ['scripts/lib/forge_origin.py', 'scripts/lib/forge_origin_client.py'])
        source = ('import forge_origin\nimport forge_origin_client\n'
                  'URL = ' + repr(vendor_url('origin', '/agents')) + '\n' +
                  'run(["origin", "api", "GET", "/v1/origin/agents"])\n')
        for path in origin['adapters']:
            found, errors = self.fixture_calls(source, path=path)
            self.assertEqual(sorted(how for _, _, _, _, how in found), ['cli', 'endpoint', 'module', 'module'])
            self.assertEqual(errors, [])
        _, errors = self.fixture_calls('import forge_origin_client')
        self.assertEqual(len(errors), 1)
        _, errors = self.fixture_calls(source, path='scripts/lib/forge_events.py')
        self.assertEqual(len(errors), len(('endpoint', 'cli')))  # Selector permits imports, never endpoint or CLI calls.
        found = vendor_check.calls(ROOT, [(p, '.py') for p in origin['adapters']], catalog)
        self.assertEqual(vendor_check.judge(found, {'vendors': [origin]}), ([], []))

    def test_a_new_call_outside_its_adapter_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'scripts' / 'lib' / 'caller.py'
            target.parent.mkdir(parents=True)
            target.write_text('import subprocess\nsubprocess.run(["claude", "--print"])\n')
            catalog, _ = vendor_check.load(ROOT)
            errors, _ = vendor_check.judge(vendor_check.calls(tmp, [('scripts/lib/caller.py', '.py')], catalog), catalog)
        self.assertEqual(len(errors), 1)
        self.assertIn('cli call to claude (claude) outside its adapter (scripts/lib/adapters/agent_claude.py, scripts/lib/adapters/launcher_claude.py)', errors[0])


class FactCache(unittest.TestCase):
    """F31: each Python file's facts are kept by content (source_facts) and the catalog is applied live, so the calls
    are the uncached ones whatever the cache holds."""
    CALLER = textwrap.dedent('''
        """Talks to api.acme.test in prose only."""
        import subprocess
        import acme_api
        URL = "{url}"
        subprocess.run(["acme", "pr", "view"])
        subprocess.run([b"acme", None, 'scripts/lib/acme_api.py'])
        ''').format(url='https://' + VENDOR['endpoints'][0] + '/v1')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'checkout'
        self.cache = Path(self.tmp.name) / 'cache'
        patched = mock.patch.dict('os.environ', {source_facts.ENV: str(self.cache)})
        patched.start()
        self.addCleanup(patched.stop)
        self.write(self.CALLER)

    def write(self, text):
        target = self.root / 'scripts/lib/caller.py'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def calls(self, extracted, catalog=CATALOG):
        """The calls of the fixture, asserting how many files were extracted rather than read from the cache."""
        with mock.patch.object(vendor_check, 'python_facts', wraps=vendor_check.python_facts) as extract:
            found = vendor_check.calls(self.root, [('scripts/lib/caller.py', '.py')], catalog)
        self.assertEqual(extract.call_count, extracted)
        return found

    def test_cold_warm_and_uncached_give_the_parsed_calls(self):
        parsed = [('scripts/lib/caller.py', line, 'acme', token, how)
                  for line, token, how in sorted(set(py(self.CALLER)))]
        self.assertEqual(self.calls(extracted=1), parsed)
        self.assertEqual(self.calls(extracted=0), parsed)
        with mock.patch.dict('os.environ', {source_facts.ENV: ''}):
            self.assertEqual(self.calls(extracted=1), parsed)

    def test_a_changed_file_is_extracted_again(self):
        def modules(found):
            return [line for _, line, _, token, how in found if how == 'module']
        before = modules(self.calls(extracted=1))
        self.write(self.CALLER.replace('import acme_api\n', ''))
        after = modules(self.calls(extracted=1))
        self.assertEqual(len(after), len(before) - 1)  # the import is gone; the module file the process runs stays
        self.assertEqual(modules(self.calls(extracted=0)), after)

    def test_a_catalog_change_is_judged_on_cached_facts(self):
        self.calls(extracted=1)
        renamed = {**VENDOR, 'clis': ['subprocess'], 'endpoints': ['acme.test/v1'], 'modules': []}
        found = self.calls(extracted=0, catalog={'vendors': [renamed]})
        self.assertEqual(sorted({how for *_, how in found}), ['endpoint'])

    def test_a_corrupt_entry_or_a_new_extractor_is_extracted_again(self):
        expected = self.calls(extracted=1)
        for entry in (path for path in self.cache.rglob('*') if path.is_file()):
            entry.write_text('[[["one", "acme"]], [], [[1, null]]]')
        self.assertEqual(self.calls(extracted=1), expected)
        self.assertEqual(self.calls(extracted=0), expected)  # the entry was rewritten
        with mock.patch.object(source_facts, 'digest', return_value='another extractor'):
            self.assertEqual(self.calls(extracted=1), expected)


if __name__ == '__main__':
    unittest.main(verbosity=1)
