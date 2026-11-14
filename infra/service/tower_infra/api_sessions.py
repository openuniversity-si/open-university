"""The session executor by API (D-310, D-311; P4 F3): one call to a model's API runs as a session, so a job's brief goes
to Claude, GPT, Gemini, Grok, Mistral, DeepSeek, Llama or Nova through the same contract as a subscription's session
(launch, follow, resume, end) and the same adapter (sessions.py).

A dialect is one function, complete(spec, model) -> completion(): the text, the served model, the input and output
tokens, the stop reason. Calls(complete, models) makes it a provider. launch(spec) refuses a model the service does not
allow this provider (no model is allowed until the service's configuration names it, so no API provider spends by
default; NotAllowed), starts the call in a worker thread and answers its id. follow(session) answers running until the
call returns, then ended: succeeded with the text, or failed with the error named (a refusal is failed with
`refusal`), always with the call's usage as meters: tokens:<model> (the total, for token limits), tokens_in:<model> and
tokens_out:<model> (for the tenant's meter rates, which turn them into money; D-308), api_s:<model> (the call's
seconds) and any other meter a dialect names, priced apart (a cache's reads and writes: tokens_cache_read:<model>). A
call refused for the account's rate or quota limit (Limited) waits until the time it names and is sent
again at resume. end(session) forgets the call: a sent request cannot be taken back, and its tokens are billed. A
session this process does not know (it restarted) ends failed as `lost`, and the job's retry policy decides. Standard
library only.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import time
import uuid

SAID = 500  # characters of an error kept in the result


class NotAllowed(Exception):
    """A job asked a model the service does not allow this provider."""


class NoKey(Exception):
    """The provider's key is not there (its SecureString under /tower/sessions/)."""


class Limited(Exception):
    """The provider's rate or quota limit; retry_after_s is how long it asks to wait."""

    def __init__(self, message, retry_after_s=60.0):
        super().__init__(message)
        self.retry_after_s = float(retry_after_s)


def completion(text, model, tokens_in, tokens_out, stop=None, meters=None, **extra):
    """What a dialect answers for one call; meters are other tokens it counts apart ({'tokens_cache_read': n})."""
    return {'text': text or '', 'model': model, 'tokens_in': int(tokens_in or 0), 'tokens_out': int(tokens_out or 0),
            'stop': stop, 'meters': {name: int(value) for name, value in (meters or {}).items() if value}, **extra}


def key_of(key):
    """The key a callable or a value holds, read when used; NoKey when there is none."""
    found = key() if callable(key) else key
    if not found:
        raise NoKey('no key for this provider (its SecureString under /tower/sessions/)')
    return found


def retry_after(headers, default=60.0):
    """The seconds a Retry-After header asks for, or the default."""
    try:
        return float((headers or {}).get('retry-after') or default)
    except (TypeError, ValueError):
        return default


class Calls:
    def __init__(self, complete, models=(), workers=4, kept=256, clock=time.monotonic, now=None):
        self.complete, self.models, self.kept, self.clock = complete, tuple(models), kept, clock
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='api-call')
        self.calls, self.lock = {}, threading.Lock()

    def send(self, spec):
        def timed():
            started = self.clock()
            done = self.complete(spec, spec['model'])
            return done, self.clock() - started
        return self.pool.submit(timed)

    def launch(self, spec):
        model = spec.get('model')
        if not isinstance(model, str) or model not in self.models:
            raise NotAllowed(f"model {model!r} is not allowed for this provider "
                             f"(allowed: {', '.join(self.models) or 'none'})")
        session = uuid.uuid4().hex
        with self.lock:
            self.calls[session] = {'spec': spec, 'future': self.send(spec)}
            while len(self.calls) > self.kept:  # the oldest calls go first; their runs ended long ago
                self.calls.pop(next(iter(self.calls)))
        return session

    def follow(self, session):
        with self.lock:
            call = self.calls.get(session)
        if call is None:
            return {'state': 'ended', 'outcome': 'failed', 'error': 'lost',
                    'result': {'error': 'this process does not know the call (the service restarted)'}}
        if 'until' in call:
            return {'state': 'waiting', 'until': call['until']}
        future = call['future']
        if not future.done():
            return {'state': 'running'}
        error = future.exception()
        if isinstance(error, Limited):
            call['until'] = (self.now() + timedelta(seconds=error.retry_after_s)).isoformat()
            return {'state': 'waiting', 'until': call['until']}
        if error is not None:
            return {'state': 'ended', 'outcome': 'failed', 'error': type(error).__name__,
                    'result': {'error': str(error)[:SAID]}}
        done, seconds = future.result()
        asked, meters = call['spec']['model'], done.get('meters') or {}
        refused = done.get('stop') == 'refusal'
        return {'state': 'ended', 'outcome': 'failed' if refused else 'succeeded', 'error': 'refusal' if refused else None,
                'result': {key: value for key, value in done.items() if key not in ('tokens_in', 'tokens_out', 'meters')},
                'tokens': {asked: done['tokens_in'] + done['tokens_out'] + sum(meters.values())},
                'usage': {f'tokens_in:{asked}': done['tokens_in'], f'tokens_out:{asked}': done['tokens_out'],
                          f'api_s:{asked}': round(seconds, 3),
                          **{f'{name}:{asked}': value for name, value in meters.items()}}}

    def resume(self, session):
        with self.lock:
            call = self.calls.get(session)
            if call is not None and 'until' in call:
                del call['until']
                call['future'] = self.send(call['spec'])

    def end(self, session):
        with self.lock:
            self.calls.pop(session, None)
