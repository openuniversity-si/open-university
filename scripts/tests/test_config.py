"""The configuration registry (D-068, P-41): reading, validation and secret refusal (generated types: test_generate.py).

Fixture registries in a temporary directory; no network, no clock.
"""
import copy
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
import forge_events  # noqa: E402
import json_schema  # noqa: E402

PYTHON = sys.executable


def parameter(default, **extra):
    kind = {bool: 'boolean', int: 'integer', float: 'number', str: 'string', list: 'array'}[type(default)]
    item = {'type': kind, 'default': default, 'x-unit': 'count', 'description': 'A test value.', 'x-readers': []}
    item.update(extra)
    return item


def registry(owner, **parameters):
    return {'$schema': json_schema.DIALECT, '$id': f'config/registry/{owner}.json', 'x-owner': owner,
            'x-schema-version': 1, 'type': 'object', 'additionalProperties': False, 'properties': parameters}


def pin_file_store(root):
    """The fixture's change store is its own local log, chosen here explicitly: a test never reads the forge."""
    path = Path(root) / 'config/registry/config.json'
    document = json.loads(path.read_text())
    document['properties']['config.store_adapter']['default'] = 'file'
    path.write_text(json.dumps(document))


class Fixture(unittest.TestCase):
    """A repository with the meta-schema and the config owner's guard policy, plus the files a test writes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ('contracts/config/registry.v1.json', 'config/registry/config.json'):
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        pin_file_store(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, document):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document) if not isinstance(document, str) else document)

    def errors(self):
        return '\n'.join(config.check(self.root))


class Reading(Fixture):
    def test_get_returns_the_registry_value(self):
        self.write('config/registry/train.json', registry('train', **{'train.batch_size': parameter(8)}))
        self.assertEqual(config.get('train.batch_size', self.root), 8)

    def test_an_unregistered_name_is_an_error_never_a_fallback(self):
        with self.assertRaises(KeyError) as raised:
            config.get('train.missing', self.root)
        self.assertIn('not a registered parameter', str(raised.exception))

    def test_the_command_line_prints_json_for_shell_and_mjs_readers(self):
        out = subprocess.run([PYTHON, str(ROOT / 'scripts/lib/config.py'), 'get', 'train.batch_size'],
                             capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(out.stdout), config.get('train.batch_size'))
        missing = subprocess.run([PYTHON, str(ROOT / 'scripts/lib/config.py'), 'get', 'train.nope'],
                                 capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('not a registered parameter', missing.stderr)

    def test_several_names_print_one_object_and_one_unknown_name_fails_them_all(self):
        names = ['train.batch_size', 'units.manifest_dir']
        out = subprocess.run([PYTHON, str(ROOT / 'scripts/lib/config.py'), 'get', *names],
                             capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(out.stdout), {name: config.get(name) for name in names})
        missing = subprocess.run([PYTHON, str(ROOT / 'scripts/lib/config.py'), 'get', *names, 'train.nope'],
                                 capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(missing.stdout, '')

    def test_the_repository_registry_is_valid(self):
        self.assertEqual(config.check(), [])


class Validation(Fixture):
    def test_the_file_must_satisfy_the_meta_schema_and_name_its_owner(self):
        bad = registry('lane', **{'train.batch_size': parameter(8)})
        bad['$id'] = 'config/registry/other.json'
        self.write('config/registry/train.json', bad)
        errors = self.errors()
        self.assertIn('$id is', errors)
        self.assertIn("x-owner is 'lane'", errors)

    def test_a_name_without_its_owner_prefix_or_declared_twice_fails(self):
        self.write('config/registry/train.json', registry('train', **{'battery.limit': parameter(1)}))
        self.write('config/registry/battery.json', registry('battery', **{'battery.limit': parameter(1)}))
        errors = self.errors()
        self.assertIn('battery.limit does not start with its owner train.', errors)
        self.assertIn('is also declared in', errors)

    def test_the_default_must_satisfy_its_own_range(self):
        self.write('config/registry/train.json', registry('train', **{'train.batch_size': parameter(0, minimum=1)}))
        self.assertIn('train.batch_size default 0 is below the minimum 1', self.errors())

    def test_every_reader_exists(self):
        self.write('scripts/lib/train.py', 'BATCH = config.get("train.batch_size")\n')
        self.write('scripts/lib/other.py', 'print("nothing")\n')
        self.write('config/registry/train.json', registry('train', **{
            'train.batch_size': parameter(8, **{'x-readers': ['scripts/lib/train.py']}),
            'train.lock_name': parameter('train-lock', **{'x-readers': ['scripts/lib/other.py', 'scripts/lib/gone.py']})}))
        self.assertIn('names a reader that does not exist: scripts/lib/gone.py', self.errors())


class Secrets(Fixture):
    def findings(self, name, value):
        self.write('config/registry/forge.json', registry('forge', **{name: parameter(value)}))
        return '\n'.join(config.secret_findings(name, value, self.root))

    def test_one_read_of_the_guard_judges_like_seven(self):
        """GATE-SPEED F3: config.check reads secret_guard once for every parameter; the findings are the same."""
        self.write('config/registry/forge.json', registry('forge', **{'forge.api_token': parameter('abc')}))
        guard = config.secret_guard(self.root)
        self.assertEqual(config.secret_findings('forge.api_token', 'abc', self.root, guard),
                         config.secret_findings('forge.api_token', 'abc', self.root))

    def test_a_key_that_names_a_secret_is_refused(self):
        self.assertIn('the key names a secret', self.findings('forge.api_token', 'abc'))
        self.assertIn('the key names a secret', self.findings('forge.client_secret', 'abc'))
        self.assertEqual(self.findings('forge.none_token', 'none'), '')
        self.assertIn('the key names a secret', self.findings('forge.private_key', 'abc'))

    def test_only_the_secret_name_may_be_registered(self):
        self.assertEqual(self.findings('forge.api_token_env', 'GH_TOKEN'), '')
        self.assertIn('not an environment variable name', self.findings('forge.api_token_env', 'ghs_value'))

    def test_secret_shaped_values_are_refused(self):
        for value in ('ghp_' + 'a1B2' * 9, 'github_pat_' + 'x' * 30, 'sk-' + 'Q' * 30, 'AKIA' + 'A' * 16,
                      '-----BEGIN RSA PRIVATE KEY-----', 'postgres://user:pw@db.example.invalid/x'):
            with self.subTest(value=value[:12]):
                self.assertIn('shape of a secret', self.findings('forge.endpoint', value))

    def test_a_random_string_is_refused_and_a_digest_or_an_ordinary_value_is_not(self):
        self.assertIn('random secret', self.findings('forge.endpoint', 'q8Z3vN0xL5pR7tY2wK9mB4cH6jD1fG0sA3eU'))
        self.assertEqual(self.findings('forge.endpoint', '0123456789abcdef' * 4), '')
        self.assertEqual(self.findings('forge.max_tokens', 'claude'), '')

    def test_a_secret_in_the_registry_fails_the_check(self):
        self.write('config/registry/forge.json', registry('forge', **{'forge.password': parameter('hunter2')}))
        self.assertIn('forge.password: the key names a secret', self.errors())

    def test_set_values_are_judged_like_defaults(self):
        self.write('config/registry/forge.json', registry('forge', **{'forge.endpoint': parameter('x', pattern='^[a-z]+$')}))
        self.assertTrue(config.value_errors('forge.endpoint', 'sk-' + 'Q' * 30, self.root))
        self.assertIn('does not match', '\n'.join(config.value_errors('forge.endpoint', 'A1', self.root)))
        self.assertEqual(config.value_errors('forge.endpoint', 'ok', self.root), [])


class RegistryMemo(Fixture):
    """The registry is parsed once per process while no file changes; the replay once per read of the log."""

    def setUp(self):
        super().setUp()
        self.size = True + 0  # every value here is derived from this one, never restated
        self.write('config/registry/train.json', registry('train', **{'train.batch_size': parameter(self.size)}))
        # the racy rule's clock, pinned to the file system's own stamp of that write: no test reads the wall clock,
        # and what a test writes a moment later is still within a tick of it, as on the real clock
        self.now = (self.root / 'config/registry/train.json').stat().st_mtime_ns
        self.enterContext(mock.patch.object(config, '_now_ns', lambda: self.now))
        settled = self.now - (self.size + self.size) * config._RACY_NS  # a registry older than a clock tick
        for path in (self.root / 'config/registry').glob('*.json'):
            os.utime(path, ns=(settled, settled))
        self.addCleanup(config.invalidate)

    def reads(self):
        """Count every read of a file under this fixture's registry."""
        counted, original = [], Path.read_text

        def read_text(path, *args, **kwargs):
            if Path(path).parent == self.root / 'config/registry':
                counted.append(Path(path).name)
            return original(path, *args, **kwargs)
        self.enterContext(mock.patch.object(Path, 'read_text', read_text))
        return counted

    def test_repeated_gets_read_the_registry_once(self):
        counted = self.reads()
        for _ in 'repeated':
            self.assertEqual(config.get('train.batch_size', self.root), self.size)
        self.assertEqual(sorted(counted), ['config.json', 'train.json'])  # once each

    def test_a_registry_stamped_within_a_clock_tick_is_never_trusted_by_another_call(self):
        # The runner's disk (04/11): a same-size rewrite in the same coarse tick keeps the file's whole stat
        path = self.root / 'config/registry/train.json'
        now = self.now  # the pinned clock: stamped this tick
        os.utime(path, ns=(now, now))
        config.invalidate()
        self.assertEqual(config.get('train.batch_size', self.root), self.size)
        other = self.size + 1  # the same size on disk
        self.write('config/registry/train.json', registry('train', **{'train.batch_size': parameter(other)}))
        os.utime(path, ns=(now, now))  # the coarse clock's same stamp
        self.assertEqual(config.get('train.batch_size', self.root), other)

    def test_a_reading_block_stats_the_registry_once_and_sees_a_rewrite_after_it(self):
        """GATE-SPEED F3: inside config.reading() every get reuses the first look at the registry, so a file rewritten
        inside the block is read once the block ends."""
        bigger = self.size + 1
        with config.reading():
            self.assertEqual(config.get('train.batch_size', self.root), self.size)
            self.write('config/registry/train.json', registry('train', **{'train.batch_size': parameter(bigger)}))
            self.assertEqual(config.get('train.batch_size', self.root), self.size)
        self.assertEqual(config.get('train.batch_size', self.root), bigger)

    def test_a_returned_value_is_a_copy_of_the_registry_default(self):
        self.write('config/registry/train.json', registry('train', **{'train.lanes': parameter(['a'])}))
        config.get('train.lanes', self.root).append('b')
        self.assertEqual(config.get('train.lanes', self.root), ['a'])

    def test_a_rewritten_file_is_read_again(self):
        self.assertEqual(config.get('train.batch_size', self.root), self.size)
        path = self.root / 'config/registry/train.json'
        bigger = self.size + 1
        self.write('config/registry/train.json', registry('train', **{'train.batch_size': parameter(bigger)}))
        self.assertEqual(config.get('train.batch_size', self.root), bigger)
        stat = path.stat()
        same_size = bigger + 1
        self.write('config/registry/train.json', registry('train', **{'train.batch_size': parameter(same_size)}))
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
        self.assertEqual(config.get('train.batch_size', self.root), same_size)
        self.write('config/registry/lane.json', registry('lane', **{'lane.width': parameter(self.size)}))  # new file
        self.assertEqual(config.get('lane.width', self.root), self.size)

    def test_invalidate_drops_the_memo(self):
        counted = self.reads()
        config.get('train.batch_size', self.root)
        first = sorted(counted)
        config.invalidate()
        config.get('train.batch_size', self.root)
        self.assertEqual(sorted(counted), sorted(first + first))

    def test_callers_cannot_corrupt_the_memo(self):
        self.write('config/registry/train.json', registry('train', **{'train.names': parameter(['a'])}))
        config.get('train.names', self.root).append('b')
        config.entry('train.names', self.root)['default'].append('c')
        config._load(self.root)['train.names']['default'].append('d')
        self.assertEqual(config.get('train.names', self.root), ['a'])

    def listings(self):
        """Count every listing of this fixture's registry directory."""
        counted, original = [], os.listdir

        def listdir(path='.'):
            if Path(path) == self.root / 'config/registry':
                counted.append(path)
            return original(path)
        self.enterContext(mock.patch.object(os, 'listdir', listdir))
        return counted

    def age(self):
        """Move the registry directory's stamps past the racy window, so its listing is held (VAZÃO F1)."""
        directory = self.root / 'config/registry'
        old = directory.stat().st_mtime_ns - 2 * config._RACY_NS
        os.utime(directory, ns=(old, old))
        return directory, old

    def test_a_held_listing_still_sees_a_file_added_or_removed(self):
        """VAZÃO F1: the listing is reused while the directory's stat holds; an added file moves the directory's
        mtime, and a removed file a held listing still names is listed again, never a stale signature."""
        directory, old = self.age()
        listed = self.listings()
        for _ in 'repeated':
            self.assertEqual(config.get('train.batch_size', self.root), self.size)
        self.assertEqual(len(listed), 1)
        self.write('config/registry/lane.json', registry('lane', **{'lane.width': parameter(self.size)}))
        self.assertEqual(config.get('lane.width', self.root), self.size)
        (directory / 'lane.json').unlink()
        with self.assertRaises(KeyError):
            config.get('lane.width', self.root)
        os.utime(directory, ns=(old, old))
        config.get('train.batch_size', self.root)
        state, names = config._listing_memo[directory]
        config._listing_memo[directory] = (state, names + ('gone.json',))  # a held listing naming a file now gone
        self.assertEqual(config.get('train.batch_size', self.root), self.size)
        self.assertEqual(config._listing_memo[directory][1], names)

    def test_a_listing_taken_in_the_racy_window_is_not_held(self):
        listed = self.listings()
        for _ in 'repeated':
            config.get('train.batch_size', self.root)
        self.assertEqual(len(listed), len('repeated'))

    def test_a_scalar_is_handed_out_and_a_list_copied(self):
        self.write('config/registry/train.json', registry('train', **{'train.lanes': parameter(['a']),
                                                                      'train.batch_size': parameter(self.size)}))
        copies = self.enterContext(mock.patch.object(config.copy, 'deepcopy', wraps=copy.deepcopy))
        self.assertEqual(config.get('train.batch_size', self.root), self.size)
        self.assertEqual(copies.call_count, 0)
        config.get('train.lanes', self.root)
        self.assertEqual(copies.call_count, 1)

    def test_a_file_log_is_replayed_again_only_when_it_changes(self):
        # change detection alone; a log stamped within a clock tick is the racy rule's test, below
        self.enterContext(mock.patch.object(config, '_RACY_NS', 0))
        replays = self.enterContext(mock.patch.object(config, 'replay', wraps=config.replay))
        stores = self.enterContext(mock.patch.object(config, 'store', wraps=config.store))
        adapter = forge_events.FileAdapter(self.root / config.entry('config.store_dir', self.root)['default'])
        log = adapter.path(forge_events.Channel(config.entry('forge-events.repo')['default'], None))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('')
        past = self.enterContext(mock.patch.object(config, '_now_ns'))  # the clock just past the log's last stamp
        past.side_effect = lambda: max(log.stat().st_mtime_ns, log.stat().st_ctime_ns) + 1
        for _ in 'repeated':
            config.get('train.batch_size', self.root)
        self.assertEqual(replays.call_count, self.size)
        self.assertEqual(stores.call_count, self.size)
        stat = log.stat()
        os.utime(log, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
        config.get('train.batch_size', self.root)
        self.assertEqual(replays.call_count, self.size + 1)
        self.assertEqual(stores.call_count, self.size + 1)

    def test_a_log_stamped_within_a_clock_tick_is_folded_again_and_an_old_one_is_held(self):
        # The runner's disk (04/11): a same-size rewrite in one coarse tick, its mtime put back, kept the whole stat
        adapter = forge_events.FileAdapter(self.root / config.entry('config.store_dir', self.root)['default'])
        log = adapter.path(forge_events.Channel(config.entry('forge-events.repo')['default'], None))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('\n')
        now = self.now  # the pinned clock
        for stamped, folds in ((now, len(('first', 'again'))), (now - int('10') * config._RACY_NS, 1)):
            config._replay_memo.clear()
            stat = (1, 1, stamped, stamped, 1)  # the same stat on both reads, as the coarse clock gave it
            with mock.patch.object(config, '_log_state', return_value=stat), \
                    mock.patch.object(config, 'store', wraps=config.store) as stores:
                config.get('train.batch_size', self.root)
                config.get('train.batch_size', self.root)
            self.assertEqual(stores.call_count, folds, stamped)

    def test_rewriting_a_log_with_the_same_size_and_mtime_invalidates_its_fold(self):
        adapter = forge_events.FileAdapter(self.root / config.entry('config.store_dir', self.root)['default'])
        log = adapter.path(forge_events.Channel(config.entry('forge-events.repo')['default'], None))
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text('\n')
        config.get('train.batch_size', self.root)
        previous = log.stat()
        log.write_text(' ')
        os.utime(log, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        with mock.patch.object(config, 'store', wraps=config.store) as stores:
            self.assertEqual(config.get('train.batch_size', self.root), self.size)
        self.assertEqual(stores.call_count, self.size)


class RemoteForge(forge_events.MemoryAdapter):
    remote = True


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def now(self):
        return self.moment


class ReplayMemo(Fixture):
    """A remote store's overrides are replayed once per config.store_cache_ttl_s, then from a fresh read."""

    def test_the_replay_is_memoized_within_the_ttl_and_refreshed_after_it(self):
        start = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
        clock = Clock(start)
        self.enterContext(config.use_adapter(RemoteForge(), clock))
        self.addCleanup(config.invalidate)
        self.write('config/registry/train.json', registry('train', **{'train.batch_size': parameter(True + 0)}))
        replays = self.enterContext(mock.patch.object(config, 'replay', wraps=config.replay))
        ttl = config.entry('config.store_cache_ttl_s', self.root)['default']
        size = config.get('train.batch_size', self.root)
        for _ in 'repeated':
            self.assertEqual(config.get('train.batch_size', self.root), size)
        self.assertEqual(replays.call_count, size)
        clock.moment = start + datetime.timedelta(seconds=ttl - 1)
        config.get('train.batch_size', self.root)
        self.assertEqual(replays.call_count, size)
        clock.moment = start + datetime.timedelta(seconds=ttl)
        config.get('train.batch_size', self.root)
        self.assertEqual(replays.call_count, size + 1)
        config.overrides(self.root)['train.batch_size'] = size + 1  # a caller's copy, never the memo
        self.assertEqual(config.get('train.batch_size', self.root), size)

    def test_a_stored_value_is_read_in_place_and_returned_as_a_copy(self):
        """GATE-SPEED R3: a read no longer copies every override, only the value it returns; changing it never
        reaches the held replay."""
        self.enterContext(config.use_adapter(RemoteForge(), Clock(datetime.datetime.fromtimestamp(0, datetime.timezone.utc))))
        self.addCleanup(config.invalidate)
        self.write('config/registry/train.json', registry('train', **{'train.names': parameter(['a'])}))
        self.enterContext(mock.patch.object(config, 'replay', return_value={'train.names': ['b']}))
        copies = self.enterContext(mock.patch.object(config.copy, 'deepcopy', wraps=copy.deepcopy))
        config.get('train.names', self.root).append('c')
        self.assertEqual(config.get('train.names', self.root), ['b'])
        self.assertNotIn({'train.names': ['b']}, [call.args[0] for call in copies.call_args_list])  # never the whole fold


class Quarantine(Fixture):
    """ENV-FIX-PREMISE-BLAST: the real premise.blast of the repository channel (#548, producer 'scripts/premises')
    made every config.get raise StoreError. The append-only log keeps it; the reader skips and quarantines it."""

    EVENT = json.loads((ROOT / 'scripts/tests/fixtures/premise-blast-548.json').read_text())

    def test_an_invalid_envelope_on_the_log_is_quarantined_not_fatal(self):
        forge = RemoteForge()
        clock = Clock(datetime.datetime.fromisoformat(self.EVENT['occurred_at'].replace('Z', '+00:00')))
        self.enterContext(config.use_adapter(forge, clock))
        self.enterContext(mock.patch.object(config, '_ROOT', self.root))  # nested reads without a root stay in the fixture
        self.addCleanup(config.invalidate)
        default = True + 0
        self.write('config/registry/train.json', registry('train', **{'train.batch_size': parameter(default)}))
        channel = forge_events.Channel(config.entry('forge-events.repo')['default'], None)
        forge.append(channel, [self.EVENT])
        err = self.enterContext(mock.patch('sys.stderr', new_callable=io.StringIO))
        changed = default + default
        config.set_value('train.batch_size', changed, actor='test', reason='after the bad event', now=clock.now(),
                         root=self.root)
        config._invalidate(self.root)
        self.assertEqual(config.get('train.batch_size', self.root), changed)
        self.assertIn("'scripts/premises' does not match", err.getvalue())
        log = self.root / config.entry('config.store_quarantine_log')['default']
        lines = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([(item['event_id'], item['type']) for item in lines], [(self.EVENT['event_id'], 'premise.blast')])
        config._invalidate(self.root)
        err.seek(0)
        err.truncate()
        self.assertEqual(config.get('train.batch_size', self.root), changed)
        self.assertEqual((err.getvalue(), len(log.read_text().splitlines())), ('', len(lines)))  # said and recorded once


# M5 (#497): every entry is typed, documented, owned by its file and read by a real module.
TYPES = {"integer", "number", "boolean", "string", "array", "object"}


class RegistryTest(unittest.TestCase):
    def test_unknown_name_is_rejected(self):
        with self.assertRaises(KeyError):
            config.get("session-cache.no_such_key")

    def test_every_entry_is_typed_documented_owned_and_read(self):
        for path in sorted((ROOT / "config" / "registry").glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["$id"], f"config/registry/{path.name}")
            owner = doc["x-owner"]
            for name, spec in doc["properties"].items():
                with self.subTest(name=name):
                    self.assertTrue(name.startswith(owner + "."))
                    self.assertIn(spec["type"], TYPES)
                    self.assertIn("default", spec)
                    self.assertTrue(spec["description"].strip())
                    self.assertTrue(spec["x-readers"])
                    for reader in spec["x-readers"]:
                        self.assertTrue((ROOT / reader).is_file(), reader)


class RegistryAtRef(unittest.TestCase):
    """VAZÃO F1: the registry at a git ref is read with one git ls-tree and one git cat-file --batch."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owners = {'lane': {'lane.width': parameter(2)},
                       'train': {'train.batch_size': parameter(3), 'train.names': parameter(['é'])}}
        for owner, parameters in self.owners.items():
            path = self.root / f'config/registry/{owner}.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(registry(owner, **parameters), indent=1, ensure_ascii=False), encoding='utf-8')
        (self.root / 'config/registry/train').mkdir()
        (self.root / 'config/registry/train/batch.json').write_text('{"a split owner source": true}')
        (self.root / 'config/registry/README.md').write_text('not a registry file')
        env = {**os.environ, 'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't',
               'GIT_COMMITTER_EMAIL': 't@t'}
        for command in (['init', '-q'], ['add', '.'], ['commit', '-qm', 'registry']):
            subprocess.run(['git', '-C', str(self.root), *command], check=True, env=env, capture_output=True)

    def test_every_aggregate_is_read_in_two_git_processes(self):
        runs = self.enterContext(mock.patch.object(config.subprocess, 'run', wraps=subprocess.run))
        found = config._registry_at('HEAD', self.root)
        self.assertEqual(found, {name: item for parameters in self.owners.values() for name, item in parameters.items()})
        self.assertEqual(runs.call_count, 2)

    def test_an_unknown_ref_reads_as_no_registry(self):
        self.assertEqual(config._registry_at('no-such-ref', self.root), {})



class Replay(unittest.TestCase):
    """Moved from test_config_key.py when the control store's versioned key left (D-300)."""

    def test_a_snapshot_whose_change_left_the_window_folds_every_change_the_window_holds(self):
        snapshot = {'type': 'config.snapshot', 'event_id': 's', 'payload': {'overrides': {'a': 1}, 'through': 'gone'}}
        change = {'type': 'config.changed', 'event_id': 'c', 'payload': {'name': 'b', 'new': 0}}
        for events in ([snapshot, change], [change, snapshot]):
            self.assertEqual(config.replay(events), {'a': 1, 'b': 0})


if __name__ == '__main__':
    unittest.main()
