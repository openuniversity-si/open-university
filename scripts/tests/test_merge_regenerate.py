"""The regenerate merge driver (CENSO-NO-MANIFESTO 3bis): a committed generated file never reaches a person as a conflict.

Two branches each add a unit; both regenerate a fixture map of unit homes with hand-written keys at the same place,
which is a textual conflict for git (CODEOWNERS was the live such file until D-295). With the driver of .gitattributes the
merge is clean and the merged file is the regeneration of the merged manifests. The map's renderer is a fixture that
declares strip(), as Open University's @ou address map did before it left (OU-DECOUPLE F4 (D-111)), so the driver's
3-way merge of hand-written content stays tested. Fixture git repositories in a temporary directory; no network.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import generate  # noqa: E402
import merge_regenerate  # noqa: E402
import units  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2: the aggregates, not the 900 per-key sources)

PATHS_TARGET = 'demo-paths'  # the fixture's generated map; scripts/lib/generate_<name>.py is RENDERER below
PATHS_FILE = 'products/demo/paths.json'
PREFIX = 'units/'  # the generated keys; every other key of the map is hand-written
ALIAS = 'alias'
RENDERER = '''"""Fixture renderer: each unit's home under a `units/<id>` key of a JSON map; other keys are hand-written."""
import json

import units

PREFIX = %r


def _kept(text):
    return {key: value for key, value in json.loads(text).items() if not key.startswith(PREFIX)}


def _dump(document):
    return json.dumps(document, indent=True, sort_keys=True) + '\\n'


def render(root, target):
    path = target['output']
    if not (root / path).is_file():
        return {}
    document = _kept((root / path).read_text(encoding='utf-8'))
    for unit, manifest in units.manifests(root).items():
        document[PREFIX + unit] = units.home(manifest)
    return {path: _dump(document)}


def strip(root, text):
    return _dump(_kept(text))
''' % PREFIX
LIB = tempfile.TemporaryDirectory()
(Path(LIB.name) / f"generate_{PATHS_TARGET.replace('-', '_')}.py").write_text(RENDERER, encoding='utf-8')
PYTHONPATH = os.environ.get('PYTHONPATH')


def setUpModule():
    sys.path.append(LIB.name)
    os.environ['PYTHONPATH'] = os.pathsep.join(item for item in (PYTHONPATH, LIB.name) if item)  # the driver's runs


def tearDownModule():
    global TEMPLATE
    if TEMPLATE is not None:
        TEMPLATE.cleanup()
        TEMPLATE = None
    sys.path.remove(LIB.name)
    if PYTHONPATH is None:
        os.environ.pop('PYTHONPATH', None)
    else:
        os.environ['PYTHONPATH'] = PYTHONPATH
    LIB.cleanup()


TEMPLATE = None  # the seeded fixture repository, built once and copied per case (the seed is the same for every case)


def template():
    global TEMPLATE
    if TEMPLATE is None:
        TEMPLATE = tempfile.TemporaryDirectory()
        builder = Fixture('seed')
        builder.root = Path(TEMPLATE.name) / 'repo'
        builder.root.mkdir()
        builder.seed()
    return Path(TEMPLATE.name) / 'repo'


class Fixture(unittest.TestCase):
    def setUp(self):
        config.pin_store('file')
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'repo'
        shutil.copytree(template(), self.root, symlinks=True)

    def seed(self):
        fixture_copy.registry(self.root)
        shutil.copytree(ROOT / 'contracts/units', self.root / 'contracts/units')
        registry = self.root / 'config/registry/generate.json'
        document = json.loads(registry.read_text(encoding='utf-8'))
        document['properties']['generate.targets']['default'].append({
            'name': PATHS_TARGET, 'description': 'A fixture map of unit homes with hand-written keys.',
            'sources': ['units/*/unit.json'], 'output': PATHS_FILE, 'committed': True, 'enabled': True,
            'requires': 'units/*/unit.json'})
        registry.write_text(json.dumps(document, indent=1), encoding='utf-8')
        attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        self.write('.gitattributes', f'{attributes}{PATHS_FILE} merge={merge_regenerate.wiring("merge_driver_name")}\n')
        self.write(PATHS_FILE, json.dumps({ALIAS: './src/*'}) + '\n')
        self.unit('demo-base', 'engine-lane', 'products/demo/src/base')
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'fixture')
        self.regenerate_and_commit('base')

    def tearDown(self):
        units.reset()
        self.tmp.cleanup()

    def git(self, *args, check=True):
        return subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True, check=check)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def unit(self, unit, lane, folder):
        manifest = {'id': unit, 'purpose': 'A fixture unit.', 'cell': 'engine', 'owner': lane, 'paths': [f'{folder}/**']}
        self.write(f'units/{unit}/unit.json', json.dumps(manifest, indent=1) + '\n')
        self.write(f'{folder}/index.ts', 'export {};\n')

    def regenerate_and_commit(self, message):
        units.reset()
        self.git('add', '-A')
        for name in (PATHS_TARGET,):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(generate.main([name, '--root', str(self.root)]), 0)
        self.git('add', '-A')
        self.git('commit', '-q', '-m', message)

    def branch(self, name, unit, lane, folder, alias=None):
        self.git('checkout', '-q', '-b', name, 'main')
        self.unit(unit, lane, folder)
        if alias:
            path = self.root / PATHS_FILE
            document = json.loads(path.read_text(encoding='utf-8'))
            document[ALIAS] = alias
            path.write_text(json.dumps(document), encoding='utf-8')
        self.regenerate_and_commit(name)

    def install(self):
        self.git('config', f'merge.{merge_regenerate.wiring("merge_driver_name")}.driver',
                 f'{ROOT}/scripts/merge-regenerate %O %A %B %P')

    def merge_both(self, left_alias=None, right_alias=None):
        self.branch('left', 'demo-left', 'engine-lane', 'products/demo/src/left', left_alias)
        self.branch('right', 'demo-right', 'tooling-lane', 'products/demo/src/right', right_alias)
        self.git('checkout', '-q', 'left')
        return self.git('merge', '--no-edit', 'right', check=False)


class Driver(Fixture):
    def test_without_the_driver_the_two_owners_collide(self):
        merged = self.merge_both()
        self.assertNotEqual(merged.returncode, 0)
        self.assertIn(f'CONFLICT (content): Merge conflict in {PATHS_FILE}', merged.stdout)

    def test_with_the_driver_the_merge_is_clean_and_equals_the_regeneration(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(merge_regenerate.main(['install', '--root', str(self.root)]), 0)
        self.assertIn('scripts/merge-regenerate %O %A %B %P', self.git('config', 'merge.regenerate.driver').stdout)
        self.install()
        merged = self.merge_both()
        self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
        homes = json.loads((self.root / PATHS_FILE).read_text(encoding='utf-8'))
        self.assertEqual(homes[f'{PREFIX}demo-left'], 'products/demo/src/left')
        self.assertEqual(homes[f'{PREFIX}demo-right'], 'products/demo/src/right')
        units.reset()
        self.assertEqual(generate.drift(self.root, [PATHS_TARGET]), [])
        self.assertEqual(self.git('worktree', 'list').stdout.count('\n'), 1)  # the throwaway worktree is gone

    def test_a_hand_written_key_changed_on_one_side_survives_the_regeneration(self):
        self.install()
        merged = self.merge_both(right_alias='./source/*')
        self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
        homes = json.loads((self.root / PATHS_FILE).read_text(encoding='utf-8'))
        self.assertEqual(homes[ALIAS], './source/*')
        self.assertIn(f'{PREFIX}demo-left', homes)

    def test_a_hand_written_key_changed_on_both_sides_stays_a_conflict(self):
        self.install()
        merged = self.merge_both(left_alias='./left/*', right_alias='./right/*')
        self.assertNotEqual(merged.returncode, 0)
        self.assertIn(f'Merge conflict in {PATHS_FILE}', merged.stdout)

    def test_a_conflict_in_the_sources_stays_a_conflict(self):
        self.install()
        self.branch('left', 'demo-same', 'engine-lane', 'products/demo/src/left')
        self.branch('right', 'demo-same', 'tooling-lane', 'products/demo/src/right')
        self.git('checkout', '-q', 'left')
        merged = self.git('merge', '--no-edit', 'right', check=False)
        self.assertNotEqual(merged.returncode, 0)
        self.assertIn('units/demo-same/unit.json', merged.stdout)

    def test_every_committed_one_file_target_is_named_in_gitattributes(self):
        attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        name = merge_regenerate.wiring('merge_driver_name')
        for target in generate.targets(ROOT).values():
            if target['committed'] and Path(target['output']).suffix:
                self.assertIn(f'{target["output"]} merge={name}\n', attributes)

    def test_the_other_head_is_the_one_githead_variable(self):
        self.assertEqual(merge_regenerate.their_head({'GITHEAD_abc': 'right', 'HOME': os.sep}), 'abc')
        self.assertIsNone(merge_regenerate.their_head({'HOME': os.sep}))
        self.assertIsNone(merge_regenerate.their_head({'GITHEAD_abc': 'a', 'GITHEAD_def': 'b'}))


LANE_TOOLS = 'units/engine-lane-tools/unit.json'
KEY_FILE = 'config/registry/gate-pin/gate-pin.enabled.json'


class HandWrittenJson(Fixture):
    """03/11: lanes conflicted at least four times (about 120 s each) appending a `requires` entry after the last line of
    engine-lane-tools' manifest, and twice appending a reader to one key's `x-readers`. Two branches each add a
    different entry at that same place; the driver merges them as JSON."""

    def edit(self, name, change):
        path = self.root / name
        text = path.read_text(encoding='utf-8')
        document = json.loads(text)
        change(document)
        path.write_text(json.dumps(document, **merge_regenerate._json_style(text)) + '\n', encoding='utf-8')

    def two_branches(self, name, left, right):
        self.write(name, (ROOT / name).read_text(encoding='utf-8'))
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'the shared file')
        for branch, change in (('left', left), ('right', right)):
            self.git('checkout', '-q', '-b', branch, 'main')
            self.edit(name, change)
            self.git('commit', '-q', '-am', branch)
        self.git('checkout', '-q', 'left')
        return self.git('merge', '--no-edit', 'right', check=False)

    def requires(self, unit, version='^1'):
        return lambda document: document['requires'].__setitem__(unit, version)

    def test_without_the_driver_two_requires_appends_collide(self):
        merged = self.two_branches(LANE_TOOLS, self.requires('engine-units'), self.requires('engine-push-guard'))
        self.assertIn(f'Merge conflict in {LANE_TOOLS}', merged.stdout)

    def test_two_requires_appends_merge_clean_and_sorted(self):
        self.install()
        merged = self.two_branches(LANE_TOOLS, self.requires('engine-units'), self.requires('engine-push-guard'))
        self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
        text = (self.root / LANE_TOOLS).read_text(encoding='utf-8')
        requires = json.loads(text)['requires']
        self.assertEqual(list(requires), sorted({*json.loads((ROOT / LANE_TOOLS).read_text())['requires'],
                                                 'engine-units', 'engine-push-guard'}))
        self.assertIsNotNone(merge_regenerate._json_style(text))  # written back in the file's own style
        self.assertEqual(self.git('status', '--porcelain').stdout, '')

    def test_two_readers_appended_to_one_key_merge_clean(self):
        self.install()
        merged = self.two_branches(KEY_FILE, lambda d: d['x-readers'].append('scripts/lib/zeta.py'),
                                   lambda d: d['x-readers'].append('scripts/lib/zulu.py'))
        self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
        readers = json.loads((self.root / KEY_FILE).read_text(encoding='utf-8'))['x-readers']
        self.assertEqual(readers, sorted({*json.loads((ROOT / KEY_FILE).read_text())['x-readers'],
                                          'scripts/lib/zeta.py', 'scripts/lib/zulu.py'}))

    def test_the_same_requires_at_two_versions_stays_a_conflict(self):
        self.install()
        merged = self.two_branches(LANE_TOOLS, self.requires('engine-units', '^1'), self.requires('engine-units', '>=1'))
        self.assertNotEqual(merged.returncode, 0)
        self.assertIn('<<<<<<<', (self.root / LANE_TOOLS).read_text(encoding='utf-8'))

    def test_the_structural_merge_keeps_a_removal_and_refuses_what_it_cannot_write_back(self):
        base, ours, theirs = ({'r': ['a', 'b'], 'k': 'x'}, {'r': ['a', 'b', 'c'], 'k': 'x'}, {'r': ['b'], 'k': 'y'})
        self.assertEqual(merge_regenerate._merge_value(base, ours, theirs), {'k': 'y', 'r': ['b', 'c']})
        with self.assertRaises(merge_regenerate.Clash):
            merge_regenerate._merge_value({'k': [{}]}, {'k': [{'a': 1}]}, {'k': [{'b': 1}]})
        self.assertIsNone(merge_regenerate._json_style('{"a":1}'))


class Union(unittest.TestCase):
    def test_two_appends_to_gitattributes_merge_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args):
                return subprocess.run(['git', '-C', tmp, '-c', 'user.email=f@example.invalid', '-c', 'user.name=f',
                                       *args], capture_output=True, text=True, check=True)
            attributes = Path(tmp) / '.gitattributes'
            base = (ROOT / '.gitattributes').read_text(encoding='utf-8')
            attributes.write_text(base, encoding='utf-8')
            git('init', '-q', '-b', 'main')
            git('add', '.')
            git('commit', '-qm', 'base')
            for branch, line in (('left', 'a merge=union'), ('right', 'b merge=union')):
                git('checkout', '-qb', branch, 'main')
                attributes.write_text(f'{base}{line}\n', encoding='utf-8')
                git('commit', '-qam', branch)
            git('merge', '-q', '--no-edit', 'left')
            self.assertEqual(attributes.read_text(encoding='utf-8'), f'{base}b merge=union\na merge=union\n')

    def test_two_rows_added_at_the_same_place_of_the_aws_board_merge_clean(self):
        # DOCS-UNION: every PR adds its row before the same line of the board; BRANCH-MERGE said conflict on #648
        with tempfile.TemporaryDirectory() as tmp:
            def git(*args):
                return subprocess.run(['git', '-C', tmp, '-c', 'user.email=f@example.invalid', '-c', 'user.name=f',
                                       *args], capture_output=True, text=True, check=True)
            board = Path(tmp) / 'docs' / 'operations' / 'aws-pendencias.md'
            board.parent.mkdir(parents=True)
            (Path(tmp) / '.gitattributes').write_text((ROOT / '.gitattributes').read_text(encoding='utf-8'), encoding='utf-8')
            base = '| item | state |\n| ANCHOR | x |\n'
            board.write_text(base, encoding='utf-8')
            git('init', '-q', '-b', 'main')
            git('add', '.')
            git('commit', '-qm', 'base')
            for branch in ('left', 'right'):
                git('checkout', '-qb', branch, 'main')
                board.write_text(base.replace('| ANCHOR', f'| {branch} | y |\n| ANCHOR'), encoding='utf-8')
                git('commit', '-qam', branch)
            git('merge', '-q', '--no-edit', 'left')
            rows = board.read_text(encoding='utf-8').splitlines()
            self.assertEqual(sorted(rows[1:3]), ['| left | y |', '| right | y |'])
            self.assertEqual(rows[3], '| ANCHOR | x |')


if __name__ == '__main__':
    unittest.main()
