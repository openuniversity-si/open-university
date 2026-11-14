"""The port's cold start (PORT2): Origin's webhook limit is 10 s and the Lambda took 6 to 12 s on its first call.

The webhook path answers with the least it can: the handler module loads in a fresh process without boto3, botocore,
psycopg or urllib (the connection's own imports wait for the first call that needs the database, and the IAM token is
signed with the standard library), inside a generous time budget; a delivery refused by its headers touches no
database; an accepted ping costs two statements (the keys, the record) and nothing else; the token is the one boto3
signs, byte for byte. No network, no database.
"""
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
from tower_infra import database, ed25519, forge_webhooks, http_port  # noqa: E402

HEAVY = ('boto3', 'botocore', 'psycopg', 'urllib.request', 'http.client')
IMPORT_BUDGET_S = 2.0  # measured ~0.03 s here; generous for a slow runner, tight against boto3 (+0.2 s here, seconds on 256 MB)
NOW = datetime(2026, 11, 8, 16, 0, 0, tzinfo=timezone.utc)
# boto3 1.43.123's generate_db_auth_token for these inputs at NOW (Session with explicit credentials, time frozen)
BOTO3_TOKEN = ('db.cluster-x.us-east-1.rds.amazonaws.com:5432/?Action=connect&DBUser=tower_service&X-Amz-Algorithm='
               'AWS4-HMAC-SHA256&X-Amz-Credential=AKIDEXAMPLE%2F20261108%2Fus-east-1%2Frds-db%2Faws4_request&X-Amz-Date='
               '20261108T160000Z&X-Amz-Expires=900&X-Amz-Security-Token=tok%2Fen%2B1%3D%3D&X-Amz-SignedHeaders=host&'
               'X-Amz-Signature=b62daf7e3aa7c65fa9c8499d1e1068d5d68f633c0abdf2d5554a6b681be39cd3')
SECRET = bytes(range(32))


class Scripted:
    """libpq's connection as login() polls it: each step is (what the poll answers, the state it leaves, the seconds
    the poll took); the clock is the test's."""
    socket, error_message = 7, b'FATAL:  PAM authentication failed for user "tower_service"\n'

    def __init__(self, steps, clock):
        self.steps, self.clock, self.status = list(steps), clock, 'STARTED'

    def connect_poll(self):
        polled, self.status, took = self.steps.pop(0)
        self.clock.now += took
        return polled


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


class Kinds:
    ok, reading, writing, r, w, bad, error = 'ok', 'reading', 'writing', 'R', 'W', 'BAD', ConnectionError

    @staticmethod
    def phase(status):
        return database.PHASE_OF.get(status, 'start')


class TheLoginsPhases(unittest.TestCase):
    """PORT-LOGIN-PHASES: where a login's seconds went, read around libpq's own polls and waits."""

    def run_login(self, steps, waits):
        clock, phases = Clock(), {}
        login = database.login(Scripted(steps, clock), phases, Kinds, clock)
        asked = [next(login)]
        try:
            for seconds in waits:
                clock.now += seconds
                asked.append(login.send(True))
        except StopIteration as ended:
            return phases, asked, ended.value
        self.fail('the login did not end')

    def test_a_logins_seconds_go_to_the_part_they_were_spent_in(self):
        steps = [('writing', 'STARTED', 0.0),            # the socket connects
                 ('reading', 'SSL_STARTUP', 0.001),      # SSLRequest sent: the server accepts, forks, answers
                 ('reading', 'SSL_STARTUP', 0.004),      # the handshake's own round trips
                 ('reading', 'AWAITING_RESPONSE', 0.02),  # the handshake ends (this side's crypto), the startup packet goes
                 ('reading', 'AWAITING_RESPONSE', 0.0),  # the password is asked for and sent
                 ('reading', 'AUTH_OK', 0.0),            # AuthenticationOk
                 ('ok', 'OK', 0.001)]
        phases, asked, pgconn = self.run_login(steps, [0.002, 0.05, 0.03, 0.01, 0.6, 0.25])
        self.assertEqual({name: round(seconds, 3) for name, seconds in phases.items()},
                         {'tcp': 0.003, 'tls': 0.104, 'auth': 0.61, 'start': 0.251})
        self.assertAlmostEqual(sum(phases.values()), 0.002 + 0.05 + 0.03 + 0.01 + 0.6 + 0.25 + 0.026)  # all of it, once
        self.assertEqual(asked[0], (7, 'W'))  # the driver's wait: the socket, and for what
        self.assertEqual(set(asked[1:]), {(7, 'R')})
        self.assertEqual(pgconn.status, 'OK')
        self.assertEqual(set(phases), set(database.PHASES))

    def test_a_state_this_module_does_not_name_is_the_backends_start(self):
        phases, _, _ = self.run_login([('reading', 'CHECK_TARGET', 0.0), ('ok', 'OK', 0.0)], [0.5])
        self.assertEqual({name: round(seconds, 3) for name, seconds in phases.items()}, {'tcp': 0.0, 'start': 0.5})

    def test_a_login_the_server_refuses_raises_what_the_server_said(self):
        with self.assertRaises(ConnectionError) as refused:
            self.run_login([('writing', 'STARTED', 0.0), ('failed', 'BAD', 0.0)], [0.01])
        self.assertIn('PAM authentication failed', str(refused.exception))
        clock = Clock()
        gone = Scripted([], clock)
        gone.status = 'BAD'
        with self.assertRaises(ConnectionError):
            next(database.login(gone, {}, Kinds, clock))

    def test_the_real_driver_logs_in_by_it(self):
        url = os.environ.get('TEST_DATABASE_URL')
        try:
            import psycopg  # noqa: F401
        except ImportError:
            self.skipTest('the gate\'s Python has no psycopg; with it and TEST_DATABASE_URL this is the driver\'s own login')
        if not url:
            self.skipTest('needs TEST_DATABASE_URL (Postgres; local port 54322)')
        sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
        import test_db
        from infra_db.psql import database_url
        name = test_db.create(url)
        self.addCleanup(test_db.destroy, url, name)
        phases, began = {}, time.monotonic()
        with database.phased(phases).connect(database_url(url, name), connect_timeout=5) as connection:
            wall = time.monotonic() - began
            self.assertEqual(connection.execute('select 1').fetchone(), (1,))
            self.assertFalse(connection.autocommit)  # the driver's connection, as psycopg.connect gives it
        self.assertLessEqual(set(phases), set(database.PHASES))
        # start is its own part only when ReadyForQuery comes after AuthenticationOk's packet (a backend slow to start);
        # here both come together and the whole of it is in auth
        self.assertGreater(phases['auth'], 0)
        self.assertLessEqual(sum(phases.values()), wall)
        with self.assertRaises(psycopg.OperationalError) as refused:
            database.phased({}).connect(database_url(url, 'no_such_database_here'), connect_timeout=5)
        self.assertIn('does not exist', str(refused.exception))  # the server's own words, as the port's 503 reads them


class Counting:
    """A database that answers the keys query with one key and every other statement with one row, counting calls."""

    def __init__(self, keys):
        self.statements, self.keys = [], keys

    def rows(self, sql, params=None):
        self.statements.append(sql)
        if sql == forge_webhooks.LATEST_KEYS:
            return [(json.dumps({'keys': self.keys}),)]
        return [('event',)]


def delivery(body=b'{"event":{"type":"ping"}}'):
    stamp = str(int(NOW.timestamp()))
    message = hashlib.sha256(f'wh-1.{stamp}.'.encode() + body).hexdigest().encode()
    signature = base64.b64encode(ed25519.sign(SECRET, message)).decode()
    headers = {'webhook-id': 'wh-1', 'webhook-timestamp': stamp, 'webhook-signature': f'v1ed,{signature}'}
    return {'rawPath': forge_webhooks.PATH, 'requestContext': {'http': {'method': 'POST'}}, 'headers': headers,
            'body': body.decode()}


class ColdStart(unittest.TestCase):
    def test_the_handler_module_loads_light_and_fast(self):
        code = ('import sys, time\nsys.path.insert(0, %r)\nstart = time.perf_counter()\n'
                'import tower_infra.http_port\nprint(time.perf_counter() - start)\n'
                'print(",".join(name for name in %r if name in sys.modules))' % (str(ROOT / 'infra' / 'service'), HEAVY))
        out = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, check=True,
                             timeout=60).stdout.split()
        self.assertEqual(out[1:], [], f'the handler module imports {out[1:]} at load: defer them to first use')
        self.assertLess(float(out[0]), IMPORT_BUDGET_S)

    def test_a_refused_delivery_touches_no_database(self):
        db = Counting([])
        for headers in ({}, {'webhook-id': 'x', 'webhook-timestamp': 'soon', 'webhook-signature': 'v1ed,AAAA'},
                        {'webhook-id': 'x', 'webhook-timestamp': '1', 'webhook-signature': 'v1ed,AAAA'}):
            event = {'rawPath': forge_webhooks.PATH, 'requestContext': {'http': {'method': 'POST'}},
                     'headers': headers, 'body': '{}'}
            self.assertIn(http_port.handle(event, db, '', NOW)['statusCode'], (400, 401))
        self.assertEqual(db.statements, [])
        self.assertEqual(http_port.handle({'rawPath': '/nope', 'requestContext': {'http': {'method': 'GET'}}}, db,
                                          '')['statusCode'], 404)
        self.assertEqual(db.statements, [])

    def test_the_202_path_does_the_least_before_answering(self):
        db = Counting([['kid', base64.urlsafe_b64encode(
            ed25519.public_key(SECRET)).decode().rstrip('=')]])
        answered = http_port.handle(delivery(), db, '', NOW)
        self.assertEqual(answered['statusCode'], 202)
        self.assertEqual(db.statements, [forge_webhooks.LATEST_KEYS, forge_webhooks.WRITE])

    def test_the_iam_token_is_the_one_boto3_signs_without_importing_it(self):
        where = {'host': 'db.cluster-x.us-east-1.rds.amazonaws.com', 'port': 5432, 'region': 'us-east-1'}
        environ = {'AWS_ACCESS_KEY_ID': 'AKIDEXAMPLE', 'AWS_SESSION_TOKEN': 'tok/en+1==',
                   'AWS_SECRET_ACCESS_KEY': 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY'}
        self.assertEqual(database.auth_token(where, 'tower_service', environ, NOW), BOTO3_TOKEN)


class TheInitsConnection(unittest.TestCase):
    """PORT-COLD-START: the Lambda of the port opens its connection in its init, and every answer says what it cost."""

    class Connection:
        closed = False

    class Wrap:
        def __init__(self, connection):
            self.connection = connection

        def rows(self, sql, params=None):
            return [(1,)]

    def setUp(self):
        self.opened = []
        for name, value in (('_connection', None), ('_opened', None), ('_calls', 0), ('_init', {})):
            self.addCleanup(setattr, http_port, name, getattr(http_port, name))
            setattr(http_port, name, value)

    def lazy(self, fail=None):
        def connect(purpose='call', **options):
            if fail:
                raise fail
            self.opened.append(options)
            return self.Connection()
        return mock.patch.multiple(http_port, driver=lambda environ=None: None,
                                   lazy_database=lambda user='tower_service', role='port': http_port.Lazy(connect, self.Wrap))

    def call(self, path='/v1/health'):
        return http_port.handler({'rawPath': path, 'requestContext': {'http': {'method': 'GET'}}, 'headers': {}}, None)

    def timing(self, said):
        return [part.split(';')[0] for part in said['headers']['server-timing'].split(', ')]

    def test_only_the_ports_own_lambda_opens_its_connection_at_its_init(self):
        with self.lazy():
            for environ in ({}, {'_HANDLER': 'tower_infra.webhook_consumer.handler'}, {'_HANDLER': 'tower_infra.ingress.handler'}):
                self.assertFalse(http_port.warm(environ))  # a test, a process of the service, another Lambda: nothing
            self.assertEqual((self.opened, http_port._connection), ([], None))
            self.assertTrue(http_port.warm({'_HANDLER': http_port.HANDLER}))
            self.assertEqual(self.opened, [{'connect_timeout': http_port.WARM_TIMEOUT_S}])  # inside the init's 10 s
            self.assertEqual(http_port._opened['at'], 'init')
            self.assertFalse(http_port.warm({'_HANDLER': http_port.HANDLER}))  # once
        stack = json.loads((ROOT / 'infra/aws/stacks/40-port.json').read_text())
        handlers = [each['Properties'].get('Handler') for each in stack['Resources'].values()
                    if each['Type'] == 'AWS::Lambda::Function']
        self.assertEqual(handlers.count(http_port.HANDLER), 1)  # the name the init looks for is the stack's
        self.assertLess(http_port.WARM_TIMEOUT_S, 10)

    def test_the_first_call_of_a_warmed_environment_opens_nothing_and_every_answer_says_what_it_cost(self):
        with self.lazy():
            http_port.warm({'_HANDLER': http_port.HANDLER})
            first, again = self.call(), self.call()
        self.assertEqual((first['statusCode'], len(self.opened)), (200, 1))  # the init's, kept: the call opened none
        self.assertEqual(self.timing(first), ['handler', 'cold', 'driver', 'connect'])  # PORT-COLD-SPLIT: the import apart
        self.assertIn('connect;dur=', first['headers']['server-timing'])
        self.assertIn('desc="init"', first['headers']['server-timing'])
        self.assertEqual(self.timing(again), ['handler'])  # a warm call: its own milliseconds
        self.assertRegex(again['headers']['server-timing'], r'^handler;dur=[0-9.]+$')

    def test_an_init_that_cannot_reach_the_database_leaves_the_connection_to_the_first_call(self):
        with self.lazy(fail=OSError('timeout expired')), mock.patch('builtins.print') as told:
            self.assertFalse(http_port.warm({'_HANDLER': http_port.HANDLER}))  # never raises: the Lambda still starts
        self.assertIn('OSError', told.call_args.args[0])
        self.assertNotIn('timeout expired', told.call_args.args[0])  # the type alone: a driver's message may hold a host
        with self.lazy():
            first, again = self.call(), self.call()
        self.assertEqual((first['statusCode'], self.opened), (200, [{}]))  # opened by the call, as before
        # PORT-COLD-SPLIT: the answer says the init tried and failed, how long it took and with what (live 11/11: one
        # environment of three opened nothing in its init, and its first call's answer did not say so)
        self.assertEqual(self.timing(first), ['handler', 'cold', 'driver', 'init-failed', 'connect'])
        self.assertRegex(first['headers']['server-timing'], r'init-failed;dur=[0-9.]+;desc="OSError"')
        self.assertIn('desc="call"', first['headers']['server-timing'])
        self.assertEqual(self.timing(again), ['handler'])

    def test_the_answer_says_where_the_logins_time_went(self):
        # PORT-LOGIN-PHASES: ~1.0 s of a cold start is the login (live 12/11 07:10 UTC, three environments) and nothing
        # said which part of it: the socket, the TLS, RDS's check of the IAM token or the backend's own start
        phases = {}

        def connect(purpose='call', **options):
            phases.update(tcp=0.0021, tls=0.1204, auth=0.6, start=0.25)
            return self.Connection()
        with mock.patch.multiple(http_port, driver=lambda environ=None: None, lazy_database=lambda user='tower_service',
                                 role='port': http_port.Lazy(connect, self.Wrap, phases)):
            http_port.warm({'_HANDLER': http_port.HANDLER})
            first, again = self.call(), self.call()
        self.assertEqual(self.timing(first), ['handler', 'cold', 'driver', 'connect', 'tcp', 'tls', 'auth', 'start'])
        self.assertIn('tcp;dur=2.1, tls;dur=120.4, auth;dur=600.0, start;dur=250.0', first['headers']['server-timing'])
        self.assertEqual(self.timing(again), ['handler'])  # said once, with the connect it is of
        self.assertEqual(http_port.LOGIN_PHASES, database.PHASES)

    def test_an_answer_that_is_not_the_apis_is_left_as_it_is(self):
        self.assertEqual(http_port.timed(None, 0.0, True), None)
        self.assertEqual(http_port.timed({'ok': True}, 0.0, True), {'ok': True})  # an event's answer (the build's state)


if __name__ == '__main__':
    unittest.main()
