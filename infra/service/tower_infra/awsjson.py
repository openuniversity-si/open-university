"""A minimal AWS JSON-protocol client over the standard library (PORT3): SigV4, one kept-alive connection per host.

The webhook ingress answers Origin from Lambda in well under a second, so it cannot import boto3 (135 ms and more at a
Lambda's small CPU) nor open a database connection. It needs two calls only: SSM GetParameter (the forge's keys) and SQS
SendMessage (the durable write). Both speak the JSON protocol, a POST with an X-Amz-Target header. `transport` is the
seam the tests use: transport(host, path, headers, body) -> (status, bytes); the default keeps one HTTPS connection per
host between calls and reopens it once when the server has closed it.
"""
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import json
import os

TIMEOUT_S = 5.0


def signed_headers(host, service, region, target, body, version, environ=None, now=None):
    """The headers of a SigV4-signed POST / of the JSON protocol (host, content-type, x-amz-date, x-amz-target,
    x-amz-security-token when the credentials are temporary, authorization)."""
    environ = os.environ if environ is None else environ
    key, secret = environ['AWS_ACCESS_KEY_ID'], environ['AWS_SECRET_ACCESS_KEY']
    moment = (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%SZ')
    day = moment[:8]
    headers = {'content-type': f'application/x-amz-json-{version}', 'host': host, 'x-amz-date': moment,
               'x-amz-target': target}
    if environ.get('AWS_SESSION_TOKEN'):
        headers['x-amz-security-token'] = environ['AWS_SESSION_TOKEN']
    names = sorted(headers)
    canonical = ''.join(f'{name}:{headers[name]}\n' for name in names)
    signed = ';'.join(names)
    request = f'POST\n/\n\n{canonical}\n{signed}\n{hashlib.sha256(body).hexdigest()}'
    scope = f'{day}/{region}/{service}/aws4_request'
    signing = hmac.new(('AWS4' + secret).encode(), day.encode(), hashlib.sha256).digest()
    for part in (region, service, 'aws4_request'):
        signing = hmac.new(signing, part.encode(), hashlib.sha256).digest()
    unsigned = f'AWS4-HMAC-SHA256\n{moment}\n{scope}\n{hashlib.sha256(request.encode()).hexdigest()}'
    signature = hmac.new(signing, unsigned.encode(), hashlib.sha256).hexdigest()
    headers['authorization'] = (f'AWS4-HMAC-SHA256 Credential={key}/{scope}, SignedHeaders={signed}, '
                                f'Signature={signature}')
    return headers


class Pool:
    """One HTTPS connection per host, kept between calls (a warm Lambda pays the TLS handshake once)."""

    def __init__(self):
        self.connections = {}

    def connect(self, host):
        if host not in self.connections:
            self.connections[host] = http.client.HTTPSConnection(host, timeout=TIMEOUT_S)
            self.connections[host].connect()
        return self.connections[host]

    def __call__(self, host, path, headers, body):
        for attempt in (0, 1):
            try:
                connection = self.connect(host)
                connection.request('POST', path, body=body, headers=headers)
                answer = connection.getresponse()
                return answer.status, answer.read()
            except (OSError, http.client.HTTPException):
                self.connections.pop(host, None)  # closed by the server while idle: one fresh connection
                if attempt:
                    raise


class Client:
    def __init__(self, service, region, version, prefix, transport=None, environ=None):
        self.service, self.region, self.version, self.prefix = service, region, version, prefix
        self.host = f'{service}.{region}.amazonaws.com'
        self.transport = transport or Pool()
        self.environ = environ

    def call(self, action, payload, now=None):
        body = json.dumps(payload, separators=(',', ':')).encode('utf-8')
        headers = signed_headers(self.host, self.service, self.region, f'{self.prefix}.{action}', body, self.version,
                                 self.environ, now)
        status, answer = self.transport(self.host, '/', headers, body)
        if status != 200:
            raise RuntimeError(f'{self.service} {action} answered {status}: {answer[:200]!r}')
        return json.loads(answer or b'{}')

    def warm(self):
        """Open the connection ahead of the first call (best effort: the Lambda's init phase has the CPU for it)."""
        try:
            if isinstance(self.transport, Pool):
                self.transport.connect(self.host)
        except OSError:
            pass
