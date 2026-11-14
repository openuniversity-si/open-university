"""IMAGE-SWAP-TICK (docs/operations/aws.md 22.9): the first work of each role after an image-only swap, part by part.

Live on 11/11, the swaps since the log's indexes (#471): landing to pointers 0.04 to 0.07 s and notify_s 0.02 to 0.06 s, but
the service's first dispatch pass took 0.05 to 2.6 s and the runner's first TAKE 0.014 to 0.72 s, statements of milliseconds
on local Postgres. What was on the swap's second, and is cut here:
1. The connection. The service's first tick took a pooled connection (a checkout and its ping, a new login with its IAM
   token and TLS when the pool's were in use by the listeners the same commit woke) and every statement was three round
   trips (BEGIN, the statement, COMMIT): 13 for a pass with nothing to claim, 34 with one claim. The loop now keeps a
   connection of its own, the standby's beat goes through it every pass, and it commits each statement by itself: 4 and 11
   round trips, none of them a login. The runner's slot kept its connection already; its TAKE and beat are one round trip.
2. The measure. image_live is timed at the service's first committed claim (Gate.first_work), not at the end of the pass,
   and says its parts: wake_s, connect_s, reap_s, dispatch_s (the runner: wake_s, connect_s, take_s), which add up to
   work_s, with pass_s and jobs for the whole first pass.
3. The pass after it. A standby keeps its wake listening and drained (the service's loop, each runner slot), so the first
   wait after the first work neither logs in nor misses what was notified meanwhile (DB-LISTEN-ONE: the wakes of a process
   are waiters of its one listening connection, wake.Hub, which listens from the process's start); the cold reads of a
   first pass (the forge's key and token, its webhook keys) leave it. The looks the landing's commit wakes are left as they were: making
   them read the pointer first (#502) moved the landing's look to the promoted service, whose dispatcher then made no good
   tick for 10 s (live 11/11: a failover; the swap's canary dispatched in 10.5 s).
With no TOWER_IMAGE_DIGEST, or no pointer, the statements are exactly the ones before the unit.

Hermetic: fakes with injected clocks and a stand-in for the dbos package; OnPostgres runs the real statements
(TEST_DATABASE_URL), each costing a fixed time on the injected clock.
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
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from test_infra_swap_ready import Clock, Pointer, workflows_with  # noqa: E402
from test_infra_wake_hub import Lines  # noqa: E402
import test_db  # noqa: E402
from tower_infra import container, live_image, mechanisms, runner, wake  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
S, OLD = 'a' * 64, 'f' * 64
MAIN = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
SERVE = MAIN[MAIN.index('def serve('):MAIN.index('\ndef ', MAIN.index('def serve(') + 1)]
RUN = MAIN[MAIN.index('def run_container('):MAIN.index('\ndef ', MAIN.index('def run_container(') + 1)]
# the dispatcher's statements as they were before the unit: a pass, and what each claim adds to it
IDLE = ['select id::text from work.reap() id', mechanisms.ROLL, mechanisms.WAKE, mechanisms.QUEUES]
# CANARY-OWN-SLOT: the account right after the route (a job the free slot is not for goes no further)
CLAIM = [mechanisms.CANDIDATES, mechanisms.ROUTE, mechanisms.ACCOUNT, mechanisms.FROM_CACHE, mechanisms.TWIN, mechanisms.HOLD, mechanisms.CLAIM]
EACH = 0.01  # what one statement costs on the injected clock


def a_pass(claims):
    """The statements of a dispatch pass that claims `claims` jobs of one queue: the last read finds no candidate left."""
    return IDLE + CLAIM * claims + ([mechanisms.CANDIDATES] if claims else [])


class Work(Pointer):
    """The pointer's table and one queue of queued jobs, by statement."""

    def __init__(self, value=OLD, jobs=()):
        super().__init__(value)
        self.jobs, self.claimed, self.parts = list(jobs), [], None

    def rows(self, sql, params=None):
        if sql == mechanisms.QUEUES:
            return [('tenant', 'queue')] if self.jobs else []
        if sql == mechanisms.CANDIDATES:
            return [(job, False) for job in self.jobs]  # FULL-RUN-SKIP: and whether it yields
        if sql == mechanisms.ROUTE:
            return [('executor',)]
        if sql == mechanisms.HOLD:
            return [(None,)]
        if sql == mechanisms.ACCOUNT:
            return [('account',)]
        if sql == mechanisms.CLAIM:
            self.claimed.append(self.jobs.pop(0))
            return [(self.claimed[-1], f'run-{self.claimed[-1]}', 1, 1, 'executor', 'account', 'uri', 'digest', 'none', '{}')]
        return super().rows(sql, params)


class Wire:
    """What container.Reconnecting keeps: a connection and the database over it; each statement is recorded and costs EACH."""

    def __init__(self, db, clock, sent):
        self.db, self.clock, self.sent = db, clock, sent
        self.connection = types.SimpleNamespace(closed=False, broken=False)

    def rows(self, sql, params=None):
        self.sent.append(sql)
        self.clock.now += EACH
        return self.db.rows(sql, params)


def kept(db, clock, sent, made, login_s=0.0):
    """A kept connection over db (the service's loop's, a runner slot's): `made` counts the logins, each login_s long."""
    def connect():
        made.append(1)
        clock.now += login_s
        return Wire(db, clock, sent)
    return container.Reconnecting(connect, lambda wire: wire)


def standing_by(table, role, clock, strict=True):
    gate = live_image.Gate(table.scope, role, S, task='t', strict=strict, clock=clock)
    gate.refresh()
    return gate


def swap(table, gate, notify_s=0.027):
    """The landing's write of the pointer and the read its notification runs."""
    table.value, table.version, table.seen_s = S, table.version + 1, notify_s
    assert gate.refresh()


def tick(workflows, gate, loop, clock, **more):
    began = clock()
    return workflows.tick('5 minutes', scope=loop.scope, first=gate.first_work, clock=clock,
                          dispatched=lambda parts: gate.working(began=began, **parts), **more)


class TheServicesFirstTick(unittest.TestCase):
    def setUp(self):
        self.started = []
        self.workflows = workflows_with(self.started)
        self.clock, self.sent, self.made = Clock(), [], []

    def test_the_first_tick_after_a_long_standby_opens_no_connection(self):
        table = Work(jobs=['j1'])
        loop = kept(table, self.clock, self.sent, self.made)
        gate = standing_by(table, 'service', self.clock)
        for _ in range(3):
            gate.beat(loop)  # the standby pass, on the loop's connection
            self.clock.now += 600  # ten minutes between two: whatever the standby lasts
        self.assertEqual((self.made, self.sent), ([1], [live_image.BEAT] * 3))
        swap(table, gate)
        self.assertEqual(tick(self.workflows, gate, loop, self.clock), ['run-j1'])
        self.assertEqual(self.made, [1])  # the connection the beats kept: no checkout, no login on the swap's second
        self.assertEqual(self.sent[3:], a_pass(1))
        self.assertEqual((table.parts['connect_s'], table.parts['jobs']), (0.0, 1))

    def test_with_no_digest_or_no_pointer_the_statements_are_the_ones_before(self):
        table = Work(value='', jobs=['j1'])
        self.assertIsNone(live_image.gate('service', '', table.scope))  # no TOWER_IMAGE_DIGEST: no gate, the pooled path
        wire = Wire(table, self.clock, self.sent)
        with mock.patch.object(self.workflows, 'connected', lambda: contextlib.nullcontext(wire)):
            self.assertEqual(self.workflows.tick('5 minutes'), ['run-j1'])
        self.assertEqual(self.sent, a_pass(1))
        del self.sent[:]
        table.jobs = ['j2']
        gate = standing_by(table, 'service', self.clock, strict=False)  # an ECS task under no pointer: live, as before
        self.assertTrue(gate.active())
        loop = kept(table, self.clock, self.sent, self.made)
        self.assertEqual(tick(self.workflows, gate, loop, self.clock), ['run-j2'])
        self.assertEqual(self.sent, a_pass(1))
        self.assertEqual(table.sent.count(live_image.READ), 1)  # the gate's one read at its start: nothing beats,
        self.assertIsNone(table.parts)  # nothing is recorded

    def test_the_role_works_at_its_first_committed_claim_and_the_parts_add_up(self):
        table = Work(jobs=['j1', 'j2', 'j3'])
        loop = kept(table, self.clock, self.sent, self.made)
        gate = standing_by(table, 'service', self.clock)
        gate.beat(loop)
        swap(table, gate, notify_s=0.027)
        self.clock.now += 0.003  # the loop's wake on the gate's event
        seen = []
        first = gate.first_work
        gate.first_work = lambda: (first(), seen.append((list(table.claimed), gate.worked.is_set(), table.parts)))
        self.assertEqual(tick(self.workflows, gate, loop, self.clock), ['run-j1', 'run-j2', 'run-j3'])
        # timed when the first claim was committed: the other two not yet claimed, nothing recorded, the looks still held
        self.assertEqual(seen, [(['j1'], False, None)])
        self.assertTrue(gate.worked.is_set())  # the looks go on once the pass is done
        parts = table.parts
        # PRE-GATE: one statement more per claim (mechanisms.TWIN), each 0.01 s on this clock
        self.assertEqual(parts, {'notify_s': 0.027, 'wake_s': 0.003, 'connect_s': 0.0, 'reap_s': 0.01, 'dispatch_s': 0.1,
                                 'work_s': 0.113, 'swap_s': 0.14, 'pass_s': 0.26, 'jobs': 3})
        self.assertAlmostEqual(parts['wake_s'] + parts['connect_s'] + parts['reap_s'] + parts['dispatch_s'], parts['work_s'])
        self.assertAlmostEqual(parts['notify_s'] + parts['work_s'], parts['swap_s'])
        self.assertEqual(len(self.sent[1:]) * EACH, parts['pass_s'])  # the whole pass, every claim: 23 statements
        self.assertIsNone(gate.working())  # once per swap

    def test_a_first_pass_with_nothing_to_claim_works_at_its_end(self):
        table = Work()
        loop = kept(table, self.clock, self.sent, self.made)
        gate = standing_by(table, 'service', self.clock)
        gate.beat(loop)
        swap(table, gate, notify_s=0.02)
        self.assertEqual(tick(self.workflows, gate, loop, self.clock), [])
        self.assertEqual(table.parts, {'notify_s': 0.02, 'wake_s': 0.0, 'connect_s': 0.0, 'reap_s': 0.01, 'dispatch_s': 0.03,
                                       'work_s': 0.04, 'swap_s': 0.06, 'pass_s': 0.04, 'jobs': 0})

    def test_a_connection_that_broke_is_made_again_and_timed_apart(self):
        table = Work()
        loop = kept(table, self.clock, self.sent, self.made, login_s=0.2)
        gate = standing_by(table, 'service', self.clock)
        gate.beat(loop)
        loop.db.connection.closed = True  # the database closed it under the standby
        swap(table, gate, notify_s=0.02)
        tick(self.workflows, gate, loop, self.clock)
        self.assertEqual(self.made, [1, 1])
        self.assertEqual((table.parts['connect_s'], table.parts['reap_s'], table.parts['work_s']), (0.2, 0.01, 0.24))

    def test_a_look_woken_with_the_swap_decides_on_what_the_gate_has_read(self):
        table = Work(value='')
        old = live_image.Gate(table.scope, 'service', OLD, task='ecs')  # the ECS service, live under no pointer
        self.assertTrue(old.refresh())
        promoted = standing_by(table, 'service', self.clock)
        looks = {'old': old.after_work(old.active), 'promoted': promoted.after_work(promoted.sole)}
        table.value, table.version = S, 2  # the landing's commit: no listener of either gate has read it yet
        sent = len(table.sent)
        # the service the swap retires runs the landing's look (it has the CPU), the one it promotes does not: as before
        self.assertEqual((looks['old'](), looks['promoted'](), len(table.sent)), (True, False, sent))
        swap(table, promoted)  # read by the listener, the promoted service's later looks wait for its first work
        seen = []
        thread = threading.Thread(target=lambda: seen.append(looks['promoted']()), daemon=True)
        thread.start()
        thread.join(0.2)
        self.assertEqual(seen, [])
        promoted.working()
        thread.join(5)
        self.assertEqual(seen, [True])


class TheRunnersFirstTake(unittest.TestCase):
    def setUp(self):
        self.clock, self.sent, self.made, self.table = Clock(), [], [], Work()
        self.db = kept(self.table, self.clock, self.sent, self.made, login_s=0.2)
        self.gate = standing_by(self.table, 'runner', self.clock)
        self.slot = runner.Runner(self.db, None, None, None, tempfile.gettempdir(), gate=self.gate)

    def test_the_take_after_a_standby_is_on_the_slots_kept_connection_and_its_parts_add_up(self):
        stop = threading.Event()
        for _ in range(3):
            self.slot.standby(stop, 0)
            self.clock.now += 600
        self.assertEqual((self.made, self.sent), ([1], [live_image.BEAT] * 3))
        swap(self.table, self.gate, notify_s=0.018)
        self.clock.now += 0.002  # the slot's wake on the gate's event
        self.assertIsNone(self.slot.once())
        # SWAP-RECORD-WARM: the record too is on the slot's kept connection, the one that rehearsed it while it stood by
        self.assertEqual((self.made, self.sent[3:]), ([1], [runner.TAKE, live_image.LIVE, live_image.LIVE_BEAT]))
        self.assertEqual(self.table.parts, {'notify_s': 0.018, 'wake_s': 0.002, 'connect_s': 0.0, 'take_s': 0.01,
                                            'work_s': 0.012, 'swap_s': 0.03})

    def test_a_slot_whose_connection_broke_logs_in_again_apart_from_its_take(self):
        self.slot.standby(threading.Event(), 0)
        self.db.db.connection.closed = True
        swap(self.table, self.gate, notify_s=0.018)
        self.assertIsNone(self.slot.once())
        self.assertEqual(self.made, [1, 1])
        self.assertEqual(self.table.parts, {'notify_s': 0.018, 'wake_s': 0.0, 'connect_s': 0.2, 'take_s': 0.01,
                                            'work_s': 0.21, 'swap_s': 0.228})

    def test_a_standby_slot_keeps_its_wake_listening_and_drained(self):
        lines = Lines()
        hub = wake.Hub(lines, (wake.RUNS, wake.CONFIG))  # DB-LISTEN-ONE: the task's one listener, the slot's wake on it
        self.addCleanup(hub.close)
        mark, self.slot.wait = hub.wake(wake.RUNS), hub.wake(wake.RUNS).wait
        line, stop = lines.line(), threading.Event()
        for _ in range(3):
            line.notify(wake.RUNS)  # a run handed over to another task
            self.assertTrue(mark.wait(5))
            self.slot.standby(stop, 0)
            self.assertFalse(self.slot.wait(0))  # drained by the pass, which never waits on it
        swap(self.table, self.gate)
        self.assertIsNone(self.slot.once())  # nothing to take yet
        line.notify(wake.RUNS)  # the run the service hands over during that pass
        self.assertTrue(self.slot.wait(30))  # the slot's first idle wait: no login, and it sees the run
        self.assertEqual((len(lines.made), line.heard), (1, ['listen tower_runs', 'listen tower_config']))  # one login, ever

    def test_without_a_gate_the_take_is_the_only_statement(self):
        slot = runner.Runner(self.db, None, None, None, tempfile.gettempdir())
        self.assertIsNone(slot.once())
        self.assertEqual(self.sent, [runner.TAKE])


class TheWiring(unittest.TestCase):
    def test_the_services_loop_keeps_one_connection_from_its_standby_to_its_ticks(self):
        # SWAP-CPU: made before the gate, whose first read goes through it
        self.assertIn('    early = container.Reconnecting(\n'
                      "        lambda: connection(database, where, user, password, purpose='loop', autocommit=True), "
                      'database.Database)', SERVE)
        self.assertIn('    loop = None if gate is None else early\n', SERVE)
        self.assertLess(SERVE.index('    early = container.Reconnecting('), SERVE.index("    gate = live_image.gate('service'"))
        self.assertIn("first=early.scope if os.environ.get('TOWER_IMAGE_DIGEST', '').strip() else None)", SERVE)
        loop = SERVE[SERVE.index("LOG.info('serve: up')"):]
        standby = loop[loop.index('if gate is not None and not gate.active():'):loop.index('launched = launch.done')]
        self.assertIn('gate.beat(loop)  # IMAGE-SWAP-TIGHTEN', standby)
        self.assertIn("timed = {} if gate is None else {'scope': loop.scope, 'first': gate.first_work, "
                      "'dispatched': lambda parts: gate.working(", loop)
        self.assertIn('started = workflows.tick(lease, **timed)', loop)  # no gate: the pooled tick, as before

    def test_the_cold_reads_of_a_first_pass_leave_the_swaps_moment(self):
        loop = SERVE[SERVE.index("LOG.info('serve: up')"):]
        standby = loop[loop.index('if gate is not None and not gate.active():'):loop.index('launched = launch.done')]
        self.assertIn('aside(origin_forge.warm)  # IMAGE-SWAP-TICK', standby)  # the forge's key and token, kept by the standby
        self.assertIn('last_keys = time.monotonic()  # and the webhook keys', standby)  # their refresh: an interval after
        before = SERVE[:SERVE.index("LOG.info('serve: up')")]  # a reloaded task reads both before it takes the role over
        self.assertIn('    if gate is not None and gate.reloaded is not None and gate.sharing():\n'
                      '        origin_forge.warm()\n        refresh_keys(forge_webhooks, workflows)\n'
                      '        last_keys = time.monotonic()\n        woken.wait(0)  # and its wake is drained', before)

    def test_the_services_standby_keeps_its_loops_wake_listening_and_drained(self):
        loop = SERVE[SERVE.index("LOG.info('serve: up')"):]
        standby = loop[loop.index('if gate is not None and not gate.active():'):loop.index('launched = launch.done')]
        self.assertLess(standby.index('gate.beat(loop)'), standby.index('woken.wait(0)\n'))
        self.assertIn("woken.wait(settings.get('service.dispatch_s'))  # the safety tick", loop)  # the same wake, live

    def test_the_runners_kept_connections_commit_each_statement_under_a_digest(self):
        self.assertIn("autocommit=bool(os.environ.get('TOWER_IMAGE_DIGEST', '').strip())", RUN)
        self.assertIn("live_image.kept(container.Reconnecting(lambda: kept('gate'), database.Database))", RUN)
        self.assertIn('runner.Runner(container.Reconnecting(kept, database.Database), box.fetch', RUN)
        self.assertIn('wait=hub.wake(wake.RUNS).wait', RUN)  # DB-LISTEN-ONE: the slots' wakes, on the task's one listener
        self.assertIn("return connection(database, where, user, password, purpose='warm')", RUN)  # the warm-up's record

    def test_a_login_started_ahead_is_the_one_the_kept_connection_waits_for(self):
        # LOGIN-AHEAD: a successor the role waits for logged in one connection after the other; the ones its first work
        # needs start together, and the caller waits for the login in flight instead of making another
        gate, made = threading.Event(), []

        def connect():
            made.append(threading.current_thread().name)
            gate.wait(5)
            return types.SimpleNamespace(connection=types.SimpleNamespace(closed=False, broken=False))
        loop = container.Reconnecting(connect, lambda wire: wire).ahead()
        deadline = time.monotonic() + 5
        while not made and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertEqual(made, ['login-ahead'])  # started at once, in a thread of its own: the caller goes on
        self.assertIs(loop.ahead(), loop)  # asked again while it is in flight: the same login
        gate.set()
        found = loop.ready()
        self.assertEqual((len(made), loop.ready() is found), (1, True))  # the login in flight was the connection: no second one

    def test_a_login_ahead_that_fails_is_left_to_the_caller_which_raises_what_it_finds(self):
        made = []

        def connect():
            made.append(1)
            if len(made) == 1:
                raise OSError('the database is away')
            return types.SimpleNamespace(connection=types.SimpleNamespace(closed=False, broken=False))
        with mock.patch.object(container.LOG, 'exception') as said:
            loop = container.Reconnecting(connect, lambda wire: wire).ahead()
            self.assertIsNotNone(loop.ready())  # the caller logged in itself
        self.assertEqual((len(made), said.call_count), (2, 1))
        ahead = container.Ahead(lambda: 'a connection')
        self.assertEqual((ahead.result(), ahead.result()), ('a connection', None))  # handed over once

    def test_a_successor_under_its_own_pointer_applies_no_migration_and_logs_its_loop_in_ahead(self):
        # LATE-NO-MIGRATE: the pass (a login, the lock, the partitions) was on the role's clock at the drill of 12/11
        self.assertIn('    if gate is not None and gate.strict and intask and gate.live is True:\n'
                      '        loop.ahead()\n', SERVE)
        self.assertIn("    elif gate is None or gate.live is not False:\n"
                      "        LOG.info('serve: migrations applied now: %s', migrate(engine) or 'none')", SERVE)
        self.assertLess(SERVE.index('loop.ahead()'), SERVE.index('launch = live_image.OnceLive('))  # beside the launch

    def test_a_runner_successor_starts_its_first_slot_s_login_beside_its_gate_s(self):
        self.assertIn("early = [container.Ahead(login)] if os.environ.get(live_image.STANDBY) == live_image.INTASK else []", RUN)
        self.assertLess(RUN.index('early = [container.Ahead(login)]'), RUN.index("live_image.gate('runner'"))  # before the gate's
        self.assertIn("            found = early.pop().result() if purpose == 'slot' else None\n", RUN)  # a slot's, never the gate's
        self.assertIn('        return login(purpose) if found is None else found\n', RUN)

    def test_a_kept_connection_is_asked_of_psycopg_in_autocommit(self):
        asked = []
        fake = types.ModuleType('psycopg')
        fake.connect = lambda **options: asked.append(options) or 'connection'
        from tower_infra import __main__ as main, database
        where = {'host': 'h', 'port': 5432, 'name': 'tower', 'region': 'us-east-1', 'sslmode': 'require'}
        with mock.patch.dict(sys.modules, {'psycopg': fake}):
            self.assertEqual(main.connection(database, where, 'tower_service', 'local', autocommit=True), 'connection')
            main.connection(database, where, 'tower_service', 'local')
        self.assertEqual([each.get('autocommit') for each in asked], [True, None])


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements: a promoted service's first tick on the connection its standby kept, with two jobs queued."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db
        self.started = []
        self.workflows = workflows_with(self.started)
        self.clock, self.sent, self.made = Clock(), [], []

    def put(self, value):
        return self.world.port('PUT', '/v1/config/deploy.live_image_service', 'torre', {'value': value, 'reason': 'test'})

    def runs(self):
        return [each[0] for each in self.db.rows('select state from work.run order by id')]

    def test_the_promoted_service_claims_on_its_standbys_connection_and_is_timed_at_its_first_claim(self):
        self.put(OLD)
        gate = live_image.gate('service', S, live_image.kept(self.db), task='service-standby', strict=True)
        gate.clock = self.clock
        loop = kept(self.db, self.clock, self.sent, self.made)
        for _ in range(2):
            gate.beat(loop)
            self.clock.now += 600
        for name in ('one', 'two'):
            self.world.job(name, 'true')
        self.put(S)
        self.assertTrue(gate.refresh())
        seen = []
        first = gate.first_work
        gate.first_work = lambda: (first(), seen.append(self.runs()))
        ran = tick(self.workflows, gate, loop, self.clock)
        self.assertEqual((len(ran), self.runs()), (2, ['starting', 'starting']))
        self.assertEqual(seen, [['starting']])  # the first claim was committed, and only it, when the role was timed
        self.assertEqual((self.made, self.sent[2:]), ([1], a_pass(2)))
        (payload,) = [each for (each,) in self.db.rows(
            "select payload from log.event where type = 'platform.deploy.image_live'")]
        payload = __import__('json').loads(payload)
        self.assertEqual({name: payload[name] for name in ('connect_s', 'reap_s', 'dispatch_s', 'pass_s', 'jobs')},
                         {'connect_s': 0.0, 'reap_s': 0.01, 'dispatch_s': 0.1, 'pass_s': 0.19, 'jobs': 2})  # PRE-GATE: TWIN
        self.assertAlmostEqual(payload['wake_s'] + payload['connect_s'] + payload['reap_s'] + payload['dispatch_s'],
                               payload['work_s'])
        # SWAP-EVIDENCE-WHEN-SLOW: this swap was inside its second: its record asks the database nothing
        self.assertLess(payload['swap_s'], live_image.EVIDENCE_S)
        self.assertNotIn('busy', payload)
        self.assertNotIn('backends', payload)
        # SWAP-TAIL-EVIDENCE: the real statement over pg_stat_activity: the other backends' statements of the window, by text
        found = live_image.busy(self.db, 30)
        self.assertGreaterEqual(found['backends'], 1)
        self.assertIsInstance(found['busy'], list)
        for each in found['busy']:
            self.assertLessEqual({'q', 'n', 'ms', 'active'}, set(each))
            self.assertLessEqual(set(each), {'q', 'n', 'ms', 'active', 'of', 'waits', 'ago'})  # SWAP-TAIL-WAITS
            self.assertGreaterEqual(each['ago'], each['ms'])  # DB-STALL-EVIDENCE: when it began, before this read
            self.assertNotIn("'", each['q'])  # literals are removed: no value of a statement reaches the log

    def test_the_record_s_rehearsal_is_the_record_s_insert_on_the_real_schema(self):
        # SWAP-RECORD-WARM: the statement a standby runs and rolls back so its backend has written to log.event before
        # the swap; run here for real (and kept: no transaction to roll back through this database's shape)
        self.put(S)
        params = {'id': f'platform.deploy.image_live:service:{S}:rehearsal', 'producer': 'tower-service', 'role': 'service',
                  'digest': S, 'task': 'standby', 'tenant': live_image.config_data.TENANT, 'key': live_image.KEYS['service']}
        count = ("select count(*), min(payload->>'role'), min(payload->>'digest') from log.event "
                 "where type = 'platform.deploy.image_live' and event_id like '%:rehearsal'")
        self.db.rows(live_image.REHEARSE, params)
        self.assertEqual([tuple(str(each) for each in row) for row in self.db.rows(count)], [('1', 'service', S)])
        self.db.rows(live_image.REHEARSE, params)  # the same id again: the lookup finds it, as the record's does
        self.assertEqual(str(self.db.rows(count)[0][0]), '1')
        self.db.rows(live_image.REHEARSE, {**params, 'key': 'deploy.no_such_pointer', 'id': 'other:rehearsal'})
        self.assertEqual(str(self.db.rows(count)[0][0]), '1')  # no pointer of the role: nothing to rehearse

    def test_the_evidence_says_what_a_statement_still_running_waits_on_and_the_event_it_names(self):
        """SWAP-TAIL-WAITS: live 12/11 02:31 UTC a swap took 1.049 s: an insert into log.event still running after
        0.99 s, the delivery's train release after 0.55 s, a beat after 0.49 s, and the evidence could not tell a lock
        from the CPU or the disk, nor which of the engine's dozen inserts into log.event it was (they share their first
        64 characters). Each statement of the window that is still running says what it waits on (pg_stat_activity's
        wait event; none is the CPU), and a statement that names an event type or a key says which (its first literal
        that is a dotted name of the engine's families: a name of the code, never a value)."""
        psql = [str(test_db.psql_binary()), self.db.url, '-X', '-q', '-c']
        held = subprocess.Popen(psql + ["begin; lock table work.standby_beat in access exclusive mode; "
                                        "select pg_sleep(20), 'platform.deploy.image_live', 'a value: kept out'"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(held.wait)
        self.addCleanup(held.kill)
        found, late = {}, time.monotonic() + 15
        while time.monotonic() < late and not any('lock table' in each['q'] for each in found.get('busy') or []):
            found = live_image.busy(self.db, 30)
        blocked = subprocess.Popen(psql + ["insert into work.standby_beat (role, digest, task, beat_at) "
                                           "values ('runner', 'some.value', 'another', clock_timestamp())"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(blocked.wait)
        self.addCleanup(blocked.kill)
        while time.monotonic() < late and not any(each['q'].startswith('insert into work.standby_beat')
                                                  and each.get('waits') for each in found.get('busy') or []):
            found = live_image.busy(self.db, 30)
        by = {each['q'][:17]: each for each in found['busy']}
        self.assertEqual((by['begin; lock table']['waits'], by['begin; lock table']['of'], by['begin; lock table']['active']),
                         (['Timeout:PgSleep'], 'platform.deploy.image_live', 1))
        self.assertEqual(by['insert into work.']['waits'], ['Lock:relation'])  # what holds it: a lock, not the CPU
        self.assertNotIn('of', by['insert into work.'])  # a dotted value is no name of the engine's: no field
        self.assertNotIn('value', json.dumps(found))  # and no value of a statement reaches the log, as before
        # DB-STALL-EVIDENCE: the connections opened inside the window, by who opened them (their application name): a
        # login is a fork, a TLS handshake and an IAM token's check on the database's host, and nothing said how many
        # came at the swap's instant (the two this test opened; the read's own connection is not counted)
        self.assertEqual(found['logins'], {'psql': 2})
        self.assertNotIn('logins', live_image.busy(self.db, 0.001))  # none born in the window: no field
        # the lock's holder ended (its backend, not only its client), what it held goes on
        self.db.rows("select pg_terminate_backend(pid) from pg_stat_activity where datname = current_database() "
                     "and pid <> pg_backend_pid() and query like 'begin; lock table%'")
        self.assertEqual(blocked.wait(timeout=15), 0)

    def test_a_promoted_service_keeps_dispatching_and_beating_pass_after_pass(self):
        """Several passes of serve's live branch after the swap, in its order (the tick on the loop's connection, the live
        beat, the wait on the loop's wake), with a job made during each pass: #502's tests stopped at the first tick."""
        self.world.port('PUT', '/v1/executors/script-runner/capacity/fargate', 'installation', {'slots': '8'})
        self.put(OLD)
        gate = live_image.gate('service', S, live_image.kept(self.db), task='service-standby', strict=True)
        gate.clock = self.clock
        ecs = live_image.gate('service', OLD, live_image.kept(self.db), task='ecs')  # the ECS task: stands by and watches
        loop = kept(self.db, self.clock, self.sent, self.made)
        lines = Lines()
        hub = wake.Hub(lines, (wake.WORK,))  # DB-LISTEN-ONE: the loop's wake is a waiter of the service's one listener
        self.addCleanup(hub.close)
        woken, line = hub.wake(wake.WORK), lines.line()
        for _ in range(2):  # standing by
            gate.beat(loop)
            woken.wait(0)
        self.put(S)
        self.assertTrue(gate.refresh())
        self.assertFalse(ecs.refresh())

        def beat():
            return self.db.rows("select live_at from work.standby_beat where role = 'service' and digest = %(digest)s "
                                "and task = 'service-standby'", {'digest': S})[0][0]
        beats, jobs = [], []
        for n in range(5):
            ran = tick(self.workflows, gate, loop, self.clock)
            self.assertEqual(len(ran), len(jobs[-1:]), f'pass {n}')  # the job made during the pass before, and only it
            self.assertTrue(gate.live_beat(), f'pass {n}')
            beats.append(beat())
            jobs.append(self.world.job(f'made in pass {n}', 'true'))  # the swap's canary, a check: work made meanwhile
            line.notify(wake.WORK)  # job.created
            self.assertTrue(woken.wait(30), f'pass {n}')  # the next pass comes at once: no login, nothing missed
            self.clock.now += live_image.LIVE_BEAT_S
            ecs.beat()  # the ECS task's standby pass: the promoted service's live beat is fresh, the role stays
            self.assertEqual((ecs.pointer, ecs.live), (S, False), f'pass {n}')
        self.assertEqual(sorted(beats), beats)
        self.assertEqual(len(set(beats)), 5)  # the live beat advanced on every pass
        self.assertEqual(self.runs(), ['starting'] * 4)  # every job made after the first pass was dispatched by the next
        self.assertEqual((self.made, len(lines.made)), ([1], 1))  # one connection for the beats and every tick; one LISTEN
        self.assertFalse(self.db.rows("select 1 from log.event where type = 'platform.deploy.image_retired'"))

    def test_with_no_gate_the_tick_sends_the_same_statements_through_the_pool(self):
        self.world.job('one', 'true')
        wire = Wire(self.db, self.clock, self.sent)
        with mock.patch.object(self.workflows, 'connected', lambda: contextlib.nullcontext(wire)):
            ran = self.workflows.tick('5 minutes')
        self.assertEqual((len(ran), self.runs(), self.sent), (1, ['starting'], a_pass(1)))


if __name__ == '__main__':
    unittest.main()
