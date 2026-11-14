"""The runner's control transport (ADR-41, D-086, D-290): jobs claimed from the control plane over HTTPS, trains first,
results and heartbeats reported, a cancel heard, and a control plane that does not answer is a failed poll, never another
route. A fake opener stands in for the network; nothing leaves the machine."""
import hashlib
import ipaddress
from http import HTTPStatus
import json
from pathlib import Path
import socket
import sys
import unittest
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_forge_events import FakeClock, REPO  # noqa: E402
import config  # noqa: E402
import service_runner  # noqa: E402

PR = 1
URL = config.get('service.control_url')
HEAD = hashlib.sha1(b'head').hexdigest()


class Answer:
    def __init__(self, status, body=None):
        self.status, self.body = status, body

    def read(self):
        return b'' if self.body is None else json.dumps(self.body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeControl:
    """The control plane's runner API: claims served in order, then 204; every request kept with its token."""

    def __init__(self, claims=(), fail=None):
        self.claims, self.fail, self.requests, self.agents = list(claims), fail, [], []

    def __call__(self, request, timeout=None):
        path, body = urlsplit(request.full_url).path, json.loads(request.data)
        self.requests.append((path, body, request.get_header('Authorization')))
        self.agents.append(request.get_header('User-agent'))
        if self.fail:
            raise self.fail
        if path == '/v1/runner/claim':
            return Answer(HTTPStatus.OK, self.claims.pop(0)) if self.claims else Answer(HTTPStatus.NO_CONTENT)
        if path == '/v1/runner/heartbeat':
            return Answer(HTTPStatus.OK, {'cancel': body['job'] == 'gate:cancel#me'})
        return Answer(HTTPStatus.OK, {'done': body.get('job')})


class State:
    def __init__(self):
        self.data = {}


def claimed(kind, number):
    return service_runner.job(kind, REPO, number, HEAD, 'control', 'claimed', '2026-10-30T06:00:00.000Z')


class Control(unittest.TestCase):
    def transport(self, opener):
        return service_runner.ControlTransport(URL, 'runner-token', {'name': 'vm', 'kind': 'vm'}, opener=opener)

    def test_a_poll_claims_one_job_with_its_token_and_none_when_the_queue_is_empty(self):
        """D-291: one claim per poll, so a job's budget starts at its claim and no claimed job waits behind another."""
        control = FakeControl([claimed('train', PR + 1)])
        transport = self.transport(control)
        self.assertEqual([item['kind'] for item in transport.poll(State())], ['train'])
        self.assertEqual(transport.poll(State()), [])  # the control plane answered 204
        self.assertEqual(len(control.requests), 2)
        self.assertTrue(all(token == 'Bearer runner-token' for _, _, token in control.requests))

    def test_a_result_is_reported_and_a_cancel_is_heard(self):
        control = FakeControl()
        transport = self.transport(control)
        transport.report({'job': 'gate:1#feed', 'outcome': 'passed'})
        self.assertEqual(control.requests[-1][:1], ('/v1/runner/result',))
        self.assertTrue(transport.heartbeat('gate:cancel#me'))
        self.assertFalse(transport.heartbeat('gate:keep#going'))

    def test_a_control_plane_that_does_not_answer_is_a_failed_poll_not_another_route(self):
        state = State()
        with self.assertRaises(OSError) as raised:
            self.transport(FakeControl(fail=urllib.error.URLError('no route'))).poll(state)
        self.assertIn('no route', str(raised.exception))
        self.assertEqual(state.data['transport'], 'control')

    def test_a_refused_token_is_a_failed_poll_that_names_the_answer(self):
        refused = urllib.error.HTTPError(f'{URL}/v1/runner/claim', HTTPStatus.UNAUTHORIZED, 'no', {}, None)
        with self.assertRaises(OSError) as raised:
            self.transport(FakeControl(fail=refused)).poll(State())
        self.assertIn(str(int(HTTPStatus.UNAUTHORIZED)), str(raised.exception))

    def test_no_token_is_refused_at_construction_naming_the_variable(self):
        for token in (None, ''):
            with self.subTest(token=token), self.assertRaises(service_runner.RouteError) as raised:
                service_runner.ControlTransport(URL, token, {'name': 'vm', 'kind': 'vm'}, opener=FakeControl())
            self.assertIn(f'${config.get("service.runner_token_env")}', str(raised.exception))

    def test_reporting_failure_is_visible_to_the_runner(self):
        with self.assertRaises(OSError):
            self.transport(FakeControl(fail=urllib.error.URLError('down'))).report({'job': 'x', 'outcome': 'passed'})
        self.assertFalse(self.transport(FakeControl(fail=urllib.error.URLError('down'))).heartbeat('x'))

    def test_result_and_heartbeat_refusals_name_the_rotated_secret(self):
        for method, value in [('report', {'job': 'x', 'outcome': 'passed'}), ('heartbeat', 'x')]:
            refused = urllib.error.HTTPError(URL, HTTPStatus.UNAUTHORIZED, 'no', {}, None)
            with self.subTest(method=method), self.assertRaisesRegex(OSError, 'RUNNER_TOKEN'):
                getattr(self.transport(FakeControl(fail=refused)), method)(value)

    def test_result_reporting_uses_only_the_time_left_in_the_job(self):
        seen = []
        def opener(request, timeout=None):
            seen.append(timeout)
            return Answer(HTTPStatus.OK, {'done': 'x'})
        transport = self.transport(opener)
        transport.deadline = service_runner.time.time() + 0.25
        transport.report({'job': 'x', 'outcome': 'passed'})
        self.assertTrue(0 < seen[0] <= 0.25)

    def test_every_control_plane_request_names_the_runner_not_urllib(self):
        """D-091: the edge answers 403 to `Python-urllib/<version>`; claim, result and heartbeat carry the registry's agent."""
        control = FakeControl([claimed('gate', PR)])
        transport = self.transport(control)
        transport.poll(State())
        transport.report({'job': 'gate:1#feed', 'outcome': 'passed'})
        transport.heartbeat('gate:keep#going')
        paths = {path for path, _, _ in control.requests}
        self.assertEqual(paths, {'/v1/runner/claim', '/v1/runner/result', '/v1/runner/heartbeat'})
        self.assertEqual(set(control.agents), {config.get('service.user_agent')})
        self.assertFalse(config.get('service.user_agent').startswith('Python-urllib'))

    def test_the_agent_is_sent_on_the_wire(self):
        """The header survives urllib's own request building: a loopback server sees it, not urllib's default."""
        import http.server
        import threading
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.headers.get('User-Agent'))
                self.rfile.read(int(self.headers.get('Content-Length') or 0))
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()

            def log_message(self, *args):
                pass

        loopback = str(ipaddress.IPv4Address(socket.INADDR_LOOPBACK))
        server = http.server.HTTPServer((loopback, 0), Handler)  # the port is the kernel's
        # shutdown() waits for serve_forever's next poll: 10 ms, not the default 0.5 s
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        try:
            url = urlunsplit(('http', '{}:{}'.format(*server.server_address), '', '', ''))
            direct = urllib.request.build_opener(urllib.request.ProxyHandler({})).open  # loopback never goes through a proxy
            transport = service_runner.ControlTransport(url, 'runner-token', {'name': 'vm', 'kind': 'vm'},
                                                        opener=direct)
            self.assertEqual(transport.poll(State()), [])
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(seen, [config.get('service.user_agent')])


if __name__ == '__main__':
    unittest.main()
