"""RUNNER-STALL-ALERT (docs/operations/aws-revisao-arquitetura.md, findings 2 and 3): the service watches the runner.

Runs handed over to the runner and not taken (work.run `starting`) past service.runner_stall_alert_s are an event of the
configuration tenant and an alert to the platform's topic, once when it starts and once when it ends.

Hermetic: a stand-in database that answers the two statements; OnPostgres runs them on the migrated tables
(TEST_DATABASE_URL) with the service's real dispatch tick and the runner's real TAKE.
"""
import contextlib
import json
import logging
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import config_data, http_port, port, stall  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')


def setUpModule():
    logging.disable(logging.CRITICAL)  # the alerts and the reads that fail are logged on purpose


def tearDownModule():
    logging.disable(logging.NOTSET)


class Settings:
    tenant = 'torre'

    def __init__(self, limit=None):
        self.limit = limit

    def get(self, name):
        return config_data.SPEC[name][1] if self.limit is None else self.limit


class Db:
    def __init__(self):
        self.waiting, self.events, self.fail, self.ready = (0, 0.0), [], False, []

    def rows(self, sql, params=None):
        if self.fail:
            raise RuntimeError('the database is away')
        if sql == stall.WAITING:
            assert params == {'adapter': 'container'}
            return [self.waiting]
        if sql == stall.RECORD:
            assert params['tenant'] == 'torre'
            self.events.append(json.loads(params['payload']))
            return []
        if sql == stall.READY:
            return [(job,) for job in self.ready]
        if sql == stall.IDLE_RECORD:
            assert params['tenant'] == 'torre'
            self.events.append(json.loads(params['payload']))
            return []
        raise AssertionError(sql)


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


class TheWatch(unittest.TestCase):
    def setUp(self):
        self.db, self.sent, self.clock = Db(), [], Clock()
        self.watch = stall.Watch(Settings(), publish=lambda said, subject: self.sent.append((subject, said)),
                                 clock=self.clock)

    def later(self, seconds, runs, oldest):
        self.clock.now += seconds
        self.db.waiting = (runs, oldest)
        return self.watch.beat(self.db)

    def test_runs_not_taken_past_the_limit_alert_once_and_their_end_once(self):
        beat = stall.SETTLE_S / 2  # the service's heartbeat
        self.assertIsNone(self.watch.beat(self.db))  # nothing handed over
        self.assertIsNone(self.later(beat, 2, 75.0))  # a runner the rollout replaced is warming: under the limit
        said = self.later(beat, 3, 181.5)
        self.assertEqual(said, {'state': 'stalled', 'runs': 3, 'oldest_s': 181.5, 'limit_s': 180.0})
        self.assertIsNone(self.later(beat, 4, 240.0))  # still stalled: said once
        self.assertIsNone(self.later(beat, 1, 12.0))  # the runner is back: it takes what is handed over
        self.assertIsNone(self.later(beat, 0, 0.0))  # RUNNER-STALL-QUIET: calm, not yet for SETTLE_S
        self.assertEqual(self.later(beat, 0, 0.0)['state'], 'recovered')  # calm for SETTLE_S: it takes runs again
        self.assertIsNone(self.later(beat, 0, 0.0))
        self.assertEqual([each['state'] for each in self.db.events], ['stalled', 'recovered'])
        self.assertEqual([subject for subject, _ in self.sent], [stall.SUBJECTS[True], stall.SUBJECTS[False]])

    def test_runs_reaped_and_handed_over_again_stay_stalled_said_once(self):
        # RUNNER-STALL-QUIET, live 16-23/11: runs nobody took, each reaped at its lease and its job handed over again as
        # a new run, so the oldest fell under the limit at each reap; it said recovered and stalled every 2.5 minutes
        self.assertGreaterEqual(stall.SETTLE_S, stall.CALM_S)  # a run that ages from zero is calm for under CALM_S
        self.assertLess(stall.CALM_S, config_data.SPEC[stall.LIMIT][1])
        limit = config_data.SPEC[stall.LIMIT][1]
        lease = limit + stall.SETTLE_S  # any lease past the limit
        self.assertEqual(self.later(0, 3, lease)['state'], 'stalled')
        for every in (stall.SETTLE_S / 2, stall.CALM_S / stall.CALM_S):  # the heartbeat, and a look every second
            ages = [float(age) for age in range(0, int(lease), int(every))]  # a run handed over again at each lease
            for _ in ages:
                for age in ages:
                    self.assertIsNone(self.later(every, 1, age))
        self.assertEqual([each['state'] for each in self.db.events], ['stalled'])
        self.assertEqual(len(self.sent), 1)

    def test_the_limit_is_data_and_stays_under_the_lease(self):
        self.assertEqual(config_data.SPEC[stall.LIMIT], (float, 180.0))
        self.assertLess(config_data.SPEC[stall.LIMIT][1], 300)  # TOWER_LEASE: a run not taken is reaped at five minutes
        quick = stall.Watch(Settings(limit=10.0), publish=lambda said, subject: None)
        self.db.waiting = (1, 11.0)
        self.assertEqual(quick.beat(self.db)['limit_s'], 10.0)

    def test_a_read_that_fails_never_raises_and_says_nothing(self):
        self.db.fail = True
        self.assertIsNone(self.watch.beat(self.db))
        self.db.fail, self.db.waiting = False, (1, 500.0)
        self.assertEqual(self.watch.beat(self.db)['state'], 'stalled')

    def test_the_live_service_beats_it_on_its_heartbeat(self):
        loop = (ROOT / 'infra/service/tower_infra/__main__.py').read_text()
        self.assertIn('taking = stall.Watch(settings)', loop)
        self.assertLess(loop.index('measured.beat(db)'), loop.index('taking.beat(db)'))


class TheStandbysWatch(unittest.TestCase):
    """DISPATCH-STALL-ALERT: a service process that stands by alerts when what is ready is not dispatched."""

    def setUp(self):
        self.db, self.sent, self.clock = Db(), [], Clock()
        self.watch = stall.Idle(Settings(), publish=lambda said, subject: self.sent.append((subject, said)),
                                task='heir', clock=self.clock)

    def later(self, seconds, *ready):
        self.clock.now += seconds
        self.db.ready = list(ready)
        return self.watch.beat(self.db)

    def test_the_same_job_ready_past_the_limit_alerts_once_and_its_dispatch_once(self):
        self.assertIsNone(self.later(0))  # nothing queued
        self.assertIsNone(self.later(30, 'a'))  # found ready: a live dispatcher starts it on its next tick
        self.assertIsNone(self.later(30, 'b'))  # another one, the first was started: the dispatch runs
        self.assertIsNone(self.later(60, 'b', 'c'))
        said = self.later(60, 'b', 'c')  # b has been ready for 120 s of this process's looks: nobody dispatches
        self.assertEqual(said, {'state': 'stalled', 'jobs': 2, 'oldest_s': 120.0, 'limit_s': 120.0, 'task': 'heir'})
        self.assertIsNone(self.later(30, 'b', 'c'))  # said once
        self.assertEqual(self.later(30, 'd')['state'], 'recovered')  # they were started; d is new
        self.assertIsNone(self.later(30))
        self.assertEqual([each['state'] for each in self.db.events], ['stalled', 'recovered'])
        self.assertEqual([subject for subject, _ in self.sent], [stall.IDLE_SUBJECTS[True], stall.IDLE_SUBJECTS[False]])

    def test_the_limit_is_data_past_a_takeover_and_under_the_incident(self):
        self.assertEqual(config_data.SPEC[stall.IDLE_LIMIT], (float, 120.0))
        self.assertGreater(config_data.SPEC[stall.IDLE_LIMIT][1], 3 * config_data.SPEC['deploy.live_stale_s'][1])
        self.assertLess(config_data.SPEC[stall.IDLE_LIMIT][1], 7.7 * 60)  # 11/11 20:41 UTC: 7.7 min with no dispatch
        quick = stall.Idle(Settings(limit=10.0), publish=lambda said, subject: None, clock=self.clock)
        self.db.ready = ['a']
        self.assertIsNone(quick.beat(self.db))
        self.clock.now += 11
        self.assertEqual(quick.beat(self.db)['limit_s'], 10.0)

    def test_a_read_that_fails_never_raises_and_says_nothing(self):
        self.db.fail = True
        self.assertIsNone(self.watch.beat(self.db))
        self.assertEqual((self.db.events, self.sent), ([], []))

    def test_the_service_that_stands_by_beats_it_on_its_heartbeat_and_the_live_one_does_not(self):
        loop = (ROOT / 'infra/service/tower_infra/__main__.py').read_text()
        self.assertIn('idle = stall.Idle(settings, task=None if gate is None else gate.task)', loop)
        standby = loop[loop.index('if gate is not None and not gate.active():  # IMAGE-PREWARM-A: a standby beats'):]
        standby = standby[:standby.index('continue')]
        self.assertIn('idle.beat(loop)', standby)  # in the standby's pass, on the loop's own connection
        self.assertEqual(loop.count('idle.beat('), 1)
        self.assertEqual(stall.mechanisms.RESERVED, 'canary')  # the slot READY leaves to the jobs that name it


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements: a job created by the port, the service's dispatch tick, the runner's TAKE."""

    def setUp(self):
        from runner_world import RunnerWorld
        from test_infra_swap_ready import workflows_with
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db, self.workflows, self.sent = self.world.db, workflows_with([]), []

    def tick(self):
        @contextlib.contextmanager
        def connected():
            yield self.db
        with mock.patch.object(self.workflows, 'connected', connected):
            return self.workflows.tick('5 minutes')

    def events(self):
        answer = http_port.handle({'rawPath': '/v1/log/query', 'requestContext': {'http': {'method': 'POST'}},
                                   'headers': {'Authorization': 'Bearer torre'},
                                   'body': json.dumps({'filters': {'type': stall.EVENT}})}, self.db, port.sha256('installation'))
        return [each['payload'] for each in json.loads(answer['body'])['events']]

    def test_a_run_handed_over_and_not_taken_is_stalled_and_recovered_once_the_runner_takes_it(self):
        clock = Clock()
        watch = stall.Watch(Settings(limit=0.05), publish=lambda said, subject: self.sent.append(subject), clock=clock)
        self.assertIsNone(watch.beat(self.db))  # no run handed over
        self.world.job('one', 'true')
        self.assertEqual(len(self.tick()), 1)  # dispatched: the run is handed over to the runner's executor
        import time
        time.sleep(0.1)
        said = watch.beat(self.db)
        self.assertEqual((said['state'], said['runs']), ('stalled', 1))
        self.assertGreaterEqual(said['oldest_s'], 0.05)
        self.world.runner.once()  # the runner takes it and runs it
        self.assertIsNone(watch.beat(self.db))  # RUNNER-STALL-QUIET: calm from now
        clock.now += stall.SETTLE_S
        self.assertEqual(watch.beat(self.db)['state'], 'recovered')  # calm for SETTLE_S: it takes runs again
        self.assertEqual([each['state'] for each in self.events()], ['stalled', 'recovered'])  # the configuration tenant reads it
        self.assertEqual(self.sent, [stall.SUBJECTS[True], stall.SUBJECTS[False]])

    def idle_events(self):
        answer = http_port.handle({'rawPath': '/v1/log/query', 'requestContext': {'http': {'method': 'POST'}},
                                   'headers': {'Authorization': 'Bearer torre'},
                                   'body': json.dumps({'filters': {'type': stall.IDLE_EVENT}})}, self.db, port.sha256('installation'))
        return [each['payload'] for each in json.loads(answer['body'])['events']]

    def test_a_job_ready_that_no_service_dispatches_is_stalled_and_recovered_once_one_does(self):
        # DISPATCH-STALL-ALERT on the real tables: the process of the role stands by (11/11 20:41 UTC), so nothing ticks
        import time
        watch = stall.Idle(Settings(limit=0.05), publish=lambda said, subject: self.sent.append(subject), task='heir')
        self.assertIsNone(watch.beat(self.db))  # nothing queued
        job = self.world.job('one', 'true')
        self.assertIsNone(watch.beat(self.db))  # ready, just now
        time.sleep(0.1)
        said = watch.beat(self.db)
        self.assertEqual((said['state'], said['jobs'], said['task']), ('stalled', 1, 'heir'))
        self.assertGreaterEqual(said['oldest_s'], 0.05)
        self.assertEqual(self.db.rows(stall.READY), [(job,)])
        self.assertEqual(len(self.tick()), 1)  # a service dispatches it
        self.assertEqual(watch.beat(self.db)['state'], 'recovered')
        self.assertEqual([each['state'] for each in self.idle_events()], ['stalled', 'recovered'])
        self.assertEqual(self.sent, [stall.IDLE_SUBJECTS[True], stall.IDLE_SUBJECTS[False]])

    def test_a_job_that_waits_for_a_slot_a_dependency_or_its_time_is_not_ready(self):
        import time
        watch = stall.Idle(Settings(limit=0.05), publish=lambda said, subject: self.sent.append(subject))
        self.db.rows("update work.capacity set in_use = slots where executor = 'script-runner'")  # the runner is full
        waits = self.world.job('waits-for-a-slot', 'true')
        self.assertEqual(self.db.rows(stall.READY), [])
        # the reserved slot of the deploy canary is free and is not this job's (CANARY-OWN-SLOT)
        self.world.port('PUT', '/v1/executors/script-runner/capacity/canary', 'installation', {'slots': '1'})
        self.assertEqual(self.db.rows(stall.READY), [])
        self.db.rows("update work.job set not_before = now() + interval '1 hour' where id = %(id)s::uuid", {'id': waits})
        self.db.rows("update work.capacity set in_use = 0")
        self.assertEqual(self.db.rows(stall.READY), [])  # its time has not come
        time.sleep(0.1)
        self.assertIsNone(watch.beat(self.db))
        self.assertEqual((self.sent, self.idle_events()), ([], []))


if __name__ == '__main__':
    unittest.main()
