"""The storage port and its local adapter (D-069 item 7); the tier-1 result cache stores through it. No network."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import gate_result_cache  # noqa: E402
from adapters import storage  # noqa: E402


class Local(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = storage.open_store(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_put_get_exists_and_keys(self):
        self.assertFalse(self.store.exists('a/b'))
        self.assertIsNone(self.store.get('a/b'))
        self.store.put('a/b', b'one')
        self.store.put('a/b', b'two')
        self.store.put('c', b'')
        self.assertTrue(self.store.exists('a/b'))
        self.assertEqual(self.store.get('a/b'), b'two')
        self.assertEqual(self.store.keys(), ['a/b', 'c'])
        self.assertEqual(self.store.keys('a'), ['a/b'])
        self.assertEqual(self.store.keys('missing'), [])
        self.assertEqual(sorted(p.name for p in Path(self.tmp.name, 'a').iterdir()), ['b'], 'no temporary file left')

    def test_a_key_never_leaves_the_root(self):
        for key in ('', '/abs', '../up', 'a/../b', 'a//b', 'a/./b', 'sp ace'):
            with self.assertRaises(storage.StorageError, msg=key):
                self.store.put(key, b'x')

    def test_the_registry_selects_the_adapter(self):
        self.assertEqual(self.store.name, config.get('providers.storage_adapter'))
        with self.assertRaises(storage.StorageError):
            storage.open_store(self.tmp.name, 'other')


class ResultCache(unittest.TestCase):
    def test_the_tier1_marker_is_a_storage_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(gate_result_cache.hit(tmp, 'f' * 64))
            gate_result_cache.store(tmp, 'f' * 64)
            self.assertTrue(gate_result_cache.hit(tmp, 'f' * 64))
            self.assertEqual(storage.open_store(tmp).keys(), ['tier1/' + 'f' * 64])
            self.assertTrue((Path(tmp) / 'tier1' / ('f' * 64)).is_file(), 'the on-disk layout is unchanged')
            self.assertFalse(gate_result_cache.hit(tmp, ''))
            with self.assertRaises(ValueError):
                gate_result_cache.store(tmp, '')

    def test_the_port_never_touches_the_filesystem_directly(self):
        source = (ROOT / 'scripts/lib/adapters/storage.py').read_text()
        self.assertNotIn('open(', source.replace('open_store(', ''))
        self.assertNotIn('os.replace', source)


if __name__ == '__main__':
    unittest.main(verbosity=1)
