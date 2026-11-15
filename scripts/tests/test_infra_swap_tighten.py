"""IMAGE-SWAP-TIGHTEN (docs/operations/aws.md 22.9): the image-only swap from the landing to both roles working, under 1 s.

1. Landing -> pointer: LANDING-PREWARM-GONE (D-316): the landing (POST /v1/deploy/landed) swapped onto the bundle a
   prewarm job built; the prewarm left, and the landing is a record alone. The merge queue's swap writes the pointers
   (queue_deploy.SWAP, test_infra_queue_reload).
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
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import live_image, port, runner  # noqa: E402
import medir  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
BASE, MERGE, PR_HEAD, NEXT, NEXT_HEAD = 'b' * 40, '9' * 40, '8' * 40, '6' * 40, '5' * 40
S = 'a' * 64
KEYS = sorted(live_image.KEYS.values())


def landed(merge=MERGE, base=BASE, head=PR_HEAD, **code):
    return {'merge_sha': merge, 'base_before': base, 'pr_head': head, 'pr': '7', 'functions': [], 'paths': [],
            'code': {'code_only': True, 'why': '1 file(s)', 'bundle_same': True, **code}}


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
    """The real statements: the beats and the landing, recorded alone."""

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
        self.standbys = {role: live_image.gate(role, S, live_image.kept(self.db), task=f'{role}-standby', strict=True)
                         for role in ('runner', 'service')}

    def beat(self, *roles, ago_s=0):
        for role in roles:
            self.standbys[role].beat()
        self.db.rows("update work.standby_beat set beat_at = clock_timestamp() - make_interval(secs => %(ago)s::float8)",
                     {'ago': ago_s})

    def pointers(self):
        return self.db.rows("select key, value::text, version::text, actor from work.config_value "
                            "where key like 'deploy.live_image_%%' order by key")

    def test_the_landing_alone_is_recorded_once_as_before(self):
        params = {'id': f'{port.LANDED}:{MERGE}', 'tenant': None, 'payload': json.dumps(landed())}
        self.assertEqual((self.db.rows(port.LANDED_ONLY, params), self.db.rows(port.LANDED_ONLY, params)), ([('1',)], []))

    def test_any_landing_is_recorded_with_nothing_about_a_swap(self):
        # LANDING-PREWARM-GONE: a code-only landing whose bundle's standbys beat swaps nothing either
        self.beat('runner', 'service')
        for each in (landed(code_only=False), landed(merge=NEXT, base=MERGE, head=NEXT_HEAD)):
            said_ = self.world.port('POST', '/v1/deploy/landed', 'torre', each)
            self.assertEqual(said_, {'event_id': f"{port.LANDED}:{each['merge_sha']}", 'merge_sha': each['merge_sha']})
        stored = self.db.rows("select payload ? 'swap' from log.event where type = 'platform.deploy.landed'")
        self.assertEqual((stored, self.pointers()), ([('f',), ('f',)], []))


if __name__ == '__main__':
    unittest.main()
