"""The port of the infrastructure (engine-infra-service; INFRA-SVC 2, P3 F2; D-309): the acceptance test through the
port, with two tenants.

http_port.handle answers API Gateway's events on a throwaway database of the toolchain's PostgreSQL (TI1), migrated by
the service's own runner: the installation registers two tenants and its executors; each tenant configures its
queues, prices and limits and creates its jobs; each reads only its own jobs and log; and the port refuses what it
must (another tenant's private executor, a job with neither executor nor selector, a job over a refuse limit, another
tenant's job, an unknown token, the wrong caller). What the port writes feeds the mechanisms: the queue function orders
the tenants' jobs by each queue's policy, and a usage report stops a job at the tenant's money limit. Local PostgreSQL
only, no network.
"""
from http import HTTPStatus
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest import mock
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
import config  # noqa: E402
import test_db  # noqa: E402
from tower_infra import http_port, migrations, port  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
NULL = '<null>'
SEPARATOR = '\x1f'
PLACEHOLDER = re.compile(r'%\((\w+)\)s')
SQLSTATE = re.compile(r"ERROR:\s+([0-9A-Z]+):")
INSTALLATION = 'installation-token-of-the-test'
TORRE, LIVRE = 'torre-token-of-the-test', 'livre-token-of-the-test'


class DatabaseError(RuntimeError):
    def __init__(self, message, sqlstate):
        super().__init__(message)
        self.sqlstate = sqlstate


def literal(value):
    return 'null' if value is None else "'" + str(value).replace("'", "''") + "'"


class Psql:
    """rows(sql, params) and run(sql) through psql: the parameters become quoted literals, NULL keeps a marker, and a
    refusal keeps its SQLSTATE, as psycopg's errors do."""

    def __init__(self, url):
        self.url = url

    def call(self, args, script=None):
        done = subprocess.run([str(test_db.psql_binary()), self.url, '-X', '-q', '-v', 'ON_ERROR_STOP=1',
                               '-v', 'VERBOSITY=verbose', *args], input=script, capture_output=True, text=True,
                              timeout=config.get('test-db.psql_timeout_s'), check=False)
        if done.returncode:
            found = SQLSTATE.search(done.stderr)
            raise DatabaseError(done.stderr.strip(), found.group(1) if found else None)
        return done.stdout

    def rows(self, sql, params=None):
        sql = bind(sql, params or {})
        out = self.call(['-A', '-t', '-F', SEPARATOR, '-P', f'null={NULL}', '-c', sql])
        return [tuple(None if cell == NULL else cell for cell in line.split(SEPARATOR))
                for line in out.splitlines() if line]

    def run(self, sql):
        self.call(['-1', '-f', '-'], script=sql)


def bind(sql, params):
    """psycopg sends each named parameter as ONE untyped server-side parameter ($n), however often the SQL repeats it,
    and Postgres gives it a single type from its uses: a parameter cast ::jsonb in one place and passed bare to md5()
    in another is jsonb in both, and md5(jsonb) does not exist (production 500, request 1b309cde). Literals inlined
    into the text would hide that, so this prepares the statement the way the driver binds it."""
    order = []
    def numbered(found):
        if found.group(1) not in order:
            order.append(found.group(1))
        return f'${order.index(found.group(1)) + 1}'
    text = PLACEHOLDER.sub(numbered, sql)
    if not order:
        return text
    return (f"prepare bound as {text}; execute bound({', '.join(literal(params[name]) for name in order)}); "
            "deallocate bound")


def request(method, path, token=None, body=None):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    return {'rawPath': path, 'requestContext': {'http': {'method': method}}, 'headers': headers,
            'body': json.dumps(body) if body is not None else None}


class Heard:
    """A wake for the long poll: wait() plays the next scripted event, as the notification would, and says it woke."""

    def __init__(self, events):
        self.events = list(events)
        self.listened = self.closed = False

    def listening(self):
        self.listened = True

    def wait(self, seconds):
        self.waits = getattr(self, 'waits', []) + [seconds]
        if not self.events:
            return False
        self.events.pop(0)()
        return True

    def close(self):
        self.closed = True


class PortAcceptance(unittest.TestCase):
    """One database, built by the calls of setUpClass the way two managements would build it through the port."""

    @classmethod
    def setUpClass(cls):
        cls.name = test_db.create(URL)
        parts = urlsplit(URL)
        cls.db = Psql(urlunsplit((parts.scheme, parts.netloc, '/' + cls.name, '', '')))
        try:
            migrations.migrate(cls.db, ROOT / 'infra/db/migrations', 'test')
            cls.build()
        except BaseException:
            test_db.destroy(URL, cls.name)
            raise

    @classmethod
    def tearDownClass(cls):
        test_db.destroy(URL, cls.name)

    @classmethod
    def call(cls, method, path, token=None, body=None):
        answer = http_port.handle(request(method, path, token, body), cls.db, port.sha256(INSTALLATION))
        return answer['statusCode'], json.loads(answer['body'])

    @classmethod
    def ok(cls, method, path, token=None, body=None):
        status, said = cls.call(method, path, token, body)
        if status not in (HTTPStatus.OK, HTTPStatus.CREATED):
            raise AssertionError(f'{method} {path}: {status} {said}')
        return said

    @classmethod
    def build(cls):
        for name, token in (('torre', TORRE), ('livre', LIVRE)):
            cls.ok('POST', '/v1/tenants', INSTALLATION, {'name': name, 'token_sha256': port.sha256(token)})
        for name, adapter, capabilities in (('script-runner', 'container', {'root': True}),
                                            ('claude-sub', 'agent-session', {}), ('codex-sub', 'agent-session', {}),
                                            ('pessoa', 'person-queue', {}), ('forge', 'forge', {})):
            cls.ok('POST', '/v1/executors', INSTALLATION, {'name': name, 'adapter': adapter,
                                                           'capabilities': capabilities})
        cls.ok('POST', '/v1/executors', LIVRE, {'name': 'livre-own-key', 'adapter': 'agent-session'})
        for executor, account, slots in (('script-runner', 'fargate', '4'), ('claude-sub', 'max-1', '0'),
                                         ('codex-sub', 'plus-1', '1'), ('pessoa', 'daniel', '1'), ('forge', 'origin', '1')):
            cls.ok('PUT', f'/v1/executors/{executor}/capacity/{account}', INSTALLATION, {'slots': slots})
        cls.ok('PUT', '/v1/executors/livre-own-key/capacity/own', LIVRE, {'slots': '1'})
        cls.ok('PUT', '/v1/queues/default', TORRE, {'policy': 'fifo'})
        cls.ok('PUT', '/v1/queues/ranked', TORRE, {'policy': 'rank'})
        cls.ok('PUT', '/v1/queues/default', LIVRE, {'policy': 'deadline'})
        cls.jobs = {}
        for key, queue, rank in (('rank-1', 'ranked', '1'), ('rank-5', 'ranked', '5'), ('rank-3', 'ranked', '3'),
                                 ('fifo-first', 'default', '9'), ('fifo-second', 'default', '1')):
            cls.jobs[key] = cls.ok('POST', '/v1/jobs', TORRE, {
                'queue': queue, 'rank': rank, 'executor': 'script-runner', 'input_uri': f'in/{key}',
                'input_digest': f'sha256:{key}', 'idempotency_key': key})['id']
        for key, hours in (('deadline-later', '2 hours'), ('deadline-sooner', '1 hour')):
            deadline = cls.db.rows(f"select (now() + interval '{hours}')::text")[0][0]
            cls.jobs[key] = cls.ok('POST', '/v1/jobs', LIVRE, {
                'deadline': deadline, 'executor': 'pessoa', 'input_uri': f'in/{key}',
                'input_digest': f'sha256:{key}', 'idempotency_key': key})['id']
        cls.jobs['by-ai'] = cls.ok('POST', '/v1/jobs', TORRE, {
            'selector': {'any_of': ['claude-sub', 'codex-sub']}, 'input_uri': 'in/regen',
            'input_digest': 'sha256:same', 'idempotency_key': 'by-ai'})['id']

    def next_of(self, tenant, queue):
        tenant_id = self.db.rows('select id::text from work.tenant where name = %(name)s', {'name': tenant})[0][0]
        found = self.db.rows('select idempotency_key from work.job where id = work.next_job(%(tenant)s::uuid, '
                             '%(queue)s)', {'tenant': tenant_id, 'queue': queue})
        return found[0][0] if found else None

    def test_each_queue_the_tenants_configured_orders_by_its_own_policy(self):
        self.assertEqual((self.next_of('torre', 'ranked'), self.next_of('torre', 'default'),
                          self.next_of('livre', 'default')), ('rank-5', 'fifo-first', 'deadline-sooner'))

    def test_the_route_of_a_port_job_is_decided_by_capacity(self):
        self.assertEqual(self.db.rows('select work.route(%(job)s::uuid)', {'job': self.jobs['by-ai']}),
                         [('codex-sub',)])

    def test_a_tenant_reads_its_own_job_and_not_another_tenants(self):
        job = self.ok('GET', f"/v1/jobs/{self.jobs['rank-5']}", TORRE)
        self.assertEqual((job['queue'], job['state'], job['executor'], job['runs']), ('ranked', 'queued',
                                                                                     'script-runner', []))
        self.assertEqual(self.call('GET', f"/v1/jobs/{self.jobs['rank-5']}", LIVRE)[0], HTTPStatus.NOT_FOUND)

    def test_the_same_idempotency_key_answers_the_first_job(self):
        status, said = self.call('POST', '/v1/jobs', TORRE, {'queue': 'ranked', 'executor': 'script-runner',
                                                             'input_uri': 'in/again', 'input_digest': 'sha256:x',
                                                             'idempotency_key': 'rank-1'})
        self.assertEqual((status, said), (HTTPStatus.OK, {'id': self.jobs['rank-1'], 'created': False}))

    def test_a_queued_job_asked_again_at_a_higher_rank_takes_it_and_a_running_one_keeps_its_own(self):
        # GATE-OUTRANKS-PREGATE: a delivery's gate lifts the pre-gate's queued job it asks for by the same key
        body = {'queue': 'ranked', 'executor': 'script-runner', 'input_uri': 'in/lift', 'input_digest': 'sha256:lift',
                'idempotency_key': 'lift-1', 'rank': -5}
        status, made = self.call('POST', '/v1/jobs', TORRE, body)
        self.assertEqual(status, HTTPStatus.CREATED)
        rank = lambda: float(self.db.rows('select rank from work.job where id = %(id)s::uuid', {'id': made['id']})[0][0])
        self.assertEqual(self.call('POST', '/v1/jobs', TORRE, dict(body, rank=990))[1], {'id': made['id'], 'created': False})
        self.assertEqual(rank(), 990)
        self.call('POST', '/v1/jobs', TORRE, dict(body, rank=3))  # never lowered
        self.assertEqual(rank(), 990)
        self.db.rows("update work.job set state = 'running' where id = %(id)s::uuid", {'id': made['id']})
        self.call('POST', '/v1/jobs', TORRE, dict(body, rank=5000))  # a running job is not moved
        self.assertEqual(rank(), 990)

    def test_the_port_refuses_what_the_infrastructure_must(self):
        refusals = [
            (('POST', '/v1/jobs', TORRE, {'executor': 'livre-own-key', 'input_uri': 'in/x', 'input_digest': 'x'}),
             HTTPStatus.CONFLICT),  # the private executor of another tenant
            (('POST', '/v1/jobs', TORRE, {'input_uri': 'in/x', 'input_digest': 'x'}), HTTPStatus.BAD_REQUEST),  # no executor, no selector
            (('POST', '/v1/jobs', TORRE, {'executor': 'forge'}), HTTPStatus.BAD_REQUEST),  # no input
            (('POST', '/v1/tenants', TORRE, {'name': 'third', 'token_sha256': port.sha256('third')}), HTTPStatus.FORBIDDEN),
            (('POST', '/v1/jobs', INSTALLATION, {'executor': 'forge', 'input_uri': 'in/x', 'input_digest': 'x'}),
             HTTPStatus.FORBIDDEN),  # the installation creates no work; tenants do
            (('GET', '/v1/jobs/00000000-0000-7000-8000-000000000000', TORRE), HTTPStatus.NOT_FOUND),
            (('POST', '/v1/jobs', 'a-token-nobody-registered', {}), HTTPStatus.UNAUTHORIZED),
            (('POST', '/v1/jobs', None, {}), HTTPStatus.UNAUTHORIZED),
            (('PUT', '/v1/executors/livre-own-key/capacity/own', TORRE, {'slots': '1'}), HTTPStatus.NOT_FOUND),  # not torre's executor
            (('DELETE', '/v1/jobs', TORRE, None), HTTPStatus.NOT_FOUND),
        ]
        for args, status in refusals:
            method, path = args[0], args[1]
            self.assertEqual(self.call(*args)[0], status, f'{method} {path}')

    def test_a_refuse_limit_keeps_a_new_job_out(self):
        tenant_id = self.db.rows("select id::text from work.tenant where name = 'livre'")[0][0]
        self.ok('POST', '/v1/limits', LIVRE, {'scope': 'executor', 'scope_id': 'livre-own-key', 'meter': 'usd',
                                              'maximum': '0', 'action': 'refuse'})
        status, said = self.call('POST', '/v1/jobs', LIVRE, {'executor': 'livre-own-key', 'input_uri': 'in/y',
                                                             'input_digest': 'y'})
        self.assertEqual(status, HTTPStatus.CONFLICT, said)
        self.assertIn(tenant_id, said['error'])

    def test_cancel_and_resume_answer_by_the_state_of_the_job(self):
        job = self.jobs['fifo-second']
        self.assertEqual(self.call('POST', f'/v1/jobs/{job}/cancel', TORRE)[0], HTTPStatus.OK)
        self.assertEqual(self.call('POST', f'/v1/jobs/{job}/cancel', TORRE)[0], HTTPStatus.CONFLICT)  # no longer open
        waiting = self.jobs['rank-3']
        self.db.rows("update work.job set state = 'waiting' where id = %(id)s::uuid returning id", {'id': waiting})
        self.assertEqual(self.call('POST', f'/v1/jobs/{waiting}/resume', TORRE, {'content': {'answer': 'yes'}})[0], HTTPStatus.OK)
        self.assertEqual(self.call('POST', f'/v1/jobs/{job}/resume', TORRE, {'content': {}})[0], HTTPStatus.CONFLICT)
        resumed = self.ok('POST', '/v1/log/query', TORRE, {'filters': {'type': 'job.resume.requested'},
                                                           'payload': {'job_id': waiting}})['events']
        self.assertEqual([event['payload']['content'] for event in resumed], [{'answer': 'yes'}])

    def forget_repeats(self):
        """Keep the first row of each event id so the log-wide uniqueness check of another test still means something."""
        self.db.rows("delete from log.event a using log.event b where a.event_id = b.event_id and a.ctid > b.ctid "
                     "returning a.event_id")

    def test_configuring_an_executor_and_resuming_a_job_write_one_event_with_a_stable_id(self):
        """Production 500 (request 1b309cde): md5(%(config)s) beside %(config)s::jsonb made md5(jsonb). Each caller
        configures with a dict, answers 200, writes one executor.configured event, and the same transition again
        writes the same event id (the log is append-only, so the repeat is a second row with the id a reader drops)."""
        def configured(name):
            return self.db.rows("select event_id from log.event where type = 'executor.configured' "
                                "and subject = 'executor/' || %(name)s order by occurred_at", {'name': name})
        for token, name, config in ((INSTALLATION, 'forge', {'installation_id': 7, 'tenant': 'torre'}),
                                    (LIVRE, 'livre-own-key', {'region': 'eu', 'tags': ['a', 'b']})):
            path = f'/v1/executors/{name}/config'
            self.assertEqual(self.call('PUT', path, token, {'config': config})[0], HTTPStatus.OK)
            first = configured(name)
            self.assertEqual(len(first), 1)
            self.assertRegex(first[0][0], rf'^executor\.configured:{name}:[0-9a-f]{{32}}$')
            self.assertEqual(self.call('PUT', path, token, {'config': config})[0], HTTPStatus.OK)
            self.assertEqual(sorted(set(configured(name))), first)
            self.assertEqual(self.call('PUT', path, token, {'config': {**config, 'more': 1}})[0], HTTPStatus.OK)
            self.assertEqual(len(set(configured(name))), 2)
            self.forget_repeats()
        waiting = self.jobs['by-ai']
        before = self.db.rows('select state from work.job where id = %(id)s::uuid', {'id': waiting})[0][0]
        self.db.rows("update work.job set state = 'waiting' where id = %(id)s::uuid returning id", {'id': waiting})
        try:
            for _ in range(2):
                self.assertEqual(self.call('POST', f'/v1/jobs/{waiting}/resume', TORRE,
                                           {'content': {'answer': 'no'}})[0], HTTPStatus.OK)
        finally:
            self.db.rows("update work.job set state = %(state)s where id = %(id)s::uuid returning id",
                         {'id': waiting, 'state': before})
        ids = self.db.rows("select distinct event_id from log.event where type = 'job.resume.requested' and subject "
                           "= 'job/' || %(id)s", {'id': waiting})
        self.assertEqual(len(ids), 1)
        self.forget_repeats()
        self.assertRegex(ids[0][0], rf'^job\.resume\.requested:{waiting}:[0-9a-f]{{32}}$')

    def test_each_tenant_queries_only_its_own_log_with_its_own_filters_and_groups(self):
        torre = {row['type']: row['count'] for row in self.ok('POST', '/v1/log/query', TORRE,
                                                               {'group_by': ['type']})['events']}
        livre = {row['type']: row['count'] for row in self.ok('POST', '/v1/log/query', LIVRE,
                                                               {'group_by': ['type']})['events']}
        self.assertGreaterEqual(torre['job.created'], len([key for key in self.jobs if not key.startswith('dead')]))
        self.assertEqual(livre['job.created'], len([key for key in self.jobs if key.startswith('deadline')]))
        mine = self.ok('POST', '/v1/log/query', LIVRE, {'payload': {'job_id': self.jobs['rank-5']}})['events']
        self.assertEqual(mine, [])  # torre's job is not in livre's log
        self.assertEqual(self.call('POST', '/v1/log/query', TORRE, {'filters': {'payload': 'x'}})[0], HTTPStatus.BAD_REQUEST)

    def test_a_usage_report_stops_a_job_at_the_money_limit_the_tenant_priced(self):
        job = self.ok('POST', '/v1/jobs', TORRE, {'executor': 'codex-sub', 'input_uri': 'in/big',
                                                  'input_digest': 'sha256:big', 'idempotency_key': 'money'})['id']
        self.ok('PUT', '/v1/meter-rates', TORRE, {'meter': 'tokens', 'derived_meter': 'usd', 'rate': '0.000003'})
        self.ok('POST', '/v1/limits', TORRE, {'scope': 'job', 'scope_id': job, 'meter': 'usd', 'maximum': '0.03',
                                              'action': 'stop'})
        self.db.rows("update work.job set state = 'running' where id = %(id)s::uuid returning id", {'id': job})
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                     "select 'run.usage:test', tenant_id, 'run.usage', clock_timestamp(), 'test', 'job/' || id, "
                     "jsonb_build_object('job_id', id, 'meter', 'tokens', 'quantity', 12000) from work.job "
                     "where id = %(id)s::uuid returning event_id", {'id': job})
        self.assertEqual(self.ok('GET', f'/v1/jobs/{job}', TORRE)['state'], 'stopped')

    def test_a_tenant_reads_only_its_own_limits(self):
        mine = self.ok('POST', '/v1/limits', LIVRE, {'scope': 'executor', 'scope_id': 'livre-read', 'meter': 'usd',
                                                     'maximum': '5', 'action': 'stop'})['id']
        theirs = self.ok('POST', '/v1/limits', TORRE, {'scope': 'executor', 'scope_id': 'torre-read', 'meter': 'usd',
                                                       'maximum': '7', 'action': 'refuse'})['id']
        listed = self.ok('GET', '/v1/limits', LIVRE)['limits']
        self.assertIn(mine, [one['id'] for one in listed])
        self.assertNotIn(theirs, [one['id'] for one in listed])
        one = self.ok('GET', f'/v1/limits/{mine}', LIVRE)
        self.assertEqual({key: one[key] for key in ('scope', 'scope_id', 'meter', 'action')},
                         {'scope': 'executor', 'scope_id': 'livre-read', 'meter': 'usd', 'action': 'stop'})
        self.assertEqual(set(one), {'id', 'scope', 'scope_id', 'meter', 'maximum', 'used', 'action', 'resets_at'})
        self.assertEqual(self.call('GET', f'/v1/limits/{theirs}', LIVRE)[0], HTTPStatus.NOT_FOUND)
        self.assertEqual(self.call('GET', '/v1/limits', INSTALLATION)[0], HTTPStatus.FORBIDDEN)

    def test_a_subscription_belongs_to_its_tenant(self):
        made = self.ok('POST', '/v1/subscriptions', TORRE, {'sink': 'arn:aws-partition:sns:region-of-the-test:the-account:topic',
                                                            'types': ['job.created']})
        self.assertEqual(self.db.rows('select t.name, s.types::text from log.subscription s join work.tenant t on '
                                      't.id = s.tenant_id where s.id = %(id)s::uuid', {'id': made['id']}),
                         [('torre', '{job.created}')])
        mine = [each for each in self.ok('GET', '/v1/subscriptions', TORRE)['subscriptions'] if each['id'] == made['id']]
        self.assertEqual([(each['sink'], each['types'], each['state']) for each in mine],  # WEBHOOK-DEAD-ALERT: it can be seen
                         [('arn:aws-partition:sns:region-of-the-test:the-account:topic', ['job.created'], 'active')])
        self.assertNotIn(made['id'], [each['id'] for each in self.ok('GET', '/v1/subscriptions', LIVRE)['subscriptions']])

    def test_the_merge_train_keeps_arrival_order_per_base_and_each_exit_is_an_event(self):
        base = 'mod/roadmap-integration'
        for pr in ('410', '411', '412'):
            self.ok('POST', '/v1/train/join', TORRE, {'base': base, 'pr': pr, 'head': pr * 13, 'files': ['a']})
        self.ok('POST', '/v1/train/join', TORRE, {'base': base, 'pr': '411', 'head': 'f' * 40, 'files': ['b']})  # again: same place
        self.ok('POST', '/v1/train/join', TORRE, {'base': 'main', 'pr': '9', 'head': '9' * 40})
        where = self.ok('GET', '/v1/train', TORRE)['queues']
        self.assertEqual([e['pr'] for e in where[base]], ['410', '411', '412'])
        self.assertEqual(where[base][1]['head'], 'f' * 40)
        self.assertEqual([e['pr'] for e in where['main']], ['9'])
        self.assertEqual(self.ok('GET', '/v1/train', LIVRE)['queues'], {})  # another tenant sees none
        waiting = {'base': base, 'pr': '411'}
        self.assertEqual(self.ok('POST', '/v1/train/wait', TORRE, waiting)['state'], 'queued')  # no wake here: answers now
        self.ok('POST', '/v1/train/end', TORRE, {'base': base, 'pr': '410', 'ended': 'left', 'reason': 'red'})
        self.assertEqual(self.ok('POST', '/v1/train/wait', TORRE, waiting)['state'], 'front')
        self.ok('POST', '/v1/train/end', TORRE, {'base': base, 'pr': '411', 'ended': 'landed'})
        self.ok('POST', '/v1/train/end', TORRE, {'base': base, 'pr': '411', 'ended': 'landed'})  # idempotent
        self.assertEqual(self.ok('POST', '/v1/train/wait', TORRE, waiting)['state'], 'gone')
        types = [e['type'] for e in self.ok('POST', '/v1/log/query', TORRE, {'filters': {'subject': f'train/{base}'}})['events']]
        self.assertEqual(sorted(types), ['platform.train.joined'] * 3 + ['platform.train.landed', 'platform.train.left'])
        with mock.patch.object(http_port, 'wake_of', lambda db: Heard([lambda: self.ok(
                'POST', '/v1/train/end', TORRE, {'base': base, 'pr': '412', 'ended': 'left'})])):
            self.ok('POST', '/v1/train/join', TORRE, {'base': base, 'pr': '413', 'head': 'd' * 40})
            self.assertEqual(self.ok('POST', '/v1/train/wait', TORRE, {'base': base, 'pr': '413'})['state'], 'front')

    def test_the_long_poll_s_timeout_bounds_the_whole_call_not_each_wake(self):
        # PORT-LONG-POLL-TIMEOUT: wakes that are not this entry's front (other deliveries' events) each waited the full
        # 20 s again, 60 s in all, past the API's 30 s; the call has one deadline and a wake waits for what is left of it
        base, at = 'deadline/base', [0.0]
        for pr in ('1', '2'):
            self.ok('POST', '/v1/train/join', TORRE, {'base': base, 'pr': pr, 'head': pr * 40})
        heard = Heard([lambda: at.__setitem__(0, at[0] + 12.0)] * 2)  # two wakes, 12 s apart, that move nothing
        state = port.train_wait(self.db, port.caller(self.db, TORRE, ''), {'base': base, 'pr': '2'}, heard, clock=lambda: at[0])
        self.assertEqual((state['state'], state['timed_out'], heard.waits), ('queued', True, [20.0, 8.0]))
        self.assertTrue(heard.closed)

    def test_a_train_entry_whose_lease_ran_out_expires_and_the_entry_behind_becomes_the_front(self):
        base = 'lease/base'
        for pr in ('1', '2'):
            self.ok('POST', '/v1/train/join', TORRE, {'base': base, 'pr': pr, 'head': pr * 40, 'lease_s': 900})
        # the live entry renews; the front's process died: its lease is the past (the test moves the row, not a clock)
        self.db.rows("update work.train set lease_until = clock_timestamp() - interval '1 second' where base = %(b)s and pr = '1'",
                     {'b': base})
        renewed = self.ok('POST', '/v1/train/renew', TORRE, {'base': base, 'pr': '2', 'lease_s': 900})
        self.assertEqual((renewed['state'], [e['pr'] for e in renewed['entries']]), ('front', ['2']))
        self.assertEqual(self.ok('POST', '/v1/train/renew', TORRE, {'base': base, 'pr': '1'})['state'], 'gone')
        self.assertEqual(self.ok('POST', '/v1/train/wait', TORRE, {'base': base, 'pr': '1'})['state'], 'gone')
        self.assertEqual(self.db.rows("select ended from work.train where base = %(b)s order by pr", {'b': base}),
                         [('expired',), (None,)])
        types = [e['type'] for e in self.ok('POST', '/v1/log/query', TORRE, {'filters': {'subject': f'train/{base}'}})['events']]
        self.assertEqual(sorted(types), ['platform.train.expired', 'platform.train.joined', 'platform.train.joined'])
        self.ok('POST', '/v1/train/end', TORRE, {'base': base, 'pr': '2', 'ended': 'landed'})

    def test_every_command_wrote_its_event_with_a_deterministic_id(self):
        repeats = self.db.rows('select count(*) - count(distinct event_id) from log.event')
        self.assertEqual(repeats, [('0',)])
        self.assertEqual(self.db.rows("select count(*) from work.job j where not exists (select 1 from log.event e "
                                      "where e.event_id = 'job.created:' || j.id)"), [('0',)])

    def test_a_body_that_is_not_json_and_a_route_that_is_not_there(self):
        broken = request('POST', '/v1/jobs', TORRE)
        broken['body'] = '{not json'
        answer = http_port.handle(broken, self.db, port.sha256(INSTALLATION))
        self.assertEqual(answer['statusCode'], HTTPStatus.BAD_REQUEST)
        self.assertEqual(self.call('GET', '/v1/nothing', TORRE)[0], HTTPStatus.NOT_FOUND)


STACK = ROOT / 'infra/aws/stacks/40-port.json'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


class PortStackTests(unittest.TestCase):
    """infra/aws/stacks/40-port.json: the HTTP API and the Lambda on the service image, in the VPC, and the webhook queue (PORT3)."""

    def setUp(self):
        self.template = load(STACK)
        self.resources = self.template['Resources']
        self.function = self.resources['PortFunction']['Properties']

    def test_the_lambda_runs_the_port_as_a_zip_behind_the_alias(self):
        self.assertNotIn('PackageType', self.function)  # DEP8: Zip, built by scripts/lib/lambda_package.py
        self.assertEqual(self.function['Code'], {'S3Bucket': {'Fn::Sub': 'tower-outputs-${AWS::AccountId}-${AWS::Region}'},
                                                 'S3Key': {'Ref': 'PortCode'}})
        self.assertEqual((self.function['Runtime'], self.function['Handler']), ('python3.12', 'tower_infra.http_port.handler'))
        self.assertEqual(self.function['Layers'], [{'Ref': 'DepsLayer'}])
        self.assertTrue(callable(http_port.handler))
        self.assertEqual(self.function['Architectures'], ['arm64'])

    def test_a_database_that_cannot_be_reached_is_a_503_with_its_reason_and_the_call_is_tried_twice(self):
        # PORT-503-NO-DATABASE: live 11/11 22:17 to 22:21 UTC: the database at its connections' limit, the Lambda could not
        # connect, and every route answered API Gateway's bare 500: the gate's client retries a 503 and gives up on a 500
        tries = []

        def refused(purpose='call'):
            tries.append(purpose)
            raise RuntimeError('connection to server at "tower.example.rds.amazonaws.com" (10.40.1.2), port 5432 failed: '
                               'FATAL:  remaining connection slots are reserved for roles with the SUPERUSER attribute')
        event = {'rawPath': '/v1/train', 'requestContext': {'http': {'method': 'GET'}},
                 'headers': {'Authorization': 'Bearer anything'}}
        with mock.patch.object(http_port, '_connection', None), \
                mock.patch.object(http_port, 'lazy_database', lambda user: http_port.Lazy(refused, None)):
            said = http_port.handler(event, None)
        self.assertEqual((said['statusCode'], len(tries)), (503, 2))
        body = json.loads(said['body'])
        self.assertEqual(body['error'], 'unavailable')
        self.assertIn('remaining connection slots are reserved', body['detail'])
        self.assertNotIn('rds.amazonaws.com', body['detail'])  # the reason, not the host
        import gate_infra
        self.assertIn(503, gate_infra.TRANSIENT)  # the gate's client sends it again
        self.assertNotIn(500, gate_infra.TRANSIENT)


    def test_it_reaches_the_database_from_the_private_subnets_and_nothing_else(self):
        vpc = self.function['VpcConfig']
        self.assertEqual(vpc['SubnetIds'], {'Fn::Split': [',', {'Fn::ImportValue': 'tower-network-private-subnets'}]})
        self.assertEqual(vpc['SecurityGroupIds'], [{'Fn::ImportValue': 'tower-network-tasks-sg'}])
        # GATE-SHUTDOWN: no queue any more (the webhook path, ingress -> queue -> consumer, left the stack)
        self.assertEqual(sorted(name for name, resource in self.resources.items()
                                if resource['Type'].startswith('AWS::SQS')), [])

    def test_it_knows_the_database_and_the_installation_only_by_reference(self):
        variables = self.function['Environment']['Variables']
        self.assertLessEqual({'TOWER_DB_HOST', 'TOWER_DB_PORT', 'TOWER_DB_NAME', 'TOWER_DB_USER',
                              'TOWER_INSTALLATION_TOKEN_SHA256'}, set(variables))
        self.assertEqual(variables['TOWER_INSTALLATION_TOKEN_SHA256'], {'Ref': 'InstallationTokenSha256'})
        token = self.template['Parameters']['InstallationTokenSha256']
        self.assertEqual((token['Type'], token['Default']), ('AWS::SSM::Parameter::Value<String>',
                                                             '/tower/port/installation-token-sha256'))

    def test_its_role_connects_only_as_the_service_login(self):
        role = self.resources['PortRole']['Properties']
        self.assertTrue(role['RoleName'].startswith('tower-app-'))
        self.assertIn('policy/tower-boundary', str(role['PermissionsBoundary']))
        statements = role['Policies'][0]['PolicyDocument']['Statement']
        database = [item for item in statements if item['Action'] == 'rds-db:connect']
        self.assertEqual(len(database), len([item for item in statements if 'rds' in str(item['Action'])]))
        self.assertTrue(database[0]['Resource']['Fn::Sub'][0].endswith('/tower_service'))

    def test_the_api_calls_it_with_payload_2_and_bounds_it(self):
        integration = self.resources['PortIntegration']['Properties']
        self.assertEqual((integration['IntegrationType'], integration['PayloadFormatVersion']), ('AWS_PROXY', '2.0'))
        self.assertEqual(self.resources['DefaultRoute']['Properties']['RouteKey'], '$default')
        self.assertIn('ThrottlingRateLimit', self.resources['DefaultStage']['Properties']['DefaultRouteSettings'])
        # A reservation must leave 10 unreserved, more than a new account's whole pool: none by default, and the
        # account's pool and the stage's throttle bound the port's connections until the quota grows (16:31 BRT).
        self.assertEqual(self.function['ReservedConcurrentExecutions'],
                         {'Fn::If': ['ReservesConcurrency', {'Ref': 'Concurrency'}, {'Ref': 'AWS::NoValue'}]})
        self.assertEqual(self.template['Conditions']['ReservesConcurrency'],
                         {'Fn::Not': [{'Fn::Equals': [{'Ref': 'Concurrency'}, 0]}]})
        self.assertEqual(self.template['Parameters']['Concurrency']['Default'], 0)
        permission = self.resources['InvokeFromTheApi']['Properties']
        self.assertTrue(permission['Principal'].startswith('apigateway.'))  # API Gateway, and no other caller
        self.assertEqual(permission['FunctionName'], {'Ref': 'PortAlias'})


class CancelSubscription(unittest.TestCase):
    """A subscription is stopped by its tenant only, once, without a database (a recording one)."""

    class Db:
        def __init__(self, changes, exists):
            self.changes, self.exists, self.sql = changes, exists, []

        def rows(self, sql, params=None):
            self.sql.append(sql)
            return [('x',)] if (self.changes if sql.startswith('with') else self.exists) else []

    ID = '01a1be27-07af-75d3-bf27-a6cb38b0dba6'

    def who(self):
        return {'tenant': 'torre', 'tenant_id': '00000000-0000-0000-0000-000000000001'}

    def test_cancelling_sets_the_state_the_deliverer_skips_and_logs_the_event(self):
        db = self.Db(True, True)
        with mock.patch.object(port, 'tenant_only', return_value='t'):
            self.assertEqual(port.cancel_subscription(db, self.who(), self.ID), {'id': self.ID, 'state': 'cancelled'})
        self.assertIn("set state = 'cancelled'", db.sql[0])
        self.assertIn('platform.subscription.cancelled', db.sql[0])
        from tower_infra import subscriptions
        self.assertNotIn('cancelled', subscriptions.ACTIVE)
        self.assertIn("state = 'active'", subscriptions.ACTIVE)

    def test_a_second_cancel_is_a_success_and_another_tenants_id_is_404(self):
        with mock.patch.object(port, 'tenant_only', return_value='t'):
            self.assertEqual(port.cancel_subscription(self.Db(False, True), self.who(), self.ID)['state'], 'cancelled')
            with self.assertRaises(port.PortError) as refused:
                port.cancel_subscription(self.Db(False, False), self.who(), self.ID)
        self.assertEqual(refused.exception.status, 404)

    def test_the_route_exists_and_the_state_is_allowed_by_migration_0008(self):
        self.assertTrue(any(m == 'POST' and 'subscriptions' in r and r.endswith('/cancel')
                            for m, r, _ in http_port.ROUTES))
        sql = (ROOT / 'infra/db/migrations/0008_subscription_cancel.sql').read_text()
        self.assertIn("'cancelled'", sql)


class WithoutTheDatabase(unittest.TestCase):
    """A call the port refuses before it reads anything answers without a connection, so a cold start pays none for it
    (04/11: the first call to the deployed port answered 503, its handler connecting before it routed)."""

    class Unreachable:
        def rows(self, sql, params=None):
            raise AssertionError('the database was asked')

    def call(self, path, token=None):
        headers = {'Authorization': f'Bearer {token}'} if token else {}
        return http_port.handle({'rawPath': path, 'requestContext': {'http': {'method': 'GET'}}, 'headers': headers,
                                 'body': '{}'}, self.Unreachable(), port.sha256('installation'))

    def test_no_route_and_no_token_answer_without_the_database(self):
        self.assertEqual(self.call('/v1/jobs')['statusCode'], HTTPStatus.NOT_FOUND)  # GET /v1/jobs is no route
        self.assertEqual(self.call('/v1/jobs/00000000-0000-0000-0000-000000000000')['statusCode'],
                         HTTPStatus.UNAUTHORIZED)

    def test_the_connection_opens_on_the_first_call_that_needs_it_and_again_after_it_breaks(self):
        opened = []

        class Connection:
            closed = False

        class Wrap:
            def __init__(self, connection):
                self.connection = connection

            def rows(self, sql, params=None):
                return [(len(opened),)]

        def connect():
            opened.append(Connection())
            return opened[-1]
        self.addCleanup(setattr, http_port, '_connection', None)
        http_port._connection = None
        lazy = http_port.Lazy(connect, Wrap)
        self.assertEqual(opened, [])
        lazy.rows('select 1')
        lazy.rows('select 1')
        self.assertEqual(len(opened), 1)  # kept between calls
        opened[-1].closed = True
        self.assertTrue(lazy.broken())
        lazy.rows('select 1')
        self.assertEqual(len(opened), len(('the first', 'again')))

    def test_the_long_polls_end_before_the_api_and_the_client_give_up(self):
        # PORT-LONG-POLL-TIMEOUT: the integration cut at 10 s while the long polls waited 20 (live 11/11: POST
        # /v1/train/wait answered 503 at 10.25 s, and a delivery that waited for the train's front gave up on it)
        from tower_infra import canary
        resources = load(STACK)['Resources']
        integration_s = resources['PortIntegration']['Properties']['TimeoutInMillis'] / 1000
        cold_s = 5  # a cold start, the IAM login and the LISTEN of the wake, with room (measured ~2.5 s)
        for longest in (port.TRAIN_WAIT_MAX_S, canary.WAIT_MAX_S):
            self.assertLessEqual(longest + cold_s, integration_s)
        self.assertLessEqual(integration_s, resources['PortFunction']['Properties']['Timeout'])
        self.assertLessEqual(integration_s, config.get('gate-infra.call_timeout_s'))

    def test_the_lambda_has_the_time_of_a_cold_start(self):
        function = load(STACK)['Resources']['PortFunction']['Properties']
        self.assertEqual(str(function['Timeout']), '30')  # the most API Gateway's HTTP API waits for an integration


class Record(unittest.TestCase):
    def test_the_record_names_this_proof_and_what_it_amends(self):
        record = (ROOT / 'docs/domain/decisions/D-309.md').read_text(encoding='utf-8')
        self.assertIn('proof: scripts/tests/test_infra_port.py', record)
        for said in ('amends the ingress row of ARQUITETURA-ALVO §2', 'D-294', '04/11 13:27 BRT'):
            self.assertIn(said, record)


if __name__ == '__main__':
    unittest.main()
