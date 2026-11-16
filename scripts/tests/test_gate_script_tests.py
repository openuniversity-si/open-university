"""Table-driven script-test selection. An uncovered scripts path runs the whole suite."""
import functools
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from gate_areas import glob_match
import gate_script_tests as tests
import gate_test_cache as cache

COVERS = ROOT / 'scripts' / 'tests' / 'covers'


@functools.lru_cache(maxsize=None)
def manifests():
    """The covers manifests as written (T2, TX23): read straight from the files, not through the selector under test."""
    return [json.loads(path.read_text()) for path in sorted(COVERS.glob('*.json'))]


@functools.lru_cache(maxsize=None)
def traced():
    """The traced map as written (PADRAO-DEV F5b-2): {script: [files]}, read straight from the file."""
    target = ROOT / 'scripts' / 'tests' / 'traced-covers.json'
    return json.loads(target.read_text())['tests'] if target.exists() else {}


def covering(path):
    return [item['script'] for item in manifests()
            if any(glob_match(path, pattern) for pattern in (*item['covers'], *traced().get(item['script'], ())))]


def expected_selection(paths):
    """What the selector must choose for scoped paths: the tests whose manifests cover an owned path. A path outside
    scripts/ is owned only when some manifest covers it (a registry file or contract a script test reads)."""
    owned = [path for path in paths if path.startswith('scripts/') or covering(path)]
    return tuple(sorted({script for path in owned for script in covering(path)}))


class ScriptTestSelection(unittest.TestCase):
    def setUp(self):
        self.mapping = tests.load()
        self.all = self.mapping['scripts']

    def test_the_map_names_every_script_test_once(self):
        self.assertEqual(tuple(sorted(item['script'] for item in self.mapping['tests'])), self.all)
        self.assertIn('scripts/tests/gate-script-tests.test.sh', self.all)

    def test_table(self):
        cases = {
            'setup': (['scripts/cloud/setup.sh'], expected_selection(['scripts/cloud/setup.sh']), False),
            'one-lib': (
                ['scripts/lib/session_identity.py'],
                None,
                False,
            ),
            'selector': (['scripts/lib/gate_script_tests.py'], self.all, True),
            'runner': (['scripts/gate-local'], self.all, True),
            'uncovered-shell': (['tools/brand-new.sh'], self.all, True),
            'empty': ([], self.all, True),
            'docs-only-input': (['docs/operations/local-gate.md'], self.all, True),
            'new-lib-python': (['scripts/lib/not-yet.py'], expected_selection(['scripts/lib/not-yet.py']), False),
            # OU-DECOUPLE F4 (D-111): a covered path outside scripts/ (a registry file a script test reads) beside an
            # uncovered product path, formerly the admin CLI run by the tower-media tests.
            'covered-outside-scripts': (
                ['config/registry/forge-events.json', 'products/demo/src/app.ts'],
                expected_selection(['config/registry/forge-events.json', 'products/demo/src/app.ts']),
                False,
            ),
        }
        for name, (paths, expected, full) in cases.items():
            with self.subTest(name=name):
                chosen, reason = tests.select(paths, self.mapping)
                if name == 'one-lib':
                    self.assertIn('scripts/tests/root-identity.test.sh', chosen)
                    # D-215 (91f76f343): gate-verdict no longer covers session_identity.py; covers-prove PASS
                    # (`scripts/covers-prove gate-verdict --without scripts/lib/session_identity.py`), so it is not chosen.
                    self.assertNotIn('scripts/tests/gate-verdict.test.sh', chosen)
                    self.assertLess(len(chosen), len(self.all))
                    self.assertNotIn('full script suite', reason)
                    continue
                self.assertEqual(chosen, expected, reason)
                self.assertEqual(chosen == self.all, full)
                if not full:
                    self.assertTrue(chosen, 'a scoped row selects at least one test')
                    self.assertLess(len(chosen), len(self.all))

    def test_a_full_area_plan_runs_every_script_test(self):
        chosen, reason = tests.select_plan({'kind': 'full', 'paths': ['scripts/cloud/setup.sh']})
        self.assertEqual(chosen, self.all)
        self.assertIn('full area plan', reason)

    def test_gate_local_runs_the_selected_tests_together(self):
        text = (ROOT / 'scripts' / 'gate-local').read_text()
        self.assertNotIn('for t in scripts/tests/*.test.sh', text)
        self.assertIn('run_script_tests', text)
        self.assertIn('gate_test_cache.py" run', text)  # GS1: one bounded concurrent runner with the per-test cache, results in test order
        # OU-DECOUPLE F5 (D-113): no script test runs Open University's web package, so the gate installs none.
        self.assertNotIn('share_node_modules', text)
        self.assertNotIn('pnpm install', text)

    def test_the_selector_has_no_installed_modules_question(self):
        # VAZÃO F57: modules_required and the `modules` action had no caller; no script test installs a package.
        self.assertFalse(hasattr(tests, 'modules_required'))
        # PADRAO-DEV F5b-2: a test may also carry its traced files, apart from its covers.
        self.assertTrue(all({'script', 'covers'} <= set(item) <= {'script', 'covers', 'traced'} for item in self.mapping['tests']))


class CoversManifests(unittest.TestCase):
    """GX-08: one covers manifest per script test (D-065 V4); the old aggregate map and its migration left (VAZÃO F57)."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        (self.root / 'scripts' / 'tests').mkdir(parents=True)
        for name in ('a', 'b'):
            (self.root / 'scripts' / 'tests' / f'{name}.test.sh').write_text(f'#!/usr/bin/env bash\necho {name}\n')
        (self.root / 'scripts' / 'lib').mkdir()
        (self.root / 'scripts' / 'lib' / 'x.py').write_text('x = 1\n')
        self.covers = self.root / 'scripts' / 'tests' / 'covers'
        self.covers.mkdir()
        self.write('a', {'script': 'scripts/tests/a.test.sh', 'covers': ['scripts/tests/a.test.sh', 'scripts/lib/x.py']})
        self.write('b', {'script': 'scripts/tests/b.test.sh', 'covers': ['scripts/lib/*.py', 'scripts/tests/b.test.sh']})
        self.files = ['scripts/tests/a.test.sh', 'scripts/tests/b.test.sh', 'scripts/lib/x.py']

    def write(self, name, data):
        (self.covers / f'{name}.json').write_text(json.dumps(data))

    def test_the_manifests_load_in_script_order(self):
        mapping = tests.load(self.root)
        self.assertEqual([item['script'] for item in mapping['tests']], list(mapping['scripts']))
        self.assertEqual(mapping['tests'][1], {'script': 'scripts/tests/b.test.sh', 'covers': ('scripts/lib/*.py', 'scripts/tests/b.test.sh')})

    def test_a_leftover_modules_field_is_optional_and_without_effect(self):
        # No covers file carries the field since PR 2 of F57; a stray one is still read as nothing.
        before = tests.load(self.root)
        keys = {script: cache.key(script, self.root, before, self.files, node='n') for script in before['scripts']}
        self.assertTrue(all(keys.values()))
        for value in (True, False, 'yes', None):
            with self.subTest(modules=value):
                self.write('b', {'script': 'scripts/tests/b.test.sh', 'covers': ['scripts/lib/*.py', 'scripts/tests/b.test.sh'],
                                 'modules': value})
                after = tests.load(self.root)
                self.assertEqual(after, before)
                self.assertEqual(tests.check(self.root), [])
                self.assertEqual({script: cache.key(script, self.root, after, self.files, node='n') for script in after['scripts']}, keys)

    def test_the_traced_map_joins_the_selection_and_the_cache_key_but_not_the_declared_covers(self):
        before = tests.load(self.root)
        key = cache.key('scripts/tests/a.test.sh', self.root, before, self.files, node='n')
        (self.root / 'scripts' / 'lib' / 'y.py').write_text('y = 1\n')
        self.files.append('scripts/lib/y.py')
        self.assertEqual(tests.select(['scripts/lib/y.py'], before)[0], ('scripts/tests/b.test.sh',))
        (self.root / 'scripts' / 'tests' / 'traced-covers.json').write_text(
            json.dumps({'tests': {'scripts/tests/a.test.sh': ['scripts/lib/y.py']}}))
        after = tests.load(self.root)
        self.assertEqual(after['tests'][0]['covers'], ('scripts/tests/a.test.sh', 'scripts/lib/x.py'))
        self.assertEqual(after['tests'][0]['traced'], ('scripts/lib/y.py',))
        self.assertEqual(tests.select(['scripts/lib/y.py'], after)[0], ('scripts/tests/a.test.sh', 'scripts/tests/b.test.sh'))
        self.assertNotEqual(cache.key('scripts/tests/a.test.sh', self.root, after, self.files, node='n'), key)

    def test_a_traced_map_that_is_not_a_map_of_paths_is_refused(self):
        (self.root / 'scripts' / 'tests' / 'traced-covers.json').write_text(json.dumps({'tests': {'a': 'x'}}))
        self.assertIn('tests must map a script to a list of paths', tests.check(self.root)[0])

    def test_a_script_test_without_a_manifest_is_refused(self):
        self.assertEqual(tests.check(self.root), [])
        (self.root / 'scripts' / 'tests' / 'new.test.sh').write_text('#!/usr/bin/env bash\n')
        errors = tests.check(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn('scripts/tests/new.test.sh: no covers manifest', errors[0])

    def test_a_manifest_without_a_script_test_or_with_a_wrong_script_is_refused(self):
        covers = self.root / 'scripts' / 'tests' / 'covers'
        (covers / 'ghost.json').write_text('{}')
        self.assertIn('without a script test', tests.check(self.root)[0])
        (covers / 'ghost.json').unlink()
        (covers / 'a.json').write_text(json.dumps({'script': 'scripts/tests/b.test.sh', 'covers': ['x']}))
        self.assertIn('declares scripts/tests/b.test.sh', tests.check(self.root)[0])

    def test_the_real_repository_has_a_valid_manifest_for_every_script_test(self):
        self.assertEqual(tests.check(), [])
        self.assertEqual(len(tests.load()['tests']), len(tests.discover()))
        self.assertFalse((ROOT / 'scripts' / 'lib' / 'gate-script-tests.json').exists())
        self.assertEqual([item['script'] for item in manifests() if set(item) != {'script', 'covers'}], [])

class CoversTrace(unittest.TestCase):
    def setUp(self):
        self.mapping = {'tests': ({'script': 'a.test.sh', 'covers': ('scripts/tests/test_a.py', 'scripts/lib/a.py')},
                                  {'script': 'b.test.sh', 'covers': ('scripts/tests/test_a.py', 'docs/b.md')})}

    def test_reads_outside_every_manifest_naming_the_test_are_under_declared(self):
        found = tests.trace_check(['scripts/lib/a.py', 'docs/b.md', 'scripts/lib/other.py'], 'scripts/tests/test_a.py', mapping=self.mapping)
        self.assertEqual(found, {'declared': True, 'under': ['scripts/lib/other.py']})

    def test_the_registry_and_generated_modules_are_exempt(self):
        found = tests.trace_check(['config/registry/tests.json', 'scripts/lib/generated/x.py', 'scripts/lib/a.py'],
                                  'scripts/tests/test_a.py', mapping=self.mapping)
        self.assertEqual(found['under'], [])

    def test_the_decisions_file_every_manifest_load_reads_is_exempt_but_other_docs_are_not(self):
        found = tests.trace_check(['docs/domain/DECISIONS.md', 'docs/domain/CONTRACT.md', 'scripts/lib/a.py'],
                                  'scripts/tests/test_a.py', mapping=self.mapping)
        self.assertEqual(found['under'], ['docs/domain/CONTRACT.md'])

    def test_a_test_in_no_manifest_is_not_declared(self):
        self.assertEqual(tests.trace_check(['x'], 'scripts/tests/test_zzz.py', mapping=self.mapping), {'declared': False, 'under': []})


if __name__ == '__main__':
    unittest.main()
