"""The merge train's role (plan v3 M3, D-065 (1)): the lock, the drain loop, the flag, the ownership interface
(fixture manifests) and the Origin adapter's train operations. Fake forge, fake gate, real local git, injected clock; no network (test_train.py holds the fixture).
"""
from datetime import datetime
import io
import os
from pathlib import Path
import sys
import unittest
import unittest.mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_train import REPO, ROOT, FakeClock, Fixture, config, engine_role, forge_events, train  # noqa: E402
import forge_doubles  # noqa: E402
import train_ownership  # noqa: E402
import forge_git_ref  # noqa: E402
import forge_origin  # noqa: E402
import forge_origin_client  # noqa: E402
import train_trigger  # noqa: E402


def setUpModule():
    """An empty change store chosen explicitly: registry values only, never the forge (D-069 item 5)."""
    unittest.enterModuleContext(config.use_adapter(forge_events.MemoryAdapter()))


class Role(Fixture):
    def setUp(self):
        super().setUp()
        # The infrastructure runner names the lock owner and deadline of the job in the check's environment; the
        # box does not. These tests judge the owner from what each sets itself, so the runner's values are removed.
        env = dict(os.environ)
        for name in (engine_role.service_budget.OWNER_ENV, engine_role.service_budget.DEADLINE_ENV):
            env.pop(name, None)
        self.enterContext(unittest.mock.patch.dict(os.environ, env, clear=True))
        self.lock_ref = engine_role.setting('train.lock_ref')

    def test_runs_batches_until_the_queue_is_empty_then_releases(self):
        for number in range(1, 4):
            self.pr(number, {f'f{number}.txt': 'x\n'})
        self.train.batch_size = self.train.queue_growing_batches = 1  # explicit overrides: three batches of one
        self.assertEqual(self.train.run('lane-a'), 'drained')
        self.assertEqual(self.forge.merges, [1, 2, 3])
        self.assertEqual(len(self.events(None, 'train.batch.green')), 3)
        [growing] = self.events(None, 'train.queue.growing')
        self.assertEqual((growing['payload']['queue_size'], growing['payload']['batch_size']), (2, 1))
        self.assertGreater(growing['payload']['tier2_ms'], 0)
        [empty] = self.events(None, 'train.queue.empty')
        self.assertEqual(empty['payload']['sha'], self.run_git(self.origin, 'rev-parse', self.base_branch))
        self.assertNotIn(self.lock_ref, self.forge.locks)
        self.assertEqual(self.forge.lock_calls.count('lane-a'), 1, 'taken once until the deadline, never renewed (D-291)')

    def test_a_held_lock_leaves_the_work_to_its_holder(self):
        self.pr(1, {'c.txt': 'x\n'})
        self.forge.locks[self.lock_ref] = {'owner': 'lane-b', 'expires': '2999-01-01T00:00:00.000Z'}
        self.assertEqual(self.train.run('lane-a'), 'busy')
        self.assertEqual(self.forge.merges, [])
        self.assertEqual(self.forge.locks[self.lock_ref]['owner'], 'lane-b')

    def test_an_expired_lock_is_taken_over(self):
        self.pr(1, {'c.txt': 'x\n'})
        self.forge.locks[self.lock_ref] = {'owner': 'lane-b', 'expires': '2000-01-01T00:00:00.000Z'}
        self.assertEqual(self.train.run('lane-a'), 'drained')
        self.assertEqual(self.forge.merges, [1])

    def test_a_run_past_its_deadline_stops_before_judging_and_releases_with_the_reason(self):
        """D-291: the lock is held until the deadline; a run that reaches it stops before it judges or merges, and its
        release record says why."""
        self.pr(1, {'c.txt': 'x\n'})
        left = iter([5.0])  # the take sees 5 s left; every later check finds the budget spent
        with unittest.mock.patch.object(engine_role.service_budget, 'remaining', side_effect=lambda when: next(left, -1.0)):
            with self.assertRaises(engine_role.service_budget.OverBudget):
                self.train.run('lane-a')
        self.assertEqual((self.forge.merges, self.gate.runs), ([], []))
        self.assertNotIn(self.lock_ref, self.forge.locks)
        [(name, owner, died)] = self.forge.deaths
        self.assertEqual((name, owner), (self.lock_ref, 'lane-a'))
        self.assertTrue(died.startswith('OverBudget: '), died)

    def test_a_run_that_dies_releases_the_lock_with_its_reason(self):
        """TRAIN-TEMP-FIX R1: the runner VM's runs took the lock, raised on the log read and released it in ~3 s
        with nothing that named the cause; the release now carries it."""
        self.pr(1, {'c.txt': 'x\n'})

        def unreadable():
            raise RuntimeError('no events token: set $TOWER_EVENTS_TOKEN\nsecond line')
        self.train.queue = unreadable
        with self.assertRaises(RuntimeError):
            self.train.run('lane-a')
        self.assertNotIn(self.lock_ref, self.forge.locks, 'released, as before')
        self.assertEqual(self.forge.deaths,
                         [(self.lock_ref, 'lane-a', 'RuntimeError: no events token: set $TOWER_EVENTS_TOKEN')])
        self.assertEqual(self.forge.merges, [])

    def test_a_run_that_drains_releases_without_a_reason(self):
        self.assertEqual(self.train.run('lane-a'), 'drained')
        self.assertEqual(getattr(self.forge, 'deaths', []), [])

    def test_the_command_ends_a_dead_run_with_its_reason(self):
        saved = train.from_config
        self.addCleanup(setattr, train, 'from_config', saved)

        def unreadable():
            raise RuntimeError('no events token: set $TOWER_EVENTS_TOKEN')
        self.train.queue = unreadable
        train.from_config = lambda: self.train
        with unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as err, \
                unittest.mock.patch('sys.stdout', new_callable=io.StringIO):
            self.assertEqual(train.main(['run', '--owner', 'lane-a']), 1)
        last = err.getvalue().strip().splitlines()[-1]
        self.assertEqual(last, f'{train.DIED} RuntimeError: no events token: set $TOWER_EVENTS_TOKEN')
        self.assertIn('Traceback', err.getvalue(), 'the traceback stays for whoever reads the whole output')

    def test_an_empty_queue_still_announces_and_releases(self):
        self.assertEqual(self.train.run('lane-a'), 'drained')
        self.assertEqual(len(self.events(None, 'train.queue.empty')), 1)
        self.assertEqual(self.forge.locks, {})

    def test_the_registry_ships_it_on_because_only_the_train_role_session_runs_it(self):
        self.assertIs(config.entry('train.enabled', ROOT)['default'], True, 'GX-06: on, with emit_only')
        self.assertEqual(config.entry('train.trigger_mode', ROOT)['default'], 'emit_only')
        self.assertIs(engine_role.setting('train.enabled'), True, 'the empty store keeps the registry value')

    def test_the_registry_ships_batch_admission_with_the_requeue_fallback_and_shard_shadow(self):
        """D-075 as amended: verdict admission is opt-in through the shared store; batch is the one-key rollback."""
        self.assertEqual(config.entry('train.admit_mode', ROOT)['default'], 'batch')
        self.assertEqual(config.entry('train.admit_mode', ROOT)['enum'], ['batch', 'verdict'])
        self.assertEqual(config.entry('train.verdict_fallback', ROOT)['default'], 'requeue')
        self.assertEqual(config.entry('train.verdict_fallback', ROOT)['enum'], ['tier2', 'requeue'])
        self.assertEqual(config.entry('train.shard_admit', ROOT)['default'], 'shadow', 'P-54: measured before on')
        self.assertEqual(config.entry('train.shard_admit', ROOT)['enum'], ['off', 'shadow', 'on'])

    def test_the_command_does_nothing_while_the_flag_is_off(self):
        saved = train.from_config
        self.addCleanup(setattr, train, 'from_config', saved)
        train.from_config = lambda: self.fail('a disabled train must not build its role')
        shared = engine_role.setting
        with unittest.mock.patch.object(engine_role, 'setting',
                                        lambda name: False if name == 'train.enabled' else shared(name)), \
                unittest.mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(train.main(['run']), 0)
        self.assertIn('train: off', out.getvalue())

    def test_a_machine_local_override_of_the_flag_is_refused(self):
        saved = train.from_config
        self.addCleanup(setattr, train, 'from_config', saved)
        train.from_config = lambda: self.fail('a refused train must not build its role')
        import tempfile
        with tempfile.TemporaryDirectory() as directory, \
                config.use_adapter(forge_events.FileAdapter(Path(directory)), self.clock), \
                unittest.mock.patch('sys.stderr', new_callable=io.StringIO) as err:
            config.set_value('train.enabled', False, actor='box', reason='local', now=self.clock.now(), root=ROOT)
            self.assertEqual(train.main(['run']), 1)
        self.assertIn('train: refused: train.enabled is overridden by a machine-local change log', err.getvalue())

    def test_a_local_store_without_an_override_reads_the_shared_value(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory, \
                config.use_adapter(forge_events.FileAdapter(Path(directory)), self.clock):
            self.assertIsNone(train.local_override(), 'a local store that does not set it')
        with unittest.mock.patch.dict(os.environ, {'OU_CONFIG_STORE': 'file'}):
            self.assertIsNone(train.local_override(), 'the shared (here in-memory) store chosen in process')

    def test_the_lease_ends_at_the_runs_deadline_never_later(self):
        """D-291: the lock expires at the job's deadline (the runner's, or start + service.job_budget_s), so a holder
        that dies blocks the next job at most until then; the old 35-minute lease keys are gone."""
        taken = []
        real_lock = self.forge.lock

        def record(repo, name, owner, now, expires):
            taken.append((now, expires))
            return real_lock(repo, name, owner, now, expires)

        self.forge.lock = record
        self.train.run('lane-a')
        [(now, expires)] = taken
        lease = (datetime.fromisoformat(expires.replace('Z', '+00:00'))
                 - datetime.fromisoformat(now.replace('Z', '+00:00'))).total_seconds()
        self.assertGreater(lease, 0)
        self.assertLessEqual(lease, config.get('service.job_budget_s'))

    def test_a_runner_job_takes_the_lock_under_the_owner_the_runner_named(self):
        with unittest.mock.patch.dict(os.environ, {engine_role.service_budget.OWNER_ENV: 'vm1/train:7#abc'}):
            self.assertEqual(train.default_owner(), f'{engine_role.setting("train.producer")}@vm1/train:7#abc')

    def test_the_lock_owner_is_the_session_id(self):
        names = engine_role.setting('train.session_id_env')
        with unittest.mock.patch.dict(os.environ, {name: '' for name in names}):
            os.environ[names[-1]] = 'session_abc'
            self.assertEqual(train.default_owner(), engine_role.setting('train.producer') + '@session_abc')
            os.environ[names[-1]] = ''
            self.assertIn(f':{os.getpid()}', train.default_owner(), 'no session id: host and pid')

    def test_the_flag_is_a_registry_flag(self):
        item = config.entry('train.enabled', ROOT)
        self.assertEqual((item['type'], item.get('x-flag')), ('boolean', True))


class Ownership(Fixture):
    """U0's manifests at the integration tip decide; without them the check is a no-op."""

    def setUp(self):
        super().setUp()
        self.asked = []
        self.approvers = []
        self.forge.approvals = lambda repo, number: self.asked.append(number) or list(self.approvers)
        self.train.ownership = train_ownership.UnitOwnership(self.workspace)

    def seed_manifest(self, text='{"id": "progress", "owner": "alice", "lane": "lane-a", "paths": ["src/progress/**"]}\n'):
        (self.seed / 'units' / 'progress').mkdir(parents=True)
        (self.seed / 'units' / 'progress' / 'unit.json').write_text(text)
        (self.seed / 'src' / 'progress').mkdir(parents=True)
        (self.seed / 'src' / 'progress' / 'a.ts').write_text('a\n')
        self.base = self.commit('unit manifests (U0)')
        self.run_git(self.seed, 'push', '--quiet', str(self.origin), f'HEAD:refs/heads/{self.base_branch}')

    def ready_in_lane(self, number, files, lane):
        head = self.pr(number, files, ready=False)
        evidence = self.events(number, 'gate.passed')[-1]['event_id']
        self.lane_port.emit('pr.ready', dict(forge_events.subject(REPO, number, head, ['P-02']), lane_id=lane,
                                             evidence=evidence))

    def test_no_manifest_is_a_no_op_and_asks_nobody(self):
        self.pr(1, {'src/progress/a.ts': 'b\n'})
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1])
        self.assertEqual((self.asked, self.events(1, 'pr.refused')), ([], []))

    def test_another_lanes_unit_without_the_owner_is_refused(self):
        self.seed_manifest()
        self.pr(1, {'src/progress/a.ts': 'b\n', 'README': 'mine\n'})
        self.pr(2, {'other.txt': 'x\n'})
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [2])
        [refused] = self.events(1, 'pr.refused')
        self.assertEqual((refused['payload']['units'], refused['payload']['files']), (['progress'],
                                                                                     ['src/progress/a.ts']))
        self.assertEqual(self.asked, [1])
        self.assertEqual(self.train.queue(), [])

    def test_d112_a_change_that_retires_another_lanes_unit_is_not_refused(self):
        self.seed_manifest()
        self.pr(1, {'units/progress/unit.json': None, 'src/progress/a.ts': None})
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1])
        self.assertEqual((self.asked, self.events(1, 'pr.refused')), ([], []))

    def test_d112_deleting_a_units_files_but_not_its_manifest_is_still_refused(self):
        self.seed_manifest()
        self.pr(1, {'src/progress/a.ts': None})
        self.assertEqual(self.train.run_batch(self.train.queue()), [])
        [refused] = self.events(1, 'pr.refused')
        self.assertEqual(refused['payload']['units'], ['progress'])

    def test_the_owners_approval_lets_it_through(self):
        self.seed_manifest()
        self.approvers = ['alice']
        self.pr(1, {'src/progress/a.ts': 'b\n'})
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1])

    def test_the_owning_lane_needs_no_approval(self):
        self.seed_manifest()
        self.ready_in_lane(1, {'src/progress/a.ts': 'b\n'}, 'lane-a')
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1])
        self.assertEqual(self.asked, [])

    def test_d067_a_manifest_without_lane_names_its_lane_as_owner(self):
        self.seed_manifest('{"id": "progress", "owner": "lane-a", "paths": ["src/progress/**"]}\n')
        self.ready_in_lane(1, {'src/progress/a.ts': 'b\n'}, 'lane-a')
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1])
        self.assertEqual(self.asked, [])

    SHARED = ('{"id": "progress", "owner": "alice", "lane": "lane-a", "paths": ["src/progress/**", "src/census/**"], '
              '"shared": ["src/census/**"]}\n')

    def test_a_shared_path_alone_merges_and_asks_nobody(self):
        """SHARED-NEEDS-NO-OWNER (a): a change of only lane-a's shared path merges and asks nobody. It is announced
        with no lane, as pr_ready announces a change of only shared paths: the shape of #632 and #663 at 17:26."""
        self.seed_manifest(self.SHARED)
        [census] = self.make({'src/census/ui.json': '{"a": 1}\n'})
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [census.number])
        self.assertEqual((self.asked, self.events(census.number, 'pr.refused')), ([], []))

    def test_a_shared_path_beside_a_foreign_one_is_refused_for_the_foreign_file_only(self):
        """SHARED-NEEDS-NO-OWNER (b): a foreign non-shared path still needs its owner; the refusal names only it."""
        self.seed_manifest(self.SHARED)
        mixed, clean = self.make({'src/census/ui.json': '{"a": 1}\n', 'src/progress/a.ts': 'b\n'}, {'other.txt': 'x\n'})
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [clean.number])
        [refused] = self.events(mixed.number, 'pr.refused')
        self.assertEqual((refused['payload']['units'], refused['payload']['files']), (['progress'],
                                                                                     ['src/progress/a.ts']))
        self.assertEqual(self.asked, [mixed.number])




class RoleOverGitLock(Fixture):
    """The train's Origin lease uses the fixture's real bare git remote; no API call can maintain the lock."""

    def setUp(self):
        super().setUp()
        self.lock_ref = engine_role.setting('train.lock_ref')
        self.client = unittest.mock.Mock()
        refs = forge_git_ref.GitRefs(self.work)
        self.enterContext(unittest.mock.patch.object(refs, 'url', return_value=f'https://{config.get("origin-client.git_hosts")[0]}/{REPO}.git'))
        self.adapter = forge_origin.OriginAdapter(self.client, REPO, log=forge_events.MemoryAdapter(), refs=refs)
        self.forge.lock, self.forge.unlock = self.adapter.lock, self.adapter.unlock

    def held(self):
        return self.adapter.refs.read(self.lock_ref)

    def test_a_train_run_takes_and_releases_the_lock_over_git_with_no_renewal(self):
        for number in (1, 2):
            self.pr(number, {f'f{number}.txt': 'x\n'})
        self.assertEqual(self.train.run('train@lane-a'), 'drained')
        self.assertEqual(self.forge.merges, [1, 2])
        sha, record = self.held()
        self.assertEqual(record, {'owner': 'train@lane-a', 'expires': ''})
        pushes = self.run_git(self.origin, 'rev-list', '--count', sha)
        self.assertEqual(int(pushes), 2, 'one take until the deadline and one release, no renewal (D-291)')
        self.assertEqual(self.client.mock_calls, [], 'no API call for the lock')

    def test_a_run_that_dies_leaves_its_reason_on_the_lock_ref_over_git(self):
        self.pr(1, {'f1.txt': 'x\n'})

        def unreadable():
            raise RuntimeError('no events token: set $TOWER_EVENTS_TOKEN')
        self.train.queue = unreadable
        with self.assertRaises(RuntimeError):
            self.train.run('train@lane-a')
        self.assertEqual(self.held()[1], {'owner': 'train@lane-a', 'expires': '',
                                          'died': 'RuntimeError: no events token: set $TOWER_EVENTS_TOKEN'})
        self.assertEqual(self.client.mock_calls, [], 'the reason goes over git, the channel that still works')

    def test_a_held_lock_leaves_the_work_to_its_holder(self):
        self.pr(1, {'f1.txt': 'x\n'})
        self.adapter.refs.advance(self.lock_ref, {'owner': 'train@lane-b', 'expires': '2999-01-01T00:00:00.000Z'}, None)
        self.assertEqual(self.train.run('train@lane-a'), 'busy')
        self.assertEqual(self.forge.merges, [])
        self.assertEqual(self.held()[1]['owner'], 'train@lane-b', 'a lock not owned is never released')

    def test_an_expired_lease_is_taken_over(self):
        self.pr(1, {'f1.txt': 'x\n'})
        self.adapter.refs.advance(self.lock_ref, {'owner': 'train@lane-b', 'expires': '2000-01-01T00:00:00.000Z'}, None)
        self.assertEqual(self.train.run('train@lane-a'), 'drained')
        self.assertEqual(self.forge.merges, [1])
        self.assertEqual(self.held()[1]['owner'], 'train@lane-a')


class RestBudget(unittest.TestCase):
    """GATE-ON-PUSH R4: a run that held the lock publishes its REST calls as budget.measured against
    train.rest_calls_per_run_max; the line prints the count and the 304s."""

    def setUp(self):
        # Counting-only doubles test budget reporting, not forge substitutability.
        self.enterContext(unittest.mock.patch.object(forge_events, '_require_compatibility'))

    def test_the_run_publishes_its_rest_calls_against_the_budget(self):
        sent = engine_role.setting(train.REST_BUDGET)

        class Counting(forge_events.MemoryAdapter):
            def calls(self):
                return {'sent': sent, 'not_modified': 1}

            def merge(self, *_):
                raise AssertionError('the accounting test must never merge')
        adapter = forge_doubles.with_surface(Counting(), 'scripts/lib/train.py')

        class Role:
            repo = REPO

            def port(self, correlation_id):
                return forge_events.ForgeEvents(adapter, FakeClock(), 'train', correlation_id)
        counts = train.forge_calls(Role())
        train.measure_rest(Role(), counts)
        events = adapter.read(forge_events.Channel(REPO, None))
        self.assertEqual([(e['type'], e['payload']['metric'], e['payload']['value']) for e in events],
                         [('budget.measured', train.REST_BUDGET, sent)])
        self.assertEqual(train.rest_line(counts), f'train: {sent} REST call(s), 1 not modified (budget {sent})')

    def test_an_adapter_that_counts_nothing_publishes_nothing(self):
        adapter = forge_events.MemoryAdapter()

        class Role:
            repo = REPO

            def port(self, correlation_id):
                return forge_events.ForgeEvents(adapter, FakeClock(), 'train', correlation_id)
        counts = train.forge_calls(Role())
        train.measure_rest(Role(), counts)
        self.assertIsNone(counts)
        self.assertEqual(adapter.read(forge_events.Channel(REPO, None)), [])
        self.assertIn('not counted', train.rest_line(counts))

    def test_the_origin_adapter_reports_the_clients_counts(self):
        client = forge_origin_client.OriginClient(run=lambda *args: {})
        client.stats.update(sent=1, not_modified=0)
        adapter = object.__new__(forge_origin.OriginAdapter)
        adapter.client = client
        self.assertEqual(adapter.calls(), {'sent': 1, 'not_modified': 0})


PR = 1  # the PR a trigger test announces


def trigger_mode(mode):
    """train.trigger_mode as `mode` for train_trigger, every other setting as registered."""
    return unittest.mock.patch.object(train_trigger, 'shared_setting',
                                      lambda name: mode if name == 'train.trigger_mode' else engine_role.setting(name))


class SharedStore(forge_events.MemoryAdapter):
    """The registry's shared store, as forge_events.ADAPTERS builds it, holding train.trigger_mode changes."""

    def __init__(self, modes, clock):
        super().__init__()
        with config.use_adapter(self, clock):
            for mode in modes:
                config.set_value('train.trigger_mode', mode, actor='test', reason='shared switch', now=clock.now(),
                                 root=ROOT)


class Trigger(unittest.TestCase):
    """Transport v0: the producer of pr.ready starts nothing by default (emit_only, GX-06); with detached (the
    rollback) it starts `scripts/train run` detached and never waits for it."""

    def test_emit_only_is_the_default_and_starts_no_process(self):
        import tempfile
        self.assertEqual(config.entry('train.trigger_mode', ROOT)['default'], 'emit_only')
        calls = []
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(train_trigger.NotStarted, 'train-role session'):
                train_trigger.start(root, 'pr-7', popen=lambda argv, **options: calls.append(argv))
            self.assertFalse((Path(root) / engine_role.setting('train.trigger_log_dir')).exists())
        self.assertEqual(calls, [])

    def test_starts_the_run_detached_without_the_pinned_local_store(self):
        import tempfile
        calls = []
        with tempfile.TemporaryDirectory() as root, unittest.mock.patch.dict(os.environ, {'OU_CONFIG_STORE': 'file'}), \
                trigger_mode(train_trigger.DETACHED):
            log = train_trigger.start(root, 'pr-7', popen=lambda argv, **options: calls.append((argv, options)))
            self.assertTrue(log.is_file())
            self.assertEqual(log.parent, Path(root) / engine_role.setting('train.trigger_log_dir'))
        argv, options = calls[0]
        self.assertEqual(argv, train_trigger.command(root))
        self.assertTrue(options['start_new_session'])
        self.assertNotIn('OU_CONFIG_STORE', options['env'])

    def shared_store(self, *modes):
        """No adapter chosen in process; the shared store (the registry's adapter) holds `modes`, the latest wins; the
        gate pins `file`. The registry's store is the file store (the only one since D-300), built here on the double,
        so the test proves the switch is read from the registry's store."""
        adapter = SharedStore(modes, FakeClock())
        self.enterContext(unittest.mock.patch.object(forge_events, 'FileAdapter', lambda _path: adapter))
        self.enterContext(unittest.mock.patch.object(config, '_chosen', []))
        self.enterContext(unittest.mock.patch.dict(os.environ, {'OU_CONFIG_STORE': 'file'}))
        self.addCleanup(config.invalidate)
        config.invalidate()

    def test_gate_on_push_r1_the_pinned_gate_reads_the_switch_from_the_shared_store(self):
        import tempfile
        self.shared_store(train_trigger.DETACHED)
        calls = []
        with tempfile.TemporaryDirectory() as root:
            train_trigger.start(root, 'pr-7', popen=lambda argv, **options: calls.append(argv))
        self.assertEqual(calls, [train_trigger.command(root)])

    def test_gate_on_push_r1_the_shared_emit_only_starts_nothing_under_the_pin(self):
        import tempfile
        self.shared_store(train_trigger.DETACHED, 'emit_only')
        calls = []
        with tempfile.TemporaryDirectory() as root, self.assertRaises(train_trigger.NotStarted):
            train_trigger.start(root, 'pr-7', popen=lambda argv, **options: calls.append(argv))
        self.assertEqual(calls, [])

    def wake_remote(self):
        """A bare remote and the producer's clone (no network): the GitRefs the wake writes through."""
        import subprocess
        import tempfile
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        base = Path(directory.name)
        for args in (['init', '-q', '--bare', 'remote.git'], ['init', '-q', 'clone'],
                     ['-C', 'clone', 'remote', 'add', 'origin', str(base / 'remote.git')]):
            subprocess.run(['git', *args], cwd=base, check=True, capture_output=True)
        return base, forge_git_ref.GitRefs(base / 'clone', 'origin')

    def ready(self, pr):
        return {'event_id': f'event-{pr}', 'type': 'pr.ready', 'payload': {'pr': pr, 'sha': f'{pr:040d}'}}

    def test_gate_on_push_r2_wake_appends_the_record_and_starts_no_process(self):
        base, refs = self.wake_remote()
        first, second = PR, PR + 1
        calls = []
        with trigger_mode(train_trigger.WAKE):
            lines = [train_trigger.trigger(base, self.ready(pr), f'pr-{pr}', popen=lambda *a, **o: calls.append(a),
                                           refs=refs) for pr in (first, second)]
        name = engine_role.setting('train.wake_ref')
        sha, record = refs.read(name)
        self.assertEqual(record, {'pr': second, 'sha': self.ready(second)['payload']['sha'], 'event_id': f'event-{second}'})
        self.assertIn(f'woken over {name} at {sha}', lines[-1])
        self.assertIn(f'#{first}', lines[0])
        self.assertEqual(calls, [], 'a wake starts no process in the producer')
        self.assertFalse((base / engine_role.setting('train.trigger_log_dir')).exists())

    def test_gate_on_push_r2_a_lost_wake_names_the_periodic_run(self):
        class Lost:
            def append(self, name, record, attempts):
                return None
        with trigger_mode(train_trigger.WAKE):
            line = train_trigger.trigger(ROOT, self.ready(PR), refs=Lost())
        self.assertIn('wake lost', line)
        self.assertIn(f'periodic run catches #{PR}', line)

    def test_gate_on_push_r2_wake_is_an_additive_value_of_the_switch(self):
        entry = config.entry('train.trigger_mode', ROOT)
        self.assertEqual(entry['default'], 'emit_only')
        self.assertEqual(entry['enum'], ['emit_only', train_trigger.DETACHED, train_trigger.WAKE])

    def test_detached_through_trigger_still_starts_the_run(self):
        import tempfile
        calls = []
        with tempfile.TemporaryDirectory() as root, trigger_mode(train_trigger.DETACHED):
            line = train_trigger.trigger(root, self.ready(PR), f'pr-{PR}',
                                         popen=lambda argv, **options: calls.append(argv))
        self.assertTrue(line.startswith('started in the background, output in '))
        self.assertEqual(calls, [train_trigger.command(root)])

    def test_the_entry_point_runs(self):
        import subprocess  # `run` itself would reach the forge now that the flag ships on; the role is tested in process
        result = subprocess.run([str(train_trigger.ROOT / 'scripts' / 'train'), '--help'], capture_output=True, text=True,
                                env=dict(os.environ, OU_CONFIG_STORE='file'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('run', result.stdout)



class RunnerEnvironment(unittest.TestCase):
    """The infrastructure runner's check environment (TOWER_JOB_OWNER, TOWER_JOB_DEADLINE) must not turn the role's tests
    red: shadow PR #310 was red on train-role.test.sh there and green on the box."""

    def test_the_role_tests_pass_with_the_runners_job_variables_set(self):
        import subprocess
        env = dict(os.environ, **{engine_role.service_budget.OWNER_ENV: 'runner-1/job-7',
                                  engine_role.service_budget.DEADLINE_ENV: '4102444800'})
        result = subprocess.run([sys.executable, str(Path(__file__)), 'Role'], capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])


if __name__ == '__main__':
    unittest.main()
