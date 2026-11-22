"""The unit map generator (D-067 (4)): import graph, co-change from the git log, the ceiling from the registry, the
proposed cut and the measures of each manifest.

Fixture git repositories in a temporary directory with a small registry ceiling; no network, no clock.
"""
from datetime import datetime, timezone
import json
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
import source_facts  # noqa: E402
import unit_map  # noqa: E402
import units  # noqa: E402

COPIED = ('contracts/units/unit.v1.json', 'contracts/config/registry.v1.json', 'config/registry/config.json',
          'config/registry/forge-events.json')
SMALL = {'units.size_target': 8, 'units.size_ceiling': 10, 'units.context_budget': 40, 'units.merge_floor_lines': 3,
         'units.production_globs': ['app/src/**', 'tools/**'], 'units.test_globs': ['**/*.test.*'],
         'units.size_exempt_globs': ['**/*.json'], 'units.tsconfig_files': ['app/tsconfig.json'],
         'units.python_import_dirs': ['tools/lib'], 'units.bytes_per_token': 1}


class Clock:
    def now(self):
        return datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc)


def lines(count, extra=''):
    return extra + ''.join(f'export const v{index} = {index};\n' for index in range(count - len(extra.splitlines())))


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        for name in COPIED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        registry = json.loads((ROOT / 'config/registry/units.json').read_text())
        for name, value in SMALL.items():
            registry['properties'][name]['default'] = value
        for item in registry['properties'].values():
            item['x-readers'] = []
        self.write('config/registry/units.json', registry)
        self.write('docs/domain/DECISIONS.md', '| D-067 | today |\n')
        self.write('app/tsconfig.json', {'compilerOptions': {'paths': {'@/*': ['./src/*']}}})
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.reset()

    def tearDown(self):
        self.reset()
        self.tmp.cleanup()

    def reset(self):
        units.reset()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))

    def commit(self, *names, message='change'):
        git = ['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
        subprocess.run(git + ['add', '-A', *names] if names else git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-qm', message, '--allow-empty'], check=True)

    def code(self):
        self.reset()
        return unit_map.Code(self.root)


class Graph(Fixture):
    def test_d067_the_graph_resolves_relative_alias_python_and_shell_references(self):
        self.write('app/src/a/one.ts', "import { x } from './two';\nimport { y } from '@/b/three';\n")
        self.write('app/src/a/two.ts', 'export const x = 1;\n')
        self.write('app/src/b/three.ts', 'export const y = 1;\n')
        self.write('tools/lib/alpha.py', 'import beta\nfrom gamma import g\n')
        self.write('tools/lib/beta.py', 'B = 1\n')
        self.write('tools/lib/gamma.py', 'g = 1\n')
        self.write('tools/run', '#!/usr/bin/env bash\nexec python3 "$(dirname "$0")/lib/alpha.py"\n')
        self.write('app/src/a/one.test.ts', "import { x } from './one';\n")
        self.write('tools/lib/plan.json', '{"covers": ["tools/lib/alpha.py"]}')
        self.commit()
        code = self.code()
        self.assertEqual(code.edges['app/src/a/one.ts'], {'app/src/a/two.ts', 'app/src/b/three.ts'})
        self.assertEqual(code.edges['tools/lib/alpha.py'], {'tools/lib/beta.py', 'tools/lib/gamma.py'})
        self.assertEqual(code.edges['tools/run'], {'tools/lib/alpha.py'})
        self.assertEqual(code.edges['tools/lib/plan.json'], set())  # data names files; it imports none
        self.assertNotIn('app/src/a/one.test.ts', code.production)
        self.assertEqual(code.closure(['tools/run']), {'tools/run', 'tools/lib/alpha.py', 'tools/lib/beta.py',
                                                       'tools/lib/gamma.py'})

    def test_dynamic_selection_is_verified_separately_from_static_imports(self):
        self.write('tools/lib/port.py', "import importlib\nDYNAMIC_IMPORTS = ('load',)\n"
                   "def load(): return importlib.import_module('vendor')\n")
        self.write('tools/lib/vendor.py', 'VALUE = 1\n')
        self.commit()
        code = self.code()
        self.assertEqual(code.dynamic_errors, [])
        self.assertEqual(code.edges['tools/lib/port.py'], {'tools/lib/vendor.py'})
        self.assertEqual(code.static_edges['tools/lib/port.py'], set())
        self.write('tools/lib/vendor.py', '')
        (self.root / 'tools/lib/vendor.py').unlink()
        self.assertTrue(any('target absent: vendor' in error for error in self.code().dynamic_errors))

    def test_real_forge_selections_are_visible_without_vendor_requires(self):
        code = unit_map.Code(ROOT, log='')
        targets = {f'scripts/lib/forge_{name}.py' for name in ('origin', 'git_ref')}  # D-300: control left the log
        self.assertTrue(targets <= code.edges['scripts/lib/forge_events.py'])
        self.assertNotIn('scripts/lib/forge_github.py', code.edges['scripts/lib/forge_events.py'])  # D-293
        self.assertEqual(targets & code.static_edges['scripts/lib/forge_events.py'],
                         {'scripts/lib/forge_git_ref.py'})
        self.assertEqual(code.dynamic_errors, [])
        needs = unit_map.requires(ROOT, code).get('engine-events', [])
        manifest = json.loads((ROOT / 'units/engine-events/unit.json').read_text())
        selected = targets - code.static_edges['scripts/lib/forge_events.py']  # a static import is a real requires (F90)
        owners = {owner for target in selected for owner in units.units_of(target, ROOT)} - {'engine-events'}
        self.assertTrue(selected)
        self.assertIn('engine-git-ref', needs)
        self.assertFalse(owners & set(manifest['requires']))
        self.assertFalse(owners & set(needs))

    def test_d067_co_change_reads_the_log_and_leaves_bulk_commits_out(self):
        self.write('app/src/a/one.ts', lines(2))
        self.write('app/src/a/two.ts', lines(2))
        self.commit()
        self.write('app/src/a/one.ts', lines(3))
        self.write('app/src/a/two.ts', lines(3))
        self.commit()
        code = self.code()
        self.assertEqual(len(code.commits), 2)
        self.assertEqual(unit_map.affinity(code, ['app/src/a/one.ts'], ['app/src/a/two.ts']),
                         config.get('units.cochange_weight', self.root))
        registry = json.loads((self.root / 'config/registry/units.json').read_text())
        registry['properties']['units.cochange_max_files']['default'] = 1
        self.write('config/registry/units.json', registry)
        self.assertEqual(self.code().commits, [])


class SelectionCache(Fixture):
    """F31: each file's dynamic selections are kept by content; the answer is the uncached one whatever the cache holds."""
    PORT = ("import importlib\nDYNAMIC_IMPORTS = ('load',)\n"
            "def load(): return importlib.import_module('vendor')\n")
    FILES = {'tools/lib/port.py': PORT, 'tools/lib/vendor.py': 'VALUE = 1\n', 'tools/lib/other.py': 'VALUE = 0\n'}
    SELECTED = {'tools/lib/port.py': ['tools/lib/vendor.py']}

    def setUp(self):
        super().setUp()
        self.cache = self.root.parent / f'{self.root.name}-cache'
        patched = mock.patch.dict('os.environ', {source_facts.ENV: str(self.cache)})
        patched.start()
        self.addCleanup(patched.stop)
        self.addCleanup(shutil.rmtree, self.cache, True)
        for name, text in self.FILES.items():
            self.write(name, text)
        self.commit()

    def entries(self):
        return sorted(path for path in self.cache.rglob('*') if path.is_file()) if self.cache.is_dir() else []

    def answer(self, extracted):
        """(dynamic edges, dynamic errors), asserting how many files were extracted rather than read from the cache."""
        with mock.patch.object(unit_map, 'dynamic_selections', wraps=unit_map.dynamic_selections) as extract:
            code = self.code()
        self.assertEqual(extract.call_count, extracted)
        return {path: sorted(found) for path, found in code.dynamic_edges.items() if found}, code.dynamic_errors

    def test_cold_warm_and_uncached_give_one_answer(self):
        cold = self.answer(extracted=len(self.FILES))
        self.assertEqual(cold, (self.SELECTED, []))
        self.assertEqual(len(self.entries()), len(self.FILES))
        self.assertEqual(self.answer(extracted=0), cold)
        with mock.patch.dict('os.environ', {source_facts.ENV: ''}):
            self.assertEqual(self.answer(extracted=len(self.FILES)), cold)
        self.assertEqual(len(self.entries()), len(self.FILES))

    def test_a_changed_file_is_extracted_again(self):
        self.answer(extracted=len(self.FILES))
        self.write('tools/lib/port.py', self.PORT.replace("'vendor'", "'other'"))
        self.assertEqual(self.answer(extracted=1), ({'tools/lib/port.py': ['tools/lib/other.py']}, []))
        self.write('tools/lib/port.py', self.PORT + "def stray(name): return importlib.import_module(name)\n")
        self.assertEqual(self.answer(extracted=1)[-1], ['tools/lib/port.py: dynamic selection must name a literal module'])

    def test_the_checkout_is_applied_live_to_cached_selections(self):
        self.answer(extracted=len(self.FILES))
        (self.root / 'tools/lib/vendor.py').unlink()
        _, errors = self.answer(extracted=1)  # the deleted file's text (now empty) only; port.py is read from the cache
        self.assertEqual(errors, ['tools/lib/port.py: dynamic selection target absent: vendor'])

    def test_a_corrupt_entry_or_a_new_extractor_is_extracted_again(self):
        expected = self.answer(extracted=len(self.FILES))
        for entry in self.entries():
            entry.write_text('{"declared": ["load"], "invalid": "one"}')
        self.assertEqual(self.answer(extracted=len(self.FILES)), expected)
        self.assertEqual(self.answer(extracted=0), expected)  # the entries were rewritten
        with mock.patch.object(source_facts, 'digest', return_value='another extractor'):
            self.assertEqual(self.answer(extracted=len(self.FILES)), expected)


class Propose(Fixture):
    def test_d067_a_directory_within_the_ceiling_is_one_candidate(self):
        self.write('app/src/small/a.ts', lines(4))
        self.write('app/src/small/b.ts', lines(4))
        self.commit()
        found = unit_map.propose(self.root, self.code())
        self.assertEqual([(row['paths'], row['lines']) for row in found], [(['app/src/**'], 8)])

    def test_d067_a_directory_above_the_ceiling_splits_by_its_subdirectories(self):
        self.write('app/src/one/a.ts', lines(7))
        self.write('app/src/two/a.ts', lines(7))
        self.commit()
        found = unit_map.propose(self.root, self.code())
        self.assertEqual(sorted(tuple(row['paths']) for row in found), [('app/src/one/**',), ('app/src/two/**',)])
        self.assertFalse(any(row['oversize'] for row in found))

    def test_d067_the_ceiling_is_read_from_the_registry_not_written_in_code(self):
        self.write('app/src/one/a.ts', lines(7))
        self.write('app/src/two/a.ts', lines(7))
        self.commit()
        registry = json.loads((self.root / 'config/registry/units.json').read_text())
        registry['properties']['units.size_ceiling']['default'] = 20
        self.write('config/registry/units.json', registry)
        self.assertEqual([row['paths'] for row in unit_map.propose(self.root, self.code())], [['app/src/**']])

    def test_d067_a_flat_group_above_the_ceiling_clusters_by_co_change(self):
        for name in ('a', 'b', 'c', 'd'):
            self.write(f'tools/lib/{name}.py', ''.join(f'V{index} = {index}\n' for index in range(2)))
        self.commit()
        for pair in (('a', 'b'), ('c', 'd'), ('a', 'b'), ('c', 'd')):
            for name in pair:
                self.write(f'tools/lib/{name}.py', (self.root / f'tools/lib/{name}.py').read_text() + '# change\n')
            self.commit()
        found = unit_map.propose(self.root, self.code())
        groups = sorted(sorted(Path(path).stem for path in row['paths']) for row in found)
        self.assertEqual(groups, [['a', 'b'], ['c', 'd']])

    def test_d067_a_candidate_below_the_floor_joins_its_closest_sibling(self):
        self.write('app/src/big/a.ts', lines(6))
        self.write('app/src/tiny/a.ts', lines(1, "import { v0 } from '../big/a';\n"))
        self.write('app/src/other/a.ts', lines(6))
        self.commit()
        found = unit_map.propose(self.root, self.code())
        self.assertIn(['app/src/big/**', 'app/src/tiny/**'], [row['paths'] for row in found])


class Measure(Fixture):
    def setUp(self):
        super().setUp()
        owner = config.get('units.owners', self.root)[0]
        self.write('app/src/one/a.ts', lines(12, "import { v0 } from '../two/a';\n"))
        self.write('app/src/two/a.ts', lines(3))
        self.write('units/one/unit.json', {'id': 'one', 'purpose': 'One.', 'cell': 'app', 'owner': owner,
                                           'paths': ['app/src/one/**']})
        self.write('units/two/unit.json', {'id': 'two', 'purpose': 'Two.', 'cell': 'app', 'owner': owner,
                                           'paths': ['app/src/two/**'],
                                           'budget': {'units.size_ceiling': {'value': 2, 'decision': 'D-067'}}})
        self.commit()

    def test_d067_measure_reports_lines_closure_and_the_budget_of_each_manifest(self):
        rows = {row['id']: row for row in unit_map.measure(self.root, self.code())}
        self.assertEqual((rows['one']['lines'], rows['one']['closure_lines'], rows['one']['oversize']), (12, 15, True))
        self.assertEqual(rows['one']['ceiling'], 10)
        self.assertEqual((rows['two']['ceiling'], rows['two']['oversize']), (2, True))
        self.assertEqual(rows['one']['closure_tokens'], (self.root / 'app/src/one/a.ts').stat().st_size
                         + (self.root / 'app/src/two/a.ts').stat().st_size)
        self.assertEqual(rows['one']['cohesion_percent'], 0)

    def test_d067_emit_publishes_the_measured_step_and_one_unit_oversize_per_unit_above_its_ceiling(self):
        port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), Clock(), config.get('units.event_producer'), 'test')
        unit_map.emit(self.root, pr=7, port=port, sha='a' * 40, premises=['P-04'])
        events = port.read(config.get('forge-events.repo'), 7, strict=True)
        self.assertEqual([event['type'] for event in events], ['engine.step.measured', 'unit.oversize', 'unit.oversize'])
        self.assertEqual(events[0]['payload']['step'], config.get('units.measure_step'))
        self.assertEqual([(e['payload']['unit'], e['payload']['size_lines'], e['payload']['budget_lines'])
                          for e in events[1:]], [('one', 12, 10), ('two', 3, 2)])
        unit_map.emit(self.root, pr=7, port=port, sha='a' * 40, premises=['P-04'])
        self.assertEqual(len(port.read(config.get('forge-events.repo'), 7)), 3)  # idempotent: same ids, no new events

    def test_d067_requires_is_seeded_from_the_measured_imports(self):
        self.assertEqual(unit_map.requires(self.root, self.code()), {'one': ['two']})

    def test_cli_calls_detect_subprocess_scripts_without_polluting_static_requires(self):
        owner = config.get('units.owners', self.root)[0]
        registry = json.loads((self.root / 'config/registry/units.json').read_text())
        registry['properties']['units.production_globs']['default'] = ['app/src/**', 'tools/**', 'scripts/**']
        self.write('config/registry/units.json', registry)
        self.write('scripts/lib/caller.py',
                   "import argparse\nimport subprocess\nfrom pathlib import Path\n"
                   "parser = argparse.ArgumentParser(prog='scripts/ignored')\n"
                   "def go(root):\n"
                   "    subprocess.run(['scripts/target', '--flag'])\n"
                   "    subprocess.Popen([str(Path(root) / 'scripts' / 'other')])\n")
        self.write('scripts/target', '#!/usr/bin/env bash\necho ok\n')
        self.write('scripts/other', '#!/usr/bin/env bash\necho ok\n')
        self.write('scripts/ignored', '#!/usr/bin/env bash\necho ok\n')
        self.write('units/caller/unit.json', {'id': 'caller', 'purpose': 'Caller.', 'cell': 'engine', 'owner': owner,
                                              'paths': ['scripts/lib/caller.py']})
        self.write('units/targets/unit.json', {'id': 'targets', 'purpose': 'Targets.', 'cell': 'engine', 'owner': owner,
                                               'paths': ['scripts/target', 'scripts/other', 'scripts/ignored']})
        self.commit()
        code = self.code()
        self.assertEqual(code.cli_edges['scripts/lib/caller.py'], {'scripts/target', 'scripts/other'})
        self.assertEqual(code.static_edges['scripts/lib/caller.py'], set())
        self.assertEqual(unit_map.cli_requires(self.root, code), {'caller': ['targets']})
        self.assertNotIn('caller', unit_map.requires(self.root, code))
        real_cli = unit_map.cli_requires(ROOT, unit_map.Code(ROOT, log=''))
        self.assertIn('engine-flow', real_cli.get('engine-lane-deliver', []))
        self.assertIn('engine-session-usage', real_cli.get('engine-lane-deliver', []))


if __name__ == '__main__':
    unittest.main()
