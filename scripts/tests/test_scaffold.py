"""The scaffold of a new script (FLUXO-AMPLO F1.2, D-146). Hermetic: a throwaway tree."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import scaffold  # noqa: E402



class ScaffoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'units' / 'u').mkdir(parents=True)
        (self.root / 'units' / 'u' / 'unit.json').write_text(json.dumps({'id': 'u', 'paths': ['scripts/old']}))

    def make(self, name='new-thing', **overrides):
        values = dict(name=name, unit='u', purpose='Does a thing.')
        values.update(overrides)
        return scaffold.write(self.root, **values)

    def test_the_six_things_a_new_script_needs_are_written(self):
        written = self.make()
        for path in ('scripts/new-thing', 'scripts/lib/new_thing.py', 'scripts/tests/test_new_thing.py',
                     'scripts/tests/new-thing.test.sh', 'scripts/tests/covers/new-thing.json'):
            self.assertTrue((self.root / path).is_file(), path)
            self.assertIn(path, written)
        covers = json.loads((self.root / 'scripts/tests/covers/new-thing.json').read_text())
        self.assertEqual(set(covers), {'script', 'covers'})  # VAZÃO F57: no `modules` field
        manifest = json.loads((self.root / 'units/u/unit.json').read_text())
        self.assertEqual(manifest['paths'], sorted({'scripts/old', 'scripts/new-thing', 'scripts/lib/new_thing.py',
                                                    'scripts/tests/new-thing.test.sh', 'scripts/tests/test_new_thing.py'}))

    def test_the_wrappers_are_executable_and_the_generated_test_passes(self):
        self.make()
        self.assertTrue(os.access(self.root / 'scripts/new-thing', os.X_OK))
        self.assertTrue(os.access(self.root / 'scripts/tests/new-thing.test.sh', os.X_OK))
        sys.path.insert(0, str(self.root / 'scripts' / 'lib'))
        try:
            import new_thing
            self.assertEqual(new_thing.main([]), 0)
        finally:
            sys.path.remove(str(self.root / 'scripts' / 'lib'))
            sys.modules.pop('new_thing', None)

    def test_it_refuses_to_overwrite_and_changes_nothing(self):
        self.make()
        before = (self.root / 'units/u/unit.json').read_text()
        with self.assertRaises(SystemExit):
            self.make()
        self.assertEqual((self.root / 'units/u/unit.json').read_text(), before)

    def test_bad_input_is_refused_before_anything_is_written(self):
        for bad in ({'name': 'Bad_Name'}, {'unit': 'nope'}):
            with self.assertRaises(SystemExit):
                self.make(**bad)
        self.assertFalse((self.root / 'scripts').exists())


class ConfigKeyTests(unittest.TestCase):
    """VAZÃO F74: `scaffold config-key` writes a key that passes the meta-schema and declares its readers."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / 'contracts' / 'config').mkdir(parents=True)
        (self.root / 'contracts/config/registry.v1.json').write_text((ROOT / 'contracts/config/registry.v1.json').read_text())
        import config
        for owner in ('demo', config.get('l10n.text_owner')):
            folder = self.root / 'config' / 'registry' / owner
            folder.mkdir(parents=True)
            (folder / '_owner.json').write_text(json.dumps({
                '$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': f'config/registry/{owner}.json',
                'x-owner': owner, 'x-schema-version': 1, 'type': 'object', 'additionalProperties': False}))
        (self.root / 'scripts' / 'lib').mkdir(parents=True)
        (self.root / 'scripts/lib/demo.py').write_text("config.get('demo.wait_s')\n")

    def key(self, **overrides):
        values = dict(root=self.root, owner='demo', key='wait_s', readers=['scripts/lib/demo.py'], kind='integer',
                      default=5, unit='s', description='How long the demo waits.')
        values.update(overrides)
        return scaffold.config_key(**values)

    def test_the_key_file_and_the_aggregate_pass_the_meta_schema(self):
        import config
        import json_schema
        written = self.key(source='VAZÃO F74')
        self.assertEqual(written, ['config/registry/demo/demo.wait_s.json', 'config/registry/demo.json'])
        item = json.loads((self.root / written[0]).read_text())
        self.assertEqual(item['x-readers'], ['scripts/lib/demo.py'])
        aggregate = json.loads((self.root / written[1]).read_text())
        self.assertEqual(aggregate['properties']['demo.wait_s'], item)
        meta = json.loads((ROOT / 'contracts/config/registry.v1.json').read_text())
        self.assertEqual(json_schema.validate(meta, aggregate), [])
        self.assertEqual(json_schema.validate(config.parameter_schema(item), item['default']), [])

    def test_an_object_text_key_is_keyed_by_locale_with_x_text(self):
        import config
        import json_schema
        locale, owner = config.get('l10n.default_locale'), config.get('l10n.text_owner')
        written = self.key(owner=owner, key='greeting', kind='object', default={locale: 'Hello'}, unit='text')
        item = json.loads((self.root / written[0]).read_text())
        self.assertIs(item['x-text'], True)
        self.assertEqual(item['required'], [locale])
        meta = json.loads((ROOT / 'contracts/config/registry.v1.json').read_text())
        self.assertEqual(json_schema.validate(meta, json.loads((self.root / written[1]).read_text())), [])
        for overrides in (dict(owner=owner, default={'zz': 'x'}), dict(owner='demo', default={locale: 'Hi'})):
            with self.subTest(overrides), self.assertRaises(SystemExit):
                self.key(key='bare', kind='object', unit='text', **overrides)

    def test_refusals_leave_nothing_written(self):
        for overrides in (dict(readers=[]), dict(readers=['scripts/lib/missing.py']),
                          dict(readers=['scripts/tests/test_demo.py']), dict(owner='nobody'),
                          dict(default='five'), dict(unit='Seconds')):
            with self.subTest(overrides), self.assertRaises(SystemExit):
                self.key(**overrides)
        self.assertFalse((self.root / 'config/registry/demo/demo.wait_s.json').exists())
        self.key()
        with self.assertRaises(SystemExit):
            self.key()  # never overwrites

    def test_the_cli_writes_the_key(self):
        with unittest.mock.patch.object(scaffold, 'ROOT', self.root):
            self.assertEqual(scaffold.main(['config-key', 'demo', 'wait_s', '--reader', 'scripts/lib/demo.py',
                                            '--type', 'integer', '--default', '5', '--unit', 's',
                                            '--description', 'How long.']), 0)
        self.assertTrue((self.root / 'config/registry/demo/demo.wait_s.json').is_file())


if __name__ == '__main__':
    unittest.main()
