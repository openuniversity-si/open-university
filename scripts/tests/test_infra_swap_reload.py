"""IMAGE-SWAP-RELOAD (docs/operations/aws.md 22.9): after an image-only swap the role returns to the ECS tasks in seconds.

Since IMAGE-SWAP-FAILOVER a promoted Spot standby that dies never stops the engine, but the role then falls back to the ECS
task's old code, and the promoted pair holds the role for the whole reconciliation (6 to 13 min). Here the ECS task
standing by under a swapped bundle loads it in place and takes the role over by handover:
1. The trigger: no statement in the first second after the task sees the swap; then one bounded read, and a reload only
   of a bundle a platform.deploy.image_swap names, once the promoted standby recorded image_live for this pointer version.
2. The drain: nothing in flight is exec'd over: a runner slot's run and the service's looks are waited for whatever they
   take; the service's DBOS workflows DRAIN_S at most, then named in the event and left to their leases.
3. The claim and the exec: platform.deploy.image_reload {state: started} only while the pointer still names the bundle
   and one task per turn, then the same command on the bundle with TOWER_CODE_KEY/TOWER_CODE_SHA256/TOWER_IMAGE_DIGEST.
4. The takeover: the reloaded task records {state: reloaded, reload_s} at its first work and empties its role's pointer by
   the same compare-and-swap (by: handover), the runner's like the service's; the promoted standby stands by.
5. The guard: a bundle that cannot be loaded, or a task that died on it, is recorded failed and never reloaded again.

Hermetic: a fake table on an injected clock, the real bundle of this checkout from a fake store, execve stubbed;
OnPostgres runs the real statements (TEST_DATABASE_URL).
"""
import contextlib
import json
import os
from pathlib import Path
import subprocess
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
from tower_infra import autodeploy, canary, code_bundle, live_image, mechanisms, prewarm, runner  # noqa: E402
import medir  # noqa: E402
import test_infra_code_bundle as bundle  # noqa: E402
import test_infra_image_swap as image_swap  # noqa: E402
import test_infra_swap_failover as failover  # noqa: E402
from test_infra_swap_ready import workflows_with  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
S, ECS, KEY = failover.S, failover.ECS, f'artifacts/lambda/tower-code/{failover.S}.zip'
QUICK = float('0.05')
MAIN = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
SERVE = MAIN[MAIN.index('def serve('):MAIN.index('\ndef ', MAIN.index('def serve(') + 1)]
RUN = MAIN[MAIN.index('def run_container('):MAIN.index('\ndef ', MAIN.index('def run_container(') + 1)]
NEW = (live_image.RELOAD_OF, live_image.RELOAD_START, live_image.RELOAD_SAY, live_image.ALONE)  # this unit's statements


Replaced = SystemExit  # execve's stand-in: the process is replaced, so nothing after it runs (a slot's thread just ends)


class Bundle:
    """code_bundle.stage and code_bundle.reload by what they were asked: the staging, and the exec that never returns."""

    def __init__(self, error=None, exec_error=None):
        self.staged, self.execed, self.error, self.exec_error = [], [], error, exec_error

    def stage(self, key, sha):
        self.staged.append((key, sha))
        if self.error:
            raise self.error
        return f'/code/{sha[:12]}'

    def execute(self, command, key, sha, directory, said):
        self.execed.append({'command': command, 'key': key, 'sha': sha, 'directory': directory, 'said': said})
        raise self.exec_error or Replaced()


class Table(failover.Table):
    """IMAGE-SWAP-FAILOVER's table (the pointer and the beats of one role on an injected clock) with the log this unit
    reads and writes: the swaps' records, image_live by its id and platform.deploy.image_reload."""

    def __init__(self, value='', clock=None):
        super().__init__(value, clock)
        self.swaps, self.lives, self.reloads, self.ids = {}, set(), [], set()
        self.canary = 'succeeded'  # DEPLOY-CANARY: the state of the swap's canary job (test_infra_canary has the canary itself)

    def swapped(self, digest=S, key=KEY):
        """The landing's swap: its record names the bundle's key, and the pointer is written."""
        self.swaps[digest] = key
        self.write(digest)

    def new(self):
        return [each for each in self.sent if each in NEW]

    def rows(self, sql, params=None):
        if sql not in NEW + (live_image.LIVE,) or self.broken:
            return super().rows(sql, params)
        self.sent.append(sql)
        if sql == live_image.LIVE:
            self.lives.add(params['id'])
            return []
        if sql == live_image.RELOAD_OF:
            mine = [each for each in self.reloads if (each['role'], each['digest']) == (params['role'], params['digest'])]
            return [(self.swaps.get(params['digest']), params['live'] in self.lives, json.dumps(mine) if mine else None,
                     self.clock(), self.canary)]
        if sql == live_image.RELOAD_START:  # the log's primary key: (the pointer's write, the id)
            if (self.value, self.version) != (params['digest'], params['version']) or (self.wrote, params['id']) in self.ids:
                return []
            self.ids.add((self.wrote, params['id']))
            self.reloads.append({**json.loads(params['payload']), 'version': self.version, 'wrote_at': self.wrote,
                                 'at': self.clock()})
            return [(json.dumps(self.reloads[-1]),)]
        if sql == live_image.RELOAD_SAY:
            if params['id'] not in self.ids:
                self.ids.add(params['id'])
                timed = {} if params['wrote_at'] is None else {'reload_s': self.clock() - params['wrote_at'],
                                                               'boot_s': self.clock() - params['started_at']}
                self.reloads.append({**json.loads(params['payload']), 'at': self.clock(), **timed})
            return []
        others = [at for (role, digest, task), at in self.beats.items()  # ALONE: EMPTY, unless another ECS task stands by
                  if (role, digest) == (params['role'], params['was']) and task != params['task']]
        if any(self.clock() - at < live_image.ALONE_S for at in others):
            return []
        found = super().rows(live_image.EMPTY, params)
        self.sent.pop()
        return found


def gate_on(table, role='service', digest=ECS, strict=False, task='ecs', reloaded=None):
    found = live_image.Gate(table.scope, role, digest, task=task, strict=strict, clock=table.clock, reloaded=reloaded)
    found.refresh()
    return found


class Pair:
    """One role after a landing swapped it to S: the promoted standby (strict) and the ECS task standing by with its
    reload, on one table. worked(): the standby's first work, which records image_live."""

    def __init__(self, role='service', command='serve', pending=None, bundle=None, swapped=True):
        self.table, self.role, self.bundle = Table(), role, bundle or Bundle()
        self.promoted, self.ecs = gate_on(self.table, role, S, strict=True, task='promoted'), gate_on(self.table, role)
        self.reload = self.reloader(self.ecs, command, pending)
        if swapped:
            self.table.swapped()
            self.promoted.refresh()
            self.ecs.refresh()

    def reloader(self, gate, command='serve', pending=None, stopping=None):
        return live_image.Reload(gate, command, pending=pending, stopping=stopping, stage=self.bundle.stage,
                                 execute=self.bundle.execute)

    def worked(self):
        self.promoted.working()
        self.promoted.live_beat()

    def passes(self, count=1, seconds=1.0, gate=None, reload=None):
        """Standby passes of the ECS task, `seconds` apart: its beat (the watch), then the reload's look."""
        for _ in range(count):
            self.table.clock.now += seconds
            self.promoted.live_beat()
            (gate or self.ecs).beat()
            (reload or self.reload).step()

    def reloaded(self, task='ecs'):
        """The gate of the process the exec started: the ECS task on S, told what the reload said."""
        said = self.bundle.execed[-1]['said']
        return gate_on(self.table, self.role, said['digest'], task=task, reloaded=said)


class TheTrigger(unittest.TestCase):
    def test_the_swaps_first_second_is_its_own_then_one_read_a_second_until_the_promoted_standby_works(self):
        pair = Pair()
        pair.passes(1, seconds=0.0)  # the pass that sees the swap
        pair.passes(1, seconds=0.5)
        self.assertEqual(pair.table.new(), [])  # no statement of the reload on the swap's clock
        pair.passes(4, seconds=0.5)
        self.assertEqual(pair.table.new(), [live_image.RELOAD_OF] * 2)  # the standby has not worked: a look, RELOAD_ASK_S apart
        self.assertEqual((pair.bundle.staged, pair.bundle.execed), ([], []))
        pair.worked()  # platform.deploy.image_live of this pointer version
        with self.assertRaises(Replaced):
            pair.passes(1)
        self.assertEqual(pair.table.new()[2:], [live_image.RELOAD_OF, live_image.RELOAD_START])
        self.assertEqual(pair.bundle.staged, [(KEY, S)])  # the key of the swap's record
        [done] = pair.bundle.execed
        self.assertEqual((done['command'], done['key'], done['sha'], done['directory']), ('serve', KEY, S, f'/code/{S[:12]}'))
        self.assertEqual(done['said'], {'role': 'service', 'digest': S, 'task': 'ecs', 'state': 'started', 'from': ECS,
                                        'turn': 0, 'key': KEY, 'drain_s': 0.0, 'version': 2, 'wrote_at': 100.0, 'at': 103.5})
        self.assertEqual(pair.table.value, S)  # the reload writes no pointer: the reloaded task hands over
        self.assertEqual(live_image.RELOAD_ASK_S, 1)

    def test_the_image_live_is_this_swaps_by_role_digest_and_pointer_version(self):
        pair = Pair()
        pair.table.lives.add(f'platform.deploy.image_live:service:{S}:1')  # an earlier swap to the same bundle
        pair.table.lives.add(f'platform.deploy.image_live:runner:{S}:2')  # the other role's
        pair.passes(4)
        self.assertEqual(pair.bundle.staged, [])
        pair.table.lives.add(f'platform.deploy.image_live:service:{S}:2')
        with self.assertRaises(Replaced):
            pair.passes(1)

    def test_a_pointer_that_names_no_swapped_bundle_is_read_once_and_never_reloaded(self):
        pair = Pair(swapped=False)
        pair.table.write('failover-probe')  # a PUT by hand (the watchdog's live proof): no platform.deploy.image_swap
        pair.ecs.refresh()
        with self.assertLogs('tower_infra.live_image', 'INFO') as logs:
            pair.passes(5)
        self.assertEqual((pair.table.new(), pair.bundle.staged), ([live_image.RELOAD_OF], []))
        self.assertIn('not a swapped bundle', logs.output[0])

    def test_a_swap_that_is_undone_is_not_chased(self):
        pair = Pair()
        pair.passes(5)  # the standby never says image_live: looks only
        self.assertEqual((set(pair.table.new()), pair.bundle.staged), ({live_image.RELOAD_OF}, []))
        pair.table.write('')  # the autodeploy's revert after SWAP_LIMIT_S (or the watchdog's failover)
        pair.ecs.refresh()
        before = len(pair.table.sent)
        pair.reload.step()
        self.assertEqual((pair.ecs.active(), pair.table.sent[before:]), (True, []))

    def test_without_a_pointer_or_a_digest_and_for_a_strict_standby_the_statements_are_todays(self):
        table = Table()
        ecs = gate_on(table)  # no pointer: the ECS task works
        reload = live_image.Reload(ecs, 'serve')
        for _ in range(3):
            table.clock.now += 1
            reload.step()
            ecs.live_beat()
            ecs.back()
        self.assertEqual(table.sent, [live_image.READ])  # the gate's one read at its start: nothing else, ever
        self.assertIsNone(live_image.gate('service', '', table.scope))  # no TOWER_IMAGE_DIGEST: no gate, so no reload
        self.assertIn('reload = None if gate is None else live_image.Reload(', SERVE)
        self.assertIn('reload = None if gate is None else live_image.Reload(', RUN)
        table.swapped()
        table.lives.add(f'platform.deploy.image_live:service:{S}:2')
        waiting = gate_on(table, digest='c' * 64, strict=True, task='another-head')  # a prewarm standby of another head
        reload = live_image.Reload(waiting, 'serve')
        for _ in range(3):
            table.clock.now += 1
            waiting.beat()
            reload.step()
        self.assertEqual(table.new(), [])
        sharing = gate_on(table, digest=S, task='reconciled')  # the pointer names it: live, nothing to reload
        live_image.Reload(sharing, 'serve').step()
        self.assertEqual(table.new(), [])

    def test_the_standby_pass_keeps_its_one_statement_and_the_look_never_raises(self):
        pair = Pair()
        pair.worked()
        pair.passes(1, seconds=0.0)
        self.assertEqual(pair.table.sent[-1], live_image.WATCH)  # the watchdog's pass is untouched: the look comes after
        pair.table.broken = True
        pair.table.clock.now += 1
        with self.assertLogs('tower_infra.live_image', 'ERROR'):
            pair.reload.step()  # the database is down: logged, and the next pass looks again
        pair.table.broken = False
        with self.assertRaises(Replaced):
            pair.passes(2)


class TheDrain(unittest.TestCase):
    def test_the_service_waits_for_its_pending_workflows_and_reloads_when_they_end(self):
        pending = [['run-1', 'run-2'], ['run-2'], []]
        pair = Pair(pending=lambda: pending.pop(0))
        pair.worked()
        pair.passes(3)  # sees the swap; looks, stages and finds two workflows; then one
        self.assertEqual((pair.bundle.staged, pair.bundle.execed, pair.table.new()), ([(KEY, S)], [], [live_image.RELOAD_OF]))
        with self.assertRaises(Replaced):
            pair.passes(1)
        said = pair.bundle.execed[0]['said']
        self.assertEqual((said['drain_s'], 'stragglers' in said), (2.0, False))
        self.assertEqual(pair.table.new(), [live_image.RELOAD_OF, live_image.RELOAD_START])  # staged once, read once

    def test_a_workflow_still_pending_after_the_bound_is_named_and_left_to_its_lease(self):
        pair = Pair(pending=lambda: ['run-stuck'])
        pair.worked()
        pair.passes(2 + live_image.DRAIN_S - 1)
        self.assertEqual(pair.bundle.execed, [])
        with self.assertLogs('tower_infra.live_image', 'WARNING') as logs, self.assertRaises(Replaced):
            pair.passes(2)
        said = pair.bundle.execed[0]['said']
        self.assertEqual((said['stragglers'], said['drain_s'] >= live_image.DRAIN_S), (['run-stuck'], True))
        self.assertIn("left to their leases: ['run-stuck']", logs.output[0])
        self.assertGreater(live_image.DRAIN_S, 60)  # past the forge adapter's own timeout (TOWER_FORGE_TIMEOUT_S)
        back = pair.reloaded()
        back.back()
        self.assertEqual(pair.table.reloads[-1]['stragglers'], ['run-stuck'])  # and in what the status shows

    def test_work_in_flight_is_never_execed_over_whatever_it_takes(self):
        for name in ('autodeploy', 'prewarm', 'ecs/1'):  # a look of the service; a slot of the runner in a run
            pair = Pair()
            pair.worked()
            with pair.ecs.engaged(name) as free:
                self.assertTrue(free)
                pair.passes(10 * live_image.DRAIN_S, seconds=10)
                self.assertEqual((pair.ecs.busy(), pair.bundle.execed, pair.ecs.reloading), ([name], [], False))
            with self.assertRaises(Replaced):
                pair.passes(1)

    def test_once_the_reload_holds_the_gate_no_work_starts(self):
        seen = []

        def pending():  # asked while the reload holds the gate, right before its claim
            with pair.ecs.engaged('autodeploy') as free:
                seen.append((free, pair.ecs.reloading))
            return []
        pair = Pair(pending=pending)
        pair.worked()
        with self.assertRaises(Replaced):
            pair.passes(3)
        self.assertEqual(seen, [(False, True)])
        with live_image.engaged(None, 'autodeploy') as free:  # no gate (no TOWER_IMAGE_DIGEST): work always starts
            self.assertTrue(free)

    def test_a_task_that_is_being_stopped_does_not_reload(self):
        stopping = [False]
        pair = Pair()
        pair.reload = pair.reloader(pair.ecs, stopping=lambda: stopping[0])
        pair.worked()
        pair.passes(1)
        stopping[0] = True  # SIGTERM: the rollout replaces this task
        pair.passes(3)
        self.assertEqual((pair.table.new(), pair.bundle.staged, pair.bundle.execed), ([], [], []))
        stopping[0] = False  # it was only the stop
        with self.assertRaises(Replaced):
            pair.passes(1)

    def test_the_looks_of_the_service_are_counted_and_none_starts_under_a_reload(self):
        for module, name in ((autodeploy, 'autodeploy'), (prewarm, 'prewarm')):
            table = Table()
            gate, stop, seen = gate_on(table), threading.Event(), []

            class Watcher:
                def step(self, force=False):
                    seen.append(gate.busy())
                    gate.reloading = True  # a reload holds the gate from here
                    return 0

                def forget(self):
                    pass
                safety_s = cap = lambda self: 0
                doorbell = 'doorbell'

            def wait(timeout_s):
                waits.append(timeout_s)
                if len(waits) == 3:
                    stop.set()
            waits = []
            with mock.patch.object(module, 'from_boto3', return_value=Watcher()):
                module.start(None, stop, wait=wait, active=lambda: True, gate=gate).join(5)
            self.assertEqual((seen, len(waits), gate.busy()), ([[name]], 3, []))  # counted; and no look after the hold

    def test_the_runner_takes_no_run_under_a_reload_and_its_pass_is_work_in_flight(self):
        table = Table()
        gate, stop, sent = gate_on(table, 'runner'), threading.Event(), []

        class Db:
            def rows(self, sql, params=None):
                sent.append((sql, gate.busy()))
                stop.set()
                return []
        slot = runner.Runner(Db(), None, None, None, tempfile.gettempdir(), name='ecs/1', gate=gate)
        slot.loop(stop, QUICK)
        self.assertEqual(sent, [(runner.TAKE, ['ecs/1'])])  # counted before its TAKE
        gate.reloading, waits = True, []
        slot.wait = lambda timeout_s: (waits.append(timeout_s), stop.set())
        stop.clear()
        slot.loop(stop, QUICK)
        self.assertEqual((len(sent), waits, gate.busy()), (1, [QUICK], []))  # held: no TAKE, an idle wait


class TheGuard(unittest.TestCase):
    def failed(self, pair):
        return [each for each in pair.table.reloads if each['state'] == 'failed']

    def test_a_bundle_that_cannot_be_loaded_is_tried_once_and_never_again_by_any_task(self):
        for error in (code_bundle.BundleError("the bundle's requirements.txt is not the image's: its code needs a new image"),
                      code_bundle.BundleError(f'{KEY} is not in the store'), OSError('no space left on device')):
            pair = Pair(bundle=Bundle(error=error))
            pair.worked()
            with self.assertLogs('tower_infra.live_image', 'INFO'):
                pair.passes(6)
            self.assertEqual((pair.bundle.staged, pair.bundle.execed), ([(KEY, S)], []))  # nothing was touched
            [event] = self.failed(pair)
            self.assertEqual((event['role'], event['digest'], event['task'], event['why']),
                             ('service', S, 'ecs', f'the bundle cannot be loaded: {error}'))
            self.assertEqual(pair.table.new(), [live_image.RELOAD_OF, live_image.RELOAD_SAY])  # then no look at all
            self.assertEqual((pair.table.value, pair.promoted.active(), pair.ecs.active()), (S, True, False))  # as before
            other = gate_on(pair.table, task='ecs-2')  # another ECS task of the role, or this one started again
            with self.assertLogs('tower_infra.live_image', 'INFO') as logs:
                pair.passes(4, gate=other, reload=pair.reloader(other))
            self.assertEqual(pair.table.new()[2:], [live_image.RELOAD_OF])  # it reads the record, once
            self.assertEqual((len(pair.bundle.staged), len(self.failed(pair))), (1, 1))
            self.assertIn('it is not tried again', logs.output[0])

    def test_a_task_that_died_on_the_bundle_is_recorded_failed_and_the_digest_is_not_reloaded_again(self):
        pair = Pair()
        pair.worked()
        with self.assertRaises(Replaced):
            pair.passes(3)
        # the child exits 3 (or dies): ECS starts the task again on its task definition's code, which stands by under S
        again = gate_on(pair.table, task='ecs-restarted')
        reload = pair.reloader(again)
        pair.passes(live_image.RELOAD_LIMIT_S - 2, gate=again, reload=reload)
        self.assertEqual((self.failed(pair), len(pair.bundle.execed)), ([], 1))  # it may still be coming up: one at a time
        with self.assertLogs('tower_infra.live_image', 'INFO'):
            pair.passes(4, gate=again, reload=reload)
        [event] = self.failed(pair)
        self.assertEqual((event['task'], event['why']), (
            'ecs-restarted', f'ecs did not come up on it within {live_image.RELOAD_LIMIT_S} s of its reload'))
        looks = len(pair.table.new())
        pair.passes(20, gate=again, reload=reload)
        self.assertEqual((len(pair.table.new()), len(pair.bundle.execed), pair.table.value), (looks, 1, S))
        self.assertEqual((pair.promoted.active(), again.active()), (True, False))  # the promoted pair keeps the role

    def test_a_pointer_emptied_before_the_exec_cancels_the_reload(self):
        pending = [['run-1'], []]
        pair = Pair(pending=lambda: pending.pop(0))
        pair.worked()
        pair.passes(2)  # staged, waiting for its workflow
        self.assertEqual((pair.bundle.staged, pending), ([(KEY, S)], [[]]))
        pair.table.write('')  # another task's failover, the standby's handback or the revert; its NOTIFY is not here yet
        pair.table.clock.now += 1
        pair.reload.step()  # the drain is over: the claim compares the pointer again, right before the exec
        self.assertEqual((pair.table.new()[-1], pair.bundle.execed, pair.table.reloads), (live_image.RELOAD_START, [], []))
        self.assertEqual(pair.table.sent[-1], live_image.READ)  # the pointer is read there, not on the notification:
        self.assertTrue(pair.ecs.active())  # not strict, it works at once on its own code, as IMAGE-SWAP-FAILOVER left it
        before = len(pair.table.sent)
        pair.reload.step()
        self.assertEqual(pair.table.sent[before:], [])

    def test_a_pointer_swapped_again_is_a_new_swap(self):
        pair = Pair()
        pair.worked()
        pair.passes(1, seconds=0.0)
        pair.table.swapped('d' * 64, 'artifacts/lambda/tower-code/next.zip')  # the next landing, before the reload
        pair.ecs.refresh()
        pair.passes(3)
        self.assertEqual((pair.bundle.staged, pair.bundle.execed), ([], []))  # its standby has not worked yet
        pair.table.lives.add(f"platform.deploy.image_live:service:{'d' * 64}:3")
        with self.assertRaises(Replaced):
            pair.passes(1)
        self.assertEqual(pair.bundle.execed[0]['key'], 'artifacts/lambda/tower-code/next.zip')

    def test_an_exec_that_fails_is_recorded_and_the_task_goes_on_standing_by(self):
        pair = Pair(bundle=Bundle(exec_error=OSError('exec format error')))
        pair.worked()
        with self.assertLogs('tower_infra.live_image', 'INFO'):
            pair.passes(5)
        self.assertEqual([each['state'] for each in pair.table.reloads], ['started', 'failed'])
        self.assertEqual((len(pair.bundle.execed), pair.ecs.reloading, pair.table.reloads[1]['why']),
                         (1, False, 'the exec failed: exec format error'))

    def test_of_several_ecs_tasks_of_a_role_one_reloads_at_a_time(self):
        pair = Pair('runner', 'run-container')
        second = gate_on(pair.table, 'runner', task='ecs-2')
        held = [[['run-1'], []], [['run-2'], []]]  # each has something in flight when it looks
        reloads = [pair.reloader(gate, 'run-container', lambda left=left: left.pop(0) if left else [])
                   for gate, left in zip((pair.ecs, second), held)]
        pair.worked()
        for seconds in (0.0, 1.0):  # both see the swap; both look, stage and wait, each sure of the first turn
            for gate, reload in zip((pair.ecs, second), reloads):
                pair.passes(1, seconds=seconds, gate=gate, reload=reload)
                seconds = 0.0
        self.assertEqual((len(pair.bundle.staged), pair.table.reloads), (2, []))
        with self.assertRaises(Replaced):
            reloads[0].step()
        reloads[1].step()  # the same turn: the log's primary key lets one insert through
        self.assertEqual([(each['task'], each['turn']) for each in pair.table.reloads], [('ecs', 0)])
        self.assertEqual(len(pair.bundle.execed), 1)
        pair.passes(5, gate=second, reload=reloads[1])  # the first is coming up: the second waits its turn, standing by
        self.assertEqual((len(pair.bundle.execed), second.active()), (1, False))
        first = pair.reloaded()
        first.back()
        self.assertEqual(pair.table.value, S)  # no handover while the second still stands by on the old code
        with self.assertRaises(Replaced):
            pair.passes(2, gate=second, reload=reloads[1])
        self.assertEqual([(each['task'], each['turn'], each['state']) for each in pair.table.reloads],
                         [('ecs', 0, 'started'), ('ecs', 0, 'reloaded'), ('ecs-2', 1, 'started')])

    def test_a_bundle_tasks_keep_dying_on_after_their_first_work_is_not_reloaded_for_ever(self):
        pair = Pair()
        pair.worked()
        for count in range(live_image.RELOAD_TASKS):
            task = gate_on(pair.table, task=f'ecs-{count}')
            with self.assertRaises(Replaced):
                pair.passes(3, gate=task, reload=pair.reloader(task))
            pair.table.reloads.append({**pair.bundle.execed[-1]['said'], 'state': 'reloaded'})  # it worked, then died
        last = gate_on(pair.table, task='ecs-last')
        with self.assertLogs('tower_infra.live_image', 'INFO') as logs:
            pair.passes(5, gate=last, reload=pair.reloader(last))
        self.assertEqual(len(pair.bundle.execed), live_image.RELOAD_TASKS)
        self.assertIn(f'{live_image.RELOAD_TASKS} tasks of the role reloaded it already', logs.output[0])


class TheTakeover(unittest.TestCase):
    def reloaded(self, role='service', command='serve'):
        pair = Pair(role, command)
        pair.worked()
        with self.assertRaises(Replaced):
            pair.passes(3)
        pair.table.clock.now += 4  # the exec, the interpreter, the connections (and the service's DBOS launch)
        return pair, pair.reloaded()

    def test_the_reloaded_task_is_live_at_once_records_its_first_work_and_takes_the_role_over(self):
        for role, command in (('service', 'serve'), ('runner', 'run-container')):
            pair, back = self.reloaded(role, command)
            self.assertEqual((back.active(), back.sharing(), back.sole(), back.strict), (True, True, False, False))
            before = len(pair.table.sent)
            back.live_beat()  # the good tick, or the TAKE
            back.back()
            self.assertEqual(pair.table.sent[before:], [live_image.LIVE_BEAT, live_image.RELOAD_SAY, live_image.ALONE])
            event = pair.table.reloads[-1]
            self.assertEqual({name: event[name] for name in ('role', 'digest', 'task', 'state', 'from', 'turn', 'version',
                                                             'wrote_at', 'reload_s', 'boot_s', 'at')},
                             {'role': role, 'digest': S, 'task': 'ecs', 'state': 'reloaded', 'from': ECS, 'turn': 0,
                              'version': 2, 'wrote_at': 100.0, 'reload_s': 6.0, 'boot_s': 4.0, 'at': 106.0})
            self.assertNotIn('key', event)
            [retired] = pair.table.events  # the same compare-and-swap as every other writer of the pointer
            self.assertEqual(retired, {'role': role, 'digest': S, 'task': 'ecs', 'by': 'handover', 'reloaded': True,
                                       'id': f'platform.deploy.image_retired:{role}:{S}:2'})
            self.assertEqual(pair.table.value, '')
            back.refresh()
            self.assertEqual((back.active(), back.sole(), back.pointed()), (True, True, False))  # the role is the ECS task's
            self.assertEqual((pair.promoted.refresh(), pair.promoted.retired), (False, True))  # the standby stands by
            before = len(pair.table.sent)
            for _ in range(3):
                pair.table.clock.now += 1
                back.live_beat()
                back.back()
            self.assertEqual(pair.table.sent[before:], [])  # under no pointer: today's statements only

    def test_the_handover_waits_while_another_ecs_task_stands_by_on_the_old_code(self):
        pair, back = self.reloaded('runner', 'run-container')
        other = gate_on(pair.table, 'runner', task='ecs-2')  # it would work on the old code under no pointer
        other.beat()
        with self.assertLogs('tower_infra.live_image', 'INFO') as logs:
            back.back()
        self.assertEqual((pair.table.value, pair.table.events), (S, []))
        self.assertIn(f'not yet: the pointer moved, or another ECS task still stands by on {ECS}', logs.output[-1])
        tried = pair.table.count(live_image.ALONE)
        back.back()  # the next pass of a slot: LIVE_BEAT_S apart at most
        self.assertEqual(pair.table.count(live_image.ALONE), tried)
        pair.table.clock.now += live_image.LIVE_BEAT_S
        other.beat()
        back.back()
        self.assertEqual((pair.table.count(live_image.ALONE), pair.table.value), (tried + 1, S))
        pair.table.clock.now += live_image.ALONE_S  # it reloaded in its turn, or the rollout stopped it: no beat of it
        back.back()
        self.assertEqual((pair.table.value, pair.table.events[0]['by']), ('', 'handover'))
        self.assertEqual(len([each for each in pair.table.reloads if each['state'] == 'reloaded']), 1)  # recorded once

    def test_a_standby_of_another_head_never_holds_the_handover(self):
        pair, back = self.reloaded()
        gate_on(pair.table, digest='c' * 64, strict=True, task='another-head').beat()  # the prewarm's, beating
        back.back()
        self.assertEqual(pair.table.value, '')

    def test_a_pointer_emptied_while_the_task_came_up_leaves_it_working_on_the_bundle_with_nothing_to_hand_over(self):
        pair = Pair()
        pair.worked()
        with self.assertRaises(Replaced):
            pair.passes(3)
        pair.table.write('')  # the standby's handback (Spot) while the ECS task execs
        back = pair.reloaded()
        self.assertEqual((back.active(), back.sharing()), (True, False))  # not strict: it works, on S
        back.back()
        self.assertEqual([each['state'] for each in pair.table.reloads], ['started', 'reloaded'])
        self.assertEqual(pair.table.count(live_image.ALONE), 0)

    def test_a_record_that_fails_is_written_on_the_next_pass(self):
        pair, back = self.reloaded()
        pair.table.broken = True
        with self.assertLogs('tower_infra.live_image', 'ERROR'):
            back.back()
        pair.table.broken = False
        back.back()
        self.assertEqual(([each['state'] for each in pair.table.reloads], pair.table.value), (['started', 'reloaded'], ''))

    def test_a_task_born_on_the_bundle_by_the_rollout_hands_over_as_before_and_its_runner_never(self):
        for role in ('service', 'runner'):
            table = Table()
            table.swapped()
            born = gate_on(table, role, S, task='born')  # LiveCode=S: the reconciliation's task, not a reload
            born.back()  # nothing: the runner's pointer waits for the build's end (settle_image), as before this unit
            self.assertEqual((table.new(), table.value), ([], S))
            self.assertTrue(born.handover())
            self.assertEqual((table.sent[-1], table.events[0]['by'], 'reloaded' in table.events[0]), (live_image.EMPTY, 'handover', False))

    def test_the_wiring_of_both_roles(self):
        loop = SERVE[SERVE.index("LOG.info('serve: up')"):]
        standby = loop[loop.index('if gate is not None and not gate.active():'):loop.index('launched = launch.done')]
        self.assertLess(standby.index('gate.beat(loop)  # IMAGE-SWAP-TIGHTEN'), standby.index('reload.step()  # IMAGE-SWAP-RELOAD'))
        self.assertLess(loop.index('gate.live_beat()  # IMAGE-SWAP-FAILOVER'), loop.index('gate.back()  # IMAGE-SWAP-RELOAD'))
        self.assertLess(loop.index('gate.back()  # IMAGE-SWAP-RELOAD'), loop.index('moved = followed.follow(db)'))
        self.assertIn("live_image.Reload(gate, 'serve', pending=pending, stopping=stop.is_set)", SERVE)
        self.assertEqual(SERVE.count('reloaded=code_bundle.reloaded()') + RUN.count('reloaded=code_bundle.reloaded()'), 2)
        self.assertIn("gate, 'run-container', stopping=lambda: stop.is_set() or any(each.interrupted for each in workers))", RUN)
        self.assertIn('reload=reload, gate=gate))', RUN)
        # a reloaded runner was warmed when its task started: its slots open at once
        # (RELOAD-WITHOUT-STANDBY: by the exec's mark, so one that went back in place is not warmed again either)
        self.assertIn('warm_s = (None if gate is not None and (os.environ.get(code_bundle.RELOADED) or late)', RUN)
        self.assertIn('else prewarm(container, boxes, connect, name))', RUN)
        source = (ROOT / 'infra/service/tower_infra/runner.py').read_text(encoding='utf-8')
        once = source[source.index('    def once('):source.index('    def execute(')]
        self.assertLess(once.index('gate.live_beat(self.db)'), once.index('gate.back(self.db)  # IMAGE-SWAP-RELOAD'))
        standby = source[source.index('    def standby('):source.index('def serve_all(')]
        self.assertLess(standby.index('self.gate.beat(self.db)'), standby.index('self.reload.step(self.db)'))
        self.assertIn('if self.reload is not None and not self.interrupted and not stop.is_set():', standby)


class TheServicesWorkflows(unittest.TestCase):
    def test_the_drain_asks_dbos_for_the_pending_workflows_of_this_application_version(self):
        self.assertIn("version = os.environ.get('TOWER_IMAGE', 'local')", SERVE)
        self.assertIn("'application_version': version,", SERVE)
        pending = SERVE[SERVE.index('    def pending():'):SERVE.index('from . import wake')]
        self.assertIn("DBOS.list_workflows(\n            status=['PENDING', 'ENQUEUED'], app_version=version, load_input=False, "
                      'load_output=False)] if launch.done else []', pending)  # never launched: nothing of its own
        # the argument reads dbos 3.4.0 (recovery at launch: the pending workflows of the executor and version): a bump re-reads it
        self.assertIn('dbos==3.4.0\n', (ROOT / 'infra/service/requirements.txt').read_text(encoding='utf-8'))

    def test_the_reloaded_service_is_another_application_version_than_the_one_it_left(self):
        with tempfile.TemporaryDirectory() as root:
            environ = {'TOWER_IMAGE': 'registry/tower:tag1', 'TOWER_ARTIFACT_BUCKET': 'outputs', 'TOWER_CODE_ROOT': root}
            directory = code_bundle.stage(bundle.KEY, bundle.SHA, environ, bundle.Store({bundle.KEY: bundle.DATA}), bundle.BAKED)
            with self.assertRaises(bundle.Execed) as done:
                code_bundle.reload('serve', bundle.KEY, bundle.SHA, directory, {'digest': bundle.SHA}, environ, bundle.execve)
        child = done.exception.args[2]
        self.assertEqual(child['TOWER_IMAGE'], f'registry/tower:tag1+code.{bundle.SHA[:16]}')
        self.assertNotEqual(child['TOWER_IMAGE'], environ['TOWER_IMAGE'])


class TheBundle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = bundle.Store({bundle.KEY: bundle.DATA})
        # an ECS task the slow path deployed with an earlier bundle (LiveCode): it runs from that bundle's directory
        self.environ = {'TOWER_CODE_KEY': 'artifacts/lambda/tower-code/earlier.zip', 'TOWER_CODE_SHA256': 'e' * 64,
                        'TOWER_IMAGE_DIGEST': 'e' * 64, 'TOWER_IMAGE': f"registry/tower:tag1+code.{'e' * 16}",
                        code_bundle.LOADED: '/tmp/tower-code-earlier', 'TOWER_MIGRATIONS': '/tmp/tower-code-earlier/migrations',
                        'TOWER_ARTIFACT_BUCKET': 'outputs', 'TOWER_CODE_ROOT': self.tmp.name, 'PATH': os.environ.get('PATH', '')}
        self.said = {'role': 'runner', 'digest': bundle.SHA, 'task': 'ecs', 'state': 'started', 'from': 'e' * 64, 'turn': 0,
                     'key': bundle.KEY, 'drain_s': 0.0, 'version': 7, 'wrote_at': 1000.0, 'at': 1002.5}

    def reload(self, command='run-container', environ=None):
        directory = code_bundle.stage(bundle.KEY, bundle.SHA, self.environ, self.store, bundle.BAKED)
        with self.assertRaises(bundle.Execed) as done:
            code_bundle.reload(command, bundle.KEY, bundle.SHA, directory, self.said, environ or self.environ, bundle.execve)
        return directory, done.exception.args

    def test_the_exec_is_the_boot_paths_with_the_swapped_bundle_as_the_childs_code_and_digest(self):
        directory, (path, argv, child) = self.reload()
        self.assertEqual((path, argv), (sys.executable, [sys.executable, '-m', 'tower_infra', 'run-container']))
        self.assertEqual({name: child[name] for name in ('TOWER_CODE_KEY', 'TOWER_CODE_SHA256', 'TOWER_IMAGE_DIGEST')},
                         {'TOWER_CODE_KEY': bundle.KEY, 'TOWER_CODE_SHA256': bundle.SHA, 'TOWER_IMAGE_DIGEST': bundle.SHA})
        self.assertEqual(child['TOWER_IMAGE'], f'registry/tower:tag1+code.{bundle.SHA[:16]}')  # not ...+code.eee+code.S
        self.assertEqual((child[code_bundle.LOADED], child['TOWER_MIGRATIONS'], child['PYTHONPATH'], child['PYTHONSAFEPATH']),
                         (str(directory), str(directory / 'migrations'), str(directory), '1'))
        self.assertEqual(directory.parent, Path(self.tmp.name))
        self.assertEqual(self.store.reads, [bundle.KEY])
        self.assertEqual(self.environ['TOWER_IMAGE_DIGEST'], 'e' * 64)  # this process's own environment is not touched

    def test_the_child_goes_on_without_a_read_and_knows_what_the_reload_said(self):
        directory, (_, _, child) = self.reload()
        loaded, store = directory / 'tower_infra', bundle.Store()
        self.assertIsNone(code_bundle.boot('run-container', ['run-container'], child, store, bundle.execve, loaded))
        self.assertEqual(store.reads, [])
        self.assertEqual(code_bundle.reloaded(child), self.said)
        self.assertIsNone(code_bundle.reloaded({}))  # any other start
        self.assertIsNone(code_bundle.reloaded({**child, code_bundle.RELOADED: 'not json'}))
        self.assertIsNone(code_bundle.reloaded({**child, 'TOWER_IMAGE_DIGEST': 'f' * 64}))  # no longer that digest
        gate = live_image.gate('runner', child['TOWER_IMAGE_DIGEST'], Table(bundle.SHA).scope, reloaded=code_bundle.reloaded(child))
        self.assertEqual((gate.reloaded['from'], gate.sharing()), ('e' * 64, True))

    def test_the_real_child_imports_the_swapped_bundle_and_reads_the_reload(self):
        directory, (_, _, child) = self.reload(environ={**os.environ, **self.environ})
        probe = ('import json, tower_infra; from tower_infra import code_bundle; '
                 'print(json.dumps([tower_infra.__file__, code_bundle.boot("serve", ["serve"]), code_bundle.reloaded()]))')
        out = subprocess.run([sys.executable, '-c', probe], cwd=bundle.BAKED.parent, env=child, capture_output=True,
                             text=True, check=True).stdout
        where, booted, said = json.loads(out)
        self.assertEqual((Path(where).parent, booted, said), (directory / 'tower_infra', None, self.said))

    def test_a_bundle_that_cannot_be_staged_raises_before_anything_is_touched(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        (Path(other.name) / 'tower_infra').mkdir()
        (Path(other.name) / 'requirements.txt').write_text('dbos==0.0.0\n')  # an image with other libraries
        cases = ((bundle.Store(), bundle.BAKED, 'is not in the store'),
                 (bundle.Store({bundle.KEY: bundle.DATA + b'x'}), bundle.BAKED, 'has sha256'),
                 (self.store, Path(other.name) / 'tower_infra', "is not the image's: its code needs a new image"))
        for store, here, why in cases:
            with self.assertRaises(code_bundle.BundleError) as refused:
                code_bundle.stage(bundle.KEY, bundle.SHA, self.environ, store, here)
            self.assertIn(why, str(refused.exception))
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        with self.assertRaises(code_bundle.BundleError):  # an execve that returns is a failure, as in boot()
            code_bundle.reload('serve', bundle.KEY, bundle.SHA, self.tmp.name, self.said, self.environ, lambda *_: None)


class AfterBothHandovers(image_swap.World):
    """The reconciliation that follows: nothing fights over a pointer nobody holds."""

    def test_the_autodeploy_writes_nothing_once_no_pointer_names_the_bundle(self):
        self.land()
        self.db.live = {'runner', 'service'}
        for key in image_swap.KEYS:
            self.db.pointer[key] = ''  # both reloaded tasks handed over
        self.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'succeeded', 'base_head': image_swap.MERGE,
                                                         'ended': 2000, 'build_id': 'b:1'})
        self.now[0] = 100.0 + 10 * autodeploy.SWAP_LIMIT_S
        self.watcher.settle_image(self.db, self.heads)  # the slow build ended well: LiveCode=S, tasks born on S
        self.assertEqual([each for kind, each in self.db.events if kind == 'platform.deploy.image_retired'], [])

    def test_the_prewarm_retires_the_promoted_pair_and_never_stops_the_runner_with_its_runs(self):
        world = image_swap.Retire('test_a_promoted_bundle_stays_while_the_pointer_names_it_whatever_its_branch')
        world.setUp()
        world.promote()
        world.db.pointer[live_image.KEYS['service']] = ''  # the reloaded service handed over; the runner drains its runs
        world.now[0] += prewarm.POLL_S
        world.watcher.step()
        self.assertEqual(world.ecs.stopped, [])  # one pointer still names it: the pair stays
        world.db.pointer[live_image.KEYS['runner']] = ''  # then the reloaded runner
        world.now[0] += prewarm.POLL_S
        world.watcher.step()
        self.assertEqual([task for task, _ in world.ecs.stopped], [world.service])
        self.assertEqual(world.db.states()[-2:], [('runner', image_swap.S, 'retiring'), ('service', image_swap.S, 'stopped')])


class TheMeasure(unittest.TestCase):
    def test_scripts_medir_shows_the_swap_to_the_ecs_task_working_on_its_bundle(self):
        status = {'image_reload': [{'state': 'reloaded', 'role': 'service', 'reload_s': 8.412},
                                   {'state': 'started', 'role': 'service'}, {'state': 'failed', 'reload_s': 3},
                                   {'state': 'reloaded', 'reload_s': True}, {'state': 'reloaded', 'reload_s': 5}, 'junk']}
        self.assertEqual(medir.from_deploy_status(status), {'image_reload_s': [8.412, 5.0]})
        self.assertNotIn('image_reload_s', medir.from_deploy_status({'image_reload': [{'state': 'started'}]}))


def service_pass(gate, tick, reload=None):
    """One pass of serve's loop: a standby's beat and the reload's look, or the dispatch tick (image_live at its first
    dispatch), the live beat and the reloaded task's record and handover."""
    if not gate.active():
        gate.beat()
        if reload is not None:
            reload.step()
        return None
    started = tick(lambda parts: gate.working())
    gate.live_beat()
    gate.back()
    return started


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements on the migrated tables, with the real bundle of this checkout: a swap, the promoted standby's
    image_live, the ECS task's reload, its record and its handover, and the status that shows them."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store, self.children = bundle.Store({bundle.KEY: bundle.DATA}), []
        self.environ = {'TOWER_IMAGE': 'registry/tower:tag1', 'TOWER_IMAGE_DIGEST': ECS, 'TOWER_ARTIFACT_BUCKET': 'outputs',
                        'TOWER_CODE_ROOT': self.tmp.name}
        for name, value in (('RELOAD_ASK_S', 0.1), ('LIVE_BEAT_S', 0.1)):
            patch = mock.patch.object(live_image, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def swap(self):
        """The landing's swap of both pointers to the bundle, with its record (digest and key)."""
        found = self.db.rows(autodeploy.SWAP_WRITE, {
            'tenant': 'torre', 'digest': bundle.SHA, 'keys': ','.join(image_swap.KEYS), 'reason': 'test',
            'id': f'{autodeploy.SWAP}:{image_swap.MERGE}', 'landed_at': time.time(),
            'payload': json.dumps({'digest': bundle.SHA, 'key': bundle.KEY, 'head': image_swap.MERGE})})
        swapped = json.loads(found[0][0])
        # DEPLOY-CANARY: the swap's canary job ended succeeded, which the reload's trigger wants (test_infra_canary has the canary)
        self.db.rows("insert into work.job (tenant_id, selector, input_uri, input_digest, idempotency_key, state) "
                     "select id, '{\"adapter\": \"container\"}', 'data:,', 'canary', %(key)s, 'succeeded' from work.tenant "
                     "where name = 'torre'", {'key': canary.PREFIX + canary.swap_key(
                         bundle.SHA, swapped['versions'][live_image.KEYS['service']])})
        return swapped

    def gate(self, role, digest, strict=False, task=None, reloaded=None):
        return live_image.gate(role, digest, live_image.kept(self.db), task=task or f'{role}-{digest[:3]}', strict=strict,
                               reloaded=reloaded)

    def reloader(self, gate, command, store=None, **more):
        """The task's reload with code_bundle's own stage and reload: only the store and execve are stand-ins."""
        def execute(*arguments):
            self.children.append(arguments)
            code_bundle.reload(*arguments, environ=self.environ, execve=lambda path, argv, environ: self.replaced(argv, environ))
        return live_image.Reload(
            gate, command, stage=lambda key, sha: code_bundle.stage(key, sha, self.environ, store or self.store, bundle.BAKED),
            execute=execute, **more)

    def replaced(self, argv, environ):
        self.child = {'argv': argv, 'environ': environ, 'at': time.monotonic()}
        raise Replaced()

    def events(self, kind):
        return [json.loads(row[0]) for row in self.db.rows(
            "select payload::text from log.event where type = %(type)s order by occurred_at, payload->>'at'", {'type': kind})]

    def pointer(self, role):
        found = self.db.rows("select value::text from work.config_value where key = %(key)s", {'key': live_image.KEYS[role]})
        return json.loads(found[0][0]) if found else None

    def took(self, job):
        return [row[0] for row in self.db.rows(
            "select payload->>'runner' from log.event where type = 'run.running' and payload->>'job_id' = %(id)s "
            "order by occurred_at", {'id': job})]

    def slot(self, gate, name, reload=None):
        return runner.Runner(self.db, self.world.fetch, self.world.prepare, self.world.upload, self.world.workdir,
                             name=name, gate=gate, reload=reload, renew_every_s=QUICK)

    def test_the_ecs_service_reloads_hands_over_and_dispatches_the_queue_on_the_swapped_bundle(self):
        workflows = workflows_with([])
        promoted, ecs = self.gate('service', bundle.SHA, strict=True, task='promoted'), self.gate('service', ECS, task='ecs')
        self.assertEqual((promoted.active(), ecs.active()), (False, True))  # no pointer: the ECS service works
        pending = [['run-in-flight'], ['run-in-flight'], []]  # a workflow the ECS service started before the swap
        reload = self.reloader(ecs, 'serve', pending=lambda: pending.pop(0) if pending else [])

        @contextlib.contextmanager
        def connected():
            yield self.db

        def tick(dispatched):
            return workflows.tick('5 minutes', dispatched=dispatched)
        with mock.patch.object(workflows, 'connected', connected):
            swap = self.swap()
            swapped = time.monotonic()
            for each in (promoted, ecs):
                each.refresh()  # what the tower_config notification runs
            service_pass(ecs, tick, reload)  # the pass that sees the swap: nothing of the reload
            self.assertEqual(self.events(live_image.RELOAD), [])
            service_pass(promoted, tick)  # the promoted standby's first dispatch: platform.deploy.image_live
            with self.assertRaises(Replaced):
                for _ in range(100):
                    service_pass(promoted, tick)
                    service_pass(ecs, tick, reload)
                    time.sleep(QUICK)
            self.assertEqual(pending, [])  # the workflow ended first
            [started] = self.events(live_image.RELOAD)
            self.assertEqual({name: started[name] for name in ('role', 'digest', 'task', 'state', 'from', 'turn', 'key', 'version')},
                             {'role': 'service', 'digest': bundle.SHA, 'task': 'ecs', 'state': 'started', 'from': ECS,
                              'turn': 0, 'key': bundle.KEY, 'version': swap['versions'][live_image.KEYS['service']]})
            self.assertAlmostEqual(started['wrote_at'], swap['wrote_at'], places=2)  # the claim is the swap's: its write
            self.assertEqual(self.pointer('service'), bundle.SHA)
            child = self.child['environ']
            self.assertEqual(self.child['argv'][-3:], ['-m', 'tower_infra', 'serve'])
            self.assertEqual((child['TOWER_CODE_KEY'], child['TOWER_CODE_SHA256'], child['TOWER_IMAGE_DIGEST']),
                             (bundle.KEY, bundle.SHA, bundle.SHA))
            self.assertEqual(code_bundle.reloaded(child), started)
            # the process the exec started: the ECS task on the swapped bundle, not strict, live at once beside the standby
            back = self.gate('service', child['TOWER_IMAGE_DIGEST'], task='ecs', reloaded=code_bundle.reloaded(child))
            self.assertEqual((back.active(), back.sharing()), (True, True))
            job = self.world.job('queued', 'true')
            service_pass(back, tick)
            reloaded_s = time.monotonic() - swapped
        self.assertEqual(self.db.rows("select state from work.run where job_id = %(id)s::uuid", {'id': job}), [('starting',)])
        self.assertEqual((self.pointer('service'), self.pointer('runner')), ('', bundle.SHA))  # the runner's role is its own
        self.assertEqual((promoted.refresh(), promoted.retired), (False, True))  # the promoted standby stands by
        back.refresh()
        self.assertEqual((back.active(), back.sole()), (True, True))
        [retired] = self.events('platform.deploy.image_retired')
        self.assertEqual((retired['by'], retired['role'], retired['task'], retired['reloaded'], retired['keys']),
                         ('handover', 'service', 'ecs', True, [live_image.KEYS['service']]))
        status = self.world.port('GET', '/v1/deploy/status', 'torre')
        self.assertEqual([each['state'] for each in status['image_reload']], ['reloaded', 'started'])  # newest first
        done = status['image_reload'][0]
        self.assertEqual((done['role'], done['digest'], done['task'], done['from'], done['version']),
                         ('service', bundle.SHA, 'ecs', ECS, started['version']))
        self.assertGreater(done['reload_s'], done['boot_s'])  # the pointer's write, and the claim, to its first tick
        self.assertGreater(done['boot_s'], 0)
        self.assertLess(done['reload_s'], reloaded_s + 1)
        self.assertIsInstance(status['image_retired'][0].pop('at'), float)  # STATUS-EVENTS-AT
        self.assertEqual(status['image_retired'], [retired])
        self.assertEqual(medir.from_deploy_status(status)['image_reload_s'], [done['reload_s']])
        self.assertEqual([each['role'] for each in status['image_live']], ['service'])

    def test_the_ecs_runner_finishes_its_run_in_flight_then_reloads_takes_the_queue_and_the_promoted_runner_ends(self):
        promoted, ecs = self.gate('runner', bundle.SHA, strict=True, task='promoted'), self.gate('runner', ECS, task='ecs')
        reload = self.reloader(ecs, 'run-container')
        seen, stops = {}, {name: threading.Event() for name in ('promoted', 'ecs', 'back')}
        original = reload.execute

        def execute(*arguments):
            seen['long at the exec'] = self.world.state(long)
            original(*arguments)
        reload.execute = execute
        long = self.world.job('long', 'sleep 1.5')
        mechanisms.dispatch(self.db)
        slots = [self.slot(ecs, 'ecs', reload), self.slot(ecs, 'ecs/1', reload)]  # one task, two slots, one reload
        threads = [threading.Thread(target=each.loop, args=(stops['ecs'], QUICK), daemon=True) for each in slots]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 60
        while not self.world.running(long) and time.monotonic() < deadline:
            time.sleep(QUICK)
        self.swap()  # the landing: the ECS runner has a run in flight
        for each in (promoted, ecs):
            each.refresh()
        standby = threading.Thread(target=self.slot(promoted, 'promoted').loop, args=(stops['promoted'], QUICK), daemon=True)
        standby.start()  # its first TAKE records image_live
        while not hasattr(self, 'child') and time.monotonic() < deadline:
            time.sleep(QUICK)
        self.assertEqual(seen, {'long at the exec': 'succeeded'})  # never killed: the reload waited for it
        self.assertEqual(self.world.state(long), 'succeeded')
        self.assertIn(self.took(long), (['ecs'], ['ecs/1']))
        self.assertEqual(len(self.children), 1)
        stops['ecs'].set()  # the exec replaced the process: its other slot is gone with it
        for thread in threads:
            thread.join(10)
        [started] = self.events(live_image.RELOAD)
        self.assertEqual((started['state'], started['role'], started['from'], started['task']), ('started', 'runner', ECS, 'ecs'))
        ended = float(self.db.rows("select extract(epoch from max(occurred_at)) from log.event where type = 'run.ended'")[0][0])
        self.assertGreaterEqual(started['at'], round(ended, 3))  # claimed after the run ended
        child = self.child['environ']
        self.assertEqual(self.child['argv'][-1], 'run-container')
        back = self.gate('runner', child['TOWER_IMAGE_DIGEST'], task='ecs', reloaded=code_bundle.reloaded(child))
        reloaded = threading.Thread(target=self.slot(back, 'ecs').loop, args=(stops['back'], QUICK), daemon=True)
        reloaded.start()  # its first TAKE: the record, and the handover of the runner's pointer
        while standby.is_alive() and time.monotonic() < deadline:
            time.sleep(QUICK)
            back.refresh()  # the notifications of the handover
            promoted.refresh()
        self.assertFalse(standby.is_alive())  # the promoted standby's slot ended: it exits on its own, never StopTask'ed
        after = self.world.job('after', 'true')
        mechanisms.dispatch(self.db)
        while self.world.state(after) != 'succeeded' and time.monotonic() < deadline:
            time.sleep(QUICK)
        stops['back'].set()
        reloaded.join(10)
        self.assertEqual((self.world.state(after), self.took(after)), ('succeeded', ['ecs']))  # the ECS task, on the bundle
        self.assertEqual((self.pointer('runner'), self.pointer('service')), ('', bundle.SHA))
        [retired] = self.events('platform.deploy.image_retired')
        self.assertEqual((retired['by'], retired['role'], retired['task'], retired['reloaded'], retired['keys']),
                         ('handover', 'runner', 'ecs', True, [live_image.KEYS['runner']]))
        states = [(each['state'], each['role']) for each in self.events(live_image.RELOAD)]
        self.assertEqual(states, [('started', 'runner'), ('reloaded', 'runner')])
        status = self.world.port('GET', '/v1/deploy/status', 'torre')
        self.assertEqual(len(medir.from_deploy_status(status)['image_reload_s']), 1)

    def test_a_bundle_that_fails_to_load_is_tried_once_and_the_promoted_pair_keeps_the_role(self):
        promoted, ecs = self.gate('service', bundle.SHA, strict=True, task='promoted'), self.gate('service', ECS, task='ecs')
        missing = bundle.Store()  # not in the store (or: another sha256, other requirements; TheBundle)
        reload = self.reloader(ecs, 'serve', store=missing)
        self.swap()
        for each in (promoted, ecs):
            each.refresh()
        promoted.working()
        with self.assertLogs('tower_infra.live_image', 'INFO'):
            for _ in range(8):
                ecs.beat()
                reload.step()
                time.sleep(QUICK)
        self.assertEqual((missing.reads, self.children), ([bundle.KEY], []))
        [failed] = self.events(live_image.RELOAD)
        self.assertEqual((failed['state'], failed['role'], failed['digest'], failed['task'], failed['why']),
                         ('failed', 'service', bundle.SHA, 'ecs', f'the bundle cannot be loaded: {bundle.KEY} is not in the store'))
        self.assertNotIn('reload_s', failed)
        again = self.gate('service', ECS, task='ecs-restarted')  # the task started again, or another of the role
        other = self.reloader(again, 'serve')  # even with the bundle there now
        with self.assertLogs('tower_infra.live_image', 'INFO') as logs:
            for _ in range(6):
                again.beat()
                other.step()
                time.sleep(QUICK)
        self.assertIn('it is not tried again', logs.output[0])
        self.assertEqual((self.store.reads, self.children, len(self.events(live_image.RELOAD))), ([], [], 1))
        self.assertEqual((self.pointer('service'), promoted.active(), ecs.active()), (bundle.SHA, True, False))
        status = self.world.port('GET', '/v1/deploy/status', 'torre')
        self.assertEqual((status['image_reload'], status['image_retired']), ([failed], []))
        self.assertNotIn('image_reload_s', medir.from_deploy_status(status))

    def claim(self, gate, turn=0):
        said = {'role': gate.role, 'digest': gate.pointer, 'task': gate.task, 'state': 'started', 'turn': turn}
        return self.db.rows(live_image.RELOAD_START, {
            'id': f'{live_image.RELOAD}:{gate.role}:{gate.pointer}:{turn}', 'producer': 'test', 'role': gate.role,
            'payload': json.dumps(said), 'tenant': 'torre', 'key': gate.key, 'digest': gate.pointer, 'version': gate.version})

    def test_one_task_per_turn_and_never_once_the_pointer_was_emptied(self):
        self.swap()
        first, second = self.gate('runner', ECS, task='ecs-1'), self.gate('runner', ECS, task='ecs-2')
        service = self.gate('service', ECS, task='ecs-1')
        self.assertEqual(len(self.claim(first)), 1)
        self.assertEqual(self.claim(second), [])  # the same turn of the same swap: the log's primary key
        self.assertEqual(len(self.claim(second, turn=1)), 1)  # the next turn is its own
        self.assertEqual(len(self.claim(service)), 1)  # each role apart
        self.assertEqual([each['task'] for each in self.events(live_image.RELOAD)], ['ecs-1', 'ecs-2', 'ecs-1'])
        promoted = self.gate('runner', bundle.SHA, strict=True, task='promoted')
        self.assertTrue(promoted.handback())  # Spot's SIGTERM: the pointer is emptied (by: handback)
        self.assertEqual(self.claim(first, turn=2), [])  # the claim compares the pointer: no reload over an emptied one
        self.assertTrue(self.db.rows(live_image.EMPTY, live_image.empty(
            'torre', [live_image.KEYS['service']], bundle.SHA, 'autodeploy', {'by': 'revert'}, 'id-revert', 'test')))
        self.assertEqual(self.claim(service, turn=1), [])  # nor after the autodeploy's revert
        self.assertEqual([each['by'] for each in self.events('platform.deploy.image_retired')], ['handback', 'revert'])

    def test_the_handover_waits_for_an_ecs_task_still_standing_by_on_the_old_code(self):
        self.swap()
        said = {'role': 'runner', 'digest': bundle.SHA, 'task': 'ecs-1', 'from': ECS, 'turn': 0, 'version': 1,
                'wrote_at': time.time(), 'at': time.time()}
        back, other = self.gate('runner', bundle.SHA, task='ecs-1', reloaded=said), self.gate('runner', ECS, task='ecs-2')
        self.gate('runner', 'c' * 64, strict=True, task='another-head').beat()  # a prewarm standby never counts
        other.beat()
        with self.assertLogs('tower_infra.live_image', 'INFO'):
            back.back()
        self.assertEqual((self.pointer('runner'), self.events('platform.deploy.image_retired')), (bundle.SHA, []))
        self.assertEqual([each['state'] for each in self.events(live_image.RELOAD)], ['reloaded'])
        self.db.rows("update work.standby_beat set beat_at = clock_timestamp() - make_interval(secs => %(ago)s::float8) "
                     "where task = 'ecs-2'", {'ago': live_image.ALONE_S + 1})  # it reloaded, or the rollout stopped it
        time.sleep(0.15)  # LIVE_BEAT_S here: the handover is tried again that often
        back.back()
        self.assertEqual(self.pointer('runner'), '')
        [retired] = self.events('platform.deploy.image_retired')
        self.assertEqual((retired['by'], retired['reloaded']), ('handover', True))
        self.assertEqual(len(self.events(live_image.RELOAD)), 1)  # recorded once


if __name__ == '__main__':
    unittest.main()
