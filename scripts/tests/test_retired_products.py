"""Retired products (OU-DECOUPLE F5, D-113): the engine names no product it retired."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import retired_products  # noqa: E402

PRODUCT = 'products/' + 'gone'  # a fixture root, assembled so this file names no root of the registry


class Repo(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        values = {'structure.retired_product_roots': [PRODUCT], 'structure.record_globs': ['docs/units/**']}
        patch = mock.patch.object(retired_products.config, 'get', side_effect=lambda name, *a: values[name])
        patch.start()
        self.addCleanup(patch.stop)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        subprocess.run(['git', '-C', str(self.root), 'add', '-A'], check=True)


class RetiredProducts(Repo):
    def test_d113_a_path_under_a_retired_root_is_refused(self):
        self.write(f'{PRODUCT}/src/page.ts', 'x\n')
        errors = retired_products.check(self.root)
        self.assertIn(f'{PRODUCT}/src/page.ts: lies under the retired product root {PRODUCT} (structure.retired_product_roots)',
                      errors)

    def test_d113_an_acting_file_naming_a_root_is_refused_and_a_record_is_not(self):
        self.write('scripts/lib/x.py', f'WEB = "{PRODUCT}/package.json"\n')
        self.write('docs/units/OLD/retro.md', f'We built {PRODUCT}.\n')
        self.write('docs/engine.md', 'the engine\n')
        errors = retired_products.check(self.root)
        self.assertEqual(len(errors), 1)
        self.assertTrue(errors[0].startswith('scripts/lib/x.py: names a retired product root'))

    def test_d113_no_root_judges_nothing(self):
        self.write('scripts/lib/x.py', f'WEB = "{PRODUCT}"\n')
        with mock.patch.object(retired_products.config, 'get', side_effect=lambda name, *a: [] if 'roots' in name else []):
            self.assertEqual(retired_products.check(self.root), [])


class ThisCheckout(unittest.TestCase):
    def test_d113_this_checkout_names_no_retired_product(self):
        self.assertEqual(retired_products.check(ROOT), [])


if __name__ == '__main__':
    unittest.main()
