#!/usr/bin/env python3
"""Loopback stand-in for GitHub REST, Neon and Vercel.

GraphQL always fails. Authorization values are never logged or written to disk.
Routes live in rest_fake/*.py, one module per owning unit, loaded by sorted glob (TX24): each exports ROUTES, a tuple of
route(handler, method, parts, directory) that answers and returns True, else returns False. Adding a route is one new
file. The proxy refusal, the secondary limit and GraphQL stay here and run first; the route matchers are disjoint.
`--wait-ready --port-file F --pid P` is the readiness probe (HD1): it returns the port once F holds one and a TCP
request to it gets an HTTP answer, polling every delivery.test_fake_start_wait_s, failing at once when P exited and after
delivery.test_fake_ready_max_s otherwise. A loaded machine only delays it; no caller sleeps a fixed count.
"""
import argparse
import importlib.util
import json
import os
import http.client
from http import HTTPStatus
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HOST = '127.0.0.1'
DIRECTORY = None
# GX-FIX-train-lock: with a file named PROXY in the case directory the fake answers like the Claude Code egress proxy,
# which refuses these REST writes before GitHub sees them (docs/units/GX-FIX-train-lock/audit.md).
PROXY = 'proxy'
PROXY_REFUSED = ('/git/', '/statuses/', '/contents/', '/merges', '/check-runs')
PROXY_REFUSAL = 'Write access to this GitHub API path is not permitted through this proxy.'


ROUTES_DIR = Path(__file__).resolve().with_name('rest_fake')


def load_routes(directory=ROUTES_DIR):
    """Every route of every module under rest_fake/, modules in file-name order."""
    routes = []
    for path in sorted(Path(directory).glob('*.py')):
        spec = importlib.util.spec_from_file_location(f'rest_fake_routes_{path.stem}', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        routes.extend(module.ROUTES)
    return tuple(routes)


def case_dir():
    return Path(DIRECTORY).resolve()


def _record(method, path, auth):
    directory = case_dir()
    try:
        with (directory / 'requests.log').open('a') as handle:
            handle.write(f'{method} {path} auth={auth}\n')
    except OSError:
        return


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    routes = ()

    def log_message(self, fmt, *args):
        return

    def _json(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get('Content-Length', '0') or '0')
        return self.rfile.read(length) if length else b''

    def _dispatch(self, method):
        parts = urlsplit(self.path)
        path = parts.path
        auth = '1' if self.headers.get('Authorization') else '0'
        directory = case_dir()
        _record(method, path, auth)
        if (method != 'GET' and (directory / PROXY).is_file() and path.startswith('/repos/')
                and any(part in path for part in PROXY_REFUSED)):
            self._body()
            self._json(HTTPStatus.FORBIDDEN, {'message': PROXY_REFUSAL})
            return
        if _secondary_limited(self, method, directory):
            return
        if 'graphql' in path.lower():
            try:
                with (directory / 'graphql-calls').open('a') as handle:
                    handle.write(path + '\n')
            except OSError:
                pass
            self._json(403, {'message': 'GitHub GraphQL is not available from Claude Code sessions; use the REST API'})
            return
        for route in self.routes:
            if route(self, method, parts, directory):
                return
        self._json(404, {})

    def do_GET(self):
        self._dispatch('GET')

    def do_PUT(self):
        self._dispatch('PUT')

    def do_POST(self):
        self._dispatch('POST')

    def do_PATCH(self):
        self._dispatch('PATCH')

    def do_DELETE(self):
        self._dispatch('DELETE')


# GX-FIX-forge-rate: the fake counts content writes (content-writes, one line per write) and, when the case directory
# holds secondary-limit.json {"limit": N, "retry_after": S}, refuses every write after the N-th the way GitHub's
# secondary limit does: 403, its message, Retry-After. A cleared file (or "limit": null) lifts the block.
SECONDARY_MESSAGE = ('You have exceeded a secondary rate limit and have been temporarily blocked from content creation. '
                     'Please retry your request again later.')


def _refuse(handler, directory, method, status, retry_after):
    with (directory / 'content-refusals').open('a') as handle:
        handle.write(f'{method} {urlsplit(handler.path).path}\n')
    raw = json.dumps({'message': SECONDARY_MESSAGE, 'status': str(status.value)}).encode()
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Retry-After', str(retry_after))
    handler.send_header('Content-Length', str(len(raw)))
    handler.end_headers()
    handler.wfile.write(raw)
    return True


def _secondary_limited(handler, method, directory):
    rule_path = directory / 'secondary-limit.json'
    rule = json.loads(rule_path.read_text()) if rule_path.is_file() else {}
    if method == 'GET':
        # GX-FIX-forge-rate-2: reads are counted (reads, one line each) and, with "read_limit": N, every read after the
        # N-th is refused like GitHub's secondary limit on reads: 429, its message, Retry-After.
        counter = directory / 'reads'
        done = len(counter.read_text().splitlines()) if counter.is_file() else 0
        if rule.get('read_limit') is not None and done >= rule['read_limit']:
            return _refuse(handler, directory, method, HTTPStatus.TOO_MANY_REQUESTS, rule['retry_after'])
        with counter.open('a') as handle:
            handle.write(f'{method} {urlsplit(handler.path).path}\n')
        return False
    if method not in ('POST', 'PATCH', 'PUT', 'DELETE'):
        return False
    counter = directory / 'content-writes'
    done = len(counter.read_text().splitlines()) if counter.is_file() else 0
    if rule.get('limit') is not None and done >= rule['limit']:
        handler._body()
        return _refuse(handler, directory, method, HTTPStatus.FORBIDDEN, rule['retry_after'])
    with counter.open('a') as handle:
        handle.write(f'{method} {urlsplit(handler.path).path}\n')
    return False


def _exited(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def wait_ready(port_file, pid):
    # Read through this tree's own config.py, as a child: a script test's Python has the pinned tooling's `config`
    # already loaded (hermetic sitecustomize), whose registry does not know a key this tree adds.
    reader = Path(__file__).resolve().parents[1] / 'lib' / 'config.py'

    def read(name):
        return float(subprocess.run([sys.executable, str(reader), 'get', name], check=True, capture_output=True,
                                    text=True).stdout)

    poll, limit = read('delivery.test_fake_start_wait_s'), read('delivery.test_fake_ready_max_s')
    deadline = time.monotonic() + limit
    while True:
        try:
            port = int(Path(port_file).read_text())
            # Ready means it answers HTTP, not only that the socket accepts.
            connection = http.client.HTTPConnection(HOST, port, timeout=poll)
            try:
                connection.request('GET', '/')
                connection.getresponse().read()
            finally:
                connection.close()
            return port
        except (OSError, ValueError, http.client.HTTPException):
            pass
        if _exited(pid):
            raise SystemExit('rest fake exited before it was ready')
        if time.monotonic() >= deadline:
            raise SystemExit(f'rest fake not ready after {limit}s')
        time.sleep(poll)


def main():
    global DIRECTORY
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir')
    parser.add_argument('--port-file', required=True)
    parser.add_argument('--wait-ready', action='store_true')
    parser.add_argument('--pid', type=int)
    args = parser.parse_args()
    if args.wait_ready:
        if args.pid is None: parser.error('--wait-ready needs --pid')
        print(wait_ready(args.port_file, args.pid))
        return
    if not args.dir: parser.error('--dir is required')
    DIRECTORY = args.dir
    Handler.routes = load_routes()
    server = ThreadingHTTPServer((HOST, 0), Handler)
    # Atomic: a poller never reads a partial port number.
    partial = Path(args.port_file + '.partial')
    partial.write_text(str(server.server_address[1]))
    os.replace(partial, args.port_file)
    server.serve_forever()


if __name__ == '__main__':
    main()
