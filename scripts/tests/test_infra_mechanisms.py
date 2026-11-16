"""The mechanisms of the infrastructure's service (engine-infra-service; INFRA-SVC 3, P3 F3): the scenarios of the
acceptance test through the service, and the service stopped in the middle of a job that is then resumed.

The world is built through the port (two tenants, their executors, capacities and queues) on a throwaway database of
the toolchain's PostgreSQL (TI1) migrated by the service's runner; the service's dispatcher (tower_infra.mechanisms)
runs the jobs, and the test plays each executor, relaying and ending its runs under the lease's fencing token. Local
PostgreSQL only, no network.
"""
from http import HTTPStatus
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from infra_db.psql import migrated  # noqa: E402
import test_db  # noqa: E402
from tower_infra import http_port, mechanisms, port  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
INSTALLATION, TORRE, LIVRE = 'installation-of-the-test', 'torre-of-the-test', 'livre-of-the-test'
SIGNATURE = b'signed by the executor'


class World(unittest.TestCase):
    """Each test gets its own database and the same two tenants, built through the port."""

    def setUp(self):
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        for name, token in (('torre', TORRE), ('livre', LIVRE)):
            self.port('POST', '/v1/tenants', INSTALLATION, {'name': name, 'token_sha256': port.sha256(token)})
        for name, adapter in (('script-runner', 'container'), ('claude-sub', 'agent-session'),
                              ('codex-sub', 'agent-session'), ('pessoa', 'person-queue'), ('forge', 'forge')):
            self.port('POST', '/v1/executors', INSTALLATION, {'name': name, 'adapter': adapter})
        for executor, account, slots in (('script-runner', 'fargate', '4'), ('claude-sub', 'max-1', '0'),
                                         ('codex-sub', 'plus-1', '1'), ('pessoa', 'daniel', '1'),
                                         ('forge', 'origin', '1')):
            self.port('PUT', f'/v1/executors/{executor}/capacity/{account}', INSTALLATION, {'slots': slots})
        for token, queue, policy in ((TORRE, 'default', 'fifo'), (TORRE, 'ranked', 'rank'),
                                     (TORRE, 'land', 'fifo'), (LIVRE, 'default', 'deadline')):
            self.port('PUT', f'/v1/queues/{queue}', token, {'policy': policy})

    def port(self, method, path, token, body=None):
        answer = http_port.handle({'rawPath': path, 'requestContext': {'http': {'method': method}},
                                   'headers': {'Authorization': f'Bearer {token}'}, 'body': json.dumps(body or {})},
                                  self.db, port.sha256(INSTALLATION))
        said = json.loads(answer['body'])
        if answer['statusCode'] >= HTTPStatus.BAD_REQUEST:
            raise AssertionError(f'{method} {path}: {said}')
        return said

    def job(self, key, token=TORRE, **fields):
        spec = {'input_uri': f'in/{key}', 'input_digest': f'sha256:{key}', 'idempotency_key': key, **fields}
        return self.port('POST', '/v1/jobs', token, spec)['id']

    def state(self, job):
        return self.db.rows('select state from work.job where id = %(id)s::uuid', {'id': job})[0][0]

    def in_use(self, executor):
        return self.db.rows('select sum(in_use) from work.capacity where executor = %(e)s', {'e': executor})[0][0]

    def due(self, job):
        """Time passing: the wait the retry policy set is over."""
        self.db.rows('update work.job set not_before = now() where id = %(id)s::uuid returning id', {'id': job})

    def runs_of(self, made, job):
        return [run for run in made if run['job'] == job]



class Dispatch(World):
    def test_each_queue_dispatches_by_its_own_policy(self):
        ranked = {key: self.job(key, queue='ranked', rank=key[-1], executor='script-runner')
                  for key in ('rank-1', 'rank-5', 'rank-3')}
        fifo = [self.job(key, queue='default', executor='script-runner') for key in ('fifo-first', 'fifo-second')]
        later = self.job('later', LIVRE, deadline='2100-01-02T00:00:00Z', executor='pessoa')
        sooner = self.job('sooner', LIVRE, deadline='2100-01-01T00:00:00Z', executor='pessoa')
        tenants = dict(self.db.rows('select name, id::text from work.tenant'))
        first = {(tenant, queue): mechanisms.dispatch_one(self.db, tenants[tenant], queue, '5 minutes', '50')['job']
                 for tenant, queue in (('torre', 'ranked'), ('torre', 'default'), ('livre', 'default'))}
        self.assertEqual(first, {('torre', 'ranked'): ranked['rank-5'], ('torre', 'default'): fifo[0],
                                 ('livre', 'default'): sooner})
        self.assertEqual(self.state(later), 'queued')  # pessoa's one slot is taken

    def test_the_route_skips_an_executor_with_no_slot_and_a_busy_one_never_stops_the_queue(self):
        by_ai = self.job('by-ai', selector={'any_of': ['claude-sub', 'codex-sub']})
        blocked = self.job('blocked', executor='claude-sub')
        behind = self.job('behind', executor='script-runner')
        made = mechanisms.dispatch(self.db)
        self.assertEqual(self.runs_of(made, by_ai)[0]['executor'], 'codex-sub')  # claude-sub has no slot
        self.assertEqual(self.runs_of(made, blocked), [])
        self.assertEqual(self.runs_of(made, behind)[0]['adapter'], 'container')
        self.assertEqual(self.state(blocked), 'queued')

    def test_the_reserved_account_is_of_the_jobs_that_name_it_and_of_no_other(self):
        # CANARY-OWN-SLOT: script-runner has four slots of the checks (fargate) and the reserved one
        self.port('PUT', f'/v1/executors/script-runner/capacity/{mechanisms.RESERVED}', INSTALLATION, {'slots': '1'})
        named = [self.job(key, selector={'adapter': 'container', 'account': mechanisms.RESERVED})
                 for key in ('canary-1', 'canary-2')]
        made = mechanisms.dispatch(self.db)  # the first takes its account; with it taken, the second takes any free slot
        self.assertEqual([(got['job'], got['account']) for got in made], [(named[0], 'canary'), (named[1], 'fargate')])
        checks = [self.job(f'check-{n}', selector={'adapter': 'container'}) for n in range(4)]
        made = mechanisms.dispatch(self.db)
        self.assertEqual([(got['job'], got['account']) for got in made], [(each, 'fargate') for each in checks[:3]])
        self.assertEqual(self.state(checks[3]), 'queued')  # every slot of the checks is taken
        first = self.db.rows('select r.id::text, j.fencing_token from work.run r join work.job j on j.lease_run_id = r.id '
                             'where j.id = %(id)s::uuid', {'id': named[0]})[0]
        mechanisms.end(self.db, first[0], first[1], 'succeeded')
        self.assertEqual(mechanisms.dispatch(self.db), [])  # the reserved slot is free and the check never takes it
        self.assertEqual((self.state(checks[3]), self.in_use('script-runner')), ('queued', '4'))
        again = self.job('canary-3', selector={'adapter': 'container', 'account': mechanisms.RESERVED})
        [got] = mechanisms.dispatch(self.db)  # behind the check in the queue, and dispatched at once: its slot is its own
        self.assertEqual((got['job'], got['account'], self.state(checks[3])), (again, 'canary', 'queued'))

    def test_the_same_job_runs_by_a_script_without_a_session_and_by_an_ai_session(self):
        script = self.job('by-script', selector={'adapter': 'container'}, input_digest='sha256:same')
        session = self.job('by-ai', selector={'any_of': ['claude-sub', 'codex-sub']}, input_digest='sha256:same')
        made = {run['job']: run for run in mechanisms.dispatch(self.db)}
        self.assertEqual((made[script]['adapter'], made[session]['adapter']), ('container', 'agent-session'))
        for job in (script, session):
            self.assertEqual(mechanisms.end(self.db, made[job]['run'], made[job]['fence'], 'succeeded',
                                            result={'exit': '0'}), 'succeeded')
        self.assertEqual((self.in_use('script-runner'), self.in_use('codex-sub')), ('0', '0'))

    def test_retry_waits_by_the_jobs_own_policy_and_stops_at_its_last_attempt(self):
        flaky = self.job('flaky', executor='script-runner', max_attempts='3', retry_on=['failed'])
        attempts = int(self.db.rows('select max_attempts from work.job where id = %(id)s::uuid', {'id': flaky})[0][0])
        states = []
        for _ in range(attempts):
            run = mechanisms.dispatch(self.db)[0]
            states.append(mechanisms.end(self.db, run['run'], run['fence'], 'failed', 'exit1'))
            if states[-1] == 'queued':
                waited, policy = self.db.rows(
                    "select round(extract(epoch from not_before - now())), extract(epoch from least(backoff_initial "
                    "* power(backoff_factor, attempts - 1), backoff_max)) from work.job where id = %(id)s::uuid",
                    {'id': flaky})[0]
                self.assertEqual(float(waited), float(policy))  # 10 s, then 20 s: the default growth, as values
                self.assertEqual(mechanisms.dispatch(self.db), [])  # not before its wait is over
                self.due(flaky)
        self.assertEqual(states, ['queued', 'queued', 'failed'])


class Coordination(World):
    def test_the_landing_waits_for_its_checks_and_for_its_branch(self):
        checks = [self.job(key, queue='land', executor='script-runner') for key in ('check-1', 'check-2')]
        landing = self.port('POST', '/v1/jobs', TORRE, {
            'queue': 'land', 'executor': 'forge', 'input_uri': 'in/land', 'input_digest': 'sha256:land',
            'idempotency_key': 'landing', 'exclusive_key': 'origin:the-tower:base',
            'depends_on': [{'job': job} for job in checks]})['id']
        second = self.job('landing-2', queue='land', executor='forge', exclusive_key='origin:the-tower:base')
        runs = {run['job']: run for run in mechanisms.dispatch(self.db)}
        self.assertNotIn(landing, runs)  # its checks are open
        self.assertIn(second, runs)  # free to land: it waits for nothing
        for job in checks:
            mechanisms.end(self.db, runs[job]['run'], runs[job]['fence'], 'succeeded')
        self.assertEqual(mechanisms.dispatch(self.db), [])  # the branch is held by the second landing
        mechanisms.end(self.db, runs[second]['run'], runs[second]['fence'], 'succeeded')
        self.assertEqual([run['job'] for run in mechanisms.dispatch(self.db)], [landing])

    def test_an_identical_input_comes_from_the_cache_without_a_run(self):
        first = self.job('first', executor='script-runner', memoize=True, input_digest='sha256:tree')
        run = mechanisms.dispatch(self.db)[0]
        mechanisms.end(self.db, run['run'], run['fence'], 'succeeded', result={'exit': '0'}, signature=SIGNATURE)
        again = self.job('again', executor='script-runner', memoize=True, input_digest='sha256:tree')
        self.assertEqual(mechanisms.dispatch(self.db), [{'job': again, 'cached': True, 'executor': 'script-runner'}])
        self.assertEqual(self.port('GET', f'/v1/jobs/{again}', TORRE)['result'], {'exit': '0'})
        self.assertEqual(self.port('GET', f'/v1/jobs/{again}', TORRE)['runs'], [])
        self.assertEqual(self.state(first), 'succeeded')

    def test_a_money_limit_stops_a_running_job_and_its_end_does_not_bring_it_back(self):
        job = self.job('money', executor='codex-sub')
        self.port('PUT', '/v1/meter-rates', TORRE, {'meter': 'tokens', 'derived_meter': 'usd', 'rate': '0.000003'})
        self.port('POST', '/v1/limits', TORRE, {'scope': 'job', 'scope_id': job, 'meter': 'usd', 'maximum': '0.03',
                                                'action': 'stop'})
        run = mechanisms.dispatch(self.db)[0]
        self.assertTrue(mechanisms.relay(self.db, run['run'], run['fence'], 'run.usage',
                                         {'meter': 'tokens', 'quantity': '12000'}))
        self.assertEqual(self.state(job), 'stopped')
        self.assertEqual(mechanisms.end(self.db, run['run'], run['fence'], 'succeeded'), 'stopped')
        self.assertEqual(self.in_use('codex-sub'), '0')

    def test_a_waiting_job_resumes_through_the_port(self):
        job = self.job('asks', executor='pessoa', token=LIVRE)
        run = mechanisms.dispatch(self.db)[0]
        self.assertTrue(mechanisms.relay(self.db, run['run'], run['fence'], 'run.waiting', {'needs': 'an answer'}))
        self.assertEqual(self.state(job), 'waiting')
        self.port('POST', f'/v1/jobs/{job}/resume', LIVRE, {'content': {'answer': 'yes'}})
        self.assertTrue(mechanisms.relay(self.db, run['run'], run['fence'], 'run.running', {}))
        self.assertEqual(mechanisms.end(self.db, run['run'], run['fence'], 'succeeded'), 'succeeded')


class Durability(World):
    def test_the_service_stopped_in_the_middle_of_a_job_and_the_job_resumed(self):
        job = self.job('survives', executor='script-runner')
        old = mechanisms.dispatch(self.db, lease='0 seconds')[0]  # the service dies here: nothing ends this run
        self.assertEqual(mechanisms.reap(self.db), [job])
        self.assertEqual((self.state(job), self.in_use('script-runner')), ('queued', '0'))
        new = mechanisms.dispatch(self.db)[0]
        self.assertEqual((new['job'], new['n'], new['fence'] > old['fence']), (job, old['n'] + 1, True))
        self.assertIsNone(mechanisms.end(self.db, old['run'], old['fence'], 'failed', 'late'))  # fenced out
        self.assertFalse(mechanisms.relay(self.db, old['run'], old['fence'], 'run.usage', {'meter': 'cpu_s'}))
        self.assertEqual(mechanisms.end(self.db, new['run'], new['fence'], 'succeeded'), 'succeeded')
        self.assertEqual(self.db.rows('select attempts from work.job where id = %(id)s::uuid', {'id': job}),
                         [('1',)])  # the lost run spent no attempt

    def test_every_transition_wrote_its_event(self):
        job = self.job('logged', executor='script-runner')
        run = mechanisms.dispatch(self.db)[0]
        mechanisms.end(self.db, run['run'], run['fence'], 'succeeded')
        kinds = [event['type'] for event in self.port('POST', '/v1/log/query', TORRE,
                                                         {'payload': {'job_id': job}})['events']]
        self.assertEqual(kinds, ['job.created', 'run.started', 'run.ended'])


if __name__ == '__main__':
    unittest.main()
