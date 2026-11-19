"""TX26: a covers manifest change selects its own script test, the map check and the tests whose covers match the
manifest path, not the whole suite (T3)."""
# Verifies: UNIT:engine-gate-tests
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config
import gate_script_tests as tests

COVERS = config.get('gate-tests.covers_dir', ROOT)
MAP_CHECK = config.get('gate-tests.map_check', ROOT)
SELECTOR_FILES = ('config/registry/gate-tests.json', 'scripts/lib/gate_script_tests.py', 'scripts/gate-local', 'scripts/lib/gate-runner.sh')


def manifest(name):
    return f'{COVERS}/{name}.json'


def covering(mapping, path):
    """Every script test whose covers meet the path, sorted."""
    return tuple(sorted(item['script'] for item in mapping['tests']
                        if any(tests.glob_match(path, glob) for glob in item['covers'])))


def script(name):
    return f'{Path(COVERS).parent.as_posix()}/{name}.test.sh'


class CoversManifestSelection(unittest.TestCase):
    def setUp(self):
        self.mapping = tests.load()
        self.all = self.mapping['scripts']

    def test_a_manifest_selects_its_test_and_the_map_check_only(self):
        chosen, reason = tests.select([manifest('gate-local')], self.mapping)
        expected = {script('gate-local'), MAP_CHECK, *covering(self.mapping, manifest('gate-local'))}
        self.assertEqual(chosen, tuple(sorted(expected)))
        self.assertIn(manifest('gate-local'), reason)
        self.assertNotIn('selector changed', reason)
        self.assertLess(len(chosen), len(self.all))

    def test_the_covers_directory_is_no_longer_a_selector_file(self):
        for pattern in self.mapping['fallback']:
            self.assertFalse(tests.glob_match(manifest('gate-local'), pattern), pattern)

    def test_the_selector_code_still_runs_everything(self):
        for path in SELECTOR_FILES:
            chosen, reason = tests.select([manifest('gate-local'), path], self.mapping)
            self.assertEqual(chosen, self.all, path)
            self.assertEqual(reason, f'selector changed: {path}')

    def test_several_manifests_select_each_test_once(self):
        chosen, _reason = tests.select([manifest('gate-local'), manifest('budgets')], self.mapping)
        readers = {*covering(self.mapping, manifest('gate-local')), *covering(self.mapping, manifest('budgets'))}
        self.assertEqual(chosen, tuple(sorted({script('gate-local'), script('budgets'), MAP_CHECK, *readers})))

    def test_a_manifest_next_to_a_covered_path_adds_to_that_tests(self):
        covered = tests.select(['scripts/lib/gate-budget.sh'], self.mapping)[0]
        chosen, _reason = tests.select([manifest('budgets'), 'scripts/lib/gate-budget.sh'], self.mapping)
        readers = set(covering(self.mapping, manifest('budgets')))
        self.assertEqual(set(chosen), set(covered) | {script('budgets'), MAP_CHECK} | readers)

    def test_a_manifest_with_a_docs_path_does_not_widen(self):
        alone = tests.select([manifest('gate-local')], self.mapping)
        self.assertEqual(tests.select([manifest('gate-local'), 'docs/x.md'], self.mapping), alone)

    def test_a_manifest_without_a_script_test_selects_the_tests_that_cover_the_path(self):
        chosen, reason = tests.select([manifest('no-such-test')], self.mapping)
        expected = covering(self.mapping, manifest('no-such-test'))
        self.assertTrue(expected)
        self.assertEqual(chosen, expected)
        self.assertIn('cover the diff', reason)

    def test_a_file_that_is_not_a_manifest_in_the_covers_directory_runs_only_the_tests_that_cover_it(self):
        # D-175: units-repository covers scripts/**, so a stray file under the covers directory is a covered path, no longer
        # an unowned one; it must select exactly the tests whose covers meet it and never fewer.
        for path in (f'{COVERS}/README.md', f'{COVERS}/nested/gate-local.json'):
            with self.subTest(path=path):
                chosen, _reason = tests.select([path], self.mapping)
                expected = covering(self.mapping, path)
                self.assertTrue(expected)
                self.assertEqual(chosen, expected)

    def test_the_plan_path_selects_the_same(self):
        chosen, _reason = tests.select_plan({'paths': [manifest('gate-local')]})
        expected = {script('gate-local'), MAP_CHECK, *covering(self.mapping, manifest('gate-local'))}
        self.assertEqual(chosen, tuple(sorted(expected)))

    def test_a_manifest_selects_every_test_whose_covers_glob_matches_it(self):
        # covers-cost and units-repository list the manifests in their own covers, so their cache keys move with any
        # manifest; a one-manifest diff must run them, by the glob rule and not a list.
        for name in ('gate-local', 'budgets'):
            chosen, _reason = tests.select([manifest(name)], self.mapping)
            readers = covering(self.mapping, manifest(name))
            self.assertIn(script('covers-cost'), readers)
            self.assertIn(script('units-repository'), readers)
            self.assertTrue(set(readers) <= set(chosen), sorted(set(readers) - set(chosen)))

    def test_the_glob_rule_is_general(self):
        mapping = {'scripts': (script('a'), script('reader'), script('other'), MAP_CHECK),
                   'fallback': (), 'tests': [
                       {'script': script('a'), 'covers': (script('a'),)},
                       {'script': script('reader'), 'covers': (script('reader'), f'{COVERS}/a.json')},
                       {'script': script('other'), 'covers': (script('other'), f'{COVERS}/b.json')},
                       {'script': MAP_CHECK, 'covers': (MAP_CHECK,)}]}
        chosen, _reason = tests.select([manifest('a')], mapping)
        self.assertEqual(chosen, (script('a'), script('reader'), MAP_CHECK))


class CoversManifestFailsClosed(unittest.TestCase):
    """A broken manifest is still refused by the map check and by select() itself."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.covers = self.root / COVERS
        self.covers.mkdir(parents=True)
        for name in ('a', 'b'):
            (self.root / script(name)).write_text(f'#!/usr/bin/env bash\necho {name}\n')
            (self.covers / f'{name}.json').write_text(json.dumps({'script': script(name), 'covers': [script(name)]}))

    def test_the_intact_map_is_ok(self):
        self.assertEqual(tests.check(self.root), [])
        chosen, _reason = tests.select([manifest('a')], tests.load(self.root))
        self.assertIn(script('a'), chosen)
        self.assertNotIn(script('b'), chosen)

    def test_a_malformed_manifest_fails_the_map_check(self):
        (self.covers / 'a.json').write_text('{not json')
        self.assertIn('cannot read', tests.check(self.root)[0])
        with self.assertRaises(tests.ScriptTestMapError):
            tests.load(self.root)

    def test_an_invalid_manifest_fails_the_map_check(self):
        (self.covers / 'a.json').write_text(json.dumps({'script': script('a'), 'covers': []}))
        self.assertIn('covers must be a non-empty list', tests.check(self.root)[0])

    def test_a_deleted_manifest_fails_the_map_check(self):
        (self.covers / 'a.json').unlink()
        self.assertIn('no covers manifest', tests.check(self.root)[0])
        with self.assertRaises(tests.ScriptTestMapError):
            tests.load(self.root)

    def test_a_removed_test_with_its_manifest_runs_everything(self):
        mapping = tests.load(self.root)
        (self.root / script('a')).unlink()
        (self.covers / 'a.json').unlink()
        self.assertEqual(tests.check(self.root), [])
        chosen, reason = tests.select([manifest('a')], tests.load(self.root))
        self.assertEqual(chosen, tests.load(self.root)['scripts'])
        self.assertIn('uncovered path', reason)
        self.assertIn(script('a'), mapping['scripts'])


if __name__ == '__main__':
    unittest.main()
