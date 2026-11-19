"""The AGENT-ENV client (D-341): it fetches the declared bundle from a local stub on 127.0.0.1 (no network), refuses a
denied or undeclared name as a whole, writes shell-quoted exports at mode 600, prints names only, and is inert and
non-fatal while the endpoint is empty or the credential is missing.

Verifies: REQ-agent-env-single-source
"""
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import agent_env_client as client  # noqa: E402

sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from rest_fake import HOST  # noqa: E402  (the loopback host of the engine's fixture servers)

CREDENTIAL = 'TOWER_SAMPLE_START'
TOKEN = 'sentinel-start-credential'
DECLARATION = {
    'id': 'sample',
    'provider': 'claude-code',
    'variables': {'TOWER_MODE': 'cloud'},
    'secrets': [{'name': 'TOWER_SAMPLE_KEY', 'store': 'ssm', 'ref': '/tower/agent-env/sample/sample-key'}],
    'network': {'hosts': []},
    'starting_credential': {'kind': 'bearer-env', 'variable': CREDENTIAL},
}
HARD_VALUE = 'it\'s "quoted" $HOME `date` \\ and\nsecond line  '
PROXY_NAMES = ('http_proxy', 'HTTP_PROXY', 'https_proxy', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY')


class Stub(BaseHTTPRequestHandler):
    answer = (HTTPStatus.OK, b'{}')
    seen = []

    def do_GET(self):  # noqa: N802 (http.server's name)
        Stub.seen.append((self.path, self.headers.get('Authorization')))
        status, body = Stub.answer
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer((HOST, 0), Stub)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f'http://{HOST}:{cls.server.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, {'no_proxy': HOST, 'NO_PROXY': HOST}))
        for name in PROXY_NAMES:  # the stub is local: no proxy, so no network
            os.environ.pop(name, None)
        self.enterContext(mock.patch.object(client, 'endpoint', return_value=self.base))
        self.enterContext(mock.patch.object(client, 'load_declarations', return_value=[DECLARATION]))
        self.dir = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.env_file = self.dir / 'claude.env'
        self.environ = {CREDENTIAL: TOKEN, client.ENV_FILE: str(self.env_file)}
        Stub.seen = []

    def serve(self, bundle, status=HTTPStatus.OK):
        Stub.answer = (status, json.dumps(bundle).encode())

    def run_fetch(self, environ=None):
        lines = []
        code = client.fetch(self.environ if environ is None else environ, out=lines.append)
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 1, lines)
        return lines[0]

    def test_a_declared_bundle_is_written_with_names_only_on_stdout(self):
        self.serve({'variables': {'TOWER_MODE': 'cloud'}, 'secrets': {'TOWER_SAMPLE_KEY': HARD_VALUE}})
        line = self.run_fetch()
        self.assertIn('1 variables, 1 secrets', line)
        self.assertIn('TOWER_MODE TOWER_SAMPLE_KEY', line)
        for value in ('cloud', HARD_VALUE, TOKEN, 'quoted', 'second line'):
            self.assertNotIn(value, line)
        self.assertEqual(Stub.seen, [(client.ROUTE, f'Bearer {TOKEN}')])

    def test_the_file_is_mode_600_and_sources_in_bash_with_the_hard_value_intact(self):
        self.env_file.write_text('export EARLIER=kept\n')
        self.env_file.chmod(client.FILE_MODE | stat.S_IRGRP | stat.S_IROTH)
        self.serve({'variables': {'TOWER_MODE': 'cloud'}, 'secrets': {'TOWER_SAMPLE_KEY': HARD_VALUE}})
        self.run_fetch()
        self.assertEqual(stat.S_IMODE(self.env_file.stat().st_mode), client.FILE_MODE)
        script = 'set -eu; source "$1"; printf "%s\\0%s\\0%s" "$EARLIER" "$TOWER_MODE" "$TOWER_SAMPLE_KEY"'
        done = subprocess.run(['bash', '-c', script, 'bash', str(self.env_file)],
                              capture_output=True, text=True, check=True, env={'PATH': os.environ['PATH']})
        self.assertEqual(done.stdout.split('\0'), ['kept', 'cloud', HARD_VALUE])

    def test_without_claude_env_file_it_writes_the_local_file_at_mode_600(self):
        path = client.write('export TOWER_MODE=cloud\n', {}, root=self.dir)
        self.assertEqual(path, self.dir / client.LOCAL_FILE)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), client.FILE_MODE)
        self.assertEqual(path.read_text(), 'export TOWER_MODE=cloud\n')

    def test_a_denied_name_refuses_the_bundle_and_writes_nothing(self):
        self.serve({'variables': {'TOWER_MODE': 'cloud'}, 'secrets': {'TEST_DATABASE_URL': HARD_VALUE}})
        line = self.run_fetch()
        self.assertIn('bundle refused', line)
        self.assertIn('TEST_DATABASE_URL is refused by agent-env.denied_names', line)
        self.assertNotIn(HARD_VALUE, line)
        self.assertFalse(self.env_file.exists())

    def test_an_undeclared_name_refuses_the_bundle(self):
        self.serve({'variables': {'TOWER_MODE': 'cloud', 'TOWER_EXTRA': 'x'}, 'secrets': {}})
        line = self.run_fetch()
        self.assertIn('TOWER_EXTRA is not declared in variables of sample', line)
        self.assertFalse(self.env_file.exists())
        self.serve({'variables': {'TOWER_SAMPLE_KEY': 'x'}, 'secrets': {}})  # a secret's name sent as a variable
        self.assertIn('bundle refused', self.run_fetch())
        self.assertFalse(self.env_file.exists())

    def test_a_missing_credential_is_one_line_and_exit_0(self):
        line = self.run_fetch({client.ENV_FILE: str(self.env_file)})
        self.assertIn(f'no starting credential is set ({CREDENTIAL})', line)
        self.assertEqual(Stub.seen, [])
        self.assertFalse(self.env_file.exists())

    def test_a_non_200_or_unreachable_endpoint_is_one_line_and_exit_0(self):
        self.serve({'error': 'no'}, status=HTTPStatus.FORBIDDEN)
        self.assertIn(f'answered {HTTPStatus.FORBIDDEN.value}', self.run_fetch())
        with socket.socket() as closed:
            closed.bind((HOST, 0))
            port = closed.getsockname()[1]
        with mock.patch.object(client, 'endpoint', return_value=f'http://{HOST}:{port}'):
            self.assertIn('could not be reached', self.run_fetch())
        self.assertFalse(self.env_file.exists())

    def test_an_empty_endpoint_is_inert(self):
        with mock.patch.object(client, 'endpoint', return_value=''):
            self.assertIn('not provisioned', self.run_fetch())
        self.assertEqual(Stub.seen, [])
        self.assertFalse(self.env_file.exists())

    def test_the_wrapper_is_inert_with_the_registry_default(self):
        self.assertEqual(client.config.get('agent-env.endpoint', ROOT), '')
        env = {key: value for key, value in os.environ.items() if key != client.ENV_FILE}
        done = subprocess.run([str(ROOT / 'scripts/cloud/agent-env'), 'fetch'], capture_output=True, text=True,
                              check=False, env=env)
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertEqual(len(done.stdout.splitlines()), 1)
        self.assertIn('not provisioned', done.stdout)


if __name__ == '__main__':
    unittest.main()
