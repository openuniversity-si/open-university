"""DRILLS (the Torre, 13/11 ~16:20 BRT): a port Lambda's rollback rehearsed and Spot's placement failure of the runner
provoked, by the port's ask and the live service's look. A fake Lambda client; the statements on PostgreSQL."""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import drills, fastdeploy, http_port, ondemand, port  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')


class Lambda:
    """An alias that answers the version it names, healthy unless that version is in `sick`."""

    def __init__(self, version='151', sick=()):
        self.version, self.sick, self.moves = version, set(sick), []

    def get_alias(self, FunctionName, Name):
        return {'FunctionVersion': self.version}

    def update_alias(self, FunctionName, Name, FunctionVersion):
        self.moves.append(FunctionVersion)
        self.version = FunctionVersion

    def invoke(self, FunctionName, Qualifier, InvocationType, Payload):
        import io
        sick = self.version in self.sick
        body = {'statusCode': 500 if sick else 200, 'body': json.dumps({'ok': not sick})}
        return {'ExecutedVersion': self.version, 'Payload': io.BytesIO(json.dumps(body).encode()),
                **({'FunctionError': 'Unhandled'} if sick else {})}


class TheLambdaRollback(unittest.TestCase):
    def test_the_placement_it_writes_is_the_one_the_on_demand_look_reads(self):
        self.assertEqual((drills.PLACEMENT, drills.SERVICE), (ondemand.PLACEMENT, ondemand.SERVICE))

    def test_the_alias_goes_to_the_version_before_and_back_each_move_timed(self):
        lam = Lambda()
        said = drills.Drills(fastdeploy.FastDeploy(lam, None, None, sleep=lambda s: None)).lambda_rollback('tower-port-api')
        self.assertEqual(lam.moves, ['150', '151'])
        self.assertEqual((said['current'], said['previous'], said['ok']), ('151', '150', True))
        for key in ('rollback_ms', 'rollback_propagation_ms', 'forward_ms', 'forward_propagation_ms'):
            self.assertGreaterEqual(said[key], 0)

    def test_a_previous_version_that_answers_an_error_is_said_and_the_alias_is_put_back(self):
        lam = Lambda(sick={'150'})
        said = drills.Drills(fastdeploy.FastDeploy(lam, None, None, sleep=lambda s: None)).lambda_rollback('tower-port-api')
        self.assertEqual((lam.version, said['rollback_healthy'], said['forward_healthy'], said['ok']), ('151', False, True, False))


@unittest.skipUnless(URL, 'TEST_DATABASE_URL: the asks, the look and the placement on PostgreSQL')
class OnPostgres(unittest.TestCase):
    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db

    def test_the_routes_are_the_ports(self):
        verbs = {(verb, pattern) for verb, pattern, _ in http_port.ROUTES}
        self.assertIn(('POST', r'/v1/deploy/drills'), verbs)
        self.assertIn(('GET', r'/v1/deploy/drills/(?P<ident>[0-9]{1,24})'), verbs)

    def test_a_rollback_asked_at_the_port_is_done_by_the_look_and_read_back(self):
        asked = self.world.port('POST', '/v1/deploy/drills', 'torre', {'kind': 'lambda-rollback'})
        lam = Lambda()
        look = drills.Drills(fastdeploy.FastDeploy(lam, None, None, sleep=lambda s: None))
        self.assertEqual(look.step(self.db), 1)
        self.assertEqual(look.step(self.db), 0)  # taken once
        said = self.world.port('GET', f"/v1/deploy/drills/{asked['id']}", 'torre')
        self.assertEqual((said['state'], said['kind'], said['ok'], said['previous']), ('done', 'lambda-rollback', True, '150'))
        refused = self.world.port('POST', '/v1/deploy/drills', 'torre', {'kind': 'reboot'})
        self.assertIn('kind is one of', json.dumps(refused))

    def test_a_placement_asked_makes_the_on_demand_look_run_a_drill_and_stop_it_once_up(self):
        asked = self.world.port('POST', '/v1/deploy/drills', 'torre', {'kind': 'runner-placement'})
        self.assertEqual(drills.Drills(None).step(self.db), 1)

        class Ecs:
            ran, stopped = [], []

            def run_task(self, **asked):
                self.ran.append(asked)
                return {'tasks': [{'taskArn': 'arn:task/od'}]}

            def describe_tasks(self, cluster, tasks):
                return {'tasks': [{'lastStatus': 'RUNNING', 'attachments': [{'details': [
                    {'name': 'privateIPv4Address', 'value': '10.40.1.2'}]}]}]}

            def stop_task(self, cluster, task, reason):
                self.stopped.append(reason)
        ecs = Ecs()
        look = ondemand.OnDemand(ecs, 'tower', {'subnets': ['s']})
        look.since = 0.0
        self.assertEqual(look.step(self.db), 'started')
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                     "('up-od', null, 'platform.deploy.task_up', clock_timestamp(), 'runner', 'deploy', %(payload)s::jsonb)",
                     {'payload': json.dumps({'role': 'runner', 'task': 'ip-10-40-1-2.example.internal'})})
        self.assertEqual(look.step(self.db), 'stopped')
        self.assertEqual(ecs.stopped, ['DRILLS: the drill is over'])
        states = [json.loads(each)['state'] for each, in self.db.rows(
            "select payload::text from log.event where type = 'platform.deploy.ondemand' order by occurred_at")]
        self.assertEqual(states, ['started', 'stopped'])
        self.assertEqual(self.world.port('GET', f"/v1/deploy/drills/{asked['id']}", 'torre')['state'], 'done')


if __name__ == '__main__':
    unittest.main()
