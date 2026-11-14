"""The census of each unit (CENSO-NO-MANIFESTO): units/<id>/census.jsonl, its fold, its check and its writer.

A record is append-only, sealed by a digest chain and written by scripts/census, so a hand edit is a check failure;
every live entry belongs to exactly one unit; the old per-area files are merged until migrated, never recreated.
Fixture git repositories in a temporary directory; no network, no clock (the date is passed in).
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import census  # noqa: E402
import generate  # noqa: E402
import generate_census  # noqa: E402
import units  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

DAY = '2026-10-28'
NUMBER_SEVEN = 'number "7"'
URL_KEY = 'string "left"'
SCANNER = ['scanner', '--list']


def tearDownModule():
    if Fixture.template is not None:
        Fixture.template.cleanup()
        Fixture.template = None


class Fixture(unittest.TestCase):
    """A repository with two units of one census area (the folder scripts) and one of another (the folder alpha)."""

    template = None  # the committed fixture repository, built once per run and copied for each test

    def build_template(self):
        Fixture.template = tempfile.TemporaryDirectory()
        self.root = Path(Fixture.template.name)
        fixture_copy.registry(self.root)
        shutil.copytree(ROOT / 'contracts/units', self.root / 'contracts/units')
        self.unit('left-tool', ['products/demo/scripts/left.ts'])
        self.unit('right-tool', ['products/demo/scripts/right.ts'])
        self.unit('alpha-domain', ['products/demo/src/alpha/**'])
        self.git('init', '-q', '--template=', '-b', 'main')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'fixture')
        self.commit('base')

    def setUp(self):
        if Fixture.template is None:
            self.build_template()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(Fixture.template.name, self.root, symlinks=True, dirs_exist_ok=True)
        units.reset()

    def tearDown(self):
        units.reset()
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, text=True, check=True).stdout

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-q', '--allow-empty', '-m', message)
        return self.git('rev-parse', 'HEAD').strip()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def unit(self, unit, paths):
        manifest = {'id': unit, 'purpose': 'A fixture unit.', 'cell': 'engine', 'owner': 'engine-lane', 'paths': paths}
        self.write(f'units/{unit}/unit.json', json.dumps(manifest, indent=1) + '\n')

    def legacy(self, census_name, area, entries):
        folder = census.setting(f'{census_name}_legacy_dir', self.root)
        self.write(f'{folder}/{area}.json', json.dumps({'description': 'old', census.LEGACY_KEYS[census_name]: entries}, indent=1))

    def add(self, unit, path, entry, census_name=census.BASELINE, op=census.ADD):
        return census.append(self.root, unit, [{'op': op, 'census': census_name, 'path': path, 'entry': entry,
                                                'why': 'fixture', 'by': 'fixture'}], at=DAY)

    def record(self, unit):
        return census.record_path(self.root, unit)

    def errors(self, base=None):
        return '\n'.join(census.check(self.root, base))


class Record(Fixture):
    def test_an_appended_record_folds_and_checks_clean(self):
        self.add('left-tool', 'products/demo/scripts/left.ts', {NUMBER_SEVEN: 1})
        self.add('left-tool', 'products/demo/scripts/left.ts', {NUMBER_SEVEN: 1, URL_KEY: 1}, op=census.SET)
        self.add('right-tool', 'products/demo/scripts/right.ts', {'domains': ['tools'], 'holds': 'Right keys.'}, census.CATALOG)
        self.assertEqual(self.errors(), '')
        self.assertEqual(census.entries(self.root, census.BASELINE),
                         {'products/demo/scripts/left.ts': {NUMBER_SEVEN: 1, URL_KEY: 1}})
        self.assertEqual(list(census.entries(self.root, census.CATALOG)), ['products/demo/scripts/right.ts'])
        self.assertEqual(list(census.areas(self.root, census.BASELINE)), ['scripts'])

    def test_a_remove_takes_the_entry_out_and_keeps_the_history(self):
        self.add('left-tool', 'products/demo/scripts/left.ts', {NUMBER_SEVEN: 1})
        census.append(self.root, 'left-tool', [{'op': census.REMOVE, 'census': census.BASELINE,
                                                 'path': 'products/demo/scripts/left.ts', 'why': 'gone', 'by': 'fixture'}], at=DAY)
        self.assertEqual(census.entries(self.root, census.BASELINE), {})
        self.assertEqual([event['op'] for event in census.records(self.root)['left-tool']], [census.ADD, census.REMOVE])
        self.assertEqual(self.errors(), '')

    def test_the_writer_refuses_a_fold_that_does_not_hold(self):
        self.add('left-tool', 'products/demo/scripts/left.ts', {NUMBER_SEVEN: 1})
        with self.assertRaisesRegex(census.CensusError, 'already live; a change is a set'):
            self.add('left-tool', 'products/demo/scripts/left.ts', {NUMBER_SEVEN: 1})
        with self.assertRaisesRegex(census.CensusError, 'no live entry to set'):
            self.add('right-tool', 'products/demo/scripts/right.ts', {NUMBER_SEVEN: 1}, op=census.SET)


class HandEdit(Fixture):
    def setUp(self):
        super().setUp()
        self.add('left-tool', 'products/demo/scripts/left.ts', {NUMBER_SEVEN: 1})

    def edit(self, change):
        path = self.record('left-tool')
        events = census.read_trail(path.read_text(encoding='utf-8'))
        change(events)
        path.write_text(''.join(json.dumps(event, sort_keys=True) + '\n' for event in events), encoding='utf-8')

    def test_a_count_changed_by_hand_breaks_the_digest(self):
        self.edit(lambda events: events[0]['entry'].update({NUMBER_SEVEN: 1 + 1}))
        self.assertIn('was edited (its digest differs)', self.errors())
        self.assertIn(census.FIX, self.errors())

    def test_an_event_appended_by_hand_breaks_the_chain(self):
        self.edit(lambda events: events.append({**events[0], 'n': len(events) + 1, 'op': census.SET}))
        self.assertIn('was edited (its digest differs)', self.errors())

    def test_a_reformatted_record_is_not_the_writer_s_text(self):
        path = self.record('left-tool')
        path.write_text(json.dumps(census.read_trail(path.read_text(encoding='utf-8'))[0], indent=1) + '\n', encoding='utf-8')
        self.assertIn('line', self.errors())  # a multi-line JSON object is not one event per line
        path.write_text(path.read_text(encoding='utf-8').replace('\n', ' ').strip() + '\n', encoding='utf-8')
        self.assertIn("not the writer's canonical text (a hand edit)", self.errors())

    def test_a_record_must_extend_the_base_s_events(self):
        self.add('left-tool', 'products/demo/scripts/left.ts', {NUMBER_SEVEN: 1, URL_KEY: 1}, op=census.SET)
        base = self.commit('two events')
        path = self.record('left-tool')
        path.write_text(path.read_text(encoding='utf-8').splitlines(keepends=True)[0], encoding='utf-8')
        self.assertIn('are not its first', self.errors(base))
        self.assertNotIn('are not its first', self.errors())  # without a base only the record itself is judged

    def test_a_record_of_a_folder_with_no_manifest_is_refused(self):
        self.write('units/ghost/census.jsonl', self.record('left-tool').read_text(encoding='utf-8'))
        self.assertIn('no unit manifest units/ghost/unit.json', self.errors())


class Ownership(Fixture):
    def test_the_writer_refuses_a_path_of_no_unit_or_of_two(self):
        with self.assertRaisesRegex(census.CensusError, 'belongs to no unit'):
            census.owner(self.root, 'products/demo/scripts/nobody.ts')
        self.unit('right-twin', ['products/demo/scripts/right.ts'])
        units.reset()
        with self.assertRaisesRegex(census.CensusError, 'right-tool, right-twin'):
            census.owner(self.root, 'products/demo/scripts/right.ts')

    def test_a_live_entry_in_another_unit_s_record_is_refused(self):
        self.add('left-tool', 'products/demo/scripts/right.ts', {NUMBER_SEVEN: 1})
        self.assertIn('baseline entry products/demo/scripts/right.ts belongs to right-tool, not left-tool', self.errors())

    def test_an_entry_whose_path_left_every_unit_is_refused(self):
        self.add('alpha-domain', 'products/demo/src/alpha/view.ts', {NUMBER_SEVEN: 1})
        self.unit('alpha-domain', ['products/demo/src/alpha/other.ts'])
        units.reset()
        self.assertIn('belongs to no unit, not alpha-domain', self.errors())


class Legacy(Fixture):
    def setUp(self):
        super().setUp()
        self.legacy(census.BASELINE, 'scripts', {'products/demo/scripts/left.ts': {NUMBER_SEVEN: 1},
                                                 'products/demo/scripts/right.ts': {URL_KEY: 1}})
        self.legacy(census.CATALOG, 'alpha', {'products/demo/src/alpha/keys.ts': {'domains': ['alpha'], 'holds': 'Keys.'}})
        self.base = self.commit('old per-area files')

    def test_the_readers_merge_the_old_files_while_they_last(self):
        self.add('alpha-domain', 'products/demo/src/alpha/view.ts', {NUMBER_SEVEN: 1})
        self.assertEqual(sorted(census.entries(self.root, census.BASELINE)),
                         ['products/demo/scripts/left.ts', 'products/demo/scripts/right.ts', 'products/demo/src/alpha/view.ts'])
        self.assertEqual(list(census.areas(self.root, census.BASELINE)), ['alpha', 'scripts'])
        self.assertEqual(self.errors(self.base), '')

    def test_a_path_held_in_both_forms_is_refused(self):
        self.add('left-tool', 'products/demo/scripts/left.ts', {NUMBER_SEVEN: 1})
        self.assertIn('products/demo/scripts/left.ts is also in the record of left-tool', self.errors(self.base))

    def test_a_per_area_file_the_base_does_not_have_is_refused(self):
        self.legacy(census.BASELINE, 'alpha', {'products/demo/src/alpha/view.ts': {NUMBER_SEVEN: 1}})
        self.assertIn('absolute-literals-baseline/alpha.json: a per-area file is a derived view', self.errors(self.base))

    def test_an_old_entry_of_no_unit_is_named_before_the_migration_needs_it(self):
        self.legacy(census.BASELINE, 'scripts', {'products/demo/scripts/nobody.ts': {NUMBER_SEVEN: 1}})
        self.assertIn('products/demo/scripts/nobody.ts belongs to no unit', self.errors(self.base))

    def test_migrate_moves_every_entry_to_its_unit_and_deletes_the_file(self):
        before = {name: census.entries(self.root, name) for name in census.CENSUSES}
        lines = census.command_migrate(self.root, SimpleNamespace(area='scripts', why='move', actor='fixture'))
        self.assertIn('baseline scripts: 1 entry -> left-tool', lines)
        self.assertIn('baseline scripts: 1 entry -> right-tool', lines)
        self.assertFalse((self.root / census.setting('baseline_legacy_dir', self.root) / 'scripts.json').exists())
        census.command_migrate(self.root, SimpleNamespace(area='alpha', why='move', actor='fixture'))
        self.assertEqual({name: census.entries(self.root, name) for name in census.CENSUSES}, before)  # nothing lost
        self.assertEqual(self.errors(self.base), '')
        with self.assertRaisesRegex(census.CensusError, 'no per-area file named scripts.json'):
            census.command_migrate(self.root, SimpleNamespace(area='scripts', why='again', actor='fixture'))


class Writer(Fixture):
    def args(self, **values):
        defaults = {'why': 'fixture', 'actor': 'fixture', 'unit': None, 'catalog': False, 'replace': False,
                    'domain': None, 'holds': None, 'builder': None, 'generated_from': None, 'census': None,
                    'paths': False}
        return SimpleNamespace(**{**defaults, **values})

    def scanned(self, counts):
        return mock.patch.object(census, 'scan', return_value=counts)

    def scanner(self):
        """A product's declared scanner (census.scan_argv is empty in the engine's registry)."""
        held = census.setting
        return mock.patch.object(census, 'setting', side_effect=lambda name, root=None:
                                 SCANNER if name == 'scan_argv' else held(name, root))

    def test_add_reads_the_counts_from_the_scan_and_never_from_a_person(self):
        with self.scanned({'products/demo/scripts/left.ts': {NUMBER_SEVEN: 1}}):
            census.command_add(self.root, self.args(path='products/demo/scripts/left.ts'))
            with self.assertRaisesRegex(census.CensusError, 'finds no offender in products/demo/scripts/right.ts'):
                census.command_add(self.root, self.args(path='products/demo/scripts/right.ts'))
            with self.assertRaisesRegex(census.CensusError, 'pass --replace'):
                census.command_add(self.root, self.args(path='products/demo/scripts/left.ts'))
        event = census.records(self.root)['left-tool'][0]
        self.assertEqual((event['entry'], event['by'], event['why']), ({NUMBER_SEVEN: 1}, 'fixture', 'fixture'))

    def test_sync_with_the_default_scan_argv_measures_the_engines_own_literals(self):
        """census.scan_argv is empty by default: sync reads the engine's literal census, keyed as a scanner line keys it."""
        self.assertEqual(census.setting('scan_argv', self.root), [])
        self.unit('demo-engine', ['scripts/lib/demo_census.py'])
        text = 'WAIT = 4321\nAGAIN = 4321\n'
        self.write('scripts/lib/demo_census.py', text)
        self.commit('a scanned engine file')
        units.reset()
        self.assertEqual(census.scan(self.root)['scripts/lib/demo_census.py'], {'number "4321"': text.count('4321')})
        self.assertIn('add baseline scripts/lib/demo_census.py (demo-engine)', census.command_sync(self.root, self.args()))
        self.assertEqual(census.entries(self.root)['scripts/lib/demo_census.py'], {'number "4321"': text.count('4321')})
        self.write('scripts/lib/demo_census.py', 'WAIT = 4321\n')
        self.assertIn('set baseline scripts/lib/demo_census.py (demo-engine)', census.command_sync(self.root, self.args()))
        self.assertEqual(census.entries(self.root)['scripts/lib/demo_census.py'], {'number "4321"': 1})
        self.assertEqual(self.errors(), '')

    def test_a_catalog_entry_takes_its_domains_and_its_sentence(self):
        census.command_add(self.root, self.args(path='products/demo/src/alpha/keys.ts', catalog=True, domain=['alpha'],
                                                holds='The alpha keys.', builder=['zod']))
        self.assertEqual(census.entries(self.root, census.CATALOG)['products/demo/src/alpha/keys.ts'],
                         {'domains': ['alpha'], 'holds': 'The alpha keys.', 'builders': ['zod']})
        with self.assertRaisesRegex(census.CensusError, 'needs --domain and --holds'):
            census.command_add(self.root, self.args(path='products/demo/scripts/left.ts', catalog=True))
        self.assertEqual(census.command_list(self.root, self.args(census=census.CATALOG)),
                         ['alpha-domain\tcatalog\tproducts/demo/src/alpha/keys.ts'])

    def test_sync_sets_adds_and_removes_from_the_scan(self):
        self.add('left-tool', 'products/demo/scripts/left.ts', {NUMBER_SEVEN: 1, URL_KEY: 1})
        self.add('alpha-domain', 'products/demo/src/alpha/gone.ts', {NUMBER_SEVEN: 1})
        with self.scanned({'products/demo/scripts/left.ts': {NUMBER_SEVEN: 1}, 'products/demo/scripts/right.ts': {URL_KEY: 1}}):
            lines = census.command_sync(self.root, self.args())
        self.assertEqual(lines, ['set baseline products/demo/scripts/left.ts (left-tool)',
                                 'add baseline products/demo/scripts/right.ts (right-tool)',
                                 'remove baseline products/demo/src/alpha/gone.ts (alpha-domain)'])
        self.assertEqual(census.entries(self.root, census.BASELINE),
                         {'products/demo/scripts/left.ts': {NUMBER_SEVEN: 1}, 'products/demo/scripts/right.ts': {URL_KEY: 1}})
        with self.scanned({'products/demo/scripts/left.ts': {NUMBER_SEVEN: 1}, 'products/demo/scripts/right.ts': {URL_KEY: 1}}):
            self.assertEqual(census.command_sync(self.root, self.args()), ['in sync'])
        self.assertEqual(self.errors(), '')

    def test_show_prints_the_live_entry_and_its_history(self):
        with self.scanned({'products/demo/scripts/left.ts': {NUMBER_SEVEN: 1}}):
            census.command_add(self.root, self.args(path='products/demo/scripts/left.ts', why='first'))
        shown = census.command_show(self.root, self.args(path='products/demo/scripts/left.ts'))
        self.assertTrue(shown[0].startswith('baseline\tleft-tool\t'))
        self.assertIn('\tfixture\tadd\tfirst', shown[1])

    def test_the_scan_is_parsed_from_the_offender_lines(self):
        printed = ('products/demo/scripts/left.ts:3: number "7" (magic number)\n'
                   'products/demo/scripts/left.ts:9: number "7" (magic number)\n'
                   'products/demo/scripts/left.ts:4: string "a (b) c" (prose)\n')
        done = subprocess.CompletedProcess([], 0, printed, '')
        with self.scanner(), mock.patch.object(census.subprocess, 'run', return_value=done) as ran:
            self.assertEqual(census.scan(self.root), {'products/demo/scripts/left.ts': {NUMBER_SEVEN: 1 + 1, 'string "a (b) c"': 1}})
        self.assertEqual(ran.call_args.args[0], SCANNER)
        with self.scanner(), mock.patch.object(census.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'noise\n', '')):
            with self.assertRaisesRegex(census.CensusError, 'not an offender: noise'):
                census.scan(self.root)

    def test_no_declared_scanner_runs_none_and_measures_with_the_engine_scan(self):
        """OU-DECOUPLE F5 (D-113): the registry declares no scanner, so none is run; the engine's own scan measures, and a
        file it does not scan has no count to allow (none is invented)."""
        with mock.patch.object(census, 'engine_scan', return_value={}) as measured, \
                mock.patch.object(census.subprocess, 'run') as ran:
            with self.assertRaisesRegex(census.CensusError, 'finds no offender in products/demo/scripts/left.ts'):
                census.command_add(self.root, self.args(path='products/demo/scripts/left.ts'))
        ran.assert_not_called()
        measured.assert_called_once_with(self.root)

    def test_the_command_line_reports_a_refusal_and_exits_1(self):
        self.assertEqual(census.main(['--root', str(self.root), 'remove', 'products/demo/scripts/left.ts', '--why', 'x']), 1)
        self.assertEqual(census.main(['--root', str(self.root), 'check']), 0)


class Neighbours(Fixture):
    """Step 5 of CENSO-NO-MANIFESTO: two units of one census area write their entries on two branches."""

    def branch(self, name, unit, path, entry):
        self.git('checkout', '-q', '-b', name, 'main')
        self.add(unit, path, entry)
        self.commit(name)

    def merge(self, other):
        self.git('checkout', '-q', 'main')
        self.git('merge', '-q', '--no-edit', 'left')
        return subprocess.run(['git', '-C', str(self.root), 'merge', '--no-edit', other], capture_output=True, text=True)

    def test_two_units_of_one_area_never_conflict_and_the_view_holds_both(self):
        self.branch('left', 'left-tool', 'products/demo/scripts/left.ts', {NUMBER_SEVEN: 1})
        self.branch('right', 'right-tool', 'products/demo/scripts/right.ts', {URL_KEY: 1})
        merged = self.merge('right')
        self.assertEqual(merged.returncode, 0, merged.stdout + merged.stderr)
        self.assertEqual(self.errors('left'), '')
        view = json.loads(generate_census.render(self.root, None)['scripts/lib/absolute-literals-baseline/scripts.json'])
        self.assertEqual(view['files'], {'products/demo/scripts/left.ts': {NUMBER_SEVEN: 1}, 'products/demo/scripts/right.ts': {URL_KEY: 1}})

    def test_the_same_two_writes_in_one_shared_area_file_collide(self):
        """The accident the records remove: both units append to scripts.json at the same place."""
        folder = census.setting('baseline_legacy_dir', self.root)
        self.legacy(census.BASELINE, 'scripts', {'products/demo/scripts/first.ts': {NUMBER_SEVEN: 1}})
        self.commit('shared area file')
        for name, path in (('left', 'products/demo/scripts/left.ts'), ('right', 'products/demo/scripts/right.ts')):
            self.git('checkout', '-q', '-b', name, 'main')
            self.legacy(census.BASELINE, 'scripts', {'products/demo/scripts/first.ts': {NUMBER_SEVEN: 1}, path: {URL_KEY: 1}})
            self.commit(name)
        merged = self.merge('right')
        self.assertNotEqual(merged.returncode, 0)
        self.assertIn(f'CONFLICT (content): Merge conflict in {folder}/scripts.json', merged.stdout)

    def test_the_view_is_a_target_never_committed(self):
        target = generate.targets(self.root)['census']
        self.assertFalse(target['committed'])
        self.add('alpha-domain', 'products/demo/src/alpha/keys.ts', {'domains': ['alpha'], 'holds': 'Keys.'}, census.CATALOG)
        rendered = generate_census.render(self.root, target)
        self.assertEqual(sorted(rendered), ['scripts/lib/literal-catalogs/alpha.json'])
        document = json.loads(rendered['scripts/lib/literal-catalogs/alpha.json'])
        self.assertEqual(document['description'], census.setting('catalog_view_description', self.root))


if __name__ == '__main__':
    unittest.main()
