"""The configuration API (D-068 (3), D-069 items 3 and 4): set, audit, history, revert, diff and replay.

Fixture repositories in a temporary directory; the clock is injected; no network.
"""
import contextlib
import datetime
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import config_cli  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402
import json_schema  # noqa: E402

T0 = datetime.datetime(2026, 10, 26, 20, 51, tzinfo=datetime.timezone.utc)
COPIED = ('contracts/config/registry.v1.json', 'contracts/events/config.changed.v1.json', 'config/registry/config.json')
TRAIN = {'$schema': json_schema.DIALECT, '$id': 'config/registry/train.json', 'x-owner': 'train', 'x-schema-version': 1,
         'type': 'object', 'additionalProperties': False, 'properties': {
             'train.batch_size': {'type': 'integer', 'default': 8, 'minimum': 1, 'maximum': 64, 'x-unit': 'count',
                                  'description': 'PRs per batch.', 'x-readers': []},
             'train.endpoint': {'type': 'string', 'default': 'local', 'x-unit': 'name', 'description': 'Where.',
                                'x-readers': []}}}


def pin_file_store(root):
    """The fixture's change store is its own local log, chosen here explicitly: a test never reads the forge."""
    path = Path(root) / 'config/registry/config.json'
    document = json.loads(path.read_text())
    document['properties']['config.store_adapter']['default'] = 'file'
    path.write_text(json.dumps(document))


def at(minutes):
    return T0 + datetime.timedelta(minutes=minutes)


def own_snapshot_file(test):
    """A fake forge that names itself (cache_identity) shares one snapshot file per checkout. The store's own reads
    without a root (forge_events' config.get inside config.store) took the real checkout's .tower/config-cache file,
    written by an earlier run under the same fake clock: they take the fixture's (VAZAO F53, a leak the covers trace
    reported)."""
    real = config._cache_file
    test.enterContext(mock.patch.object(config, '_cache_file',
                                        lambda root, key: real(test.root if root is None else root, key)))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in COPIED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        pin_file_store(self.root)
        self.write_train(TRAIN)

    def tearDown(self):
        self.tmp.cleanup()

    def write_train(self, document):
        (self.root / 'config/registry/train.json').write_text(json.dumps(document))



class Api(Fixture):
    def set(self, value, minutes=0, name='train.batch_size', **extra):
        return config.set_value(name, value, actor='motor-5', reason='measured', now=at(minutes), root=self.root, **extra)

    def test_set_overrides_the_registry_and_records_who_when_and_why(self):
        event = self.set(12, correlation_id='pr-496')
        self.assertEqual(config.get('train.batch_size', self.root), 12)
        self.assertEqual(event['payload'], {'repo': config.get('forge-events.repo'), 'pr': None, 'sha': None,
                                            'unit': None, 'premises': [], 'name': 'train.batch_size', 'old': None,
                                            'new': 12, 'actor': 'motor-5', 'reason': 'measured',
                                            'at': '2026-10-26T20:51:00.000Z'})
        self.assertEqual(event['type'], 'config.changed')
        self.assertEqual(event['version'], 1)
        self.assertEqual(event['producer'], 'config')
        self.assertEqual(event['occurred_at'], '2026-10-26T20:51:00.000Z')
        self.assertEqual(event['correlation_id'], 'pr-496')
        self.assertEqual(event['event_id'], event_contracts.event_id('config', 'config.changed',
                                                                     event_contracts.natural_key(event)))
        self.assertEqual(event_contracts.validate(event), event)

    def test_the_clock_is_injected_and_converted_to_utc(self):
        local = datetime.datetime(2026, 10, 26, 17, 51, tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
        event = config.set_value('train.batch_size', 9, actor='a', reason='r', now=local, root=self.root)
        self.assertEqual(event['payload']['at'], '2026-10-26T20:51:00.000Z')
        with self.assertRaises(config.ConfigError):
            config.set_value('train.batch_size', 10, actor='a', reason='r', now=datetime.datetime(2026, 1, 1),
                             root=self.root)

    def test_invalid_unknown_secret_and_unchanged_values_are_refused_and_not_recorded(self):
        for name, value, message in (('train.batch_size', 0, 'below the minimum'),
                                     ('train.batch_size', 'eight', 'expected integer'),
                                     ('train.missing', 1, 'not a registered parameter'),
                                     ('train.endpoint', 'ghp_' + 'a1B2' * 9, 'shape of a secret'),
                                     ('train.batch_size', 8, 'is already 8')):
            with self.subTest(value=value), self.assertRaises(config.ConfigError) as raised:
                self.set(value, name=name)
            self.assertIn(message, str(raised.exception))
        self.assertEqual(config.history(root=self.root), [])

    def test_actor_and_reason_are_required(self):
        with self.assertRaises(config.ConfigError):
            config.set_value('train.batch_size', 9, actor='', reason='r', now=T0, root=self.root)
        with self.assertRaises(config.ConfigError):
            config.set_value('train.batch_size', 9, actor='a', reason='', now=T0, root=self.root)

    def test_the_store_location_is_not_changed_through_the_store(self):
        with self.assertRaises(config.ConfigError) as raised:
            self.set('elsewhere', name='config.store_dir')
        self.assertIn('locates the change store itself', str(raised.exception))

    def test_revert_is_a_new_change_and_restores_the_value(self):
        first = self.set(12)
        second = self.set(16, minutes=1)
        undo = config.revert(second['event_id'][:10], actor='daniel', reason='too big', now=at(2), root=self.root)
        self.assertEqual(config.get('train.batch_size', self.root), 12)
        self.assertEqual(undo['payload']['reverts'], second['event_id'])
        self.assertEqual((undo['payload']['old'], undo['payload']['new']), (16, 12))
        config.revert(first['event_id'], actor='daniel', reason='back', now=at(3), root=self.root)
        self.assertEqual(config.get('train.batch_size', self.root), 8)
        self.assertNotIn('train.batch_size', config.overrides(self.root))
        self.assertEqual([event['payload']['new'] for event in config.history('train.batch_size', self.root)],
                         [12, 16, 12, None])

    def test_revert_refuses_to_overwrite_a_later_change(self):
        first = self.set(12)
        self.set(16, minutes=1)
        with self.assertRaises(config.ConfigError) as raised:
            config.revert(first['event_id'], actor='a', reason='r', now=at(2), root=self.root)
        self.assertIn('revert that first', str(raised.exception))
        with self.assertRaises(config.ConfigError):
            config.revert('', actor='a', reason='r', now=at(2), root=self.root)

    def test_unset_returns_to_the_registry_default(self):
        self.set(12)
        event = config.unset('train.batch_size', actor='a', reason='r', now=at(1), root=self.root)
        self.assertIsNone(event['payload']['new'])
        self.assertEqual(config.get('train.batch_size', self.root), 8)
        with self.assertRaises(config.ConfigError):
            config.unset('train.batch_size', actor='a', reason='r', now=at(2), root=self.root)

    def test_the_log_is_append_only_idempotent_and_replays_to_the_same_state(self):
        event = self.set(12)
        self.set(20, minutes=1)
        store = config.store(self.root)
        store.port.publish([event])
        self.assertEqual(len(store.events()), 2)
        log = forge_events.FileAdapter(self.root / config.entry('config.store_dir', self.root)['default'])
        replayed = config.replay(log.read(forge_events.Channel(config.get('forge-events.repo'), None)))
        self.assertEqual(replayed, {'train.batch_size': 20})

    def test_a_stored_value_the_schema_no_longer_accepts_is_an_error(self):
        self.set(40)
        tighter = json.loads(json.dumps(TRAIN))
        tighter['properties']['train.batch_size']['maximum'] = 32
        self.write_train(tighter)
        with self.assertRaises(config.ConfigError) as raised:
            config.get('train.batch_size', self.root)
        self.assertIn('no longer satisfies its schema', str(raised.exception))

    def test_every_recorded_payload_satisfies_the_event_contract(self):
        self.set(12)
        for event in config.history(root=self.root):
            self.assertEqual(event_contracts.validate(event), event)

    def test_diff_lists_overrides_with_their_change(self):
        event = self.set(12)
        rows = config.diff(self.root)
        self.assertEqual(rows[0]['name'], 'train.batch_size')
        self.assertEqual((rows[0]['default'], rows[0]['value'], rows[0]['change']), (8, 12, event['event_id']))

    def test_diff_against_a_ref_lists_registry_defaults_changed_by_commits(self):
        git = ['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        source = self.root / 'config' / 'registry' / 'train' / 'train.batch_size.json'  # a split owner's source (D-095)
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(json.dumps(TRAIN['properties']['train.batch_size']))
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-qm', 'base'], check=True)
        changed = json.loads(json.dumps(TRAIN))
        changed['properties']['train.batch_size']['default'] = 10
        del changed['properties']['train.endpoint']
        self.write_train(changed)
        rows = {row['name']: row for row in config.diff_ref('HEAD', self.root)}
        self.assertEqual((rows['train.batch_size']['kind'], rows['train.batch_size']['new']), ('changed', 10))
        self.assertEqual(rows['train.endpoint']['kind'], 'removed')


class CommandLine(Fixture):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = config_cli.main(list(argv), clock=lambda: T0, root=self.root)
        return code, out.getvalue(), err.getvalue()

    def test_set_get_describe_history_and_revert(self):
        code, out, _ = self.run_cli('set', 'train.batch_size', '12', '--actor', 'motor-5', '--reason', 'measured')
        self.assertEqual(code, 0)
        change = out.split()[0]
        self.assertEqual(self.run_cli('get', 'train.batch_size')[1].strip(), '12')
        self.assertIn('* train.batch_size = 12 count', self.run_cli('list', '--owner', 'train')[1])
        self.assertIn('overridden: true', self.run_cli('describe', 'train.batch_size')[1])
        self.assertIn('"measured"', self.run_cli('history')[1])
        self.assertIn('8 -> 12', self.run_cli('diff')[1])
        code, out, _ = self.run_cli('revert', change, '--actor', 'daniel', '--reason', 'undo')
        self.assertEqual(code, 0)
        self.assertIn(f'(reverts {change})', out)
        self.assertEqual(self.run_cli('diff')[1].strip(), 'no differences')
        self.assertEqual(len(config.history(root=self.root)), 2)

    def test_a_refused_change_exits_1_with_the_reason(self):
        code, _, err = self.run_cli('set', 'train.batch_size', '0', '--actor', 'a', '--reason', 'r')
        self.assertEqual(code, 1)
        self.assertIn('below the minimum', err)

    def test_set_to_default_and_json_output(self):
        self.run_cli('set', 'train.endpoint', 'remote', '--actor', 'a', '--reason', 'r')
        code, out, _ = self.run_cli('--json', 'set', 'train.endpoint', '--default', '--actor', 'a', '--reason', 'r')
        self.assertEqual(code, 0)
        self.assertIsNone(json.loads(out)['payload']['new'])
        self.assertEqual(json.loads(self.run_cli('--json', 'get', 'train.endpoint')[1]), 'local')


class StoreSelection(Fixture):
    """The store's adapter is chosen explicitly: in process (use_adapter) or for a process tree (OU_CONFIG_STORE)."""

    def setUp(self):
        super().setUp()
        pinned = list(config._pinned)  # this class tests the selection itself: hermetic.install()'s pin is lifted
        config._pinned.clear()
        self.addCleanup(lambda: config._pinned.extend(pinned))

    def test_a_pinned_process_ignores_its_environment(self):
        self.environment('elsewhere')
        config.pin_store('file')
        self.addCleanup(config._pinned.clear)
        self.assertEqual(config.store_kind(self.root), 'file')
        with self.assertRaises(config.ConfigError):
            config.pin_store('elsewhere')

    def environment(self, value):
        saved = os.environ.get('OU_CONFIG_STORE')
        os.environ['OU_CONFIG_STORE'] = value
        self.addCleanup(lambda: os.environ.pop('OU_CONFIG_STORE') if saved is None
                        else os.environ.__setitem__('OU_CONFIG_STORE', saved))

    def test_the_registry_names_the_adapter_when_nothing_is_chosen(self):
        self.environment('')
        self.assertEqual(config.store_kind(self.root), 'file')

    def test_the_file_store_is_the_only_store_adapter(self):
        """D-300 (SEMENTE §6): the control store left the enum, so naming it is an unknown adapter, never a fallback."""
        self.assertEqual(config.entry('config.store_adapter', self.root)['enum'], ['file'])
        self.environment('control')
        with self.assertRaises(config.ConfigError):
            config.store_kind(self.root)

    def test_a_process_tree_may_choose_the_local_log(self):
        self.environment('file')
        self.assertEqual(config.store_kind(self.root), 'file')
        config.set_value('train.batch_size', 12, actor='gate', reason='local', now=at(0), root=self.root)
        self.assertTrue((self.root / config.entry('config.store_dir', self.root)['default']).is_dir())
        self.assertEqual(config.get('train.batch_size', self.root), 12)

    def test_an_unknown_adapter_is_an_error_never_a_fallback(self):
        self.environment('elsewhere')
        with self.assertRaises(config.ConfigError) as raised:
            config.get('train.batch_size', self.root)
        self.assertIn('OU_CONFIG_STORE', str(raised.exception))

    def test_a_test_routes_the_store_through_its_own_adapter(self):
        forge = forge_events.MemoryAdapter()
        with config.use_adapter(forge):
            config.set_value('train.batch_size', 16, actor='motor-tr1', reason='fake forge', now=at(0), root=self.root)
            self.assertEqual(config.get('train.batch_size', self.root), 16)
        [(channel, [event])] = forge.logs.items()
        self.assertEqual((channel[1], event['type']), (None, 'config.changed'))
        self.assertFalse((self.root / config.entry('config.store_dir', self.root)['default']).exists())


class RemoteForge(forge_events.MemoryAdapter):
    """A fake forge whose log lives off the machine: the config store caches its reads. Counts every read."""

    remote = True

    def __init__(self):
        super().__init__()
        self.reads = 0

    def read(self, channel):
        self.reads += 1
        return super().read(channel)


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def now(self):
        return self.moment


class StoreCache(Fixture):
    """A remote store is read once per config.store_cache_ttl_s per checkout (TR1, D-069 item 3)."""

    def setUp(self):
        super().setUp()
        self.forge, self.clock = RemoteForge(), Clock(at(0))
        self.forge.cache_identity = 'store-cache-test'  # shares its snapshot file under this fixture's own root
        own_snapshot_file(self)
        self.enterContext(config.use_adapter(self.forge, self.clock))
        self.ttl = config.entry('config.store_cache_ttl_s', self.root)['default']

    def test_reads_within_the_ttl_cost_one_read_of_the_log(self):
        for _ in range(50):
            self.assertEqual(config.get('train.batch_size', self.root), 8)
        self.assertEqual(self.forge.reads, 1)
        self.clock.moment = at(0) + datetime.timedelta(seconds=self.ttl)
        config.get('train.batch_size', self.root)
        self.assertEqual(self.forge.reads, 2)

    def test_another_process_of_the_checkout_reads_the_snapshot_file(self):
        config.get('train.batch_size', self.root)
        config._memo.clear()  # a new process: only the snapshot file under config.store_cache_dir remains
        config.get('train.batch_size', self.root)
        self.assertEqual(self.forge.reads, 1)
        self.assertEqual(len(list((self.root / config.entry('config.store_cache_dir', self.root)['default']).glob('*.json'))), 1)

    def test_an_unreadable_snapshot_is_a_miss(self):
        config.get('train.batch_size', self.root)
        config._memo.clear()
        for path in (self.root / config.entry('config.store_cache_dir', self.root)['default']).glob('*.json'):
            path.write_text('{not json')
        config.get('train.batch_size', self.root)
        self.assertEqual(self.forge.reads, 2)

    def test_a_change_through_this_checkout_is_read_at_once(self):
        self.assertEqual(config.get('train.batch_size', self.root), 8)
        first = config.set_value('train.batch_size', 12, actor='motor-tr1', reason='cache', now=at(1), root=self.root)
        self.assertEqual(config.get('train.batch_size', self.root), 12)
        second = config.set_value('train.batch_size', 16, actor='motor-tr1', reason='cache', now=at(2), root=self.root)
        self.assertEqual((first['payload']['old'], second['payload']['old']), (None, 12))

    def test_a_change_elsewhere_is_seen_once_the_ttl_ends(self):
        self.assertEqual(config.get('train.batch_size', self.root), 8)
        elsewhere = forge_events.ForgeEvents(self.forge, self.clock, 'config', 'other-checkout')
        elsewhere.emit('config.changed', {**forge_events.subject(config.get('forge-events.repo'), None, None),
                                          'name': 'train.batch_size', 'old': None, 'new': 24, 'actor': 'other',
                                          'reason': 'shared', 'at': forge_events.rfc3339(at(0))})
        self.assertEqual(config.get('train.batch_size', self.root), 8, 'served from the read within the TTL')
        self.clock.moment = at(0) + datetime.timedelta(seconds=self.ttl)
        self.assertEqual(config.get('train.batch_size', self.root), 24)

    def test_the_cache_settings_are_store_locations(self):
        for name in ('config.store_cache_ttl_s', 'config.store_cache_dir'):
            with self.assertRaises(config.ConfigError):
                config.set_value(name, 1, actor='a', reason='r', now=at(0), root=self.root)


class SharedStore(Fixture):
    """The shared store (TR1): checkouts that share only the forge see each other's changes; no credential, no read."""

    def setUp(self):
        super().setUp()
        self.forge, self.clock = RemoteForge(), Clock(at(0))
        self.other = tempfile.TemporaryDirectory()
        self.addCleanup(self.other.cleanup)
        for name in COPIED:
            (Path(self.other.name) / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, Path(self.other.name) / name)
        pin_file_store(self.other.name)
        shutil.copy(self.root / 'config/registry/train.json', Path(self.other.name) / 'config/registry/train.json')

    def test_d300_the_registry_default_is_the_file_store_and_the_log_is_the_git_ref_log(self):
        """D-300 (VAZÃO F61): the engine does not depend on Cloudflare for what is its own. The config store is the
        checkout's file log by default (a shared value is its registry file, changed by a PR), and the event log, the
        diary and the gate proof with it, is the git-ref log on Origin for good (D-296 made permanent)."""
        registry = json.loads((ROOT / 'config/registry/config.json').read_text())
        self.assertEqual(registry['properties']['config.store_adapter']['default'], 'file')
        log = json.loads((ROOT / 'config/registry/forge-events/forge-events.log_adapter.json').read_text())
        self.assertEqual(log['default'], 'git-ref')

    def test_a_value_set_in_one_checkout_is_read_by_another_that_shares_only_the_forge(self):
        with config.use_adapter(self.forge, self.clock):
            config.set_value('train.batch_size', 21, actor='motor-tr1', reason='shared', now=at(1), root=self.root)
        with config.use_adapter(self.forge, self.clock):
            self.assertEqual(config.get('train.batch_size', self.other.name), 21)
            [change] = config.history('train.batch_size', self.other.name)
            self.assertEqual(change['payload']['actor'], 'motor-tr1')
            config.revert(change['event_id'][:12], actor='motor-tr1', reason='back', now=at(2), root=self.other.name)
        with config.use_adapter(self.forge, self.clock):
            self.assertEqual(config.get('train.batch_size', self.root), 8)

    def test_the_train_reads_the_flag_from_the_store(self):
        import engine_role
        import train

        # The train reads its checkout's registry (GX-02): that checkout is the fixture, so every write lands in the
        # fixture's log and cache, never in the real checkout's .tower/config-cache (VAZAO F66).
        shutil.copy(ROOT / 'config/registry/train.json', self.root / 'config/registry/train.json')
        self.enterContext(mock.patch.object(engine_role, 'ROOT', self.root))

        class Role:
            def run(self, owner):
                return 'drained'
        with config.use_adapter(self.forge, self.clock), mock.patch.object(train, 'from_config', lambda: Role()):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                train.main(['run'])
            self.assertIn('train: drained', out.getvalue(), 'the registry ships it on (GX-06)')
            config.set_value('train.enabled', False, actor='motor-tr1', reason='pause', now=at(1), root=self.root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                train.main(['run'])
            self.assertIn('train: off', out.getvalue())
            config.revert(config.history('train.enabled', self.root)[-1]['event_id'][:12], actor='motor-tr1',
                          reason='on', now=at(2), root=self.root)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                train.main(['run'])
            self.assertIn('train: drained', out.getvalue())


class WindowedForge(RemoteForge):
    """A fake forge that returns only its newest `window` envelopes of a channel, like the github adapter past its pages."""

    def __init__(self, window):
        super().__init__()
        self.window = window

    deeper = True  # False: an adapter that only offers its default window

    def recent(self, channel, tail=None):
        size = tail if tail and self.deeper else self.window
        events = self.read(channel)
        return events[-size:], len(events) <= size


class BoundedReads(Fixture):
    """The log can outgrow the window a reader reads: a snapshot carries the overrides, never a truncated read."""

    def setUp(self):
        super().setUp()
        # The fixture's own registry takes a short snapshot interval: the behaviour is the same at any N, and the
        # shipped 50 made each test emit ~100 events through the fake forge (F118: 25 of the file's 29 s).
        path = self.root / 'config/registry/config.json'
        document = json.loads(path.read_text())
        document['properties']['config.store_snapshot_after_events']['default'] = 5
        path.write_text(json.dumps(document))
        self.after = config.entry('config.store_snapshot_after_events', self.root)['default']
        self.forge, self.clock = WindowedForge(2 * self.after), Clock(at(0))
        self.enterContext(config.use_adapter(self.forge, self.clock))

    def change(self, value, minute):
        return config.set_value('train.batch_size', value, actor='motor-tr1', reason='window', now=at(minute),
                                root=self.root)

    def types(self):
        return [event['type'] for event in self.forge.read(forge_events.Channel(config.get('forge-events.repo'), None))]

    def test_a_snapshot_follows_the_configured_number_of_changes(self):
        for minute in range(self.after - 1):
            self.change(2 + minute, minute)
        self.assertNotIn('config.snapshot', self.types())
        self.change(60, self.after)
        events = self.forge.read(forge_events.Channel(config.get('forge-events.repo'), None))
        self.assertEqual(events[-1]['type'], 'config.snapshot')
        self.assertEqual((events[-1]['payload']['overrides'], events[-1]['payload']['count']),
                         ({'train.batch_size': 60}, self.after))

    def test_a_log_longer_than_the_window_reads_through_its_snapshot(self):
        self.forge.window = self.after + 1  # holds a snapshot and the changes after it
        for minute in range(self.after + 2):
            self.change(2 + minute, minute)
        self.assertEqual(config.get('train.batch_size', self.root), 2 + self.after + 1)
        self.assertEqual(len(self.forge.read(forge_events.Channel(config.get('forge-events.repo'), None))) > self.forge.window, True)

    def emit_elsewhere(self, count):
        elsewhere = forge_events.ForgeEvents(self.forge, self.clock, 'config', 'other-checkout')
        repo = config.entry('forge-events.repo')['default']  # a registry read: no store read, no heal yet
        for minute in range(count):
            elsewhere.emit('config.changed', {
                **forge_events.subject(repo, None, None), 'name': 'train.batch_size',
                'old': None, 'new': 2 + minute % 50, 'actor': 'other', 'reason': 'window',
                'at': forge_events.rfc3339(at(minute))})
        self.clock.moment = at(0) + datetime.timedelta(seconds=config.entry('config.store_cache_ttl_s', self.root)['default'])

    def test_a_window_without_a_snapshot_reads_deeper_not_an_error(self):
        self.emit_elsewhere(self.forge.window + 2)
        self.assertEqual(config.get('train.batch_size', self.root), 2 + (self.forge.window + 1) % 50)

    def test_a_reader_that_reads_past_the_window_heals_it(self):
        self.emit_elsewhere(self.forge.window + 2)
        channel = forge_events.Channel(config.entry('forge-events.repo')['default'], None)
        self.assertNotIn('config.snapshot', [event['type'] for event in self.forge.recent(channel)[0]])
        self.assertEqual(config.get('train.batch_size', self.root), 2 + (self.forge.window + 1) % 50)  # a plain read
        found, _ = self.forge.recent(channel)
        self.assertEqual(found[-1]['type'], 'config.snapshot')  # the reader appended it; the next read is windowed
        self.assertEqual(found[-1]['payload']['overrides'], {'train.batch_size': 2 + (self.forge.window + 1) % 50})

    def test_no_snapshot_within_the_deepest_window_is_still_an_error(self):
        self.forge.deeper = False
        self.emit_elsewhere(self.forge.window + 2)
        with self.assertRaises(config.StoreError) as raised:
            config.get('train.batch_size', self.root)
        self.assertIn('config.store_window_max', str(raised.exception))

    def test_a_replay_without_the_snapshot_gives_the_same_overrides(self):
        for minute in range(self.after + 1):
            self.change(2 + minute, minute)
        events = self.forge.read(forge_events.Channel(config.get('forge-events.repo'), None))
        self.assertIn('config.snapshot', [event['type'] for event in events])
        plain = [event for event in events if event['type'] == 'config.changed']
        self.assertEqual(config.replay(plain), config.replay(events))

    def test_a_snapshot_is_idempotent_for_the_same_changes(self):
        for minute in range(self.after):
            self.change(2 + minute, minute)
        before = len(self.forge.read(forge_events.Channel(config.get('forge-events.repo'), None)))
        self.assertIsNone(config.snapshot(self.root, self.clock))  # nothing pending after the snapshot
        self.assertEqual(len(self.forge.read(forge_events.Channel(config.get('forge-events.repo'), None))), before)


class OutageForge(RemoteForge):
    """A remote forge that can go down: a read then fails the way a GitHub limit window or an outage does."""

    def __init__(self):
        super().__init__()
        self.down = False

    def read(self, channel):
        if self.down:
            self.reads += 1
            raise RuntimeError('gh: rate-limited (the fake forge is down)')
        return super().read(channel)


class StoreOutage(Fixture):
    """NANO-UNBLOCK (D-070): a store that cannot be read never stops the machine bootstrap, and a runtime read serves the
    last good read for config.store_stale_max_s past its expiry; past that, or with nothing held, the error stands."""

    def setUp(self):
        super().setUp()
        self.forge, self.clock = OutageForge(), Clock(at(0))
        self.forge.cache_identity = 'store-outage-test'  # its snapshot file lives under this fixture's own root
        own_snapshot_file(self)
        self.enterContext(config.use_adapter(self.forge, self.clock))
        self.addCleanup(config._stale_said.clear)
        config._stale_said.clear()
        owner = config.entry('config.bootstrap_owners', self.root)['default'][0]
        self.bootstrap = f'{owner}.fixture_value'
        (self.root / f'config/registry/{owner}.json').write_text(json.dumps({
            '$schema': json_schema.DIALECT, '$id': f'config/registry/{owner}.json', 'x-owner': owner,
            'x-schema-version': 1, 'type': 'object', 'additionalProperties': False, 'properties': {
                self.bootstrap: {'type': 'string', 'default': 'registry', 'x-unit': 'name', 'description': 'A value.',
                                 'x-readers': []}}}))
        self.ttl = config.entry('config.store_cache_ttl_s', self.root)['default']
        self.bound = config.entry('config.store_stale_max_s', self.root)['default']
        self.forge.reads = 0  # the settings above cost one read of the log while it was up

    def later(self, seconds):
        self.clock.moment = at(0) + datetime.timedelta(seconds=seconds)

    def test_a_bootstrap_parameter_never_reads_the_store(self):
        self.forge.down = True
        self.assertEqual(config.get(self.bootstrap, self.root), 'registry')
        self.assertEqual(self.forge.reads, 0)

    def test_a_bootstrap_parameter_is_changed_in_its_registry_only(self):
        with self.assertRaises(config.ConfigError) as raised:
            config.set_value(self.bootstrap, 'store', actor='a', reason='r', now=at(0), root=self.root)
        self.assertIn('config.bootstrap_owners', str(raised.exception))
        for name in ('config.bootstrap_owners', 'config.store_stale_max_s'):
            with self.assertRaises(config.ConfigError):
                config.set_value(name, [] if name.endswith('owners') else 0, actor='a', reason='r', now=at(0),
                                 root=self.root)

    def test_a_failed_read_serves_the_last_good_read_within_the_bound(self):
        held = TRAIN['properties']['train.batch_size']['maximum']
        config.set_value('train.batch_size', held, actor='motor', reason='held', now=at(0), root=self.root)
        config._invalidate(self.root)  # the change's own reads may sit in the memo; this read writes this root's snapshot
        self.assertEqual(config.get('train.batch_size', self.root), held)
        self.forge.down = True
        config._memo.clear()  # a new process of the checkout: only the snapshot file remains
        self.later(self.ttl + self.bound)
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            self.assertEqual(config.get('train.batch_size', self.root), held)
            self.assertEqual(config.get('train.endpoint', self.root), 'local')
        [line] = said.getvalue().splitlines()
        self.assertIn('cannot be read', line)
        self.assertIn('config.store_stale_max_s', line)
        self.later(self.ttl + self.bound + 1)
        with self.assertRaises(config.StoreUnavailable):
            config.get('train.batch_size', self.root)

    def test_with_nothing_held_the_error_stands_and_the_cli_says_it_in_one_line(self):
        config._invalidate(self.root)  # nothing held: no memo, no snapshot file
        self.forge.down = True
        with self.assertRaises(config.StoreError):
            config.get('train.batch_size', self.root)
        del self.forge.cache_identity  # the command reads this checkout's registry: no snapshot file is shared
        with self.assertRaises(SystemExit) as raised, config.use_adapter(self.forge, self.clock):
            config.main(['get', 'train.enabled'])
        self.assertEqual(len(str(raised.exception.code).splitlines()), 1)
        self.assertIn('cannot be read', str(raised.exception.code))


if __name__ == '__main__':
    unittest.main()
