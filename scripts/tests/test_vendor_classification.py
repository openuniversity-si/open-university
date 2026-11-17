"""Baseline classification and shrink-only enforcement, using offline catalog fixtures."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import json_schema
import vendor_check

CATALOG_PATH = 'scripts/lib/adapters/engine-vendors.json'
SCHEMA_PATH = 'contracts/adapters/engine-vendors.v1.json'
CATALOG = json.loads((ROOT / CATALOG_PATH).read_text())
# the two files as they were at abdf8f623 (the old repository's history, which the public one does not carry)
BASELINE = ROOT / 'scripts' / 'tests' / 'fixtures' / 'vendor-baseline-abdf8f623'
SCHEMA = json.loads((ROOT / SCHEMA_PATH).read_text())


class Classification(unittest.TestCase):
    def test_additive_contract_accepts_old_catalog_and_rejects_bad_metadata(self):
        old_schema = json.loads((BASELINE / Path(SCHEMA_PATH).name).read_text())
        self.assertEqual(json_schema.compatible(old_schema, SCHEMA), [])
        old_catalog = copy.deepcopy(CATALOG)
        for vendor in old_catalog['vendors']:
            vendor.pop('baseline_classification', None)
        self.assertEqual(json_schema.validate(SCHEMA, old_catalog), [])
        self.assertEqual(json_schema.check_schema(SCHEMA), [])
        for field in ('nature', 'reason'):
            for value in (None, '', '  \t', {}):
                with self.subTest(field=field, value=value):
                    catalog = copy.deepcopy(CATALOG)
                    entry = next(iter(catalog['vendors'][0]['baseline_classification'].values()))
                    if value is None:
                        entry.pop(field)
                    else:
                        entry[field] = value
                    self.assertTrue(json_schema.validate(SCHEMA, catalog))

    def test_real_catalog_has_distinct_reasons_and_unchanged_baseline(self):
        before = json.loads((BASELINE / Path(CATALOG_PATH).name).read_text())
        old_by_name = {vendor['name']: vendor for vendor in before['vendors']}  # a retired vendor leaves both (D-318)
        for new in CATALOG['vendors']:
            old = old_by_name.get(new['name'], {'baseline': []})
            self.assertLessEqual(set(new['baseline']), set(old['baseline']),
                                 f"{new['name']} baseline gained a site since abdf8f623")
        self.assertEqual(vendor_check.catalog_errors(ROOT, CATALOG), [])
        entries = CATALOG['vendors'][0]['baseline_classification']
        self.assertEqual(set(entries), set(CATALOG['vendors'][0]['baseline']))
        # Every site states its nature and reason; the set itself shrinks with the baseline, so it is not pinned here.
        self.assertTrue(all(entry['nature'] and entry['reason'] for entry in entries.values()))
        self.assertEqual(len({entry['reason'] for entry in entries.values()}), len(entries))

    def test_check_rejects_missing_fields_and_growth_together(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative, data in ((CATALOG_PATH, CATALOG), (SCHEMA_PATH, SCHEMA),
                                   ('config/registry/providers.json', {})):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))
            for vendor in CATALOG['vendors']:
                for relative in vendor['adapters'] + vendor['selectors']:
                    path = root / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.touch()
            def git(*args):
                return subprocess.run(['git', '-C', str(root), *args], check=True,
                                      capture_output=True, text=True)
            git('init', '-q')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                '-c', 'core.hooksPath=/dev/null', 'commit', '-qm', 'Fixture baseline')
            settings = {'providers.vendor_catalog': CATALOG_PATH,
                        'providers.vendor_catalog_schema': SCHEMA_PATH,
                        'providers.vendor_check_excludes': [],
                        'providers.adapter_dir': 'scripts/lib/adapters'}
            def check(catalog):
                (root / CATALOG_PATH).write_text(json.dumps(catalog))
                with patch.object(vendor_check.config, 'get', side_effect=lambda key, *_: settings[key]), \
                        patch.object(vendor_check.config_check, 'engine_files', return_value=[]):
                    return vendor_check.check(root, 'HEAD')[0]
            self.assertEqual(check(CATALOG), [])
            for field in ('nature', 'reason'):
                for blank in (None, '', ' \t'):
                    with self.subTest(field=field, blank=blank):
                        catalog = copy.deepcopy(CATALOG)
                        vendor = catalog['vendors'][0]
                        site = vendor['baseline'][0]
                        if blank is None:
                            vendor.pop('baseline_classification')
                        else:
                            vendor['baseline_classification'][site][field] = blank
                        self.assertTrue(check(catalog))
            # A fully justified new site still cannot grow the baseline.
            catalog = copy.deepcopy(CATALOG)
            vendor = catalog['vendors'][0]
            site = 'scripts/new.py:github_api'
            vendor['baseline'].append(site)
            vendor['baseline_classification'][site] = {'nature': 'credential-probe', 'reason': 'Valid text.'}
            self.assertTrue(any('baseline gains ' + site in error for error in check(catalog)))
            # Both violations are reported by the same check invocation.
            vendor.pop('baseline_classification')
            errors = check(catalog)
            self.assertTrue(any('requires nonblank nature' in error for error in errors))
            self.assertTrue(any('requires nonblank reason' in error for error in errors))
            self.assertTrue(any('baseline gains ' + site in error for error in errors))
            catalog = copy.deepcopy(CATALOG)
            vendor = catalog['vendors'][0]
            removed = vendor['baseline'].pop()
            self.assertTrue(any('has no baseline site' in error for error in check(catalog)))
            vendor['baseline_classification'].pop(removed)
            self.assertEqual(check(catalog), [])


if __name__ == '__main__':
    unittest.main(verbosity=True)
