"""IMAGE-SWAP-FAILOVER (docs/operations/aws.md 22.9): a promoted standby that dies or hangs never leaves its role without
a live process.

On 10/11 02:14:42 UTC the swap of #472 promoted a standby pair on FARGATE_SPOT; Spot interrupted the service 26 s later and
the runner 3.5 min later; both exited cleanly with deploy.live_image_<role> still naming their bundle, the ECS tasks kept
standing by and no job was dispatched for 23 minutes.
1. The live beat: a process that is live because the pointer names its digest stamps work.standby_beat.live_at (migration
   0016) while it works: the service after each good dispatch tick, the runner at each TAKE and from the keeper of each run
   in flight, so a runner whose slots are all busy never looks dead. With no pointer or no digest nothing beats.
2. The watchdog: the standby pass of an ECS task (not strict) is one statement that also reads how old the pointed digest's
   live beat is; past deploy.live_stale_s (registry, 10 s) it empties the pointer by compare-and-swap
   (platform.deploy.image_retired, by: failover) and works at once. Each role apart; the autodeploy's revert takes a
   half-emptied pair; an ECS runner the pointer leaves stays up, standing by.
3. The handback: on SIGTERM (Spot's warning, a StopTask) a promoted standby first withdraws its beat and empties its pointer
   by the same compare-and-swap (by: handback), on a connection with short timeouts, and only then stops taking work: the
   ECS task works at once. The landing never swaps onto a standby that is leaving.

Hermetic: a fake table on an injected clock; OnPostgres runs the real statements (TEST_DATABASE_URL).
"""
import contextlib
import json
import os
from pathlib import Path
import signal
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
from tower_infra import autodeploy, config_data, live_image, mechanisms, runner  # noqa: E402
import medir  # noqa: E402
import test_infra_image_swap as image_swap  # noqa: E402
from test_infra_swap_ready import workflows_with  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
S, ECS = 'a' * 64, 'registry/tower:old'  # the promoted bundle; the ECS tasks' own image
QUICK = float('0.05')
MAIN = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
SERVE = MAIN[MAIN.index('def serve('):MAIN.index('\ndef ', MAIN.index('def serve(') + 1)]


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


class Table:
    """deploy.live_image_<role> and work.standby_beat by statement, on one injected clock (the database's and the gates')."""

    def __init__(self, value='', clock=None):
        self.clock = clock or Clock()
        self.value, self.version, self.wrote = value, 1, self.clock()
        self.beats, self.live, self.sent, self.broken = {}, {}, [], False
        self.events, self.stale = [], None  # platform.deploy.image_retired; deploy.live_stale_s as stored (None: no row)

    def scope(self):
        return contextlib.nullcontext(self)

    def write(self, value):
        self.value, self.version, self.wrote = value, self.version + 1, self.clock()

    def count(self, sql):
        return len([each for each in self.sent if each == sql])

    def rows(self, sql, params=None):
        if self.broken:
            raise RuntimeError('db down')
        self.sent.append(sql)
        mine = (params or {}).get('role'), (params or {}).get('digest'), (params or {}).get('task')
        if sql == live_image.READ:
            return [(json.dumps(self.value), self.version, self.clock() - self.wrote)]
        if sql == live_image.BEAT:
            self.beats[mine] = self.clock()
            return []
        if sql == live_image.LIVE_BEAT:
            self.beats[mine] = self.live[mine] = self.clock()
            return []
        if sql == live_image.WATCH:
            self.beats[mine] = self.clock()
            last = max([at for (role, digest, _), at in self.live.items() if (role, digest) == (mine[0], self.value)]
                       + [self.wrote])
            return [(self.value, self.clock() - last, None if self.stale is None else json.dumps(self.stale))]
        if sql in (live_image.EMPTY, live_image.LEAVE):
            if sql == live_image.LEAVE:  # the handback: the standby's own beat goes first
                self.beats.pop(mine, None)
                self.live.pop(mine, None)
            if self.value != params['digest']:
                return []
            self.write('')
            self.events.append({**json.loads(params['payload']), 'id': params['id']})
            return [(json.dumps(params['keys'].split(',')),)]
        if sql == runner.RENEW:
            return [('running',)]
        if sql in (live_image.LIVE, runner.TAKE, live_image.BUSY):  # SWAP-TAIL-EVIDENCE: nothing to say here
            return []
        if sql == live_image.WITHDRAW:  # LOST-BEAT-WITHDRAWN: the beat of a successor that ended
            self.withdrawn = [*getattr(self, 'withdrawn', []), mine]
            self.beats.pop(mine, None)
            return []
        if sql == live_image.HOLDS:  # SUCCESSOR-LOST: what a cover says when it ends (platform.deploy.successor)
            self.said = [*getattr(self, 'said', []), json.loads(params['payload'])]
            return []
        if sql == live_image.DRILL:  # SWAP-DRILL: a drill of this role and bundle, newer than the process that asks
            self.asked = params
            return [(1,)] if getattr(self, 'drill', False) else []
        if sql == live_image.DISMISSED:  # STANDBY-GRACE: the newest platform.deploy.standby of the role and bundle
            return [(self.standby_state,)] if getattr(self, 'standby_state', None) else []
        raise AssertionError(sql)


def gate_on(table, role, digest, strict=False, task='t'):
    return live_image.Gate(table.scope, role, digest, task=task, strict=strict, clock=table.clock)


class TheLiveBeat(unittest.TestCase):
    def test_only_a_process_the_pointer_names_owes_the_role_a_live_beat(self):
        cases = ((S, S, True, True),  # the promoted standby
                 (S, S, False, True),  # the reconciled ECS task while sharing
                 ('', ECS, False, False),  # no pointer: live as always, today's path
                 (S, ECS, False, False),  # an ECS task standing by
                 ('', S, True, False))  # a standby the pointer does not name
        for pointer, digest, strict, owes in cases:
            table = Table(pointer)
            gate = gate_on(table, 'service', digest, strict)
            gate.refresh()
            self.assertEqual((gate.pointed(), gate.live_beat()), (owes, owes), (pointer, digest, strict))
            self.assertEqual(table.count(live_image.LIVE_BEAT), int(owes))

    def test_it_is_one_statement_per_task_every_live_beat_s_whoever_calls(self):
        table = Table(S)
        gate = gate_on(table, 'runner', S, strict=True, task='task-9')
        gate.refresh()
        slots = [mock.Mock(rows=table.rows) for _ in range(3)]  # each slot's own connection
        for step in range(5):  # 2 s of passes, each slot once every half second
            for db in slots:
                gate.live_beat(db)
            table.clock.now += 0.5
        self.assertEqual(table.count(live_image.LIVE_BEAT), 2)  # at 0 and at LIVE_BEAT_S
        self.assertEqual(table.live, {('runner', S, 'task-9'): 102.0})
        self.assertEqual(live_image.LIVE_BEAT_S, 2)

    def test_a_beat_that_fails_is_only_missing(self):
        table = Table(S)
        gate = gate_on(table, 'service', S, strict=True)
        gate.refresh()
        table.broken = True
        with self.assertLogs('tower_infra.live_image', 'ERROR'):
            self.assertFalse(gate.live_beat())
        self.assertEqual(table.live, {})

    def test_the_runner_beats_at_its_take_and_only_while_the_pointer_names_it(self):
        table = Table(S)
        gate = gate_on(table, 'runner', S, strict=True)
        gate.refresh()
        slot = runner.Runner(table, None, None, None, tempfile.gettempdir(), gate=gate)
        self.assertIsNone(slot.once())
        self.assertEqual(table.sent[-2:], [runner.TAKE, live_image.LIVE_BEAT])
        for pointer in ('', ECS):  # no pointer, or (not strict) a pointer naming this image's own digest later emptied
            free = Table(pointer)
            gate = gate_on(free, 'runner', ECS)
            gate.refresh()
            free.write('')
            gate.refresh()
            runner.Runner(free, None, None, None, tempfile.gettempdir(), gate=gate).once()
            self.assertEqual([each for each in free.sent if each != live_image.READ], [runner.TAKE])  # as before

    def keeper(self, gate, renew_every_s, seconds):
        """A slot's keeper for `seconds`: the statements it sent on a database of its own."""
        table = Table()
        slot = runner.Runner(table, None, None, None, tempfile.gettempdir(), renew_every_s=renew_every_s, gate=gate)
        stop = threading.Event()
        thread = threading.Thread(target=slot.keep, args=({'run': 'r', 'fence': 1}, stop, {}), daemon=True)
        thread.start()
        time.sleep(seconds)
        stop.set()
        thread.join(5)
        return table.sent

    def test_a_busy_slots_keeper_beats_between_its_renewals_so_a_busy_runner_never_looks_dead(self):
        table = Table(S)
        gate = live_image.Gate(table.scope, 'runner', S, task='t', strict=True)  # the real clock: the keeper waits on it
        gate.refresh()
        with mock.patch.object(live_image, 'LIVE_BEAT_S', QUICK):
            sent = self.keeper(gate, renew_every_s=60.0, seconds=QUICK * 8)
        self.assertGreaterEqual(sent.count(live_image.LIVE_BEAT), 3)  # the run is far from its first renewal
        self.assertNotIn(runner.RENEW, sent)

    def test_the_keeper_renews_at_its_pace_with_the_beat_and_exactly_as_before_without_a_pointer(self):
        table = Table(S)
        gate = live_image.Gate(table.scope, 'runner', S, task='t', strict=True)
        gate.refresh()
        self.assertEqual((gate.pace(60.0), gate.pace(1.0)), (live_image.LIVE_BEAT_S, 1.0))
        with mock.patch.object(live_image, 'LIVE_BEAT_S', QUICK):
            sent = self.keeper(gate, renew_every_s=QUICK * 3, seconds=QUICK * 14)
        self.assertGreaterEqual(sent.count(runner.RENEW), 2)  # every third wake
        self.assertGreater(sent.count(live_image.LIVE_BEAT), sent.count(runner.RENEW))
        free = gate_on(Table(''), 'runner', ECS)
        free.refresh()
        self.assertEqual(free.pace(60.0), 60.0)
        for none in (None, free):
            sent = self.keeper(none, renew_every_s=QUICK, seconds=QUICK * 6)
            self.assertEqual(set(sent), {runner.RENEW})

    def test_the_service_beats_after_a_good_tick_in_its_main_loop(self):
        loop = SERVE[SERVE.index("LOG.info('serve: up')"):]
        tick, beat = loop.index('started = workflows.tick(lease, '), loop.index('gate.live_beat()  # IMAGE-SWAP-FAILOVER')
        self.assertLess(tick, beat)  # a tick that raises never reaches it: a hung or failing loop stops beating
        self.assertLess(beat, loop.index('moved = followed.follow(db)'))  # before the outside calls of the pass
        self.assertIn('if gate is not None:\n                gate.live_beat()', loop)


def service_pass(gate, tick):
    """One pass of serve's loop for a gated service: the standby's beat, or the dispatch tick and then its live beat."""
    if not gate.active():
        gate.beat()
        return None
    started = tick()
    gate.live_beat()
    return started


class TheWatchdog(unittest.TestCase):
    def pair(self, role='service', pointer=S):
        """The promoted standby of S, live and beating, and the role's ECS task standing by, on one table."""
        table = Table(pointer)
        promoted, ecs = gate_on(table, role, S, strict=True, task='promoted'), gate_on(table, role, ECS, task='ecs')
        self.assertEqual((promoted.refresh(), ecs.refresh()), (pointer == S, False))
        promoted.live_beat()
        return table, promoted, ecs

    def passes(self, table, ecs, beating=None, seconds=30):
        """One standby pass a second (the beating process first) until the ECS task is live; how many it took."""
        for count in range(1, seconds + 1):
            table.clock.now += 1
            if beating is not None:
                beating.live_beat()
            ecs.beat()
            if ecs.active():
                return count
        return None

    def test_the_watch_is_the_standby_passs_one_statement_and_a_beating_image_is_never_failed_over(self):
        table, promoted, ecs = self.pair()
        before = len(table.sent)
        self.assertIsNone(self.passes(table, ecs, beating=promoted, seconds=60))
        sent = [each for each in table.sent[before:] if each != live_image.LIVE_BEAT]
        self.assertEqual(sent, [live_image.WATCH] * 60)  # no extra round trip: the beat's statement watches
        self.assertEqual((table.value, table.events, table.beats[('service', ECS, 'ecs')]), (S, [], table.clock()))

    def test_a_promoted_image_that_stops_beating_is_failed_over_within_the_registry_value_and_one_pass(self):
        for role in ('service', 'runner'):
            table, promoted, ecs = self.pair(role)
            self.passes(table, ecs, beating=promoted, seconds=5)
            died = table.clock()  # dead with no handback (a hard kill, a lost host) or its loop hangs: no more beats
            self.assertIsNotNone(self.passes(table, ecs))
            window = config_data.SPEC['deploy.live_stale_s'][1]
            self.assertEqual(table.clock() - table.live[(role, S, 'promoted')], window + 1)  # the first pass past 10 s
            self.assertLessEqual(table.clock() - died, window + 1)  # deploy.live_stale_s and one pass, at most
            self.assertEqual(table.sent[-3:], [live_image.WATCH, live_image.EMPTY, live_image.READ])  # live in that pass
            self.assertEqual(table.events, [{'role': role, 'digest': S, 'task': 'ecs', 'by': 'failover', 'stale_s': 11.0,
                                             'id': f'platform.deploy.image_retired:{role}:{S}:failover:1'}])
            self.assertEqual((table.value, ecs.active(), ecs.pointed()), ('', True, False))  # not strict: works at once
            self.assertEqual((promoted.refresh(), promoted.retired), (False, True))  # the strict standby is out
            ecs.live_beat()
            self.assertNotIn(('runner', ECS, 'ecs'), table.live)  # under no pointer nothing owes a live beat

    def test_the_stale_window_is_the_registrys(self):
        for stored, limit in ((3.0, 3), (30, 30), (0, 10), ('soon', 10), (None, 10)):  # an invalid row is the default
            table, _, ecs = self.pair()
            table.stale = stored
            self.assertEqual(self.passes(table, ecs, seconds=40), limit + 1, stored)
        entry = json.loads((ROOT / 'config/registry/deploy/deploy.live_stale_s.json').read_text(encoding='utf-8'))
        self.assertEqual((entry['type'], entry['default']), ('number', 10.0))
        self.assertEqual(config_data.SPEC['deploy.live_stale_s'], (float, 10.0))
        self.assertGreater(entry['default'], 2 * live_image.LIVE_BEAT_S)  # several missed beats, never one

    def test_a_swap_has_the_window_to_take_work_and_a_standby_that_never_does_is_failed_over(self):
        table, promoted, ecs = self.pair(pointer=ECS + '-older')  # another digest is live; S's standbys only stand by
        promoted.beat()
        table.write(S)  # the landing's swap: no live beat of S yet
        ecs.refresh()
        self.assertIsNone(self.passes(table, ecs, seconds=10))  # the pointer's write counts: 10 s to its first work
        self.assertTrue(promoted.refresh())
        self.assertIsNone(self.passes(table, ecs, beating=promoted, seconds=30))
        table, promoted, ecs = self.pair(pointer=ECS + '-older')
        table.write(S)  # a standby deaf to the swap (its listener lost) still beats standing by: that is no live beat
        ecs.refresh()
        for _ in range(10):
            promoted.beat()
            self.assertIsNone(self.passes(table, ecs, seconds=1))
        self.assertEqual(self.passes(table, ecs, seconds=1), 1)
        self.assertEqual(table.events[0]['by'], 'failover')

    def test_a_prewarm_standby_only_beats_it_never_takes_a_role_it_was_not_given(self):
        table = Table(ECS + '-older')
        table.clock.now += 3600
        standby = gate_on(table, 'runner', S, strict=True)
        standby.refresh()
        standby.beat()
        self.assertEqual((table.sent[-1], table.value, standby.active()), (live_image.BEAT, ECS + '-older', False))

    def test_of_two_ecs_tasks_one_wins_and_the_other_reads_the_pointer(self):
        table, _, first = self.pair('runner')
        second = gate_on(table, 'runner', ECS, task='ecs-2')  # the ECS service replacing a task: two stand by
        second.refresh()
        table.clock.now += 11
        first.beat()
        second.beat()
        self.assertEqual([each['task'] for each in table.events], ['ecs'])
        self.assertTrue(first.active() and second.active())
        table.write(S)  # and of two that both saw it stale, the compare-and-swap lets one through
        for each in (first, second):
            each.refresh()
        table.clock.now += 11
        table.write('')
        table.value = S  # the pointer both gates read...
        first.failover(S, 11.0)
        self.assertEqual(len(table.events), 2)
        with self.assertLogs('tower_infra.live_image', 'WARNING') as logs:
            second.failover(S, 11.0)  # ...is gone when the second writes
        self.assertEqual(len(table.events), 2)
        self.assertIn('the pointer had moved already', logs.output[0])

    def test_a_pointer_change_the_listener_missed_is_read_on_the_pass(self):
        table, _, ecs = self.pair()
        table.write('')  # emptied (a handback, the reconciliation), and the notification never came
        ecs.beat()
        self.assertEqual((ecs.active(), table.events), (True, []))

    def test_the_ecs_runner_the_pointer_leaves_stands_by_and_serve_keeps_its_standby_pass(self):
        source = (ROOT / 'infra/service/tower_infra/runner.py').read_text(encoding='utf-8')
        self.assertIn('if self.gate.retired and self.gate.strict:', source)
        loop = SERVE[SERVE.index("LOG.info('serve: up')"):]
        standby = loop[loop.index('if gate is not None and not gate.active():'):loop.index('launched = launch.done')]
        self.assertIn('gate.beat(loop)  # IMAGE-SWAP-TIGHTEN', standby)  # WATCH for the ECS task: the failover is in the pass
        self.assertIn("gate.wait(settings.get('service.dispatch_s'))", standby)  # a failover wakes it at once


class TheCover(unittest.TestCase):
    """SUCCESSOR-LOST: the standby lost at the instant of the swap. The process the swap promoted ends with no word; the
    role's process before it, standing by in the same task, is told by the supervisor at once and covers the role on the
    code it has until the bundle's new process beats live. Before: no process of the role for the new one's boot (5 to
    8 s) or deploy.live_stale_s (10 s)."""

    def swapped(self, role='runner'):
        table = Table(S)
        promoted, ecs = gate_on(table, role, S, strict=True, task='promoted'), gate_on(table, role, ECS, task='ecs')
        self.assertEqual((promoted.refresh(), ecs.refresh()), (True, False))
        return table, promoted, ecs

    def test_the_role_s_process_covers_in_the_instant_it_is_told_and_stands_by_again_when_the_new_successor_beats(self):
        for role in ('runner', 'service'):
            table, promoted, ecs = self.swapped(role)
            before = len(table.sent)
            table.clock.now += 0.2  # the supervisor reaped its child and its signal came: two tenths after the swap
            self.assertTrue(ecs.lost(ended=lambda: {S: 1}))  # the supervisor's count of that bundle grew: its process is gone
            self.assertEqual((ecs.active(), ecs.turned.is_set()), (True, True))  # in that instant
            # the pointer stays; the one statement withdraws the beat of the process that ended (LOST-BEAT-WITHDRAWN)
            self.assertEqual((table.sent[before:], table.value, table.events), ([live_image.WITHDRAW], S, []))
            self.assertFalse(ecs.pointed())  # it owes the role no live beat: the watch still sees the bundle silent
            for _ in range(5):  # five passes of work on the code it has, each with the standby's own watch
                table.clock.now += 1
                self.assertIsNone(ecs.cover())
                self.assertTrue(ecs.active())
            again = live_image.Gate(table.scope, role, S, task='promoted-again', strict=True, clock=table.clock, intask=True)
            self.assertTrue(again.refresh())  # the supervisor's new successor of the bundle: live as it starts
            again.live_beat()
            table.clock.now += 1
            ended = ecs.cover()
            # COVER-GAP: gap_s, the pointer's write to the cover: how long the role had no process
            self.assertEqual(ended, {'role': role, 'digest': S, 'task': 'ecs', 'state': 'covered', 'by': ECS,
                                     'covered_s': 6.0, 'end': 'live', 'gap_s': 0.2})
            self.assertEqual((ecs.active(), ecs.turned.is_set(), table.value, table.events, table.said),
                             (False, False, S, [], [ended]))  # it stands by again; nothing was taken back
            self.assertIsNone(ecs.cover())  # said once
            # and the new successor's first work is that swap's, late: recorded with the seconds since the pointer's write
            self.assertEqual(again.working()['notify_s'], 5.2)

    def test_a_cover_no_new_process_ends_is_the_watch_s_failover_at_the_registry_s_limit(self):
        table, promoted, ecs = self.swapped()
        ecs.lost(ended=lambda: {S: 1})
        said = []
        for _ in range(12):
            table.clock.now += 1
            said.append(ecs.cover())
            self.assertTrue(ecs.active())  # the role never stops: covering, then live with no pointer
        window = config_data.SPEC['deploy.live_stale_s'][1]
        self.assertEqual([each for each in said if each], [{'role': 'runner', 'digest': S, 'task': 'ecs', 'state': 'covered',
                                                           'by': ECS, 'covered_s': window + 1, 'end': 'failover',
                                                           'gap_s': 0.0}])
        self.assertEqual(table.events, [{'role': 'runner', 'digest': S, 'task': 'ecs', 'by': 'failover', 'stale_s': window + 1,
                                         'lost': True, 'id': f'platform.deploy.image_retired:runner:{S}:failover:1'}])
        self.assertEqual((table.value, ecs.live, ecs.covering), ('', True, None))

    def test_the_gap_is_counted_from_the_pointer_s_write_as_this_process_read_it(self):
        # COVER-GAP: the standing-by process read the pointer 0.05 s after its write (the notification's delay) and is told
        # 0.3 s after that read: the role had no process for 0.35 s
        table = Table('')
        ecs = gate_on(table, 'runner', ECS, task='ecs')
        ecs.refresh()
        table.write(S)
        table.clock.now += 0.05
        self.assertFalse(ecs.refresh())
        table.clock.now += 0.3
        ecs.lost(ended=lambda: {S: 1})
        table.clock.now += 4  # the boot of the supervisor's new successor
        again = gate_on(table, 'runner', S, strict=True, task='again')
        again.refresh()
        again.live_beat()
        table.clock.now += 1
        self.assertEqual(ecs.cover()['gap_s'], 0.35)
        self.assertEqual(medir.from_deploy_status({'successor': [{'state': 'covered', 'covered_s': 5.0, 'gap_s': 0.35},
                                                                 {'state': 'covered', 'covered_s': 2.0}]}),
                         {'image_swap_covered_s': [5.0, 2.0], 'image_swap_gap_s': [0.35]})

    def test_the_beat_of_a_successor_that_ended_is_withdrawn_at_once_so_no_landing_swaps_onto_it(self):
        """LOST-BEAT-WITHDRAWN: the landing swaps onto the beats of the last deploy.standby_fresh_s (3 s). A successor that
        ended kept a fresh beat for that long: a landing inside the window pointed the role at a process already gone.
        The role's process, told of the loss, withdraws that beat in the same instant, whatever the pointer says."""
        table = Table('')
        ecs = gate_on(table, 'runner', ECS, task='ip-1')
        ecs.refresh()
        standby = gate_on(table, 'runner', S, strict=True, task=live_image.heir_of('ip-1', S))
        standby.refresh()
        standby.beat()
        self.assertIn(('runner', S, f'ip-1:{S[:12]}'), table.beats)
        before = len(table.sent)
        self.assertFalse(ecs.lost(ended=lambda: {S: 1}))  # no pointer names it: nothing to cover
        self.assertEqual((table.sent[before:], table.withdrawn), ([live_image.WITHDRAW], [('runner', S, f'ip-1:{S[:12]}')]))
        self.assertNotIn(('runner', S, f'ip-1:{S[:12]}'), table.beats)  # the landing's statement finds no beat of the role
        self.assertFalse(ecs.lost(ended=lambda: {S: 1}))  # told again of the same loss: nothing more
        self.assertEqual(table.count(live_image.WITHDRAW), 1)
        self.assertFalse(standby.lost(ended=lambda: {S: 2}))  # a successor (strict) withdraws nobody's beat
        self.assertEqual(table.count(live_image.WITHDRAW), 1)
        table.broken = True
        with mock.patch.object(live_image.LOG, 'exception'):
            self.assertFalse(ecs.lost(ended=lambda: {S: 3}))  # never raises: the beat then ages out, as before

    def test_a_cover_ends_when_the_pointer_moves(self):
        table, promoted, ecs = self.swapped()
        ecs.lost(ended=lambda: {S: 1})
        table.clock.now += 1
        table.write('c' * 64)  # another landing swapped the role to its own bundle
        self.assertEqual(ecs.cover()['end'], 'moved')
        self.assertEqual((ecs.active(), ecs.pointer), (False, 'c' * 64))

    def test_only_the_role_s_process_standing_by_under_that_bundle_covers_and_once_for_each_loss(self):
        table, promoted, ecs = self.swapped()
        self.assertFalse(promoted.lost(ended=lambda: {S: 1}))  # a successor (strict) is not who takes a role
        self.assertFalse(ecs.lost(ended=lambda: {}))  # a state that cannot be read: nothing is known
        self.assertFalse(ecs.lost(ended=lambda: {'c' * 64: 1}))  # another bundle's successor ended: not the pointed one
        self.assertTrue(ecs.lost(ended=lambda: {S: 1, 'c' * 64: 1}))
        self.assertFalse(ecs.lost(ended=lambda: {S: 1, 'c' * 64: 1}))  # the same loss, told again
        table, promoted, ecs = self.swapped()
        table.write('')
        ecs.refresh()
        self.assertFalse(ecs.lost(ended=lambda: {S: 1}))  # it is live: there is nothing to cover (and the count is kept)
        table.write(S)
        ecs.refresh()
        self.assertFalse(ecs.lost(ended=lambda: {S: 1}))  # that loss was before this swap
        self.assertTrue(ecs.lost(ended=lambda: {S: 2}))
        gone = gate_on(Table(S), 'runner', ECS, task='ecs')
        gone.refresh()
        gone.gone = True
        self.assertFalse(gone.lost(ended=lambda: {S: 1}))  # it gave its role away: it never takes work again

    def test_the_two_roles_look_at_their_cover_on_every_live_pass_and_hear_their_supervisor(self):
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        serve, run = main[main.index('def serve('):main.index('def connection(')], main[main.index('def run_container('):]
        self.assertLess(serve.index('gate.back()  # IMAGE-SWAP-RELOAD'), serve.index('gate.cover(loop)  # SUCCESSOR-LOST'))
        self.assertIn('gate.cover(self.db)  # SUCCESSOR-LOST', (ROOT / 'infra/service/tower_infra/runner.py').read_text())
        for text in (serve, run):
            self.assertIn('live_image.orphaned(gate)  # SUCCESSOR-LOST', text)
        # SUCCESSOR-BACK-FAST: a successor that starts under a pointer that already names it opens its slots at once:
        # its task is warm, and the task's warm-up was 3.2 of the 5.9 s the role's new code took at the drill of 12/11
        self.assertIn('late = gate is not None and intask and gate.active() and gate.pointed()', run)
        self.assertIn('(None if gate is not None and (os.environ.get(code_bundle.RELOADED) or late)', run)
        self.assertLess(run.index('late = gate is not None'), run.index("task_up('runner'"))

    def test_the_supervisor_s_signal_only_sets_an_event_and_a_thread_asks_the_gate(self):
        gate, started, told = mock.Mock(), [], []
        with mock.patch.object(live_image.signal, 'signal') as handled, \
                mock.patch.object(live_image.supervisor, 'heeds', side_effect=lambda environ=None: told.append(environ)):
            self.assertIsNone(live_image.orphaned(None, environ={'TOWER_SUPERVISOR': '/spool'}))  # no gate: nothing to cover
            self.assertIsNone(live_image.orphaned(gate, environ={}))  # no supervisor: nobody would tell
            thread = live_image.orphaned(gate, start=lambda target: started.append(target) or mock.Mock(),
                                         environ={'TOWER_SUPERVISOR': '/spool'})
        self.assertIsNotNone(thread)
        (signum, handler), _ = handled.call_args
        self.assertEqual((signum, told), (live_image.signal.SIGUSR2, [{'TOWER_SUPERVISOR': '/spool'}]))  # told it heeds, last
        handler(signum, None)  # the signal: no statement here, the thread's wait ends
        gate.lost.assert_not_called()
        gate.lost.side_effect = [RuntimeError('the state was half written'), SystemExit]  # never raises; the test's way out
        with mock.patch.object(live_image.LOG, 'exception'), self.assertRaises(SystemExit):
            waited = threading.Event()
            real_wait = threading.Event.wait

            def wait(self, timeout=None):  # the second wait would block: the handler runs again, as a second signal
                if waited.is_set():
                    handler(signum, None)
                waited.set()
                return real_wait(self, timeout)
            with mock.patch.object(threading.Event, 'wait', wait):
                started[0]()
        self.assertEqual(gate.lost.call_count, 2)


class TheSuccessorBack(unittest.TestCase):
    """SUCCESSOR-BACK-FASTER and BOOT-PARTS: the successor its supervisor starts after the swap's own ended is what the
    role waits for. Live 12/11 16:25 UTC it worked 4.57 s after the pointer's write: 2.8 s of boot, 0.65 s before its
    slots opened (its start said first), 0.84 s of four logins at once, 0.28 s of the TAKE."""

    def test_the_other_slots_start_after_the_first_slot_s_first_pass_when_staggered(self):
        said, release = [], threading.Event()

        class Slot:
            passed = None

            def __init__(self, name):
                self.name = name

            def loop(self, stop, poll_s):
                said.append(self.name)
                if self.name == 'first':
                    release.wait(5)
                    said.append('first passed')
                    self.passed()
                    time.sleep(0.2)  # the others start now, while the first goes on

            def interrupt(self):
                pass
        slots = [Slot('first'), Slot('second'), Slot('third')]
        threading.Timer(0.2, release.set).start()
        runner.serve_all(slots, threading.Event(), staggered=True)
        self.assertEqual((said[:2], sorted(said[2:])), (['first', 'first passed'], ['second', 'third']))
        said.clear()
        slots = [Slot('first'), Slot('second')]
        slots[0].passed = lambda: None
        release.clear()
        threading.Timer(0.3, release.set).start()
        runner.serve_all(slots, threading.Event())  # any other process: every slot at once, as before
        self.assertEqual(sorted(said[:2]), ['first', 'second'])
        self.assertEqual(runner.STAGGER_S, 1.0)  # and a first slot that never passes holds the others a second at most

    def test_a_slot_says_its_first_good_pass_once(self):
        source = (ROOT / 'infra/service/tower_infra/runner.py').read_text(encoding='utf-8')
        loop = source[source.index('    def loop('):source.index('    def standby(')]
        self.assertLess(loop.index('self.beat()  # a good pass'), loop.index('passed, self.passed = self.passed, None'))

    def test_the_swap_s_record_of_a_late_successor_says_where_its_boot_went(self):
        table = Table(S)
        table.clock.now += 2.8  # the pointer was written 2.8 s before this process could read it
        with mock.patch.object(live_image.code_bundle, 'age_s', return_value=2.71), \
                mock.patch.dict(os.environ, {live_image.code_bundle.BOOT_ENTRY: '0.05', live_image.code_bundle.BOOT_CODE: '1.1'}):
            late = live_image.Gate(table.scope, 'runner', S, task='again', strict=True, clock=table.clock, intask=True)
            self.assertTrue(late.refresh())
        said = late.working()
        self.assertEqual({name: said[name] for name in ('notify_s', 'boot_s', 'boot_code_s', 'boot_entry_s')},
                         {'notify_s': 2.8, 'boot_s': 2.71, 'boot_code_s': 1.1, 'boot_entry_s': 0.05})
        table = Table('')
        usual = live_image.Gate(table.scope, 'runner', S, task='usual', strict=True, clock=table.clock, intask=True)
        usual.refresh()
        table.write(S)
        usual.refresh()
        self.assertNotIn('boot_s', usual.working())  # a successor that stood by: its boot was long before the swap

    def test_the_record_of_a_reserve_told_to_go_counts_its_boot_from_the_word_and_says_its_gate_s_first_read(self):
        # RESERVE-NO-DB and BOOT-PARTS: the process was 840 s old when its supervisor told it to go; 3.1 s later its gate
        # had read the pointer, and of those the read itself (its login and the statement) is said apart
        table = Table(S)

        def slow():  # the gate's first read takes 1.2 s of the table's clock: a login on the swap's second
            table.clock.now += 1.2
            return table.scope()
        with mock.patch.object(live_image.code_bundle, 'age_s', return_value=843.1), \
                mock.patch.dict(os.environ, {live_image.code_bundle.WENT: '840.0'}):
            went = live_image.gate('service', S, slow, task='held', strict=True, intask=True, clock=table.clock)
        self.assertEqual(went.boot, {'boot_s': 3.1, 'held_s': 840.0, 'reserve': True, 'read_s': 1.2})
        said = went.working()
        self.assertEqual({name: said[name] for name in ('boot_s', 'held_s', 'reserve', 'read_s')},
                         {'boot_s': 3.1, 'held_s': 840.0, 'reserve': True, 'read_s': 1.2})
        calm = live_image.gate('service', S, Table('').scope, task='calm', strict=True, intask=True, clock=table.clock)
        self.assertEqual(calm.boot, {})  # a successor that stands by says no boot: nobody waited for it
        # LATE-LAUNCH-SAID: the launch of the process the role waits for is said apart in that swap's record
        self.assertTrue(live_image.launched(went, 9.9571))
        self.assertEqual(went.boot['launch_s'], 9.957)
        self.assertFalse(live_image.launched(calm, 2.0))  # a standby's launch is no part of a swap
        self.assertFalse(live_image.launched(None, 2.0))  # no gate: no record
        # LATE-SETUP-SAID: and where the seconds between its gate's read and its first pass went, in that record
        went.read_at = table.clock.now  # (the table's clock moved with the record's own statements)
        table.clock.now += 0.25
        self.assertEqual(live_image.mark(went, 'dbos'), 0.25)
        table.clock.now += 0.31
        live_image.mark(went, 'launched')
        table.clock.now += 0.1
        live_image.mark(went, 'loop')
        self.assertEqual(went.boot['after_read'], {'dbos': 0.25, 'launched': 0.56, 'loop': 0.66})  # what the record carries (timed.update(self.boot))
        self.assertIsNone(live_image.mark(calm, 'dbos'))  # a process nobody waited for says nothing
        self.assertIsNone(live_image.mark(None, 'dbos'))
        self.assertNotIn('after_read', calm.boot)
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        for name in ("live_image.mark(gate, 'dbos')", "live_image.mark(gate, 'launched')", "live_image.mark(gate, 'settings')",
                     "live_image.mark(gate, 'loop')"):
            self.assertIn(name, source)
        self.assertLess(source.index("live_image.mark(gate, 'loop')"), source.index('while not stop.is_set():'))
        self.assertIn("sinks = subscriptions.Sinks(sns_of=lambda: boto3.client('sns'", source)  # no client on the swap's way
        serve = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertLess(serve.index('if not launch():'), serve.index('live_image.launched(gate, launch.seconds)'))


class TheDrill(unittest.TestCase):
    """SWAP-DRILL: the standby lost at the instant of the swap, induced by an event (POST /v1/deploy/drill)."""

    def successor(self, drill=True, intask=True, strict=True):
        table = Table('')
        table.drill = drill
        gate = live_image.Gate(table.scope, 'runner', S, task='successor', strict=strict, clock=table.clock, intask=intask)
        gate.exit = mock.Mock()
        gate.refresh()
        return table, gate

    def test_a_successor_a_drill_names_ends_as_it_turns_live_with_no_handback(self):
        table, gate = self.successor()
        self.assertTrue(gate.arm(table))
        self.assertEqual(table.asked, {'role': 'runner', 'digest': S, 'born': live_image.BORN})  # a drill newer than itself
        gate.exit.assert_not_called()  # armed while it stands by: nothing happens until the swap
        before = len(table.sent)
        table.write(S)
        gate.refresh()
        gate.exit.assert_called_once_with(live_image.DRILL_EXIT)
        self.assertEqual(table.sent[before:], [live_image.READ])  # the read that turned it live: no handback, no beat withdrawn

    def test_no_drill_no_end_and_only_a_successor_in_its_task_is_ever_armed(self):
        for how in ({'drill': False}, {'intask': False}, {'strict': False}):
            table, gate = self.successor(**how)
            self.assertFalse(gate.arm(table))
            table.write(S)
            gate.refresh()
            gate.exit.assert_not_called()
        table, gate = self.successor()
        table.broken = True
        with mock.patch.object(live_image.LOG, 'exception'):
            self.assertFalse(gate.arm(table))  # a drill that cannot be read is no drill


class TheHandback(unittest.TestCase):
    def promoted(self, role='service', pointer=S):
        table = Table(pointer)
        standby, ecs = gate_on(table, role, S, strict=True, task='promoted'), gate_on(table, role, ECS, task='ecs')
        standby.refresh()
        ecs.refresh()
        standby.beat()
        standby.live_beat()
        return table, standby, ecs

    def test_a_promoted_standby_that_is_stopping_gives_its_role_back_and_the_ecs_task_works_at_once(self):
        for role in ('service', 'runner'):
            table, standby, ecs = self.promoted(role)
            before = len(table.sent)
            self.assertTrue(standby.handback())
            self.assertEqual(table.sent[before:], [live_image.LEAVE])  # one statement
            self.assertEqual(table.events, [{'role': role, 'digest': S, 'task': 'promoted', 'by': 'handback',
                                             'id': f'platform.deploy.image_retired:{role}:{S}:handback:promoted'}])
            self.assertEqual((table.value, table.beats, table.live), ('', {}, {}))  # the pointer emptied, its beat withdrawn
            table.clock.now += 1
            ecs.beat()  # the ECS task's next pass: live, with no stale window to wait for
            self.assertTrue(ecs.active())
            self.assertEqual([each['by'] for each in table.events], ['handback'])  # the watchdog had nothing to do
            sent = len(table.sent)
            standby.beat()
            standby.live_beat()
            self.assertEqual(len(table.sent), sent)  # a standby that is leaving beats no more

    def test_a_standby_not_promoted_only_withdraws_its_beat_and_an_ecs_task_hands_nothing_back(self):
        table, standby, ecs = self.promoted(pointer=ECS + '-older')
        self.assertEqual(table.beats, {('service', S, 'promoted'): 100.0})
        self.assertFalse(standby.handback())  # the compare-and-swap: a pointer that does not name it stays
        self.assertEqual((table.value, table.events, table.beats), (ECS + '-older', [], {}))
        sent = len(table.sent)
        self.assertIsNone(ecs.handback())
        self.assertEqual((len(table.sent), ecs.leaving), (sent, False))

    def test_a_handback_that_fails_never_raises_and_the_watchdog_is_the_net(self):
        table, standby, ecs = self.promoted()
        table.broken = True
        with self.assertLogs('tower_infra.live_image', 'ERROR'):
            self.assertFalse(standby.handback())
        table.broken = False
        table.clock.now += 11
        ecs.beat()
        self.assertEqual(([each['by'] for each in table.events], ecs.active()), (['failover'], True))

    def test_on_sigterm_the_handback_comes_before_the_stop_and_any_other_process_stops_as_before(self):
        def then():
            pass
        self.assertIs(live_image.on_term(None, None, then), then)  # no TOWER_IMAGE_DIGEST
        self.assertIs(live_image.on_term(gate_on(Table(S), 'runner', ECS), None, then), then)  # an ECS task
        table, standby, _ = self.promoted('runner')
        order, stopped = [], threading.Event()
        halt = live_image.on_term(standby, table.scope, lambda: order.append(('stop', table.value)) or stopped.set())
        self.assertEqual(order, [])  # nothing before the signal
        halt(signal.SIGTERM, None)
        self.assertTrue(stopped.wait(5))
        self.assertEqual((order, table.events[0]['by']), ([('stop', '')], 'handback'))  # handed back, then stopped

    def test_a_slow_database_never_holds_the_exit(self):
        table, standby, _ = self.promoted()
        held, stopped = threading.Event(), threading.Event()

        @contextlib.contextmanager
        def slow():
            held.wait(30)  # a connection that does not answer
            yield table
        with mock.patch.object(live_image, 'HANDBACK_S', QUICK):
            halt = live_image.on_term(standby, slow, stopped.set)
            began = time.monotonic()
            halt()
            self.assertTrue(stopped.wait(5))
        self.assertLess(time.monotonic() - began, 2)
        self.assertEqual((table.value, live_image.HANDBACK_S), (S, 5))  # not handed back: deploy.live_stale_s is the net
        held.set()

    def warned(self, state='healthy', pointer='', grace=30.0):
        """STANDBY-GRACE: a standby that is not promoted, its SIGTERM handler, and the event of its stop."""
        table = Table(pointer)
        table.standby_state = state
        standby = gate_on(table, 'service', S, strict=True, task='standby')
        standby.refresh()
        standby.beat()
        stopped = threading.Event()
        for name, value in (('GRACE_TICK_S', 0.01), ('GRACE_S', grace)):
            patch = mock.patch.object(live_image, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        return table, standby, live_image.on_term(standby, table.scope, stopped.set), stopped

    def test_a_standby_spot_warns_stands_by_is_promoted_and_leaves_once_the_ecs_task_took_the_role_over(self):
        table, standby, halt, stopped = self.warned()
        halt(signal.SIGTERM, None)
        self.assertFalse(stopped.wait(0.2))  # warned, not dismissed: it stays, and it still beats
        table.beats.clear()
        standby.beat()
        self.assertIn(('service', S, 'standby'), table.beats)
        table.write(S)  # a landing swaps onto its fresh beat
        self.assertTrue(standby.refresh())
        self.assertFalse(stopped.wait(0.2))  # promoted: it works through the swap
        table.write('')  # the ECS task reloaded and took the role over (handover)
        standby.refresh()
        self.assertTrue(stopped.wait(5))
        self.assertNotIn(('service', S, 'standby'), table.beats)  # its beat withdrawn on the way out
        self.assertEqual(table.events, [])  # nothing to hand back: the pointer was already the ECS task's

    def test_the_grace_that_runs_out_ends_with_the_handback_when_the_pointer_still_names_the_standby(self):
        table, standby, halt, stopped = self.warned(grace=0.3)
        halt()
        table.write(S)
        standby.refresh()
        self.assertTrue(stopped.wait(5))
        self.assertEqual((table.value, [each['by'] for each in table.events]), ('', ['handback']))
        table, standby, halt, stopped = self.warned(grace=0.1)  # never promoted: it just leaves when the grace ends
        halt()
        self.assertTrue(stopped.wait(5))
        self.assertEqual(table.events, [])

    def test_a_standby_the_engine_dismissed_or_one_that_cannot_ask_leaves_at_once(self):
        for state, broken in (('stopped', False), ('healthy', True)):
            table, standby, halt, stopped = self.warned(state)
            table.broken = broken
            began = time.monotonic()
            with self.assertLogs('tower_infra.live_image', 'ERROR') if broken else contextlib.nullcontext():
                halt()
                self.assertTrue(stopped.wait(5))
            self.assertLess(time.monotonic() - began, 2)  # no grace: prewarm stopped it (a newer push, a deleted branch)
        table, standby, halt, stopped = self.warned(pointer=S)  # promoted before the warning: the handback first, as before
        halt()
        self.assertTrue(stopped.wait(5))
        self.assertEqual([each['by'] for each in table.events], ['handback'])

    def test_the_wiring_of_both_roles(self):
        halt = SERVE.index('halt = live_image.on_term(gate, quick(database, where, user, password), stop.set)')
        self.assertLess(halt, SERVE.index('signal.signal(signum, lambda *_: halt())'))
        self.assertLess(halt, SERVE.index('DBOS.destroy()'))  # the pointer first: stop is only set after the handback
        run = MAIN[MAIN.index('def run_container('):MAIN.index('\ndef ', MAIN.index('def run_container(') + 1)]
        # SPOT-KEEP: the handback first, then the task's process keeps its slots until its replacement is up
        self.assertIn('term=lambda interrupt: live_image.on_term(gate, quick(database, where, user, password), kept_on(interrupt)))', run)
        source = (ROOT / 'infra/service/tower_infra/runner.py').read_text(encoding='utf-8')
        self.assertIn('signal.signal(signal.SIGTERM, interrupt if term is None else term(interrupt))', source)

    def test_the_handbacks_connection_is_its_own_with_short_timeouts_and_is_closed(self):
        from tower_infra import __main__ as main
        made = []

        def connect(*who, **options):
            made.append((who, options, mock.Mock()))
            return made[-1][2]
        database = mock.Mock(password_connection=connect, iam_connection=connect, Database=lambda connection: connection)
        for password, who in (('secret', ({}, 'tower', 'secret')), (None, ({}, 'tower'))):  # a local run; the IAM token
            scope = main.quick(database, {}, 'tower', password)
            self.assertEqual(len(made), int(password is None))  # a new connection when used, none kept
            with scope() as db:
                db.close.assert_not_called()
            self.assertEqual(made[-1][:2], (who, {'purpose': 'quick', 'connect_timeout': 5,  # DB-LISTEN-ONE: its name
                                                  'options': '-c statement_timeout=5000'}))
            made[-1][2].close.assert_called_once_with()


class TheMeasure(unittest.TestCase):
    def test_scripts_medir_shows_how_long_each_failover_found_the_role_without_a_live_beat(self):
        status = {'image_retired': [{'by': 'failover', 'role': 'service', 'stale_s': 10.412},
                                    {'by': 'handback', 'role': 'runner'}, {'by': 'failover', 'stale_s': True},
                                    {'by': 'reconciled', 'stale_s': 3}, {'by': 'failover', 'stale_s': 11}, 'junk']}
        self.assertEqual(medir.from_deploy_status(status), {'image_failover_s': [10.412, 11.0]})
        self.assertNotIn('image_failover_s', medir.from_deploy_status({'image_retired': [{'by': 'handback'}]}))


class AHalfEmptiedPair(image_swap.World):
    """One role failed over (its pointer emptied), the other still on the promoted standby: the autodeploy's way back
    takes the pair as it is, and nothing fights over a pointer."""

    def failed_over(self, role, live=('runner', 'service')):
        self.land()
        self.db.live = set(live)
        self.db.pointer[live_image.KEYS[role]] = ''  # the ECS task's failover (or the standby's handback)

    def retired(self):
        return [each for kind, each in self.db.events if kind == 'platform.deploy.image_retired']

    def test_the_other_role_stays_promoted_until_the_reconciliation_empties_only_its_pointer(self):
        self.failed_over('service')
        self.now[0] = 100.0 + 10 * autodeploy.SWAP_LIMIT_S
        self.watcher.settle_image(self.db, self.heads)  # both took work at the swap: nothing to undo
        self.assertEqual((self.db.pointer[live_image.KEYS['runner']], self.retired()), (image_swap.S, []))
        self.params[autodeploy.LAST_BUILD] = json.dumps({'status': 'succeeded', 'base_head': image_swap.MERGE,
                                                         'ended': 2000, 'build_id': 'b:1'})
        self.watcher.settle_image(self.db, self.heads)
        [event] = self.retired()
        self.assertEqual((event['by'], event['keys']), ('reconciled', [live_image.KEYS['runner']]))

    def test_the_revert_of_a_swap_one_standby_never_took_empties_what_is_left_and_writes_nothing_after(self):
        self.failed_over('service', live=('runner',))  # the service standby died at the swap: failed over after 10 s
        self.now[0] = 100.0 + autodeploy.SWAP_LIMIT_S + 1
        self.watcher.settle_image(self.db, self.heads)
        [event] = self.retired()
        self.assertEqual((event['by'], event['keys']), ('revert', [live_image.KEYS['runner']]))
        self.watcher.settle_image(self.db, self.heads)  # both emptied (failover, then revert): one event each, no fight
        self.assertEqual(len(self.retired()), 1)


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements on the migrated tables: the live beat of a promoted pair, and the failover of each role by the
    ECS task standing by, with deploy.live_stale_s written through PUT /v1/config."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db

    def put(self, key, value):
        return self.world.port('PUT', f'/v1/config/{key}', 'torre', {'value': value, 'reason': 'test'})

    def gate(self, role, digest, strict=False, task=None):
        return live_image.gate(role, digest, live_image.kept(self.db), task=task or f'{role}-{digest[:3]}', strict=strict)

    def beats(self):
        return self.db.rows("select role, task, live_at is not null, extract(epoch from live_at)::text "
                            "from work.standby_beat order by role, task")

    def slot(self, gate, name, **more):
        return runner.Runner(self.db, self.world.fetch, self.world.prepare, self.world.upload, self.world.workdir,
                             name=name, gate=gate, **{'renew_every_s': QUICK, **more})

    def test_a_standby_beats_beat_at_and_a_promoted_one_live_at(self):
        self.put('deploy.live_image_service', ECS)
        standby = self.gate('service', S, strict=True, task='standby')
        standby.beat()
        self.assertEqual([row[:3] for row in self.beats()], [('service', 'standby', 'f')])
        self.assertFalse(standby.live_beat())  # not the pointer's: nothing
        self.put('deploy.live_image_service', S)
        standby.refresh()
        self.assertTrue(standby.live_beat())
        self.assertEqual([row[:3] for row in self.beats()], [('service', 'standby', 't')])
        fresh = self.db.rows("select count(*) from work.standby_beat where live_at - beat_at < interval '1 second'")
        self.assertEqual(fresh, [('1',)])  # beat_at with it: the landing still counts the image healthy

    def test_a_runner_with_every_slot_busy_keeps_its_live_beat(self):
        self.put('deploy.live_image_runner', S)
        gate = self.gate('runner', S, strict=True, task='promoted')
        job = self.world.job('long', 'sleep 1.2')
        mechanisms.dispatch(self.db)
        seen = []
        with mock.patch.object(live_image, 'LIVE_BEAT_S', QUICK * 2):
            thread = threading.Thread(target=self.slot(gate, 'promoted', renew_every_s=60.0).once, daemon=True)
            thread.start()  # the only slot, in a run far from its first lease renewal
            while thread.is_alive():
                seen.extend(row[3] for row in self.beats())
                time.sleep(QUICK * 2)
            thread.join()
        self.assertEqual(self.world.state(job), 'succeeded')
        self.assertGreaterEqual(len(set(seen)), 3)  # live_at moved on while the slot was busy

    STALE_S = float('0.6')  # deploy.live_stale_s in these tests; the live beat every 0.1 s

    def pointer(self, role):
        found = self.db.rows("select value::text from work.config_value where key = %(key)s", {'key': live_image.KEYS[role]})
        return json.loads(found[0][0]) if found else None

    def retired(self):
        return [json.loads(row[0]) for row in self.db.rows(
            "select payload::text from log.event where type = 'platform.deploy.image_retired' order by occurred_at")]

    def promoted_pair(self):
        self.put('deploy.live_stale_s', self.STALE_S)
        for role in ('runner', 'service'):
            self.put(f'deploy.live_image_{role}', S)

    def took(self, job):
        return [row[0] for row in self.db.rows(
            "select payload->>'runner' from log.event where type = 'run.running' and payload->>'job_id' = %(id)s "
            "order by occurred_at", {'id': job})]

    def test_a_promoted_service_that_stops_beating_is_failed_over_and_the_ecs_service_dispatches_the_queue(self):
        workflows = workflows_with([])
        self.promoted_pair()
        promoted, ecs = self.gate('service', S, strict=True, task='promoted'), self.gate('service', ECS, task='ecs')
        self.assertEqual((promoted.active(), ecs.active()), (True, False))

        @contextlib.contextmanager
        def connected():
            yield self.db

        def tick():
            return workflows.tick('5 minutes')
        with mock.patch.object(workflows, 'connected', connected), mock.patch.object(live_image, 'LIVE_BEAT_S', 0.1):
            until = time.monotonic() + 2 * self.STALE_S
            while time.monotonic() < until:  # the promoted service ticks for twice the window: never failed over
                service_pass(promoted, tick)
                service_pass(ecs, tick)
            self.assertEqual((self.pointer('service'), ecs.active(), self.retired()), (S, False, []))
            job = self.world.job('queued', 'true')  # it arrives as the promoted service dies with no handback
            died = time.monotonic()
            while not ecs.active() and time.monotonic() - died < 30:
                service_pass(ecs, tick)
                time.sleep(QUICK)
            took = time.monotonic() - died
            service_pass(ecs, tick)  # live in the pass that failed over: its next pass dispatches
        self.assertEqual(self.db.rows("select state from work.run where job_id = %(id)s::uuid", {'id': job}), [('starting',)])
        self.assertLess(took, self.STALE_S + 3)  # deploy.live_stale_s and one pass (psql per statement here)
        [event] = self.retired()
        self.assertEqual((event['by'], event['role'], event['digest'], event['task'], event['keys']),
                         ('failover', 'service', S, 'ecs', [live_image.KEYS['service']]))
        self.assertGreaterEqual(event['stale_s'], self.STALE_S)  # past the window (rounded to the millisecond)
        self.assertLess(event['stale_s'], self.STALE_S + 3)
        self.assertEqual((self.pointer('service'), self.pointer('runner')), ('', S))  # the runner's role is its own
        self.assertEqual((promoted.refresh(), promoted.retired), (False, True))
        status = self.world.port('GET', '/v1/deploy/status', 'torre')
        self.assertIsInstance(status['image_retired'][0].pop('at'), float)  # STATUS-EVENTS-AT
        self.assertEqual(status['image_retired'], [event])
        self.assertEqual(medir.from_deploy_status(status), {'image_failover_s': [event['stale_s']]})

    def test_a_promoted_runner_that_dies_is_failed_over_and_the_ecs_runner_takes_the_queued_run(self):
        self.promoted_pair()
        gates = {'promoted': self.gate('runner', S, strict=True, task='promoted'), 'ecs': self.gate('runner', ECS, task='ecs')}
        stops = {name: threading.Event() for name in gates}
        with mock.patch.object(live_image, 'LIVE_BEAT_S', 0.1):
            threads = {name: threading.Thread(target=self.slot(gate, name).loop, args=(stops[name], QUICK), daemon=True)
                       for name, gate in gates.items()}
            for thread in threads.values():
                thread.start()
            first = self.world.job('first', 'true')
            mechanisms.dispatch(self.db)
            deadline = time.monotonic() + 30
            while self.world.state(first) != 'succeeded' and time.monotonic() < deadline:
                time.sleep(QUICK)
            time.sleep(2 * self.STALE_S)  # idle and beating for twice the window: never failed over
            self.assertEqual((self.pointer('runner'), self.retired()), (S, []))
            stops['promoted'].set()  # the promoted runner dies with no handback
            threads['promoted'].join(10)
            died = time.monotonic()
            second = self.world.job('second', 'true')
            mechanisms.dispatch(self.db)
            while self.world.state(second) != 'succeeded' and time.monotonic() - died < 30:
                time.sleep(QUICK)
            took = time.monotonic() - died
            stops['ecs'].set()
            threads['ecs'].join(10)
        self.assertEqual((self.world.state(second), self.took(first), self.took(second)), ('succeeded', ['promoted'], ['ecs']))
        self.assertLess(took, self.STALE_S + 5)  # the window, one pass and the run itself
        [event] = self.retired()
        self.assertEqual((event['by'], event['role'], event['digest'], event['keys']),
                         ('failover', 'runner', S, [live_image.KEYS['runner']]))
        self.assertEqual((self.pointer('runner'), self.pointer('service')), ('', S))

    def test_sigterm_to_a_promoted_runner_hands_the_pointer_back_before_its_slots_stop_and_the_ecs_runner_takes_the_run(self):
        self.promoted_pair()
        self.put('deploy.live_stale_s', 60.0)  # the watchdog is out of this test's reach: only the handback can do it
        promoted, ecs = self.gate('runner', S, strict=True, task='promoted'), self.gate('runner', ECS, task='ecs')
        mark = Path(self.world.workdir) / 'ran-once'
        job = self.world.job('interrupted', f'if [ -f {mark} ]; then exit 0; fi; touch {mark}; sleep 30')
        mechanisms.dispatch(self.db)
        order, ecs_stop = [], threading.Event()

        def term(interrupt):
            def then():
                order.append(('slots interrupted', self.pointer('runner')))
                interrupt()
            return live_image.on_term(promoted, live_image.kept(self.db), then)

        def spot():
            deadline = time.monotonic() + 60
            while not self.world.running(job) and time.monotonic() < deadline:
                time.sleep(QUICK)
            order.append(('SIGTERM', self.pointer('runner')))
            os.kill(os.getpid(), signal.SIGTERM)  # what Fargate sends a Spot task two minutes before it stops
            while self.world.state(job) != 'succeeded' and time.monotonic() < deadline:
                mechanisms.dispatch(self.db)  # the dispatcher: the lost run's job is handed over again
                time.sleep(QUICK)
            ecs_stop.set()
        standing_by = threading.Thread(target=self.slot(ecs, 'ecs').loop, args=(ecs_stop, QUICK), daemon=True)
        interruption = threading.Thread(target=spot, daemon=True)
        standing_by.start()
        interruption.start()
        slots = [self.slot(promoted, 'promoted')]
        slots[0].grace_s = 0.5  # RUNNER-TERM-GRACE: this run does not end in the grace: lost, and the ECS runner's
        runner.serve_all(slots, threading.Event(), poll_s=QUICK, term=term)  # the main thread, where SIGTERM is handled
        interruption.join(90)
        standing_by.join(10)
        self.assertEqual(order, [('SIGTERM', S), ('slots interrupted', '')])  # the pointer first, then the slots
        self.assertTrue(slots[0].interrupted)
        self.assertEqual((self.world.state(job), self.took(job)), ('succeeded', ['promoted', 'ecs']))  # lost, taken again
        [event] = self.retired()
        self.assertEqual((event['by'], event['role'], event['digest'], event['task'], event['keys']),
                         ('handback', 'runner', S, 'promoted', [live_image.KEYS['runner']]))
        self.assertEqual((self.pointer('runner'), self.pointer('service')), ('', S))
        self.assertEqual(self.db.rows("select task from work.standby_beat where task = 'promoted'"), [])

    def test_sigterm_to_a_promoted_service_hands_the_pointer_back_before_it_stops_and_the_ecs_service_dispatches(self):
        workflows = workflows_with([])
        self.promoted_pair()
        self.put('deploy.live_stale_s', 60.0)  # only the handback can do it
        promoted, ecs = self.gate('service', S, strict=True, task='promoted'), self.gate('service', ECS, task='ecs')
        stop, ecs_stop, seen = threading.Event(), threading.Event(), []

        def stopped():
            seen.append(self.pointer('service'))  # what the pointer says when the service stops taking work
            stop.set()
        halt = live_image.on_term(promoted, live_image.kept(self.db), stopped)
        self.addCleanup(signal.signal, signal.SIGTERM, signal.signal(signal.SIGTERM, lambda *_: halt()))  # as serve does

        @contextlib.contextmanager
        def connected():
            yield self.db

        def tick():
            return workflows.tick('5 minutes')

        def ecs_service():
            while not ecs_stop.is_set():
                service_pass(ecs, tick)
                time.sleep(QUICK)
        with mock.patch.object(workflows, 'connected', connected):
            standing_by = threading.Thread(target=ecs_service, daemon=True)
            standing_by.start()
            threading.Timer(0.5, os.kill, (os.getpid(), signal.SIGTERM)).start()  # Spot's warning, or a StopTask
            deadline = time.monotonic() + 60
            while not stop.is_set() and time.monotonic() < deadline:  # serve's loop, in the main thread
                service_pass(promoted, tick)
                time.sleep(QUICK)
            job = self.world.job('queued', 'true')  # after the promoted service stopped
            claimed = []
            while not claimed and time.monotonic() < deadline:
                claimed = self.db.rows("select state from work.run where job_id = %(id)s::uuid", {'id': job})
                time.sleep(QUICK)
            ecs_stop.set()
            standing_by.join(10)
        self.assertEqual((stop.is_set(), seen), (True, ['']))  # handed back before it stopped
        self.assertEqual((claimed, ecs.active()), ([('starting',)], True))  # the ECS service dispatched it
        [event] = self.retired()
        self.assertEqual((event['by'], event['role'], event['task'], event['keys']),
                         ('handback', 'service', 'promoted', [live_image.KEYS['service']]))
        self.assertEqual((self.pointer('service'), self.pointer('runner')), ('', S))
        said = self.world.port('GET', '/v1/deploy/status', 'torre')['image_retired']
        self.assertIsInstance(said[0].pop('at'), float)  # STATUS-EVENTS-AT
        self.assertEqual(said, [event])

    def test_a_pointer_naming_a_digest_nobody_runs_is_emptied_and_the_ecs_runner_works_again(self):
        # the live proof of the watchdog (aws.md 22.9): no promotion and no AWS call, one PUT per role
        self.put('deploy.live_stale_s', self.STALE_S)
        ecs, stop = self.gate('runner', ECS, task='ecs'), threading.Event()
        self.assertTrue(ecs.active())  # no pointer: the ECS runner works, as always
        thread = threading.Thread(target=self.slot(ecs, 'ecs').loop, args=(stop, QUICK), daemon=True)
        thread.start()
        self.put('deploy.live_image_runner', 'failover-probe')
        ecs.refresh()  # what the tower_config notification runs
        self.assertFalse(ecs.active())
        job = self.world.job('waiting', 'true')
        mechanisms.dispatch(self.db)
        deadline = time.monotonic() + 30
        while self.world.state(job) != 'succeeded' and time.monotonic() < deadline:
            time.sleep(QUICK)
        stop.set()
        thread.join(10)
        [event] = self.retired()
        self.assertEqual((event['by'], event['role'], event['digest'], event['task']), ('failover', 'runner', 'failover-probe', 'ecs'))
        self.assertGreaterEqual(event['stale_s'], self.STALE_S)
        self.assertEqual((self.world.state(job), self.took(job), self.pointer('runner')), ('succeeded', ['ecs'], ''))

    def test_a_busy_runner_with_every_slot_in_a_long_run_is_not_failed_over(self):
        self.promoted_pair()
        # the window is 2 s here, not the class's 0.6 s: every statement of these tests is a psql process, and on a runner
        # shared by two deliveries (the gate's red of #537, 11/11) two live beats came more than 0.6 s apart and the busy
        # runner was failed over. What is held is the same: a run of several windows, and no failover
        stale = 2.0
        self.put('deploy.live_stale_s', stale)
        promoted, ecs = self.gate('runner', S, strict=True, task='promoted'), self.gate('runner', ECS, task='ecs')
        job = self.world.job('long', f'sleep {2.5 * stale}')
        mechanisms.dispatch(self.db)
        stop = threading.Event()
        with mock.patch.object(live_image, 'LIVE_BEAT_S', 0.1):
            watching = threading.Thread(target=self.slot(ecs, 'ecs').loop, args=(stop, QUICK), daemon=True)
            watching.start()
            self.slot(promoted, 'promoted', renew_every_s=60.0).once()  # its only slot, two windows and a half in one run
            stop.set()
            watching.join(10)
        self.assertEqual((self.world.state(job), self.took(job)), ('succeeded', ['promoted']))
        self.assertEqual((self.pointer('runner'), self.retired(), ecs.active()), (S, [], False))


if __name__ == '__main__':
    unittest.main()
