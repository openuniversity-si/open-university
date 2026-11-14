"""The engine-vendors contract (P-07): what other units import is published, exists, and nothing else leaks. No network."""
import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import units  # noqa: E402
from adapters import launcher, storage  # noqa: E402
import vendor_check  # noqa: E402

PUBLISHED = {('adapters.storage', 'open_store'), ('adapters.launcher', 'adapter'),
             ('adapters.launcher', 'LaunchRequest'), ('vendor_check', 'check')}
MODULES = {'adapters.storage': storage, 'adapters.launcher': launcher, 'vendor_check': vendor_check}


def foreign_imports():
    """(module, name) pairs that files outside the unit take from it, read from the import statements."""
    found = set()
    for path in sorted((ROOT / 'scripts').rglob('*.py')):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith('scripts/lib/adapters/') or rel.endswith(('vendor_check.py', 'test_vendor_check.py')) \
                or '/test_ports_' in rel:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ImportFrom) and node.module and (node.module.startswith('adapters')
                                                                    or node.module == 'vendor_check'):
                found.update((node.module, alias.name) for alias in node.names)
    return found


class Contract(unittest.TestCase):
    def test_every_published_name_exists(self):
        for module, name in PUBLISHED:
            self.assertTrue(hasattr(MODULES[module], name), f'{module}.{name}')

    def test_outside_files_import_only_published_names(self):
        extra = {pair for pair in foreign_imports() if pair not in PUBLISHED and pair[0] != 'adapters'}
        self.assertEqual(extra, set())

    def test_the_entry_is_a_file_of_the_unit(self):
        entry = ROOT / 'scripts' / 'lib' / 'adapters' / '__init__.py'
        self.assertEqual(units.units_of('scripts/lib/adapters/__init__.py', ROOT), ['engine-vendors'])
        self.assertIn('Published surface (contract 1.0.0', entry.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
