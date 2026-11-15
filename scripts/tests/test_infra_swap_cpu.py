"""SWAP-CPU (docs/operations/aws.md 22.9): what the task's CPU quota holds back in the second of a swap, said in the
swap's record, and the CPU taken out of that second.

The drills of 12/11 with the task's pool (#609, #610): the service's new code at work 1.48 to 1.54 s after the pointer
with no login, of which its gate's first read was 0.36 s (one statement, through the engine's first connection with
its dialect's setup and its ping) where the runner's took 0.08 s (a kept psycopg connection). The task has a quarter
of a vCPU, a quota of 25 ms in every 100 ms shared by every process of the task.

1. The cgroup's cpu.stat, v2 and v1, read; the record of a process told to go says, from the word to its first work,
   the wall time, the CPU the task used and how long the quota held it back.
2. The service's gate reads first through its loop's own connection; the threads of no work of the role (the
   autodeploy's look) run at a lower priority.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from tower_infra import code_bundle, live_image, reserve  # noqa: E402
from test_infra_swap_failover import S, Table  # noqa: E402


class TheQuotaIsRead(unittest.TestCase):
    def folder(self, files):
        root = Path(tempfile.mkdtemp(prefix='sc-'))
        self.addCleanup(shutil.rmtree, root, True)
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text)
        return root

    def test_the_cgroup_s_cpu_stat_of_either_version(self):
        two = self.folder({'cpu.stat': 'usage_usec 9000000\nuser_usec 7000000\nsystem_usec 2000000\nnr_periods 500\n'
                                       'nr_throttled 42\nthrottled_usec 1250000\n'})
        self.assertEqual(live_image.cpu(two), {'usage_us': 9000000, 'nr_throttled': 42, 'throttled_us': 1250000})
        one = self.folder({'cpu/cpu.stat': 'nr_periods 500\nnr_throttled 7\nthrottled_time 3000000000\n',
                           'cpuacct/cpuacct.usage': '5000000000\n'})
        self.assertEqual(live_image.cpu(one), {'usage_us': 5000000, 'nr_throttled': 7, 'throttled_us': 3000000})
        self.assertEqual(live_image.cpu(self.folder({})), {})
        self.assertIn('usage_us', live_image.cpu())  # this machine's own, for real

    def test_from_the_word_to_the_first_work_the_task_s_cpu_and_what_the_quota_held_back(self):
        said = json.dumps({'usage_us': 1000000, 'nr_throttled': 10, 'throttled_us': 500000, 'at': 100.0})
        now = {'usage_us': 1380000, 'nr_throttled': 19, 'throttled_us': 1360000}
        self.assertEqual(live_image.cpu_since(said, now, clock=lambda: 101.2),
                         {'cpu': {'wall_ms': 1200.0, 'usage_ms': 380.0, 'throttled_ms': 860.0, 'nr_throttled': 9}})
        self.assertEqual(live_image.cpu_since(None, now), {})  # no word: no measure
        self.assertEqual(live_image.cpu_since('not json', now), {})
        partial = live_image.cpu_since(json.dumps({'usage_us': 1, 'at': 100.0}), {'usage_us': 2001}, clock=lambda: 100.5)
        self.assertEqual(partial, {'cpu': {'wall_ms': 500.0, 'usage_ms': 2.0}})

    def test_the_word_keeps_the_task_s_cpu_and_the_record_says_it(self):
        environ = {'TOWER_SUPERVISOR_CHILD': '4'}
        before = live_image.BORN
        self.addCleanup(setattr, live_image, 'BORN', before)
        with mock.patch.object(live_image, 'cpu', lambda: {'usage_us': 7, 'nr_throttled': 1, 'throttled_us': 2}):
            reserve.hold('serve', environ, wait=lambda signals: None, tell=lambda *a, **k: True, prepare=lambda c, e: [],
                         age=lambda: 30.0, mask=lambda how, signals: None, handle=lambda signum, how: None,
                         lower=lambda: None, raise_=lambda before: None)
        kept = json.loads(environ[code_bundle.CPU_AT])
        self.assertEqual({name: kept[name] for name in ('usage_us', 'nr_throttled', 'throttled_us')},
                         {'usage_us': 7, 'nr_throttled': 1, 'throttled_us': 2})
        table = Table(S)
        with mock.patch.object(live_image.code_bundle, 'age_s', return_value=31.0), \
                mock.patch.dict(os.environ, {code_bundle.WENT: '30.0', code_bundle.CPU_AT: json.dumps(
                    {'usage_us': 0, 'nr_throttled': 0, 'throttled_us': 0, 'at': 0.0})}), \
                mock.patch.object(live_image, 'cpu', lambda: {'usage_us': 300000, 'nr_throttled': 4, 'throttled_us': 700000}):
            went = live_image.gate('runner', S, table.scope, task='held', strict=True, intask=True, clock=table.clock)
            said = went.working()
        self.assertEqual({name: said['cpu'][name] for name in ('usage_ms', 'throttled_ms', 'nr_throttled')},
                         {'usage_ms': 300.0, 'throttled_ms': 700.0, 'nr_throttled': 4})


class TheSecondIsLighter(unittest.TestCase):
    def test_the_gate_s_first_read_goes_through_the_scope_it_is_given(self):
        table, other, asked = Table(S), Table(S), []

        def first():
            asked.append('first')
            return other.scope()
        gate = live_image.gate('service', S, table.scope, task='t', strict=True, clock=table.clock, first=first)
        self.assertEqual((asked, gate.pointer, gate.live), (['first'], S, True))
        table.write('')
        gate.refresh()  # every later read: the gate's own scope
        self.assertEqual((asked, gate.live), (['first'], False))

    def test_a_thread_of_no_work_of_the_role_runs_lower_for_good(self):
        done = threading.Event()
        thread = threading.Thread(target=done.wait, daemon=True)
        thread.start()
        self.addCleanup(done.set)
        set_ = []
        self.assertTrue(live_image.lowly(thread, set_=lambda which, who, value: set_.append((which, who, value))))
        self.assertEqual(set_, [(os.PRIO_PROCESS, thread.native_id, 10)])
        self.assertTrue(live_image.lowly(thread))  # for real: raising a thread's nice needs no privilege
        self.assertEqual(os.getpriority(os.PRIO_PROCESS, thread.native_id), 10)
        self.assertNotEqual(os.getpriority(os.PRIO_PROCESS, threading.get_native_id()), 10)  # the caller's is not touched
        self.assertFalse(live_image.lowly(None))
        refused = live_image.lowly(thread, set_=mock.Mock(side_effect=PermissionError('no')))
        self.assertFalse(refused)

    def test_a_late_service_reads_its_settings_on_its_loop_s_connection(self):
        from tower_infra import config_data
        asked = []

        class Db:
            def rows(self, sql, params=None):
                return []

        def scope_of(name):
            import contextlib

            @contextlib.contextmanager
            def scope():
                asked.append(name)
                yield Db()
            return scope
        settings = config_data.Config(scope_of('engine'))
        settings.refresh(scope_of('loop'))
        settings.refresh()
        self.assertEqual(asked, ['loop', 'engine'])
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn('    settings.refresh(loop.scope if loop is not None and gate.boot else None)\n', source)
        self.assertLess(source.index('settings.refresh(loop.scope'), source.index("live_image.mark(gate, 'settings')"))

    def test_the_wiring(self):
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        serve = source[source.index('def serve('):source.index('\ndef ', source.index('def serve(') + 1)]
        self.assertIn('    live_image.lowly(autodeploy.start(workflows.connected,', serve)
        self.assertNotIn('standbys.start(', serve)  # GATE-LOOKS-GONE: the prewarm's look left
        self.assertIn('timed.update(cpu_since(os.environ.get(code_bundle.CPU_AT)))',
                      (ROOT / 'infra/service/tower_infra/live_image.py').read_text(encoding='utf-8'))



class TheLaunchComesAfterTheClaims(unittest.TestCase):
    """LAUNCH-AFTER-CLAIM: a late service's DBOS.launch was 1.28 s of its 2.38 s with no login (12/11 23:11 UTC); its
    first pass's claims (the role's work: a runner takes the run from the database) come first, its workflows after."""

    def tick(self, launch, made):
        from test_infra_swap_ready import workflows_with
        started, order = [], []
        workflows = workflows_with(started)
        import contextlib

        @contextlib.contextmanager
        def scope():
            yield 'the loop'
        with mock.patch.object(workflows.mechanisms, 'reap', lambda db: order.append('reap')), \
                mock.patch.object(workflows.mechanisms, 'dispatch', lambda db, lease, claimed: order.append('claims') or made):
            try:
                found = workflows.tick('5 minutes', dispatched=lambda parts: order.append('recorded'), scope=scope,
                                       launch=None if launch is None else lambda: order.append('launch') or launch())
            except RuntimeError as error:
                found = error
        return workflows, order, started, found

    def test_the_claims_and_the_swap_s_record_come_before_the_launch_and_the_workflows_after_it(self):
        runs = [{'run': 'r1', 'cached': False}, {'run': 'r2', 'cached': True}]
        workflows, order, started, found = self.tick(lambda: None, runs)
        self.assertEqual(order, ['reap', 'claims', 'recorded', 'launch'])
        self.assertEqual((started, found), (['r1'], ['r1']))
        _, order, started, _ = self.tick(None, runs)  # any other pass: as before
        self.assertEqual((order, started), (['reap', 'claims', 'recorded'], ['r1']))

    def test_a_launch_that_fails_loses_no_claimed_run(self):
        def broken():
            raise RuntimeError('the database refused the launch')
        workflows, order, started, found = self.tick(broken, [{'run': 'r1', 'cached': False}])
        self.assertIsInstance(found, RuntimeError)
        self.assertEqual((started, [each['run'] for each in workflows.LEFT]), ([], ['r1']))  # kept, not started
        import contextlib

        @contextlib.contextmanager
        def scope():
            yield 'the loop'
        with mock.patch.object(workflows.mechanisms, 'reap', lambda db: None), \
                mock.patch.object(workflows.mechanisms, 'dispatch', lambda db, lease, claimed: []):
            self.assertEqual(workflows.tick('5 minutes', scope=scope, launch=lambda: None), ['r1'])  # the next pass starts it
        self.assertEqual((started, workflows.LEFT), (['r1'], []))

    def test_the_wiring(self):
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn('    deferred = gate is not None and bool(gate.boot)\n', source)
        self.assertIn("            if deferred and not launched:  # LAUNCH-AFTER-CLAIM", source)
        self.assertIn("                timed['launch'] = launch", source)
        self.assertIn('            if not deferred or launched:\n                launch()', source)
        self.assertLess(source.index('    deferred = gate is not None and bool(gate.boot)'), source.index('    elif not launch():'))



class TheSwapSecond(unittest.TestCase):
    """SWAP-SECOND: what the database does in the second of a swap, said by the process that covers; and a late
    service's first pass claims before it reaps."""

    def test_a_late_first_pass_claims_before_it_reaps(self):
        from test_infra_swap_ready import workflows_with
        import contextlib
        order, started = [], []
        workflows = workflows_with(started)

        @contextlib.contextmanager
        def scope():
            yield 'the loop'
        with mock.patch.object(workflows.mechanisms, 'reap', lambda db: order.append('reap')), \
                mock.patch.object(workflows.mechanisms, 'dispatch', lambda db, lease, claimed: order.append('claims') or []):
            workflows.tick('5 minutes', scope=scope, dispatched=lambda parts: order.append('recorded'), reap_after=True)
            workflows.tick('5 minutes', scope=scope, dispatched=lambda parts: order.append('recorded'))
        self.assertEqual(order, ['claims', 'reap', 'recorded', 'reap', 'claims', 'recorded'])
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn("                timed['reap_after'] = True", source)

    def test_the_process_that_covers_reads_the_database_a_few_times_and_says_it_with_the_cover_s_end(self):
        table = Table(S)
        gate = live_image.Gate(table.scope, 'service', 'b' * 64, task='covers', clock=table.clock)
        readings = iter(range(100))
        with mock.patch.object(live_image, 'busy', lambda db, window_s: {'busy': [{'q': 'insert', 'ms': 240, 'waits': ['cpu']}],
                                                                        'backends': next(readings)}):
            with mock.patch.object(live_image, 'SAMPLES', 5):  # asked for (TOWER_COVER_SAMPLES)
                for at in range(7):
                    gate.sample(table, at * 0.25)
        self.assertEqual([(each['at_s'], each['backends']) for each in gate.samples],
                         [(0.0, 0), (0.25, 1), (0.5, 2), (0.75, 3), (1.0, 4)])  # SAMPLES at most: a light reading
        with mock.patch.object(live_image, 'busy', lambda db, window_s: {}):
            gate.samples = []
            gate.sample(table, 0.1)
        self.assertEqual(gate.samples, [])  # nothing read: nothing said
        # SAMPLES-OFF: by default none is read (the reading itself was 471 ms of the database's CPU in that second)
        self.assertEqual(live_image.SAMPLES, 0)
        with mock.patch.object(live_image, 'busy', lambda db, window_s: self.fail('no reading by default')):
            gate.sample(table, 0.2)
        source = Path(live_image.__file__).read_text(encoding='utf-8')
        self.assertIn("**({'samples': self.samples} if self.samples else {})}  # SWAP-SECOND", source)
        self.assertIn('self.sample(db, covered_s)', source)

    def test_the_marks_between_dbos_and_the_settings(self):
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        names = ["live_image.mark(gate, 'dbos')", "live_image.mark(gate, 'providers')", "live_image.mark(gate, 'lifecycle')",
                 "live_image.mark(gate, 'orders')", "live_image.mark(gate, 'settings')"]
        self.assertEqual(sorted(names, key=source.index), names)



class TheSettingsAreHanded(unittest.TestCase):
    """SETTINGS-HANDED: the late service's settings read was 0.73 s of its 1.18 s at the drill of 12/11 23:53 UTC (one
    statement on a database busy in the swap's second); it starts with what the task's other process read, and reads
    the table itself after its first work."""

    def config(self, keep, rows, tenant='torre'):
        from tower_infra import config_data
        import contextlib

        class Db:
            def rows(self, sql, params=None):
                return rows

        @contextlib.contextmanager
        def scope():
            yield Db()
        return config_data.Config(scope, tenant, keep=keep)

    def test_a_read_leaves_its_values_and_another_process_starts_with_them(self):
        folder = Path(tempfile.mkdtemp(prefix='sh-'))
        self.addCleanup(shutil.rmtree, folder, True)
        keep = str(folder / 'settings.json')
        live = self.config(keep, [('service.dispatch_s', '2', '7'), ('deploy.live_stale_s', '12', '3')])
        with mock.patch.object(type(live), 'observe', lambda self, before: None):
            live.refresh()
        late = self.config(keep, lambda: self.fail('no read before its first work'))
        self.assertTrue(late.kept())
        self.assertEqual((late.get('service.dispatch_s'), late.get('deploy.live_stale_s'), late.versions),
                         (2, 12, {'service.dispatch_s': 7, 'deploy.live_stale_s': 3}))
        self.assertFalse(self.config(keep, [], tenant='another').kept())  # another tenant's: not taken
        (folder / 'settings.json').write_text('{"tenant": "torre", "values": {"no.such.key": 1}, "versions": {"no.such.key": 1}}')
        self.assertFalse(self.config(keep, []).kept())  # a value the registry refuses: the table is read, as before
        self.assertFalse(self.config(None, []).kept())
        self.assertFalse(self.config(str(folder / 'none.json'), []).kept())

    def test_the_wiring(self):
        source = (ROOT / 'infra/service/tower_infra/__main__.py').read_text(encoding='utf-8')
        self.assertIn("keep=os.path.join(spool, 'settings.json') if spool else None)", source)
        self.assertIn('    handed = gate is not None and bool(gate.boot) and settings.kept()\n    if not handed:\n', source)
        after = source.index('            if handed:  # SETTINGS-HANDED')
        self.assertLess(source.index('started = workflows.tick(lease, **timed)'), after)
        self.assertIn('                settings.refresh(loop.scope)\n', source[after:after + 200])


if __name__ == '__main__':
    unittest.main()
