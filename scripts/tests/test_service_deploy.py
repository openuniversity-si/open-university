"""The control-plane deploy (D-291 (6), TRAIN-DEFINITIVE F16, R5): the Worker uploaded through the Cloudflare REST API,
no npx, no wrangler. A temporary checkout holds a wrangler.toml and two modules; a fake opener is the API. The token
is sent as a header and never printed. Numbers come from HTTPStatus, the registry or 1 (the literal census of a new
unit allows no other)."""
from email import message_from_bytes
from email.policy import HTTP
from http import HTTPStatus
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

ROOT = Path(__file__).resolve().parents[1].parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))

import config  # noqa: E402
import service_deploy  # noqa: E402

TOKEN = 'cf-token-that-must-never-be-printed'
VARIABLE = config.get('service.deploy_token_env')
WRANGLER = '''name = "forge-test"
main = "src/index.js"
compatibility_date = "2026-10-01"
account_id = "test-account"
workers_dev = true

[observability]
enabled = true

[[durable_objects.bindings]]
name = "CONTROL"
class_name = "Control"

[[migrations]]
tag = "v1"
new_sqlite_classes = ["Control"]

[triggers]
crons = ["*/15 * * * *"]

[vars]
REPO = "openuniversity-si/open-university"
BASE_BRANCH = "mod/roadmap-integration"
'''
INDEX = b"import { handle } from './core.js';\nexport default { fetch: handle };\n"
CORE = b'export function handle() { return new Response("ok"); }\n'


def git(*args, cwd):
    return subprocess.run(['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args], cwd=cwd, input='',
                          capture_output=True, text=True, check=True).stdout.strip()


class Answer:
    """What urlopen returns: a context manager with a status and a body."""

    def __init__(self, status, body):
        self.status, self.body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


class Api:
    """The Cloudflare API as the deploy sees it: records every request and answers what it was told to."""

    def __init__(self, status=HTTPStatus.OK, answer=None, error=None):
        self.status, self.error, self.requests = status, error, []
        self.answer = {'success': True, 'errors': [], 'result': {}} if answer is None else answer

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if self.error:
            raise self.error
        body = json.dumps(self.answer).encode()
        if self.status >= HTTPStatus.BAD_REQUEST:
            raise urllib.error.HTTPError(request.full_url, self.status, 'refused', {}, io.BytesIO(body))
        return Answer(self.status, body)


class Fixture(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        plane = self.root / config.get('service.deploy_path')
        (plane / 'src').mkdir(parents=True)
        (plane / 'wrangler.toml').write_text(WRANGLER)
        (plane / 'src' / 'index.js').write_bytes(INDEX)
        (plane / 'src' / 'core.js').write_bytes(CORE)
        (plane / 'src' / 'notes.md').write_text('not a module')
        git('init', '-q', cwd=self.root)
        git('add', '-A', cwd=self.root)
        git('commit', '-q', '-m', 'control plane', cwd=self.root)
        self.tree = git('rev-parse', f'HEAD:{config.get("service.deploy_path")}', cwd=self.root)

    def parts(self, request):
        """The multipart body as {name: (filename, content type, bytes)}."""
        head = f'Content-Type: {request.get_header("Content-type")}\r\n\r\n'.encode()
        message = message_from_bytes(head + request.data, policy=HTTP)
        return {part.get_param('name', header='content-disposition'):
                (part.get_filename(), part.get_content_type(), part.get_payload(decode=True))
                for part in message.iter_parts()}


class Tree(Fixture):
    def test_the_tree_is_the_git_tree_of_the_control_plane_and_drift_compares_it(self):
        self.assertEqual(service_deploy.tree(self.root), self.tree)
        self.assertFalse(service_deploy.drift(self.root, self.tree))
        self.assertTrue(service_deploy.drift(self.root, None))
        self.assertTrue(service_deploy.drift(self.root, self.tree[::-1]))


class Request(Fixture):
    def test_the_upload_is_a_put_to_the_account_script_of_wrangler_toml_with_the_bearer(self):
        request = service_deploy.request(self.root, TOKEN)
        self.assertEqual(request.get_method(), 'PUT')
        self.assertEqual(request.full_url, config.get('service.deploy_api_url').rstrip('/')
                         + '/accounts/test-account/workers/scripts/forge-test')
        self.assertEqual(request.get_header('Authorization'), f'Bearer {TOKEN}')
        self.assertTrue(request.get_header('Content-type').startswith('multipart/form-data; boundary='))
        self.assertEqual(request.get_header('User-agent'), config.get('service.user_agent'))

    def test_the_metadata_keeps_the_secrets_records_the_tree_and_sends_no_migration_or_trigger(self):
        parts = self.parts(service_deploy.request(self.root, TOKEN))
        filename, kind, raw = parts['metadata']
        self.assertEqual(kind, 'application/json')
        metadata = json.loads(raw)
        self.assertEqual(metadata['main_module'], 'index.js')
        self.assertEqual(metadata['compatibility_date'], '2026-10-01')
        self.assertEqual(metadata['keep_bindings'], ['secret_text', 'secret_key'])
        self.assertEqual(metadata['observability'], {'enabled': True})
        bindings = {item['name']: item for item in metadata['bindings']}
        self.assertEqual(bindings['CONTROL'], {'type': 'durable_object_namespace', 'name': 'CONTROL',
                                               'class_name': 'Control'})
        self.assertEqual(bindings['REPO'], {'type': 'plain_text', 'name': 'REPO', 'text': 'openuniversity-si/open-university'})
        self.assertEqual(bindings['BASE_BRANCH']['text'], 'mod/roadmap-integration')
        self.assertEqual(bindings['DEPLOYED_TREE'], {'type': 'plain_text', 'name': 'DEPLOYED_TREE', 'text': self.tree})
        self.assertEqual(bindings['BUDGET_S'], {'type': 'plain_text', 'name': 'BUDGET_S',
                                                'text': f"{config.get('service.job_budget_s'):g}"})
        for absent in ('migrations', 'triggers', 'crons', 'schedules'):
            self.assertNotIn(absent, metadata)
        self.assertNotIn(TOKEN, raw.decode())

    def test_every_module_of_src_is_a_part_named_by_its_basename(self):
        parts = self.parts(service_deploy.request(self.root, TOKEN))
        self.assertEqual(sorted(parts), ['core.js', 'index.js', 'metadata'])
        self.assertEqual(parts['index.js'], ('index.js', 'application/javascript+module', INDEX))
        self.assertEqual(parts['core.js'], ('core.js', 'application/javascript+module', CORE))


class Deploy(Fixture):
    def test_without_the_token_it_refuses_naming_the_variable_and_the_inventory_and_calls_nothing(self):
        api = Api()
        ok, sentence = service_deploy.deploy(self.root, {}, opener=api)
        self.assertFalse(ok)
        self.assertIn(VARIABLE, sentence)
        self.assertIn('service.token_holders', sentence)
        self.assertIn('Workers Scripts:Edit', sentence)
        self.assertEqual(api.requests, [])

    def test_a_success_names_the_short_tree_and_the_worker_and_never_the_token(self):
        api = Api()
        ok, sentence = service_deploy.deploy(self.root, {VARIABLE: TOKEN}, opener=api)
        self.assertTrue(ok, sentence)
        shown = config.get('service.deploy_tree_chars')
        self.assertEqual(sentence, f'deployed {config.get("service.deploy_path")} tree {self.tree[:shown]} to '
                                   f'forge-test')
        self.assertEqual(len(api.requests), 1)
        request, timeout = api.requests[0]
        self.assertEqual(timeout, config.get('service.deploy_timeout_s'))
        self.assertEqual(request.get_header('Authorization'), f'Bearer {TOKEN}')
        self.assertNotIn(TOKEN, sentence)

    def test_the_deploy_fits_the_job_budget(self):
        self.assertLess(config.get('service.deploy_timeout_s'), config.get('service.job_budget_s'))

    def test_a_2xx_without_success_is_a_failure_with_the_first_error(self):
        api = Api(answer={'success': False, 'errors': [{'code': 'E1', 'message': 'bad module'}]})
        ok, sentence = service_deploy.deploy(self.root, {VARIABLE: TOKEN}, opener=api)
        self.assertFalse(ok)
        self.assertIn(f'answered {HTTPStatus.OK.value}', sentence)
        self.assertIn('bad module', sentence)

    def test_an_http_error_names_the_status_and_the_api_message_never_the_token(self):
        api = Api(status=HTTPStatus.BAD_REQUEST, answer={'success': False, 'errors': [
            {'code': 'E2', 'message': f'no such class (sent {TOKEN})'}]})
        ok, sentence = service_deploy.deploy(self.root, {VARIABLE: TOKEN}, opener=api)
        self.assertFalse(ok)
        self.assertIn(f'answered {HTTPStatus.BAD_REQUEST.value}', sentence)
        self.assertIn('no such class', sentence)
        self.assertNotIn(TOKEN, sentence)

    def test_a_refused_token_is_reported_as_the_inventory_entry(self):
        api = Api(status=HTTPStatus.FORBIDDEN, answer={'success': False, 'errors': []})
        ok, sentence = service_deploy.deploy(self.root, {VARIABLE: TOKEN}, opener=api)
        self.assertFalse(ok)
        self.assertIn(f'the Cloudflare API refused {VARIABLE} ({HTTPStatus.FORBIDDEN.value})', sentence)
        self.assertIn('restart the runner', sentence)
        self.assertNotIn(TOKEN, sentence)

    def test_no_answer_is_a_sentence(self):
        api = Api(error=urllib.error.URLError('timed out'))
        ok, sentence = service_deploy.deploy(self.root, {VARIABLE: TOKEN}, opener=api)
        self.assertFalse(ok)
        self.assertIn('got no answer', sentence)

    def test_a_checkout_without_a_control_plane_is_a_sentence(self):
        ok, sentence = service_deploy.deploy(self.root / 'nowhere', {VARIABLE: TOKEN}, opener=Api())
        self.assertFalse(ok)
        self.assertIn('could not be built', sentence)
        self.assertNotIn(TOKEN, sentence)


class Main(Fixture):
    def test_a_deploy_job_with_the_already_deployed_tree_never_uploads(self):
        answer = Answer(HTTPStatus.OK, json.dumps({'deployed_tree': self.tree}).encode())
        with mock.patch.object(service_deploy.urllib.request, 'urlopen', return_value=answer), \
                mock.patch.object(service_deploy, 'deploy', side_effect=AssertionError('unexpected upload')), \
                mock.patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(service_deploy.main(['--root', str(self.root)], environ={VARIABLE: TOKEN}), 0)

    def test_a_deploy_job_with_a_different_tree_uploads_the_merged_checkout(self):
        answer = Answer(HTTPStatus.OK, json.dumps({'deployed_tree': None}).encode())
        with mock.patch.object(service_deploy.urllib.request, 'urlopen', return_value=answer), \
                mock.patch.object(service_deploy, 'deploy', return_value=(True, 'uploaded')) as upload, \
                mock.patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(service_deploy.main(['--root', str(self.root)], environ={VARIABLE: TOKEN}), 0)
        upload.assert_called_once_with(str(self.root), {VARIABLE: TOKEN})

    def test_the_dry_run_prints_the_metadata_with_no_token(self):
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(service_deploy.main(['--dry-run', '--root', str(self.root)], environ={}), 0)
        metadata = json.loads(out.getvalue())
        self.assertEqual(metadata['main_module'], 'index.js')
        self.assertIn({'type': 'plain_text', 'name': 'DEPLOYED_TREE', 'text': self.tree}, metadata['bindings'])

    def test_the_budget_is_only_service_job_budget_s_and_a_wrangler_budget_is_refused(self):
        plane = self.root / config.get('service.deploy_path') / 'wrangler.toml'
        plane.write_text(WRANGLER + 'BUDGET_S = "10"\n')
        with self.assertRaisesRegex(ValueError, 'service.job_budget_s'):
            service_deploy.metadata(self.root, 'tree')
        self.assertNotIn('BUDGET_S', service_deploy.wrangler(ROOT).get('vars', {}))

    def test_the_dry_run_of_this_checkout_reads_the_real_wrangler_toml(self):
        metadata = service_deploy.metadata(ROOT)
        self.assertEqual(metadata['main_module'], 'index.js')
        self.assertIn({'type': 'durable_object_namespace', 'name': 'CONTROL', 'class_name': 'Control'},
                      metadata['bindings'])
        self.assertEqual(metadata['keep_bindings'], ['secret_text', 'secret_key'])

    def test_main_without_the_token_fails_on_stderr(self):
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out, \
                mock.patch('sys.stderr', new_callable=io.StringIO) as err:
            self.assertEqual(service_deploy.main(['--root', str(self.root)], environ={}), 1)
        self.assertEqual(out.getvalue(), '')
        self.assertIn(VARIABLE, err.getvalue())


if __name__ == '__main__':
    unittest.main()
