"""IMAGE-SWAP-SERVICE-READY (docs/operations/aws.md 22.9): both roles ready before the swap, so the swap is only the wake.

Live on 10/11 (#469): landing to pointers 0.095 s, the runner working 0.627 s after the write, the service 8.862 s (DBOS.launch
deferred to the swap, 2.764 s, then ~6.1 s more to the end of its first tick, on the task's 0.25 vCPU).
1. The service: the prewarm's standby (strict) launches DBOS while it stands by (schema verified, not migrated; an executor
   id of its own), so nothing of the launch is on the swap's clock; image_live is timed once the first dispatch is committed,
   before the workflows start (workflows.tick's dispatched hook), with dispatch_s apart; the looks woken with the swap
   (autodeploy, prewarm: Gate.after_work) wait for that first work.
2. The runner: the standby slot wakes on the gate's event (never its poll) and TAKEs at once; take_s is the TAKE's round trip.

Hermetic: fakes with injected clocks and a stand-in for the dbos package (not in the gate); OnPostgres runs the real
statements (TEST_DATABASE_URL).
"""
import contextlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import live_image, mechanisms, runner  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
S, OLD = 'a' * 64, 'f' * 64
MAIN = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
SERVE = MAIN[MAIN.index('def serve('):MAIN.index('\ndef ', MAIN.index('def serve(') + 1)]


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


class Pointer:
    """work.config_value's pointer row, the beats and image_live, by statement."""

    def __init__(self, value=OLD):
        self.value, self.version, self.seen_s, self.sent = value, 1, 0.0, []

    def scope(self):
        return contextlib.nullcontext(self)

    def rows(self, sql, params=None):
        self.sent.append(sql)
        if sql == live_image.READ:
            return [(json.dumps(self.value), self.version, self.seen_s)]
        if sql == live_image.LIVE:
            self.parts = json.loads(params['parts'])
        return []


def workflows_with(started):
    """tower_infra.workflows over a stand-in dbos whose start_workflow appends the run."""
    fake = types.ModuleType('dbos')

    class DBOS:
        step = workflow = staticmethod(lambda: (lambda function: function))
        start_workflow = staticmethod(lambda function, run: started.append(run['run']))
    fake.DBOS, fake.SetWorkflowID = DBOS, lambda ident: contextlib.nullcontext()
    with mock.patch.dict(sys.modules, {'dbos': fake}):
        sys.modules.pop('tower_infra.workflows', None)
        return importlib.import_module('tower_infra.workflows')  # a fresh module per stand-in (patch.dict drops it after)


def turned(table, role, clock, notify_s=0.027):
    """A strict standby's gate on table, turned live by the pointer's write (notify_s after it, database clock)."""
    gate = live_image.Gate(table.scope, role, S, task='t', strict=True, clock=clock)
    gate.refresh()
    table.value, table.version, table.seen_s = S, 2, notify_s
    assert gate.refresh()
    return gate


class TheService(unittest.TestCase):
    def test_a_prewarm_standby_launches_dbos_at_its_start_verifying_under_an_executor_id_of_its_own(self):
        self.assertIn('ready = gate is not None and gate.strict', SERVE)
        self.assertIn("**({'run_migrations': False, 'executor_id': f'standby-{gate.task}'} if ready else {})", SERVE)
        self.assertIn('launch = live_image.OnceLive(lambda: DBOS.launch(), None if ready else gate)', SERVE)
        self.assertLess(SERVE.index('DBOS(config='), SERVE.index('launch = live_image.OnceLive('))
        self.assertLess(SERVE.index('if not launch():'), SERVE.index("LOG.info('serve: up')"))
        # the safety argument reads dbos 3.4.0 (run_migrations=False verifies; executor_id keys the recovery): a bump re-reads it
        requirements = (ROOT / 'infra/service/requirements.txt').read_text(encoding='utf-8')
        self.assertIn('dbos==3.4.0\n', requirements)

    def test_once_live_without_a_gate_runs_at_the_start_so_the_swap_has_no_launch(self):
        clock, launched = Clock(), []

        def start():
            clock.now += 2.764  # the launch live on 10/11, now while standing by
            launched.append(1)
        launch = live_image.OnceLive(start, None, clock=clock)
        self.assertTrue(launch())
        turned(Pointer(), 'service', clock)
        was = launch.done
        launch()
        self.assertEqual((launched, was), ([1], True))  # launched once, before the swap

    def test_the_service_records_at_its_first_dispatch_before_the_workflows_start(self):
        started, order = [], []
        workflows = workflows_with(started)
        clock, table = Clock(), Pointer()
        gate = turned(table, 'service', clock)
        made = [{'run': 'r1', 'cached': False}, {'job': 'j2', 'cached': True}]

        class Db:
            pass

        @contextlib.contextmanager
        def connected():
            yield Db()

        def reap(db):
            clock.now += 0.004

        def dispatch(db, lease, claimed=None):
            clock.now += 0.008  # the claims, committed statement by statement
            order.append('dispatched')
            return made
        clock.now += 0.001  # the main loop's wake on the gate's event
        began = clock()
        with mock.patch.object(workflows, 'connected', connected), mock.patch.object(mechanisms, 'reap', reap), \
                mock.patch.object(mechanisms, 'dispatch', dispatch):
            ran = workflows.tick('5 minutes', clock=clock, dispatched=lambda parts: order.append(
                (gate.working(began=began, launch_s=None, **parts), list(started))))
        self.assertEqual((ran, started), (['r1'], ['r1']))
        self.assertEqual(order[0], 'dispatched')
        parts = {'notify_s': 0.027, 'work_s': 0.013, 'swap_s': 0.04, 'wake_s': 0.001, 'connect_s': 0.0, 'reap_s': 0.004,
                 'dispatch_s': 0.008, 'pass_s': 0.012, 'jobs': 2}  # IMAGE-SWAP-TICK: the pass in parts
        self.assertEqual(order[1], (parts, []))  # recorded before any workflow started
        self.assertEqual(table.parts, parts)
        self.assertIsNone(gate.working())  # once per swap

    def test_the_serve_loop_times_the_dispatch_and_the_looks_wait_for_it(self):
        loop = SERVE[SERVE.index("LOG.info('serve: up')"):]
        self.assertIn("'dispatched': lambda parts: gate.working(", loop)  # IMAGE-SWAP-TICK: the tick times its parts
        self.assertIn('began=began, launch_s=None if launched else launch.seconds, **parts)}', loop)
        self.assertIn('started = workflows.tick(lease, **timed)', loop)
        self.assertLess(loop.index('launch()  # IMAGE-PREWARM-B2'), loop.index('began = time.monotonic()'))
        self.assertIn('active=None if gate is None else gate.after_work(gate.active))', SERVE)  # the autodeploy
        self.assertIn('active=None if gate is None else gate.after_work(gate.sole))', SERVE)  # the prewarm

    def test_a_look_woken_with_the_swap_waits_for_the_first_work_and_no_longer(self):
        table = Pointer()
        gate = live_image.Gate(table.scope, 'service', S, task='t', strict=True)
        gate.refresh()
        look = gate.after_work(gate.active)
        self.assertFalse(look())  # standing by: no wait, no look
        table.value, table.version = S, 2
        gate.refresh()
        seen = []
        thread = threading.Thread(target=lambda: seen.append(look()), daemon=True)
        thread.start()
        thread.join(0.2)
        self.assertEqual(seen, [])  # waiting for the dispatch
        gate.working()
        thread.join(5)
        self.assertEqual(seen, [True])
        began = time.monotonic()
        self.assertTrue(look())  # after the first work: at once
        self.assertLess(time.monotonic() - began, 0.1)
        table.value, table.version = OLD, 3
        gate.refresh()
        table.value, table.version = S, 4
        gate.refresh()  # a second swap that never works: bounded
        with mock.patch.object(live_image, 'FIRST_WORK_S', 0.05):
            self.assertTrue(look())


class TheRunner(unittest.TestCase):
    def test_the_first_take_is_timed_with_its_round_trip_apart(self):
        clock, table = Clock(), Pointer()
        gate = turned(table, 'runner', clock, notify_s=0.027)
        clock.now += 0.002  # the slot's wake on the gate's event

        def rows(sql, params=None):
            if sql == runner.TAKE:
                clock.now += 0.005
                return []
            return table.rows(sql, params)
        slot = runner.Runner(mock.Mock(rows=rows), None, None, None, tempfile.gettempdir(), gate=gate)
        self.assertIsNone(slot.once())
        self.assertEqual(table.parts, {'notify_s': 0.027, 'work_s': 0.007, 'swap_s': 0.034, 'wake_s': 0.002, 'connect_s': 0.0,
                                       'take_s': 0.005})  # IMAGE-SWAP-TICK: the parts of work_s

    def test_the_standby_slot_wakes_on_the_gate_not_on_its_poll(self):
        table, takes, stop = Pointer(), [], threading.Event()
        gate = live_image.Gate(table.scope, 'runner', S, task='t', strict=True)
        gate.refresh()

        def rows(sql, params=None):
            if sql == runner.TAKE:
                takes.append(time.monotonic())
                stop.set()
            if sql == live_image.LIVE:  # SWAP-RECORD-WARM: the record is the slot's connection's
                table.rows(sql, params)
            return []
        slot = runner.Runner(mock.Mock(rows=rows), None, None, None, tempfile.gettempdir(), gate=gate,
                             wait=lambda timeout_s: stop.wait(timeout_s))
        thread = threading.Thread(target=slot.loop, args=(stop, 30.0), daemon=True)  # a poll of 30 s
        thread.start()
        time.sleep(0.1)  # the slot stands by in gate.wait
        self.assertEqual(takes, [])
        table.value, table.version = S, 2
        swapped = time.monotonic()
        gate.refresh()  # what the tower_config notification runs
        thread.join(5)
        self.assertEqual(len(takes), 1)
        self.assertLess(takes[0] - swapped, 0.1)
        self.assertLess(table.parts['work_s'], 0.1)


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements: the pointer written through PUT /v1/config, a standby runner that wakes on the swap with a poll
    it never waits for, and the service's record at its first committed dispatch."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db

    def put(self, role, value):
        return self.world.port('PUT', f'/v1/config/deploy.live_image_{role}', 'torre', {'value': value, 'reason': 'test'})

    def live(self):
        found = self.db.rows("select payload::text from log.event where type = 'platform.deploy.image_live'")
        return [json.loads(each[0]) for each in found]

    def test_the_runner_standby_takes_the_run_on_the_swap_not_on_its_poll(self):
        self.put('runner', OLD)
        gate = live_image.gate('runner', S, live_image.kept(self.db), task='runner-standby', strict=True)
        slot = runner.Runner(self.db, self.world.fetch, self.world.prepare, self.world.upload, self.world.workdir,
                             name='runner-standby', renew_every_s=0.05, gate=gate)
        job = self.world.job('swapped', 'true')
        mechanisms.dispatch(self.db)
        stop = threading.Event()
        thread = threading.Thread(target=slot.loop, args=(stop, 60.0), daemon=True)  # a poll it must never wait for
        thread.start()
        time.sleep(0.3)
        self.assertFalse(self.world.running(job))
        self.put('runner', S)
        swapped = time.monotonic()
        gate.refresh()  # what the tower_config notification runs (config_data.listen)
        deadline = time.monotonic() + 30
        while self.world.state(job) != 'succeeded' and time.monotonic() < deadline:
            time.sleep(0.02)
        stop.set()
        thread.join(5)
        self.assertEqual(self.world.state(job), 'succeeded')
        self.assertLess(time.monotonic() - swapped, 30)
        (payload,) = self.live()
        self.assertEqual((payload['role'], payload['digest'], payload['version']), ('runner', S, 2))
        self.assertLessEqual(payload['take_s'], payload['work_s'])
        self.assertLess(payload['work_s'], 5)  # psql per statement here; never the 60 s poll

    def test_the_service_records_once_its_first_dispatch_is_committed(self):
        started = []
        workflows = workflows_with(started)
        self.put('service', OLD)
        gate = live_image.gate('service', S, live_image.kept(self.db), task='service-standby', strict=True)
        job = self.world.job('dispatched', 'true')
        self.put('service', S)
        self.assertTrue(gate.refresh())
        claimed = []

        @contextlib.contextmanager
        def connected():
            yield self.db

        def dispatched(parts):
            claimed.extend(self.db.rows("select state from work.run where job_id = %(id)s::uuid", {'id': job}))
            gate.working(dispatch_s=0.01)
        with mock.patch.object(workflows, 'connected', connected):
            ran = workflows.tick('5 minutes', dispatched=dispatched)
        self.assertEqual(claimed, [('starting',)])  # the run is claimed (a container run takeable) when it is recorded
        self.assertEqual(ran, started)  # no container adapter: started as before, after the record
        (payload,) = self.live()
        self.assertEqual((payload['role'], payload['digest'], payload['version'], payload['dispatch_s']),
                         ('service', S, 2, 0.01))
        self.assertNotIn('launch_s', payload)  # DBOS was launched while standing by


if __name__ == '__main__':
    unittest.main()
