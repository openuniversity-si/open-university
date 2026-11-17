"""The infrastructure's port over HTTP (GATE-INFRA, D-322): the client the gate and the check-run publisher share.

A layer-0 module (engine-events): it imports nothing of the engine but the registry, so forge_control's PortAdapter
(the events port's check-run publisher) builds a Port without importing the gate. gate_infra re-exports Port, Refused,
TRANSIENT, COLD and said for its own callers; the registry entries it reads stay gate-infra.*.
"""
from http import HTTPStatus
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request

import config

TRANSIENT = (HTTPStatus.TOO_MANY_REQUESTS, HTTPStatus.BAD_GATEWAY, HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.GATEWAY_TIMEOUT)


class Refused(RuntimeError):
    """The port refused a call: its HTTP status and what it said."""

    def __init__(self, status, said):
        super().__init__(f'{status}: {said}')
        self.status = status


def said(text):
    """The end of what a tool said, as long as a verdict keeps it."""
    return text.strip()[-config.get('gate-infra.said_chars'):]


class Port:
    """The infrastructure's port over HTTP with the tenant's token; call is replaceable (the test's port in
    process)."""

    def __init__(self, url, token, call=None, opener=urllib.request.urlopen, sleep=time.sleep,
                 jitter=random.uniform):
        self.url, self.token = (url or '').rstrip('/'), token
        self.colds = []  # GATE-COLD-PARTS: (the call, its wall s, the port's cold ms) of each answer a cold Lambda gave
        self.call = call or self.http
        self.opener, self.sleep, self.jitter = opener, sleep, jitter

    def http(self, method, path, body=None):
        """One call to the port. A transient answer (429 from the API Gateway's throttle, 502, 503, 504, or a
        connection that drops: the port's Lambda starting cold answers 503 past the HTTP API's 30 s) is tried again,
        at most gate-infra.call_retries times and gate-infra.call_max_wait_s seconds of pauses in all, each pause a
        full jitter of an exponential (gate-infra.call_backoff_s doubling) or the answer's Retry-After; one line per
        retry on stderr. A 429 is the throttle rejecting the request before the port saw it, and the port's commands
        are idempotent by their key, so a repeat makes nothing twice."""
        retries, base = config.get('gate-infra.call_retries'), config.get('gate-infra.call_backoff_s')
        limit, waited = config.get('gate-infra.call_max_wait_s'), 0.0
        for attempt in range(retries + 1):
            request = urllib.request.Request(self.url + path, method=method,
                                             data=json.dumps(body or {}).encode('utf-8'),
                                             headers={'Authorization': f'Bearer {self.token}',
                                                      'Content-Type': 'application/json'})
            hinted, began = None, time.monotonic()
            try:
                with self.opener(request, timeout=config.get('gate-infra.call_timeout_s')) as answer:
                    answered = json.loads(answer.read() or b'{}')
                    cold = COLD.search(str((getattr(answer, 'headers', None) or {}).get('Server-Timing') or ''))
                    if cold:  # GATE-COLD-PARTS: PORT-COLD-START's mark: this call started a Lambda environment
                        self.colds.append((f"{method} {re.sub(r'[0-9a-f-]{36}', '<id>', path)}",
                                           round(time.monotonic() - began, 3), float(cold.group(1))))
                    return answered
            except urllib.error.HTTPError as error:
                told = (error.headers or {}).get('Retry-After')
                hinted = float(told) if told and re.fullmatch(r'\d+(\.\d+)?', told.strip()) else None
                why = error.code
                refusal = (error.code, said(error.read().decode('utf-8', 'replace')))
                if error.code not in TRANSIENT:
                    raise Refused(*refusal) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                why = type(error).__name__
                refusal = (HTTPStatus.SERVICE_UNAVAILABLE, f'{type(error).__name__}: {error}')
            pause = hinted if hinted is not None else self.jitter(0, base * 2 ** attempt)
            if attempt == retries or waited + pause > limit:
                raise Refused(refusal[0], f'{refusal[1]} (gave up after {attempt + 1} call(s), {waited:.1f} s waited)') from None
            print(f'gate-infra: {method} {path} answered {why}; retry {attempt + 1}/{retries} in {pause:.1f} s',
                  file=sys.stderr)
            self.sleep(pause)
            waited += pause


COLD = re.compile(r'(?:^|,\s*)cold;dur=([0-9.]+)')
