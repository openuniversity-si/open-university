"""DB-VITALS (docs/operations/aws-revisao-arquitetura.md, findings 10 and 13): the live service measures its database.

The size of the database and of the log, and the peak of connections, were readings of the AWS account no session has.
The service counts the connections on its heartbeat and writes platform.db.vitals on a task's second beat and every
hour; a threshold crossed is published once when it starts and once when it ends.

Hermetic: a stand-in database that answers the four statements; OnPostgres runs them on the migrated tables
(TEST_DATABASE_URL) and reads the event back through the port's log query.
"""
import functools
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
from tower_infra import config_data, http_port, port, vitals  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
GIB = 1024 ** 3


def setUpModule():
    logging.disable(logging.CRITICAL)  # the measures that fail and the alerts are logged on purpose


def tearDownModule():
    logging.disable(logging.NOTSET)


class Settings:
    def __init__(self, **over):
        self.over = over

    def get(self, name):
        return self.over.get(name, config_data.SPEC[name][1])


class Db:
    """The database as the four statements see it: connections by user and application name (by_user alone: every one
    of a user under one name), the sizes, the largest tables, the last alerts."""

    def __init__(self, database=GIB, most=80, log=GIB // 2, events=1000):
        self.by_user, self.sizes, self.events, self.fail = {'tower_service': 9}, (database, most, log, events), [], False
        self.held = None  # DB-LISTEN-ONE: [(user, application name, connections)], when a test says who holds them
        self.host = None  # DB-HOST-VITALS: what work.host_vitals() answers (None: the function is not there)
        self.server = []  # SERVER-SETTINGS-READ: pg_settings' rows (name, setting, unit)
        self.since = []  # VITALS-LOGINS: what each beat asked CONNECTIONS (the window of "born since")
        self.runner = None  # RUNNER-OWN-LOGIN: what RUNNER_LOGIN answers (None: no such login)
        self.idle = []  # DB-SWAP-CUT: [(application name, backends idle a minute or more)]

    def rows(self, sql, params=None):
        if self.fail:
            raise RuntimeError('the database is away')
        if sql == vitals.CONNECTIONS:
            self.since.append(params['since'])  # VITALS-LOGINS: the seconds since the last beat
            return self.held or [(user, 'tower-service:pool', count) for user, count in self.by_user.items()]
        if sql == vitals.SERVER:  # SERVER-SETTINGS-READ: the server's settings as pg_settings says them
            assert params == {'names': ','.join(vitals.SERVER_NAMES)}
            return self.server
        if sql == vitals.IDLE:
            return self.idle
        if sql == vitals.RUNNER_LOGIN:
            return [(self.runner,)]
        if sql == vitals.HOST_THERE:  # DB-HOST-VITALS: no such function unless a test says the host answers
            return [('t' if self.host is not None else 'f',)]
        if sql == vitals.HOST:
            return [(json.dumps(self.host) if self.host else None,)]
        if sql == vitals.SIZES:
            return [self.sizes]
        if sql == vitals.TABLES:
            return [('log.event_2026_11', self.sizes[2])]
        if sql == vitals.LAST:
            return [(json.dumps(self.events[-1]['alerts']),)] if self.events else []
        if sql == vitals.RECORD:
            self.events.append(json.loads(params['payload']))
            return []
        raise AssertionError(sql)


class Measure(unittest.TestCase):
    def setUp(self):
        self.db, self.sent, self.at = Db(), [], [0.0]
        self.vitals = vitals.Vitals(Settings(), publish=lambda said, subject: self.sent.append((subject, said)),
                                    clock=lambda: self.at[0])

    def test_the_event_says_the_backends_idle_a_minute_or_more_by_who_opened_them(self):
        # DB-SWAP-CUT (revisão da arquitetura, achado 37): the host pages out what nobody uses; the event says how much of it
        # each pool keeps
        self.db.idle = [('tower-service:pooled', '9'), ('tower-runner:pooled', '3')]
        self.vitals.beat(self.db)
        self.at[0] = 30.0
        self.vitals.beat(self.db)
        self.assertEqual(self.db.events[-1]['idle_by_app'], {'tower-service:pooled': 9, 'tower-runner:pooled': 3})

    def test_the_second_beat_records_and_the_first_does_not(self):
        self.vitals.beat(self.db)  # the first pass may be an image swap's: no measure of the sizes on it
        self.assertEqual(self.db.events, [])
        self.at[0] = 30.0
        self.vitals.beat(self.db)
        (said,) = self.db.events
        self.assertEqual((said['database_bytes'], said['disk_bytes'], said['disk_ratio']), (GIB, 20 * GIB, 0.05))
        self.assertEqual((said['log_bytes'], said['log_events'], said['tables']),
                         (GIB // 2, 1000, {'log.event_2026_11': GIB // 2}))
        self.assertEqual((said['connections'], said['connections_peak'], said['max_connections'], said['connections_ratio']),
                         (9, 9, 80, 0.1125))
        self.assertEqual((said['peak_by_user'], said['window_s'], said['alerts']), ({'tower_service': 9}, 30.0, []))
        self.vitals.beat(self.db)  # later beats only count: the next event is the hour's
        self.assertEqual(len(self.db.events), 1)
        self.assertEqual(self.sent, [])

    def test_the_peak_is_the_largest_count_of_the_window_with_who_held_it(self):
        self.vitals.beat(self.db)
        self.db.by_user = {'tower_service': 30, 'tower_port': 12}
        self.vitals.beat(self.db)  # records: peak 42
        self.db.by_user = {'tower_service': 8}
        self.vitals.beat(self.db)
        self.assertEqual((self.db.events[0]['connections_peak'], self.db.events[0]['connections']), (42, 42))
        self.db.by_user = {'tower_service': 20, 'tower_port': 1}
        self.vitals.beat(self.db)
        self.db.by_user = {'tower_service': 8}
        self.vitals.beat(self.db)
        said = self.vitals.record(self.db)  # the hour's: the window after the first event peaked at 21, not 42
        self.assertEqual((said['connections'], said['connections_peak'], said['peak_by_user']),
                         (8, 21, {'tower_service': 20, 'tower_port': 1}))

    def test_the_peak_says_which_process_held_the_connections_and_what_for(self):
        # DB-LISTEN-ONE: the engine names its connections tower-<role>:<purpose>; the event carries the largest holders
        self.db.held = [('tower_service', 'tower-service:pool', '6'), ('tower_service', 'tower-service:listen', '1'),
                        ('tower_service', 'tower-runner:slot', '4'), ('tower_service', 'tower-runner:listen', '1'),
                        ('tower_port', 'tower-port:call', '2'), ('tower_owner', 'tower-runner:slot', '1'), ('-', '-', '1')]
        self.vitals.beat(self.db)
        self.vitals.beat(self.db)  # records
        said = self.db.events[0]
        self.assertEqual((said['connections_peak'], said['peak_by_user']),
                         (16, {'tower_service': 12, 'tower_port': 2, 'tower_owner': 1, '-': 1}))
        self.assertEqual(said['peak_by_app'], {'tower-service:pool': 6, 'tower-runner:slot': 5, 'tower-port:call': 2,
                                               '-': 1, 'tower-runner:listen': 1, 'tower-service:listen': 1})
        self.db.held = [('tower_service', f'psql-{n:02}', 20 - n) for n in range(15)]
        self.vitals.beat(self.db)
        said = self.vitals.record(self.db)  # an event stays small: the 12 largest names, the rest counted together
        self.assertEqual((len(said['peak_by_app']), said['peak_by_app']['others'], sum(said['peak_by_app'].values())),
                         (vitals.APPS + 1, 8 + 7 + 6, said['connections_peak']))

    def test_the_event_says_the_logins_of_the_window_and_who_made_them(self):
        # VITALS-LOGINS: a login is a fork, a TLS handshake and the IAM token's check on the database's host: alone
        # 0.06 to 0.17 s, five at once 0.42 to 1.2 s each (live 12/11), and nothing said how many the engine makes
        # in an hour, nor who makes them
        def held(born, sessions):  # (user, application name, connections, born since the last beat, sessions so far)
            return [('tower_service', name, 5, count, sessions) for name, count in born.items()]
        self.db.held = held({'tower-service:pool': 0, 'tower-port:call': 0}, 100)
        self.vitals.beat(self.db)  # the process's first beat: where its count starts
        self.at[0] = 30.0
        self.db.held = held({'tower-service:pool': 2, 'tower-port:call': 3}, 109)
        self.vitals.beat(self.db)  # records
        self.assertEqual(self.db.since, [0.0, 30.0])  # born since the last beat, to the second
        said = self.db.events[0]
        # nine sessions opened in the window; five were still there at a beat, the other four came and went inside one
        self.assertEqual((said['logins'], said['logins_by_app']), (9, {'tower-port:call': 3, 'tower-service:pool': 2}))
        self.at[0] = 60.0
        self.db.held = held({'tower-service:pool': 0, 'tower-port:call': 1}, 110)
        self.vitals.beat(self.db)
        self.at[0] = 90.0
        self.db.held = held({'tower-service:pool': 0, 'tower-port:call': 0}, 112)
        self.vitals.beat(self.db)
        said = self.vitals.record(self.db)  # the next window counts from the event before it
        self.assertEqual((said['logins'], said['logins_by_app']), (3, {'tower-port:call': 1}))
        self.assertEqual(self.vitals.record(self.db)['logins'], 0)  # nothing since: said as none, with no names
        self.assertNotIn('logins_by_app', self.db.events[-1])

    def test_a_database_that_does_not_say_its_sessions_leaves_the_logins_out(self):
        self.vitals.beat(self.db)  # rows of user, name and count alone (an older statement's shape)
        self.vitals.beat(self.db)
        self.assertNotIn('logins', self.db.events[0])
        self.assertNotIn('logins_by_app', self.db.events[0])
        self.assertIn('max_parallel_workers_per_gather', vitals.SERVER_NAMES)  # DATA-WORK-MEM's third parameter, read

    def test_the_event_says_the_idle_passes_that_stalled_and_when(self):
        """DB-STALL-EVIDENCE: live 12/11 the swaps of 02:31 and 03:26 UTC took 1.05 and 1.32 s with every statement of
        their second waiting on nothing (a BEGIN running for 127 ms, a 1 ms insert for 1.3 s): the database's host
        stalled, and nothing said whether it stalls only at a landing. The live service's idle dispatch pass is the
        probe it already runs (the same few statements on its kept connection, milliseconds): the event counts them,
        how many took STALL_S or more, and keeps the worst with when they were."""
        wall = [1000.0]
        measured = vitals.Vitals(Settings(), publish=lambda said, subject: None, clock=lambda: self.at[0],
                                 wall=lambda: wall[0])
        measured.passed(0.004, 0)
        measured.passed(1.302, 2)  # a pass that started runs: its length is its work, no probe
        for n in range(7):  # seven stalls, 0.30 to 0.90 s, ten seconds apart
            wall[0] += 10
            measured.passed(0.3 + n / 10, 0)
        measured.passed('no number', 0)  # what cannot be read is no pass and no failure
        measured.beat(self.db)
        measured.beat(self.db)  # records
        said = self.db.events[0]
        self.assertEqual((said['passes'], said['stalled']), (8, 7))
        self.assertEqual(said['stalls'], [{'at': 1000.0 + 10 * n, 'ms': 300 + 100 * (n - 1)}
                                          for n in range(3, 8)])  # the five worst, in the order they happened
        measured.passed(0.004)
        said = measured.record(self.db)  # a new window: its own count, and no list with nothing to say
        self.assertEqual((said['passes'], said['stalled'], 'stalls' in said), (1, 0, False))
        self.assertNotIn('passes', self.vitals.record(self.db))  # a service that never told a pass says nothing of them
        # the wiring: the live service's loop tells every pass, timed from before its tick to after it
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        loop = main[main.index("LOG.info('serve: up')"):]
        self.assertLess(loop.index('began = time.monotonic()'), loop.index('started = workflows.tick(lease, **timed)'))
        self.assertIn('started = workflows.tick(lease, **timed)\n            measured.passed(time.monotonic() - began, len(started))', loop)

    def test_a_stall_says_what_the_database_was_doing_while_it_lasted(self):
        # STALL-SAYS-WHAT: live 12/11 a pass of the live service stalled 0.4 to 0.6 s within a second of nearly every
        # landing, and the event said when and how long, never what ran then
        asked, wall = [], [2000.0]
        busy = [{'q': 'insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values and more',
                 'n': 3, 'ms': 410, 'active': 1, 'of': 'platform.deploy.image_live', 'waits': ['IO:DataFileRead'], 'ago': 480},
                {'q': 'select work.take(', 'n': 4, 'ms': 120, 'active': 0, 'ago': 300},
                {'q': 'COMMIT', 'n': 6, 'ms': 90, 'active': 0}, {'q': 'BEGIN', 'n': 2, 'ms': 3, 'active': 0},
                {'q': 'select 1', 'n': 1, 'ms': 1, 'active': 0}]

        def evidence(window_s):
            asked.append(window_s)
            if len(asked) == 2:
                raise RuntimeError('the database is away')
            return {'busy': busy, 'backends': 31, 'logins': {'tower-consumer:call': 1}}
        measured = vitals.Vitals(Settings(), publish=lambda said, subject: None, clock=lambda: self.at[0],
                                 wall=lambda: wall[0], evidence=evidence)
        measured.passed(0.004, 0)  # a pass inside its time asks nothing
        measured.passed(2.5, 3)    # nor one whose length is its work
        self.assertEqual(asked, [])
        for seconds in (0.401, 0.3, 0.9):
            wall[0] += 10
            measured.passed(seconds, 0)
        self.assertEqual(asked, [0.651, 0.55])  # the stall's seconds and a little before it; the window's first two only
        measured.beat(self.db)
        measured.beat(self.db)  # records
        first, second, third = self.db.events[0]['stalls']
        self.assertEqual(first, {'at': 2010.0, 'ms': 401, 'logins': {'tower-consumer:call': 1}, 'busy': [
            {'q': busy[0]['q'][:vitals.TEXT], 'n': 3, 'ms': 410, 'active': 1, 'of': 'platform.deploy.image_live',
             'waits': ['IO:DataFileRead']},
            {'q': 'select work.take(', 'n': 4, 'ms': 120, 'active': 0}, {'q': 'COMMIT', 'n': 6, 'ms': 90, 'active': 0},
            {'q': 'BEGIN', 'n': 2, 'ms': 3, 'active': 0}]})  # the four that ran longest; `ago` and the fifth stay out
        self.assertEqual((second, third), ({'at': 2020.0, 'ms': 300}, {'at': 2030.0, 'ms': 900}))  # unread, and not asked
        wall[0] += 10
        measured.passed(0.5, 0)  # a new window: its first stalls ask again
        self.assertEqual(len(asked), 3)
        self.assertIn('busy', measured.record(self.db)['stalls'][0])
        # the wiring: the live service gives its vitals the swap's own reading, on a pooled connection
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn('measured = vitals.Vitals(settings, evidence=during)', main)
        self.assertIn('return live_image.busy(db, window_s)', main)

    def test_the_event_carries_the_host_s_memory_swap_and_load_when_the_database_can_say_them(self):
        """DB-HOST-VITALS: live 12/11 the database's host froze for 0.3 to 1.3 s at each landing (DB-STALL-EVIDENCE) and
        whether it is short of memory was a metric of the AWS account, which no session reads. With pg_proctab created
        by the owner's step, work.host_vitals() (migration 0017) answers the host's memory, swap, load and CPU times,
        and the event carries them as `host`; without the extension, or before the migration, there is no field."""
        self.vitals.record(self.db)
        self.assertNotIn('host', self.db.events[-1])  # the function is not there: nothing asked of it, nothing said
        self.db.host = {}
        self.assertNotIn('host', self.vitals.record(self.db))  # there, and the extension is not: null
        self.db.host = {'mem': {'memfree': 31000, 'swapused': 412000}, 'load': {'load1': 3.2}, 'cpu': {'iowait': 9}}
        self.assertEqual(self.vitals.record(self.db)['host'], self.db.host)

    def test_the_event_says_how_the_host_spent_its_window_waiting_for_the_disk_running_or_idle(self):
        """HOST-RATES: pg_cputime's counters run since the host's boot, so one event said nothing of now: on 12/11 the
        share of the host's time spent waiting for the disk (6% of it, three times the time it ran the engine's SQL) came
        out of two events' numbers by hand. The event carries the shares of the window between two readings (each
        counter's growth over the growth of all of them: no clock rate, no count of cores to know), so a change of the
        server's memory is read before and after; the first reading of a process is its first beat's."""
        self.db.host = {'mem': {'swapused': 600000}, 'cpu': {'user': 1000, 'nice': 0, 'system': 2000, 'idle': 90000, 'iowait': 7000}}
        self.vitals.beat(self.db)  # the first beat: no event, the first reading
        self.db.host = {'mem': {'swapused': 610000}, 'cpu': {'user': 1020, 'nice': 0, 'system': 2045, 'idle': 90873, 'iowait': 7062}}
        self.at[0] = 30.0
        self.vitals.beat(self.db)  # records: the shares of those 30 s
        self.assertEqual(self.db.events[0]['host']['rates'],
                         {'user': 0.02, 'nice': 0.0, 'system': 0.045, 'idle': 0.873, 'iowait': 0.062, 'window_s': 30.0})
        self.db.host = {'mem': {'swapused': 610000}, 'cpu': {'user': 1020, 'nice': 0, 'system': 2045, 'idle': 90873, 'iowait': 7062}}
        self.assertNotIn('rates', self.vitals.record(self.db)['host'])  # no counter moved: nothing to divide by
        self.db.host = {'error': 'permission denied'}
        self.assertEqual(self.vitals.record(self.db)['host'], {'error': 'permission denied'})  # no counters: no rates

    def test_the_event_carries_the_server_s_memory_settings_as_the_database_says_them(self):
        """SERVER-SETTINGS-READ: what sizes the server's memory on the micro (work_mem a sort, maintenance_work_mem and
        autovacuum_work_mem a vacuum, max_connections the table of backends) was the default of RDS's parameter group,
        which no session reads. The service reads pg_settings with the login it has (no owner's step) and the event
        carries each as the database says it, with its unit; what the database does not know is left out."""
        self.db.server = [('work_mem', '4096', 'kB'), ('maintenance_work_mem', '65536', 'kB'), ('autovacuum_work_mem', '-1', 'kB'),
                          ('max_connections', '79', None), ('jit', 'off', None)]
        self.assertEqual(self.vitals.record(self.db)['server'],
                         {'work_mem': '4096 kB', 'maintenance_work_mem': '65536 kB', 'autovacuum_work_mem': '-1 kB',
                          'max_connections': '79', 'jit': 'off'})
        self.db.server = [('shared_buffers', '8192', '8kB')]  # pages: the count and the page apart (it read `81928kB`)
        self.assertEqual(self.vitals.record(self.db)['server'], {'shared_buffers': '8192 8kB'})
        self.db.server = []
        self.assertNotIn('server', self.vitals.record(self.db))
        self.assertLessEqual({'shared_buffers', 'work_mem', 'maintenance_work_mem', 'autovacuum_work_mem',
                              'autovacuum_max_workers', 'max_connections', 'synchronous_commit'}, set(vitals.SERVER_NAMES))

    def test_the_event_says_whether_the_runner_s_login_is_there_and_granted(self):
        # RUNNER-OWN-LOGIN: read in production before the runner's stack is told to log in as it
        self.assertEqual(self.vitals.record(self.db)['runner_login'], 'no login')
        self.db.runner = 'f'
        self.assertEqual(self.vitals.record(self.db)['runner_login'], 'not granted')
        self.db.runner = 't'
        self.assertEqual(self.vitals.record(self.db)['runner_login'], 'granted')

    def test_a_threshold_is_published_when_it_starts_and_when_it_ends_only(self):
        self.db.sizes = (15 * GIB, 80, 14 * GIB, 10 ** 7)  # 0.75 of the disk
        self.vitals.beat(self.db)
        self.vitals.beat(self.db)
        self.assertEqual(self.db.events[-1]['alerts'], ['disk'])
        self.assertEqual([subject for subject, _ in self.sent], ['tower database: disk'])
        self.vitals.record(self.db)  # still over: the event says so, nothing is published again
        other = vitals.Vitals(Settings(), publish=lambda said, subject: self.sent.append((subject, said)))
        other.beat(self.db)
        other.beat(self.db)  # nor by the task that replaces this one: the last event already says it
        self.assertEqual((len(self.db.events), len(self.sent)), (3, 1))
        self.db.by_user = {'tower_service': 70}  # 0.875 of max_connections
        self.vitals.beat(self.db)
        self.assertEqual(self.vitals.record(self.db)['alerts'], ['disk', 'connections'])
        self.db.sizes, self.db.by_user = (GIB, 80, GIB // 2, 1000), {'tower_service': 9}
        self.vitals.beat(self.db)
        self.assertEqual(self.vitals.record(self.db)['alerts'], [])
        self.assertEqual([subject for subject, _ in self.sent],
                         ['tower database: disk', 'tower database: disk, connections',
                          'tower database: back under its thresholds'])

    def test_the_connections_threshold_is_said_on_the_beat_that_sees_it_not_on_the_hour(self):
        # VITALS-ALERT-AT-BEAT: live 11/11: the event of 22:14 read 36 of 79; three minutes later the database was at its
        # limit and the port answered 500 for four minutes; the next event, with its alert, was due at 23:14
        self.vitals.beat(self.db)
        self.vitals.beat(self.db)  # the task's first event: 9 of 80, no alert
        self.db.by_user = {'tower_service': 40, 'tower_runner': 30}  # 70 of 80: over 0.8
        self.at[0] = 200.0
        self.vitals.beat(self.db)
        self.assertEqual([each['alerts'] for each in self.db.events], [[], ['connections']])
        self.assertEqual((self.db.events[1]['connections'], self.db.events[1]['window_s']), (70, 200.0))
        self.assertEqual([subject for subject, _ in self.sent], ['tower database: connections'])
        self.vitals.beat(self.db)  # still over: said once, the next event is the hour's
        self.db.by_user = {'tower_service': 9}
        self.vitals.beat(self.db)  # back under: said by the hour's event, not by a beat
        self.assertEqual((len(self.db.events), len(self.sent)), (2, 1))
        self.vitals.record(self.db)  # the hour's event: the window's peak was still over
        self.vitals.beat(self.db)
        self.vitals.record(self.db)  # the next hour's: under for the whole window
        self.assertEqual([each['alerts'] for each in self.db.events[2:]], [['connections'], []])
        self.assertEqual([subject for subject, _ in self.sent][-1], 'tower database: back under its thresholds')
        self.db.by_user = {'tower_service': 70}
        self.vitals.beat(self.db)  # over again: said again at once
        self.assertEqual((len(self.db.events), self.db.events[4]['alerts'], len(self.sent)), (5, ['connections'], 3))

    def test_the_thresholds_and_the_disk_are_data(self):
        measured = vitals.Vitals(Settings(**{vitals.DISK: 2 * GIB, vitals.DISK_RATIO: 0.4, vitals.CONNECTIONS_RATIO: 0.1}),
                                 publish=lambda said, subject: self.sent.append(subject))
        measured.beat(self.db)
        self.assertEqual(measured.record(self.db)['alerts'], ['disk', 'connections'])
        for name in (vitals.DISK, vitals.DISK_RATIO, vitals.CONNECTIONS_RATIO):
            self.assertIn(name, config_data.SPEC)

    def test_a_measure_that_fails_never_raises_and_is_tried_again(self):
        self.db.fail = True
        self.vitals.beat(self.db)
        self.assertIsNone(self.vitals.record(self.db))
        self.db.fail = False
        self.vitals.beat(self.db)
        self.vitals.beat(self.db)
        self.assertEqual(len(self.db.events), 1)


class Memory(unittest.TestCase):
    """The service process's own memory, from the files of /proc and of the cgroup: a temporary directory stands for both."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.status, self.cgroup = self.root / 'status', self.root / 'cgroup'
        (self.cgroup / 'memory').mkdir(parents=True)
        self.status.write_text('Name:\tpython\nVmPeak:\t  400000 kB\nVmHWM:\t  181248 kB\nVmRSS:\t  153600 kB\nThreads:\t9\n')
        self.read = functools.partial(vitals.memory, self.status, self.cgroup)

    def test_the_process_and_its_task_are_read_in_mebibytes_from_cgroup_v2(self):
        (self.cgroup / 'memory.current').write_text(f'{300 * 2 ** 20}\n')
        (self.cgroup / 'memory.max').write_text(f'{512 * 2 ** 20}\n')
        self.assertEqual(self.read(), {'rss_mb': 150.0, 'rss_peak_mb': 177.0, 'task_mb': 300.0, 'task_limit_mb': 512.0})

    def test_cgroup_v1s_files_are_read_when_v2s_are_not_there(self):
        (self.cgroup / 'memory' / 'memory.usage_in_bytes').write_text(f'{210 * 2 ** 20 + 2 ** 19}\n')
        (self.cgroup / 'memory' / 'memory.limit_in_bytes').write_text(f'{512 * 2 ** 20}\n')
        self.assertEqual(self.read(), {'rss_mb': 150.0, 'rss_peak_mb': 177.0, 'task_mb': 210.5, 'task_limit_mb': 512.0})

    def test_no_limit_is_left_out_in_either_version(self):
        (self.cgroup / 'memory.current').write_text('1048576\n')
        (self.cgroup / 'memory.max').write_text('max\n')
        self.assertEqual(self.read(), {'rss_mb': 150.0, 'rss_peak_mb': 177.0, 'task_mb': 1.0})
        (self.cgroup / 'memory.max').unlink()
        (self.cgroup / 'memory' / 'memory.limit_in_bytes').write_text('9223372036854771712\n')
        self.assertNotIn('task_limit_mb', self.read())

    def test_what_cannot_be_read_is_left_out_and_nothing_raises(self):
        self.assertEqual(self.read(), {'rss_mb': 150.0, 'rss_peak_mb': 177.0})  # no cgroup file
        self.status.write_text('VmRSS:\nVmHWM:\t  2048 kB\n')  # a line that is not a number ends the read
        (self.cgroup / 'memory.current').write_text('many\n')
        self.assertEqual(self.read(), {})
        self.assertEqual(vitals.memory(self.root / 'absent', self.root / 'absent'), {})

    def test_the_event_carries_what_was_read(self):
        (self.cgroup / 'memory.current').write_text(f'{300 * 2 ** 20}\n')
        db, measured = Db(), vitals.Vitals(Settings(), publish=lambda said, subject: None)
        with mock.patch.object(vitals, 'memory', self.read):
            said = measured.record(db)
        self.assertEqual({name: said.get(name) for name in ('rss_mb', 'rss_peak_mb', 'task_mb', 'task_limit_mb')},
                         {'rss_mb': 150.0, 'rss_peak_mb': 177.0, 'task_mb': 300.0, 'task_limit_mb': None})
        self.assertEqual(db.events, [said])


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    def setUp(self):
        from infra_db.psql import migrated
        import test_db
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        self.db.rows("insert into work.tenant (name, token_sha256) values ('torre', %(d)s), ('other', %(o)s)",
                     {'d': port.sha256('torre-token'), 'o': port.sha256('other-token')})

    def query(self, token):
        answer = http_port.handle({'rawPath': '/v1/log/query', 'requestContext': {'http': {'method': 'POST'}},
                                   'headers': {'Authorization': f'Bearer {token}'},
                                   'body': json.dumps({'filters': {'type': vitals.EVENT}})}, self.db, '')
        return answer['statusCode'], json.loads(answer['body'])['events']

    def test_the_host_s_vitals_are_null_without_the_extension_and_read_through_its_functions_with_it(self):
        """DB-HOST-VITALS: migration 0017's work.host_vitals() on real Postgres. Without pg_proctab's functions it is
        null and the event has no `host`; with them (stand-ins of the same names and columns here: the extension reads
        the host's /proc, which a test database does not have) it is their rows as they come; a function that fails
        is said, never raised."""
        measured = vitals.Vitals(Settings(), publish=lambda said, subject: None)
        self.assertEqual(self.db.rows(vitals.HOST_THERE), [('t',)])
        if self.db.rows("select to_regproc('pg_memusage') is null")[0][0] == 't':  # the toolchain's Postgres: no pg_proctab
            self.assertEqual(self.db.rows(vitals.HOST), [(None,)])
            self.assertNotIn('host', measured.record(self.db))
            self.db.run("""
                create function public.pg_memusage(out memused bigint, out memfree bigint, out memshared bigint,
                  out membuffers bigint, out memcached bigint, out swapused bigint, out swapfree bigint, out swapcached bigint)
                  language sql as $$ select 900000::bigint, 31000::bigint, 200000::bigint, 4000::bigint, 150000::bigint,
                                            412000::bigint, 600000::bigint, 9000::bigint $$;
                create function public.pg_loadavg(out load1 float4, out load5 float4, out load15 float4, out last_pid int)
                  language sql as $$ select 3.25::float4, 1.5::float4, 0.75::float4, 4242 $$;
                create function public.pg_cputime(out "user" bigint, out nice bigint, out system bigint, out idle bigint,
                  out iowait bigint) language sql as $$ select 10::bigint, 0::bigint, 5::bigint, 900::bigint, 7::bigint $$;
            """)
            host = measured.record(self.db)['host']
            self.assertEqual((host['mem']['memfree'], host['mem']['swapused'], host['load']['load1'], host['cpu']['iowait']),
                             (31000, 412000, 3.25, 7))
            self.db.run("create or replace function public.pg_loadavg(out load1 float4, out load5 float4, out load15 float4, "
                        "out last_pid int) language plpgsql as $$ begin raise exception 'no /proc here'; end $$;")
            self.assertEqual(measured.record(self.db)['host'], {'error': 'no /proc here'})
            # migration 0018: the owner's function first (RDS keeps pg_proctab's own from the service's login)
            server = measured.record(self.db)['server']  # SERVER-SETTINGS-READ: the real pg_settings, with the test's login
            self.assertEqual(server['max_connections'], self.db.rows('show max_connections')[0][0])
            self.assertRegex(server['shared_buffers'], r'^\d+ 8kB$')  # pages of 8 kB, as pg_settings counts them
            self.db.run("create function public.tower_host() returns jsonb language sql as "
                        "$$ select '{\"mem\": {\"memfree\": 5}}'::jsonb $$;")
            self.assertEqual(measured.record(self.db)['host'], {'mem': {'memfree': 5}})
        else:  # a Postgres that has the extension: its real rows
            host = measured.record(self.db)['host']
            self.assertLessEqual({'mem', 'load', 'cpu'}, set(host))

    def test_the_real_statements_measure_the_database_and_write_the_event(self):
        sent = []
        measured = vitals.Vitals(Settings(), publish=lambda said, subject: sent.append(subject))
        measured.beat(self.db)
        measured.beat(self.db)
        (status, (event,)), other = self.query('torre-token'), self.query('other-token')
        said = event['payload']  # the configuration tenant reads it through the port; another tenant does not
        self.assertEqual((status, event['subject'], event['producer'], other), (200, 'database', 'tower-service', (200, [])))
        self.assertGreater(said['database_bytes'], said['log_bytes'])
        self.assertGreater(said['log_bytes'], 0)  # the partitions of log.event, indexes included
        self.assertGreaterEqual(said['connections_peak'], 1)  # this test's own connection
        self.assertEqual(sum(said['peak_by_user'].values()), said['connections_peak'])
        self.assertEqual(sum(said['peak_by_app'].values()), said['connections_peak'])  # DB-LISTEN-ONE: by who opened them
        self.assertIn('psql', said['peak_by_app'])  # this test's own connection says its name
        self.assertGreater(said['max_connections'], said['connections_peak'])
        self.assertEqual((len(said['tables']), said['alerts'], sent), (5, [], []))
        # VITALS-LOGINS: the real statement: every row carries what was born since the last beat and the database's
        # sessions; this test's own connections are the logins (each psql call is one)
        rows = self.db.rows(vitals.CONNECTIONS, {'since': 3600.0})
        self.assertTrue(all(len(row) == 5 for row in rows))
        self.assertGreaterEqual(sum(int(row[3]) for row in rows if row[1] == 'psql'), 1)
        self.assertGreaterEqual(int(rows[0][4]), 1)  # pg_stat_database.sessions of this database
        self.assertEqual(sum(int(row[3]) for row in self.db.rows(vitals.CONNECTIONS, {'since': 0.0}) if row[1] != 'psql'), 0)
        self.assertIsInstance(said.get('logins', 0), int)
        tiny = vitals.Vitals(Settings(**{vitals.DISK: said['database_bytes']}), publish=lambda said, subject: sent.append(subject))
        tiny.beat(self.db)
        self.assertEqual(tiny.record(self.db)['alerts'], ['disk'])  # read back from the last event: published once
        self.assertEqual(tiny.record(self.db)['alerts'], ['disk'])
        self.assertEqual(sent, ['tower database: disk'])


if __name__ == '__main__':
    unittest.main()
