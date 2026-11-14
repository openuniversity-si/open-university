"""SLOW-PATH-NO-ROLLOUT-WAIT (docs/operations/aws.md 22.10): the service's side of a slow deploy that waits for no rollout.

The migrations of the head a build deploys are applied by the live service, ahead of that head's tasks, from the code
bundle deploy.sh names in last-build.migrate (autodeploy.migrate, migrations.migrate_bundle), and GET /v1/health?migration
is the build's evidence; so the runner's rollout never waits for the service's. And no build waits for an ECS rollout:
after a build that ended `rolling` the autodeploy holds the ring until each stack's rollout is seen (autodeploy.rolling:
the stack's new task says it is up, __main__.task_up, or the CloudFormation Stack Status Change the port records,
http_port.stack_state, whichever is first; last-build.rolling.until is the safety of a rollout that says neither), then
rings the build that verifies them. And a code-only landing needs no rollout to last: the look writes
deploy.live_code after a swap (autodeploy.live_code), GET /v1/deploy/status shows it and a task ECS starts reads it
(code_bundle.LIVE; the boot itself is in test_infra_code_bundle.py). infra/aws/deploy.sh's side is in test_deploy.py.

Hermetic: the autodeploy's rig of test_infra_autodeploy (fakes, an injected clock); OnPostgres runs the real migrations
and statements (TEST_DATABASE_URL).
"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import __main__ as entry, autodeploy, code_bundle, config_data, http_port, port  # noqa: E402
from test_infra_autodeploy import BASE, BUILD, FakeDb, HEAD, NEXT, Rig, T0, at  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')


def bundle(**files):
    """A code bundle as scripts/lib/lambda_package.py build_code makes it (the migrations under migrations/), its key and
    its sha256."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('tower_infra/__main__.py', '')
        for name, sql in sorted(files.items()):
            archive.writestr(name, sql)
    data = out.getvalue()
    sha = hashlib.sha256(data).hexdigest()
    return data, f'artifacts/lambda/tower-code/{sha}.zip', sha


class Store:
    def __init__(self, objects):
        self.objects, self.reads = objects, []

    def get(self, key):
        self.reads.append(key)
        return self.objects.get(key)


def asked(rig, key, sha, status='in_progress'):
    rig.params[autodeploy.LAST_BUILD] = json.dumps({'status': status, 'build_id': BUILD, 'started': T0, 'ended': 0,
                                                    'migrate': {'key': key, 'sha256': sha, 'want': '0099_more'}})


class MigrateAskTests(unittest.TestCase):
    """What the look does with last-build.migrate before any database is needed."""

    def test_a_build_in_progress_keeps_the_safety_look_short(self):
        rig = Rig()
        rig.watcher.check_every_s, rig.watcher.idle_safety_s = 30, 300
        self.assertEqual(rig.watcher.safety_s(), 300)
        asked(rig, 'k', 's')
        rig.watcher.migrate(None)  # no store: nothing to apply, and the build is seen
        self.assertEqual(rig.watcher.safety_s(), 30)  # the build may ask at any step: the look comes every check_every_s
        rig.build('succeeded', 'a' * 40, T0, T0 + 10)
        rig.watcher.migrate(None)
        self.assertEqual(rig.watcher.safety_s(), 300)

    def test_only_the_code_bundle_named_by_its_own_sha256_is_read_and_once(self):
        data, key, sha = bundle(**{'migrations/0099_more.sql': 'select 1;'})
        rig = Rig()
        rig.watcher.bundles = Store({key: data, 'artifacts/lambda/tower-port-api/x.zip': data})

        class Refuses:
            def rows(self, sql, params=None):
                raise AssertionError('a bundle that is refused never reaches the database')
        for wrong_key, wrong_sha in (('artifacts/lambda/tower-port-api/x.zip', sha), (key, 'f' * 64),
                                     (f'artifacts/lambda/tower-code/{"f" * 64}.zip', 'f' * 64)):
            asked(rig, wrong_key, wrong_sha)
            rig.watcher.migrate(Refuses())  # never raises: the build keeps the old order
        self.assertEqual(rig.watcher.bundles.reads, [f'artifacts/lambda/tower-code/{"f" * 64}.zip'])  # read, absent, refused
        asked(rig, key, sha)
        for _ in range(3):
            rig.watcher.migrate(Refuses())  # the database fails: tried once per bundle, never raised
        self.assertEqual(rig.watcher.bundles.reads.count(key), 1)


def stack_event(stack='tower-app-runner', status='UPDATE_COMPLETE', ident='e-1'):
    """A CloudFormation Stack Status Change as EventBridge delivers it to the port's Lambda."""
    return {'version': '0', 'id': ident, 'source': 'aws.cloudformation', 'detail-type': 'CloudFormation Stack Status Change',
            'time': '2026-11-10T04:08:16Z', 'detail': {
                'stack-id': f'arn:aws-partition:cloudformation:us-east-1:123456789012:stack/{stack}/1125e160-b7a1-11ec-a4d0-0a51b9de0b1f',
                'status-details': {'status': status, 'status-reason': ''}}}


def task_event(task='0529eab22d5741c8a6d253d48edcacd2', last='STOPPED', cluster='tower', **detail):
    """An ECS Task State Change as EventBridge delivers it to the port's Lambda (the runner task of 12/11 13:57 UTC)."""
    return {'version': '0', 'id': 't-1', 'source': 'aws.ecs', 'detail-type': 'ECS Task State Change',
            'time': '2026-11-12T13:57:25Z', 'resources': [f'arn:aws-partition:ecs:us-east-1:123456789012:task/{cluster}/{task}'],
            'detail': {'clusterArn': f'arn:aws-partition:ecs:us-east-1:123456789012:cluster/{cluster}',
                       'taskArn': f'arn:aws-partition:ecs:us-east-1:123456789012:task/{cluster}/{task}', 'lastStatus': last,
                       'group': 'service:tower-runner', 'capacityProviderName': 'FARGATE_SPOT',
                       'taskDefinitionArn': 'arn:aws-partition:ecs:us-east-1:123456789012:task-definition/tower-runner:212',
                       'stopCode': 'SpotInterruption', 'stoppedReason': 'Your Spot Task was interrupted.',
                       'startedAt': '2026-11-12T13:55:31Z', 'stoppingAt': '2026-11-12T13:57:24Z',
                       'stoppedAt': '2026-11-12T13:57:26Z',
                       'containers': [{'name': 'runner', 'exitCode': 0, 'lastStatus': 'STOPPED'}], **detail}}


def service_event(name='SERVICE_TASK_PLACEMENT_FAILURE', service='tower-runner', cluster='tower', ident='s-1'):
    """An ECS Service Action as EventBridge delivers it (12/11 13:57:48 UTC: no Spot capacity for the runner)."""
    return {'version': '0', 'id': ident, 'source': 'aws.ecs', 'detail-type': 'ECS Service Action',
            'resources': [f'arn:aws-partition:ecs:us-east-1:123456789012:service/{cluster}/{service}'],
            'detail': {'eventType': 'ERROR', 'eventName': name, 'reason': 'RESOURCE:FARGATE',
                       'clusterArn': f'arn:aws-partition:ecs:us-east-1:123456789012:cluster/{cluster}'}}


class RollingDb(FakeDb):
    """The autodeploy's fake log, with the stacks' ends the port recorded: (when, stack)."""

    def __init__(self):
        super().__init__()
        self.ends, self.live_code_of, self.ups = [], [], []  # ups: (when, stack, image) of each task_up, VERIFY-AT-UP

    def rows(self, sql, params=None):
        if sql == autodeploy.STACKS_ENDED:
            return sorted({(stack,) for when, stack in self.ends if when >= params['since']})
        if sql == autodeploy.TASKS_UP:
            return [(stack, image) for when, stack, image in self.ups if when >= params['since']]
        if sql == autodeploy.LIVE_CODE_WRITE:
            self.live_code_of.append(params['head'])
        return super().rows(sql, params)


class RollingTests(unittest.TestCase):
    """After a build that started the rollouts and ended, the ring waits for the stacks' end, then verifies."""

    def rig(self, until=T0 + 600):
        rig = Rig()
        rig.db = RollingDb()
        rig.watcher.check_every_s, rig.watcher.idle_safety_s = 30, 300
        rig.params[autodeploy.LAST_SHA] = 'z' * 40
        rig.db.push(T0 - 900, HEAD)
        rig.db.ledger.append((autodeploy.RUNG, at(T0 - 300), {'build': BUILD, 'head': HEAD, 'source': 'autodeploy'}))
        rig.params[autodeploy.LAST_BUILD] = json.dumps({
            'status': 'rolling', 'base_head': HEAD, 'started': T0 - 290, 'ended': T0 - 100, 'build_id': BUILD,
            'targets': ['service', 'port', 'runner'],
            'rolling': {'head': HEAD, 'until': until, 'stacks': {'service': {'t0': T0 - 120, 'hash': 'a'},
                                                                 'runner': {'t0': T0 - 110, 'hash': 'b'}}}})
        return rig

    def step(self, rig, later=0):
        rig.now += later
        return rig.watcher.step(force=True)

    def test_the_ring_waits_for_every_rolling_stack_and_then_rings_the_build_that_verifies(self):
        rig = self.rig()
        action, reason = self.step(rig)
        self.assertEqual((action, reason.split(';')[0]), ('skip', 'rolling: runner, service still rolling out'))
        self.assertEqual(rig.rings, [])
        self.assertEqual(rig.watcher.safety_s(), 30)  # in flight: the safety look stays short
        cycle = [payload for kind, payload in rig.db.inserted if kind == autodeploy.CYCLE]
        self.assertEqual((cycle[0]['status'], cycle[0]['seconds']), ('rolling', 190))  # the build's clock: no rollout in it
        rig.db.ends.append((T0 + 150, 'tower-app-service'))
        self.assertEqual(self.step(rig, 160)[1].split(';')[0], 'rolling: runner still rolling out')
        rig.db.ends.append((T0 - 3000, 'tower-app-runner'))  # an end before this rollout started is not its end
        self.assertEqual(self.step(rig, 10)[1].split(';')[0], 'rolling: runner still rolling out')
        rig.db.ends.append((T0 + 290, 'tower-app-runner'))
        self.assertEqual(self.step(rig, 120), ('ring', 'started'))  # the event woke the look: no clock in between
        self.assertEqual(len(rig.rings), 1)

    def test_a_new_task_up_on_the_rollouts_image_is_its_rollout_seen_and_rings_the_build_that_settles_it(self):
        # VERIFY-AT-UP: the stack's end comes 53 to 93 s after ECS is done with it (the old task's exit, Fargate's deprovision,
        # CloudFormation's wait); a task of the stack up on the image the build deployed is the rollout seen, rule or no rule
        rig = self.rig()
        last = json.loads(rig.params[autodeploy.LAST_BUILD])
        for name in ('service', 'runner'):
            last['rolling']['stacks'][name]['image'] = 'registry.test/tower-service:two'
        rig.params[autodeploy.LAST_BUILD] = json.dumps(last)
        rig.db.ends.append((T0 - 2000, 'tower-app-data'))  # the rule is there: an end was recorded
        rig.db.ups += [(T0 - 115, 'tower-app-service', 'registry.test/tower-service:one'),  # the old image: not this rollout
                       (T0 - 3000, 'tower-app-runner', 'registry.test/tower-service:two')]  # before the rollout started
        self.assertEqual(self.step(rig)[1].split(';')[0], 'rolling: runner, service still rolling out')
        rig.db.ups.append((T0 - 30, 'tower-app-service', 'registry.test/tower-service:two'))
        self.assertEqual(self.step(rig, 10)[1].split(';')[0], 'rolling: runner still rolling out')
        rig.db.ups.append((T0 - 10, 'tower-app-runner', 'registry.test/tower-service:two'))
        self.assertEqual(self.step(rig, 10), ('ring', 'started'))  # every stack's new task is up: no stack's end awaited
        # the cycle of the build that settled them carries the seconds to each one's up
        verifier = 'tower-infra-deploy:3333'
        rig.params[autodeploy.LAST_BUILD] = json.dumps({
            'status': 'succeeded', 'base_head': HEAD, 'started': rig.now + 20, 'ended': rig.now + 45, 'build_id': BUILD,
            'targets': ['service', 'port', 'runner'], 'rolling': {'head': HEAD, 'settling': True, 'until': 0, 'stacks': {
                'service': {'t0': T0 - 120, 'hash': 'a', 'image': 'i', 'up': 90}, 'runner': {'t0': T0 - 110, 'hash': 'b', 'up': 100}}}})
        self.assertEqual(autodeploy.settled_up(json.loads(rig.params[autodeploy.LAST_BUILD])),
                         {'tower-app-service': 90, 'tower-app-runner': 100})
        self.assertEqual(autodeploy.settled_up({'status': 'rolling', 'rolling': {'stacks': {'runner': {'up': 3}}}}), {})
        self.assertIsNone(rig.watcher.rolling(rig.db, json.loads(rig.params[autodeploy.LAST_BUILD]), rig.now))  # green: no wait

    def test_the_cycle_of_the_build_that_verified_carries_the_wait_and_each_stacks_rollout(self):
        rig = self.rig()
        self.step(rig)
        rig.db.ends += [(T0 + 150, 'tower-app-service'), (T0 + 290, 'tower-app-runner')]
        verifier = 'tower-infra-deploy:2222'
        rig.answers = [{'statusCode': 202, 'body': json.dumps({'build': verifier})}]
        self.assertEqual(self.step(rig, 300), ('ring', 'started'))  # the verifying build is rung
        rollout = {'tower-app-service': 270, 'tower-app-runner': 400, 'tower-app-data': 9}
        rig.params[autodeploy.LAST_BUILD] = json.dumps({
            'status': 'succeeded', 'base_head': HEAD, 'started': rig.now + 40, 'ended': rig.now + 65, 'build_id': verifier,
            'targets': ['service', 'port', 'runner'], 'rollout': rollout, 'rollout_wait_s': 390})
        rig.params[autodeploy.LAST_SHA] = HEAD
        rig.db.push(rig.now + 50, NEXT)  # the look after it settles the build (a newer head keeps it from the memory's skip)
        self.step(rig, 100)
        cycles = [payload for kind, payload in rig.db.inserted if kind == autodeploy.CYCLE]
        self.assertEqual([(each['status'], each['seconds'], each.get('rollout_wait_s')) for each in cycles],
                         [('rolling', 190, None), ('succeeded', 25, 390)])
        self.assertEqual(cycles[-1]['rollout'], rollout)
        shown = rig.db.observed[-1][1]['cycles']
        self.assertEqual((shown[-1]['rollout_wait_s'], 'rollout_wait_s' in shown[0]), (390, False))  # GET /v1/deploy/status
        # VERIFY-AT-UP: each cycle keeps its build's own start and end: the slow path whole, the rolling build's start to the
        # verifying build's end (the cycle's event is written when a look sees that end, up to minutes later)
        self.assertEqual((shown[-1]['started'], shown[-1]['ended']), (rig.now - 100 + 40, rig.now - 100 + 65))
        import medir
        status = {'cycles': [{'at': 1000, 'seconds': 120, 'status': 'rolling'},
                             {'at': 1500, 'seconds': 45, 'status': 'succeeded', 'started': 1350, 'ended': 1395},
                             {'at': 1600, 'seconds': 20, 'status': 'succeeded'},
                             {'at': 2000, 'seconds': 100, 'status': 'rolling', 'started': 1890, 'ended': 1990},
                             {'at': 2400, 'seconds': 40, 'status': 'failed', 'started': 2300, 'ended': 2340}]}
        self.assertEqual(medir.slow_paths(status), [515.0, 450.0])
        self.assertEqual(medir.from_deploy_status({**status, 'cycles': [{**each, 'settled': {'tower-app-runner': 95}}
                                                                        for each in status['cycles'][:2]]})['deploy_settled_s'],
                         [95.0, 95.0])

    def test_a_lost_event_is_covered_by_the_safety_the_build_set(self):
        rig = self.rig(until=T0 + 400)
        self.assertEqual(self.step(rig, 399)[0], 'skip')
        self.assertEqual(self.step(rig, 1), ('ring', 'started'))  # no stack event came: rung anyway, the build waits for what is left

    def test_a_newer_head_is_not_rung_while_the_stacks_roll_and_goes_with_the_verifying_build(self):
        rig = self.rig()
        rig.db.push(T0 - 50, NEXT)  # a merge during the rollout
        self.assertEqual(self.step(rig)[1].split(':')[0], 'rolling')
        self.assertEqual(rig.rings, [])
        rig.db.ends += [(T0 + 5, 'tower-app-service'), (T0 + 5, 'tower-app-runner')]
        self.assertEqual(self.step(rig, 10), ('ring', 'started'))  # one build: it verifies and deploys the current head

    def test_the_look_writes_the_live_code_of_the_bases_newest_head_only(self):
        rig = self.rig()
        self.step(rig)
        rig.db.push(T0 - 50, NEXT)  # a landing since: the swap of the head before it is no longer the one to write
        self.step(rig, 1)
        self.assertEqual(rig.db.live_code_of, [HEAD, NEXT])
        self.assertIn("payload->>'head' = %(head)s", autodeploy.LIVE_CODE_WRITE)

    def test_a_rolling_build_is_not_deployed_and_the_observation_says_it(self):
        rig = self.rig()
        self.step(rig)
        seen = rig.db.observed[-1][1]
        self.assertEqual((seen['last_build']['status'], seen['ring']['action'], seen['pending']), ('rolling', 'skip', 1))
        self.assertIsNone(rig.watcher.deployed)


class StackEventTests(unittest.TestCase):
    """The port turns the CloudFormation event of an app stack's end into the log event that wakes the autodeploy."""

    def handled(self, event):
        writes = []

        class Db:
            def rows(self, sql, params=None):
                writes.append((sql, params))
                return []
        return http_port.handle(event, Db(), 'x'), writes

    def test_the_end_of_an_app_stacks_operation_is_one_ended_event(self):
        said, writes = self.handled(stack_event())
        ident = 'platform.deploy.ended:tower-app-runner:update_complete:e-1'
        self.assertEqual(said, {'event_id': ident})
        (sql, params), = writes
        self.assertIn("'platform.deploy.ended'", sql)  # the type migration 0009 notifies tower_deploy for
        self.assertIn("'cloudformation', 'deploy/stack'", sql)
        self.assertEqual((params['id'], json.loads(params['payload'])),
                         (ident, {'stack': 'tower-app-runner', 'status': 'update_complete', 'source': 'cloudformation'}))
        said, _ = self.handled(stack_event(status='UPDATE_ROLLBACK_COMPLETE', ident='e-2'))  # a rollback ends the operation too
        self.assertEqual(said, {'event_id': 'platform.deploy.ended:tower-app-runner:update_rollback_complete:e-2'})

    def test_a_status_in_progress_another_stack_or_an_http_call_writes_nothing(self):
        for event in (stack_event(status='UPDATE_IN_PROGRESS'), stack_event(status='UPDATE_COMPLETE_CLEANUP_IN_PROGRESS'),
                      stack_event(stack='tower-bootstrap'), {**stack_event(), 'detail': 'x'}, {**stack_event(), 'detail': {}}):
            said, writes = self.handled(event)
            self.assertEqual((said, writes), ({'ignored': True}, []))
        said, writes = self.handled({**stack_event(), 'requestContext': {'http': {'method': 'POST'}}, 'rawPath': '/x'})
        self.assertEqual((said['statusCode'], writes), (404, []))  # an HTTP call is never read as an EventBridge event


class EcsEventTests(StackEventTests):
    """ECS-STOPS-IN-LOG: why a task of the engine stopped is kept in the engine's own log. ECS forgets a stopped task's
    stopCode and stoppedReason within the hour, and nothing kept the event: on 12/11 a runner task stopped 47 s after
    it started and an hour later the account could only infer a Spot interruption from the runner's own log."""

    def test_a_stopped_task_of_the_cluster_is_one_event_with_its_code_and_reason(self):
        said, writes = self.handled(task_event())
        ident = 'platform.ecs.task_stopped:0529eab22d5741c8a6d253d48edcacd2'
        self.assertEqual(said, {'event_id': ident})
        (sql, params), = writes
        self.assertIn('where not exists', sql)  # EventBridge delivers at least once, and a task says STOPPED more than once
        self.assertEqual((params['id'], params['type'], params['subject']), (ident, 'platform.ecs.task_stopped', 'ecs/task'))
        self.assertEqual(json.loads(params['payload']), {
            'task': '0529eab22d5741c8a6d253d48edcacd2', 'group': 'service:tower-runner', 'definition': 'tower-runner:212',
            'capacity': 'FARGATE_SPOT', 'stop_code': 'SpotInterruption', 'reason': 'Your Spot Task was interrupted.',
            'containers': [{'name': 'runner', 'exit': 0}], 'started_at': '2026-11-12T13:55:31Z',
            'stopping_at': '2026-11-12T13:57:24Z', 'stopped_at': '2026-11-12T13:57:26Z'})
        long = self.handled(task_event(stoppedReason='x' * 5000, containers=[{'name': 'runner', 'exitCode': 137,
                                                                               'reason': 'OutOfMemoryError: ' + 'y' * 5000}]))
        payload = json.loads(long[1][0][1]['payload'])
        self.assertEqual((len(payload['reason']), len(payload['containers'][0]['reason']), payload['containers'][0]['exit']),
                         (500, 500, 137))

    def test_a_stopped_task_keeps_the_times_its_rollout_is_made_of(self):
        # ROLLOUT-PARTS: made, pulled, connected, its containers ended (the rest to STOPPED is Fargate's)
        times = {'createdAt': '2026-11-12T13:54:40Z', 'pullStartedAt': '2026-11-12T13:54:55Z',
                 'pullStoppedAt': '2026-11-12T13:55:20Z', 'connectivityAt': '2026-11-12T13:54:50Z',
                 'executionStoppedAt': '2026-11-12T13:57:25Z'}
        payload = json.loads(self.handled(task_event(**times))[1][0][1]['payload'])
        self.assertEqual({name: payload[name] for name in ('created_at', 'pull_started_at', 'pull_stopped_at',
                                                            'connectivity_at', 'execution_stopped_at')},
                         dict(zip(('created_at', 'pull_started_at', 'pull_stopped_at', 'connectivity_at',
                                   'execution_stopped_at'), times.values())))

    def test_a_rollout_is_decomposed_part_by_part_from_the_build_that_started_it_to_its_stacks_end(self):
        # ROLLOUT-PARTS: the 275 s rollout of 12/11 22:50 UTC, as the status keeps it
        sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
        import medir
        began = medir.at_of('2026-11-12T22:50:27Z')
        status = {'cycles': [{'at': began, 'status': 'rolling'},
                             {'at': began + 1300, 'status': 'succeeded', 'rollout': {'tower-app-runner': 275}}],
                  'ecs': [{'type': 'platform.ecs.task_stopped', 'group': 'service:tower-runner', 'stop_code': 'SpotInterruption',
                           'started_at': '2026-11-12T22:51:15Z', 'created_at': '2026-11-12T22:50:40Z',
                           'pull_started_at': '2026-11-12T22:50:50Z', 'pull_stopped_at': '2026-11-12T22:51:05Z'},
                          {'type': 'platform.ecs.task_stopped', 'group': 'service:tower-runner',
                           'stop_code': 'ServiceSchedulerInitiated', 'started_at': '2026-11-12T22:08:28Z',
                           'stopping_at': '2026-11-12T22:52:53Z', 'execution_stopped_at': '2026-11-12T22:53:00Z',
                           'stopped_at': '2026-11-12T22:53:34Z'}],
                  'runner_life': [{'type': 'platform.deploy.task_up', 'stack': 'tower-app-runner',
                                   'at': medir.at_of('2026-11-12T22:52:31Z')}]}
        found = medir.rollout_parts(status)
        self.assertEqual({name: values for name, values in found.items() if values}, {
            'rollout_running_s': [48.0], 'rollout_up_s': [76.0], 'rollout_healthy_s': [98.0], 'rollout_exit_s': [7.0],
            'rollout_deprovision_s': [34.0], 'rollout_after_s': [88.0], 'rollout_placed_s': [13.0], 'rollout_pull_s': [15.0]})

    def test_a_service_s_action_is_one_event_with_its_name_and_reason(self):
        said, writes = self.handled(service_event())
        self.assertEqual(said, {'event_id': 'platform.ecs.service_action:s-1'})
        (sql, params), = writes
        self.assertEqual((params['type'], json.loads(params['payload'])), ('platform.ecs.service_action', {
            'name': 'SERVICE_TASK_PLACEMENT_FAILURE', 'level': 'ERROR', 'reason': 'RESOURCE:FARGATE',
            'services': ['tower-runner']}))

    def test_a_task_not_stopped_another_cluster_s_or_an_http_call_writes_nothing(self):
        for event in (task_event(last='RUNNING'), task_event(last='DEPROVISIONING'), task_event(cluster='another'),
                      {**task_event(), 'detail': 'x'}, {**task_event(), 'detail-type': 'ECS Container Instance State Change'},
                      service_event(cluster='another'), {**service_event(), 'detail': {}}):
            said, writes = self.handled(event)
            self.assertEqual((said, writes), ({'ignored': True}, []), event)
        said, writes = self.handled({**task_event(), 'requestContext': {'http': {'method': 'POST'}}, 'rawPath': '/x'})
        self.assertEqual((said['statusCode'], writes), (404, []))


class TaskUpTests(unittest.TestCase):
    """A task ECS started says it is up, once, where its role begins to work; never a standby, a reload or an error."""

    TASK = {'TOWER_IMAGE': 'registry.test/tower-service:two', 'TOWER_IMAGE_DIGEST': 'd' * 64, 'TOWER_RUNNER_NAME': 'task-1'}

    def said(self, role, environ, fail=None):
        writes = []

        class Db:
            def rows(self, sql, params=None):
                if fail:
                    raise fail
                writes.append((sql, params))
                return []

        @contextlib.contextmanager
        def scope():
            yield Db()
        return entry.task_up(role, scope, environ), writes

    def test_the_event_names_the_tasks_stack_and_notifies_the_autodeploys_channel(self):
        done, writes = self.said('runner', self.TASK)
        (sql, params), = writes
        self.assertTrue(done)
        self.assertIn("pg_notify('tower_deploy', type)", sql)  # migration 0009's trigger does not name this type
        self.assertRegex(params['id'], r'^platform\.deploy\.task_up:runner:task-1:\d+$')
        self.assertEqual(json.loads(params['payload']), {
            'stack': 'tower-app-runner', 'role': 'runner', 'task': 'task-1', 'image': self.TASK['TOWER_IMAGE'], 'code': 'd' * 64})

    def test_a_standby_a_reloaded_process_and_a_failed_write_say_nothing_and_never_raise(self):
        self.assertEqual(self.said('service', {**self.TASK, code_bundle.STANDBY: '1'}), (False, []))  # no task of the stack
        self.assertEqual(self.said('service', {**self.TASK, code_bundle.RELOADED: '{"digest": "x"}'}), (False, []))  # no rollout
        with self.assertLogs('tower_infra', 'ERROR'):
            self.assertEqual(self.said('service', self.TASK, fail=RuntimeError('no database')), (False, []))

    def test_serve_and_run_container_say_it_when_they_are_up(self):
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        serve, runner = main.index("LOG.info('serve: up')"), main.index("LOG.info('run-container: up")
        self.assertLess(serve, main.index("task_up('service', ", serve))
        self.assertLess(main.index("task_up('service', ", serve), main.index('while not stop.is_set()', serve))
        self.assertLess(main.index('prewarm(container, boxes, connect, name)', main.index('def run_container')), runner)
        self.assertLess(runner, main.index("task_up('runner', ", runner))  # after the warm-up: the slots open next
        self.assertLess(main.index("task_up('runner', ", runner), main.index('runner.serve_all(', runner))


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real migrations: the live service applies what the head's bundle adds, and the port says so."""

    def setUp(self):
        from infra_db import psql
        import test_db
        name, self.db = psql.migrated(URL)
        self.addCleanup(test_db.destroy, URL, name)
        self.newest = sorted(path.stem for path in (ROOT / 'infra/db/migrations').glob('*.sql'))[-1]

    def health(self, query='migration=1'):
        said = http_port.handle({'requestContext': {'http': {'method': 'GET'}}, 'rawPath': '/v1/health',
                                 'rawQueryString': query}, self.db, 'x')
        return json.loads(said['body'])

    def test_the_live_service_applies_the_heads_migrations_and_the_port_answers_the_newest(self):
        self.assertEqual(self.health()['migration'], self.newest)
        self.assertNotIn('migration', self.health(''))  # only when asked: the smoke's and the probes' call is one read
        repo = {f'migrations/{path.name}': path.read_text() for path in (ROOT / 'infra/db/migrations').glob('*.sql')}
        data, key, sha = bundle(**repo, **{'migrations/9998_rollout_a.sql': 'create table work.rollout_a (id int);',
                                           'migrations/9999_rollout_b.sql': 'alter table work.rollout_a add column b int;',
                                           'migrations/README.md': 'not a migration'})
        rig = Rig()
        rig.watcher.bundles = Store({key: data})
        asked(rig, key, sha)
        rig.watcher.migrate(self.db)
        self.assertEqual(self.health()['migration'], '9999_rollout_b')
        self.assertEqual(self.db.rows("select count(*) from information_schema.columns where table_schema = 'work' "
                                      "and table_name = 'rollout_a'"), [('2',)])
        applied = self.db.rows("select payload->>'migration', producer from log.event where type = 'platform.migration.applied' "
                               "and payload->>'migration' > %(newest)s order by 1", {'newest': self.newest})
        self.assertEqual(applied, [('9998_rollout_a', 'autodeploy'), ('9999_rollout_b', 'autodeploy')])
        rig.watcher.migrate(self.db)  # the same ask again (every look reads last-build): nothing read, nothing applied
        self.assertEqual(rig.watcher.bundles.reads, [key])

    def test_a_stopped_task_and_a_service_s_action_are_recorded_once_on_the_real_log(self):
        # ECS-STOPS-IN-LOG: the real statement; a task says STOPPED more than once and EventBridge delivers at least once
        for event in (task_event(), task_event(), task_event(task='ab3bef84'), service_event(), service_event(),
                      service_event('SERVICE_STEADY_STATE', ident='s-2')):
            http_port.handle(event, self.db, 'x')
        self.assertEqual(self.db.rows("select type, count(*), count(tenant_id), min(payload->>'stop_code') from log.event "
                                      "where type like 'platform.ecs.%' group by type order by type"),
                         [('platform.ecs.service_action', '2', '0', None), ('platform.ecs.task_stopped', '2', '0', 'SpotInterruption')])
        # ECS-STOPS-READ: and the deploy status shows them, newest first, each with its type: the log's query answers a
        # tenant's events only, and these are the platform's (no tenant), so nothing could read what was kept
        shown = port.deploy_status(self.db, ('installation', None))['ecs']
        self.assertEqual(sorted((each['type'], each.get('task') or each.get('name')) for each in shown), [
            ('platform.ecs.service_action', 'SERVICE_STEADY_STATE'), ('platform.ecs.service_action', 'SERVICE_TASK_PLACEMENT_FAILURE'),
            ('platform.ecs.task_stopped', '0529eab22d5741c8a6d253d48edcacd2'), ('platform.ecs.task_stopped', 'ab3bef84')])
        stopped = next(each for each in shown if each.get('task') == '0529eab22d5741c8a6d253d48edcacd2')
        self.assertEqual((stopped['stop_code'], isinstance(stopped['at'], (int, float))), ('SpotInterruption', True))
        self.assertEqual([each['at'] for each in shown], sorted((each['at'] for each in shown), reverse=True))

    def test_the_stacks_end_the_port_records_is_what_the_autodeploy_reads_once_per_event(self):
        for event in (stack_event(), stack_event(), stack_event('tower-app-service', 'UPDATE_ROLLBACK_COMPLETE', 'e-2'),
                      stack_event('tower-app-port', 'UPDATE_IN_PROGRESS', 'e-3')):
            http_port.handle(event, self.db, 'x')
        now = float(self.db.rows('select extract(epoch from clock_timestamp())')[0][0])
        self.assertEqual(sorted(self.db.rows(autodeploy.STACKS_ENDED, {'since': now - 60})),
                         [('tower-app-runner',), ('tower-app-service',)])
        self.assertEqual(self.db.rows(autodeploy.STACKS_ENDED, {'since': now + 60}), [])  # an end before the rollout's start
        self.assertEqual(self.db.rows("select count(*), count(tenant_id) from log.event where type = 'platform.deploy.ended'"),
                         [('2', '0')])  # delivered twice, recorded once; the installation's, like a build's end

    def test_a_new_tasks_up_wakes_the_look_and_with_the_stacks_end_of_the_other_the_ring_waits_no_more(self):
        from infra_db import psql
        heard = []

        class Listening:  # the task's statement, on a session that listens as the autodeploy's look does
            def rows(_, sql, params=None):
                sql = psql.PLACEHOLDER.sub(lambda found: psql.literal(params[found.group(1)]), sql)
                heard.append(self.db.call(['-A', '-t', '-f', '-'], script=f'listen tower_deploy;\n{sql};\nselect 1;\n'))
                return []

        @contextlib.contextmanager
        def scope():
            yield Listening()
        now = float(self.db.rows('select extract(epoch from clock_timestamp())')[0][0])
        last = {'status': 'rolling', 'rolling': {'head': HEAD, 'until': now + 600, 'stacks': {
            'service': {'t0': now - 5, 'hash': 'a'}, 'runner': {'t0': now - 4, 'hash': 'b'}}}}
        rig = Rig()
        self.assertEqual(rig.watcher.rolling(self.db, last, now).split(';')[0], 'rolling: runner, service still rolling out')
        self.assertTrue(entry.task_up('runner', scope, TaskUpTests.TASK))
        self.assertIn('Asynchronous notification "tower_deploy" with payload "platform.deploy.task_up"', heard[0])
        self.assertEqual(rig.watcher.rolling(self.db, last, now).split(';')[0], 'rolling: service still rolling out')
        # (no CloudFormation event was ever recorded: the EventBridge rule is not there, and a task up is all there is)
        http_port.handle(stack_event('tower-app-service'), self.db, 'x')  # the other stack's end, by CloudFormation's event
        # RING-AT-STACK-END: the rule is there (an end was recorded): a stack's rollout is seen at its own end, not when its
        # new task is up. The build rung at the task's up came before the stack's end and waited for it in its own
        # seconds (wait:service 41 to 92 s, wait:runner 19 to 75 s, live 11/11): the wait Daniel took off the build's clock
        self.assertEqual(rig.watcher.rolling(self.db, last, now).split(';')[0], 'rolling: runner still rolling out')
        http_port.handle(stack_event('tower-app-runner', ident='e-9'), self.db, 'x')
        self.assertIsNone(rig.watcher.rolling(self.db, last, now))  # every rollout is seen: the verifying build is rung
        later = {**last, 'rolling': {**last['rolling'], 'stacks': {'runner': {'t0': now + 60, 'hash': 'c'}}}}
        self.assertEqual(rig.watcher.rolling(self.db, later, now).split(';')[0],
                         'rolling: runner still rolling out')  # a task up before a rollout started is not that rollout's

    SWAP = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values (%(id)s, null, "
            "'platform.deploy.image_swap', clock_timestamp(), 'port', 'deploy/image', %(payload)s::jsonb)")

    def swap(self, digest, head, swapped=True):
        self.db.rows(self.SWAP, {'id': f'platform.deploy.image_swap:{head}', 'payload': json.dumps(
            {'digest': digest, 'head': head, 'swapped': swapped, 'by': 'landing'})})

    def datum(self):
        return port.deploy_status(self.db, ('installation', None))['live_code']  # GET /v1/deploy/status: what deploy.sh reads

    def test_the_look_writes_the_live_code_once_per_swap_and_the_status_shows_it(self):
        self.db.rows("insert into work.tenant (name, token_sha256) values (%(name)s, %(token)s)",
                     {'name': config_data.TENANT, 'token': 'f' * 64})
        rig = Rig()
        self.assertEqual(self.datum(), '')
        rig.watcher.live_code(self.db, 'e' * 40)  # no swap yet: nothing written
        self.swap('c' * 64, 'e' * 40, swapped=False)  # a landing that did not swap is not the live code
        rig.watcher.live_code(self.db, 'e' * 40)
        self.assertEqual(self.datum(), '')
        first, second = f"{'a' * 64}@{'1' * 40}", f"{'b' * 64}@{'2' * 40}"
        self.swap('a' * 64, '1' * 40)
        # the base's newest head is another one (a landing that did not swap, deployed by a build since): the older swap is
        # never written, by this look or by a service that starts later: a task of that build would boot the older bundle
        rig.watcher.live_code(self.db, 'e' * 40)
        rig.watcher.live_code(self.db, None)  # no push seen: nothing either
        self.assertEqual((self.datum(), self.db.rows("select count(*) from work.config_value where key = 'deploy.live_code'")),
                         ('', [('0',)]))
        rig.watcher.live_code(self.db, '1' * 40)  # the look of that landing, while its head is the newest
        self.assertEqual(self.datum(), first)
        row = "select version, actor from work.config_value where key = 'deploy.live_code'"
        self.assertEqual(self.db.rows(row), [('1', 'autodeploy')])
        rig.watcher.live_code(self.db, '1' * 40)  # every look: the same swap writes nothing again
        self.assertEqual(self.db.rows(row), [('1', 'autodeploy')])
        self.swap('b' * 64, '2' * 40)
        rig.watcher.live_code(self.db, '2' * 40)
        self.assertEqual((self.datum(), self.db.rows(row)), (second, [('2', 'autodeploy')]))
        # emptied by hand after the swap (PUT /v1/config/deploy.live_code ''): the look leaves it; the next swap writes again
        self.db.rows("update work.config_value set value = '\"\"'::jsonb, version = version + 1, actor = 'hand', "
                     "updated_at = clock_timestamp() where key = 'deploy.live_code'")
        rig.watcher.live_code(self.db, '2' * 40)
        self.assertEqual(self.datum(), '')
        self.assertEqual(config_data.validate('deploy.live_code', ''), '')
        self.swap('d' * 64, '3' * 40)
        rig.watcher.live_code(self.db, '3' * 40)
        self.assertEqual(self.datum(), f"{'d' * 64}@{'3' * 40}")
        # what a booting task reads (code_bundle.live): the value, and whether a reload onto that bundle failed
        read = lambda: self.db.rows(code_bundle.LIVE, {'tenant': config_data.TENANT})  # noqa: E731
        self.assertEqual(read(), [(f"{'d' * 64}@{'3' * 40}", 'f')])
        for ident, digest in (('r1', 'e' * 64), ('r2', 'd' * 64)):  # another bundle's failure is not this one's
            self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                         "(%(id)s, null, 'platform.deploy.image_reload', clock_timestamp(), 'tower-runner', 'deploy/image/runner', "
                         "%(payload)s::jsonb)", {'id': ident, 'payload': json.dumps({'role': 'runner', 'digest': digest, 'state': 'failed'})})
            self.assertEqual(read(), [(f"{'d' * 64}@{'3' * 40}", 't' if digest == 'd' * 64 else 'f')])
        self.assertEqual(self.db.rows(code_bundle.LIVE, {'tenant': 'nobody'}), [])

    def test_a_migration_that_fails_is_left_to_the_new_service_and_changes_nothing(self):
        data, key, sha = bundle(**{'migrations/9999_broken.sql': 'create table work.rollout_c (id int); select 1 / 0;'})
        rig = Rig()
        rig.watcher.bundles = Store({key: data})
        asked(rig, key, sha)
        rig.watcher.migrate(self.db)  # logged, not raised
        self.assertEqual(self.health()['migration'], self.newest)  # no evidence: deploy.sh keeps the old order
        self.assertEqual(self.db.rows("select to_regclass('work.rollout_c') is null"), [('t',)])  # one transaction


if __name__ == '__main__':
    unittest.main()
