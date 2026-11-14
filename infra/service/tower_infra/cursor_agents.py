"""The Cursor Cloud Agents provider of the session executor (P4 F3; ARQUITETURA-ALVO §6, 12-unidade-e-sessoes §5):
a session is one run of a Cursor cloud agent, through Cursor's REST API as the official @cursor/sdk 1.3.1 calls it.

launch(spec) creates the agent with the brief as its prompt (POST /v1/agents, the job's own idempotency key, the
spec's repositories and model) and answers "<agent id>/<run id>"; follow(session) reads the run (GET
/v1/agents/<agent>/runs/<run>): CREATING and RUNNING are running; FINISHED ended succeeded with its result; ERROR,
EXPIRED and CANCELLED ended failed or cancelled; a 429 is the account's limit, the session waiting a minute; the
tokens of an ended run come from GET /v1/agents/<agent>/usage?runId=<run>, all under the run's model. end(session)
cancels the run; resume(session) has nothing to do (a Cursor run waits on nobody). The key is the caller's, read when
used (the service reads /tower/sessions/cursor from Parameter Store); with none, a launch is refused. Standard library
only.
"""
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
import json
import urllib.error
import urllib.request

BASE = 'https://api.cursor.com'
ENDED = {'FINISHED': ('succeeded', None), 'ERROR': ('failed', 'error'), 'EXPIRED': ('failed', 'expired'),
         'CANCELLED': ('cancelled', 'cancelled')}
LIMIT_WAIT = timedelta(minutes=1)
LIMIT_BODY = 500


class NoKey(Exception):
    pass


class CursorError(Exception):
    """An HTTP refusal from the Cursor API: the status and the start of the body, never the key."""

    def __init__(self, code, body):
        self.code, self.body = code, body
        super().__init__(f'HTTP {code}: {body}')


class CursorAgents:
    def __init__(self, key, opener=urllib.request.urlopen, base=BASE, timeout_s=30.0, now=None):
        self.key, self.opener, self.base, self.timeout_s = key, opener, base.rstrip('/'), timeout_s
        self.now = now or (lambda: datetime.now(timezone.utc))

    def call(self, method, path, body=None, idempotency=None):
        key = self.key() if callable(self.key) else self.key
        if not key:
            raise NoKey('no Cursor key for the session executor (/tower/sessions/cursor)')
        headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
        if idempotency:
            headers['Idempotency-Key'] = idempotency
        request = urllib.request.Request(self.base + path, method=method, headers=headers,
                                         data=None if body is None else json.dumps(body).encode('utf-8'))
        try:
            with self.opener(request, timeout=self.timeout_s) as answer:
                return json.loads(answer.read() or b'{}')
        except urllib.error.HTTPError as error:
            if error.code == HTTPStatus.TOO_MANY_REQUESTS:
                raise
            try:
                text = (error.read() or b'').decode('utf-8', 'replace')
            except Exception:  # noqa: BLE001 - a body that cannot be read is no reason to lose the status
                text = ''
            raise CursorError(error.code, text.replace(key, '[redacted]')[:LIMIT_BODY]) from error

    def launch(self, spec):
        body = {'prompt': {'text': spec['brief']}, 'repos': [
            {'url': repo['url'], **({'startingRef': repo['ref']} if repo.get('ref') else {})}
            for repo in spec.get('repos') or []]}
        if spec.get('model'):
            body['model'] = spec['model']
        if 'auto_pr' in spec:
            body['autoCreatePR'] = bool(spec['auto_pr'])
        made = self.call('POST', '/v1/agents', body, idempotency=spec.get('idempotency_key'))
        return f"{made['agent']['id']}/{made['run']['id']}"

    def follow(self, session):
        agent, run = session.split('/', 1)
        try:
            seen = self.call('GET', f'/v1/agents/{agent}/runs/{run}')
        except urllib.error.HTTPError as error:
            if error.code == HTTPStatus.TOO_MANY_REQUESTS:
                return {'state': 'waiting', 'until': (self.now() + LIMIT_WAIT).isoformat()}
            raise
        status = str(seen.get('status', '')).upper()
        if status not in ENDED:
            return {'state': 'running'}
        outcome, error = ENDED[status]
        usage = self.call('GET', f'/v1/agents/{agent}/usage?runId={run}').get('usage') or {}
        model = seen.get('model') or 'cursor'
        model = model.get('id', 'cursor') if isinstance(model, dict) else model
        return {'state': 'ended', 'outcome': outcome, 'error': error,
                'result': {key: seen[key] for key in ('result', 'git', 'durationMs') if key in seen},
                'tokens': {model: usage.get('totalTokens', 0)}}

    def resume(self, session):
        return None

    def end(self, session):
        agent, run = session.split('/', 1)
        self.call('POST', f'/v1/agents/{agent}/runs/{run}/cancel')
