"""IMAGE-PREWARM-A (docs/operations/aws.md 22.9): the live image of each role as data (deploy.live_image_<role>), the
standby of a runner or service whose TOWER_IMAGE_DIGEST is not the pointer's, the swap seen on the tower_config event, and
platform.deploy.image_live {role, digest, swap_s} in GET /v1/deploy/status and in scripts/medir as image_swap_s.

Today's behaviour is pinned first: with no TOWER_IMAGE_DIGEST gate() answers None without a read, and a runner slot with no
gate, or with a gate and no pointer, sends exactly the same statements, waits and beats as before. The hermetic classes use
a fake database and a fake gate; OnPostgres runs the real SQL on a throwaway database (TEST_DATABASE_URL, skipped without).
"""
import contextlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import autodeploy, config_data, live_image, runner  # noqa: E402
import medir  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
QUICK = float('0.05')
OLD, NEW = 'sha256:' + '0' * 64, 'sha256:' + '1' * 64


class Pointer:
    """work.config_value's one row of deploy.live_image_<role>, as the gate reads it; events are what it records."""

    def __init__(self, value=None, version=1):
        self.value, self.version, self.events, self.reads, self.broken = value, version, [], 0, False

    def scope(self):
        table = self

        class Scope:
            def __enter__(self):
                if table.broken:
                    raise RuntimeError('db down')
                return table

            def __exit__(self, *_):
                return False
        return Scope()

    def write(self, value):
        self.value, self.version = value, self.version + 1

    def rows(self, sql, params=None):
        if sql == live_image.READ:
            self.reads += 1
            return [] if self.value is None else [(json.dumps(self.value), self.version, 0.25)]  # 0.25 s after the write
        if sql == live_image.LIVE:
            self.events.append(dict(params))
            return []
        if sql == live_image.BUSY:  # SWAP-TAIL-EVIDENCE: nothing to say here
            return []
        raise AssertionError(sql)


def gate_on(table, digest, role='runner'):
    return live_image.gate(role, digest, table.scope, task='task-1')


class TodaysBehaviour(unittest.TestCase):
    def test_with_no_digest_there_is_no_gate_and_nothing_is_read(self):
        scope = mock.Mock(side_effect=AssertionError('read with no TOWER_IMAGE_DIGEST'))
        for digest in (None, '', '  '):
            self.assertIsNone(live_image.gate('runner', digest, scope))
            self.assertIsNone(live_image.gate('service', digest, scope))
        scope.assert_not_called()

    def test_no_pointer_or_an_empty_one_is_live_for_any_digest(self):
        for value in (None, '', ' '):
            table = Pointer(value)
            found = gate_on(table, NEW)
            self.assertTrue(found.active(), value)
            self.assertFalse(found.retired)
            self.assertTrue(found.wait(0))  # a live gate never blocks
            self.assertEqual(table.events, [])

    def slot(self, db, gate):
        """A slot over a fake database that answers nothing to take; two idle passes, then stop."""
        stop, waited, beats = threading.Event(), [], []

        def wait(timeout_s):
            waited.append(timeout_s)
            if len(waited) == 2:
                stop.set()
        slot = runner.Runner(db, None, None, None, tempfile.gettempdir(), beat=lambda: beats.append(1), wait=wait,
                             gate=gate)
        slot.loop(stop, poll_s=QUICK)
        return waited, len(beats)

    def test_a_slot_with_no_gate_or_no_pointer_sends_the_same_statements_waits_and_beats(self):
        def fake():
            sent = []
            db = mock.Mock()
            db.rows.side_effect = lambda sql, params=None: sent.append(sql) or []
            return db, sent
        before, sent_before = fake()
        without = self.slot(before, None)
        after, sent_after = fake()
        with_gate = self.slot(after, gate_on(Pointer(None), NEW))
        self.assertEqual((without, with_gate), (([QUICK, QUICK], 2), ([QUICK, QUICK], 2)))
        self.assertEqual(sent_before, [runner.TAKE, runner.TAKE])
        self.assertEqual(sent_after, sent_before)

    def test_the_autodeploy_looks_on_every_wake_with_no_gate(self):
        watcher = mock.Mock(check_every_s=1, safety_s=lambda: 1)
        stop, looked = threading.Event(), []
        watcher.step.side_effect = lambda force: looked.append(force) or stop.set()
        with mock.patch.object(autodeploy, 'from_boto3', return_value=watcher):
            autodeploy.start(None, stop, wait=lambda _: None, config=None).join(5)
        self.assertEqual(looked, [True])

    def test_the_empty_pointer_is_a_valid_value_only_for_the_live_image_keys(self):
        self.assertEqual(config_data.SPEC['deploy.live_image_service'], (str, ''))
        self.assertEqual(config_data.SPEC['deploy.live_image_runner'], (str, ''))
        self.assertEqual(config_data.validate('deploy.live_image_runner', ''), '')
        self.assertEqual(config_data.validate('deploy.live_image_service', NEW), NEW)
        for name, bad in (('deploy.live_image_runner', 7), ('deploy.base_branch', '')):
            with self.assertRaises(ValueError):
                config_data.validate(name, bad)


class TheGate(unittest.TestCase):
    def test_only_the_pointers_digest_is_live_and_several_standbys_may_wait(self):
        table = Pointer(OLD)
        live, first, second = gate_on(table, OLD), gate_on(table, NEW), gate_on(table, 'sha256:' + '2' * 64)
        self.assertEqual([each.active() for each in (live, first, second)], [True, False, False])
        self.assertFalse(first.wait(0))  # a standby's wait blocks until its image turns live
        self.assertEqual(table.events, [])  # starting live or standing by is no swap

    def test_the_standby_the_pointer_names_turns_live_at_once_and_records_the_swap(self):
        table = Pointer(OLD, version=4)
        standby = gate_on(table, NEW)
        woke = []
        waiter = threading.Thread(target=lambda: woke.append(standby.wait(5)), daemon=True)
        waiter.start()
        table.write(NEW)
        started = time.monotonic()
        self.assertTrue(standby.refresh())  # what the tower_config event runs
        waiter.join(5)
        self.assertEqual(woke, [True])
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(table.events, [])  # IMAGE-SWAP-TIGHTEN: recorded once the role has taken work, not on the read
        standby.clock = lambda: started + 0.1  # the first TAKE, 0.1 s after the read on this process's clock
        standby.working()
        self.assertEqual(table.events, [{'id': f'platform.deploy.image_live:runner:{NEW}:5', 'producer': 'tower-runner',
                                         'role': 'runner', 'digest': NEW, 'task': 'task-1', 'tenant': 'torre',
                                         'key': 'deploy.live_image_runner', 'version': 5, 'parts': table.events[0]['parts']}])
        self.assertEqual(json.loads(table.events[0]['parts'])['notify_s'], 0.25)
        standby.refresh()
        standby.working()
        self.assertEqual(len(table.events), 1)  # the same version is one swap

    def test_the_image_the_pointer_leaves_is_retired(self):
        table = Pointer(None)
        live = gate_on(table, OLD, role='service')  # live with no pointer: the first swap retires today's task too
        table.write(NEW)
        self.assertFalse(live.refresh())
        self.assertTrue(live.retired)
        self.assertFalse(live.active())
        self.assertEqual(table.events, [])

    def test_a_failed_or_invalid_read_keeps_the_state_and_a_failed_first_read_stands_by(self):
        table = Pointer(OLD)
        live = gate_on(table, OLD)
        table.broken = True
        self.assertTrue(live.refresh())
        table.broken, table.value = False, 42  # not a string: config.invalid, the last pointer stays
        self.assertTrue(live.refresh())
        self.assertEqual(live.pointer, OLD)
        cold = Pointer(OLD)
        cold.broken = True
        unknown = gate_on(cold, OLD)
        self.assertFalse(unknown.active())  # never works on a guess
        cold.broken = False
        self.assertTrue(unknown.active())  # read again at the next pass


class FakeGate:
    def __init__(self, live=False, strict=False):
        self.live, self.retired, self.turned = live, False, threading.Event()
        self.strict = strict  # IMAGE-SWAP-FAILOVER: only a promoted standby (strict) the pointer leaves ends its slots

    def beat(self, db):  # IMAGE-SWAP-TIGHTEN: the standby pass's round trip
        db.rows(live_image.BEAT, {})

    def working(self, **parts):  # IMAGE-SWAP-SERVICE-READY: the runner passes take_s
        pass

    def live_beat(self, db=None):  # IMAGE-SWAP-FAILOVER: no pointer names this fake, so no live beat
        return False

    def back(self, db=None):  # IMAGE-SWAP-RELOAD: this fake did not reload itself: nothing to record or hand over
        pass

    def engaged(self, name):  # IMAGE-SWAP-RELOAD: no reload holds this fake: a slot's pass always starts
        return contextlib.nullcontext(True)

    def clock(self):
        return time.monotonic()

    def active(self):
        return self.live

    def wait(self, timeout_s):
        return self.turned.wait(timeout_s)


class TheRunner(unittest.TestCase):
    def test_a_standby_slot_claims_nothing_beats_and_takes_runs_once_live(self):
        sent, beats, stop, gate = [], [], threading.Event(), FakeGate()
        db = mock.Mock()
        db.rows.side_effect = lambda sql, params=None: sent.append(sql) or []

        def wait(timeout_s):
            if timeout_s:  # IMAGE-SWAP-TICK: a standby pass drains the slot's wake (0), which is no idle pass
                stop.set()  # the first idle pass after turning live ends the test
        slot = runner.Runner(db, None, None, None, tempfile.gettempdir(), beat=lambda: beats.append(1), wait=wait, gate=gate)
        thread = threading.Thread(target=slot.loop, args=(stop, QUICK), daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while len(beats) < 3 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertNotIn(runner.TAKE, sent)
        self.assertEqual(set(sent), {live_image.BEAT})  # IMAGE-SWAP-TIGHTEN: the beat is the pass's round trip
        gate.live = True
        gate.turned.set()
        thread.join(5)
        self.assertEqual(sent[-1], runner.TAKE)

    def test_a_standby_that_cannot_reach_the_database_does_not_beat(self):
        stop, beats, gate = threading.Event(), [], FakeGate()
        db = mock.Mock()
        db.rows.side_effect = RuntimeError('db down')
        gate.wait = lambda timeout_s: stop.set()
        runner.Runner(db, None, None, None, tempfile.gettempdir(), beat=lambda: beats.append(1), gate=gate).loop(stop, QUICK)
        self.assertEqual(beats, [])

    def test_a_retired_slot_ends_without_a_stop(self):
        gate = FakeGate(strict=True)  # a promoted standby the pointer left
        gate.retired = True
        db = mock.Mock()
        runner.Runner(db, None, None, None, tempfile.gettempdir(), gate=gate).loop(threading.Event(), QUICK)
        db.rows.assert_not_called()

    def test_an_ecs_task_the_pointer_leaves_stays_standing_by(self):
        # IMAGE-SWAP-FAILOVER: it used to exit and be replaced by a task that stood by; now it is there to take the role back
        sent, stop, gate = [], threading.Event(), FakeGate()
        gate.retired = True
        db = mock.Mock()
        db.rows.side_effect = lambda sql, params=None: sent.append(sql) or []
        gate.wait = lambda timeout_s: len(sent) >= 2 and stop.set()
        runner.Runner(db, None, None, None, tempfile.gettempdir(), gate=gate).loop(stop, QUICK)
        self.assertEqual(sent, [live_image.BEAT, live_image.BEAT])


class TheWiring(unittest.TestCase):
    main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')

    def body(self, name):
        start = self.main.index(f'def {name}(')
        return self.main[start:self.main.index('\ndef ', start + 1)]

    def test_the_service_gates_the_dispatcher_the_autodeploy_and_the_migrations_only_with_a_digest(self):
        serve = self.body('serve')
        self.assertIn("live_image.gate('service', os.environ.get('TOWER_IMAGE_DIGEST')", serve)
        self.assertIn('if gate is None or gate.live is not False:', serve)  # no gate: migrate as before
        self.assertIn('config_data.listen(gate, stop, hub.wake(wake.CONFIG).wait)', serve)  # on tower_config, not a poll
        self.assertIn('active=None if gate is None else gate.after_work(gate.active))', serve)
        loop = serve[serve.index('while not stop.is_set():'):]
        self.assertLess(loop.index('if gate is not None and not gate.active():'), loop.index('workflows.tick(lease, '))
        self.assertIn('touch_health(engine)', loop[:loop.index('workflows.tick(lease, ')])  # a standby stays healthy

    def test_the_runner_reads_its_gate_on_one_kept_connection_and_listens_for_the_swap(self):
        body = self.body('run_container')
        self.assertIn("live_image.gate('runner', os.environ.get('TOWER_IMAGE_DIGEST')", body)
        self.assertIn("live_image.kept(container.Reconnecting(lambda: kept('gate'), database.Database))", body)
        self.assertIn('gate=gate))', body)
        self.assertIn('config_data.listen(gate, stop, hub.wake(wake.CONFIG).wait)', body)  # DB-LISTEN-ONE: on the task's hub
        self.assertLess(body.index('config_data.listen(gate'), body.index('runner.serve_all(workers'))

    def test_the_autodeploy_of_a_standby_never_looks(self):
        watcher = mock.Mock(check_every_s=1, safety_s=lambda: 1)
        stop, waits = threading.Event(), []

        def wait(_):
            waits.append(1)
            if len(waits) == 3:
                stop.set()
        with mock.patch.object(autodeploy, 'from_boto3', return_value=watcher):
            autodeploy.start(None, stop, wait=wait, config=None, active=lambda: False).join(5)
        watcher.step.assert_not_called()


class TheStandbyOfThePrewarm(unittest.TestCase):
    """IMAGE-PREWARM-B2: a standby the prewarm starts (TOWER_STANDBY=1) works only once the pointer names its digest; no
    pointer is not live for it, or a head's standby would take the role's work with an authoring branch's code. DBOS is
    launched (its system-schema migrations, the version registration, the recovery) only when the service turns live."""

    def test_a_strict_gate_stands_by_with_no_pointer_and_turns_live_only_on_its_digest(self):
        table = Pointer()
        for value in (None, '', OLD):
            table.value = value
            found = live_image.gate('runner', NEW, table.scope, task='t', strict=True)
            self.assertEqual((found.live, found.active(), found.turned.is_set()), (False, False, False), value)
        table.write(NEW)
        self.assertTrue(found.refresh())
        found.working()
        self.assertEqual(table.events[-1]['digest'], NEW)  # the swap is timed as for any standby
        self.assertTrue(live_image.gate('runner', NEW, Pointer('').scope).live)  # not strict: today's behaviour

    def test_dbos_is_launched_once_and_only_when_the_standby_turns_live(self):
        table, launched = Pointer(OLD), []
        standby = live_image.gate('service', NEW, table.scope, task='t', strict=True)
        launch = live_image.OnceLive(lambda: launched.append(1), standby)
        self.assertEqual((launch(), launch(), launched), (False, False, []))
        table.write(NEW)
        standby.refresh()
        self.assertEqual((launch(), launch(), launched), (True, True, [1]))
        at_once = live_image.OnceLive(lambda: launched.append(2), None)  # no TOWER_IMAGE_DIGEST: launched at once
        self.assertEqual((at_once(), launched), (True, [1, 2]))

    def test_a_launch_that_raises_is_tried_again(self):
        calls = []

        def start():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError('database down')
        launch = live_image.OnceLive(start, None)
        with self.assertRaises(RuntimeError):
            launch()
        self.assertEqual((launch(), launch(), len(calls)), (True, True, 2))

    def test_serve_launches_through_the_gate_before_any_tick_and_both_roles_read_the_standby_flag(self):
        main = TheWiring.main
        serve = main[main.index('def serve('):main.index('\ndef ', main.index('def serve(') + 1)]
        self.assertEqual(serve.count('DBOS.launch()'), 1)
        self.assertIn('launch = live_image.OnceLive(lambda: DBOS.launch(), None if ready else gate)', serve)
        loop = serve[serve.index('while not stop.is_set():'):]
        self.assertLess(loop.index('launch()'), loop.index('workflows.tick(lease, '))
        self.assertLess(loop.index('if gate is not None and not gate.active():'), loop.index('launch()'))
        self.assertEqual(main.count('strict=bool(os.environ.get(live_image.STANDBY))'), 2)


class TheMeasure(unittest.TestCase):
    def test_the_swaps_of_the_status_become_image_swap_s(self):
        status = {'image_live': [{'role': 'runner', 'digest': NEW, 'swap_s': 0.042}, {'role': 'service', 'swap_s': 1},
                                 {'role': 'runner', 'swap_s': None}, {'swap_s': True}, 'junk']}
        self.assertEqual(medir.from_deploy_status(status), {'image_swap_s': [0.042, 1.0]})
        self.assertNotIn('image_swap_s', medir.from_deploy_status({'image_live': []}))


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real SQL: the pointer written through PUT /v1/config, the trigger's NOTIFY, the standby that turns live, the
    event timed on the database clock, the status that serves it, and a live runner retired with its run finished."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db

    def put(self, role, value):
        return self.world.port('PUT', f'/v1/config/deploy.live_image_{role}', 'torre', {'value': value, 'reason': 'test'})

    def scope(self):
        return live_image.kept(self.db)

    def slot(self, digest):
        return runner.Runner(self.db, self.world.fetch, self.world.prepare, self.world.upload, self.world.workdir,
                             name=f'runner-{digest[-1]}', renew_every_s=QUICK,
                             gate=live_image.gate('runner', digest, self.scope(), task=f'task-{digest[-1]}'))

    def test_a_pointer_write_notifies_tower_config(self):
        import re
        tenant = self.db.rows("select id::text from work.tenant where name = 'torre'")[0][0]
        said = self.db.call(['-A', '-t', '-f', '-'], script=(
            "listen tower_config;\ninsert into work.config_value (tenant_id, key, value, actor, reason) values "
            f"('{tenant}', 'deploy.live_image_runner', '\"{NEW}\"', 'test', 'test');\nselect 1;\n"))
        self.assertIn(('tower_config', 'deploy.live_image_runner'),
                      re.findall(r'Asynchronous notification "(\w+)" with payload "([^"]+)"', said))

    def test_the_standby_takes_the_run_once_the_pointer_names_it_and_the_swap_is_timed(self):
        self.assertEqual(self.put('runner', OLD)['version'], 1)
        standby = self.slot(NEW)
        job = self.world.job('swapped', 'echo swapped')
        from tower_infra import mechanisms
        mechanisms.dispatch(self.db)
        stop = threading.Event()
        thread = threading.Thread(target=standby.loop, args=(stop, QUICK), daemon=True)
        thread.start()
        time.sleep(QUICK * 4)
        self.assertFalse(self.world.running(job))  # handed over, never taken by the standby
        self.assertEqual(self.put('runner', NEW)['version'], 2)
        standby.gate.refresh()  # what the tower_config notification runs (config_data.listen)
        deadline = time.monotonic() + 30
        while self.world.state(job) != 'succeeded' and time.monotonic() < deadline:
            time.sleep(QUICK)
        stop.set()
        thread.join(10)
        self.assertEqual(self.world.state(job), 'succeeded')
        found = self.db.rows("select tenant_id, producer, payload::text from log.event where type = 'platform.deploy.image_live'")
        self.assertEqual(len(found), 1)
        tenant, producer, payload = found[0]
        payload = json.loads(payload)
        self.assertEqual((tenant, producer, payload['role'], payload['digest'], payload['version'], payload['task']),
                         (None, 'tower-runner', 'runner', NEW, 2, 'task-1'))
        self.assertGreaterEqual(payload['swap_s'], 0)
        self.assertLess(payload['swap_s'], 5)
        status = self.world.port('GET', '/v1/deploy/status', 'torre')
        self.assertIsInstance(status['image_live'][0].pop('at'), float)  # STATUS-EVENTS-AT: when the role first worked
        self.assertEqual(status['image_live'], [payload])
        self.assertEqual(medir.from_deploy_status(status)['image_swap_s'], [payload['swap_s']])

    def test_the_live_runner_the_pointer_leaves_finishes_its_run_and_ends(self):
        self.put('runner', OLD)
        live = self.slot(OLD)
        live.gate.strict = True  # a promoted standby; IMAGE-SWAP-FAILOVER: an ECS task stays standing by (below)
        marks = Path(self.world.workdir) / 'started'
        job = self.world.job('in-flight', f'touch {marks}; sleep 0.5')
        from tower_infra import mechanisms
        mechanisms.dispatch(self.db)
        ended = []
        thread = threading.Thread(target=lambda: ended.append(live.loop(threading.Event(), QUICK)), daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not marks.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.put('runner', NEW)
        live.gate.refresh()
        thread.join(30)
        self.assertEqual((ended, self.world.state(job), live.gate.retired), ([None], 'succeeded', True))

    def test_the_ecs_runner_the_pointer_leaves_finishes_its_run_and_stands_by(self):
        live = self.slot(OLD)  # not strict, no pointer: an ECS task, live
        marks = Path(self.world.workdir) / 'started'
        job = self.world.job('in-flight', f'touch {marks}; sleep 0.5')
        from tower_infra import mechanisms
        mechanisms.dispatch(self.db)
        stop = threading.Event()
        thread = threading.Thread(target=live.loop, args=(stop, QUICK), daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not marks.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.put('runner', NEW)
        live.gate.refresh()
        while self.world.state(job) != 'succeeded' and time.monotonic() < deadline:
            time.sleep(QUICK)
        later = self.world.job('later', 'true')
        mechanisms.dispatch(self.db)
        time.sleep(QUICK * 6)
        self.assertTrue(thread.is_alive())  # IMAGE-SWAP-FAILOVER: still up, standing by
        self.assertEqual((self.world.state(job), self.world.running(later)), ('succeeded', []))  # and taking nothing
        self.assertEqual(self.db.rows("select task from work.standby_beat"), [('task-0',)])
        stop.set()
        thread.join(10)


if __name__ == '__main__':
    unittest.main()
