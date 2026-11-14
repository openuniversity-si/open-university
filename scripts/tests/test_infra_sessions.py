"""The AI session executor (engine-infra-service; INFRA-EXE 3, P4 F3).

Through the port on a throwaway database of the toolchain's PostgreSQL (TI1), the dispatcher hands a session job to the
adapter, which launches it through a fake provider and follows it: a session runs and ends with its tokens per model as
run.usage; an exhausted quota makes the job wait until the reset, and then the session resumes; a job cancelled while
its session runs ends the session and gives its slot back; a provider that is not configured refuses the run and
launches nothing; an input it does not understand is refused; a launch that fails (no key, the account's limit) is a
refused run, never a workflow left to its lease; and the same work runs through the container executor and through a
session, by the same port; an API call's tokens in and out reach the log and the tenant's meter rates price them in a
limit of dollars (D-310). The Cursor Cloud Agents provider runs against a stand-in for Cursor's REST API, in the
shapes the official @cursor/sdk 1.3.1 calls. No network.
"""
from concurrent.futures import wait
import contextlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from http import HTTPStatus
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from infra_db.psql import migrated  # noqa: E402
import test_db  # noqa: E402
from tower_infra import api_sessions, cli_sessions, cursor_agents, forge, http_port, mechanisms, port, runner, sessions  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
RESET = datetime.fromisoformat('2026-11-04T21:00:00+00:00')  # when the fake subscription's quota comes back
BEFORE, AFTER = RESET - timedelta(minutes=1), RESET + timedelta(minutes=1)
RUNNING = {'state': 'running'}
WAITING = {'state': 'waiting', 'until': RESET.isoformat()}
ENDED = {'state': 'ended', 'outcome': 'succeeded', 'result': {'summary': 'the brief is done'},
         'tokens': {'model-a': int('1200'), 'model-b': int('300')}}


class Provider:
    """A subscription that answers, on each follow, the next state it was given (the last one repeats)."""

    def __init__(self, *states):
        self.states, self.calls = list(states), []

    def launch(self, spec):
        self.calls.append(('launch', spec['brief']))
        return 'session-of-the-test'

    def follow(self, session):
        self.calls.append(('follow', session))
        return self.states.pop(0) if len(self.states) > 1 else self.states[0]

    def resume(self, session):
        self.calls.append(('resume', session))

    def end(self, session):
        self.calls.append(('end', session))


class Sessioned(unittest.TestCase):
    def setUp(self):
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        for method, path, token, body in (
                ('POST', '/v1/tenants', 'installation', {'name': 'torre', 'token_sha256': port.sha256('torre')}),
                ('POST', '/v1/executors', 'installation', {'name': 'claude-code', 'adapter': 'session'}),
                ('PUT', '/v1/executors/claude-code/capacity/subscription', 'installation', {'slots': '2'}),
                ('POST', '/v1/executors', 'installation', {'name': 'fargate-runner', 'adapter': 'container'}),
                ('PUT', '/v1/executors/fargate-runner/capacity/spot', 'installation', {'slots': '1'}),
                ('PUT', '/v1/queues/default', 'torre', {'policy': 'fifo'})):
            self.call(method, path, token, body)

    def call(self, method, path, token, body=None):
        answer = http_port.handle({'rawPath': path, 'requestContext': {'http': {'method': method}},
                                   'headers': {'Authorization': f'Bearer {token}'}, 'body': json.dumps(body or {})},
                                  self.db, port.sha256('installation'))
        return json.loads(answer['body'])

    def job(self, key, spec, executor='claude-code'):
        return self.call('POST', '/v1/jobs', 'torre', {'executor': executor, 'input_uri': forge.encode(spec),
                                                       'input_digest': 'sha256:' + key, 'idempotency_key': key})['id']

    def adapter(self, provider):
        return sessions.Sessions(lambda: contextlib.nullcontext(self.db), {'fake': provider})

    def started(self, adapter):
        """What the service's workflow does with a claimed run: hand it to its adapter, and end it if it answered."""
        for run in mechanisms.dispatch(self.db):
            if run.get('adapter') == 'session':
                ended = adapter.start(run)
                if ended:
                    mechanisms.finish(self.db, run, ended)

    def state(self, job):
        return self.db.rows('select state from work.job where id = %(id)s::uuid', {'id': job})[0][0]


class Lifecycle(Sessioned):
    def test_a_session_runs_and_ends_with_its_tokens_per_model(self):
        job = self.job('runs', {'provider': 'fake', 'brief': 'write the test'})
        fake = Provider(RUNNING, ENDED)
        adapter = self.adapter(fake)
        self.started(adapter)
        self.assertEqual(self.db.rows('select external_id from work.run where job_id = %(id)s::uuid', {'id': job}),
                         [('session-of-the-test',)])
        self.assertEqual((adapter.follow(self.db), self.state(job)), ({}, 'running'))
        self.assertEqual(list(adapter.follow(self.db).values()), ['ended'])
        self.assertEqual(self.state(job), 'succeeded')
        usage = self.call('POST', '/v1/log/query', 'torre', {'filters': {'type': 'run.usage'},
                                                             'payload': {'job_id': job}})['events']
        self.assertEqual(sorted((event['payload']['meter'], event['payload']['quantity']) for event in usage),
                         sorted((f'tokens:{model}', count) for model, count in ENDED['tokens'].items()))
        self.assertEqual(self.call('GET', f'/v1/jobs/{job}', 'torre')['result'], ENDED['result'])

    def test_an_api_calls_tokens_in_and_out_reach_the_log_and_the_tenants_rates_price_them(self):
        # D-310: the cost reads from the log; the money is the tenant's meter rates (D-308), here a limit in dollars.
        model = 'anthropic.claude-haiku-5-5'
        tenant = self.db.rows("select id::text from work.tenant where name = 'torre'")[0][0]
        for meter, rate in ((f'tokens_in:{model}', '0.0000001'), (f'tokens_out:{model}', '0.0000005')):
            self.call('PUT', '/v1/meter-rates', 'torre', {'meter': meter, 'derived_meter': 'usd', 'rate': rate})
        self.call('POST', '/v1/limits', 'torre', {'scope': 'tenant', 'scope_id': tenant, 'meter': 'usd',
                                                  'maximum': '1', 'action': 'stop'})
        calls = api_sessions.Calls(lambda spec, asked: api_sessions.completion('OK', asked, int('20'), int('4')),
                                   models=(model,))
        adapter = sessions.Sessions(lambda: contextlib.nullcontext(self.db), {'bedrock': calls})
        job = self.job('api', {'provider': 'bedrock', 'brief': 'Answer only OK.', 'model': model})
        self.started(adapter)
        session, = self.db.rows('select external_id from work.run where job_id = %(id)s::uuid', {'id': job})[0]
        wait([calls.calls[session]['future']])
        self.assertEqual(list(adapter.follow(self.db).values()), ['ended'])
        self.assertEqual(self.state(job), 'succeeded')
        usage = {event['payload']['meter']: event['payload']['quantity'] for event in self.call(
            'POST', '/v1/log/query', 'torre', {'filters': {'type': 'run.usage'}, 'payload': {'job_id': job}})['events']}
        self.assertEqual({meter: usage[meter] for meter in (f'tokens_in:{model}', f'tokens_out:{model}',
                                                            f'tokens:{model}')},
                         {f'tokens_in:{model}': int('20'), f'tokens_out:{model}': int('4'), f'tokens:{model}': int('24')})
        self.assertIn(f'api_s:{model}', usage)
        spent, = self.db.rows("select used from work.limits where meter = 'usd'")[0]
        self.assertEqual(Decimal(spent), Decimal('0.000004'))  # 20 x 0.0000001 + 4 x 0.0000005

    def test_an_exhausted_quota_makes_the_job_wait_until_the_reset_and_then_the_session_resumes(self):
        job = self.job('quota', {'provider': 'fake', 'brief': 'a long brief'})
        fake = Provider(WAITING, WAITING, WAITING, RUNNING, ENDED)
        adapter = self.adapter(fake)
        self.started(adapter)
        adapter.follow(self.db, now=BEFORE)
        self.assertEqual(self.state(job), 'waiting')
        self.assertEqual((adapter.follow(self.db, now=BEFORE), self.state(job)), ({}, 'waiting'))  # not yet
        self.assertEqual(list(adapter.follow(self.db, now=AFTER).values()), ['resumed'])
        self.assertEqual((self.state(job), fake.calls.count(('resume', 'session-of-the-test'))), ('running', 1))
        adapter.follow(self.db, now=AFTER)
        adapter.follow(self.db, now=AFTER)
        self.assertEqual(self.state(job), 'succeeded')
        waited = self.call('POST', '/v1/log/query', 'torre', {'filters': {'type': 'run.waiting'},
                                                              'payload': {'job_id': job}})['events']
        self.assertEqual([event['payload']['until'] for event in waited], [RESET.isoformat()])

    def test_a_job_cancelled_while_its_session_runs_ends_the_session_and_gives_its_slot_back(self):
        job = self.job('cancelled', {'provider': 'fake', 'brief': 'a brief nobody wants now'})
        fake = Provider(RUNNING)
        adapter = self.adapter(fake)
        self.started(adapter)
        self.call('POST', f'/v1/jobs/{job}/cancel', 'torre')
        adapter.follow(self.db)
        self.assertEqual((self.state(job), fake.calls[-1]), ('cancelled', ('end', 'session-of-the-test')))
        self.assertEqual(self.db.rows("select in_use from work.capacity where executor = 'claude-code'"), [('0',)])

    def test_a_provider_not_configured_refuses_the_run_and_launches_nothing(self):
        job = self.job('nobody', {'provider': 'a-subscription-of-nobody', 'brief': 'a brief'})
        fake = Provider(RUNNING)
        self.started(self.adapter(fake))
        runs = self.call('GET', f'/v1/jobs/{job}', 'torre')['runs']
        self.assertEqual((self.state(job), runs[-1]['error_type'], fake.calls), ('failed', 'refused', []))

    def test_a_launch_that_fails_is_a_refused_run(self):
        class Failing(Provider):
            def launch(self, spec):
                raise cursor_agents.NoKey('no Cursor key for the session executor')
        job = self.job('failing', {'provider': 'fake', 'brief': 'a brief'})
        self.started(self.adapter(Failing(RUNNING)))
        runs = self.call('GET', f'/v1/jobs/{job}', 'torre')['runs']
        self.assertEqual((self.state(job), runs[-1]['error_type']), ('failed', 'refused'))

    def test_an_input_it_does_not_understand_is_refused(self):
        for key, spec in (('no-brief', {'provider': 'fake'}), ('empty', {'provider': 'fake', 'brief': ' '})):
            job = self.job(key, spec)
            self.started(self.adapter(Provider(RUNNING)))
            self.assertEqual(self.call('GET', f'/v1/jobs/{job}', 'torre')['runs'][-1]['error_type'], 'not_understood')


class TheSameWork(Sessioned):
    def test_the_same_work_runs_through_the_container_and_through_a_session_by_the_same_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            def fetch(spec, checkout):
                checkout.mkdir(parents=True, exist_ok=True)
            worker = runner.Runner(self.db, fetch, lambda checkout: None, lambda run, log: 'kept', tmp)
            commit = '0123456789abcdef0123456789abcdef01234567'
            by_container = self.job('by-container', {'repo': 'openuniversity-si/open-university', 'commit': commit,
                                                     'command': ['sh', '-c', 'echo the work is done']},
                                    executor='fargate-runner')
            by_session = self.job('by-session', {'provider': 'fake', 'brief': 'do the work'})
            adapter = self.adapter(Provider(ENDED))
            self.started(adapter)
            worker.once()
            adapter.follow(self.db)
        self.assertEqual((self.state(by_container), self.state(by_session)), ('succeeded', 'succeeded'))
        ended = self.call('POST', '/v1/log/query', 'torre', {'filters': {'type': 'run.ended'}})['events']
        self.assertEqual(sorted(event['payload']['executor'] for event in ended), ['claude-code', 'fargate-runner'])


class Answer:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class CursorAgentsTransport(unittest.TestCase):
    """The Cursor Cloud Agents provider against a stand-in for Cursor's REST API (the shapes @cursor/sdk 1.3.1 calls)."""

    def setUp(self):
        self.asked, self.answers = [], []

    def opener(self, request, timeout):
        self.asked.append((request.get_method(), request.full_url.split('.com', 1)[-1], request.headers,
                           json.loads(request.data) if request.data else None))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Answer(json.dumps(answer))

    def provider(self, key='key-of-the-test'):
        return cursor_agents.CursorAgents(lambda: key, opener=self.opener, now=lambda: RESET)

    def test_a_launch_creates_the_agent_with_the_brief_and_answers_its_run(self):
        self.answers = [{'agent': {'id': 'bc-agent'}, 'run': {'id': 'run-1'}}]
        session = self.provider().launch({'brief': 'write the test', 'repos': [{'url': 'repo-url', 'ref': 'base'}],
                                          'model': 'composer-2', 'idempotency_key': 'the-job'})
        method, path, headers, body = self.asked[0]
        self.assertEqual((session, method, path), ('bc-agent/run-1', 'POST', '/v1/agents'))
        self.assertEqual(body, {'prompt': {'text': 'write the test'}, 'repos': [{'url': 'repo-url', 'startingRef': 'base'}],
                                'model': 'composer-2'})
        self.assertEqual((headers['Authorization'], headers['Idempotency-key']), ('Bearer key-of-the-test', 'the-job'))

    def test_a_run_that_finished_ends_with_its_result_and_its_tokens(self):
        self.answers = [{'status': 'FINISHED', 'result': 'done', 'model': 'composer-2'},
                        {'usage': {'totalTokens': int('4321')}}]
        seen = self.provider().follow('bc-agent/run-1')
        self.assertEqual((seen['state'], seen['outcome'], seen['tokens'], seen['result']),
                         ('ended', 'succeeded', {'composer-2': int('4321')}, {'result': 'done'}))
        self.assertEqual([path for _, path, _, _ in self.asked],
                         ['/v1/agents/bc-agent/runs/run-1', '/v1/agents/bc-agent/usage?runId=run-1'])

    def test_running_errors_and_the_limit(self):
        self.answers = [{'status': 'RUNNING'}, {'status': 'ERROR'}, {'usage': {}},
                        urllib.error.HTTPError('u', HTTPStatus.TOO_MANY_REQUESTS, 'limit', {}, None)]
        provider = self.provider()
        self.assertEqual(provider.follow('a/r'), {'state': 'running'})
        self.assertEqual(provider.follow('a/r')['outcome'], 'failed')
        self.assertEqual(provider.follow('a/r'), {'state': 'waiting', 'until': (RESET + timedelta(minutes=1)).isoformat()})

    def test_a_refusal_keeps_its_status_and_body_without_the_key(self):
        body = '{"error":"bad repo"} echo key-of-the-test ' + 'x' * 600
        self.answers = [urllib.error.HTTPError('u', HTTPStatus.BAD_REQUEST, 'Bad Request', {}, io.BytesIO(body.encode()))]
        with self.assertRaises(cursor_agents.CursorError) as caught:
            self.provider().launch({'brief': 'x'})
        message = str(caught.exception)
        self.assertEqual(caught.exception.code, HTTPStatus.BAD_REQUEST)
        self.assertTrue(message.startswith('HTTP 400: {"error":"bad repo"} echo [redacted] xxx'))
        self.assertNotIn('key-of-the-test', message)
        self.assertEqual(len(caught.exception.body), 500)

    def test_a_refusal_without_a_readable_body_still_names_the_status(self):
        self.answers = [urllib.error.HTTPError('u', HTTPStatus.BAD_REQUEST, 'Bad Request', {}, None)]
        with self.assertRaises(cursor_agents.CursorError) as caught:
            self.provider().launch({'brief': 'x'})
        self.assertEqual(str(caught.exception), 'HTTP 400: ')

    def test_a_refused_launch_puts_the_status_and_body_in_the_failure_detail(self):
        self.answers = [urllib.error.HTTPError('u', HTTPStatus.BAD_REQUEST, 'Bad Request', {}, io.BytesIO(b'no such repo'))]
        failed = sessions.Sessions(None, {'cursor': self.provider()}).start(
            {'run': 'r', 'fence': 1, 'input_uri': forge.encode({'provider': 'cursor', 'brief': 'x'})})
        self.assertIn('CursorError: HTTP 400: no such repo', json.dumps(failed))

    def test_end_cancels_the_run_and_no_key_refuses(self):
        self.answers = [{}]
        self.provider().end('bc-agent/run-1')
        method, path, _, _ = self.asked[0]
        self.assertEqual((method, path), ('POST', '/v1/agents/bc-agent/runs/run-1/cancel'))
        with self.assertRaises(cursor_agents.NoKey):
            self.provider(key=None).launch({'brief': 'x'})


class Waits(Sessioned):
    """AWS12: a limit that waits (migration 0007) and a capacity whose reset is still to come hold work `waiting` until
    the reset, through the same states the provider's throttle uses; stop and refuse are as they were."""

    LATER = '2099-01-01T00:00:00+00:00'

    def setUp(self):
        super().setUp()
        self.call('POST', '/v1/tenants', 'installation', {'name': 'other', 'token_sha256': port.sha256('other')})

    def status(self, method, path, token, body=None):
        return http_port.handle({'rawPath': path, 'requestContext': {'http': {'method': method}},
                                 'headers': {'Authorization': f'Bearer {token}'}, 'body': json.dumps(body or {})},
                                self.db, port.sha256('installation'))['statusCode']

    def limit(self, action='wait', maximum=1000, resets_at=None, scope='tenant', meter='tokens:model-a'):
        tenant = self.db.rows("select id::text from work.tenant where name = 'torre'")[0][0]
        body = {'scope': scope, 'scope_id': tenant, 'meter': meter, 'maximum': maximum, 'action': action}
        if resets_at or action == 'wait':
            body['resets_at'] = resets_at or self.LATER
        return self.call('POST', '/v1/limits', 'torre', body)['id']

    def events(self, kind, job=None):
        found = self.call('POST', '/v1/log/query', 'torre', {'filters': {'type': kind},
                                                             **({'payload': {'job_id': job}} if job else {})})
        return [event['payload'] for event in found['events']]

    def spend(self, adapter, key='a'):
        """A job whose session ends having spent 1200 tokens of model-a."""
        job = self.job(key, {'provider': 'fake', 'brief': key})
        self.started(adapter)
        adapter.follow(self.db)
        self.assertEqual(self.state(job), 'succeeded')
        return job

    def test_a_wait_limit_reached_holds_the_next_job_waiting_until_the_reset_with_no_run_and_no_slot(self):
        limit = self.limit()
        adapter = self.adapter(Provider(ENDED))
        self.spend(adapter)
        job = self.job('b', {'provider': 'fake', 'brief': 'b'})
        self.assertEqual(mechanisms.dispatch(self.db), [])
        self.assertEqual(self.state(job), 'waiting')
        self.assertEqual(self.db.rows('select count(*) from work.run where job_id = %(id)s::uuid', {'id': job}),
                         [('0',)])
        self.assertEqual(self.db.rows("select in_use from work.capacity where executor = 'claude-code'"), [('0',)])
        held = self.events('run.waiting', job)
        self.assertEqual([(e['reason'], e['limit_id'], e['until'][:10]) for e in held], [('limit', limit, '2099-01-01')])
        self.assertEqual(mechanisms.dispatch(self.db), [])  # still held, and not announced again
        self.assertEqual(len(self.events('run.waiting', job)), 1)
        got = self.call('GET', f'/v1/jobs/{job}', 'torre')
        self.assertEqual((got['state'], got['wait_reason']), ('waiting', 'limit'))

    def test_lifting_the_limit_wakes_the_job_and_it_runs_to_the_end(self):
        limit = self.limit()
        adapter = self.adapter(Provider(ENDED))
        self.spend(adapter)
        job = self.job('b', {'provider': 'fake', 'brief': 'b'})
        mechanisms.dispatch(self.db)
        changed = self.call('PUT', f'/v1/limits/{limit}', 'torre', {'lift': True})
        self.assertEqual(changed['used'], 0)
        self.started(adapter)
        self.assertEqual(self.state(job), 'running')
        self.assertEqual(len(self.events('job.woken', job)), 1)
        self.assertEqual(self.events('limit.changed')[0]['limit_id'], limit)
        adapter.follow(self.db)
        self.assertEqual(self.state(job), 'succeeded')

    def test_at_the_reset_the_window_rolls_and_the_held_job_goes(self):
        limit = self.limit(resets_at=(datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat())
        adapter = self.adapter(Provider(ENDED))
        self.spend(adapter)
        job = self.job('b', {'provider': 'fake', 'brief': 'b'})
        mechanisms.dispatch(self.db)
        self.assertEqual(self.state(job), 'waiting')
        time.sleep(2.2)
        self.started(adapter)
        self.assertEqual(self.state(job), 'running')
        self.assertEqual(self.db.rows('select used from work.limits where id = %(id)s::uuid', {'id': limit}), [('0',)])
        self.assertEqual(len(self.events('limit.reset')), 1)

    def test_a_run_whose_usage_crosses_the_limit_waits_until_the_reset_and_the_session_resumes_after_it(self):
        limit = self.limit(maximum=100, meter='calls')
        fake = Provider(RUNNING, RUNNING, ENDED)
        adapter = self.adapter(fake)
        job = self.job('c', {'provider': 'fake', 'brief': 'c'})
        self.started(adapter)
        run = self.db.rows("select r.id::text, j.fencing_token from work.run r join work.job j on j.id = r.job_id "
                           "where j.id = %(id)s::uuid", {'id': job})[0]
        mechanisms.relay(self.db, run[0], int(run[1]), 'run.usage', {'meter': 'calls', 'quantity': 150})
        self.assertEqual(self.state(job), 'waiting')
        held = self.events('run.waiting', job)
        self.assertEqual([(e['reason'], e['run_id']) for e in held], [('limit', run[0])])
        self.assertEqual(adapter.follow(self.db), {})  # the provider runs on, but the run waits for the reset
        self.assertEqual(self.state(job), 'waiting')
        self.call('PUT', f'/v1/limits/{limit}', 'torre', {'lift': True})
        self.assertEqual(list(adapter.follow(self.db).values()), ['resumed'])
        self.assertEqual(self.state(job), 'running')
        adapter.follow(self.db)
        self.assertEqual(self.state(job), 'succeeded')

    def test_a_capacity_with_no_slots_and_a_reset_to_come_holds_the_job_until_the_reset(self):
        self.call('PUT', '/v1/executors/claude-code/capacity/subscription', 'installation',
                  {'slots': '0', 'resets_at': self.LATER})
        job = self.job('d', {'provider': 'fake', 'brief': 'd'})
        self.assertEqual(mechanisms.dispatch(self.db), [])
        self.assertEqual(self.state(job), 'waiting')
        self.assertEqual([e['reason'] for e in self.events('run.waiting', job)], ['capacity'])
        mechanisms.dispatch(self.db)
        self.assertEqual(len(self.events('run.waiting', job)), 1)
        self.call('PUT', '/v1/executors/claude-code/capacity/subscription', 'installation', {'slots': '1'})
        self.started(self.adapter(Provider(RUNNING)))
        self.assertEqual(self.state(job), 'running')

    def test_a_capacity_reset_that_passed_wakes_the_job_and_one_still_at_no_slots_leaves_it_queued(self):
        soon = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
        self.call('PUT', '/v1/executors/claude-code/capacity/subscription', 'installation',
                  {'slots': '0', 'resets_at': soon})
        job = self.job('e', {'provider': 'fake', 'brief': 'e'})
        mechanisms.dispatch(self.db)
        self.assertEqual(self.state(job), 'waiting')
        time.sleep(2.2)
        self.assertEqual(mechanisms.dispatch(self.db), [])
        self.assertEqual(self.state(job), 'queued')  # woken at the reset; the owner has not given slots yet
        self.assertEqual(len(self.events('job.woken', job)), 1)
        mechanisms.dispatch(self.db)
        self.assertEqual(len(self.events('run.waiting', job)), 1)  # not held again: the reset has passed

    def test_the_port_validates_and_keeps_a_limit_to_its_tenant(self):
        tenant = self.db.rows("select id::text from work.tenant where name = 'torre'")[0][0]
        body = {'scope': 'tenant', 'scope_id': tenant, 'meter': 'usd', 'maximum': 1, 'action': 'wait'}
        self.assertEqual(self.status('POST', '/v1/limits', 'torre', body), 400)  # no resets_at
        self.assertEqual(self.status('POST', '/v1/limits', 'torre', {**body, 'action': 'pause'}), 400)
        limit = self.limit(meter='usd')
        self.assertEqual(self.status('POST', '/v1/limits', 'torre', {**body, 'resets_at': self.LATER}), 409)
        self.assertEqual(self.status('PUT', f'/v1/limits/{limit}', 'other', {'lift': True}), 404)
        self.assertEqual(self.status('PUT', f'/v1/limits/{limit}', 'installation', {'lift': True}), 403)
        self.assertEqual(self.status('PUT', f'/v1/limits/{limit}', 'torre', {'colour': 'red'}), 400)
        self.assertEqual(self.status('PUT', f'/v1/limits/{limit}', 'torre', {'action': 'wait', 'resets_at': None}), 400)
        self.assertEqual(self.db.rows('select used, maximum from work.limits where id = %(id)s::uuid', {'id': limit}),
                         [('0', '1000')])
        raised = self.call('PUT', f'/v1/limits/{limit}', 'torre', {'maximum': 5, 'resets_at': self.LATER})
        self.assertEqual(raised['maximum'], 5)
        defined = self.events('limit.defined')
        self.assertEqual((defined[0]['action'], defined[0]['resets_at'][:4]), ('wait', '2099'))

    def test_stop_and_refuse_limits_work_as_before(self):
        stop = self.limit(action='stop', maximum=1000)
        adapter = self.adapter(Provider(RUNNING, ENDED))
        job = self.job('s', {'provider': 'fake', 'brief': 's'})
        self.started(adapter)
        run = self.db.rows("select r.id::text, j.fencing_token from work.run r join work.job j on j.id = r.job_id "
                           "where j.id = %(id)s::uuid", {'id': job})[0]
        mechanisms.relay(self.db, run[0], int(run[1]), 'run.usage', {'meter': 'tokens:model-a', 'quantity': 1200})
        self.assertEqual(self.state(job), 'stopped')
        self.assertEqual(self.events('run.waiting', job), [])
        self.assertEqual(self.status('PUT', f'/v1/limits/{stop}', 'torre', {'maximum': 5000}), 200)
        refuse = self.limit(action='refuse', maximum=0, meter='refused')
        self.assertTrue(refuse)
        self.assertEqual(self.status('POST', '/v1/jobs', 'torre', {
            'executor': 'claude-code', 'input_uri': forge.encode({'provider': 'fake', 'brief': 'r'}),
            'input_digest': 'sha256:r', 'idempotency_key': 'r'}), 409)


class Done:
    def __init__(self, out='', code=0, err=''):
        self.stdout, self.returncode, self.stderr = out, code, err


class CliSubscriptions(unittest.TestCase):
    """claude-code and codex as providers, against an injected runner, clock and OAuth call: no CLI, no network, no wall clock."""
    NOW = 1_800_000_000
    CLAUDE = {'claudeAiOauth': {'accessToken': 'at-secret-old', 'refreshToken': 'rt-secret-old',
                                'expiresAt': (1_800_000_000 + 7200) * 1000}}
    SPEC = {'provider': 'claude-code', 'brief': 'do the thing', 'repos': [{'url': 'https://forge/x/app.git', 'ref': 'main'}]}

    def setUp(self):
        self.CLAUDE = json.loads(json.dumps(self.CLAUDE))
        self.calls, self.seen_home, self.saved, self.files = [], [], [], {}
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(self.tmp, ignore_errors=True))
        self.out = Done(json.dumps({'is_error': False, 'result': 'PR https://forge/pr/1', 'total_cost_usd': 0.5,
                                    'duration_ms': 9, 'modelUsage': {'claude-x': {'inputTokens': 100, 'outputTokens': 20}}}))

    def runner(self, argv, cwd=None, env=None, input=None, **_):
        self.calls.append((argv, str(cwd), input))
        home = Path(env['HOME'])
        if argv[0] == 'claude' or argv[0] == 'codex':
            self.seen_home.append(home)
            self.files = {str(p.relative_to(home)): oct(p.stat().st_mode & 0o777) for p in home.rglob('*') if p.is_file()
                          and 'work' not in p.parts}
            self.mode = oct(home.stat().st_mode & 0o777)
            self.env = dict(env)
            self.codex_write = lambda text: (home / '.codex' / 'auth.json').write_text(text)
            if self.mutate:
                self.mutate(home)
            return self.out
        return Done()
    mutate = None

    def made(self, text=None, save='default', **kw):
        stored = {'claude-code': json.dumps(self.CLAUDE) if text is None else text, 'codex': '{"tokens": {"access_token": "cx-secret"}}'}
        saver = (lambda name, value: self.saved.append((name, value))) if save == 'default' else save
        return cli_sessions.providers(lambda name: stored[name], saver, lambda: 'forge-key-secret', run=self.runner,
                                      clock=lambda: self.NOW, spawn=lambda fn: fn(), tmp=self.tmp,
                                      ids=lambda: 'id1', environ={'PATH': '/bin'}, **kw)

    def test_claude_runs_in_a_private_home_with_the_brief_and_reports_tokens_and_cost_and_leaves_nothing(self):
        provider = self.made()['claude-code']
        session = provider.launch(self.SPEC)
        seen = provider.follow(session)
        self.assertEqual((seen['state'], seen['outcome'], seen['tokens']), ('ended', 'succeeded', {'claude-x': 120}))
        self.assertEqual(seen['result']['total_cost_usd'], 0.5)
        self.assertEqual(self.mode, '0o700')
        self.assertEqual(self.files['.claude/.credentials.json'], '0o600')
        self.assertIn('do the thing', self.calls[-1][2])
        self.assertEqual(self.calls[-1][0][:2], ['claude', '-p'])
        self.assertEqual([p for p in Path(self.tmp).iterdir()], [])  # the home and its checkout are gone
        self.assertEqual(self.saved, [])  # the CLI did not rotate anything: nothing is written back
        self.assertNotIn('secret', json.dumps(seen))

    CODEX2 = json.dumps({'tokens': {'access_token': 'cx-secret-2', 'refresh_token': 'cr-secret-2'},
                         'last_refresh': '2030-01-01T00:00:00Z'})
    ROTATED = '{"claudeAiOauth": {"accessToken": "at-secret-new", "refreshToken": "rt-secret-new", "expiresAt": 9999999999999}}'

    def test_the_stored_credentials_go_into_the_home_as_they_are_and_a_token_the_cli_rotated_is_written_back(self):
        self.mutate = lambda home: (home / '.claude' / '.credentials.json').write_text(self.ROTATED)
        provider = self.made()['claude-code']
        seen = provider.follow(provider.launch(self.SPEC))
        self.assertEqual(self.saved, [('/tower/sessions/claude-code', self.ROTATED)])
        self.assertEqual(seen['outcome'], 'succeeded')
        self.assertNotIn('credentials_unsaved', seen['result'])
        self.assertNotIn('secret', json.dumps(seen))

    def test_the_cli_finds_the_stored_text_unchanged_in_its_own_credentials_file(self):
        stored = json.dumps(self.CLAUDE)
        self.mutate = lambda home: setattr(self, 'found', (home / '.claude' / '.credentials.json').read_text())
        provider = self.made()['claude-code']
        provider.follow(provider.launch(self.SPEC))
        self.assertEqual(self.found, stored)

    def test_a_rotated_token_is_written_back_also_when_the_run_fails(self):
        self.mutate = lambda home: (home / '.claude' / '.credentials.json').write_text(self.ROTATED)
        self.out = Done('', 1, 'boom at-secret-new')
        provider = self.made()['claude-code']
        seen = provider.follow(provider.launch(self.SPEC))
        self.assertEqual(seen['outcome'], 'failed')
        self.assertEqual(self.saved, [('/tower/sessions/claude-code', self.ROTATED)])
        self.assertNotIn('secret', json.dumps(seen))

    def test_a_rotated_token_is_written_back_also_when_the_cli_times_out(self):
        def timeout_after_rotating(argv, **kw):
            if argv[0] == 'claude':
                Path(kw['env']['HOME'], '.claude', '.credentials.json').write_text(self.ROTATED)
                raise subprocess.TimeoutExpired(argv, 1)
            return self.runner(argv, **kw)
        provider = cli_sessions.providers(lambda name: json.dumps(self.CLAUDE), lambda n, v: self.saved.append((n, v)),
                                          lambda: 'forge-key-secret', run=timeout_after_rotating, spawn=lambda fn: fn(),
                                          tmp=self.tmp, environ={})['claude-code']
        seen = provider.follow(provider.launch(self.SPEC))
        self.assertEqual(seen['outcome'], 'failed')
        self.assertEqual(self.saved, [('/tower/sessions/claude-code', self.ROTATED)])
        self.assertNotIn('secret', json.dumps(seen))

    def leave(self, text, outcome=None):
        self.mutate = lambda home: (home / '.claude' / '.credentials.json').write_text(text)
        if outcome:
            self.out = outcome
        provider = self.made()['claude-code']
        return provider.follow(provider.launch(self.SPEC))

    def test_a_failed_run_that_left_an_empty_credential_writes_nothing_and_says_why(self):
        empty = json.dumps({'claudeAiOauth': {'accessToken': '', 'refreshToken': '', 'expiresAt': 0}})
        seen = self.leave(empty, Done('', 1, 'boom'))
        self.assertEqual((seen['outcome'], self.saved), ('failed', []))
        self.assertIn('empty token', seen['result']['credentials_unsaved'])

    def test_a_file_that_does_not_parse_or_misses_fields_writes_nothing(self):
        for junk in ('', '{not json', '{}', json.dumps({'claudeAiOauth': {'accessToken': 'a', 'refreshToken': 'r'}}),
                     json.dumps({'claudeAiOauth': {'accessToken': 'a', 'refreshToken': 'r', 'expiresAt': 'soon'}}),
                     json.dumps({'claudeAiOauth': {'accessToken': 'a', 'refreshToken': ' ', 'expiresAt': 9e12}})):
            for out in (None, Done('', 1, 'boom')):
                seen = self.leave(junk, out)
                self.assertEqual(self.saved, [], junk)
                self.assertTrue(seen['result']['credentials_unsaved'])

    def test_an_older_or_equal_expiry_than_the_stored_one_writes_nothing(self):
        for expires in (1, (self.NOW + 7200) * 1000):
            older = json.dumps({'claudeAiOauth': {'accessToken': 'a-secret', 'refreshToken': 'r-secret', 'expiresAt': expires}})
            seen = self.leave(older)
            self.assertEqual(self.saved, [])
            self.assertIn('no newer', seen['result']['credentials_unsaved'])
            self.assertNotIn('secret', json.dumps(seen))

    def test_a_newer_valid_credential_is_written(self):
        seen = self.leave(self.ROTATED)
        self.assertEqual(self.saved, [('/tower/sessions/claude-code', self.ROTATED)])
        self.assertNotIn('credentials_unsaved', seen['result'])

    def test_the_parameter_is_re_read_at_write_back_and_a_newer_one_the_torre_stored_is_kept(self):
        reads, torre = [], json.dumps({'claudeAiOauth': {'accessToken': 'a', 'refreshToken': 'r', 'expiresAt': 99999999999999}})

        def read(name):
            reads.append(name)
            return json.dumps(self.CLAUDE) if len(reads) < 3 else torre  # changed after the job started
        self.mutate = lambda home: (home / '.claude' / '.credentials.json').write_text(self.ROTATED)
        provider = cli_sessions.providers(read, lambda n, v: self.saved.append((n, v)), lambda: 'k', run=self.runner,
                                          spawn=lambda fn: fn(), tmp=self.tmp, environ={})['claude-code']
        seen = provider.follow(provider.launch(self.SPEC))
        self.assertEqual(self.saved, [])
        self.assertIn('changed during the run', seen['result']['credentials_unsaved'])

    def test_the_credential_is_read_at_every_job(self):
        reads = []
        def read(name):
            reads.append(name)
            return json.dumps(self.CLAUDE)
        provider = cli_sessions.providers(read, lambda n, v: self.saved.append((n, v)), lambda: 'k', run=self.runner,
                                          spawn=lambda fn: fn(), tmp=self.tmp, environ={})['claude-code']
        provider.follow(provider.launch(self.SPEC))
        first = len(reads)
        provider.follow(provider.launch(self.SPEC))
        self.assertEqual(len(reads), 2 * first)
        self.assertGreaterEqual(first, 2)  # launch check, job start (and write-back when the file changed)

    def test_codex_older_or_empty_auth_is_not_written_and_a_newer_by_last_refresh_is(self):
        old = json.dumps({'tokens': {'access_token': 'x', 'refresh_token': 'y'}, 'last_refresh': '2020-01-01T00:00:00Z'})
        stored = {'claude-code': '{}', 'codex': json.dumps({'tokens': {'access_token': 'x', 'refresh_token': 'y'},
                                                           'last_refresh': '2025-01-01T00:00:00Z'})}
        for left in (old, '{"tokens": {"access_token": "", "refresh_token": ""}}', '{"OPENAI_API_KEY": "sk-secret"}', 'nope'):
            self.mutate = lambda home, left=left: (home / '.codex' / 'auth.json').write_text(left)
            provider = cli_sessions.providers(lambda n: stored[n], lambda n, v: self.saved.append((n, v)), lambda: 'k',
                                              run=self.runner, spawn=lambda fn: fn(), tmp=self.tmp, environ={})['codex']
            seen = provider.follow(provider.launch(dict(self.SPEC, provider='codex')))
            self.assertEqual(self.saved, [])
            self.assertTrue(seen['result']['credentials_unsaved'])
        self.mutate = lambda home: (home / '.codex' / 'auth.json').write_text(self.CODEX2)
        provider = cli_sessions.providers(lambda n: stored[n], lambda n, v: self.saved.append((n, v)), lambda: 'k',
                                          run=self.runner, spawn=lambda fn: fn(), tmp=self.tmp, environ={})['codex']
        provider.follow(provider.launch(dict(self.SPEC, provider='codex')))
        self.assertEqual(self.saved, [('/tower/sessions/codex', self.CODEX2)])

    def test_without_put_permission_the_run_goes_on_and_says_so_without_a_secret(self):
        self.mutate = lambda home: (home / '.claude' / '.credentials.json').write_text(self.ROTATED)

        def denied(name, value):
            raise PermissionError('AccessDenied for ' + value)
        provider = self.made(save=denied)['claude-code']
        seen = provider.follow(provider.launch(self.SPEC))
        self.assertEqual(seen['outcome'], 'succeeded')
        self.assertTrue(seen['result']['credentials_unsaved'])
        self.assertNotIn('secret', json.dumps(seen))

    def test_a_login_failure_of_the_cli_is_an_auth_error_with_a_short_reason_and_no_secret(self):
        for said, reason in (('OAuth token has expired. Please obtain a new token or refresh your existing token. at-secret-old',
                              'token expired'), ('Invalid API key - Please run /login', 'invalid key'),
                             ('Please run /login', 'not logged in')):
            self.out = Done(json.dumps({'is_error': True, 'result': said, 'modelUsage': {}}), 1)
            provider = self.made()['claude-code']
            seen = provider.follow(provider.launch(self.SPEC))
            self.assertEqual((seen['outcome'], seen['error']), ('failed', f'auth: login needed ({reason})'))
            self.assertNotIn('secret', json.dumps(seen))
        self.out = Done('', 1, 'OAuth token has expired')  # not JSON at all
        provider = self.made()['claude-code']
        self.assertEqual(provider.follow(provider.launch(self.SPEC))['error'], 'auth: login needed (token expired)')

    def test_another_failure_is_not_called_an_auth_one(self):
        self.out = Done(json.dumps({'is_error': True, 'result': 'rate limited', 'modelUsage': {}}), 1)
        provider = self.made()['claude-code']
        self.assertEqual(provider.follow(provider.launch(self.SPEC))['error'], 'rate limited')

    def test_codex_writes_back_its_renewed_auth_also_when_it_fails(self):
        self.out = Done('', 1, 'boom cx-secret-2')
        self.mutate = lambda home: (home / '.codex' / 'auth.json').write_text(self.CODEX2)
        provider = self.made()['codex']
        seen = provider.follow(provider.launch(dict(self.SPEC, provider='codex')))
        self.assertEqual(seen['outcome'], 'failed')
        self.assertEqual(self.saved, [('/tower/sessions/codex', self.CODEX2)])
        self.assertNotIn('secret', json.dumps(seen))

    def test_a_failing_cli_ends_failed_and_what_it_says_is_scrubbed_of_the_credentials(self):
        self.out = Done('', 1, 'boom at-secret-old and forge-key-secret')
        provider = self.made()['claude-code']
        seen = provider.follow(provider.launch(self.SPEC))
        self.assertEqual(seen['outcome'], 'failed')
        self.assertNotIn('secret', json.dumps(seen))

    def test_the_forge_key_reaches_the_cli_for_git_and_origin_only_through_its_environment(self):
        provider = self.made()['claude-code']
        provider.launch(self.SPEC)
        self.assertEqual(self.env['CURSOR_API_KEY'], 'forge-key-secret')
        self.assertIn('credential-helper', self.env['GIT_CONFIG_VALUE_1'])
        self.assertEqual([c[0][:2] for c in self.calls[:2]], [['git', 'clone'], ['git', 'checkout']])

    def test_codex_runs_exec_reports_tokens_writes_back_its_renewed_auth_and_is_never_resumed(self):
        self.out = Done('\n'.join(json.dumps(e) for e in [
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'opened PR 2'}},
            {'type': 'turn.completed', 'usage': {'input_tokens': 70, 'output_tokens': 5}}]))
        self.mutate = lambda home: (home / '.codex' / 'auth.json').write_text(self.CODEX2)
        provider = self.made()['codex']
        session = provider.launch(dict(self.SPEC, provider='codex'))
        seen = provider.follow(session)
        self.assertEqual((seen['outcome'], sum(seen['tokens'].values()), seen['result']['result']), ('succeeded', 75, 'opened PR 2'))
        self.assertEqual(self.saved, [('/tower/sessions/codex', self.CODEX2)])
        self.assertEqual(self.env['CODEX_HOME'], str(self.seen_home[0] / '.codex'))
        self.assertIsNone(provider.resume(session))
        self.assertEqual(self.calls[-1][0][:2], ['codex', 'exec'])

    def test_the_two_clis_never_run_at_once_a_second_launch_waits_for_the_lock(self):
        provider = self.made()['codex']
        with cli_sessions.LOCK:
            session = provider.launch.__self__.sessions  # noqa: F841 - the lock is held below by the test itself
            started = []
            worker = __import__('threading').Thread(target=lambda: started.append(provider.launch(dict(self.SPEC, provider='codex'))))
            worker.start()
            time.sleep(0.05)  # the real clock only lets the blocked thread reach the lock; nothing asserts on it
            self.assertEqual(self.calls, [])  # blocked behind the lock, nothing ran
        worker.join(5)
        self.assertEqual(provider.follow(started[0])['state'], 'ended')

    def test_a_missing_credential_refuses_the_launch_and_an_unknown_session_is_lost(self):
        provider = cli_sessions.providers(lambda name: None, run=self.runner, spawn=lambda fn: fn(), tmp=self.tmp)['codex']
        with self.assertRaises(cli_sessions.NoCredential):
            provider.launch(self.SPEC)
        self.assertEqual(provider.follow('codex/none')['outcome'], 'failed')


if __name__ == '__main__':
    unittest.main()
