"""F31: each Python file's raw values are kept by content (source_facts) and the census rules are applied live, so the
answer is the uncached one whatever the cache holds: a changed file, a changed extractor or a corrupt entry is
extracted again, and a rule change is judged on the cached values.

Fixture git checkouts in a temporary directory (the Checkout of test_literal_census.py); no network, no clock.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_literal_census import CASES, Checkout  # noqa: E402
import literal_census  # noqa: E402
import source_facts  # noqa: E402

PYTHON = [case for case in CASES['refused'] + CASES['allowed'] if case['suffix'] == '.py']
REFUSED = {case['name']: case for case in CASES['refused']}


class ValueCache(Checkout):
    def setUp(self):
        super().setUp()
        self.cache = self.root.parent / f'{self.root.name}-cache'
        patched = mock.patch.dict('os.environ', {source_facts.ENV: str(self.cache)})
        patched.start()
        self.addCleanup(patched.stop)
        self.addCleanup(shutil.rmtree, self.cache, True)

    def entries(self):
        return sorted(path for path in self.cache.rglob('*') if path.is_file()) if self.cache.is_dir() else []

    def scan(self, extracted):
        """occurrences of the fixture, asserting how many files were extracted rather than read from the cache."""
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)  # the scan reads tracked files
        with mock.patch.object(literal_census, 'python_values', wraps=literal_census.python_values) as extract:
            found = literal_census.occurrences(self.root)
        self.assertEqual(extract.call_count, extracted)
        return found

    def test_every_case_is_found_alike_cold_warm_and_uncached(self):
        rules, store = literal_census.Census(self.root), source_facts.store(self.root)
        for case in PYTHON:
            with self.subTest(case['name']):
                uncached = literal_census.python_literals(case['source'], rules)
                self.assertEqual(literal_census.python_literals(case['source'], rules, store), uncached)  # cold
                self.assertEqual(literal_census.python_literals(case['source'], rules, store), uncached)  # warm
        self.assertEqual(len(self.entries()), len({case['source'] for case in PYTHON}))

    def test_a_changed_file_is_extracted_again(self):
        case = REFUSED['a python number']
        self.write('scripts/lib/lane.py', case['source'])
        cold = self.scan(extracted=1)
        self.assertEqual(self.scan(extracted=0), cold)
        self.write('scripts/lib/lane.py', case['source'] + case['source'])
        lines = self.scan(extracted=1)['scripts/lib/lane.py'][-1]
        self.assertEqual(lines, {literal_census.key(*case['found'][0]): [1, len(case['source'].splitlines()) + 1]})

    def test_a_rule_change_is_judged_on_cached_values(self):
        case = REFUSED['a python number']
        self.write('scripts/lib/lane.py', case['source'])
        self.assertIn('scripts/lib/lane.py', self.scan(extracted=1))
        policy = self.registry('config/registry/literals.json')
        policy['properties']['literals.allowed_numbers']['default'].append(case['found'][0][-1])
        self.write('config/registry/literals.json', policy)
        self.assertNotIn('scripts/lib/lane.py', self.scan(extracted=0))

    def test_a_corrupt_entry_or_a_new_extractor_is_extracted_again(self):
        self.write('scripts/lib/lane.py', REFUSED['a python number']['source'])
        expected = self.scan(extracted=1)
        for entry in self.entries():
            entry.write_text('[[1, "number", "thirty"]]')
        self.assertEqual(self.scan(extracted=1), expected)
        self.assertEqual(self.scan(extracted=0), expected)  # the entry was rewritten
        with mock.patch.object(source_facts, 'digest', return_value='another extractor'):
            self.assertEqual(self.scan(extracted=1), expected)


if __name__ == '__main__':
    unittest.main()
