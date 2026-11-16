"""SPOT-KEEP (tower_infra.runner.keep; docs/operations/aws.md 22.9): at Spot's warning the runner's task keeps taking
runs until the task ECS starts in its place is up.

The loss the in-task successor and the reserve cannot cover is the whole task's: Spot interrupted the runner's task
at 17:28 and at 19:27 UTC on 12/11 and the role had no runner for ~144 s and 110.3 s. ECS starts the replacement at
the warning and gives the task its StopTimeout (120 s); the process left within 6 s.

1. The handler, on a clock of its own: the slots are not interrupted at the warning; they are when the replacement is
   up or the limit passed; a second signal is now; the grace of a run in flight counts from the warning.
2. REPLACED on the toolchain's PostgreSQL, migrated: a rollout's new task (up before the stop) is a replacement at
   once; a task of before, or this task's own word, is not.
3. The measure: the status's runner lives, on the real statement, and medir's gap of each Spot interruption, on the
   real events of 19:27 UTC (110.3 s) and on a kept task (0 s).
Local PostgreSQL only, no network.
"""
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from test_infra_mechanisms import World  # noqa: E402
from tower_infra import lifecycle, port, runner  # noqa: E402
import medir  # noqa: E402


class Slot:
    def __init__(self):
        self.termed_at, self.interrupts = None, 0


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds


def started():
    found = []

    def start(target):
        found.append(threading.Thread(target=target, daemon=True))
        found[-1].start()
    return found, start


class TheHandlerKeepsTheSlots(unittest.TestCase):
    def test_the_slots_take_runs_until_the_task_in_its_place_is_up(self):
        clock, slots, asked, said, done = Clock(), [Slot(), Slot()], [], [], threading.Event()
        threads, start = started()
        handler = runner.keep(slots, lambda: done.set(), lambda: asked.append(clock.now) or len(asked) >= 4, 60, clock=clock,
                              start=start, said=lambda kept_s, found: said.append((kept_s, found)), wait=clock.wait)
        self.assertEqual((asked, done.is_set()), ([], False))  # nothing before the warning
        handler(15, None)
        self.assertEqual([each.termed_at for each in slots], [1000.0, 1000.0])  # the grace counts from the warning
        self.assertTrue(done.wait(5))
        self.assertEqual(asked, [1000.0, 1002.0, 1004.0, 1006.0])  # asked every 2 s, until it was up
        self.assertEqual(said, [(6.0, True)])

    def test_the_limit_interrupts_when_no_task_comes_and_a_failed_read_is_no_replacement(self):
        clock, done, said = Clock(), threading.Event(), []
        threads, start = started()
        reads = iter([RuntimeError('the database is away')] + [False] * 100)

        def replaced():
            found = next(reads)
            if isinstance(found, Exception):
                raise found
            return found
        with mock.patch.object(runner.LOG, 'exception'):
            handler = runner.keep([Slot()], done.set, replaced, 60, clock=clock, start=start,
                                  said=lambda kept_s, found: said.append((kept_s, found)), wait=clock.wait)
            handler(15, None)
            self.assertTrue(done.wait(5))
        self.assertEqual(said, [(60.0, False)])  # 60 s at most: what runs then has the 40 s left of the grace

    def test_a_second_signal_interrupts_now(self):
        clock, interrupts = Clock(), []
        handler = runner.keep([Slot()], lambda: interrupts.append(1), lambda: False, 60, clock=clock,
                              start=lambda target: None, wait=clock.wait)
        handler(15, None)
        self.assertEqual(interrupts, [])
        handler(15, None)
        self.assertEqual(interrupts, [1])

    def test_a_run_s_grace_counts_from_the_warning_not_from_the_end_of_the_keeping(self):
        clock = Clock()
        one = runner.Runner(None, None, None, None, '/tmp', clock=clock)
        one.termed_at = 1000.0  # the warning
        clock.now = 1060.0
        one.interrupt()  # the keeping ended
        self.assertEqual(one.termed_at, 1000.0)
        clock.now = 1099.9
        self.assertFalse(one.overdue())
        clock.now = 1100.0
        self.assertTrue(one.overdue())  # 100 s after the warning: before ECS's SIGKILL at 120 s

    def test_the_stop_says_how_long_it_kept_and_whether_it_was_replaced(self):
        written = []
        life = lifecycle.Life.__new__(lifecycle.Life)
        life.ended, life.gate, life.clock, life.since = False, None, lambda: 10.0, 0.0
        life.write = lambda kind, payload: written.append(payload) or True
        from tower_infra import supervisor
        with mock.patch.object(lifecycle, 'NOW', life), mock.patch.object(supervisor, 'memory', lambda: {'task_limit_mb': 512.0}), \
                mock.patch.object(supervisor, 'cgroup', lambda: {'used_mb': 340.5, 'peak_mb': 431.0}):
            lifecycle.note(kept_s=6.0, replaced=True)
            life.stopped()
        # TASK-MEMORY-AT-STOP: and the task's memory then, by its cgroup: its peak since it started (a Spot warning's)
        self.assertEqual(written, [{'up_s': 10.0, 'reason': 'asked', 'error': None, 'kept_s': 6.0, 'replaced': True,
                                    'task_mb': 340.5, 'task_peak_mb': 431.0, 'task_limit_mb': 512.0}])
        with mock.patch.object(supervisor, 'cgroup', mock.Mock(side_effect=OSError('no cgroup'))):
            self.assertEqual(lifecycle.memory(), {})  # never the stop's failure
        with mock.patch.object(supervisor, 'cgroup', lambda: {}), mock.patch.object(supervisor, 'memory', lambda: {}):
            self.assertEqual(lifecycle.memory(), {})  # no cgroup (a local run, a Lambda): nothing

    def test_the_wiring_keeps_the_task_s_process_and_never_a_successor(self):
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        run = source[source.index('def run_container('):source.index('\ndef ', source.index('def run_container(') + 1)]
        self.assertIn("        if gate is not None and gate.strict:\n            return interrupt\n", run)
        self.assertIn('return runner.keep(workers, interrupt, replaced, number(runner.KEEP_S, 60),', run)
        self.assertIn("return db.rows(runner.REPLACED, {'task': name})[0][0] in (True, 't')", run)


UP = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
      "(%(id)s, null, 'platform.deploy.task_up', now() - (%(ago)s || ' seconds')::interval, 'tower-runner', 'deploy/task', "
      "jsonb_build_object('role', %(role)s, 'task', %(task)s))")


class OnPostgres(World):
    def up(self, task, ago, role='runner'):
        self.db.rows(UP, {'id': f'up:{task}:{ago}:{role}', 'ago': str(ago), 'role': role, 'task': task})

    def replaced(self, task='ip-old'):
        return self.db.rows(runner.REPLACED, {'task': task})[0][0] in (True, 't')

    def test_only_a_runner_task_up_after_this_one_is_its_replacement(self):
        self.up('ip-old', 600)
        self.up('ip-before', 900)  # a task of before this one
        self.up('ip-service', 10, role='service')  # another role's
        self.assertFalse(self.replaced())
        self.up('ip-old', 300)  # this task's own word again (a reload)
        self.assertFalse(self.replaced())
        self.up('ip-new', 5)  # the task ECS started in its place (or a rollout's, up before the stop)
        self.assertTrue(self.replaced())
        self.assertFalse(self.replaced('ip-new'))

    def test_the_status_keeps_a_branchs_want_behind_many_newer_successor_events(self):
        # SUCCESSOR-WINDOW: with 20 rows, other bundles' events pushed #707's want out; its delivery did not wait for it
        rows = [{'state': 'wanted', 'branch': 'units/a', 'digest': 'd' * 64}] + [
            {'state': 'up', 'role': 'runner', 'digest': 'e' * 64, 'task': f't{n}'} for n in range(60)]
        for n, payload in enumerate(rows):
            self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                         "(%(id)s, null, 'platform.deploy.successor', now() - (%(ago)s || ' seconds')::interval, 'prewarm', "
                         "'deploy/successor', %(payload)s::jsonb)", {'id': f'successor:{n}', 'ago': str(100 - n),
                                                                     'payload': json.dumps(payload)})
        said = port.deploy_status(self.db, ('installation', None))['successor']
        self.assertEqual(len(said), 61)
        self.assertEqual(said[-1]['branch'], 'units/a')  # the want, the oldest, still there

    def test_the_status_says_the_prune_passes_newest_first(self):
        # LAMBDA-PRUNE-STATUS: the prune look's pass (tenant_id null) is read where the deploy is read; the log's query
        # answers a tenant's events only, so #689's first pass could not be shown
        for at, objects in ((40, 0), (3, 7)):
            self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                         "(%(id)s, null, 'platform.deploy.prune', now() - (%(ago)s || ' seconds')::interval, 'prune', "
                         "'deploy/prune', %(payload)s::jsonb)", {'id': f'platform.deploy.prune:{at}', 'ago': str(at),
                                                                 'payload': json.dumps({'state': 'done', 'objects': objects,
                                                                                        'versions': {'tower-port-api': [1]}})})
        said = port.deploy_status(self.db, ('installation', None))['prune']
        self.assertEqual([(each['state'], each['objects']) for each in said], [('done', 7), ('done', 0)])
        self.assertIsInstance(said[0]['at'], (int, float))

    def test_the_status_says_the_runner_tasks_lives_newest_first(self):
        self.up('ip-old', 600)
        self.up('ip-new', 5)
        tenant = self.db.rows("select id::text from work.tenant where name = 'torre'")[0][0]
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                     "('stopped:ip-old', %(tenant)s::uuid, 'platform.process.stopped', now() - interval '100 seconds', "
                     "'tower-runner', 'process/runner', '{\"mode\": \"task\", \"task\": \"ip-old\", \"reason\": \"asked\"}'), "
                     "('stopped:ip-old:x', %(tenant)s::uuid, 'platform.process.stopped', now() - interval '90 seconds', "
                     "'tower-runner', 'process/runner', '{\"mode\": \"successor\", \"task\": \"ip-old:abc\"}')",
                     {'tenant': tenant})
        self.up('ip-service', 50, role='service')  # VERIFY-AT-UP: the service's own: in task_up, never a runner's life
        status = port.deploy_status(self.db, ('installation', None))
        lives = status['runner_life']
        self.assertEqual([(each['type'], each['task']) for each in lives], [
            ('platform.deploy.task_up', 'ip-new'), ('platform.process.stopped', 'ip-old'), ('platform.deploy.task_up', 'ip-old')])
        self.assertEqual([(each['role'], each['task']) for each in status['task_up']],
                         [('runner', 'ip-new'), ('service', 'ip-service'), ('runner', 'ip-old')])


# the real events of the Spot interruption of 12/11 19:27 UTC (ECS's, and the runner's own; the new task said its start
# 0.4 s after its task_up, which the tenant's log does not show)
STOP = {'type': 'platform.ecs.task_stopped', 'group': 'service:tower-runner', 'stop_code': 'SpotInterruption',
        'stopping_at': '2026-11-12T19:27:35.744Z', 'stopped_at': '2026-11-12T19:28:22.507Z', 'at': 1794511703.0}
OLD = {'type': 'platform.process.stopped', 'mode': 'task', 'task': 'ip-10-40-23-2.example.internal', 'at': 1794511661.527}
NEW = {'type': 'platform.deploy.task_up', 'role': 'runner', 'task': 'ip-10-40-18-16.example.internal', 'at': 1794511771.874}


class TheMeasure(unittest.TestCase):
    def test_the_role_with_no_runner_at_the_interruption_of_19_27(self):
        self.assertEqual(medir.runner_task_loss_gap({'ecs': [STOP], 'runner_life': [NEW, OLD]}), [110.347])

    def test_a_task_kept_until_its_replacement_was_up_had_no_gap(self):
        kept = {**OLD, 'at': NEW['at'] + 1.5, 'kept_s': 97.6, 'replaced': True}
        self.assertEqual(medir.runner_task_loss_gap({'ecs': [STOP], 'runner_life': [kept, NEW]}), [0.0])

    def test_an_interruption_with_no_replacement_yet_or_a_rollout_s_stop_is_left_out(self):
        self.assertEqual(medir.runner_task_loss_gap({'ecs': [STOP], 'runner_life': [OLD]}), [])
        rollout = {**STOP, 'stop_code': 'ServiceSchedulerInitiated'}
        self.assertEqual(medir.runner_task_loss_gap({'ecs': [rollout], 'runner_life': [NEW, OLD]}), [])
        service = {**STOP, 'group': 'service:tower-service'}
        self.assertEqual(medir.runner_task_loss_gap({'ecs': [service], 'runner_life': [NEW, OLD]}), [])
        self.assertEqual(medir.runner_task_loss_gap({}), [])


if __name__ == '__main__':
    unittest.main()
