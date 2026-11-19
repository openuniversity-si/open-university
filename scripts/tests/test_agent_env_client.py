"""The AGENT-ENV client (D-341): it fetches the declared bundle from a local stub on 127.0.0.1 (no network), refuses a
denied or undeclared name as a whole, writes shell-quoted exports at mode 600, prints names only, and is inert and
non-fatal while the endpoint is empty or the credential is missing; `torre` POSTs a text to the relay and prints only
the status it answers.

Verifies: REQ-agent-env-single-source
"""
import contextlib
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
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
REAL_ENDPOINT = client.endpoint  # the setUp patches the module's; the template test calls the real one

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

    def do_POST(self):  # noqa: N802 (http.server's name): the Torre relay's route
        body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        Stub.seen.append((self.path, self.headers.get('Authorization'), json.loads(body)))
        status, answer = Stub.answer
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(answer)

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
        closed = ThreadingHTTPServer((HOST, 0), Stub)  # a port of the loopback that answers nothing once closed
        port = closed.server_address[1]
        closed.server_close()
        with mock.patch.object(client, 'endpoint', return_value=f'http://{HOST}:{port}'):
            self.assertIn('could not be reached', self.run_fetch())
        self.assertFalse(self.env_file.exists())

    def test_an_empty_endpoint_is_inert(self):
        with mock.patch.object(client, 'endpoint', return_value=''):
            self.assertIn('not provisioned', self.run_fetch())
        self.assertEqual(Stub.seen, [])
        self.assertFalse(self.env_file.exists())

    def test_preflight_warns_while_not_provisioned_and_gaps_a_missing_credential_after(self):
        with mock.patch.object(client, 'endpoint', return_value=''):
            self.assertEqual(client.preflight_lines({}), (['agent-env: not provisioned'], []))
        self.assertEqual(client.preflight_lines({}), ([], ['agent-env: no starting credential is set']))
        self.assertEqual(client.preflight_lines({CREDENTIAL: TOKEN}), ([], []))

    def test_the_endpoint_is_a_template_of_the_environment_and_the_session(self):
        """No host of the account in the repository: {id} is the environment, $NAME a variable of the session; a
        variable the session lacks is not provisioned."""
        with mock.patch.object(client.config, 'get', return_value='$TOWER_PORT_URL/agent-env/{id}/'):
            self.assertEqual(REAL_ENDPOINT(environ={'TOWER_PORT_URL': self.base}, env_id='the-tower'),
                             f'{self.base}/agent-env/the-tower')
            self.assertEqual(REAL_ENDPOINT(environ={}, env_id='the-tower'), '')
        with mock.patch.object(client.config, 'get', return_value=''):
            self.assertEqual(REAL_ENDPOINT(environ={'TOWER_PORT_URL': self.base}), '')

    def test_preflight_today_is_a_warning_never_a_gap(self):
        import preflight
        unset = {key: value for key, value in os.environ.items() if key != 'TOWER_PORT_URL'}
        with mock.patch.object(client, 'endpoint', side_effect=lambda root=ROOT, environ=None, env_id='':
                               REAL_ENDPOINT(root, unset, env_id)), mock.patch.dict(os.environ, unset, clear=True):
            warnings, gaps = preflight.agent_env_lines()
        self.assertEqual((warnings, gaps), (['agent-env: not provisioned'], []))
        stderr, stdout = io.StringIO(), io.StringIO()
        with mock.patch.object(preflight, 'problems', return_value=[]), contextlib.redirect_stderr(stderr), \
                contextlib.redirect_stdout(stdout), \
                mock.patch.object(preflight, 'agent_env_lines', return_value=(warnings, gaps)):
            self.assertEqual(preflight.main([]), 0)
        self.assertEqual((stderr.getvalue(), stdout.getvalue()), ('WARN agent-env: not provisioned\n', 'preflight: ok\n'))

    def run_torre(self, text, environ=None):
        lines = []
        self.assertEqual(client.torre(text, self.environ if environ is None else environ, out=lines.append), 0)
        self.assertEqual(len(lines), 1, lines)
        return lines[0]

    def test_torre_posts_the_text_with_the_starting_credential_and_prints_the_status(self):
        self.serve({'forwarded': HTTPStatus.ACCEPTED})
        line = self.run_torre('hello Torre')
        self.assertIn(f'forwarded, the Torre answered {HTTPStatus.ACCEPTED.value}', line)
        self.assertEqual(Stub.seen, [(client.TORRE_ROUTE, f'Bearer {TOKEN}', {'text': 'hello Torre'})])
        self.assertNotIn(TOKEN, line)

    def test_torre_prints_the_relay_s_own_refusal_and_exits_0(self):
        for status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.BAD_REQUEST, HTTPStatus.TOO_MANY_REQUESTS):
            self.serve({}, status=status)
            self.assertIn(f'answered {status.value}', self.run_torre('hi'))
        self.serve(['not', 'an', 'object'])
        self.assertIn('did not answer JSON', self.run_torre('hi'))

    def test_torre_is_inert_unprovisioned_or_without_the_credential(self):
        with mock.patch.object(client, 'endpoint', return_value=''):
            self.assertIn('torre: not provisioned', self.run_torre('hi'))
        self.assertIn(f'no starting credential is set ({CREDENTIAL})', self.run_torre('hi', {}))
        self.assertEqual(Stub.seen, [])

    def test_the_wrapper_is_inert_with_the_registry_default(self):
        # the registry default names the session's port URL: a session without it is not provisioned
        self.assertIn('$TOWER_PORT_URL', client.config.get('agent-env.endpoint', ROOT))
        env = {key: value for key, value in os.environ.items() if key not in (client.ENV_FILE, 'TOWER_PORT_URL')}
        done = subprocess.run([str(ROOT / 'scripts/cloud/agent-env'), 'fetch'], capture_output=True, text=True,
                              check=False, env=env)
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertEqual(len(done.stdout.splitlines()), 1)
        self.assertIn('not provisioned', done.stdout)
        done = subprocess.run([str(ROOT / 'scripts/cloud/agent-env'), 'torre', 'hi'], capture_output=True, text=True,
                              check=False, env=env)
        self.assertEqual((done.returncode, done.stderr), (0, ''))
        self.assertIn('torre: not provisioned', done.stdout)
        self.assertEqual(Stub.seen, [])


if __name__ == '__main__':
    unittest.main()
