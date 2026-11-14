"""RUNNER-ON-DEMAND (the review's finding 3; the Torre, 13/11 ~14:15 BRT): the runner on Fargate on demand only while Spot
cannot place it, stopped once Spot's runner is up again. A fake ECS and a fake log; the statements are the module's."""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import ondemand  # noqa: E402

TASK = 'arn:aws-partition:ecs:us-east-1:1:task/tower/abc'
HOST = 'ip-10-40-1-2.example.internal'
URL = os.environ.get('TEST_DATABASE_URL', '')
NETWORK = {'subnets': ['s'], 'securityGroups': ['g'], 'assignPublicIp': 'ENABLED'}


class Ecs:
    def __init__(self):
        self.ran, self.stopped, self.status, self.refuse = [], [], 'RUNNING', None

    def run_task(self, **asked):
        self.ran.append(asked)
        if self.refuse:
            return {'tasks': [], 'failures': [{'reason': self.refuse}]}
        return {'tasks': [{'taskArn': TASK}]}

    def describe_tasks(self, cluster, tasks):
        return {'tasks': [{'taskArn': tasks[0], 'lastStatus': self.status, 'attachments': [
            {'details': [{'name': 'privateIPv4Address', 'value': '10.40.1.2'}]}]}]}

    def stop_task(self, cluster, task, reason):
        self.stopped.append((task, reason))


class Log:
    """The log as the look reads it: placement failures, runners up, its own events."""

    def __init__(self):
        self.failures, self.ups, self.said, self.drill = [], [], [], None

    def rows(self, sql, params=None):
        if sql == ondemand.FAILED:
            assert (params['name'], params['service']) == ('SERVICE_TASK_PLACEMENT_FAILURE', 'tower-runner')
            return [(at, self.drill) for at in self.failures if at > params['since']][-1:]
        if sql == ondemand.OWN_UP:
            return [(at,) for at, host in self.ups if at > params['since'] and host.split('.')[0] == params['host']][:1]
        if sql == ondemand.UP:
            return [(host,) for at, host in self.ups if at > params['since'] and host.split('.')[0] != params['host']][-1:]
        if sql == ondemand.OPEN:
            return [(self.said[-1],)] if self.said else []
        if sql == ondemand.SAY:
            self.said.append(params['payload'])
            return []
        raise AssertionError(sql)

    def states(self):
        return [json.loads(each)['state'] for each in self.said]


class TheLook(unittest.TestCase):
    def setUp(self):
        self.now = [1000.0]
        self.ecs, self.log = Ecs(), Log()
        self.look = ondemand.OnDemand(self.ecs, 'tower', NETWORK, clock=lambda: self.now[0])

    def step(self, seconds=5.0):
        self.now[0] += seconds
        return self.look.step(self.log)

    def test_nothing_runs_while_spot_places_the_runner(self):
        self.assertIsNone(self.step())
        self.log.ups.append((self.now[0] + 1, 'ip-10-40-9-9.example.internal'))  # Spot replaced a task: not a failure
        self.assertIsNone(self.step())
        self.assertEqual(self.ecs.ran, [])

    def test_a_placement_failure_runs_one_on_demand_runner_and_spot_back_stops_it(self):
        self.log.failures.append(self.now[0] + 1)
        self.assertEqual(self.step(), 'started')
        (asked,) = self.ecs.ran
        self.assertEqual((asked['taskDefinition'], asked['capacityProviderStrategy'], asked['startedBy']),
                         ('tower-runner', [{'capacityProvider': 'FARGATE', 'weight': 1}], 'ondemand'))
        self.assertEqual(asked['networkConfiguration'], {'awsvpcConfiguration': NETWORK})
        self.log.failures.append(self.now[0] + 1)  # ECS tries again and fails again: still one fallback
        self.assertIsNone(self.step())
        self.assertEqual(len(self.ecs.ran), 1)
        self.log.ups.append((self.now[0] + 1, HOST))  # the fallback itself says it is up: not Spot's
        self.assertIsNone(self.step())
        self.log.ups.append((self.now[0] + 1, 'ip-10-40-7-7.example.internal'))  # Spot's runner up again
        self.assertEqual(self.step(), 'stopped')
        self.assertEqual(self.ecs.stopped, [(TASK, 'RUNNER-ON-DEMAND: Spot placed the runner again')])
        self.assertEqual(self.log.states(), ['started', 'stopped'])
        self.assertIsNone(self.step())  # nothing more to do

    def test_a_drill_s_fallback_is_stopped_once_it_said_it_is_up(self):
        # DRILLS (the Torre, 13/11 ~16:20 BRT): Spot's placement failure provoked; Spot placed the runner all along, so the
        # drill's fallback is stopped once its own task said it is up, not at another runner's up
        self.log.drill = 'd-1'
        self.log.failures.append(self.now[0] + 1)
        self.assertEqual(self.step(), 'started')
        self.log.ups.append((self.now[0] + 1, 'ip-10-40-7-7.example.internal'))  # the Spot runner, up before and after
        self.assertIsNone(self.step())
        self.log.ups.append((self.now[0] + 30, HOST))  # the fallback's own up
        self.assertEqual(self.step(40), 'stopped')
        self.assertEqual(self.ecs.stopped, [(TASK, 'DRILLS: the drill is over')])
        said = [json.loads(each) for each in self.log.said]
        self.assertEqual([(each['state'], each.get('drill')) for each in said], [('started', 'd-1'), ('stopped', 'd-1')])
        self.assertGreater(said[-1]['up_s'], 0)

    def test_a_fallback_that_ended_by_itself_is_said_and_the_next_failure_runs_another(self):
        self.log.failures.append(self.now[0] + 1)
        self.step()
        self.ecs.status = 'STOPPED'
        self.assertEqual(self.step(), 'ended')
        self.ecs.status = 'RUNNING'
        self.log.failures.append(self.now[0] + 1)
        self.assertEqual(self.step(), 'started')
        self.assertEqual(self.log.states(), ['started', 'ended', 'started'])

    def test_a_refused_run_is_tried_at_the_next_failure_and_a_reloaded_service_takes_its_fallback_back(self):
        self.ecs.refuse = 'Capacity is unavailable at this time'
        self.log.failures.append(self.now[0] + 1)
        self.assertEqual(self.step(), 'refused')
        self.assertEqual(self.log.said, [])
        self.ecs.refuse = None
        self.log.failures.append(self.now[0] + 1)
        self.assertEqual(self.step(), 'started')
        again = ondemand.OnDemand(self.ecs, 'tower', NETWORK, clock=lambda: self.now[0])  # the service started again
        self.log.ups.append((self.now[0] + 1, 'ip-10-40-7-7.example.internal'))
        self.now[0] += 5
        self.assertEqual(again.step(self.log), 'stopped')
        self.assertEqual(len(self.ecs.ran), 2)  # no second fallback: the open one was read back



class TheThread(unittest.TestCase):
    def test_it_is_off_without_the_network_and_makes_its_client_at_its_first_active_look(self):
        import threading
        self.assertIsNone(ondemand.start(None, threading.Event(), lambda s: None, environ={}))
        stop, made, looked = threading.Event(), [], threading.Event()

        class Scope:
            def __enter__(self):
                return Log()

            def __exit__(self, *exc):
                return False

        def make():
            made.append(1)
            return ondemand.OnDemand(Ecs(), 'tower', NETWORK)
        active = iter([False, False, True, True])
        thread = ondemand.start(Scope, stop, lambda s: (looked.set(), stop.set()) if len(made) else None,
                                active=lambda: next(active, False), make=make)
        thread.join(5)
        self.assertEqual(made, [1])  # not made while the role waited for it

@unittest.skipUnless(URL, 'TEST_DATABASE_URL: the statements on PostgreSQL')
class OnPostgres(unittest.TestCase):
    """The look's statements on the log as ECS's events and the runner's task_up write it."""

    def setUp(self):
        from infra_db import psql
        import test_db
        name, self.db = psql.migrated(URL)
        self.addCleanup(test_db.destroy, URL, name)

    def event(self, ident, kind, payload):
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                     "(%(id)s, null, %(type)s, clock_timestamp(), 'ecs', 'ecs/service', %(payload)s::jsonb)",
                     {'id': ident, 'type': kind, 'payload': json.dumps(payload)})

    def test_a_placement_failure_of_the_runner_starts_it_and_another_runner_up_stops_it(self):
        import time
        ecs = Ecs()
        look = ondemand.OnDemand(ecs, 'tower', NETWORK)
        self.event('a-1', 'platform.ecs.service_action', {'name': 'SERVICE_STEADY_STATE', 'services': ['tower-runner']})
        self.event('a-2', 'platform.ecs.service_action', {'name': 'SERVICE_TASK_PLACEMENT_FAILURE', 'services': ['tower-service']})
        self.assertIsNone(look.step(self.db))  # neither the runner's failure
        self.event('a-3', 'platform.ecs.service_action', {'name': 'SERVICE_TASK_PLACEMENT_FAILURE', 'level': 'WARN',
                                                          'services': ['tower-runner']})
        look.since -= 1  # the event's clock and the look's
        self.assertEqual(look.step(self.db), 'started')
        self.event('u-1', 'platform.deploy.task_up', {'role': 'runner', 'task': HOST})  # its own
        self.assertIsNone(look.step(self.db))
        time.sleep(0.01)
        self.event('u-2', 'platform.deploy.task_up', {'role': 'runner', 'task': 'ip-10-40-7-7.example.internal'})
        self.assertEqual(look.step(self.db), 'stopped')
        states = [json.loads(each)['state'] for each, in self.db.rows(
            "select payload::text from log.event where type = 'platform.deploy.ondemand' order by occurred_at")]
        self.assertEqual(states, ['started', 'stopped'])
        again = ondemand.OnDemand(ecs, 'tower', NETWORK)
        again.recover(self.db)
        self.assertIsNone(again.task)  # the last word is stopped: nothing open to take back


if __name__ == '__main__':
    unittest.main()
