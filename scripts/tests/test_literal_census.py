"""The census of unregistered engine literals (LT1): what it finds, what it leaves, and that every exception is a
registry entry. The source texts of the cases live in data (fixtures/unregistered-literals/cases.json), so this file
spells none of them.

Fixture git checkouts in a temporary directory; no network, no clock.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import literal_census  # noqa: E402

CASES = json.loads((ROOT / 'scripts/tests/fixtures/unregistered-literals/cases.json').read_text())
COPIED = ('contracts/config/registry.v1.json', 'contracts/events/config.changed.v1.json', 'config/registry/config.json',
          'config/registry/literals.json', 'config/registry/production.json')


class Checkout(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in COPIED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        for name in COPIED[2:]:
            policy = self.registry(name)
            for item in policy['properties'].values():
                item['x-readers'] = []  # the readers live in the real checkout, not in the fixture
            if name.endswith('config.json'):
                policy['properties']['config.store_adapter']['default'] = 'file'  # the fixture's own log, never the forge
            if name.endswith('production.json'):
                # OU-DECOUPLE F4 (D-111): the repository forbids no entrypoint now; the fixture names one.
                policy['properties']['production.forbidden_entrypoints']['default'] = ['demo-deploy']
            self.write(name, policy)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def registry(self, name):
        return json.loads((self.root / name).read_text())

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))

    def commit(self):
        git = ['git', '-C', str(self.root), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid']
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-qm', 'fixture'], check=True)
        return subprocess.run(git + ['rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()

    def found(self, case):
        rules = literal_census.Census(self.root)
        if case['suffix'] == '.py':
            hits = literal_census.python_literals(case['source'], rules)
        else:
            hits = literal_census.text_literals(case['source'], rules, shell=case['suffix'] == '.sh')
        return [[kind, value] for _, kind, value in hits]


class Census(Checkout):
    def test_lt1_each_refused_case_is_found(self):
        for case in CASES['refused']:
            with self.subTest(case['name']):
                self.assertEqual(self.found(case), case['found'])

    def test_lt1_each_allowed_case_is_not_found(self):
        for case in CASES['allowed']:
            with self.subTest(case['name']):
                self.assertEqual(self.found(case), [])

    def test_lt1_the_exceptions_are_registry_entries_not_code(self):
        refused = {case['name']: case for case in CASES['refused']}
        policy = self.registry('config/registry/literals.json')
        policy['properties']['literals.allowed_numbers']['default'].append(refused['a python number']['found'][0][1])
        policy['properties']['literals.allowed_values']['default'].append(refused['an absolute path']['found'][0][1])
        policy['properties']['literals.patterns']['default'] = [
            item for item in policy['properties']['literals.patterns']['default'] if item['kind'] != 'url']
        self.write('config/registry/literals.json', policy)
        for name in ('a python number', 'an absolute path', 'a url'):
            with self.subTest(name):
                self.assertEqual(self.found(refused[name]), [])

    def test_lt1_the_census_counts_per_area_file_kind_and_value(self):
        case = CASES['refused'][0]
        self.write('scripts/lib/lane.py', case['source'] * 2)
        self.write('scripts/lib/clean.py', CASES['allowed'][0]['source'])
        self.commit()
        unowned = config.get('literals.unowned_area', self.root)
        found = literal_census.key(*case['found'][0])
        self.assertEqual(literal_census.census(self.root), {unowned: {'scripts/lib/lane.py': {found: 2}}})

    def default_ref(self, ref):
        policy = self.registry('config/registry/literals.json')
        policy['properties']['literals.base_ref']['default'] = ref
        self.write('config/registry/literals.json', policy)

    def test_lt1_the_census_is_computed_never_stored(self):
        self.write('scripts/lib/clean.py', CASES['allowed'][0]['source'])
        self.default_ref(self.commit())  # without --base, the merge-base with literals.base_ref
        case = CASES['refused'][0]
        self.write('scripts/lib/lane.py', case['source'])
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        self.assertIn('at scripts/lib/lane.py:1;', literal_census.check(self.root)[0][0])
        self.assertEqual(sorted(path.name for path in (self.root / 'scripts/lib').iterdir()), ['clean.py', 'lane.py'])
        with self.assertRaises(SystemExit):
            literal_census.main(['--write'])
        self.write('scripts/lib/lane.py', CASES['allowed'][0]['source'])
        self.assertEqual(literal_census.check(self.root), ([], []))

    def test_f96_the_old_baseline_lists_still_allow_their_counts(self):
        case = CASES['refused'][0]
        found = literal_census.key(*case['found'][0])
        self.write('scripts/lib/clean.py', CASES['allowed'][0]['source'])
        self.write('scripts/lib/absolute-literals-baseline/engine/engine-x.json',
                   {'files': {'scripts/lib/lane.py': {found: 1}}})
        self.write('scripts/lib/literal-catalogs/engine.json', {'catalogs': {'scripts/lib/cat.py': {'domains': []}}})
        self.write('scripts/lib/broken.json', '{')
        commit = self.commit()
        self.assertEqual(literal_census.legacy_lists(self.root, commit, 'baseline'),
                         {'scripts/lib/lane.py': {found: 1}})
        self.assertEqual(list(literal_census.legacy_lists(self.root, commit, 'catalog')), ['scripts/lib/cat.py'])
        self.default_ref(commit)
        self.write('scripts/lib/lane.py', case['source'])
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        self.assertEqual(literal_census.check(self.root), ([], []))  # the old count allows one
        self.write('scripts/lib/lane.py', case['source'] + case['source'])
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)
        self.assertIn('allows 1', literal_census.check(self.root)[0][0])

    def test_lt1_without_the_base_ref_the_census_fails_closed(self):
        self.write('scripts/lib/clean.py', CASES['allowed'][0]['source'])
        self.commit()
        self.default_ref('origin/absent-branch')
        errors = literal_census.check(self.root)[0]
        self.assertEqual(errors, ['literals: origin/absent-branch (literals.base_ref) is not in this checkout, so the base '
                                  'census cannot be computed: run git fetch origin absent-branch, or pass --base <ref>; '
                                  'the allowed counts are the base census, so nothing is allowed (fail closed)'])

    def test_lt1_a_file_the_production_guard_forbids_naming_is_not_listed(self):
        entrypoint = config.get('production.forbidden_entrypoints', self.root)[0]
        case = CASES['refused'][0]
        self.write(f'scripts/lib/{entrypoint.replace("-", "_")}.py', case['source'])  # the guard's module form
        self.write('scripts/lib/lane.py', case['source'])
        self.commit()
        self.assertEqual(list(literal_census.census(self.root).popitem()[1]), ['scripts/lib/lane.py'])

    def test_lt1_a_checkout_without_the_literals_registry_is_not_judged(self):
        (self.root / 'config/registry/literals.json').unlink()
        self.assertEqual(literal_census.check(self.root), ([], []))


if __name__ == '__main__':
    unittest.main()
