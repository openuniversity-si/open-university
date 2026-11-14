"""IMAGE-PREWARM-B2 (docs/operations/aws.md 22.9): on each push of a unit branch the live service makes the head's bundle job
(`scripts/gate-check artifact code`) and, for a code-only head, one standby Fargate task per role with that bundle; the
lifecycle follows the events (a newer push, a deleted branch, a closed PR, the cap), each transition is
platform.deploy.standby, and the status shows them.

Hermetic: a fake database that answers only the statements the prewarm sends (by their text) and a fake ECS client; the
OnPostgres class runs the same look on a throwaway database (TEST_DATABASE_URL, skipped without).
"""
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import forge, live_image, port, prewarm  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
BASE = 'b' * 40
H1, H2, H3 = '1' * 40, '2' * 40, '3' * 40
S1, S2 = 'a' * 64, 'c' * 64
NETWORK = {'subnets': ['subnet-1'], 'securityGroups': ['sg-1'], 'assignPublicIp': 'ENABLED'}
REPOSITORY = {'name': 'open-university', 'owner': {'slug': 'openuniversity-si'}}


def push(branch, after, deleted=False):
    return ('forge.repository.pushed', {'repository': REPOSITORY, 'refUpdates': [
        {'ref': f'refs/heads/{branch}', 'before': '0' * 40, 'after': '0' * 40 if deleted else after, 'deleted': deleted}]})


def closed(branch):
    return ('forge.pull_request.closed', {'pullRequest': {'number': 7, 'head': {'ref': branch, 'sha': H1},
                                                          'repository': REPOSITORY}})


def merged(branch):
    return ('forge.pull_request.merged', {'pullRequest': {'number': 7, 'head': {'ref': branch, 'sha': H1},
                                                          'repository': REPOSITORY}})


def said(sha=None, why='3 file(s) of infra/service/tower_infra/ only'):
    """A bundle job's result as the runner keeps it: the log's tail ends with gate_code's JSON line."""
    line = ({'code_only': True, 'why': why, 'published': True, 'key': f'artifacts/lambda/tower-code/{sha}.zip',
             'sha256': sha, 'bytes': 10, 'uploaded': True} if sha else {'code_only': False, 'why': why})
    return json.dumps({'exit': 0, 'log_uri': 's3://x', 'tail': 'setup: ok\n' + json.dumps(line, sort_keys=True) + '\n'})


class Config:
    def __init__(self, cap=1):
        self.values = {'deploy.prewarm_max_tasks': cap, 'deploy.base_branch': 'mod/roadmap-integration',
                       'deploy.intask_standbys': 0}  # IN-TASK-STANDBY: off, as the registry's default

    def get(self, name):
        return self.values[name]


class Db:
    """The statements of the prewarm, by their text; anything else is a failure of the test."""

    def __init__(self):
        self.events, self.jobs, self.made, self.recorded, self.pointer, self.known = [], {}, [], [], {}, []
        self.train = set()  # PREWARM-TRAIN-SLOT
        self.landed = set()  # LANDING-KEEPS-STANDBY: the PR heads a platform.deploy.landed named
        self.swapped = set()  # IMAGE-PREWARM-C: the bundles a platform.deploy.image_swap promoted
        self.base = [(json.dumps([{'ref': 'refs/heads/mod/roadmap-integration', 'after': BASE}]),)]
        # PREWARM-ONE-LOOK: the id of the newest thing a prewarm said; whether another service holds the look's lock; and
        # `log`: the alive tasks are read from what was recorded (two services on one log), not from `known` alone
        self.said, self.busy, self.log, self.turns = '', False, False, 0

    def scope(self):
        db = self

        class Scope:
            def __enter__(self):
                return db

            def __exit__(self, *_):
                return False
        return Scope()

    def add(self, at, kind, body):
        self.events.append((f'{kind}:{len(self.events)}', at, kind, json.dumps(body)))

    def states(self, state=None):
        return [(each['role'], each['digest'], each['state']) for each in self.recorded if state in (None, each['state'])]

    def rows(self, sql, params=None):
        if sql == prewarm.TURN:
            assert params == {'key': prewarm.LOCK_KEY}
            self.turns += 0 if self.busy else 1
            return [(not self.busy, self.said)]
        if sql == prewarm.TURN_END:
            self.turns -= 1
            return [(True, self.said)]
        if sql == prewarm.EVENTS:
            return [each for each in self.events if each[1] > params['since']]
        if sql == prewarm.BASE:
            assert json.loads(params['ref']) == [{'ref': 'refs/heads/mod/roadmap-integration'}]
            return self.base
        if sql == prewarm.TENANT_ID:
            return [('tenant-1',)]
        if sql.startswith('with created as (insert into work.job'):  # port.create_job
            assert params['tenant'] == 'tenant-1'
            if any(each['idempotency_key'] == params['idempotency_key'] for each in self.made):
                return []
            self.made.append(dict(params))
            self.jobs[f'job-{len(self.made)}'] = ('queued', None)
            return [(f'job-{len(self.made)}', True)]
        if sql.startswith('select id::text from work.job where tenant_id = %(tenant)s::uuid and idempotency_key'):
            return [(f'job-{n + 1}',) for n, each in enumerate(self.made) if each['idempotency_key'] == params['key']]  # port.create_job: the same key again
        if sql == prewarm.JOBS:
            return [(job, *self.jobs[job]) for job in params['ids'].split(',')]
        if sql == prewarm.RECORD:
            payload = json.loads(params['payload'])
            assert params['id'].startswith(f"platform.deploy.standby:{payload['role']}:{payload['digest']}:")
            self.recorded.append(payload)
            self.said = params['id']
            return []
        if sql == prewarm.LANDED:  # LANDING-KEEPS-STANDBY: the heads whose landing the test said
            return [(1,)] if params['head'] in self.landed else []
        if sql == prewarm.TRAIN_HAS:  # PREWARM-TRAIN-SLOT: the heads the test put in the merge train
            return [(1,)] if set(params['heads']) & self.train else []
        if sql == prewarm.PROMOTED:
            return [(1,)] if params['sha'] in self.swapped else []
        if sql == prewarm.KNOWN:
            newest = {each['task']: each for each in self.recorded if each.get('task')} if self.log else {}
            return [(json.dumps(each),) for each in self.known + list(newest.values())]
        if sql == live_image.READ:
            value = self.pointer.get(params['key'])
            return [] if value is None else [(json.dumps(value), 1)]
        raise AssertionError(sql)


class Ecs:
    def __init__(self):
        self.ran, self.stopped, self.status, self.refuse = [], [], {}, set()

    def run_task(self, **call):
        if call['taskDefinition'] in self.refuse:
            return {'tasks': [], 'failures': [{'reason': 'RESOURCE:FARGATE'}]}
        self.ran.append(call)
        arn = f"arn:aws-partition:ecs:r:1:task/tower/{len(self.ran)}"
        self.status[arn] = {'taskArn': arn, 'lastStatus': 'PROVISIONING', 'healthStatus': 'UNKNOWN'}
        return {'tasks': [{'taskArn': arn}]}

    def stop_task(self, cluster, task, reason):
        self.stopped.append((task, reason))
        self.status[task] = {'taskArn': task, 'lastStatus': 'STOPPED', 'stoppedReason': reason}

    def describe_tasks(self, cluster, tasks):
        assert cluster == 'tower'
        return {'tasks': [self.status[each] for each in tasks if each in self.status], 'failures': []}

    def healthy(self):
        for each in self.status.values():
            if each['lastStatus'] != 'STOPPED':
                each.update(lastStatus='RUNNING', healthStatus='HEALTHY')

    def digests(self):
        return [next(tag['value'] for tag in call['tags'] if tag['key'] == 'digest') for call in self.ran]


class World(unittest.TestCase):
    def setUp(self):
        self.db, self.ecs, self.now = Db(), Ecs(), [1_000_000.0]
        self.watcher = self.make(Config())

    def make(self, config):
        return prewarm.Prewarm(self.db.scope, self.ecs, 'tower', NETWORK, config=config, clock=lambda: self.now[0])

    def at(self, kind_body, later=1):
        self.now[0] += later
        self.db.add(self.now[0], *kind_body)
        return self.watcher.step()

    def finish(self, head, result, state='succeeded'):
        job = self.watcher.pending[head]
        self.db.jobs[job] = (state, result)
        self.now[0] += 1
        return self.watcher.step()

    def live(self, *branches_heads_shas):
        for branch, head, sha in branches_heads_shas:
            self.at(push(branch, head))
            if head in self.watcher.pending:
                self.finish(head, said(sha))


class ThePortIsWarmedByThePush(World):
    """PORT-WARM-ON-PUSH: a cold environment of the port's Lambda costs its first caller about 1.9 s (12/11, three
    environments: the driver's import 0.33 to 0.36 s, the login to the database 0.99 to 1.04 s, the first handler 0.35
    s): the login alone is over the 1 s goal, so trimming the package cannot close it, and warming by the clock is not
    the engine's way. The push of a units/ branch is the event that says a delivery is coming: the prewarm, which
    already makes the head's bundle job on it, asks the port's live alias for its health without waiting for the
    answer; an idle warm environment answers, and when there is none one starts now, during the authoring."""

    def test_a_pushed_head_warms_the_port_once_and_a_warm_up_that_fails_changes_nothing(self):
        warmed = []
        self.watcher.warm = lambda: warmed.append(self.now[0])
        self.at(push('units/x', 'a' * 40))
        self.assertEqual((len(warmed), list(self.watcher.pending)), (1, ['a' * 40]))
        self.watcher.step()  # the same head again: nothing new was pushed
        self.assertEqual(len(warmed), 1)
        self.at(push('units/x', 'b' * 40))  # a new head: a delivery of it is coming
        self.assertEqual(len(warmed), 2)

        def broken():
            raise RuntimeError('the Lambda API is away')
        self.watcher.warm = broken
        with self.assertLogs('tower_infra.prewarm', 'WARNING'):
            self.at(push('units/y', 'c' * 40))
        self.assertIn('c' * 40, self.watcher.pending)  # the bundle job was made all the same

    def test_the_live_service_s_prewarm_asks_the_live_alias_for_its_health_as_an_event(self):
        calls = []

        class Lambda:
            def invoke(self, **asked):
                calls.append(asked)
                return {'StatusCode': 202}
        prewarm.port_warm(Lambda())()
        (asked,) = calls
        self.assertEqual((asked['FunctionName'], asked['Qualifier'], asked['InvocationType']), ('tower-port-api', 'live', 'Event'))
        self.assertEqual(json.loads(asked['Payload'])['rawPath'], '/v1/health')
        self.assertEqual(prewarm.Prewarm(self.db.scope, self.ecs, 'tower', NETWORK).warm, None)  # nothing unless given


class TwoLiveServices(World):
    """PREWARM-ONE-LOOK: live 11/11, twice within ten minutes: two services were live at once (the handover of a swap; an
    ECS rollout that keeps the old task until the new one is healthy), each with its own memory, and each started a pair
    for the same bundle: four Spot tasks, 65 of the database's 79 connections, and a pair in nobody's memory."""

    def setUp(self):
        super().setUp()
        self.db.log = True
        self.other = self.make(Config())

    def both(self, kind_body):
        self.now[0] += 1
        self.db.add(self.now[0], *kind_body)
        return self.watcher.step(), self.other.step()

    def test_the_same_push_seen_by_both_starts_one_pair(self):
        self.both(push('units/a', H1))
        [job] = set(self.watcher.pending.values()) | set(self.other.pending.values())  # one job: its key is the head's
        self.db.jobs[job] = ('succeeded', said(S1))
        self.now[0] += 1
        self.watcher.step()
        self.other.step()
        self.assertEqual(self.ecs.digests(), [S1, S1])  # one task per role, not two
        self.assertEqual(self.db.states('started'), [('runner', S1, 'started'), ('service', S1, 'started')])
        self.assertEqual(self.other.holds, {'units/a': S1})  # the second read the first's pair from the log
        self.assertEqual(sorted(self.other.standbys[S1]['tasks']), ['runner', 'service'])
        self.assertEqual(self.db.turns, 0)  # every look gave the lock back

    def test_a_look_while_the_other_service_looks_does_nothing_and_reads_the_log_next_time(self):
        self.live(('units/a', H1, S1))
        self.db.busy = True
        self.now[0] += 1
        self.db.add(self.now[0], *push('units/a', H2))
        self.other.step()
        self.assertEqual((self.other.pending, self.other.restored, len(self.ecs.ran)), ({}, False, 2))
        self.db.busy = False
        self.other.step()
        self.assertEqual((self.other.restored, sorted(self.other.standbys[S1]['tasks'])), (True, ['runner', 'service']))

    def test_a_second_standby_of_a_role_in_the_log_is_stopped_and_the_healthy_one_stays(self):
        self.db.known = [{'role': role, 'digest': S1, 'task': f'arn:{role}:{n}', 'branch': 'units/a', 'state': state}
                         for role in ('runner', 'service') for n, state in ((1, 'started'), (2, 'healthy'))]
        self.ecs.status = {each['task']: {'taskArn': each['task'], 'lastStatus': 'RUNNING', 'healthStatus': 'HEALTHY'}
                           for each in self.db.known}
        self.watcher.step()
        self.assertEqual(sorted(task for task, _ in self.ecs.stopped), ['arn:runner:1', 'arn:service:1'])
        self.assertTrue(all(reason.startswith('PREWARM-ONE-LOOK: one standby per role') for _, reason in self.ecs.stopped))
        self.assertEqual({role: task['task'] for role, task in self.watcher.standbys[S1]['tasks'].items()},
                         {'runner': 'arn:runner:2', 'service': 'arn:service:2'})
        self.assertEqual(self.db.states('stopped'), [('runner', S1, 'stopped'), ('service', S1, 'stopped')])  # dismissed first
        self.assertEqual(self.watcher.extras, [])

    def test_a_second_standby_of_the_pointers_bundle_stays_until_the_pointer_lets_go(self):
        self.db.known = [{'role': 'service', 'digest': S1, 'task': f'arn:service:{n}', 'branch': 'units/a', 'state': 'healthy'}
                         for n in (1, 2)]
        self.ecs.status = {each['task']: {'taskArn': each['task'], 'lastStatus': 'RUNNING', 'healthStatus': 'HEALTHY'}
                           for each in self.db.known}
        self.db.pointer = {live_image.KEYS['service']: S1, live_image.KEYS['runner']: S1}
        self.watcher.step()
        self.assertEqual((self.ecs.stopped, len(self.watcher.extras)), ([], 1))  # stopping it would hand the pointer back
        self.db.pointer = {}
        self.now[0] += 1
        self.watcher.step()
        self.assertEqual(len([task for task, reason in self.ecs.stopped if reason.startswith('PREWARM-ONE-LOOK')]), 1)

    def test_a_stop_that_fails_is_tried_on_a_few_looks_and_then_left(self):
        self.db.known = [{'role': 'service', 'digest': S1, 'task': f'arn:service:{n}', 'branch': 'units/a', 'state': 'healthy'}
                         for n in (1, 2)]
        self.ecs.status = {'arn:service:1': {'taskArn': 'arn:service:1', 'lastStatus': 'RUNNING', 'healthStatus': 'HEALTHY'}}
        self.ecs.stop_task = mock.Mock(side_effect=RuntimeError('the task is not found'))
        with self.assertLogs('tower_infra.prewarm', 'ERROR'):
            for _ in range(prewarm.EXTRA_TRIES + 2):
                self.now[0] += 1
                self.watcher.step()
        self.assertEqual((self.ecs.stop_task.call_count, self.watcher.extras), (prewarm.EXTRA_TRIES, []))


class Push(World):
    def test_a_unit_branchs_push_makes_one_bundle_job_of_its_head_on_the_gates_queue(self):
        self.at(push('units/a', H1))
        self.at(push('mod/roadmap-integration', H2))  # the base and other branches are not prewarmed
        self.at(push('units/a', H1))  # the same head again: nothing new
        self.assertEqual(len(self.db.made), 1)
        made = self.db.made[0]
        spec = forge.decode(made['input_uri'])
        self.assertEqual(spec, {'repo': 'openuniversity-si/open-university', 'ref': 'refs/heads/units/a', 'commit': H1,
                                'base': BASE, 'timeout_s': prewarm.TIMEOUT_S,
                                'command': ['scripts/gate-check', 'artifact', 'code', '--base', BASE]})
        self.assertEqual((made['queue'], made['selector'], made['memoize'], made['idempotency_key']),
                         ('checks', '{"adapter": "container"}', 'false', f'prewarm:code:{H1}'))
        self.assertTrue(made['input_digest'].startswith('sha256:'))
        self.assertEqual(self.ecs.ran, [])  # nothing runs before the bundle exists

    def test_a_premerges_push_is_its_unit_branchs_head_and_its_bundle_is_made_from_the_premerge_ref(self):
        # PREWARM-PREMERGE (criterion 3): a PR behind the base lands the premerge's commit, whose code no standby had (#699
        # and #701 waited 12.1 s at the train's front, 13/11): its push is the branch's newest head
        self.at(push('units/a', H1))
        self.at(push('premerge/units/a/' + H2[:12], H3))
        self.assertEqual(self.watcher.heads['units/a'], H3)
        spec = forge.decode(self.db.made[-1]['input_uri'])
        self.assertEqual((spec['ref'], spec['commit']), (f'refs/heads/premerge/units/a/{H2[:12]}', H3))
        self.at(push('units/a', H3))  # the delivery pushes that very commit to the branch: nothing new
        self.assertEqual(len(self.db.made), 2)
        self.at(push('premerge/nope/' + H2[:12], H1))  # not a unit branch's premerge: not followed
        self.assertEqual(len(self.db.made), 2)

    def test_a_push_of_another_repository_is_not_followed(self):
        kind, body = push('units/a', H1)
        self.at((kind, {**body, 'repository': {'name': 'other', 'owner': {'slug': 'someone'}}}))
        self.assertEqual(self.db.made, [])

    def test_a_code_only_head_gets_one_standby_per_role_with_its_bundle(self):
        self.at(push('units/a', H1))
        wait = self.finish(H1, said(S1))
        self.assertEqual(wait, prewarm.POLL_S)  # a task is starting: the one poll
        self.assertEqual([call['taskDefinition'] for call in self.ecs.ran], ['tower-runner', 'tower-service-standby'])
        for call, container in zip(self.ecs.ran, ('runner', 'service')):
            self.assertEqual((call['cluster'], call['count'], call['networkConfiguration']),
                             ('tower', 1, {'awsvpcConfiguration': NETWORK}))
            self.assertEqual(call['capacityProviderStrategy'], [{'capacityProvider': 'FARGATE_SPOT', 'weight': 1}])
            self.assertNotIn('launchType', call)  # a launch type would override the capacity provider
            self.assertEqual(call['overrides'], {'containerOverrides': [{'name': container, 'environment': [
                {'name': 'TOWER_CODE_KEY', 'value': f'artifacts/lambda/tower-code/{S1}.zip'},
                {'name': 'TOWER_CODE_SHA256', 'value': S1}, {'name': 'TOWER_IMAGE_DIGEST', 'value': S1},
                {'name': 'TOWER_STANDBY', 'value': '1'}]}]})
            self.assertEqual({tag['key']: tag['value'] for tag in call['tags']},
                             {'project': 'tower', 'role': container, 'digest': S1, 'branch': 'units/a'})
        self.assertEqual(self.db.states(), [('runner', S1, 'started'), ('service', S1, 'started')])
        self.assertEqual({each['branch'] for each in self.db.recorded}, {'units/a'})
        self.ecs.healthy()
        self.now[0] += prewarm.POLL_S
        self.assertEqual(self.watcher.step(), prewarm.SAFETY_S)  # none starting: only events wake the look
        self.assertEqual(self.db.states('healthy'), [('runner', S1, 'healthy'), ('service', S1, 'healthy')])

    def test_a_head_that_is_not_code_only_or_whose_job_failed_starts_nothing(self):
        self.at(push('units/a', H1))
        with self.assertLogs('tower_infra.prewarm', 'INFO') as logs:
            self.finish(H1, said(why='the image itself changes: infra/service/Dockerfile'))
        self.assertIn('slow path: not code-only: the image itself changes: infra/service/Dockerfile', '\n'.join(logs.output))
        self.at(push('units/b', H2))
        self.finish(H2, None, state='failed')
        self.at(push('units/c', H3))
        self.finish(H3, json.dumps({'exit': 0, 'tail': 'no json here'}))
        self.assertEqual((self.ecs.ran, self.db.recorded), ([], []))
        self.assertEqual(prewarm.answer('succeeded', said(S1)), ((f'artifacts/lambda/tower-code/{S1}.zip', S1), None))
        unpublished = json.dumps({'tail': json.dumps({'code_only': True, 'published': False, 'key': 'k', 'sha256': S1})})
        self.assertEqual(prewarm.answer('succeeded', unpublished), (None, 'its bundle was not published'))

    def test_no_push_of_the_base_seen_leaves_the_head_on_the_slow_path(self):
        self.db.base = []
        with self.assertLogs('tower_infra.prewarm', 'WARNING'):
            self.at(push('units/a', H1))
        self.assertEqual((self.db.made, self.ecs.ran), ([], []))


class Lifecycle(World):
    def test_a_newer_push_stops_the_older_standby_and_starts_its_own(self):
        self.live(('units/a', H1, S1))
        first = [call for call in self.ecs.status]
        self.live(('units/a', H2, S2))
        self.assertEqual([task for task, _ in self.ecs.stopped], first)
        self.assertTrue(all(reason.startswith('IMAGE-PREWARM-B2: units/a: its head moved to 222222222222')
                            for _, reason in self.ecs.stopped))
        self.assertEqual(self.ecs.digests(), [S1, S1, S2, S2])
        self.assertEqual(self.db.states('stopped'), [('runner', S1, 'stopped'), ('service', S1, 'stopped')])

    def test_a_newer_head_with_the_same_bundle_keeps_its_tasks(self):
        self.live(('units/a', H1, S1), ('units/a', H2, S1))  # e.g. a docs commit on top: the same tower_infra
        self.assertEqual((len(self.ecs.ran), self.ecs.stopped), (2, []))

    def test_two_heads_with_the_same_bundle_share_one_task_per_role_until_both_let_go(self):
        self.watcher = self.make(Config(cap=2))
        self.live(('units/a', H1, S1), ('units/b', H2, S1))
        self.assertEqual(len(self.ecs.ran), 2)
        self.live(('units/a', H3, S2))
        self.assertEqual((self.ecs.digests(), self.ecs.stopped), ([S1, S1, S2, S2], []))  # units/b still holds S1
        self.at(push('units/b', None, deleted=True))
        self.assertEqual(len(self.ecs.stopped), 2)
        self.assertTrue(all('units/b: the branch was deleted' in reason for _, reason in self.ecs.stopped))

    def test_the_same_head_on_two_branches_is_one_job_and_one_standby(self):
        self.watcher = self.make(Config(cap=2))
        self.at(push('units/a', H1))
        self.at(push('units/b', H1))
        self.finish(H1, said(S1))
        self.assertEqual((len(self.db.made), len(self.ecs.ran)), (1, 2))
        self.assertEqual(self.watcher.standbys[S1]['branches'], {'units/a', 'units/b'})

    def test_a_deleted_branch_or_a_closed_pr_stops_its_standby(self):
        self.live(('units/a', H1, S1))
        self.at(push('units/a', None, deleted=True))
        self.assertEqual(self.db.states('stopped'), [('runner', S1, 'stopped'), ('service', S1, 'stopped')])
        self.live(('units/b', H2, S2))
        self.at(closed('units/b'))
        self.assertEqual(len(self.ecs.stopped), 4)
        self.assertTrue(all('units/b: its PR was closed' in reason for _, reason in self.ecs.stopped[2:]))
        self.assertEqual(self.watcher.standbys, {})

    def test_a_head_moved_to_the_slow_path_lets_go_of_its_standby(self):
        self.live(('units/a', H1, S1))
        self.at(push('units/a', H2))
        self.assertEqual(self.ecs.stopped, [])  # until the new head's job says, the old standby stays
        self.finish(H2, said(why='also slow:stack-data'))
        self.assertEqual(len(self.ecs.stopped), 2)

    def test_over_the_cap_the_newest_push_wins_and_the_older_branch_falls_back_to_the_slow_path(self):
        self.live(('units/a', H1, S1))
        with self.assertLogs('tower_infra.prewarm', 'WARNING') as logs:
            self.live(('units/b', H2, S2))
        self.assertIn('over deploy.prewarm_max_tasks=1: the newest push (units/b) wins; units/a of aaaaaaaaaaaa fall back '
                      'to the slow path', '\n'.join(logs.output))
        self.assertEqual(self.ecs.digests(), [S1, S1, S2, S2])
        self.assertEqual(len(self.ecs.stopped), 2)
        self.assertEqual((self.watcher.holds, list(self.watcher.standbys)), ({'units/b': S2}, [S2]))

    def test_a_cap_of_zero_starts_nothing(self):
        self.watcher = self.make(Config(cap=0))
        with self.assertLogs('tower_infra.prewarm', 'INFO') as logs:
            self.live(('units/a', H1, S1))
        self.assertIn('deploy.prewarm_max_tasks is 0', '\n'.join(logs.output))
        self.assertEqual(self.ecs.ran, [])

    def test_the_bundle_the_pointer_names_is_never_stopped_nor_counted(self):
        self.live(('units/a', H1, S1))
        self.db.pointer = {'deploy.live_image_runner': S1, 'deploy.live_image_service': S1}  # phase C swapped to it
        self.live(('units/b', H2, S2))  # not over the cap: S1 is the live one
        self.at(push('units/a', None, deleted=True))  # its branch is deleted after the merge
        self.assertEqual((self.ecs.stopped, self.ecs.digests()), ([], [S1, S1, S2, S2]))

    def test_a_failed_stop_is_tried_again_on_the_next_look(self):
        self.live(('units/a', H1, S1))
        throttled, stop = [True], self.ecs.stop_task

        def flaky(**call):
            if throttled[0]:
                raise RuntimeError('throttled')
            return stop(**call)
        self.ecs.stop_task = flaky
        with self.assertLogs('tower_infra.prewarm', 'ERROR'):
            self.at(push('units/a', None, deleted=True))
        self.assertIn(S1, self.watcher.standbys)
        throttled[0] = False
        self.watcher.step()
        self.assertEqual((len(self.ecs.stopped), self.watcher.standbys), (2, {}))


class Health(World):
    def test_a_task_that_stops_by_itself_fails_and_its_role_falls_back(self):
        self.live(('units/a', H1, S1))
        runner_task = self.watcher.standbys[S1]['tasks']['runner']['task']
        self.ecs.status[runner_task].update(lastStatus='STOPPED', stoppedReason='Essential container exited (3)')
        self.now[0] += prewarm.POLL_S
        self.watcher.step()
        self.assertEqual(self.db.recorded[-1]['state'], 'failed')
        self.assertEqual(self.db.recorded[-1]['why'], 'Essential container exited (3)')
        self.assertEqual(list(self.watcher.standbys[S1]['tasks']), ['service'])

    def test_a_healthy_standby_ecs_is_stopping_is_replaced_in_the_same_look(self):
        # STANDBY-GRACE: Spot's warning sets desiredStatus STOPPED two minutes before the task ends; the replacement started
        # 51 s after the task was gone (RETRY_S) and took ~95 s to be healthy, with no standby for the landings in between
        self.live(('units/a', H1, S1))
        self.ecs.healthy()
        self.now[0] += prewarm.POLL_S
        self.watcher.step()
        service_task = self.watcher.standbys[S1]['tasks']['service']['task']
        self.assertEqual(self.watcher.standbys[S1]['tasks']['service']['state'], 'healthy')
        self.assertEqual(self.watcher.standbys[S1]['tries'], {'runner': 0, 'service': 0})  # RETRY_MAX counts refusals in a row
        self.ecs.status[service_task].update(desiredStatus='STOPPED', stopCode='SpotInterruption',
                                             stoppedReason='Your Spot Task was interrupted.')  # still RUNNING
        before = len(self.ecs.ran)
        self.now[0] += prewarm.POLL_S
        self.watcher.step()
        failed = [each for each in self.db.recorded if each['state'] == 'failed']
        self.assertEqual([(each['role'], each['why']) for each in failed], [('service', 'Your Spot Task was interrupted.')])
        self.assertEqual(len(self.ecs.ran), before + 1)  # replaced at once
        replacement = self.watcher.standbys[S1]['tasks']['service']
        self.assertNotEqual(replacement['task'], service_task)
        self.assertEqual((replacement['state'], self.ecs.stopped), ('started', []))  # the warned one is left to ECS
        self.assertEqual(list(self.watcher.standbys[S1]['tasks']), ['runner', 'service'])

    def test_a_stop_is_recorded_before_the_task_is_stopped(self):
        # STANDBY-GRACE: the standby reads the event at its SIGTERM: a dismissed one leaves at once, a warned one stays
        self.live(('units/a', H1, S1))
        seen, stop = [], self.ecs.stop_task

        def stopping(**call):
            seen.append([each['state'] for each in self.db.recorded if each['task'] == call['task']][-1])
            return stop(**call)
        self.ecs.stop_task = stopping
        self.at(push('units/a', None, deleted=True))
        self.assertEqual(seen, ['stopped', 'stopped'])

    def test_a_task_not_healthy_in_the_start_limit_is_stopped_as_failed(self):
        self.live(('units/a', H1, S1))
        self.now[0] += prewarm.START_LIMIT_S + 1
        self.watcher.step()
        self.assertEqual(len(self.ecs.stopped), 2)
        self.assertEqual(self.db.states('failed'), [('runner', S1, 'failed'), ('service', S1, 'failed')])
        self.assertEqual((self.watcher.standbys, self.watcher.holds), ({}, {}))

    def test_the_health_is_read_at_most_every_poll_and_only_while_a_task_is_alive(self):
        describes = []
        self.ecs.describe_tasks = lambda **call: describes.append(call) or {
            'tasks': [{'taskArn': each, 'lastStatus': 'RUNNING', 'healthStatus': 'UNKNOWN'} for each in call['tasks']]}
        self.watcher.step()
        self.assertEqual(describes, [])  # no task: no call
        self.live(('units/a', H1, S1))
        self.watcher.step()
        self.watcher.step()
        self.assertLessEqual(len(describes), 1)
        self.assertLess(prewarm.POLL_S * 2, 120)  # never two minutes blind while a task starts

    def test_a_refused_run_task_is_recorded_failed_and_the_other_role_still_stands_by(self):
        self.ecs.refuse.add('tower-runner')
        with self.assertLogs('tower_infra.prewarm', 'ERROR'):
            self.live(('units/a', H1, S1))
        self.assertEqual(self.db.states(), [('runner', S1, 'failed'), ('service', S1, 'started')])
        self.assertEqual(self.ecs.digests(), [S1])

    def test_a_refused_role_is_tried_again_later_and_the_same_refusal_is_one_event(self):
        # PREWARM-RETRY (live 10/11: 'Capacity is unavailable at this time' left the pair half until a new push)
        self.ecs.refuse.add('tower-runner')
        with self.assertLogs('tower_infra.prewarm', 'ERROR'):
            self.live(('units/a', H1, S1))
            self.assertEqual(self.watcher.step(), prewarm.POLL_S)  # the service standby is starting
            self.ecs.healthy()
            self.now[0] += prewarm.POLL_S
            self.assertEqual(self.watcher.step(), prewarm.RETRY_S)  # nothing starting, a role missing: looked at again
            self.now[0] += prewarm.RETRY_S
            self.watcher.step()  # refused again: no second failed event
        self.assertEqual([state for state in self.db.states() if state[0] == 'runner'], [('runner', S1, 'failed')])
        self.ecs.refuse.clear()
        self.now[0] += prewarm.RETRY_S
        self.watcher.step()
        self.assertEqual([state for state in self.db.states() if state[0] == 'runner'][-1], ('runner', S1, 'started'))
        self.assertEqual(len([call for call in self.ecs.ran if call['taskDefinition'] == 'tower-runner']), 1)

    def test_a_role_is_tried_a_bounded_number_of_times_and_never_for_a_promoted_bundle(self):
        self.ecs.refuse.add('tower-runner')
        asked = []
        run_task = self.ecs.run_task
        self.ecs.run_task = lambda **call: (asked.append(call['taskDefinition']), run_task(**call))[1]
        with self.assertLogs('tower_infra.prewarm', 'ERROR'):
            self.live(('units/a', H1, S1))
            for _ in range(prewarm.RETRY_MAX + 5):
                self.now[0] += prewarm.RETRY_S
                self.ecs.healthy()
                self.watcher.step()
        self.assertEqual(asked.count('tower-runner'), prewarm.RETRY_MAX)
        self.assertEqual(self.watcher.step(), prewarm.SAFETY_S)  # given up: no more looks for it
        self.watcher.promoted.add(S1)
        self.assertEqual(self.watcher.missing(), [])

    def test_the_slot_stays_with_the_delivery_in_the_train_and_the_pusher_gets_it_when_it_frees(self):
        # PREWARM-TRAIN-SLOT (live 11/11: a later push of another branch stopped the pair of a PR 4 min before its landing)
        self.live(('units/a', H1, S1))
        self.db.train.add(H1)  # units/a's delivery joined the merge train
        self.live(('units/b', H2, S2))  # a later push of another branch: the cap is 1
        self.assertEqual(self.ecs.stopped, [])
        self.assertEqual(set(self.ecs.digests()), {S1})
        self.assertEqual(self.watcher.step(), prewarm.POLL_S)  # (S1's tasks are starting)
        self.ecs.healthy()
        self.now[0] += prewarm.POLL_S
        self.assertEqual(self.watcher.step(), prewarm.RETRY_S)  # units/b waits: looked at again by itself
        self.db.train.clear()  # units/a left the train (landed or dropped): the slot is the newest push's again
        self.now[0] += prewarm.RETRY_S
        self.watcher.step()
        self.assertEqual(set(self.ecs.digests()), {S1, S2})
        self.assertEqual(len(self.ecs.stopped), 2)  # S1's pair, stopped for the newest push only now

    def test_a_merged_prs_standbys_stay_until_its_landing_is_said_and_the_branch_that_waits_gets_the_slot_then(self):
        # LANDING-KEEPS-STANDBY: live 11/11 23:45 UTC: #546 merged with #547 waiting for the slot; the merge event came 1.5 s
        # before the landing's statement, the standbys of #546 were stopped for #547's, and the landing swapped onto none
        self.live(('units/a', H1, S1))
        self.db.train.add(H1)  # units/a's delivery is in the train
        self.live(('units/b', H2, S2))  # another branch pushes: it waits for the slot
        self.assertEqual((self.watcher.holds, self.ecs.stopped), ({'units/a': S1}, []))
        self.db.train.clear()  # the forge merged units/a: its train entry ended, and the merge event is here
        self.assertEqual(self.at(merged('units/a')), prewarm.LANDING_S)
        self.assertEqual((self.watcher.holds, self.ecs.stopped), ({'units/a': S1}, []))  # before: stopped here, for units/b
        self.now[0] += 2
        self.watcher.step()  # any other look meanwhile: still kept
        self.assertEqual((self.watcher.holds, self.ecs.stopped), ({'units/a': S1}, []))
        self.db.landed.add(H1)  # the delivery said the landing (its statement swapped onto the standbys)
        self.db.swapped.add(S1)
        self.db.pointer = {key: S1 for key in live_image.KEYS.values()}
        self.now[0] += 1
        self.watcher.step()  # the look the landing wakes: units/a is done, and the slot is units/b's
        self.assertNotIn('units/a', self.watcher.holds)
        self.assertEqual((self.watcher.landing, self.watcher.holds.get('units/b')), ({}, S2))

    def test_a_merge_whose_landing_is_never_said_frees_the_slot_at_its_bound(self):
        self.live(('units/a', H1, S1))
        self.at(merged('units/a'))  # the delivery died between the merge and its word
        self.assertEqual(self.ecs.stopped, [])
        self.now[0] += prewarm.LANDING_S
        self.watcher.step()
        self.assertEqual((self.watcher.landing, self.watcher.holds, len(self.ecs.stopped)), ({}, {}, 2))
        self.assertTrue(all('no landing was said' in reason for _, reason in self.ecs.stopped))

    def test_a_service_that_takes_the_role_reads_the_pushes_of_hours_and_keeps_the_trains_slot(self):
        # PREWARM-RESTART-WINDOW: with the in-task successors every landing gives the role to a new process, whose prewarm
        # starts from the log. It read the pushes of the last 10 min only: a branch pushed before that had its pair (the
        # log gives it back) but no head, so the train was never asked for it and a later push took its slot
        for n, head in enumerate((H3, H1)):  # two pushes of units/a, 40 and 30 min ago: only the newest is its head
            self.db.add(self.now[0] - 2400 + 600 * n, *push('units/a', head))
        self.db.known = [{'role': role, 'digest': S1, 'task': f'arn:{role}', 'branch': 'units/a', 'state': 'healthy', 'at': 5}
                         for role in ('runner', 'service')]
        self.ecs.status = {each['task']: {'taskArn': each['task'], 'lastStatus': 'RUNNING', 'healthStatus': 'HEALTHY'}
                           for each in self.db.known}
        self.db.train.add(H1)  # units/a's delivery is in the merge train
        self.watcher.step()
        self.assertEqual((self.watcher.heads, list(self.watcher.pending)), ({'units/a': H1}, [H1]))  # one job: the newest head's
        self.finish(H1, said(S1))
        self.live(('units/b', H2, S2))  # a later push of another branch: the cap is 1
        self.assertEqual((self.ecs.stopped, self.ecs.ran), ([], []))  # the slot stays with the train's delivery
        self.assertEqual(self.watcher.waiting, {'units/b': H2})
        old = self.make(Config())  # and what is older than the window is not read
        self.db.events = [(f'old:{n}', self.now[0] - prewarm.RESTART_S - 60, kind, body) for n, (_, _, kind, body) in
                          enumerate(self.db.events)]
        old.step()
        self.assertEqual(old.heads, {})

    def test_a_prewarm_that_starts_takes_no_merged_branch_for_a_live_one(self):
        # PREWARM-MERGED-RELEASED: live 11/11 22:14 UTC: the process that took the role read three hours of pushes, found six
        # branches whose PRs had merged, and started and dropped a Spot pair for each in turn: five runner standbys left
        # behind as `retiring`, the database at its connections' limit, the port down for four minutes
        self.db.add(self.now[0] - 3000, *push('units/a', H1))
        self.db.add(self.now[0] - 2400, *merged('units/a'))
        self.db.add(self.now[0] - 1800, *push('units/b', H2))
        self.db.swapped.add(S2)  # units/b's bundle landed too; its merge event is not in the log (a webhook lost)
        self.watcher.step()
        for head, sha in ((H1, S1), (H2, S2)):
            if head in self.watcher.pending:
                self.finish(head, said(sha))
        self.now[0] += prewarm.RETRY_S
        self.watcher.step()
        self.assertEqual((self.ecs.ran, self.ecs.stopped, self.db.states()), ([], [], []))
        self.assertEqual((self.watcher.holds, self.watcher.standbys), ({}, {}))
        self.live(('units/a', H3, S1))  # the same continuously: a branch whose PR merged is released once it landed
        self.assertEqual(len(self.ecs.ran), 2)
        self.db.landed.add(H1)  # (LANDING-KEEPS-STANDBY: the delivery's word, which the merge event may come before)
        self.at(merged('units/a'))
        self.assertEqual(len(self.ecs.stopped), 2)
        self.assertTrue(all('units/a: its PR was merged' in reason for _, reason in self.ecs.stopped))

    def test_a_task_left_retiring_is_stopped_at_its_limit_whoever_restarted_meanwhile(self):
        # the five runner standbys of 22:14 UTC stayed `retiring`: every process that took the role counted the limit anew
        self.db.known = [{'role': 'runner', 'digest': S1, 'task': 'arn:old', 'branch': 'units/a', 'state': 'retiring',
                          'at': self.now[0] - prewarm.RETIRE_LIMIT_S - 5}]
        self.ecs.status['arn:old'] = {'taskArn': 'arn:old', 'lastStatus': 'RUNNING', 'healthStatus': 'HEALTHY'}
        self.db.swapped.add(S1)
        self.watcher.step()
        self.assertEqual([task for task, _ in self.ecs.stopped], ['arn:old'])

    def test_a_restarted_service_takes_its_live_tasks_back_from_the_log(self):
        self.db.known = [{'role': 'runner', 'digest': S1, 'task': 'arn:1', 'branch': 'units/a', 'state': 'healthy', 'at': 5},
                         {'role': 'service', 'digest': S1, 'task': 'arn:2', 'branch': 'units/a', 'state': 'stopped', 'at': 6}]
        self.ecs.status['arn:1'] = {'taskArn': 'arn:1', 'lastStatus': 'RUNNING', 'healthStatus': 'HEALTHY'}
        self.watcher.step()
        self.assertEqual(self.watcher.holds, {'units/a': S1})
        self.assertEqual(list(self.watcher.standbys[S1]['tasks']), ['runner'])
        self.at(push('units/a', H2))
        self.finish(H2, said(S2))
        self.assertEqual(self.ecs.stopped[0][0], 'arn:1')  # the older bundle of the branch, from before the restart


class Wiring(unittest.TestCase):
    def test_only_the_live_service_looks(self):
        watcher, stop, waits = mock.Mock(), threading.Event(), []
        watcher.cap.return_value = 1

        def wait(timeout):
            waits.append(timeout)
            if len(waits) == 3:
                stop.set()
        with mock.patch.object(prewarm, 'from_boto3', return_value=watcher):
            prewarm.start(None, stop, wait, active=lambda: False).join(5)
        watcher.step.assert_not_called()
        self.assertEqual(waits, [prewarm.SAFETY_S] * 3)

    def test_without_the_cluster_and_its_network_it_is_off(self):
        environ = {'TOWER_STANDBY_CLUSTER': 'tower', 'TOWER_STANDBY_SUBNETS': 'subnet-1,subnet-2',
                   'TOWER_STANDBY_SECURITY_GROUPS': 'sg-1', 'TOWER_ARTIFACT_BUCKET': 'outputs'}
        for name in environ:
            self.assertIsNone(prewarm.from_boto3(None, environ={**environ, name: ''}), name)
        self.assertIsNone(prewarm.start(None, threading.Event(), None, environ={}))

    def test_serve_starts_it_behind_the_gate_on_a_push_and_on_a_job_end(self):
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        serve = main[main.index('def serve('):main.index('\ndef ', main.index('def serve(') + 1)]
        self.assertIn('(wake.DEPLOY, wake.WORK)).wait', serve)
        self.assertIn('from . import prewarm as standbys', serve)
        self.assertIn('standbys.start(workflows.connected, stop, hub.wake(', serve)  # DB-LISTEN-ONE: on the service's hub
        start = serve.index('standbys.start(')
        self.assertIn('active=None if gate is None else gate.after_work(gate.sole))', serve[start:start + 400])  # IMAGE-PREWARM-C

    def test_the_job_is_one_the_gates_runner_takes_with_the_artifact_environment(self):
        from tower_infra import runner
        import config  # scripts/lib: the registry
        self.assertEqual(prewarm.QUEUE, config.get('gate-infra.check_queue'))
        spec = {'repo': prewarm.REPO, 'ref': 'refs/heads/units/a', 'commit': H1, 'base': BASE,
                'command': ['scripts/gate-check', 'artifact', 'code', '--base', BASE], 'timeout_s': prewarm.TIMEOUT_S}
        self.assertTrue(runner.understood(spec))
        self.assertIn('TOWER_ARTIFACT_BUCKET', runner.passed_env(spec['command'], {'TOWER_ARTIFACT_BUCKET': 'b'}))
        self.assertEqual(prewarm.REPO, config.get('forge-events.repo'))

    def test_the_families_containers_and_environment_are_the_templates(self):
        stacks = ROOT / 'infra/aws/stacks'
        service = json.loads((stacks / '30-service.json').read_text(encoding='utf-8'))['Resources']
        runner = json.loads((stacks / '50-runner.json').read_text(encoding='utf-8'))['Resources']
        for role, task in (('runner', runner['TaskDefinition']), ('service', service['StandbyTaskDefinition'])):
            self.assertEqual(task['Properties']['Family'], prewarm.FAMILIES[role])
            self.assertIn(prewarm.CONTAINERS[role], [each['Name'] for each in task['Properties']['ContainerDefinitions']])
        live = next(each for each in service['TaskDefinition']['Properties']['ContainerDefinitions'] if each['Name'] == 'service')
        given = {item['Name'] for item in live['Environment']}
        self.assertLessEqual({'TOWER_STANDBY_CLUSTER', 'TOWER_STANDBY_SUBNETS', 'TOWER_STANDBY_SECURITY_GROUPS',
                              'TOWER_ARTIFACT_BUCKET'}, given)
        self.assertEqual(service['Cluster']['Properties']['ClusterName'], 'tower')
        self.assertIn('FARGATE_SPOT', service['Cluster']['Properties']['CapacityProviders'])

    def test_the_status_shows_the_newest_transitions(self):
        self.assertIn("type = 'platform.deploy.standby' and tenant_id is null", (ROOT / 'infra/service/tower_infra/port.py')
                      .read_text(encoding='utf-8'))
        self.assertEqual(port.STANDBY_ROWS, 20)
        self.assertGreaterEqual(port.SUCCESSOR_ROWS, 200)  # SUCCESSOR-WINDOW: the front reads its branch's want there


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements: the pushes the ingress records, the job made through port.create_job, the job's end, the
    platform.deploy.standby events, the status that serves them and the restart that reads them back."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db, self.ecs = self.world.db, Ecs()
        self.tenant = self.db.rows("select id::text from work.tenant where name = 'torre'")[0][0]
        self.world.port('PUT', '/v1/queues/checks', 'torre', {'policy': 'fifo'})

    def watcher(self):
        return prewarm.Prewarm(live_image.kept(self.db), self.ecs, 'tower', NETWORK, config=Config())

    def ingress(self, n, kind, body):
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
                     "values (%(id)s, %(tenant)s::uuid, %(type)s, clock_timestamp(), 'forge/origin', 'app/origin', "
                     "%(payload)s::jsonb)", {'id': f'{kind}:{n}', 'tenant': self.tenant, 'type': kind,
                                             'payload': json.dumps({'delivery': {'event': {'payload': body}}})})

    def test_a_push_makes_the_job_its_end_starts_the_standbys_and_the_status_and_a_restart_read_them(self):
        self.ingress(1, *push('mod/roadmap-integration', BASE))
        self.ingress(2, *push('units/a', H1))
        watcher = self.watcher()
        watcher.step()
        job = watcher.pending[H1]
        found = self.db.rows("select queue, state, input_uri, idempotency_key, memoize from work.job where id = %(id)s::uuid",
                             {'id': job})[0]
        self.assertEqual((found[0], found[1], found[3], found[4]), ('checks', 'queued', f'prewarm:code:{H1}', 'f'))
        self.assertEqual(forge.decode(found[2])['command'], ['scripts/gate-check', 'artifact', 'code', '--base', BASE])
        self.db.rows("update work.job set state = 'succeeded', result = %(result)s::jsonb where id = %(id)s::uuid",
                     {'id': job, 'result': said(S1)})
        watcher.step()
        self.assertEqual(self.ecs.digests(), [S1, S1])
        status = self.world.port('GET', '/v1/deploy/status', 'torre')
        self.assertEqual([(each['role'], each['state'], each['branch']) for each in status['standby']],
                         [('service', 'started', 'units/a'), ('runner', 'started', 'units/a')])
        again = self.watcher()  # a restart of the service
        again.step()
        self.assertEqual(again.holds, {'units/a': S1})
        self.assertEqual(sorted(again.standbys[S1]['tasks']), ['runner', 'service'])
        self.ingress(3, *push('units/a', None, deleted=True))
        again.step()
        self.assertEqual(len(self.ecs.stopped), 2)
        newest = self.world.port('GET', '/v1/deploy/status', 'torre')['standby']
        self.assertEqual([each['state'] for each in newest[:2]], ['stopped', 'stopped'])


if __name__ == '__main__':
    unittest.main()
