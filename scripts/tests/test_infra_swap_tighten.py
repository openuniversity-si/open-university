"""IMAGE-SWAP-TIGHTEN (docs/operations/aws.md 22.9): the image-only swap from the landing to both roles working, under 1 s.

1. Landing -> pointer: the landing (POST /v1/deploy/landed, port.deploy_landed) decides and writes both pointers in the
   statement that records it, when the merge runs the PR head's bundle (autodeploy.merged_bundle, the rule the autodeploy
   applies too) and both roles' standbys beat now (work.standby_beat, migration 0014, within deploy.standby_fresh_s on the
   database clock): no AWS call and no service look on the clock. Otherwise the landing says why and the autodeploy decides
   as before (its fallback keeps the landing's why).
2. Pointer -> working: platform.deploy.image_live is recorded when the role really takes work (the runner's first TAKE, the
   service's first dispatch tick after DBOS.launch), with its parts: notify_s (the pointer's write to the gate's read, the
   database clock), work_s (that read to the work, the process's clock), launch_s (the service's DBOS.launch), swap_s their
   sum; the record's own statement is after the measure. scripts/medir: image_landing_to_live_s.

Hermetic: fakes with injected clocks; OnPostgres runs the real statements (TEST_DATABASE_URL).
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import autodeploy, config_data, live_image, port, runner  # noqa: E402
import medir  # noqa: E402
from test_infra_prewarm import said  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
BASE, MERGE, PR_HEAD, NEXT, NEXT_HEAD = 'b' * 40, '9' * 40, '8' * 40, '6' * 40, '5' * 40
S = 'a' * 64
KEYS = sorted(live_image.KEYS.values())


def landed(merge=MERGE, base=BASE, head=PR_HEAD, **code):
    return {'merge_sha': merge, 'base_before': base, 'pr_head': head, 'pr': '7', 'functions': [], 'paths': [],
            'code': {'code_only': True, 'why': '1 file(s)', 'bundle_same': True, **code}}


class Reads:
    """The landing's reads before its statement, by their text."""

    def __init__(self, base=BASE, job=None, config=None):
        self.base, self.config, self.asked = base, config or {}, []
        self.job = [('succeeded', said(S))] if job is None else job

    def rows(self, sql, params=None):
        self.asked.append(sql)
        if sql == port.DECIDE:  # LANDING-ONE-READ: the three reads in one statement, as it answers them
            assert params['merge'] == MERGE and params['key'] == f'prewarm:code:{PR_HEAD}'
            assert params['base'] == 'mod/roadmap-integration' and params['keys'] == ','.join(port.SWAP_KEYS)
            named = self.config.get('deploy.base_branch')
            ref = 'refs/heads/' + (named if isinstance(named, str) and named.strip() else params['base'])
            job = [json.dumps({'state': state, 'result': json.loads(result) if result else None})
                   for state, result in self.job[:1]]
            return [(json.dumps(self.config), self.base, job[0] if job else None, ref)]
        if sql == port.SWAP_CONFIG:
            return [(name, json.dumps(value)) for name, value in self.config.items()]
        if sql == port.BASE_HEAD:
            assert params['ref'] == 'refs/heads/mod/roadmap-integration' and params['merge'] == MERGE
            return [(self.base,)] if self.base else []
        if sql == autodeploy.BUNDLE_JOB:
            assert params['key'] == f'prewarm:code:{PR_HEAD}'
            return self.job
        raise AssertionError(sql)


class TheLandingDecides(unittest.TestCase):
    def test_a_code_only_merge_of_the_heads_bundle_names_it_with_the_registry_freshness(self):
        self.assertEqual(port.landing_swap(Reads(), landed()),
                         (S, f'artifacts/lambda/tower-code/{S}.zip', 3.0, ''))
        self.assertEqual(port.landing_swap(Reads(config={'deploy.standby_fresh_s': 7.5}), landed())[2], 7.5)
        self.assertEqual(config_data.SPEC['deploy.standby_fresh_s'], (float, 3.0))

    def test_every_reason_not_to_is_the_autodeploys(self):
        cases = [(Reads(config={'deploy.promote': False}), landed(), 'deploy.promote is false'),
                 (Reads(), landed(bundle_same=False, moved=['infra/service/x.py']), "the base changed the bundle's inputs"),
                 (Reads(base='c' * 40), landed(), "the merge's parent is not base_before"),
                 (Reads(base=None), landed(), "the merge's parent is not base_before"),
                 (Reads(job=[]), landed(), 'the PR head has no bundle job'),
                 (Reads(job=[('failed', None)]), landed(), 'its bundle job ended failed')]
        for db, event, why in cases:
            digest, key, _, said_why = port.landing_swap(db, event)
            self.assertEqual((digest, key), ('', None), why)
            self.assertTrue(said_why.startswith(why), said_why)

    def test_the_landing_decides_on_one_read(self):
        """LANDING-ONE-READ: the landing read the registry's rows, the base's head and the PR head's bundle job in three
        statements before its own, each a round trip from a 256 MB Lambda: decide_s was 0.05 to 0.12 s of every landing
        (live 12/11, ten landings), a third to a half of a swap of 0.15 to 0.25 s. One statement answers the three."""
        db = Reads()
        self.assertEqual(port.landing_swap(db, landed())[0], S)
        self.assertEqual(db.asked, [port.DECIDE])
        db = Reads(job=[])
        self.assertEqual(port.landing_swap(db, landed())[3], 'the PR head has no bundle job')
        self.assertEqual(db.asked, [port.DECIDE])
        # a row of the base's name the registry refuses (the statement took it, the registry's rule gives the default):
        # the base's head is asked again for the name the service reads, the one case of a second read
        db = Reads(config={'deploy.base_branch': 7})
        self.assertEqual(port.landing_swap(db, landed())[0], S)
        self.assertEqual(db.asked, [port.DECIDE])  # 7 is no string: the statement took the default too
        odd = Reads(config={'deploy.base_branch': '\t'})
        odd.rows = lambda sql, params=None, rows=odd.rows: (
            [(json.dumps(odd.config), None, json.dumps({'state': 'succeeded', 'result': json.loads(said(S))}), 'refs/heads/\t')]
            if sql == port.DECIDE and not odd.asked.append(sql) else rows(sql, params))
        self.assertEqual(port.landing_swap(odd, landed())[0], S)
        self.assertEqual(odd.asked, [port.DECIDE, port.BASE_HEAD])

    def test_a_landing_that_is_not_code_only_has_nothing_to_say(self):
        self.assertEqual(port.landing_swap(Reads(), landed(code_only=False)), ('', None, 0, ''))

    def test_the_landing_is_recorded_whatever_the_reads_do(self):
        class Broken(Reads):
            def rows(self, sql, params=None):
                if sql == port.LANDED_SWAP:
                    self.sent = params
                    return [('{"swapped": false, "why": "x"}', None)]
                raise RuntimeError('db hiccup')
        db = Broken()
        found = port.deploy_landed(db, ('tenant', 't-1'), landed())
        self.assertEqual((db.sent['digest'], db.sent['why']), ('', 'the landing could not decide: RuntimeError'))
        self.assertEqual(found['swap'], {'swapped': False, 'why': 'x'})

    def test_a_statement_that_cannot_swap_still_records_the_landing(self):
        class Db(Reads):
            def rows(self, sql, params=None):
                if sql == port.LANDED_SWAP:
                    raise RuntimeError('relation "work.standby_beat" does not exist')
                if sql == port.LANDED_ONLY:
                    self.recorded = json.loads(params['payload'])
                    return [(1,)]
                return super().rows(sql, params)
        db = Db()
        found = port.deploy_landed(db, ('tenant', 't-1'), landed())
        self.assertEqual(db.recorded['swap'], {'swapped': False, 'why': 'the landing could not swap: RuntimeError'})
        self.assertEqual(found['swap'], db.recorded['swap'])

    def test_the_decision_is_timed_on_the_lambdas_clock(self):
        ticks = iter([10.0, 10.004])

        class Db(Reads):
            def rows(self, sql, params=None):
                if sql == port.LANDED_SWAP:
                    self.sent = params
                    return [('{"swapped": true}', json.dumps({'swapped': True, 'landed_s': 0.002}))]
                return super().rows(sql, params)
        db = Db()
        found = port.deploy_landed(db, ('tenant', 't-1'), landed(), clock=lambda: next(ticks))
        self.assertEqual(json.loads(db.sent['swap'])['decide_s'], 0.004)
        self.assertEqual((db.sent['digest'], db.sent['fresh_s'], db.sent['keys']), (S, 3.0, ','.join(KEYS)))
        self.assertEqual(found['image_swap'], {'swapped': True, 'landed_s': 0.002})

    def test_the_autodeploy_falls_back_with_the_landings_why(self):
        from test_infra_image_swap import Db, Ecs
        db = Db()
        watcher = autodeploy.AutoDeploy(db.scope, {}.get, lambda _: {}, clock=lambda: 1000.0)
        watcher.ecs, watcher.cluster = Ecs(), 'tower'
        watcher.landed[MERGE] = {**landed(), 'swap': {'swapped': False, 'why': 'no beat of the runner standby'}}
        watcher.landed_at[MERGE] = 990.0
        watcher.promote(db, [BASE, MERGE], {'promote': True})
        swap = db.swaps(True)[0]
        self.assertEqual((swap['by'], swap['landing_why']), ('autodeploy', 'no beat of the runner standby'))


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


class Pointer:
    """deploy.live_image_<role> as the gate reads it; notify_s is the third column, the database clock."""

    def __init__(self, value, version=1, seen_s=0.0):
        self.value, self.version, self.seen_s, self.sent = value, version, seen_s, []

    def scope(self):
        import contextlib
        return contextlib.nullcontext(self)

    def rows(self, sql, params=None):
        self.sent.append((sql, params))
        if sql == live_image.READ:
            return [(json.dumps(self.value), self.version, self.seen_s)]
        if sql in (live_image.LIVE, live_image.BEAT, runner.TAKE, live_image.LIVE_BEAT):  # IMAGE-SWAP-FAILOVER: the live beat
            return []
        if sql == live_image.BUSY:  # SWAP-TAIL-EVIDENCE: what a test says the database was doing; by default it cannot be read
            return getattr(self, 'busy', [])
        raise AssertionError(sql)

    def recorded(self):
        return [json.loads(params['parts']) for sql, params in self.sent if sql == live_image.LIVE]


class PointerToWorking(unittest.TestCase):
    """What sits inside swap_s per role, timed with injected clocks."""

    def turned(self, role):
        table, clock = Pointer('f' * 64), Clock()
        gate = live_image.Gate(table.scope, role, S, task='t', strict=True, clock=clock)
        gate.refresh()
        table.value, table.version, table.seen_s = S, 2, 0.031  # the NOTIFY and the read: 31 ms after the write
        self.assertTrue(gate.refresh())
        self.assertEqual(table.recorded(), [])  # live is not working yet
        return table, gate, clock

    def test_the_runner_records_at_its_first_take(self):
        table, gate, clock = self.turned('runner')
        table.busy = [(json.dumps([{'q': 'select work.take(', 'n': 4, 'ms': 310, 'active': 1}]), 23)]  # SWAP-TAIL-EVIDENCE
        clock.now += 0.004  # the slot's wake and its TAKE
        executed = []
        slot = runner.Runner(table, None, None, None, tempfile.gettempdir(), gate=gate)
        slot.execute = lambda run: executed.append(run)
        self.assertIsNone(slot.once())
        # SWAP-EVIDENCE-WHEN-SLOW: a swap inside its second records its parts and asks the database nothing more: the
        # evidence read ran in both roles in the second after every swap and was itself what the database was doing
        # then (live 12/11: it saw its own statement active for 88 to 423 ms, ten records of five landings)
        self.assertEqual([sql for sql, _ in table.sent[-3:]], [runner.TAKE, live_image.LIVE, live_image.LIVE_BEAT])
        self.assertNotIn(live_image.BUSY, [sql for sql, _ in table.sent])
        self.assertEqual(table.recorded(), [{'notify_s': 0.031, 'work_s': 0.004, 'swap_s': 0.035, 'wake_s': 0.004,
                                             'connect_s': 0.0, 'take_s': 0.0}])  # IMAGE-SWAP-TICK: the parts of work_s
        slot.once()
        self.assertEqual(len(table.recorded()), 1)  # once per swap, whatever the slots

    def test_a_slow_swap_records_what_the_database_was_doing(self):
        table, gate, clock = self.turned('runner')
        table.busy = [(json.dumps([{'q': 'select work.take(', 'n': 4, 'ms': 310, 'active': 1}]), 23)]  # SWAP-TAIL-EVIDENCE
        clock.now += live_image.EVIDENCE_S  # the slot's wake and its TAKE: half the goal's second gone
        slot = runner.Runner(table, None, None, None, tempfile.gettempdir(), gate=gate)
        slot.execute = lambda run: None
        self.assertIsNone(slot.once())
        self.assertEqual([sql for sql, _ in table.sent[-4:]],  # SWAP-TAIL-EVIDENCE: the evidence is read after the TAKE
                         [runner.TAKE, live_image.BUSY, live_image.LIVE, live_image.LIVE_BEAT])
        (recorded,) = table.recorded()
        self.assertEqual((recorded['swap_s'], recorded['busy'], recorded['backends']),
                         (0.531, [{'q': 'select work.take(', 'n': 4, 'ms': 310, 'active': 1}], 23))
        self.assertEqual(table.sent[-3][1], {'window': 1.531})  # the swap's seconds and one more
        self.assertLessEqual(live_image.EVIDENCE_S, 0.5)  # of a goal of 1 s: the delay that needs a cause is seen

    def test_the_service_records_at_its_first_tick_with_dbos_launch_apart(self):
        table, gate, clock = self.turned('service')

        def start():
            clock.now += 0.12  # DBOS.launch: its migrations' check, the version, the recovery query, the threads
        launch = live_image.OnceLive(start, gate, clock=clock)
        launched = launch.done
        launch()
        clock.now += 0.015  # the first dispatch tick (workflows.tick)
        gate.working(launch_s=None if launched else launch.seconds)
        self.assertEqual(table.recorded(), [{'notify_s': 0.031, 'work_s': 0.135, 'swap_s': 0.166, 'launch_s': 0.12}])

    def test_a_standby_beats_on_its_own_pass_and_a_live_gate_has_nothing_to_record(self):
        table = Pointer(S)
        gate = live_image.Gate(table.scope, 'runner', S, task='task-9', strict=True)  # IMAGE-SWAP-FAILOVER: an ECS task's is WATCH
        gate.beat()
        gate.beat(table)
        self.assertEqual([params for sql, params in table.sent if sql == live_image.BEAT],
                         [{'role': 'runner', 'digest': S, 'task': 'task-9'}] * 2)
        gate.refresh()  # live from the start: no swap
        self.assertIsNone(gate.working())

    def test_the_serve_and_run_container_wiring(self):
        main = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn('gate.beat(loop)  # IMAGE-SWAP-TIGHTEN', main)  # IMAGE-SWAP-TICK: on the loop's connection
        self.assertLess(main.index("'dispatched': lambda parts: gate.working("), main.index('started = workflows.tick(lease, '))
        self.assertLess(main.index('launch()  # IMAGE-PREWARM-B2'), main.index('started = workflows.tick(lease, '))


class Measure(unittest.TestCase):
    def test_a_series_asks_the_status_for_its_landings_and_any_other_caller_reads_ten(self):
        # STATUS-LANDINGS: the goal is a p99 over N >= 10 landings, and the status keeps the newest ten: live 12/11 the
        # measure since 05:50 UTC said n=10 with fifteen landings in the series
        self.assertEqual(port.status_rows(None), (port.LIVE_ROWS, port.SWAP_ROWS))
        self.assertEqual(port.status_rows('100'), (200, 100))  # two image_live (one a role) and one image_swap a landing
        self.assertEqual(port.status_rows(3), (port.LIVE_ROWS, port.SWAP_ROWS))  # never fewer than every caller reads
        # FIRST-JOB-REHEARSED: and the canaries of those landings (a swap's and a reload's each)
        self.assertEqual((port.canary_rows(None), port.canary_rows(3), port.canary_rows('100')),
                         (port.CANARY_ROWS, port.CANARY_ROWS, 200))
        for odd in ('many', 0, -4, port.LANDINGS_MOST + 1, [], 2.5e9):
            self.assertEqual(port.status_rows(odd), (port.LIVE_ROWS, port.SWAP_ROWS), odd)
        asked = {}

        class Db:
            def rows(self, sql, params=None):
                for kind in ('image_live', 'image_swap', 'image_retired', 'fast'):
                    if f"'platform.deploy.{kind}'" in sql:
                        asked[kind] = params['limit']
                return []
        port.deploy_status(Db(), ('tenant', None), landings='60')
        # FAST-SERIES: and the Lambdas' swaps of the series from the log, as many as its image swaps
        self.assertEqual(asked, {'image_live': 120, 'image_swap': 60, 'image_retired': port.SWAP_ROWS, 'fast': 60})
        asked.clear()
        said = port.deploy_status(Db(), ('tenant', None))
        self.assertEqual(asked, {'image_live': port.LIVE_ROWS, 'image_swap': port.SWAP_ROWS, 'image_retired': port.SWAP_ROWS})
        self.assertEqual(said['fast'], [])  # any other caller: the observation's newest (none here)
        from tower_infra import http_port
        route = next(act for verb, pattern, act in http_port.ROUTES if (verb, pattern) == ('GET', r'/v1/deploy/status'))
        route(Db(), ('tenant', None), {'landings': '40'})  # a GET's query is its body
        self.assertEqual((asked['image_live'], asked['image_swap']), (80, 40))
        route(Db(), ('tenant', None), None)
        self.assertEqual(asked['image_swap'], port.SWAP_ROWS)
        calls = []

        class Port:
            def call(self, method, path, body=None):
                calls.append((method, path))
                return {'image_swap': []}
        self.assertEqual(medir.deploy_status_of(Port(), medir.LANDINGS), {'image_swap': []})
        self.assertEqual(medir.deploy_status_of(Port()), {'image_swap': []})
        self.assertEqual(calls, [('GET', f'/v1/deploy/status?landings={medir.LANDINGS}'), ('GET', '/v1/deploy/status')])
        self.assertLessEqual(medir.LANDINGS, port.LANDINGS_MOST)
        text = (ROOT / 'scripts/lib/medir.py').read_text()
        self.assertIn('deploy_status_of(port, LANDINGS if since else None), since)', text)  # only a series asks for more

    def test_every_code_only_landing_counts_by_the_path_it_took(self):
        # IMAGE-CODE-LANDING: the 1 s goal is the p99 of every landing, not the best swap: a landing whose standby Spot
        # took reloads in place (tens of seconds) and one with a busy runner or a moved base takes the slow path (minutes)
        swapped = {'swapped': True, 'head': 'h1', 'digest': S, 'landed_s': 0.004, 'decide_s': 0.006,
                   'versions': {'deploy.live_image_runner': 3, 'deploy.live_image_service': 3}}
        status = {'image_swap': [swapped,
                                 {'swapped': False, 'head': 'h2', 'why': 'no healthy service standby'},  # reloaded in place
                                 {'swapped': False, 'head': 'h3', 'why': 'no healthy runner standby'},  # its order never ended
                                 {'swapped': False, 'head': 'h4', 'why': 'the base moved'},  # no order at all
                                 {**swapped, 'head': 'h5', 'digest': 'unrecorded'}],  # a swap with no first work recorded
                  'image_live': [{'role': 'runner', 'digest': S, 'version': 3, 'swap_s': 0.05},
                                 {'role': 'service', 'digest': S, 'version': 3, 'swap_s': 0.2}],
                  'image_reload': [{'state': 'ordered', 'head': 'h2', 'order': 'h2', 'landed_s': 0.13},
                                   {'state': 'reloaded', 'order': 'h2', 'role': 'runner', 'reload_s': 2.4},
                                   {'state': 'reloaded', 'order': 'h2', 'role': 'service', 'reload_s': 22.0},
                                   {'state': 'ordered', 'head': 'h3', 'order': 'h3', 'landed_s': 0.35},
                                   {'state': 'reloaded', 'role': 'service', 'reload_s': 9.0}]}  # a swap's reload: no order
        found = medir.from_deploy_status(status)
        self.assertEqual(found['image_code_landing_s'], [0.21, 22.13, medir.SLOW_S, medir.SLOW_S])
        self.assertEqual(found['image_code_landing_over_1s_s'], [22.13, medir.SLOW_S, medir.SLOW_S])
        self.assertEqual(found['image_code_landing_slow_s'], [medir.SLOW_S, medir.SLOW_S])
        self.assertNotIn('image_code_landing_s', medir.from_deploy_status({'image_swap': []}))

    def test_a_swap_that_was_taken_back_counts_as_the_slow_path_whatever_its_first_work_says(self):
        # PROMOTED-SUCCESSOR-STAYS: live 11/11 23:58 UTC the swap of #548 had both roles working in 0.694 s, the promoted
        # successors were stopped 8 s later and handed the pointers back, and the head was deployed with a rollout
        swap = {'swapped': True, 'head': 'h1', 'digest': S, 'landed_s': 0.164, 'decide_s': 0.197,
                'versions': {'deploy.live_image_runner': 75, 'deploy.live_image_service': 77}}
        status = {'image_swap': [swap],
                  'image_live': [{'role': 'runner', 'digest': S, 'version': 75, 'swap_s': 0.24},
                                 {'role': 'service', 'digest': S, 'version': 77, 'swap_s': 0.333}]}
        self.assertEqual(medir.image_code_landing(status), [0.694])
        for by in ('handover', 'reconciled'):  # the swap held: the promoted process keeps the role, or the deploy caught up
            kept = {**status, 'image_retired': [{'by': by, 'role': 'service', 'digest': S}]}
            self.assertEqual(medir.image_code_landing(kept), [0.694], by)
        for by in medir.TAKEN_BACK:
            back = {**status, 'image_retired': [{'by': by, 'role': 'runner', 'digest': S}, {'by': 'handover', 'digest': 'other'}]}
            self.assertEqual(medir.image_code_landing(back), [medir.SLOW_S], by)
        self.assertEqual(medir.TAKEN_BACK, ('handback', 'failover', 'canary', 'revert'))

    def test_landing_to_the_later_role_working(self):
        swap = {'swapped': True, 'digest': S, 'landed_s': 0.004, 'decide_s': 0.006,
                'versions': {'deploy.live_image_runner': 3, 'deploy.live_image_service': 3}}
        status = {'image_swap': [swap, {**swap, 'digest': 'other'}, {'swapped': False, 'why': 'x'}],
                  'image_live': [{'role': 'runner', 'digest': S, 'version': 3, 'swap_s': 0.05},
                                 {'role': 'service', 'digest': S, 'version': 3, 'swap_s': 0.2},
                                 {'role': 'service', 'digest': S, 'version': 2, 'swap_s': 9.0}]}
        found = medir.from_deploy_status(status)
        self.assertEqual(found['image_landing_to_live_s'], [0.21])
        self.assertEqual(found['image_swap_s'], [0.05, 0.2, 9.0])  # the existing lines stay
        old = {'image_swap': [{'swapped': True, 'digest': S, 'landed_s': 0.385, 'versions': {key: 3 for key in KEYS}}],
               'image_live': [{'role': 'service', 'digest': S, 'version': 3, 'swap_s': 0.926},
                              {'role': 'runner', 'digest': S, 'version': 3, 'swap_s': 0.495}]}
        self.assertEqual(medir.image_landing_to_live(old), [1.311])  # #466, 09/11: over 1 s


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements: the beats, the landing that swaps in its own statement (or says why), the gate's notify_s and
    the image_live of its parts, and the measure from the status."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db = self.world.db
        tenant = self.db.rows("select id::text from work.tenant where name = 'torre'")[0][0]
        push = {'refUpdates': [{'ref': 'refs/heads/mod/roadmap-integration', 'before': '0' * 40, 'after': BASE}]}
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                     "('push:1', %(tenant)s::uuid, 'forge.repository.pushed', clock_timestamp() - interval '1 minute', "
                     "'forge/origin', 'app/origin', %(payload)s::jsonb)",
                     {'tenant': tenant, 'payload': json.dumps({'delivery': {'event': {'payload': push}}})})
        for head in (PR_HEAD, NEXT_HEAD):
            job = self.world.job(f'prewarm:code:{head}', 'true')
            self.db.rows("update work.job set state = 'succeeded', result = %(result)s::jsonb where id = %(id)s::uuid",
                         {'id': job, 'result': said(S)})
        self.standbys = {role: live_image.gate(role, S, live_image.kept(self.db), task=f'{role}-standby', strict=True)
                         for role in ('runner', 'service')}

    def test_the_landing_s_commit_does_not_wait_for_the_disk(self):
        """LANDING-ASYNC-COMMIT: the pointers' notification leaves when the landing's transaction commits, and a commit
        waits for the WAL to reach the disk. On a host that pages (12/11: 420 to 620 MB in swap on the db.t4g.micro) that
        disk is the swap's too: COMMITs of 0.10 to 0.25 s in the evidence of every slow landing, and the roles read the
        pointer 0.2 to 0.47 s after its write. The landing's statement sets synchronous_commit off for its own
        transaction: the commit answers and notifies at once and the WAL follows within the writer's delay. What a crash
        inside that delay would lose is the landing's record and its pointers, both together: the merge is at the
        forge, and its push takes the head to the slow path, the net that was always there."""
        from infra_db.psql import PLACEHOLDER, literal
        self.assertIn("set_config('synchronous_commit', 'off', true)", port.LANDED_SWAP)
        params = {'id': 'platform.deploy.landed:t', 'digest': S, 'fresh_s': 3, 'keys': ','.join(KEYS), 'reason': 't',
                  'config_tenant': 'torre', 'tenant': None, 'payload': '{}', 'why': '', 'swap_id': 'platform.deploy.image_swap:t',
                  'swap': '{}'}
        landing = PLACEHOLDER.sub(lambda found: literal(params[found.group(1)]), port.LANDED_SWAP)
        server = self.db.rows("select current_setting('synchronous_commit')")
        said = self.db.call(['-A', '-t', '-c', "begin; set local synchronous_commit = on; select 'before: ' || "
                             f"current_setting('synchronous_commit'); {landing}; "
                             "select 'commit: ' || current_setting('synchronous_commit'); commit"])
        self.assertIn('commit: off', said)  # the statement turned it off, in the landing's own transaction
        self.assertEqual(self.db.rows("select current_setting('synchronous_commit')"), server)  # and in no other

    def beat(self, *roles, ago_s=0):
        for role in roles:
            self.standbys[role].beat()
        self.db.rows("update work.standby_beat set beat_at = clock_timestamp() - make_interval(secs => %(ago)s::float8)",
                     {'ago': ago_s})

    def pointers(self):
        return self.db.rows("select key, value::text, version::text, actor from work.config_value "
                            "where key like 'deploy.live_image_%%' order by key")

    def test_the_landing_swaps_in_its_own_statement_and_the_roles_record_their_parts(self):
        self.beat('runner', 'service')
        said_ = self.world.port('POST', '/v1/deploy/landed', 'torre', landed())
        self.assertEqual(said_['swap'], {'swapped': True})
        swap = said_['image_swap']
        self.assertEqual((swap['by'], swap['digest'], swap['versions']), ('landing', S, {key: 1 for key in KEYS}))
        self.assertGreaterEqual(swap['landed_s'], 0)
        self.assertLess(swap['landed_s'], 0.2)  # one statement; the old path was a service look, 0.31-0.39 s live
        self.assertEqual(self.pointers(), [(key, json.dumps(S), '1', 'port') for key in KEYS])
        self.assertTrue(self.db.rows(autodeploy.SWAP_OF, {'id': f'{autodeploy.SWAP}:{MERGE}'}))  # the fallback stays out
        again = self.world.port('POST', '/v1/deploy/landed', 'torre', landed())  # the same landing: nothing new
        self.assertNotIn('swap', again)
        self.assertEqual([row[2] for row in self.pointers()], ['1', '1'])
        for role, gate in self.standbys.items():
            self.assertTrue(gate.refresh())
            self.assertGreaterEqual(gate.swapped[1], 0)  # notify_s on the database clock
            gate.working(**({'launch_s': 0.05} if role == 'service' else {}))
        status = self.world.port('GET', '/v1/deploy/status', 'torre')
        live = {each['role']: each for each in status['image_live']}
        self.assertEqual(set(live['service']) >= {'notify_s', 'work_s', 'swap_s', 'launch_s'}, True)
        self.assertAlmostEqual(live['runner']['swap_s'], live['runner']['notify_s'] + live['runner']['work_s'],
                               delta=0.0011)  # each is rounded to the millisecond by itself
        self.assertEqual(len(medir.image_landing_to_live(status)), 1)

    def test_a_stale_or_missing_beat_says_why_and_the_freshness_is_the_registrys(self):
        self.beat('runner', 'service', ago_s=10)
        said_ = self.world.port('POST', '/v1/deploy/landed', 'torre', landed())
        self.assertEqual(said_['swap'], {'swapped': False,
                                         'why': f'no beat of the runner or service standby of {S[:12]} in the last 3 s'})
        self.assertEqual(self.pointers(), [])
        self.assertFalse(self.db.rows(autodeploy.SWAP_OF, {'id': f'{autodeploy.SWAP}:{MERGE}'}))  # the autodeploy decides
        stored = self.db.rows("select payload->'swap'->>'why' from log.event where type = 'platform.deploy.landed'")
        self.assertTrue(stored[0][0].startswith('no beat'))
        self.world.port('PUT', '/v1/config/deploy.standby_fresh_s', 'torre', {'value': 30.0, 'reason': 'test'})
        self.beat('service', ago_s=10)
        said_ = self.world.port('POST', '/v1/deploy/landed', 'torre', landed(merge=NEXT, base=MERGE, head=NEXT_HEAD))
        self.assertEqual(said_['swap'], {'swapped': True})

    def test_the_landing_alone_is_recorded_once_as_before(self):
        params = {'id': f'{port.LANDED}:{MERGE}', 'tenant': None, 'payload': json.dumps(landed())}
        self.assertEqual((self.db.rows(port.LANDED_ONLY, params), self.db.rows(port.LANDED_ONLY, params)), ([('1',)], []))

    def test_a_landing_that_is_not_code_only_is_recorded_with_nothing_about_a_swap(self):
        self.beat('runner', 'service')
        said_ = self.world.port('POST', '/v1/deploy/landed', 'torre', landed(code_only=False))
        self.assertEqual(said_, {'event_id': f'{port.LANDED}:{MERGE}', 'merge_sha': MERGE})
        stored = self.db.rows("select payload ? 'swap' from log.event where type = 'platform.deploy.landed'")
        self.assertEqual((stored, self.pointers()), ([('f',)], []))

    def test_one_role_without_a_beat_or_a_moved_base_never_swaps(self):
        self.beat('service')
        self.assertIn('no beat of the runner standby', self.world.port('POST', '/v1/deploy/landed', 'torre', landed())['swap']['why'])
        self.beat('runner', 'service')
        said_ = self.world.port('POST', '/v1/deploy/landed', 'torre', landed(merge=NEXT, base=BASE, head=NEXT_HEAD))
        self.assertTrue(said_['swap']['why'].startswith("the merge's parent is not base_before"))  # MERGE landed between
        self.assertEqual(self.pointers(), [])


if __name__ == '__main__':
    unittest.main()
