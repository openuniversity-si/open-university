"""RELOAD-WITHOUT-STANDBY (docs/operations/aws.md 22.9): a code-only landing with no healthy standby pair is loaded in place.

The image-only swap needs both roles' Spot standbys beating at the landing; without them the landed bundle went to the slow
path's two ECS rollouts (minutes). Here the ECS tasks load it in place, one role at a time, with no standby to fall back on:
1. The order: the autodeploy's look records platform.deploy.image_reload {state: ordered} for a landing whose code is a
   verified bundle and whose pair is missing (never with a pair, with deploy.promote false or with no bundle), one order at
   a time, and holds that head's ring while the tasks reload.
2. The runner first: it stages the bundle, takes no new run while the ones in flight end, claims and execs; then the
   service, which goes on dispatching until the pass that finds nothing in flight.
3. The judge is never the process under test: the service (on the code it had) fires and reads the runner's canary, the
   runner reads the service's. Green is proven; red, or a task that never came up, is failed: the bundle is never loaded
   again, whoever runs it goes back afresh, and the landing is the slow path's. Until proven a reloaded task is not trusted
   (its health file is not touched).
4. Both proven, the look writes deploy.live_code and {state: done}: what deploy.sh reads to skip the image and the rollouts.

Hermetic: the look's order on IMAGE-PREWARM-C's fake database, the tasks' looks on a log by statement with an injected
clock, the wiring, the bundle's way back, the measures. OnPostgres runs the real statements (TEST_DATABASE_URL) with the
service's real dispatch tick and the runner's real TAKE.
"""
import contextlib
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import autodeploy, canary, code_bundle, live_image, port, runner  # noqa: E402
import medir  # noqa: E402
import test_infra_autodeploy as looks  # noqa: E402
import test_infra_image_swap as image_swap  # noqa: E402
import test_infra_swap_failover as failover  # noqa: E402
import test_infra_swap_reload as reload  # noqa: E402
from test_infra_swap_ready import workflows_with  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
S, ECS, KEY = reload.S, reload.ECS, reload.KEY  # the landed bundle; the code the ECS tasks run; the bundle's key
MERGE, PR_HEAD, LATER = image_swap.MERGE, image_swap.PR_HEAD, image_swap.LATER
ORDER = {'state': 'ordered', 'digest': S, 'key': KEY, 'head': MERGE, 'pr_head': PR_HEAD, 'order': MERGE}
COMMANDS = {'runner': 'run-container', 'service': 'serve'}
MAIN, SERVE, RUN = reload.MAIN, reload.SERVE, reload.RUN


class Away:
    """code_bundle.afresh by what it was asked: the exec that never returns."""

    def __init__(self, error=None):
        self.went, self.error = [], error

    def __call__(self, command, said):
        self.went.append((command, said))
        raise self.error or reload.Replaced()


class Log(failover.Table):
    """IMAGE-SWAP-FAILOVER's table (one role's pointer on an injected clock) with the order as ORDER_OF answers it and what
    the tasks say of it: the claim (refused under a pointer or once the bundle failed) and proven, failed, back."""

    def __init__(self):
        super().__init__()
        self.order, self.told, self.jobs, self.refused, self.age = dict(ORDER), [], {}, False, 1.0
        self.heads = []  # the order each look asked for: '' the newest, else the one that started the task

    def asked(self, sql=live_image.ORDER_OF):
        return self.count(sql)

    def states(self, role=None):
        return [each['state'] for each in self.told if role in (None, each['role'])]

    def rows(self, sql, params=None):
        if self.broken or sql not in (live_image.ORDER_OF, live_image.ORDER_START, live_image.ORDER_SAY):
            return super().rows(sql, params)
        self.sent.append(sql)
        if sql == live_image.ORDER_OF:
            self.heads.append(params['head'])
            return [] if self.order is None else [(json.dumps(self.order), self.age, json.dumps(self.told), self.refused,
                                                   json.dumps(self.jobs), None, self.clock())]
        said = {**json.loads(params['payload']), 'at': self.clock()}
        if sql == live_image.ORDER_START and (self.value or self.refused or params['id'] in [each.get('id') for each in self.told]):
            return []
        self.told.append({**said, 'id': params['id']})
        self.refused = self.refused or said['state'] == 'failed'
        return [(json.dumps(said),)]


class Task:
    """One ECS task on a log: its gate and its look at the order. step(): one pass later; answers what the exec was asked
    when the pass replaced the process (the bundle's exec, or the way back), else None."""

    def __init__(self, log, role, digest=ECS, name=None, by=None, pending=None, bundle=None, fired=None, strict=False):
        self.log, self.bundle, self.away, self.fired = log, bundle or reload.Bundle(), Away(), [] if fired is None else fired
        self.gate = live_image.Gate(log.scope, role, digest, task=name or f'ecs-{role}', strict=strict, clock=log.clock,
                                    reloaded=by)
        self.gate.refresh()
        self.order = live_image.Order(
            self.gate, COMMANDS[role], pending=pending, hold=role == 'runner', stage=self.bundle.stage,
            execute=self.bundle.execute, afresh=self.away,
            fire=lambda db, tenant, key, said, fire: self.fired.append((key, said, fire)))

    def step(self, later=1.0):
        self.log.clock.now += later
        try:
            self.order.step()
        except reload.Replaced:
            return self.bundle.execed[-1] if self.bundle.execed and not self.away.went else self.away.went[-1]
        return None


def reloaded(role, task=None, turn=None):
    """What a role's reload by the order says: its claim and its first work on the bundle."""
    said = {'role': role, 'digest': S, 'task': task or f'ecs-{role}', 'order': MERGE, 'turn': turn or f'{MERGE[:12]}.0'}
    return [{**said, 'state': 'started', 'at': 1000.0}, {**said, 'state': 'reloaded', 'at': 1000.0}]


def proven(role):
    return {'role': role, 'digest': S, 'state': 'proven', 'order': MERGE}


class TheTasksLook(unittest.TestCase):
    def setUp(self):
        self.log = Log()

    def test_with_no_order_a_pass_sends_nothing_but_the_look_owed_at_the_start_and_on_a_notification(self):
        self.log.order = None
        task = Task(self.log, 'runner')
        for _ in range(5):
            self.assertIsNone(task.step())
        self.assertEqual(self.log.asked(), 1)  # the start's: a task ECS started mid-way finds the order
        task.gate.refresh()  # the gate's listener read the pointer again: a notification of tower_config
        for _ in range(5):
            task.step()
        self.assertEqual((self.log.asked(), task.gate.reloading, task.order.trusted()), (2, False, True))

    def test_a_standby_and_a_task_under_a_pointer_follow_no_order(self):
        strict = Task(self.log, 'runner', S, strict=True)
        under = Task(self.log, 'runner')
        self.log.write(S)  # a swap: the pointer names another digest, this task stands by (Reload is in charge)
        under.gate.refresh()
        for task in (strict, under):
            self.assertIsNone(task.step())
        self.assertEqual((self.log.asked(), under.bundle.staged), (0, []))

    def test_the_runner_stages_takes_no_new_run_while_one_is_in_flight_and_execs_when_it_ends(self):
        task = Task(self.log, 'runner')
        with task.gate.engaged('slot-1') as free:  # a run in flight
            self.assertTrue(free)
            self.assertIsNone(task.step())
            self.assertEqual((task.bundle.staged, task.bundle.execed, self.log.states()), ([(KEY, S)], [], []))
            with task.gate.engaged('slot-2') as other:
                self.assertFalse(other)  # no slot takes a run while the task drains
            self.assertIsNone(task.step())
        with task.gate.engaged('slot-2') as other:  # the run ended: still no new one
            self.assertFalse(other)
        went = task.step()
        self.assertEqual((went['command'], went['key'], went['sha'], task.bundle.staged), ('run-container', KEY, S, [(KEY, S)]))
        said = went['said']
        self.assertEqual((said['state'], said['role'], said['from'], said['order'], said['turn'], said['task']),
                         ('started', 'runner', ECS, MERGE, f'{MERGE[:12]}.0', 'ecs-runner'))
        self.assertEqual(said['drain_s'], 2.0)  # from the staging to the claim: the run in flight
        self.assertEqual(self.log.states(), ['started'])

    def test_the_service_stages_and_waits_for_the_runner_to_be_proven(self):
        task = Task(self.log, 'service')
        self.assertIsNone(task.step())
        self.log.told += reloaded('runner')  # reloaded, not judged yet
        self.assertIsNone(task.step())
        self.assertEqual((task.bundle.staged, task.bundle.execed, task.gate.reloading), ([(KEY, S)], [], False))
        self.log.told.append(proven('runner'))
        went = task.step()
        self.assertEqual((went['command'], went['said']['role'], went['said']['turn']), ('serve', 'service', f'{MERGE[:12]}.0'))

    def test_the_service_goes_on_working_until_the_pass_that_finds_nothing_in_flight(self):
        pending = ['run-1']
        task = Task(self.log, 'service', pending=lambda: pending)
        self.log.told += [*reloaded('runner'), proven('runner')]
        for _ in range(3):
            self.assertIsNone(task.step())
            with task.gate.engaged('look') as free:  # between its passes its looks start and it dispatches
                self.assertTrue(free)
        del pending[:]
        with task.gate.engaged('look'):
            self.assertIsNone(task.step())  # a look in flight is waited for too
        self.assertEqual(task.step()['said']['drain_s'], 4.0)  # from the staging: the workflow and the look in flight
        slow = Task(Log(), 'service', pending=lambda: ['hung'])
        slow.log.told += [*reloaded('runner'), proven('runner')]
        self.assertIsNone(slow.step())
        went = slow.step(live_image.DRAIN_S)  # past DRAIN_S the workflows are named and left to their leases
        self.assertEqual(went['said']['stragglers'], ['hung'])

    def test_the_service_fires_the_runners_canary_and_judges_it_by_its_job(self):
        task = Task(self.log, 'service')
        self.log.told += reloaded('runner')[:1]
        self.assertIsNone(task.step())
        self.assertEqual(task.fired, [])  # claimed, not up yet: nothing to prove
        self.log.told += reloaded('runner')[1:]
        task.step()
        self.assertEqual(task.fired, [(f'order:{MERGE}:runner', {'digest': S, 'head': MERGE, 'by': 'order'}, True)])
        self.log.jobs = {'runner': {'state': 'running', 'age_s': 3.0}}
        task.step()
        self.assertEqual((self.log.states('runner'), len(task.fired)), (['started', 'reloaded'], 1))
        self.log.jobs = {'runner': {'state': 'succeeded', 'age_s': 4.0}}
        with self.assertLogs('tower_infra.live_image', 'INFO'):
            went = task.step()  # proven, and the service's own turn in the same look
        said = [each for each in self.log.told if each['state'] == 'proven'][0]
        self.assertEqual((said['role'], said['task'], said['by'], said['order'], went['said']['role']),
                         ('runner', 'ecs-runner', 'ecs-service', MERGE, 'service'))

    def test_a_red_canary_or_a_task_that_never_came_up_is_failed_and_nothing_loads_the_bundle(self):
        for jobs, told, later, why in (
                ({'runner': {'state': 'failed', 'age_s': 2.0}}, reloaded('runner'), 1, 'the canary of its reload is failed after 2.0 s'),
                ({'runner': {'state': 'queued', 'age_s': 121.0}}, reloaded('runner'), 1, 'the canary of its reload is queued after 121.0 s'),
                ({}, reloaded('runner')[:1], live_image.RELOAD_LIMIT_S, 'ecs-runner did not come up on it within 120 s of its reload')):
            log = Log()
            log.clock.now, log.jobs = 1000.0, jobs
            log.told += told
            task = Task(log, 'service')
            with self.assertLogs('tower_infra.live_image', 'WARNING'):
                self.assertIsNone(task.step(later))
            said = log.told[-1]
            self.assertEqual((said['state'], said['role'], said['why'], said['by'], task.bundle.execed), ('failed', 'runner', why, 'ecs-service', []))
            self.assertIsNone(task.step())  # the bundle failed: no more looks, nothing loaded
            self.assertEqual((log.asked(), task.gate.reloading), (2, False))

    def test_the_runner_judges_the_service_by_the_canary_the_service_fired_and_none_in_the_limit_is_failed(self):
        log = self.log
        log.clock.now = 1000.0
        log.told += [*reloaded('runner'), proven('runner'), *reloaded('service')]
        task = Task(log, 'runner', S, by=reloaded('runner')[0])
        self.assertIsNone(task.step())
        self.assertEqual((task.fired, log.states('service')), ([], ['started', 'reloaded']))  # it never fires the service's
        log.jobs = {'service': {'state': 'succeeded', 'age_s': 3.0}}
        with self.assertLogs('tower_infra.live_image', 'INFO'):
            task.step()
        self.assertEqual(log.states('service'), ['started', 'reloaded', 'proven'])
        late = Log()
        late.clock.now = 1000.0
        late.told += [*reloaded('runner'), proven('runner'), *reloaded('service')]
        judge = Task(late, 'runner', S, by=reloaded('runner')[0])
        with self.assertLogs('tower_infra.live_image', 'WARNING'):
            judge.step(121)  # deploy.canary_limit_s with no row: 120 s
        self.assertEqual((late.told[-1]['state'], late.told[-1]['why']), ('failed', 'no canary of its reload in 120 s'))

    def test_a_reloaded_task_is_not_trusted_until_proven_and_goes_back_afresh_when_its_bundle_failed(self):
        self.log.told += reloaded('runner')
        task = Task(self.log, 'runner', S, by=reloaded('runner')[0])
        self.assertFalse(task.order.trusted())  # from its start: the health file is not touched
        task.step()
        self.assertFalse(task.order.trusted())
        self.log.told.append(proven('runner'))
        task.step()
        self.assertTrue(task.order.trusted())
        task.step()
        self.assertEqual(self.log.heads, [MERGE, MERGE, ''])  # its own order until it is judged, whatever was ordered since
        self.log.refused = True  # the service's reload failed later: the bundle is not to be run
        with task.gate.engaged('slot-1'):  # a run in flight is never killed
            self.assertIsNone(task.step())
            with task.gate.engaged('slot-2') as free:
                self.assertFalse(free)
        self.assertEqual((task.away.went, task.order.trusted()), ([], False))
        with self.assertLogs('tower_infra.live_image', 'WARNING'):
            went = task.step()
        self.assertEqual(went, ('run-container', {'back': True, 'digest': S, 'order': MERGE, 'task': 'ecs-runner'}))
        self.assertEqual(self.log.states()[-1], 'back')

    def test_a_task_that_cannot_go_back_stays_not_trusted_for_ecs_to_replace(self):
        self.log.told += reloaded('service')
        self.log.refused = True
        task = Task(self.log, 'service', S, by=reloaded('service')[0])
        task.away.error = OSError('exec format error')
        with self.assertLogs('tower_infra.live_image', 'ERROR'):
            self.assertIsNone(task.step())
        self.assertEqual((task.order.trusted(), task.gate.reloading), (False, False))
        other = Task(self.log, 'runner')  # a task that does not run the bundle has nothing to go back from
        self.assertIsNone(other.step())
        self.assertEqual((other.away.went, other.order.trusted(), other.bundle.staged), ([], True, []))

    def test_a_swap_that_lands_meanwhile_is_in_charge(self):
        task = Task(self.log, 'runner')
        with task.gate.engaged('slot-1'):
            task.step()
        self.assertTrue(task.gate.reloading)
        self.log.write('b' * 64)  # a later landing swapped: this task stands by under it
        task.gate.refresh()
        self.assertIsNone(task.step())
        self.assertEqual((task.gate.reloading, task.bundle.execed), (False, []))  # the drain is over: Reload's path now
        unseen = Task(Log(), 'runner')
        unseen.log.value = 'b' * 64  # the pointer written and not read yet: the claim's compare-and-swap refuses
        self.assertIsNone(unseen.step())
        self.assertEqual((unseen.bundle.execed, unseen.log.states(), unseen.gate.reloading), ([], [], False))

    def test_past_its_limit_an_order_starts_no_reload_and_one_reload_runs_at_a_time(self):
        self.log.age = live_image.ORDER_LIMIT_S + 1
        task = Task(self.log, 'runner')
        self.assertIsNone(task.step())
        self.assertIsNone(task.step())
        self.assertEqual((task.bundle.staged, self.log.asked()), ([], 1))  # the slow path's: no more looks
        log = Log()
        log.told += reloaded('runner', task='ecs-runner-1')[:1]  # another task of the role claimed and is not up yet
        second = Task(log, 'runner', name='ecs-runner-2')
        self.assertIsNone(second.step())
        self.assertEqual((second.bundle.execed, second.gate.reloading), ([], False))
        log.told += [*reloaded('runner', task='ecs-runner-1')[1:], proven('runner')]
        self.assertEqual(second.step()['said']['turn'], f'{MERGE[:12]}.1')  # a task ECS started mid-way follows the order

    def test_a_bundle_that_cannot_be_loaded_or_an_exec_that_fails_is_failed(self):
        task = Task(self.log, 'runner', bundle=reload.Bundle(error=code_bundle.BundleError('other requirements')))
        self.assertIsNone(task.step())
        self.assertEqual((self.log.told[-1]['state'], self.log.told[-1]['why']),
                         ('failed', 'the bundle cannot be loaded: other requirements'))
        log = Log()
        broken = Task(log, 'runner', bundle=reload.Bundle(exec_error=OSError('no exec')))
        self.assertIsNone(broken.step())
        self.assertEqual((log.states(), log.told[-1]['why'], broken.gate.reloading),
                         (['started', 'failed'], 'the exec failed: no exec', False))

    def test_a_look_that_fails_is_tried_again_on_the_next_pass(self):
        task = Task(self.log, 'runner')
        self.log.broken = True
        with self.assertLogs('tower_infra.live_image', 'ERROR'):
            self.assertIsNone(task.step())
        self.log.broken = False
        self.assertEqual(task.step()['said']['state'], 'started')


class Db(image_swap.Db):
    """IMAGE-PREWARM-C's fake database with the order as the look's statement answers it."""

    def __init__(self):
        super().__init__()
        self.busy, self.bad, self.asked, self.order = None, False, [], []

    def rows(self, sql, params=None):
        if sql == autodeploy.ORDER:
            self.asked.append(json.loads(params['payload']))
            made = not self.busy and not self.bad
            return [(int(made), self.busy, self.bad, int(made))]
        if sql == live_image.ORDER_OF:
            self.asked.append(sql)
            return [each for each in self.order if json.loads(each[0])['head'] == params['head']]
        if sql == autodeploy.ORDER_DONE:
            self.asked.append(params)
            return [(f"{params['digest']}@{params['head']}" if params['newest'] else None, 1, 1)]
        return super().rows(sql, params)


def answered(events=(), refused=False, age=5.0, jobs=None, head=MERGE):
    return [(json.dumps({**ORDER, 'head': head, 'order': head}), age, json.dumps(list(events)), refused, json.dumps(jobs or {}),
             None, 1000.0)]


class TheLooksOrder(image_swap.World):
    def setUp(self):
        super().setUp()
        self.db = Db()
        self.watcher.landed_at[MERGE] = self.now[0] - 1

    def test_a_code_only_landing_with_no_pair_is_ordered_to_the_ecs_tasks(self):
        self.db.standbys = []
        with self.assertLogs('tower_infra.autodeploy', 'INFO') as logs:
            self.land()
        [swap] = self.db.swaps()
        self.assertEqual((swap['swapped'], self.db.pointer), (False, {}))  # no swap, said as before
        self.assertIn('no healthy runner or service standby', swap['why'])
        self.assertEqual(self.db.asked, [ORDER])
        self.assertIn('ordered: the ECS tasks load aaaaaaaaaaaa in place, the runner first', '\n'.join(logs.output))
        self.assertEqual(self.watcher.reload, MERGE)
        self.watcher.promote(self.db, self.heads, image_swap.CFG)  # the same landing again: nothing
        self.assertEqual(len(self.db.asked), 1)

    def test_a_pair_present_swaps_as_today_and_orders_nothing(self):
        with self.assertLogs('tower_infra.autodeploy', 'INFO'):
            self.land()
        self.assertEqual((self.db.pointer, self.db.asked, self.watcher.reload), ({key: S for key in image_swap.KEYS}, [], None))
        self.watcher.reloads(self.db, self.heads)  # and the look follows nothing: no statement
        self.assertEqual(self.db.asked, [])

    def test_with_promote_false_or_no_bundle_it_is_the_slow_path_as_today(self):
        for given in ({'cfg': {'promote': False}}, {'job': []}, {'event': image_swap.landed(bundle_same=False)},
                      {'heads': [LATER, MERGE]}, {'event': image_swap.landed(code_only=False)}):
            self.setUp()
            self.db.standbys = []
            if 'job' in given:
                self.db.job = given['job']
            self.land(given.get('event'), given.get('cfg', image_swap.CFG), given.get('heads'))
            self.assertEqual((self.db.asked, self.db.pointer, self.watcher.reload), ([], {}, None), given)

    def test_one_order_at_a_time_and_the_newest_head_after_the_one_in_flight_settles(self):
        self.db.standbys, self.db.busy = [], 'c' * 40
        with self.assertLogs('tower_infra.autodeploy', 'INFO') as logs:
            self.land()
        self.assertIn('is not settled: this one waits', '\n'.join(logs.output))
        self.assertEqual((self.watcher.reload, self.watcher.waiting), (None, (MERGE, S, KEY, PR_HEAD)))
        self.assertRegex(self.watcher.reloading(MERGE, self.now[0]), '^reloading: ')  # its ring waits for it too
        self.watcher.reloads(self.db, self.heads)  # still not settled: asked again, waits again
        self.assertEqual((len(self.db.asked), self.watcher.waiting[0]), (2, MERGE))
        self.db.busy = None
        with self.assertLogs('tower_infra.autodeploy', 'INFO'):
            self.watcher.reloads(self.db, self.heads)  # settled: ordered now
        self.assertEqual((self.watcher.reload, self.watcher.waiting, len(self.db.asked)), (MERGE, None, 3))
        self.setUp()
        self.db.standbys, self.db.busy = [], 'c' * 40
        self.land()
        self.watcher.reloads(self.db, [*self.heads, LATER])  # another landing on top: this one is never ordered
        self.assertEqual((self.watcher.waiting, len(self.db.asked)), (None, 1))

    def test_a_bundle_a_reload_failed_on_is_not_ordered_again(self):
        self.db.standbys, self.db.bad = [], True
        with self.assertLogs('tower_infra.autodeploy', 'INFO') as logs:
            self.land()
        self.assertIn('not ordered: a reload onto aaaaaaaaaaaa failed', '\n'.join(logs.output))
        self.assertEqual((self.watcher.reload, self.watcher.waiting, self.watcher.reloading(MERGE, self.now[0])), (None, None, None))

    def test_the_ring_of_the_head_waits_for_the_reload_and_never_past_the_limit(self):
        self.db.standbys = []
        self.land()
        why = self.watcher.reloading(MERGE, self.now[0])
        self.assertEqual(why, f'reloading: the ECS tasks are loading the code of {MERGE[:12]} in place; the build is rung when '
                              'both are proven or one fails, in 299 s at most')
        self.assertEqual(self.watcher.due_in, 299.0)  # the look comes back at the limit with no event
        self.assertIsNone(self.watcher.reloading(LATER, self.now[0]))  # only the ordered head's
        self.assertIsNone(self.watcher.reloading(MERGE, self.now[0] + live_image.ORDER_LIMIT_S))
        source = (ROOT / 'infra/service/tower_infra/autodeploy.py').read_text(encoding='utf-8')
        look = source[source.index('    def decide_in('):source.index('    def bisection(')]
        self.assertIn('held = self.rolling(db, last, now) or self.reloading(head, now)', look)
        self.assertIn("decision[1].startswith(('running', 'rolling', 'reloading'))", source)  # the short safety meanwhile

    def test_the_look_holds_the_ring_of_a_swapped_head_until_both_tasks_took_its_code_over(self):
        # RING-AT-TAKEOVER: live 11/11 (#529): the landing swapped in 0.3 s, the build was rung 35 s later while the ECS
        # runner still finished its runs, read `reloaded: service` only and built the image and rolled both stacks out
        class Swapped(looks.FakeDb):
            taken, back = '', False

            def rows(self, sql, params=None):
                if sql == autodeploy.TAKEOVER:
                    return [(S, self.taken, self.back)] if params['head'] == MERGE else []
                return super().rows(sql, params)
        rig = looks.Rig()
        rig.db = Swapped()
        rig.watcher.overrides['debounce_s'] = ('0', 20)
        rig.db.push(looks.T0 - 30, MERGE)
        rig.watcher.landed_at[MERGE] = looks.T0 - 30
        rig.db.taken = 'service'
        action, why = rig.look()
        self.assertEqual((action, rig.rings), ('skip', []))
        self.assertEqual(why, f'reloading: the ECS tasks are taking the swapped code of {MERGE[:12]} over (so far: service); the '
                              f'build is rung when both have, in {live_image.ORDER_LIMIT_S - 30:.0f} s at most')
        self.assertTrue(rig.watcher.in_flight)  # a look soon, whatever notifies
        rig.db.taken = 'runner service'  # the runner's `reloaded` woke the look: the build finds the code live
        self.assertEqual(rig.look(5), ('ring', 'started'))
        for given in ({'back': True}, {'taken': '', 'landed': looks.T0 - live_image.ORDER_LIMIT_S - 1}):
            late = looks.Rig()
            late.db = Swapped()
            late.watcher.overrides['debounce_s'] = ('0', 20)
            late.db.push(looks.T0 - 30, MERGE)
            late.watcher.landed_at[MERGE] = given.get('landed', looks.T0 - 30)
            late.db.taken, late.db.back = given.get('taken', 'service'), given.get('back', False)
            self.assertEqual(late.look(), ('ring', 'started'))  # the swap went back, or the limit passed: the slow path, as before
        none = looks.Rig()  # a head that did not swap, or a look that never saw the landing, waits for nothing
        none.db = Swapped()
        self.assertIsNone(none.watcher.taking_over(none.db, LATER, looks.T0))
        none.watcher.landed_at[LATER] = looks.T0 - 1
        self.assertIsNone(none.watcher.taking_over(none.db, LATER, looks.T0))

    def test_both_roles_proven_is_the_orders_end_and_the_live_code_of_the_newest_head(self):
        self.db.standbys = []
        self.land()
        self.db.order = answered(reloaded('runner') + [proven('runner')])
        self.watcher.reloads(self.db, self.heads)
        self.assertEqual((self.watcher.reload, [each for each in self.db.asked if isinstance(each, dict) and 'newest' in each]),
                         (MERGE, []))  # the service is not proven yet
        self.db.order = answered([proven('runner'), proven('service')])
        with self.assertLogs('tower_infra.autodeploy', 'INFO') as logs:
            self.watcher.reloads(self.db, self.heads)
        done = self.db.asked[-1]
        self.assertEqual((done['head'], done['digest'], done['newest'], done['order'], done['id']),
                         (MERGE, S, True, f'{live_image.RELOAD}:order:{MERGE}', f'{live_image.RELOAD}:done:{MERGE}'))
        self.assertIn('reloaded in place: both ECS tasks run aaaaaaaaaaaa and proved it; deploy.live_code -> aaaaaaaaaaaa',
                      '\n'.join(logs.output))
        self.assertEqual((self.watcher.reload, self.watcher.reloading(MERGE, self.now[0])), (None, None))  # the build is rung
        self.setUp()
        self.db.standbys = []
        self.land()
        self.db.order = answered([proven('runner'), proven('service')])
        self.watcher.reloads(self.db, [*self.heads, LATER])  # another landing on top: done, and the datum is not this head's
        self.assertIs(self.db.asked[-1]['newest'], False)

    def test_a_failed_reload_or_another_order_ends_the_wait_and_a_service_that_starts_mid_way_follows_the_order(self):
        self.db.standbys = []
        self.land()
        self.db.order = answered(refused=True)
        self.watcher.reloads(self.db, self.heads)
        self.assertEqual((self.watcher.reload, self.watcher.reloading(MERGE, self.now[0])), (None, None))  # the slow path
        self.setUp()
        self.db.idents.add(f'{autodeploy.SWAP}:{MERGE}')  # the service before this one said why it did not swap
        self.land()
        self.assertEqual((self.watcher.reload, self.db.asked), (MERGE, []))
        self.db.order = answered(head=LATER)
        self.watcher.reloads(self.db, self.heads)  # no order of this head: nothing to follow
        self.assertIsNone(self.watcher.reload)
        self.setUp()
        self.db.idents.add(f'{autodeploy.SWAP}:{MERGE}')
        self.land({**image_swap.landed(), 'swap': {'swapped': True}})  # the landing swapped: not even a read
        self.assertIsNone(self.watcher.reload)

    def test_the_canaries_verdicts_are_recorded_by_the_look_once_each(self):
        self.db.standbys = []
        self.land()
        asked = []

        def settle(db, tenant, key, said=None, fire=False, publish=None, **_):
            asked.append((key, fire, publish))
            return {'ok': True if key.endswith('runner') else None}
        self.db.order = answered(jobs={'runner': {'state': 'succeeded', 'age_s': 2}, 'service': {'state': 'queued', 'age_s': 1}})
        with mock.patch.object(canary, 'settle', settle):
            self.watcher.reloads(self.db, self.heads)
            self.watcher.reloads(self.db, self.heads)
        self.assertEqual(asked, [(f'order:{MERGE}:runner', False, self.watcher.alert)] + [(f'order:{MERGE}:service', False, self.watcher.alert)] * 2)


class HeldDb(looks.FakeDb):
    """The autodeploy's fake log with an order of the pushed head in flight."""

    order = []

    def rows(self, sql, params=None):
        return self.order if sql == live_image.ORDER_OF and params['head'] == MERGE else super().rows(sql, params)


class TheRing(unittest.TestCase):
    def test_the_look_holds_the_ring_while_the_tasks_reload_and_rings_at_the_orders_end(self):
        rig = looks.Rig()
        rig.db = HeldDb()
        rig.watcher.overrides['debounce_s'] = ('0', 20)
        rig.db.push(looks.T0 - 30, MERGE)
        rig.watcher.reload, rig.watcher.landed_at[MERGE], rig.db.order = MERGE, looks.T0 - 30, answered()
        action, why = rig.look()
        self.assertEqual((action, why[:10], rig.rings), ('skip', 'reloading:', []))
        self.assertTrue(rig.watcher.in_flight)
        self.assertAlmostEqual(rig.watcher.safety_s(), rig.watcher.check_every_s)  # a look soon, whatever notifies
        rig.db.order = answered(refused=True)  # failed: the slow path, at once
        self.assertEqual(rig.look(5), ('ring', 'started'))
        late = looks.Rig()
        late.db = HeldDb()
        late.watcher.overrides['debounce_s'] = ('0', 20)
        late.db.push(looks.T0 - 30, MERGE)
        late.watcher.reload, late.watcher.landed_at[MERGE], late.db.order = MERGE, looks.T0 - 30, answered()
        self.assertEqual(late.look()[0], 'skip')
        self.assertEqual(late.look(live_image.ORDER_LIMIT_S), ('ring', 'started'))  # never past the limit

    def test_a_look_with_no_order_sends_todays_statements_exactly(self):
        rig = looks.Rig()  # its FakeDb refuses any statement it does not know
        rig.db.push(looks.T0 - 500, MERGE)
        with self.assertNoLogs('tower_infra.autodeploy', 'ERROR'):
            self.assertEqual(rig.look(), ('ring', 'started'))


class TheWiring(unittest.TestCase):
    def test_only_a_live_ecs_task_has_an_order_and_no_gate_is_todays_path(self):
        for body, command in ((SERVE, "'serve', pending=pending, stopping=stop.is_set)"),
                              (RUN, "'run-container', stopping=reload.stopping, hold=True)")):
            self.assertIn('order = None if gate is None or gate.strict else live_image.Order(', body)
            self.assertIn(command, body)
        sent = []

        class Recording:
            def rows(self, sql, params=None):
                sent.append(sql)
                return []
        slot = runner.Runner(Recording(), None, None, None, '/tmp', name='r')  # no TOWER_IMAGE_DIGEST: no gate, no order
        self.assertIsNone(slot.once())
        self.assertEqual((sent, slot.order), ([runner.TAKE], None))

    def test_the_services_look_is_before_its_tick_and_its_health_waits_for_its_judge(self):
        loop = SERVE[SERVE.index('launch()  # IMAGE-PREWARM-B2: once'):]
        self.assertLess(loop.index('order.step()'), loop.index('workflows.tick(lease, '))  # the exec falls between two ticks
        self.assertIn('if now - last_beat >= heartbeat and (order is None or order.trusted()):\n                touch_health(engine)', loop)
        standby = SERVE[SERVE.index('if gate is not None and not gate.active():'):SERVE.index('launched = launch.done')]
        self.assertNotIn('order', standby)  # a task standing by under a swap follows Reload

    def test_the_runners_slots_look_after_a_good_pass_and_its_health_waits_for_its_judge(self):
        self.assertIn('order=order, reload=reload, gate=gate))', RUN)
        calls, stop = [], mock.Mock()
        stop.is_set.side_effect = [False, True]
        order = mock.Mock()
        order.step.side_effect = lambda db: calls.append('look')
        gate = live_image.Gate(Log().scope, 'runner', ECS, task='r')
        gate.refresh()
        slot = runner.Runner(mock.Mock(rows=lambda sql, params=None: calls.append('take') or []), None, None, None, '/tmp',
                             name='r', gate=gate, order=order, beat=lambda: calls.append('beat'), wait=lambda _: None)
        slot.loop(stop)
        self.assertEqual([each for each in calls if each != 'take'][-2:], ['beat', 'look'])
        self.assertIn('take', calls)
        gate.reloading = True  # the task drains: the slot takes no run, and still looks
        del calls[:]
        stop.is_set.side_effect = [False, True]
        slot.loop(stop)
        self.assertEqual(calls, ['beat', 'look'])
        order.trusted.return_value = False  # reloaded by an order and not proven yet: no beat, so the health file goes stale
        del calls[:]
        stop.is_set.side_effect = [False, True]
        slot.loop(stop)
        self.assertEqual(calls, ['look'])

    def test_a_reloaded_service_fires_the_canary_its_judge_reads(self):
        gate = mock.Mock(reloaded={'order': MERGE, 'turn': 't'}, digest=S, task='ecs-service', role='service')
        self.assertEqual(canary.Live(gate, None).due(), (f'order:{MERGE}:service', 'order'))
        self.assertEqual(canary.order_key(MERGE, 'runner'), f'order:{MERGE}:runner')
        gate.reloaded = {'turn': 0}  # a swap's reload: its own key, as before
        self.assertEqual(canary.Live(gate, None).due(), (f'reload:{S}:0:ecs-service', 'reload'))

    def test_a_task_that_went_back_says_no_task_up_and_warms_nothing_again(self):
        self.assertIn('warm_s = (None if gate is not None and (os.environ.get(code_bundle.RELOADED) or late)', RUN)
        self.assertIn('else prewarm(container, boxes, connect, name))', RUN)
        self.assertIn('if environ.get(code_bundle.STANDBY) or environ.get(code_bundle.RELOADED):\n        return False', MAIN)


def execve(path, argv, environ):
    raise reload.Replaced((argv, environ))


class TheWayBack(unittest.TestCase):
    """code_bundle.afresh: the same command as ECS started the task with."""

    TASK = {'TOWER_IMAGE': 'repo@sha256:1', 'TOWER_IMAGE_DIGEST': 'repo@sha256:1', 'TOWER_CODE_KEY': '', 'TOWER_CODE_SHA256': '',
            'TOWER_CODE_SEEN': 'unknown', 'PATH': '/bin'}

    def exec(self, call, *args):
        with self.assertRaises(reload.Replaced) as went:
            call(*args, execve=execve)
        return went.exception.code

    def test_every_exec_onto_a_bundle_keeps_what_the_task_definition_gave(self):
        argv, child = self.exec(code_bundle.reload, 'serve', KEY, S, '/code/a', {'digest': S}, dict(self.TASK))
        base = json.loads(child[code_bundle.BASE])
        self.assertEqual(base, {'TOWER_CODE_KEY': '', 'TOWER_CODE_SHA256': '', 'TOWER_IMAGE_DIGEST': 'repo@sha256:1',
                                'TOWER_IMAGE': 'repo@sha256:1', 'TOWER_MIGRATIONS': None})
        self.assertEqual((child['TOWER_IMAGE_DIGEST'], child['TOWER_CODE_SHA256']), (S, S))
        _, again = self.exec(code_bundle.reload, 'serve', 'k2', 'b' * 64, '/code/b', {'digest': 'b' * 64}, child)
        self.assertEqual(json.loads(again[code_bundle.BASE]), base)  # the first exec's, carried by every later one
        del child[code_bundle.BASE]  # a process exec'd by code older than this unit: its own bundle is what it goes back to
        _, late = self.exec(code_bundle.reload, 'serve', 'k2', 'b' * 64, '/code/b', {'digest': 'b' * 64}, child)
        self.assertEqual(json.loads(late[code_bundle.BASE]), {
            'TOWER_CODE_KEY': KEY, 'TOWER_CODE_SHA256': S, 'TOWER_IMAGE_DIGEST': S, 'TOWER_IMAGE': 'repo@sha256:1',
            'TOWER_MIGRATIONS': '/code/a/migrations'})

    def test_afresh_is_the_task_as_ecs_started_it_marked_as_no_new_task(self):
        _, child = self.exec(code_bundle.reload, 'serve', KEY, S, '/code/a', {'digest': S, 'order': MERGE}, dict(self.TASK))
        for name in code_bundle.RESTORED:  # the loaded process's own boot put these back (code_bundle.restore)
            child.pop(name, None)
            child.pop(code_bundle.PRIOR + name, None)
        said = {'back': True, 'digest': S, 'order': MERGE, 'task': 't'}
        argv, back = self.exec(code_bundle.afresh, 'serve', said, child)
        self.assertEqual(argv[1:], ['-m', 'tower_infra', 'serve'])
        self.assertEqual({name: back.get(name) for name in (*self.TASK, 'TOWER_MIGRATIONS', code_bundle.LOADED, code_bundle.BASE)},
                         {**self.TASK, 'TOWER_MIGRATIONS': None, code_bundle.LOADED: None, code_bundle.BASE: None})
        self.assertEqual(json.loads(back[code_bundle.RELOADED]), said)
        self.assertIsNone(code_bundle.reloaded(back))  # it runs another digest: no reload to record, no canary of its own
        # its boot decides as a task's start does: the definition's code when the live code is one a reload failed on
        with self.assertLogs('tower_infra.code_bundle', 'WARNING'):
            self.assertIsNone(code_bundle.newer({**back, 'TOWER_CODE_SEEN': 'f' * 64 + '@' + 'e' * 40}, '',
                                                lambda environ: (f'{S}@{MERGE}', True)))

    def test_a_successor_that_took_the_role_and_reloads_in_place_is_the_roles_process_not_a_successor(self):
        # ADOPTED-EXEC-IS-MAIN: live 11/11 20:41 UTC (#530's landing, by its order): the service's process was a successor
        # that had adopted the role at the landing before; its exec onto the order's bundle kept TOWER_STANDBY=intask,
        # so the reloaded process stood by as a strict successor of a bundle no pointer named. Nothing dispatched for
        # 7.7 min, until the pointer was written by hand
        adopted = code_bundle.successor(dict(self.TASK), KEY, S, '/spool/code')  # as its supervisor started it
        self.assertEqual(adopted[code_bundle.STANDBY], code_bundle.INTASK)
        _, child = self.exec(code_bundle.reload, 'serve', 'k2', 'b' * 64, '/code/b', {'digest': 'b' * 64, 'order': MERGE}, adopted)
        self.assertNotIn(code_bundle.STANDBY, child)
        self.assertEqual((live_image.heed(child), live_image.named('task-1', child)), (False, 'task-1'))
        late = {**child, code_bundle.STANDBY: code_bundle.INTASK}  # one that code older than this unit exec'd: going back heals it
        _, back = self.exec(code_bundle.afresh, 'serve', {'back': True, 'digest': 'b' * 64}, late)
        self.assertNotIn(code_bundle.STANDBY, back)
        spot = {**self.TASK, code_bundle.STANDBY: '1'}  # a Spot standby's mark is the prewarm's: an exec does not make it a task
        _, kept = self.exec(code_bundle.reload, 'serve', KEY, S, '/code/a', {'digest': S}, spot)
        self.assertEqual(kept[code_bundle.STANDBY], '1')

    def test_a_process_no_exec_started_has_nothing_to_go_back_to(self):
        with self.assertRaisesRegex(code_bundle.BundleError, 'no TOWER_CODE_BASE'):
            code_bundle.afresh('serve', {}, dict(self.TASK), execve)


class TheMeasures(unittest.TestCase):
    STATUS = {'image_reload': [
        {'state': 'done', 'head': MERGE, 'order': MERGE, 'digest': S, 'seconds': 33.1},
        {'role': 'service', 'state': 'proven', 'order': MERGE, 'digest': S},
        {'role': 'service', 'state': 'reloaded', 'order': MERGE, 'digest': S, 'reload_s': 27.5, 'boot_s': 5.0},
        {'role': 'runner', 'state': 'reloaded', 'order': MERGE, 'digest': S, 'reload_s': 9.25, 'boot_s': 6.0},
        {'state': 'ordered', 'head': MERGE, 'order': MERGE, 'digest': S, 'landed_s': 0.75},
        {'role': 'service', 'state': 'reloaded', 'digest': 'b' * 64, 'reload_s': 14.0},  # a swap's reload
        {'state': 'ordered', 'head': LATER, 'order': LATER, 'digest': 'c' * 64, 'landed_s': 0.5},  # only the runner got there
        {'role': 'runner', 'state': 'reloaded', 'order': LATER, 'digest': 'c' * 64, 'reload_s': 8.0}]}

    def test_medir_says_the_landing_to_both_roles_on_the_bundle_apart_from_the_swaps_reloads(self):
        found = medir.from_deploy_status(self.STATUS)
        self.assertEqual(found['image_reload_nostandby_s'], [28.25])  # landing -> order 0.75 + order -> the service's first work
        self.assertEqual(found['image_reload_s'], [14.0])  # the swap's own measure keeps its meaning

    def test_the_status_keeps_enough_reloads_for_an_order_and_the_build_that_reads_it(self):
        self.assertGreaterEqual(port.RELOAD_ROWS, 4 * 9)
        source = (ROOT / 'infra/service/tower_infra/port.py').read_text(encoding='utf-8')
        self.assertIn("{'limit': RELOAD_ROWS})", source)


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements: the order, the claim, what the tasks say, the canaries through the service's dispatch tick and
    the runner's TAKE, and the order's end with deploy.live_code. The gates' clock is injected; the log's is the database's."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db, self.port = self.world.db, self.world.port
        self.port('PUT', '/v1/queues/checks', 'torre', {'policy': 'rank'})
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                     "('push-1', null, 'forge.repository.pushed', clock_timestamp(), 'ingress', 'repository', %(payload)s::jsonb)",
                     {'payload': json.dumps({'delivery': {'event': {'payload': {'refUpdates': [
                         {'ref': 'refs/heads/mod/roadmap-integration', 'after': MERGE}]}}}})})
        self.workflows, self.published, self.clock = workflows_with([]), [], failover.Clock()
        self.bundle, self.away, self.pending = reload.Bundle(), Away(), []
        self.watcher = autodeploy.AutoDeploy(live_image.kept(self.db), {}.get, lambda _: {}, clock=time.time)
        self.watcher.alert, self.watcher.landed_at[MERGE] = self.published.append, time.time() - 0.5
        self.service, self.runner = self.task('service'), self.task('runner')

    def task(self, role, digest=ECS, by=None):
        """An ECS task of the role on the test's database: its gate, its look at the order, and its work (the runner's
        slot; the service's canaries)."""
        found = mock.Mock()
        found.gate = live_image.Gate(live_image.kept(self.db), role, digest, task=f'ecs-{role}', clock=self.clock, reloaded=by)
        found.gate.refresh()
        found.order = live_image.Order(found.gate, COMMANDS[role], pending=(lambda: self.pending) if role == 'service' else None,
                                       hold=role == 'runner', stage=self.bundle.stage, execute=self.bundle.execute,
                                       afresh=self.away)
        found.slot = runner.Runner(self.db, self.world.fetch, self.world.prepare, self.world.upload, self.world.workdir,
                                   name=f'ecs-{role}', gate=found.gate, order=found.order)
        found.live = canary.Live(found.gate, live_image.kept(self.db), publish=self.published.append)
        return found

    def look(self, task):
        """The task's look at the order, one pass later; what the exec was asked when it replaced the process."""
        self.clock.now += 1
        before = len(self.bundle.execed), len(self.away.went)
        try:
            task.order.step(self.db)
        except reload.Replaced:
            return self.bundle.execed[-1]['said'] if len(self.bundle.execed) > before[0] else self.away.went[-1]
        return None

    def take(self, task):
        """A runner slot's pass: its TAKE and run when the task is not draining (Runner.loop), then its look."""
        with task.gate.engaged(task.slot.name) as free:
            took = task.slot.once() if free else None
        return took, self.look(task)

    def tick(self, task):
        """The service's pass (serve's loop): its look before the tick, the dispatch tick, the reloaded task's record and
        its canaries. Answers what the look's exec was asked, else the runs the tick started."""
        went = self.look(task)
        if went is not None:
            return went

        @contextlib.contextmanager
        def connected():
            yield self.db
        with mock.patch.object(self.workflows, 'connected', connected):
            started = self.workflows.tick('5 minutes')
        task.gate.back()
        task.live.step()
        return started

    def said(self, state=None):
        found = [json.loads(row[0]) for row in self.db.rows(
            f"select payload::text from log.event where type = '{live_image.RELOAD}' order by (payload->>'at')::float8")]
        return [each for each in found if state in (None, each['state'])]

    def states(self):
        return [(each.get('role'), each['state']) for each in self.said()]

    def job(self, role):
        found = self.db.rows(canary.JOB, {'tenant': 'torre', 'key': canary.PREFIX + canary.order_key(MERGE, role)})
        return found[0][0] if found else None

    def live_code(self):
        return self.db.rows(code_bundle.LIVE, {'tenant': 'torre'})

    def ordered(self):
        self.watcher.order(self.db, MERGE, S, KEY, PR_HEAD)

    def runner_reloaded(self):
        """The order, the runner's exec onto the bundle and its first TAKE there; the runner on the bundle."""
        self.ordered()
        claim = self.look(self.runner)
        self.runner = self.task('runner', S, by=claim)
        self.take(self.runner)
        return claim

    def service_reloaded(self):
        """And the runner proven by the service, the service's exec and its first tick on the bundle."""
        self.runner_reloaded()
        self.tick(self.service)  # the runner's canary, fired by the service on the code it has and dispatched by its tick
        self.take(self.runner)  # taken and run on the bundle
        claim = self.tick(self.service)  # proven, and the service's own turn
        self.service = self.task('service', S, by=claim)
        self.tick(self.service)
        return claim

    def test_the_takeover_of_a_swap_is_read_from_the_log_role_by_role_until_it_ends_or_goes_back(self):
        # RING-AT-TAKEOVER: the statement on the real log: the swap, each role's {state: reloaded} after it, what took it back
        def say(kind, payload, ident):
            self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                         "(%(id)s, null, %(type)s, clock_timestamp(), 'test', 'deploy', %(payload)s::jsonb)",
                         {'id': ident, 'type': kind, 'payload': json.dumps(payload)})

        def read(head=MERGE):
            return [(digest, took, back in (True, 't')) for digest, took, back in self.db.rows(autodeploy.TAKEOVER, {'head': head})]
        say(live_image.RELOAD, {'role': 'runner', 'digest': S, 'state': 'reloaded'}, 'r0')  # of an earlier swap of the bundle
        self.assertEqual(read(), [])  # no swap of the head: nothing to wait for
        say(autodeploy.SWAP, {'head': MERGE, 'digest': S, 'swapped': True}, 's1')
        say(autodeploy.SWAP, {'head': LATER, 'digest': S, 'swapped': False, 'why': 'no standby'}, 's2')
        self.assertEqual((read(), read(LATER)), ([(S, '', False)], []))
        say(live_image.RELOAD, {'role': 'service', 'digest': S, 'state': 'yielded'}, 'r1')
        say(live_image.RELOAD, {'role': 'service', 'digest': S, 'state': 'reloaded'}, 'r2')
        say('platform.deploy.image_retired', {'role': 'service', 'digest': S, 'by': 'handover'}, 'h1')
        self.assertEqual(read(), [(S, 'service', False)])
        watcher = autodeploy.AutoDeploy.__new__(autodeploy.AutoDeploy)
        watcher.landed_at, watcher.due_in = {MERGE: time.time() - 30}, None
        self.assertRegex(watcher.taking_over(self.db, MERGE, time.time()), r'^reloading: .* \(so far: service\)')
        say(live_image.RELOAD, {'role': 'runner', 'digest': S, 'state': 'reloaded'}, 'r3')
        self.assertEqual(read(), [(S, 'runner service', False)])
        self.assertIsNone(watcher.taking_over(self.db, MERGE, time.time()))
        say('platform.deploy.image_retired', {'role': 'runner', 'digest': S, 'by': 'canary'}, 'c1')
        self.assertEqual(read(), [(S, 'runner service', True)])

    def test_a_landing_with_no_pair_is_loaded_in_place_by_the_runner_then_the_service_each_proven_by_the_other(self):
        self.ordered()
        [order] = self.said('ordered')
        self.assertEqual({name: order[name] for name in ORDER}, ORDER)
        self.assertGreater(order['landed_s'], 0.5)
        self.assertRegex(self.watcher.reloading(MERGE, time.time()), '^reloading: ')  # the head's ring waits
        self.assertEqual(self.tick(self.service), [])  # the service goes on dispatching: the runner first
        with self.runner.gate.engaged('ecs-runner/1'):  # a run in flight in another slot
            self.assertEqual(self.take(self.runner), (None, None))
            self.assertEqual((self.bundle.staged, self.states()), ([(KEY, S)] * 2, [(None, 'ordered')]))  # both staged, none claimed
            waiting = self.world.job('waits-for-the-drain', 'true')
            self.assertEqual(len(self.tick(self.service)), 1)  # dispatched meanwhile, and not taken: the runner drains
            self.assertEqual(self.take(self.runner), (None, None))
        took, claim = self.take(self.runner)  # the run ended: the claim and the exec
        self.assertIsNone(took)
        self.assertEqual((claim['state'], claim['role'], claim['from'], claim['order'], claim['turn'], claim['key']),
                         ('started', 'runner', ECS, MERGE, f'{MERGE[:12]}.0', KEY))
        self.assertAlmostEqual(claim['wrote_at'], order['at'], delta=0.01)  # the order's time: reload_s counts from it
        self.runner = self.task('runner', S, by=claim)  # the exec: the same task on the bundle
        self.assertFalse(self.runner.order.trusted())  # its health file is not touched until the service says proven
        took, _ = self.take(self.runner)  # its first TAKE: the run that waited for the drain, on the bundle
        self.assertEqual((took['outcome'], self.world.state(waiting)), ('succeeded', 'succeeded'))
        [up] = self.said('reloaded')
        self.assertEqual((up['role'], up['digest'], up['order'], up['task'], up['from']), ('runner', S, MERGE, 'ecs-runner', ECS))
        self.assertGreater(up['reload_s'], up['boot_s'])  # the order to its first work; the claim to it
        # the service sees it up: the runner's canary is fired, and dispatched by the tick of the service on the code it has
        self.assertEqual((len(self.tick(self.service)), self.world.state(self.job('runner'))), (1, 'running'))
        self.assertEqual((self.take(self.runner)[0]['outcome'], self.runner.order.trusted()), ('succeeded', False))
        self.pending.append('a-forge-run')  # a workflow of the service in flight
        self.assertEqual(self.tick(self.service), [])  # proven; the service waits for it and goes on dispatching
        self.assertEqual(self.states()[-1], ('runner', 'proven'))
        self.assertFalse(self.service.gate.reloading)
        del self.pending[:]
        claim = self.tick(self.service)  # nothing in flight before this tick: the claim and the exec
        self.assertEqual((claim['state'], claim['role'], claim['from'], claim['order']), ('started', 'service', ECS, MERGE))
        self.take(self.runner)
        self.assertTrue(self.runner.order.trusted())
        self.service = self.task('service', S, by=claim)
        self.assertEqual(self.tick(self.service), [])  # its first tick on the bundle: recorded, and its own canary fired
        self.assertEqual((self.states()[-1], self.world.state(self.job('service')), self.service.order.trusted()),
                         (('service', 'reloaded'), 'queued', False))
        self.watcher.reloads(self.db, [MERGE])  # the look of the service that started mid-way: not done yet
        self.assertEqual((self.live_code(), self.watcher.reload), ([], MERGE))
        self.assertEqual(len(self.tick(self.service)), 1)
        took, _ = self.take(self.runner)  # the runner runs it, and judges the service by it
        self.assertEqual((took['outcome'], self.states()[-1]), ('succeeded', ('service', 'proven')))
        self.tick(self.service)
        self.assertTrue(self.service.order.trusted())
        self.assertEqual(self.states(), [(None, 'ordered'), ('runner', 'started'), ('runner', 'reloaded'), ('runner', 'proven'),
                                         ('service', 'started'), ('service', 'reloaded'), ('service', 'proven')])
        self.watcher.reloads(self.db, [MERGE])  # both proven: the order's end and the live code
        self.assertEqual((self.live_code(), self.watcher.reload, self.watcher.reloading(MERGE, time.time())),
                         ([(f'{S}@{MERGE}', 'f')], None, None))
        [done] = self.said('done')
        self.assertEqual((done['head'], done['digest'], done['live_code']), (MERGE, S, f'{S}@{MERGE}'))
        self.assertGreater(done['seconds'], 0)
        verdicts = [json.loads(row[0]) for row in self.db.rows(
            "select payload::text from log.event where type = 'platform.deploy.canary' order by occurred_at")]
        self.assertEqual([(each['ok'], each['key'], each['by'], each['digest'], each['head']) for each in verdicts],
                         [(True, f'order:{MERGE}:{role}', 'order', S, MERGE) for role in ('runner', 'service')])
        self.assertEqual(self.published, [])
        for task in (self.runner, self.service):  # settled: a pass sends nothing more
            self.assertIsNone(self.look(task))
            self.assertIsNone(task.order.head)
        work = self.world.job('after-the-reload', 'true')  # and a queued job is dispatched and run on the bundle
        self.assertEqual(len(self.tick(self.service)), 1)
        self.assertEqual((self.take(self.runner)[0]['outcome'], self.world.state(work)), ('succeeded', 'succeeded'))
        self.assertEqual((self.runner.gate.digest, self.service.gate.digest, self.bundle.execed[0]['command'],
                          self.bundle.execed[1]['command'], self.away.went), (S, S, 'run-container', 'serve', []))
        # what deploy.sh's code_live reads in the status: the datum and both roles' reloaded of the bundle
        status = self.port('GET', '/v1/deploy/status', 'torre')
        self.assertEqual(status['live_code'], f'{S}@{MERGE}')
        self.assertEqual(sorted(each['role'] for each in status['image_reload'] if each['state'] == 'reloaded' and each['digest'] == S),
                         ['runner', 'service'])
        [seconds] = medir.from_deploy_status(status)['image_reload_nostandby_s']
        self.assertAlmostEqual(seconds, order['landed_s'] + self.said('reloaded')[-1]['reload_s'], places=3)
        self.watcher.order(self.db, LATER, 'b' * 64, 'k', PR_HEAD)  # settled: the next landing's order goes through
        self.assertEqual((self.watcher.reload, len(self.said('ordered'))), (LATER, 2))

    def test_the_runners_canary_red_sends_it_back_and_the_bundle_is_never_loaded_again(self):
        self.runner_reloaded()
        self.assertEqual(len(self.tick(self.service)), 1)  # the canary of the runner's reload, dispatched
        with mock.patch.object(self.runner.slot, 'fetch', mock.Mock(side_effect=RuntimeError('the bundle breaks the checkout'))):
            took, _ = self.take(self.runner)
        self.assertEqual(took['outcome'], 'failed')
        with self.assertLogs('tower_infra.live_image', 'WARNING'):
            self.assertEqual(self.tick(self.service), [])  # the service, on the code it had, judges: failed
        failed = self.said('failed')[0]
        self.assertEqual((failed['role'], failed['digest'], failed['task'], failed['by'], failed['order']),
                         ('runner', S, 'ecs-runner', 'ecs-service', MERGE))
        self.assertRegex(failed['why'], r'^the canary of its reload is failed after [0-9.]+ s$')
        self.assertEqual((self.tick(self.service), len(self.bundle.execed)), ([], 1))  # the service never loads it
        self.assertFalse(self.runner.order.trusted())
        with self.assertLogs('tower_infra.live_image', 'WARNING'):
            took, went = self.take(self.runner)  # the runner is told: back to the code a task ECS starts would boot
        self.assertEqual(went, ('run-container', {'back': True, 'digest': S, 'order': MERGE, 'task': 'ecs-runner'}))
        self.assertEqual(self.states()[-1], ('runner', 'back'))
        self.runner = self.task('runner')  # the exec afresh: the previous code, and it works
        work = self.world.job('after-the-way-back', 'true')
        self.assertEqual(len(self.tick(self.service)), 1)
        self.assertEqual((self.take(self.runner)[0]['outcome'], self.world.state(work), self.runner.order.trusted()),
                         ('succeeded', 'succeeded', True))
        self.assertEqual(self.live_code(), [])  # the live code was never this bundle
        self.db.rows("insert into work.config_value (tenant_id, key, value, actor, reason) select id, 'deploy.live_code', "
                     "to_jsonb(%(datum)s::text), 'test', 'test' from work.tenant where name = 'torre'", {'datum': f'{S}@{MERGE}'})
        self.assertEqual(self.live_code(), [(f'{S}@{MERGE}', 't')])  # and no task ECS starts would boot it (code_bundle.newer)
        with self.assertLogs('tower_infra.canary', 'WARNING'):
            self.watcher.reloads(self.db, [MERGE])  # the look: the verdict recorded and published once, the ring not held
        self.watcher.reloads(self.db, [MERGE])
        [verdict] = self.published
        self.assertEqual((verdict['ok'], verdict['stage'], verdict['key'], verdict['by']), (False, 'run', f'order:{MERGE}:runner', 'order'))
        self.assertEqual((self.watcher.reload, self.watcher.reloading(MERGE, time.time())), (None, None))  # the slow path
        with self.assertLogs('tower_infra.autodeploy', 'INFO') as logs:
            self.watcher.order(self.db, LATER, S, KEY, PR_HEAD)  # the same bundle again: not ordered
        self.assertIn('not ordered: a reload onto aaaaaaaaaaaa failed', '\n'.join(logs.output))
        self.assertEqual(len(self.said('ordered')), 1)

    def test_the_services_canary_red_sends_both_back_and_the_live_code_stays(self):
        self.service_reloaded()
        job = self.job('service')
        self.assertEqual((self.world.state(job), self.service.order.trusted()), ('queued', False))
        work = self.world.job('waits-for-a-dispatcher', 'true')  # the service on the bundle beats and dispatches nothing
        age = float(self.db.rows("select extract(epoch from clock_timestamp() - uuid_extract_timestamp(%(id)s::uuid))::float8",
                                 {'id': job})[0][0])
        self.port('PUT', f'/v1/config/{canary.LIMIT}', 'torre', {'value': round(age + 0.3, 3), 'reason': 'test'})
        time.sleep(0.5)
        with self.assertLogs('tower_infra.live_image', 'WARNING'):
            self.take(self.runner)  # the runner judges: the service's canary is still open past the limit
        failed = self.said('failed')[0]
        self.assertEqual((failed['role'], failed['digest'], failed['task'], failed['by']), ('service', S, 'ecs-service', 'ecs-runner'))
        self.assertRegex(failed['why'], r'^the canary of its reload is queued after [0-9.]+ s$')
        self.assertEqual(self.live_code(), [])  # nothing said the bundle is the live code: a task ECS starts boots the one before
        with self.assertLogs('tower_infra.live_image', 'WARNING'):
            self.assertEqual(self.look(self.service), ('serve', {'back': True, 'digest': S, 'order': MERGE, 'task': 'ecs-service'}))
            self.assertEqual(self.take(self.runner)[1][0], 'run-container')  # and the runner: the bundle is not to be run
        self.assertEqual([each['role'] for each in self.said('back')], ['service', 'runner'])
        self.service, self.runner = self.task('service'), self.task('runner')  # both afresh, on the code before
        self.assertTrue(self.service.order.trusted())
        with self.assertLogs('tower_infra.canary', 'WARNING'):
            self.watcher.reloads(self.db, [MERGE])  # the look the failure woke: recorded, published, cancelled
        # the service's verdict only: the limit this test shrank is read at each judgement, so on a slow runner the
        # runner's canary, ended well but in more seconds than the shrunk limit, is judged red here too (the gate's red of
        # #523, 11/11: two published)
        [verdict] = [each for each in self.published if each['key'] == f'order:{MERGE}:service']
        self.assertEqual((verdict['ok'], verdict['stage'], verdict['key']), (False, 'dispatch', f'order:{MERGE}:service'))
        self.assertEqual((self.world.state(job), self.watcher.reload), ('cancelled', None))
        self.assertEqual(len(self.tick(self.service)), 1)  # what waited is dispatched and run
        self.assertEqual((self.take(self.runner)[0]['outcome'], self.world.state(work)), ('succeeded', 'succeeded'))

    def test_a_task_that_dies_on_the_bundle_is_failed_by_the_other_role(self):
        self.ordered()
        self.look(self.runner)  # claimed and exec'd; it never records work on the bundle
        self.runner = self.task('runner')  # ECS started the task again: the code before, and the order still there
        self.assertEqual((self.take(self.runner), len(self.bundle.execed)), ((None, None), 1))  # one reload at a time
        with mock.patch.object(live_image, 'RELOAD_LIMIT_S', 0.2):
            time.sleep(0.3)
            with self.assertLogs('tower_infra.live_image', 'WARNING'):
                self.tick(self.service)
        self.assertEqual(self.said('failed')[0]['why'], 'ecs-runner did not come up on it within 0.2 s of its reload')
        self.assertEqual((self.take(self.runner), len(self.bundle.execed), self.runner.gate.reloading), ((None, None), 1, False))

    def test_the_claim_is_refused_under_a_pointer_and_one_order_waits_for_the_other(self):
        self.ordered()
        self.db.rows(autodeploy.SWAP_WRITE, {  # a later landing swapped; this task has not read the pointer yet
            'tenant': 'torre', 'digest': 'b' * 64, 'keys': ','.join(sorted(live_image.KEYS.values())), 'reason': 'test',
            'id': f'{autodeploy.SWAP}:{LATER}', 'landed_at': time.time(), 'payload': json.dumps({'digest': 'b' * 64, 'head': LATER})})
        self.assertIsNone(self.look(self.runner))
        self.assertEqual((self.bundle.execed, self.states(), self.runner.gate.reloading), ([], [(None, 'ordered')], False))
        with self.assertLogs('tower_infra.autodeploy', 'INFO') as logs:
            self.watcher.order(self.db, LATER, 'c' * 64, 'k', PR_HEAD)  # the first order is not settled: this one waits
        self.assertIn(f'the order of {MERGE[:12]} is not settled: this one waits', '\n'.join(logs.output))
        self.assertEqual((self.watcher.waiting[0], len(self.said('ordered'))), (LATER, 1))
        self.watcher.order(self.db, MERGE, S, KEY, PR_HEAD)  # the same landing again: the order it has
        self.assertEqual((self.watcher.reload, len(self.said('ordered'))), (MERGE, 1))


if __name__ == '__main__':
    unittest.main()
