"""SWAP-TAIL-CUT (docs/operations/aws.md 22.9; the architecture review's finding 19): what the swap's evidence cut.

The record of #518's swap (11/11, SWAP-TAIL-EVIDENCE) showed, at the instant the promoted pair took its first work, five
backends in the standby beat (each slot of a runner wrote the same row, and every beat swept the whole table), up to
253 ms each, and the promoted service's first reap and first roll of the limits at 0.3 s each: first calls on a cold
backend. A process beats once a pass; the sweep is the live service's hourly statement; a prewarm standby runs its
role's first statements, rolled back, on the connection that will run them.

Hermetic: the gate over a stand-in database with an injected clock; a stand-in psycopg connection for the warm-up.
"""
import contextlib
import json
import logging
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from tower_infra import live_image, mechanisms, runner  # noqa: E402
from test_infra_swap_failover import Clock, Table, gate_on, S, ECS  # noqa: E402


def setUpModule():
    logging.disable(logging.CRITICAL)  # a warm-up that fails is logged on purpose


def tearDownModule():
    logging.disable(logging.NOTSET)


class Slot:
    """One slot's connection over the shared table: the gate tells them apart by the object."""

    def __init__(self, table):
        self.table = table

    def rows(self, sql, params=None):
        return self.table.rows(sql, params)


class OneBeatAPass(unittest.TestCase):
    def test_the_slots_of_a_process_beat_once_a_pass_and_one_connection_always_beats(self):
        for strict, statement in ((True, live_image.BEAT), (False, live_image.WATCH)):
            table = Table('' if strict else S)
            gate = gate_on(table, 'runner', S if strict else ECS, strict=strict, task='task')
            gate.refresh()
            slots = [Slot(table) for _ in range(4)]
            for each in slots:  # the four slots' passes, a fraction of a second apart
                gate.beat(each)
                table.clock.now += 0.2
            self.assertEqual(table.count(statement), 1)  # the first slot's; the others are answered with what it read
            table.clock.now += 0.4  # a second after the first beat: the next pass
            gate.beat(slots[0])
            gate.beat(slots[1])
            self.assertEqual(table.count(statement), 2)
            for _ in range(3):  # one connection alone (the service's loop) beats on every pass, however close
                gate.beat(slots[0])
            self.assertEqual(table.count(statement), 5)
            gate.beat()  # the gate's own scope: no connection to tell apart, always sent
            self.assertEqual(table.count(statement), 6)

    def test_a_slot_that_was_answered_reads_what_the_beating_one_read(self):
        table = Table(S)
        gate = gate_on(table, 'runner', ECS, task='task')
        gate.refresh()
        first, other = Slot(table), Slot(table)
        found = gate.beat(first)
        self.assertEqual(found[0][0], S)  # the pointer, as WATCH read it
        self.assertIs(gate.beat(other), found)

    def test_no_beat_sweeps_and_the_live_service_sweeps_on_its_hourly_pass(self):
        for statement in (live_image.BEAT, live_image.WATCH, live_image.LIVE_BEAT):
            self.assertNotIn('delete', statement)
        self.assertIn("beat_at < clock_timestamp() - interval '1 day'", live_image.SWEEP_OLD)
        sent = []

        class Db:
            def rows(self, sql, params=None):
                sent.append(sql)
                return []
        live_image.sweep(Db())
        self.assertEqual(sent, [live_image.SWEEP_OLD])

        class Away:
            def rows(self, sql, params=None):
                raise RuntimeError('the database is away')
        live_image.sweep(Away())  # never raises
        loop = (ROOT / 'infra/service/tower_infra/__main__.py').read_text()
        self.assertLess(loop.index('measured.record(db)'), loop.index('live_image.sweep(db)'))


class Connection:
    """A stand-in psycopg connection: transaction(force_rollback=True) and a cursor, with what was sent and rolled back."""

    def __init__(self, clock, cost):
        self.clock, self.cost, self.sent, self.rolled, self.fail = clock, cost, [], 0, False
        self.depth, self.savepoints = 0, []  # FIRST-JOB-REHEARSED: a transaction inside the warm-up's is a savepoint

    @contextlib.contextmanager
    def transaction(self, force_rollback=False):
        assert force_rollback or self.depth  # a standby's warm-up never commits: only a savepoint inside it may
        self.depth += 1
        try:
            yield
        except BaseException:
            if self.depth > 1:
                self.savepoints.append('rolled back')
            raise
        else:
            if self.depth > 1:
                self.savepoints.append('released')
        finally:
            self.depth -= 1
            if not self.depth:
                self.rolled += 1

    @contextlib.contextmanager
    def cursor(self):
        yield self

    description = True

    def execute(self, sql, params=None):
        if self.fail:
            raise RuntimeError('the database is away')
        self.sent.append((sql, params))
        self.clock.now += self.cost.pop(0) if self.cost else 0.001

    def fetchall(self):
        return []


class Kept:
    """container.Reconnecting's shape: ready() answers the database, which has the connection."""

    def __init__(self, connection):
        self.connection = connection

    def ready(self):
        return self


class TheWarmUp(unittest.TestCase):
    def make(self, strict=True, cost=None):
        table = Table('')
        gate = gate_on(table, 'service', S, strict=strict, task='standby')
        gate.refresh()
        statements = [(sql, None) for sql in (mechanisms.REAP, mechanisms.ROLL, mechanisms.WAKE, mechanisms.QUEUES)]
        warm = live_image.Warm(gate, statements, clock=table.clock)
        return table, gate, warm, Kept(Connection(table.clock, cost if cost is not None else [0.3, 0.25, 0.02, 0.01]))

    def test_a_standby_runs_its_first_pass_s_statements_rolled_back_when_it_starts_and_a_minute_apart(self):
        table, gate, warm, db = self.make()
        self.assertAlmostEqual(warm.step(db), 0.58)  # the cold calls
        self.assertEqual(([sql for sql, _ in db.connection.sent], db.connection.rolled),  # SWAP-RECORD-WARM: and the record's
                         ([mechanisms.REAP, mechanisms.ROLL, mechanisms.WAKE, mechanisms.QUEUES, live_image.REHEARSE], 1))
        self.assertIsNone(warm.step(db))  # not again within the minute
        table.clock.now += live_image.WARM_S
        self.assertAlmostEqual(warm.step(db), 0.004)  # warm
        self.assertEqual((db.connection.rolled, warm.said()), (2, {'warm_first_s': 0.58, 'warm_last_s': 0.004}))
        self.assertIs(gate.warm, warm)

    def test_a_standby_warms_again_when_its_gate_heard_a_notification(self):
        """READY-REHEARSAL: a standby warmed its connections when it started and a minute apart; on a host that pages
        (12/11: 420 to 620 MB in swap) a backend idle for seconds wakes to page faults, and the swap woke them all at
        once: the stall at the landing. The delivery at the front asks whether its successors are ready just before it
        merges; the port then notifies (tower_config, no row written) and every gate's listener reads the pointer, as
        at a swap. A standby whose gate read again warms each connection on its next pass, so what the swap will touch
        was touched a second or so before it."""
        table, gate, warm, db = self.make()
        other = Kept(Connection(table.clock, [0.4, 0.01, 0.01, 0.01]))
        warm.step(db)
        warm.step(other)
        self.assertIsNone(warm.step(db))  # within the minute, nothing heard: not again
        gate.refresh()  # the listener read the pointer again: the rehearsal's notification (or any other)
        self.assertAlmostEqual(warm.step(db), 0.004)
        self.assertAlmostEqual(warm.step(other), 0.004)  # each connection, on its own pass
        self.assertIsNone(warm.step(db))  # once for what was heard
        self.assertEqual((db.connection.rolled, other.connection.rolled), (2, 2))

    def test_each_connection_of_a_process_is_warmed_and_the_swap_s_record_carries_the_largest(self):
        table, gate, warm, first = self.make()
        other = Kept(Connection(table.clock, [0.4, 0.01, 0.01, 0.01]))
        warm.step(first)
        warm.step(other)  # a runner's slots: each warms the connection its own TAKE will use
        self.assertEqual((len(first.connection.sent), len(other.connection.sent)), (5, 5))  # the four, and the record's rehearsal
        self.assertEqual(warm.said(), {'warm_first_s': 0.58, 'warm_last_s': 0.58})
        table.write(S)  # the landing's swap
        gate.refresh()
        said = gate.working()
        self.assertEqual((said['warm_first_s'], said['warm_last_s']), (0.58, 0.58))

    def test_a_standby_rehearses_a_job_with_the_swap_s_record_and_the_record_says_what_it_cost(self):
        """FIRST-JOB-REHEARSED: the first job after a swap paid every statement of its path for the first time on its
        backend (live 12/11, nine swaps: the canary dispatched in 0.40 to 1.54 s, taken in 0.11 to 1.02 s; 0.03 to 0.10 s
        and 0.02 s warm). A job of no one goes through the whole path in the warm-up's transaction, after the record's
        rehearsal and when it runs: the connection's first warm-up and each notification, never on the minute."""
        table, gate, _, db = self.make()
        ran = []

        def job(cursor):
            ran.append((cursor, db.connection.depth, len(db.connection.sent)))
            table.clock.now += 0.7 if len(ran) == 1 else 0.03

        warm = live_image.Warm(gate, [(mechanisms.REAP, None)], clock=table.clock, job=job)
        self.assertAlmostEqual(warm.step(db), 0.3)  # the role's statements: the job's seconds are not the warm-up's
        self.assertEqual(ran, [(db.connection, 2, 2)])  # on the cursor, in a savepoint, after the statement and the record
        self.assertEqual((db.connection.savepoints, db.connection.rolled), (['released'], 1))  # and all of it rolled back
        self.assertEqual(warm.said(), {'warm_first_s': 0.3, 'warm_last_s': 0.3, 'job_first_s': 0.7, 'job_last_s': 0.7})
        table.clock.now += live_image.WARM_S
        warm.step(db)  # the minute's warm-up: no job (a rolled back insert leaves dead rows)
        self.assertEqual(len(ran), 1)
        gate.refresh()  # the delivery at the front asked whether its successors are ready
        warm.step(db)
        self.assertEqual((len(ran), warm.said()['job_first_s'], warm.said()['job_last_s']), (2, 0.7, 0.03))
        table.write(S)  # the landing's swap: the record carries what the rehearsal cost, cold and newest
        gate.refresh()
        said = gate.working()
        self.assertEqual((said['job_first_s'], said['job_last_s']), (0.7, 0.03))

    def test_a_job_s_rehearsal_that_fails_undoes_itself_and_the_warm_up_stands(self):
        table, gate, _, db = self.make()

        def job(cursor):
            raise RuntimeError('the dispatch claimed nothing')

        warm = live_image.Warm(gate, [(mechanisms.REAP, None)], clock=table.clock, job=job)
        with mock.patch.object(live_image.LOG, 'exception') as logged:
            self.assertAlmostEqual(warm.step(db), 0.3)  # never raises, and the statements' warm-up counts
        self.assertIn('did not rehearse a job', logged.call_args.args[0])
        self.assertEqual((db.connection.savepoints, db.connection.rolled), (['rolled back'], 1))
        self.assertEqual(warm.said(), {'warm_first_s': 0.3, 'warm_last_s': 0.3,  # no seconds of a job that did not run,
                                       'job_error': 'RuntimeError: the dispatch claimed nothing'})  # and the record says why

    def test_the_two_roles_rehearse_the_job_on_the_connections_that_do_their_first_work(self):
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        serve, run = main[main.index('def serve('):main.index('def connection(')], main[main.index('def run_container('):]
        self.assertIn("job=lambda cursor: rehearsal.job(rehearsal.Rows(cursor), 'service', lease, canary_of=gate.tenant))", serve)
        self.assertIn('job=lambda cursor: rehearsal.run(rehearsal.Rows(cursor)))', run)  # RUNNER-OWN-LOGIN: the owner's function
        self.assertIn('warm.step(loop)', serve)  # the loop's connection: the one that dispatches

    def test_an_ecs_task_a_stand_in_database_and_a_failure_are_left_alone(self):
        table, gate, warm, db = self.make(strict=False)
        self.assertIsNone(warm.step(db))  # an ECS task standing by is not the one a swap promotes
        self.assertEqual(db.connection.sent, [])
        table, gate, warm, db = self.make()
        self.assertIsNone(warm.step(Slot(table)))  # no psycopg connection behind it
        db.connection.fail = True
        self.assertIsNone(warm.step(db))  # never raises
        self.assertEqual(warm.said(), {})
        self.assertNotIn('warm_first_s', gate.working() or {})

    def test_an_in_task_successor_says_it_is_warm_once_after_its_first_warm_up(self):
        # READY-BEFORE-LANDING: live 11/11 (#539): the successors had started 6 to 10 s before the landing; they beat, so
        # the landing swapped, while the database was still busy with their start: 1.25 s. `up` is the first beat; `warm`
        # is what the delivery at the front waits for
        said = []
        table = Table('')
        gate = mock.Mock(strict=True, intask=True, role='runner', digest=S, task='task-1:' + S[:12])
        gate.sent.side_effect = lambda sql, params, db=None: said.append((sql, params))
        warm = live_image.Warm(gate, [(mechanisms.REAP, None)], clock=table.clock)
        first, other = (Kept(Connection(table.clock, [0.3])) for _ in range(2))
        warm.step(first)
        warm.step(other)  # another slot's connection: the process said it already
        table.clock.now += live_image.WARM_S
        warm.step(first)
        [(sql, params)] = said
        self.assertEqual((sql, params['id'], params['role']),
                         (live_image.UP, f'{live_image.SUCCESSOR}:runner:{S}:task-1:{S[:12]}:warm:{live_image.BORN}', 'runner'))  # WARM-PER-PROCESS
        said_warm = json.loads(params['payload'])
        # SUCCESSOR-MEMORY: and the most memory the process has held (the kernel's): what a successor costs its task
        self.assertGreater(said_warm.pop('rss_mb'), 1)
        self.assertEqual(said_warm, {'role': 'runner', 'digest': S, 'task': 'task-1:' + S[:12],
                                     'state': 'warm', 'warm_s': 0.3})
        self.assertEqual(live_image.rss(lambda who: mock.Mock(ru_maxrss=204800)), {'rss_mb': 200.0})
        self.assertEqual(live_image.rss(mock.Mock(side_effect=OSError('no such thing'))), {})
        spot = mock.Mock(strict=True, intask=False, role='runner', digest=S, task='spot')  # a Spot standby says nothing
        live_image.Warm(spot, [(mechanisms.REAP, None)], clock=table.clock).step(Kept(Connection(table.clock, [0.3])))
        spot.sent.assert_not_called()
        gate.sent.side_effect = RuntimeError('the database is away')  # never raises, and is not said again
        again = live_image.Warm(gate, [(mechanisms.REAP, None)], clock=table.clock)
        self.assertAlmostEqual(again.step(Kept(Connection(table.clock, [0.2]))), 0.2)

    def test_the_successor_s_warm_says_what_its_job_s_rehearsal_took_or_why_it_did_not_run(self):
        # FIRST-JOB-REHEARSED: read in the status (successor) while the delivery is at its checks, before any swap
        for job, want in ((lambda cursor: setattr(table.clock, 'now', table.clock.now + 0.9), {'job_s': 0.9}),
                          (mock.Mock(side_effect=PermissionError('permission denied for table tenant')),
                           {'job_error': 'PermissionError: permission denied for table tenant'})):
            said = []
            table = Table('')
            gate = mock.Mock(strict=True, intask=True, role='runner', digest=S, task='task-1:' + S[:12], reads=1)
            gate.sent.side_effect = lambda sql, params, db=None: said.append(json.loads(params['payload']))
            with mock.patch.object(live_image.LOG, 'exception'):
                live_image.Warm(gate, [(mechanisms.REAP, None)], clock=table.clock, job=job).step(
                    Kept(Connection(table.clock, [0.3])))
            said[0].pop('rss_mb')
            self.assertEqual(said, [{'role': 'runner', 'digest': S, 'task': 'task-1:' + S[:12], 'state': 'warm',
                                     'warm_s': 0.3, **want}])

    def test_a_successor_asks_whether_a_drill_names_it_when_it_rehearses_never_on_the_swap_s_clock(self):
        # SWAP-DRILL: read on the warm-up's cursor, at its first warm-up and at each readiness notification
        table = Table('')
        gate = mock.Mock(strict=True, intask=True, role='runner', digest=S, task='task-1', reads=1)
        warm = live_image.Warm(gate, [(mechanisms.REAP, None)], clock=table.clock)
        db = Kept(Connection(table.clock, [0.3]))
        warm.step(db)
        (asked,), _ = gate.arm.call_args
        self.assertIsInstance(asked, live_image.Rows)
        self.assertIs(asked.cursor, db.connection)  # inside the warm-up's rolled-back transaction, no commit of its own
        table.clock.now += live_image.WARM_S
        warm.step(db)  # the minute's warm-up: not asked again
        self.assertEqual(gate.arm.call_count, 1)
        gate.reads = 2  # the delivery at the front asked whether its successors are ready
        warm.step(db)
        self.assertEqual(gate.arm.call_count, 2)

    def test_the_swap_s_record_is_rehearsed_on_the_warm_up_s_connection_at_its_start_and_at_each_signal(self):
        # SWAP-RECORD-WARM: live 12/11 09:25 UTC the stall of 0.47 s within a second of the swap said what it was
        # (STALL-SAYS-WHAT): the service's own record of the swap, an insert into log.event of 365 ms on a backend that
        # had never written there, inside its first pass after the swap
        table, gate, warm, db = self.make()
        gate.reads = 3
        rehearsal = (live_image.REHEARSE, {
            'id': f'platform.deploy.image_live:service:{S}:rehearsal', 'producer': 'tower-service', 'role': 'service',
            'digest': S, 'task': 'standby', 'tenant': gate.tenant, 'key': gate.key})
        self.assertAlmostEqual(warm.step(db), 0.58)  # the role's statements alone: the rehearsal is not in warm_first_s
        self.assertEqual(db.connection.sent[-1], rehearsal)  # after them, in the same transaction
        self.assertEqual((len(db.connection.sent), db.connection.rolled), (5, 1))  # never committed
        table.clock.now += live_image.WARM_S
        warm.step(db)  # the minute's cadence: the role's statements again, no insert (a rolled-back one leaves a dead row)
        self.assertEqual((len(db.connection.sent), db.connection.rolled, db.connection.sent.count(rehearsal)), (9, 2, 1))
        gate.reads = 4  # READY-REHEARSAL: the delivery at the front asked whether its successors are ready
        warm.step(db)
        self.assertEqual((db.connection.sent[-1], db.connection.sent.count(rehearsal), db.connection.rolled), (rehearsal, 2, 3))
        other = Kept(Connection(table.clock, []))  # another connection of the process (a runner's other slot): its own
        warm.step(other)
        self.assertEqual(other.connection.sent[-1], rehearsal)
        # the rehearsal is the record's own statement for whatever version the pointer has, without the measure
        self.assertEqual(live_image.REHEARSE.replace(" from work.config_value v", " || %(parts)s::jsonb from work.config_value v")
                         .replace("v.key = %(key)s and not", "v.key = %(key)s and v.version = %(version)s::int and not"),
                         live_image.LIVE)

    def test_the_service_s_standby_has_its_pool_s_connections_open_before_the_swap(self):
        # POOL-READY: live 12/11 10:23 UTC the service's swap took 0.71 s: the pointer was read 0.69 s after its write,
        # behind a login of tower-service:pool at that instant. The pool opens a connection only when all it has are in
        # use; a standby uses one at a time, and at the swap its threads asked for several at once
        table, gate, warm, db = self.make()
        primed = []
        warm.primed = lambda: primed.append(table.clock.now)
        gate.reads = 1
        warm.step(db)
        self.assertEqual(len(primed), 1)  # when the standby first warms: the logins are its start's
        table.clock.now += live_image.WARM_S
        warm.step(db)
        self.assertEqual(len(primed), 1)  # not on the minute's cadence
        gate.reads = 2
        warm.step(db)
        # READY-ONCE: not at a delivery's readiness signal, a second or so before the landing: live 12/11 10:57 UTC the
        # standby took every pooled connection at once then, and the service read the pointer 0.34 s after its write
        # (the runner, on its own connection, 0.025 s)
        self.assertEqual(len(primed), 1)
        self.assertEqual(db.connection.sent[-1][0], live_image.REHEARSE)  # the record's rehearsal is still the signal's
        warm.step(Kept(Connection(table.clock, [])))  # another connection's first warm-up: the process readied already
        self.assertEqual(len(primed), 1)
        again = live_image.Warm(gate, [], clock=table.clock, primed=lambda: 1 / 0)
        self.assertIsNotNone(again.step(Kept(Connection(table.clock, []))))  # never raises
        sys.path.insert(0, str(ROOT / 'infra' / 'service'))
        from tower_infra import __main__ as main
        taken, given = [], []

        class Raw:
            def close(self):
                given.append(self)

        class Engine:
            def raw_connection(self):
                assert not given  # all taken before any is given back: the pool must hold that many at once
                taken.append(Raw())
                return taken[-1]
        self.assertEqual(main.pool_ready(Engine()), main.POOL_READY)
        self.assertEqual((len(taken), given), (main.POOL_READY, taken))

        class Refusing(Engine):
            def raw_connection(self):
                if len(taken) == 6:
                    raise RuntimeError('the database is at its limit')
                return Engine.raw_connection(self)
        del given[:]
        with self.assertRaises(RuntimeError):
            main.pool_ready(Refusing())  # the standby's warm-up catches it (Warm.step); what was taken is given back
        self.assertEqual(given, taken[4:])
        self.assertLessEqual(main.POOL_READY, 5)  # the pool's own size (SQLAlchemy's default): none of them an overflow
        text = (ROOT / 'infra/service/tower_infra/__main__.py').read_text()
        self.assertIn('mechanisms.REAP, mechanisms.ROLL, mechanisms.WAKE, mechanisms.QUEUES)], primed=lambda: ready_ahead(engine),', text)
        self.assertIn('    pool_ready(engine)\n    autodeploy.read_ahead(pooled(engine))', text)

    def test_the_record_is_written_on_the_connection_that_did_the_first_work(self):
        # SWAP-RECORD-WARM: the service wrote it on a pooled connection (the gate's scope), the coldest one; the loop's
        # connection, which did the first pass and rehearsed the record, writes it; the runner's slot writes its own
        table = Table('')
        gate = gate_on(table, 'runner', S, strict=True, task='standby')
        gate.refresh()
        table.value, table.version, table.seen_s = S, 2, 0.01
        self.assertTrue(gate.refresh())
        sent = []

        class Own:
            def rows(self, sql, params=None):
                sent.append(sql)
                return []
        before = len(table.sent) if hasattr(table, 'sent') else None
        self.assertIsNotNone(gate.working(db=Own()))
        self.assertEqual(sent, [live_image.LIVE])
        if before is not None:
            self.assertNotIn(live_image.LIVE, [sql for sql, _ in table.sent[before:]])  # not on the gate's scope
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text()
        self.assertIn("'dispatched': lambda parts: gate.working(\n                db=loop, began=began,", main)
        slot = (ROOT / 'infra/service/tower_infra/runner.py').read_text()
        self.assertIn('gate.working(began=began, db=self.db, connect_s=ready - began, take_s=gate.clock() - ready)', slot)

    def test_the_runner_s_slot_warms_its_take_and_the_service_s_loop_its_first_pass(self):
        table = Table('')
        gate = gate_on(table, 'runner', S, strict=True, task='standby')
        gate.refresh()
        warm = live_image.Warm(gate, [(runner.TAKE, {'adapter': 'container', 'runner': 'warm-up'})], clock=table.clock)
        slot = runner.Runner(Kept(Connection(table.clock, [0.4])), None, None, None, '/tmp', gate=gate)
        slot.db.rows = lambda sql, params=None: table.rows(sql, params)  # the beat goes to the table; the warm-up to the connection
        slot.beat = lambda: None
        slot.standby(type('Stop', (), {'is_set': lambda self: True})(), 0)
        self.assertEqual(slot.db.connection.sent[0], (runner.TAKE, {'adapter': 'container', 'runner': 'warm-up'}))
        self.assertEqual([sql for sql, _ in slot.db.connection.sent], [runner.TAKE, live_image.REHEARSE])  # SWAP-RECORD-WARM
        self.assertEqual((slot.db.connection.rolled, warm.said()['warm_first_s']), (1, 0.4))
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text()
        self.assertIn('warm.step(loop)', main)
        self.assertIn("live_image.Warm(gate, [(runner.TAKE, {'adapter': 'container', 'runner': 'warm-up'})],", main)


if __name__ == '__main__':
    unittest.main()
