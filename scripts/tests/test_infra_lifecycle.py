"""PROCESS-LIFE-IN-LOG (docs/operations/aws-revisao-arquitetura.md, finding 28): a process of the engine says in the
engine's own log when it started, why it stopped and what failed in its loop.

Hermetic: a stand-in scope that keeps the statements; OnPostgres writes the events on the migrated tables
(TEST_DATABASE_URL) and reads them back through the port's log query, as a session without the AWS account does.
"""
import contextlib
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from tower_infra import __main__ as entry, code_bundle, http_port, lifecycle, port, supervisor  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')


def setUpModule():
    logging.disable(logging.CRITICAL)  # the events that are not recorded are logged on purpose


def tearDownModule():
    logging.disable(logging.NOTSET)


class Scope:
    def __init__(self, fail=False):
        self.said, self.fail = [], fail

    @contextlib.contextmanager
    def __call__(self):
        if self.fail:
            raise RuntimeError('the database is away')
        yield self

    def rows(self, sql, params=None):
        assert sql == lifecycle.RECORD
        self.said.append((params['type'], params['subject'], params['producer'], json.loads(params['payload'])))
        return []


class Gate:
    task, gone, retired = 'task-1:abcdef012345', False, False


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class LifeTests(unittest.TestCase):
    def life(self, role='service', gate=None, environ=None, scope=None):
        self.scope, self.clock = scope or Scope(), Clock()
        return lifecycle.Life(role, self.scope, gate, {'TOWER_IMAGE': 'registry/tower@sha256:1', **(environ or {})}, self.clock)

    def test_a_task_says_it_started_with_what_it_runs(self):
        life = self.life(environ={'TOWER_RUNNER_NAME': 'ip-10-0-0-1', 'TOWER_IMAGE_DIGEST': 'd' * 64, supervisor.DIR: '/run/sup'},
                         role='runner')
        self.assertTrue(life.started())
        [(kind, subject, producer, said)] = self.scope.said
        self.assertEqual((kind, subject, producer), (lifecycle.STARTED, 'ip-10-0-0-1', 'tower-runner'))
        self.assertIsInstance(said.pop('at'), float)  # LIFE-EVENT-RETRY: when it happened
        self.assertEqual(said, {'role': 'runner', 'task': 'ip-10-0-0-1', 'mode': 'task', 'digest': 'd' * 64,
                                'image': 'registry/tower@sha256:1', 'supervised': True})

    def test_the_mode_says_what_kind_of_process_it_is(self):
        for environ, mode in (({}, 'task'), ({code_bundle.STANDBY: '1'}, 'standby'),
                              ({code_bundle.STANDBY: code_bundle.INTASK}, 'successor'),
                              ({code_bundle.RELOADED: '{"from": "x"}'}, 'reloaded')):
            self.assertEqual(self.life(environ=environ).about['mode'], mode)
        self.assertEqual(self.life(gate=Gate()).task, Gate.task)  # a successor's own name, as its beats say it

    def test_a_stop_says_why_once_and_how_long_it_was_up(self):
        for gate, error, reason in ((None, None, 'asked'), (mock.Mock(task='t', gone=True, retired=True), None, 'yielded'),
                                    (mock.Mock(task='t', gone=False, retired=True), None, 'retired'),
                                    (mock.Mock(task='t', gone=True, retired=False), ValueError('boom'), 'error')):
            life = self.life(gate=gate)
            self.clock.now += 42.5
            self.assertTrue(life.stopped(error))
            self.assertFalse(life.stopped())  # main() and a handler may both say it: one event
            [(kind, _, _, said)] = self.scope.said
            self.assertEqual((kind, said['reason'], said['up_s'], said['error']),
                             (lifecycle.STOPPED, reason, 42.5, None if error is None else 'ValueError: boom'))

    def test_a_failure_the_loop_survives_is_said_at_once_and_then_counted(self):
        life = self.life()
        self.assertTrue(life.error('tick', RuntimeError('x' * 1000)))
        for _ in range(5):
            self.clock.now += 1
            self.assertFalse(life.error('tick', RuntimeError('again')))  # the same kind: not an event per tick
        self.assertTrue(life.error('tick', KeyError('other')))  # another kind is said at once
        self.clock.now += lifecycle.ERROR_EVERY_S
        self.assertTrue(life.error('tick', RuntimeError('still')))
        said = [each[3] for each in self.scope.said if each[0] == lifecycle.ERROR]
        self.assertEqual([(each['where'], each['times']) for each in said], [('tick', 1), ('tick', 1), ('tick', 6)])
        self.assertEqual(len(said[0]['error']), lifecycle.TEXT)
        self.assertEqual(said[2]['error'], 'RuntimeError: still')

    def test_a_database_that_is_away_costs_the_event_never_the_process(self):
        life = self.life(scope=Scope(fail=True))
        self.assertEqual((life.started(), life.error('tick', RuntimeError('x')), life.stopped()), (False, False, False))

    def test_an_event_the_database_refused_is_written_on_a_later_good_beat_with_the_time_it_happened(self):
        # LIFE-EVENT-RETRY: live 11/11 17:10 UTC, the database at 65 of 79 connections: the tasks a rollout started said nothing
        life = self.life(scope=Scope(fail=True))
        with mock.patch.object(lifecycle.time, 'time', return_value=1794417000.0):
            self.assertFalse(life.started())
        self.assertFalse(life.error('tick', RuntimeError('the pool timed out')))
        self.assertEqual(life.beat(), 0)  # not at once: the database just refused
        self.clock.now += lifecycle.RETRY_S
        self.assertEqual((life.beat(), len(life.unsaid)), (0, 2))  # still away: kept, in order
        self.scope.fail = False
        self.assertEqual(life.beat(), 0)  # nor more often than RETRY_S
        self.clock.now += lifecycle.RETRY_S
        self.assertEqual((life.beat(), life.unsaid), (2, []))
        self.assertEqual([each[0] for each in self.scope.said], [lifecycle.STARTED, lifecycle.ERROR])
        self.assertEqual(self.scope.said[0][3]['at'], 1794417000.0)  # when it started, not when the database took it
        self.scope.said.clear()
        self.assertEqual((life.beat(), self.scope.said), (0, []))  # nothing kept: a beat asks nothing of the database

    def test_only_the_newest_events_are_kept_for_later(self):
        life = self.life(scope=Scope(fail=True))
        for n in range(lifecycle.KEEP + 5):
            life.write(lifecycle.ERROR, {'where': 'tick', 'n': n})
        self.assertEqual([json.loads(each['payload'])['n'] for each in life.unsaid], list(range(5, lifecycle.KEEP + 5)))


class BootTests(unittest.TestCase):
    """SUCCESSOR-BACK-FASTER and BOOT-PARTS: a process the role is waiting for (a successor started after the pointer
    named it) says its start beside its first work, and says where its boot went."""

    def test_a_start_said_aside_is_said_in_a_thread_and_the_record_is_the_process_s_all_the_same(self):
        started = []
        scope = Scope()
        before = lifecycle.NOW
        self.addCleanup(setattr, lifecycle, 'NOW', before)
        with mock.patch.object(lifecycle.threading, 'Thread') as thread, \
                mock.patch.object(lifecycle.Life, 'started', lambda self: started.append('now')):
            life = lifecycle.begin('runner', scope, None, aside=True)
            self.assertEqual((started, lifecycle.NOW), ([], life))  # nothing was written on the caller's way
            _, how = thread.call_args
            self.assertTrue(how['daemon'])
            thread.return_value.start.assert_called_once_with()
            how['target']()
            self.assertEqual(started, ['now'])
            lifecycle.begin('runner', scope, None)  # any other process: said before it goes on, as before
            self.assertEqual((started, thread.call_count), (['now', 'now'], 1))
            # FIRST-WORK-FIRST: with a gate, the thread waits for the role's first work before it logs in to say it
            waited = []
            gate = mock.Mock()
            gate.worked.wait.side_effect = lambda seconds: waited.append((seconds, list(started)))
            lifecycle.begin('service', scope, gate, aside=True)
            thread.call_args[1]['target']()
            self.assertEqual((waited, started), ([(lifecycle.FIRST_WORK_S, ['now', 'now'])], ['now', 'now', 'now']))

    def test_a_process_s_age_is_the_kernel_s_and_an_exec_keeps_it(self):
        with tempfile.TemporaryDirectory() as folder:
            stat, uptime = Path(folder) / 'stat', Path(folder) / 'uptime'
            # the 22nd field is the start time in clock ticks; a command's name may hold spaces and parentheses
            stat.write_text('4242 (python -m (x) y) S ' + ' '.join(['0'] * 18) + ' 123450 ' + ' '.join(['0'] * 30))
            uptime.write_text('1236.75 900.00\n')
            self.assertEqual(code_bundle.age_s(str(stat), str(uptime), ticks=100), 2.25)
            self.assertIsNone(code_bundle.age_s(str(stat) + '.absent', str(uptime)))  # no /proc: the part is left out
        environ = {}
        self.assertEqual(code_bundle.entered(environ, age=lambda: 0.31), 0.31)  # the image's interpreter reached main
        environ[code_bundle.LOADED] = '/tmp/tower-code-x'
        code_bundle.entered(environ, age=lambda: 1.42)  # the bundle's, after boot() fetched it and exec'ed
        self.assertEqual((environ[code_bundle.BOOT_ENTRY], environ[code_bundle.BOOT_CODE]), ('0.31', '1.42'))
        self.assertIsNone(code_bundle.entered(environ, age=lambda: None))
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertLess(source.index('code_bundle.entered()  # BOOT-PARTS'), source.index('failed = code_bundle.boot(command, args)'))
        self.assertIn("lifecycle.begin('runner', quick(database, where, user, password), gate, aside=late)", source)
        self.assertIn("lifecycle.begin('service', quick(database, where, user, password), gate, aside=late)", source)
        self.assertEqual(source.count('late = gate is not None and intask and gate.active() and gate.pointed()'), 2)  # both roles
        self.assertIn("runner.serve_all(workers, stop, poll_s=number('TOWER_POLL_S', 1), staggered=late,", source)


class MainTests(unittest.TestCase):
    """main() says the stop of serve and run-container, whatever ended them, and raises what was raised."""

    def setUp(self):
        self.scope = Scope()
        self.addCleanup(setattr, lifecycle, 'NOW', None)

    def run_main(self, command, body):
        def ready():
            lifecycle.NOW = lifecycle.Life('service', self.scope, None, {})
            return body()
        with mock.patch.object(supervisor, 'due', lambda command: False), \
                mock.patch.object(code_bundle, 'boot', lambda command, args: None), \
                mock.patch.object(entry, 'serve', ready), mock.patch.object(entry, 'run_container', ready):
            return entry.main([command])

    def reasons(self):
        return [(each[3]['reason'], each[3]['error']) for each in self.scope.said if each[0] == lifecycle.STOPPED]

    def test_a_command_that_returns_was_asked_to_stop(self):
        for command in ('serve', 'run-container'):
            self.scope.said.clear()
            self.assertEqual(self.run_main(command, lambda: None), 0)
            self.assertEqual(self.reasons(), [('asked', None)])

    def test_a_crash_is_said_and_raised(self):
        def crash():
            raise RuntimeError('the pool is gone')
        with self.assertRaises(RuntimeError):
            self.run_main('serve', crash)
        self.assertEqual(self.reasons(), [('error', 'RuntimeError: the pool is gone')])

    def test_an_exit_asked_for_is_not_an_error_and_an_exit_code_is(self):
        for raised, expected in ((SystemExit(0), ('asked', None)), (KeyboardInterrupt(), ('asked', None)),
                                 (SystemExit(3), ('error', 'SystemExit: 3'))):
            self.scope.said.clear()

            def leave(raised=raised):
                raise raised
            with self.assertRaises(type(raised)):
                self.run_main('serve', leave)
            self.assertEqual(self.reasons(), [expected])

    def test_a_process_that_never_got_ready_says_nothing_and_fails_as_before(self):
        def early():
            lifecycle.NOW = None
            raise RuntimeError('no database settings')
        with self.assertRaises(RuntimeError):
            self.run_main('serve', early)
        self.assertEqual(self.scope.said, [])

    def test_serve_and_the_runner_begin_their_record_and_the_tick_says_its_failures(self):
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn("lifecycle.begin('service', quick(database, where, user, password), gate, aside=late)", source)
        self.assertIn("lifecycle.begin('runner', quick(database, where, user, password), gate, aside=late)", source)
        self.assertIn("lifecycle.error('tick', failure)", source)
        self.assertEqual(source.count('lifecycle.beat()'), 3)  # LIFE-EVENT-RETRY: the standby's beat, the live tick, a slot's pass


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    def setUp(self):
        from infra_db.psql import migrated
        import test_db
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        self.db.rows("insert into work.tenant (name, token_sha256) values ('torre', %(d)s), ('other', %(o)s)",
                     {'d': port.sha256('torre-token'), 'o': port.sha256('other-token')})

    def query(self, token, kind):
        answer = http_port.handle({'rawPath': '/v1/log/query', 'requestContext': {'http': {'method': 'POST'}},
                                   'headers': {'Authorization': f'Bearer {token}'},
                                   'body': json.dumps({'filters': {'type': kind}})}, self.db, '')
        return answer['statusCode'], json.loads(answer['body'])['events']

    def test_the_events_are_written_and_the_configuration_tenant_reads_them_through_the_port(self):
        @contextlib.contextmanager
        def scope():
            yield self.db
        life = lifecycle.Life('service', scope, None, {'TOWER_IMAGE_DIGEST': 'd' * 64, 'TOWER_CONFIG_TENANT': 'torre'})
        self.assertTrue(life.started())
        self.assertTrue(life.error('tick', RuntimeError('the queue read failed')))
        self.assertTrue(life.stopped())
        for kind, field, value in ((lifecycle.STARTED, 'mode', 'task'), (lifecycle.ERROR, 'error', 'RuntimeError: the queue read failed'),
                                   (lifecycle.STOPPED, 'reason', 'asked')):
            status, [event] = self.query('torre-token', kind)
            self.assertEqual((status, event['producer'], event['subject'], event['payload'][field], event['payload']['digest']),
                             (200, 'tower-service', life.task, value, 'd' * 64))
            self.assertEqual(self.query('other-token', kind), (200, []))  # another tenant does not read the engine's processes


if __name__ == '__main__':
    unittest.main()
