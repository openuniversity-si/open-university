"""FAST-PATH-RELOAD (GATE-SHUTDOWN, D-314; the Torre accepted PR #23's design, 14/11): a code-only merge's deploy build asks
the live service to load the head's bundle in place, and the service alone obeys and proves it.

1. The ask: deploy.sh names the bundle in last-build.reload {key, sha256, head} while the build is in progress; the
   autodeploy look orders the service alone (roles ['service'], by: build), once, only the build's own head and bundle; an
   order it cannot make is said {state: declined} so the build goes on to the image at once.
2. The look hears the build start: the port records CodeBuild's IN_PROGRESS as platform.deploy.started and wakes it; while
   that build may still ask, its safety look is ASK_LOOK_S.
3. The service obeys by exec (no runner to wait for, no in-task successor, no canary nobody takes), proves itself by its
   own good ticks (PROVE_TICKS over PROVE_S after it said reloaded), is not trusted (its health file) until then, and past
   PROVE_LIMIT_S says failed and goes back; a task ECS started again judges a claim that never came up failed.
4. Proven, the look ends the order with one role and writes deploy.live_code for the build's head.
Hermetic: the look on IMAGE-PREWARM-C's fake database, the tasks on RELOAD-WITHOUT-STANDBY's log by statement.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import canary, live_image  # noqa: E402
import test_infra_reload_nostandby as nostandby  # noqa: E402

S, ECS, KEY, MERGE = nostandby.S, nostandby.ECS, nostandby.KEY, nostandby.MERGE
ALONE = {**nostandby.ORDER, 'pr_head': None, 'roles': ['service'], 'by': 'build', 'build': 'tower-infra-deploy:b1'}


def claim(task='ecs-service', at=100.0):
    """What the service's claim of an order of its role alone says (the exec hands it to the reloaded process); at: the
    log's clock (it starts at 100)."""
    return {'role': 'service', 'digest': S, 'task': task, 'state': 'started', 'order': MERGE, 'turn': f'{MERGE[:12]}.0',
            'roles': ['service'], 'at': at}


class TheServiceAlone(unittest.TestCase):
    def setUp(self):
        self.log = nostandby.Log()
        self.log.order = dict(ALONE)

    def test_the_order_names_its_roles_and_one_without_the_runner_is_obeyed_by_exec(self):
        self.assertEqual(live_image.order_roles(ALONE), ('service',))
        self.assertEqual(live_image.order_roles(nostandby.ORDER), live_image.ROLES)  # a landing's order: both, as before
        self.assertEqual(live_image.order_roles({'roles': ['nobody']}), live_image.ROLES)
        self.assertTrue(live_image.by_exec(ALONE))
        self.assertFalse(live_image.by_exec(nostandby.ORDER))
        self.assertFalse(live_image.Order.held({**ALONE, 'age_s': 1.0, 'refused': False, 'events': []}))  # no successor holds it

    def test_the_service_does_not_wait_for_a_runner_and_its_claim_says_the_roles(self):
        task = nostandby.Task(self.log, 'service')
        went = task.step()
        self.assertEqual((went['command'], went['key'], went['sha']), ('serve', KEY, S))
        said = went['said']
        self.assertEqual((said['state'], said['role'], said['order'], said['roles']), ('started', 'service', MERGE, ['service']))
        self.assertEqual(task.fired, [])  # nobody's canary is fired: no runner takes one
        runner = nostandby.Task(nostandby.Log(), 'runner')
        runner.log.order = dict(ALONE)
        self.assertIsNone(runner.step())  # an order of the service alone is not the runner's
        self.assertEqual(runner.bundle.staged, [])

    def test_an_intask_task_still_obeys_an_order_of_the_service_alone_by_exec(self):
        task = nostandby.Task(self.log, 'service')
        order = live_image.ordered(self.log.rows(live_image.ORDER_OF, {'tenant': 'torre', 'head': ''}))
        with self.assertRaises(nostandby.reload.Replaced):
            task.order.follow(order, None, intask=True)
        self.assertEqual(self.log.states(), ['started'])

    def test_the_reloaded_service_proves_itself_by_its_good_ticks_and_only_then_is_trusted(self):
        self.log.told += [claim(), {**claim(), 'state': 'reloaded'}]
        task = nostandby.Task(self.log, 'service', S, by=claim())
        self.assertFalse(task.order.trusted())  # from its start: the health file is not touched
        for _ in range(live_image.PROVE_TICKS):  # five good ticks, a second apart: not the window yet
            task.order.ticked()
            self.assertIsNone(task.step())
        self.assertEqual((self.log.states(), task.order.trusted()), (['started', 'reloaded'], False))
        for _ in range(int(live_image.PROVE_S)):
            task.order.ticked()
            task.step()
        proof = self.log.told[-1]
        self.assertEqual((proof['state'], proof['role'], proof['order'], proof['task'], proof['by_self']),
                         ('proven', 'service', MERGE, 'ecs-service', True))
        self.assertGreaterEqual(proof['window_s'], live_image.PROVE_S)
        self.assertGreaterEqual(proof['ticks'], live_image.PROVE_TICKS)
        self.assertTrue(task.order.trusted())
        self.assertEqual(self.log.states().count('proven'), 1)

    def test_no_proof_within_the_limit_is_failed_and_the_service_goes_back(self):
        self.log.told += [claim(), {**claim(), 'state': 'reloaded'}]
        task = nostandby.Task(self.log, 'service', S, by=claim())
        task.order.ticked()  # one good tick, then none
        self.assertIsNone(task.step(live_image.PROVE_LIMIT_S - 10))
        self.assertNotIn('failed', self.log.states())
        with self.assertLogs('tower_infra.live_image', 'WARNING'):
            self.assertIsNone(task.step(20))  # past the limit: failed, said once
            went = task.step()  # the next look finds the bundle refused: back to the code ECS would boot
        failed = [each for each in self.log.told if each['state'] == 'failed']
        self.assertEqual(len(failed), 1)
        self.assertIn('no proof within 90 s of its claim: 1 good tick(s)', failed[0]['why'])
        self.assertEqual(went, ('serve', {'back': True, 'digest': S, 'order': MERGE, 'task': 'ecs-service'}))
        self.assertFalse(task.order.trusted())

    def test_a_task_ecs_started_again_judges_a_claim_that_never_came_up_and_claims_nothing(self):
        self.log.told += [claim('ecs-old')]  # the reloaded process died on the bundle: ECS started the task again
        task = nostandby.Task(self.log, 'service', name='ecs-new')
        self.assertIsNone(task.step())
        self.assertEqual((self.log.states(), task.bundle.execed), (['started'], []))  # one claim per order of a role alone
        self.assertIsNone(task.step(live_image.RELOAD_LIMIT_S))
        failed = self.log.told[-1]
        self.assertEqual((failed['state'], failed['task']), ('failed', 'ecs-old'))
        self.assertIn('did not come up on it within 120 s', failed['why'])
        self.log.told[-1:] = [{**claim('ecs-old'), 'state': 'reloaded'}]  # it came up and died before its proof
        self.log.refused = False
        self.assertIsNone(task.step())  # its claim is past PROVE_LIMIT_S already
        self.assertIn('did not prove its reload within 90 s', self.log.told[-1]['why'])

    def test_a_service_reloaded_by_an_order_of_its_role_alone_fires_no_canary(self):
        class Gate:
            role, digest, task, strict = 'service', S, 'ecs-service', False
            reloaded = claim()

        self.assertEqual(canary.Live(Gate(), None).due(), (None, None))
        Gate.reloaded = {**claim(), 'roles': ['runner', 'service']}
        self.assertEqual(canary.Live(Gate(), None).due(), (canary.order_key(MERGE, 'service'), 'order'))
        Gate.reloaded = {key: value for key, value in claim().items() if key != 'roles'}  # a claim from before: as before
        self.assertEqual(canary.Live(Gate(), None).due()[1], 'order')


class TheWiring(unittest.TestCase):
    def test_the_services_good_tick_is_counted_after_its_tick(self):
        body = (ROOT / 'infra/service/tower_infra/__main__.py').read_text()
        tick = body.index('started = workflows.tick(lease, **timed)')
        counted = body.index('order.ticked()')
        self.assertLess(tick, counted)
        self.assertLess(counted, body.index('gate.back()  # IMAGE-SWAP-RELOAD', tick))


if __name__ == '__main__':
    unittest.main()
