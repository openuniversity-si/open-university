"""The live proof of the quota that resets (AWS12; docs/operations/aws.md 16, aws-pendencias P4 F3): a `wait` limit on the
usd meter of executor api-bedrock holds a job `waiting` with run.waiting {until}, and the job resumes and succeeds when
the limit is lifted (or, with --natural, when the window ends).

  scripts/aws-quota-proof [--window-s 900] [--natural] [--run N] [--cap-usd 0.01]

Steps: queue `sessions`; a wait limit (scope executor api-bedrock, meter usd, maximum 1e-6) whose window ends in
--window-s seconds, re-armed if it exists; job A (one Haiku 4.5 call of 16 tokens, ~US$ 0.00004) runs and crosses the limit;
job B must be held `waiting` with run.waiting {until, reason limit}; the limit is lifted (PUT /v1/limits/<id> {lift}) or the
window ends, and B must end `succeeded`. The limit is lifted at the end, whatever happened, so it cannot hold the tenant.

The port is TOWER_PORT_URL with the tenant's token TOWER_PORT_TOKEN (never printed). The spend is capped: before each Bedrock
call the cost so far (from the run.usage tokens at the Haiku 4.5 list price) plus the worst case of one more call must fit
--cap-usd (at most 0.01), or the job is not created. Idempotent: the jobs' keys come from the day and --run, so a repeat
the same day makes no new call; use --run N for another try. Exit: 0 proven, 1 not proven, 2 not configured / over the cap.
"""
import argparse
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

EXECUTOR, QUEUE, PROVIDER = 'api-bedrock', 'sessions', 'bedrock-converse'
MODEL = 'us.anthropic.claude-haiku-4-5-20251001-v1:0'
MAX_TOKENS = 16
CAP_USD = 0.01
PRICE_IN, PRICE_OUT = 1e-6, 5e-6        # Haiku 4.5, US$ per token (an upper bound: the measured rates are the tenant's)
WORST_TOKENS_IN = 100                    # the brief is a few tokens; a margin
WORST_CALL_USD = WORST_TOKENS_IN * PRICE_IN + MAX_TOKENS * PRICE_OUT
LIMIT_MAX = 0.000001
LONG_POLL = 'long_poll'  # PORT-LONG-POLL: the mark of an answer the port held (tower_infra.port.LONG_POLL)


class Refused(RuntimeError):
    """The port refused a call: its status and what it said (never the token)."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class Port:
    """The port over HTTP with the tenant's token; a connection that drops or a 5xx is tried again twice."""

    def __init__(self, url, token, opener=urllib.request.urlopen, sleep=time.sleep):
        self.url, self.token, self.opener, self.sleep = url.rstrip('/'), token, opener, sleep

    def call(self, method, path, body=None):
        for attempt in range(3):
            request = urllib.request.Request(self.url + path, method=method, data=json.dumps(body or {}).encode(),
                                             headers={'Authorization': f'Bearer {self.token}',
                                                      'Content-Type': 'application/json'})
            try:
                with self.opener(request, timeout=30) as answer:
                    return json.loads(answer.read() or b'{}')
            except urllib.error.HTTPError as error:
                if error.code < 500 or attempt == 2:
                    raise Refused(f'{method} {path}: {error.code} {error.read().decode("utf-8", "replace")[:300]}',
                                  error.code) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                if attempt == 2:
                    raise Refused(f'{method} {path}: {type(error).__name__}') from None
            self.sleep(2 ** attempt)


def encode(action):
    return 'data:application/json;base64,' + base64.b64encode(json.dumps(action, sort_keys=True).encode()).decode()


class NotProven(RuntimeError):
    pass


class OverCap(RuntimeError):
    pass


def say(*parts):
    print(*parts, flush=True)


def spec(brief):
    return {'provider': PROVIDER, 'brief': brief, 'model': MODEL, 'max_tokens': MAX_TOKENS}


class Proof:
    def __init__(self, port, cap_usd=CAP_USD, window_s=900, tag=None, sleep=time.sleep, clock=time.monotonic,
                 now=lambda: datetime.now(timezone.utc), wait_s=120, natural=False,
                 limit_id=None, original_action=None, executor=EXECUTOR):
        if not 0 < cap_usd <= CAP_USD:
            raise OverCap(f'the cap must be above 0 and at most US$ {CAP_USD}')
        self.port, self.cap, self.window_s, self.tag = port, cap_usd, window_s, tag
        self.sleep, self.clock, self.now, self.wait_s = sleep, clock, now, wait_s
        self.jobs, self.limit, self.natural = {}, None, natural
        self.original, self.limit_id, self.original_action = None, limit_id, original_action
        self.executor = executor

    def events(self, **filters):
        return self.port.call('POST', '/v1/log/query', {'filters': filters, 'limit': 100})['events']

    def spent(self):
        """The US$ the proof's jobs spent so far, at the list price, from their run.usage events."""
        total = 0.0
        for event in self.events(type='run.usage'):
            payload = event['payload']
            if payload.get('job_id') in self.jobs.values():
                meter, quantity = payload.get('meter', ''), float(payload.get('quantity') or 0)
                total += quantity * PRICE_IN if meter.startswith('tokens_in:') else (
                    quantity * PRICE_OUT if meter.startswith('tokens_out:') else 0)
        return total

    def guard(self):
        """Refuse a Bedrock call whose worst case would pass the cap."""
        if self.spent() + WORST_CALL_USD > self.cap:
            raise OverCap(f'a call (worst case US$ {WORST_CALL_USD:.6f}) after US$ {self.spent():.6f} spent would pass '
                          f'the cap of US$ {self.cap}')

    def arm(self):
        """The wait limit of the proof, created or re-armed with a window of window_s seconds."""
        resets_at = (self.now() + timedelta(seconds=self.window_s)).isoformat()
        self.port.call('PUT', f'/v1/queues/{QUEUE}', {'policy': 'fifo'})
        known = [event for event in self.events(type='limit.defined')
                 if event['payload'].get('action') == 'wait' and event['payload'].get('meter') == 'usd']
        if known and not self.limit_id:
            self.limit = known[-1]['subject'].removeprefix('limit/')
            self.port.call('PUT', f'/v1/limits/{self.limit}', {'maximum': LIMIT_MAX, 'resets_at': resets_at,
                                                               'reset_used': True})
        elif self.limit_id:
            self.rearm(self.limit_id, resets_at)
        else:
            try:
                self.limit = self.port.call('POST', '/v1/limits', {
                    'scope': 'executor', 'scope_id': self.executor, 'meter': 'usd', 'maximum': LIMIT_MAX, 'action': 'wait',
                    'resets_at': resets_at})['id']
            except Refused as error:
                if error.status != 409:
                    raise
                self.rearm(self.existing(), resets_at)
        say(f'limit {self.limit}: wait, executor {self.executor}, usd >= {LIMIT_MAX}, window ends {resets_at}')
        return resets_at

    def existing(self):
        """The id of the usd limit that already holds the executor's slot (POST said 409): the only usd limit the log
        defines. With several, the scope is not in the log, so the caller must name it (--limit-id)."""
        ids = []
        for event in self.events(type='limit.defined'):
            if event['payload'].get('meter') == 'usd' and event['subject'].startswith('limit/'):
                ids.append(event['subject'].removeprefix('limit/'))
        ids = list(dict.fromkeys(ids))
        if len(ids) != 1:
            raise NotProven(f'the limit exists (409) but {len(ids)} usd limits are defined ({", ".join(ids)}); '
                            'name the one of executor api-bedrock with --limit-id')
        return ids[0]

    def rearm(self, limit_id, resets_at):
        """Re-arm an existing limit as the wait limit, remembering its maximum and action to restore them at the end."""
        state = {}
        for kind in ('limit.defined', 'limit.changed'):
            for event in self.events(type=kind):
                if event.get('subject') == f'limit/{limit_id}':
                    state.update({k: v for k, v in event['payload'].items() if k in ('maximum', 'action')})
        state['action'] = self.original_action or state.get('action')
        if state.get('maximum') is None or not state.get('action'):
            raise NotProven(f'limit {limit_id}: its maximum or action is not in the log; give --original-action')
        self.original = {'maximum': float(state['maximum']), 'action': state['action']}
        self.limit = limit_id
        self.port.call('PUT', f'/v1/limits/{limit_id}', {'action': 'wait', 'maximum': LIMIT_MAX, 'resets_at': resets_at,
                                                         'reset_used': True})
        say(f'limit {limit_id} existed ({self.original["action"]}, usd {self.original["maximum"]}): re-armed, '
            'restored at the end')

    def restore(self):
        """Lift the limit and, if it was one that existed, put back its original maximum and action."""
        self.port.call('PUT', f'/v1/limits/{self.limit}', {'lift': True})
        if self.original:
            self.port.call('PUT', f'/v1/limits/{self.limit}', dict(self.original))
            say(f'limit restored: {self.original["action"]}, usd {self.original["maximum"]}')

    def job(self, name, brief):
        self.guard()
        text = json.dumps(spec(brief), sort_keys=True)
        made = self.port.call('POST', '/v1/jobs', {
            'queue': QUEUE, 'executor': self.executor, 'input_uri': encode(spec(brief)),
            'input_digest': 'sha256:' + hashlib.sha256(text.encode()).hexdigest(),
            'idempotency_key': f'{self.tag}-{name}'})
        self.jobs[name] = made['id']
        say(f'job {name}: {made["id"]} created={made.get("created")}')
        return made['id']

    def until(self, name, states, what):
        """PORT-LONG-POLL: each read is the port's long poll (?wait_s: what is left of the wait, which the port bounds; seen:
        the digest its previous answer's mark gave), answered when the job is not as it was or the wait passes, and asked
        again at once; an answer the port did not hold (an old port, or one with no wake) keeps the 1 s pause."""
        deadline, seen = self.clock() + self.wait_s, None
        while True:
            query = {'wait_s': max(deadline - self.clock(), 0.0), **({'seen': seen} if seen else {})}
            got = self.port.call('GET', f'/v1/jobs/{self.jobs[name]}?' + urllib.parse.urlencode(query))
            if got['state'] in states:
                return got
            mark = got.get(LONG_POLL)
            held = isinstance(mark, dict)
            seen = mark.get('seen') if held else None
            if self.clock() > deadline:
                raise NotProven(f'job {name} did not {what} in {self.wait_s} s (it is {got["state"]})')
            if not held:
                self.sleep(1)

    def report(self):
        for name, job in self.jobs.items():
            for event in self.port.call('POST', '/v1/log/query', {'payload': {'job_id': job}, 'limit': 100})['events']:
                extra = event['payload'].get('until') or ''
                say(f'  {name} {event["occurred_at"]} {event["type"]} {extra}')

    def run(self):
        resets_at = self.arm()
        try:
            self.job('a', 'Reply with the single word OK.')
            a = self.until('a', ('succeeded', 'failed', 'stopped'), 'end')
            if a['state'] != 'succeeded':
                raise NotProven(f'job A ended {a["state"]}')
            self.job('b', 'Reply with the single word READY.')
            held = self.until('b', ('waiting', 'succeeded', 'failed', 'stopped'), 'be held')
            if held['state'] != 'waiting':
                raise NotProven(f'job B was not held: it is {held["state"]} (did job A cross the limit?)')
            waits = [e for e in self.events(type='run.waiting') if e['payload'].get('job_id') == self.jobs['b']]
            if not waits or not waits[-1]['payload'].get('until'):
                raise NotProven('job B waits but the log has no run.waiting with until')
            say(f'job B waiting until {waits[-1]["payload"]["until"]} (reason {waits[-1]["payload"].get("reason")})')
            if self.natural:
                say('waiting for the window to end')
            else:
                self.port.call('PUT', f'/v1/limits/{self.limit}', {'lift': True})
                say('limit lifted')
            b = self.until('b', ('succeeded', 'failed', 'stopped'), 'end after the reset')
            if b['state'] != 'succeeded':
                raise NotProven(f'job B ended {b["state"]}')
            say(f'PROVEN: B was held waiting until {resets_at} and, after the reset, ended succeeded; '
                f'spent about US$ {self.spent():.6f} of US$ {self.cap}')
        finally:
            try:
                self.restore()
            except Exception as error:  # noqa: BLE001
                say(f'could not lift or restore the limit: {error}')
            self.report()


def main(argv=None, environ=None, port=None):
    environ = os.environ if environ is None else environ
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument('--window-s', type=int, default=900)
    args.add_argument('--natural', action='store_true', help='let the window end instead of lifting the limit')
    args.add_argument('--run', default='1')
    args.add_argument('--executor', default=EXECUTOR, help='the session executor to prove on (its usd limit slot must be free)')
    args.add_argument('--cap-usd', type=float, default=CAP_USD)
    args.add_argument('--limit-id', help='the existing usd limit of executor api-bedrock, when several are defined')
    args.add_argument('--original-action', help='its action, when the log does not say (restored at the end)')
    args = args.parse_args(argv)
    if port is None:
        if not environ.get('TOWER_PORT_URL') or not environ.get('TOWER_PORT_TOKEN'):
            print('aws-quota-proof: set TOWER_PORT_URL and TOWER_PORT_TOKEN (the port and the tenant token)',
                  file=sys.stderr)
            return 2
        port = Port(environ['TOWER_PORT_URL'], environ['TOWER_PORT_TOKEN'])
    window = args.window_s if not args.natural else min(args.window_s, 90)
    try:
        proof = Proof(port, args.cap_usd, window, f'quota-proof-{datetime.now(timezone.utc):%Y%m%d}-{args.run}',
                      wait_s=window + 120 if args.natural else 120, natural=args.natural,
                      limit_id=args.limit_id, original_action=args.original_action, executor=args.executor)
        proof.run()
    except OverCap as error:
        print(f'aws-quota-proof: {error}', file=sys.stderr)
        return 2
    except (NotProven, Refused) as error:
        print(f'aws-quota-proof: NOT PROVEN: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
