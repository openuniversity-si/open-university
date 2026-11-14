"""The Worker's check-run client (services/control-plane, POST /v1/check-run, VAZÃO F37, D-299).

ControlAdapter hands a forge's check-run body to the control plane, which posts it with the credential it alone holds.
The address is service.control_url; the token is the environment variable forge-events.control_token_env (never printed,
never in a file); the user agent is service.user_agent (D-091: the edge refuses urllib's default).
D-300: the Worker is no event log or config store for the engine, and the /v1/events methods (append, read, recent) had no
reader left and were removed; the check-run publisher is the only engine caller.
"""
import json
import os
import urllib.error
import urllib.request
from http import HTTPStatus

import config


class ControlError(RuntimeError):
    pass


CHECK_RUN = '/v1/check-run'


class ControlAdapter:
    def __init__(self, url=None, token=None, opener=None):
        self.url = (url or config.get('service.control_url')).rstrip('/')
        self.token = token if token is not None else os.environ.get(config.get('forge-events.control_token_env'), '')
        self.opener = opener or urllib.request.urlopen
        self.timeout = config.get('service.control_timeout_s')
        self.agent = config.get('service.user_agent')

    def _call(self, method, route, body=None, answers=()):
        """The parsed body of one call; an HTTP status in `answers` is an answer, returned as (status, body)."""
        if not self.token:
            raise ControlError(f'no events token: set ${config.get("forge-events.control_token_env")}')
        request = urllib.request.Request(f'{self.url}{route}', method=method,
                                         data=None if body is None else json.dumps(body).encode(), headers={
                                             'authorization': f'Bearer {self.token}', 'content-type': 'application/json',
                                             'user-agent': self.agent})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                found = json.loads(response.read() or b'null')
                return (HTTPStatus.OK, found) if answers else found
        except urllib.error.HTTPError as error:
            if error.code in answers:
                try:
                    return error.code, json.loads(error.read() or b'null')
                except (OSError, ValueError, AttributeError):
                    return error.code, None
            if error.code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
                variable = config.get('forge-events.control_token_env')
                raise ControlError(f'control plane {route} refused ${variable} ({error.code}); the secret was '
                                   'rotated or its holder is stale: update the holder in service.token_holders') from None
            raise ControlError(f'control plane {route} answered {error.code}') from None
        except OSError as error:
            raise ControlError(f'control plane unreachable: {error}') from None

    def check_run(self, repo, body):
        """POST /v1/check-run: the control plane posts `body` (the forge's check-run body) for `repo` with the app
        credential only it holds, and answers the forge's outcome. A route without that credential answers 503 and
        its reason; a refusal, the forge's error or a stale outcome raises ControlError."""
        status, found = self._call('POST', CHECK_RUN, body={'repo': repo, **body},
                                   answers=(HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.BAD_GATEWAY))
        if status != HTTPStatus.OK:
            reason = (found or {}).get('error') if isinstance(found, dict) else None
            raise ControlError(f'{status}: control plane {CHECK_RUN}: {reason or "no reason"}')
        outcome = (found or {}).get('outcome')
        if outcome == 'ignored_stale':
            raise ControlError(f'control plane {CHECK_RUN}: the forge ignored the check run as stale')
        return outcome


class PortAdapter:
    """CHECK-RUN-AWS: the same check-run body handed to the engine's port (POST /v1/check-run, TOWER_PORT_URL with the
    tenant's TOWER_PORT_TOKEN); the live service posts it with the Origin app's key from Parameter Store, and this waits
    for its word (GET /v1/check-run/<id>: posted or failed), wait_s at most. The Cloudflare Worker is off the path.
    CHECK-IN-LANDING: the live service that posts it also lands, so a success the landing follows rides the landing."""
    lands = True

    def __init__(self, port=None, wait_s=30.0, poll_s=0.5, sleep=None, clock=None):
        import time
        self.port, self.wait_s, self.poll_s = port, wait_s, poll_s
        self.sleep, self.clock = sleep or time.sleep, clock or time.monotonic

    def client(self):
        if self.port is None:
            import gate_infra
            url, token = os.environ.get('TOWER_PORT_URL'), os.environ.get('TOWER_PORT_TOKEN')
            if not (url and token):
                raise ControlError('no port: set TOWER_PORT_URL and TOWER_PORT_TOKEN')
            self.port = gate_infra.Port(url, token)
        return self.port

    def check_run(self, repo, body):
        port = self.client()
        try:
            asked = port.call('POST', CHECK_RUN, {'repo': repo, **body})
        except Exception as error:  # noqa: BLE001 - the delivery judges a publish that failed
            raise ControlError(f'port {CHECK_RUN}: {error}') from None
        ends = self.clock() + self.wait_s
        while True:
            said = port.call('GET', f"{CHECK_RUN}/{asked['id']}")
            if said.get('state') == 'posted':
                if said.get('outcome') == 'ignored_stale':
                    raise ControlError(f'port {CHECK_RUN}: the forge ignored the check run as stale')
                return said.get('outcome')
            if said.get('state') == 'failed':
                raise ControlError(f"port {CHECK_RUN}: {said.get('why') or 'failed'}")
            if self.clock() >= ends:
                raise ControlError(f'port {CHECK_RUN}: no word of the live service in {self.wait_s:g} s')
            self.sleep(self.poll_s)
