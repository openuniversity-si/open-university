"""Retired vendors (D-318): nothing of ours relates to a vendor we retired; only the historical records keep the past."""
from pathlib import Path
import io
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import retired_vendors  # noqa: E402

TERMS = ['acmecloud', '(?<![a-z])zeta']  # fixture vendors: this file names no pattern of the registry


class Repo(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.values = {'structure.retired_vendor_terms': TERMS, 'structure.record_globs': ['docs/units/**']}
        patch = mock.patch.object(retired_vendors.config, 'get', side_effect=lambda name, *a: self.values[name])
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, rel, text, binary=False):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text) if binary else path.write_text(text)
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)


class RetiredVendors(Repo):
    def test_d318_an_acting_line_naming_a_vendor_is_refused_with_its_place(self):
        self.write('scripts/lib/x.py', 'ok = 1\nHOST = "api.AcmeCloud.com"\n')
        errors = retired_vendors.check(self.root)
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith('scripts/lib/x.py:2: "HOST = "api.AcmeCloud.com"" names a retired vendor'),
                        errors[0])
        self.assertIn('(D-318)', errors[0])

    def test_d318_package_host_and_variable_forms_are_all_caught(self):
        self.write('package.json', '{"dependencies": {"@acmecloud/blob": "1.0.0"}}\n')
        self.write('next.config.ts', "const img = 'https://x.public.blob.acmecloud-storage.com';\n")
        self.write('.env.example', 'ACMECLOUD_ENV=production\nDATABASE_URL=postgresql://u@ep-1.zeta.tech/db\n')
        found = retired_vendors.references(self.root, TERMS, [])
        self.assertEqual([(path, line) for path, line, _ in found],
                         [('.env.example', 1), ('.env.example', 2), ('next.config.ts', 1), ('package.json', 1)])

    def test_d318_the_lookbehind_keeps_a_word_that_only_contains_the_letters(self):
        self.write('scripts/lib/x.py', 'class MachinezetaOnly:\n    pass\nTEST_ZETA = 1\n')
        found = retired_vendors.references(self.root, TERMS, [])
        self.assertEqual([line for _, line, _ in found], [3])

    def test_d318_a_path_naming_a_vendor_is_refused_and_a_record_is_kept(self):
        self.write('scripts/tests/fake/acmecloud.py', 'ROUTES = ()\n')
        self.write('docs/units/OLD/retro.md', 'We left AcmeCloud on 17/11.\n')
        self.write('docs/units/zeta-migrate/plan.md', 'history\n')
        errors = retired_vendors.check(self.root)
        self.assertEqual(errors, [f'scripts/tests/fake/acmecloud.py: its path names a retired vendor '
                                  '(structure.retired_vendor_terms); nothing of ours relates to one, and only the '
                                  'records of structure.record_globs keep the past (D-318)'])

    def test_d318_a_binary_file_and_an_untracked_file_are_not_read(self):
        self.write('media/logo.png', b'\x89PNG\x00acmecloud', binary=True)
        (self.root / 'notes.txt').write_text('acmecloud\n')
        self.assertEqual(retired_vendors.check(self.root), [])

    def test_d318_a_tree_that_is_not_a_checkout_has_nothing_to_judge_but_the_command_says_so(self):
        plain = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, plain)
        (plain / 'x.py').write_text('acmecloud\n')
        self.assertEqual(retired_vendors.check(plain), [])
        with self.assertRaises(RuntimeError):
            retired_vendors.main(['--root', str(plain)])

    def test_d318_no_terms_judge_nothing(self):
        self.write('scripts/lib/x.py', 'acmecloud\n')
        self.values['structure.retired_vendor_terms'] = []
        self.assertEqual(retired_vendors.check(self.root), [])

    def test_d318_the_command_judges_another_checkout_with_no_records(self):
        self.write('docs/units/OLD/retro.md', 'AcmeCloud\n')
        out = io.StringIO()
        with redirect_stdout(out):
            code = retired_vendors.main(['--root', str(self.root), '--no-records'])
        self.assertEqual(code, 1)
        self.assertIn('docs/units/OLD/retro.md:1: AcmeCloud', out.getvalue())
        self.assertIn('1 reference(s) in 1 file(s)', out.getvalue())
        self.write('docs/units/OLD/retro.md', 'gone\n')
        out = io.StringIO()
        with redirect_stdout(out):
            code = retired_vendors.main(['--root', str(self.root), '--records'])
        self.assertEqual(code, 0)
        self.assertIn('record docs/units/**: 1 tracked file(s)', out.getvalue())


class Registry(unittest.TestCase):
    def test_d318_the_registry_patterns_compile_and_keep_their_own_definition_a_record(self):
        terms = config.get('structure.retired_vendor_terms')
        self.assertGreaterEqual(len(terms), 2)
        for term in terms:
            re.compile(term, re.IGNORECASE)
        self.assertIn('config/registry/structure/structure.retired_vendor_terms.json',
                      config.get('structure.record_globs'))


class ThisCheckout(unittest.TestCase):
    def test_d318_this_checkout_names_no_retired_vendor(self):
        self.assertEqual(retired_vendors.check(ROOT), [])


if __name__ == '__main__':
    unittest.main()
