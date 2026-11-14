"""The user-facing text check (D-069 item 15, L1): x-text entries, and (later commits) the pilot unit's visible strings.

Fixture repositories in a temporary directory; no network, no clock.
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import json_schema  # noqa: E402
import text_check  # noqa: E402

COPIED = ('contracts/config/registry.v1.json', 'contracts/events/config.changed.v1.json', 'config/registry/config.json',
          'config/registry/l10n.json')


def entry(**extra):
    item = {'type': 'object', 'x-text': True, 'x-unit': 'text', 'description': 'A heading.', 'x-readers': [],
            'default': {'en': 'No courses yet'}, 'propertyNames': {'type': 'string'},
            'additionalProperties': {'type': 'string'}, 'required': ['en']}
    item.update(extra)
    return item


def registry(owner, properties):
    return {'$schema': json_schema.DIALECT, '$id': f'config/registry/{owner}.json', 'x-owner': owner,
            'x-schema-version': 1, 'type': 'object', 'additionalProperties': False, 'properties': properties}


class Repo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in COPIED:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        for name in ('config', 'l10n'):
            policy = json.loads((self.root / f'config/registry/{name}.json').read_text())
            for item in policy['properties'].values():
                item['x-readers'] = []
            self.write(f'config/registry/{name}.json', policy)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else json.dumps(content))

    def text(self, **properties):
        self.write('config/registry/text.json', registry('text', properties))


class EntryTests(Repo):
    def test_a_well_formed_entry_passes(self):
        self.text(**{'text.empty_title': entry()})
        self.assertEqual(text_check.entry_errors(self.root), [])

    def test_an_entry_without_en_in_its_default_fails(self):
        self.text(**{'text.empty_title': entry(default={})})
        self.assertTrue(any('without en' in error and 'default' in error for error in text_check.entry_errors(self.root)))

    def test_an_entry_that_does_not_require_en_fails(self):
        self.text(**{'text.empty_title': entry(required=[])})
        self.assertTrue(any('without en' in error and 'required' in error for error in text_check.entry_errors(self.root)))

    def test_a_locale_outside_the_registry_list_fails(self):
        self.text(**{'text.empty_title': entry(default={'en': 'No courses', 'pt': 'Sem cursos'})})
        self.assertTrue(any("'pt'" in error for error in text_check.entry_errors(self.root)))

    def test_a_blank_text_fails(self):
        self.text(**{'text.empty_title': entry(default={'en': '  '})})
        self.assertTrue(any('non-empty' in error for error in text_check.entry_errors(self.root)))

    def test_an_owner_entry_that_is_not_text_fails(self):
        plain = {'type': 'integer', 'default': 1, 'x-unit': 'count', 'description': 'A count.', 'x-readers': []}
        self.text(**{'text.count': plain})
        self.assertTrue(any('must be user-facing text' in error for error in text_check.entry_errors(self.root)))

    def test_text_outside_the_text_owner_fails(self):
        self.write('config/registry/train.json', registry('train', {'train.title': entry()}))
        self.assertTrue(any('live in config/registry/text.json' in error for error in text_check.entry_errors(self.root)))

    def test_a_default_locale_outside_the_list_fails(self):
        policy = json.loads((self.root / 'config/registry/l10n.json').read_text())
        policy['properties']['l10n.default_locale']['default'] = 'pt'
        self.write('config/registry/l10n.json', policy)
        self.assertTrue(any('l10n.default_locale' in error for error in text_check.entry_errors(self.root)))

    def test_a_repository_without_the_l10n_registry_is_not_judged(self):
        (self.root / 'config/registry/l10n.json').unlink()
        self.write('config/registry/train.json', registry('train', {'train.title': entry(default={})}))
        self.assertEqual(text_check.entry_errors(self.root), [])

    def test_the_repository_entries_pass(self):
        self.assertEqual(text_check.entry_errors(ROOT), [])

    def test_the_contract_accepts_the_additive_context_field(self):
        meta = json.loads((ROOT / 'contracts/config/registry.v1.json').read_text())
        document = registry('text', {'text.empty_title': entry(**{'x-text-context': 'Heading of the empty catalog.'})})
        self.assertEqual(json_schema.validate(meta, document), [])
        self.assertTrue(config.get('l10n.locales'))


class VisibleTests(Repo):
    FILE = 'products/demo/src/ui/Panel/Panel.tsx'
    CATALOG = 'products/demo/src/site/domain/copy.ts'

    def scope(self, files=(FILE,), exports=()):
        policy = json.loads((self.root / 'config/registry/l10n.json').read_text())
        policy['properties']['l10n.scoped_files']['default'] = list(files)
        policy['properties']['l10n.scoped_exports']['default'] = list(exports)
        self.write('config/registry/l10n.json', policy)

    def component(self, body):
        self.write(self.FILE, 'export function Panel({ title }: { title: string }) {\n  return (\n' + body + '\n  );\n}\n')

    def errors(self):
        return text_check.check_visible(self.root)

    def test_a_component_that_reads_its_props_and_ids_passes(self):
        self.scope()
        self.component('    <section data-testid="panel" className="x"><h2>{title}</h2><p className="body">{text("a")}</p></section>')
        self.assertEqual(self.errors(), [])

    def test_a_jsx_text_node_fails(self):
        self.scope()
        self.component('    <section><h2>No courses yet</h2></section>')
        self.assertTrue(any('Panel.tsx:3' in error and 'No courses yet' in error for error in self.errors()))

    def test_a_string_child_fails(self):
        self.scope()
        self.component('    <section><h2>{"No courses yet"}</h2></section>')
        self.assertTrue(any('No courses yet' in error for error in self.errors()))

    def test_a_visible_attribute_fails_but_other_attributes_pass(self):
        self.scope()
        self.component('    <img alt="A lecture hall" data-testid="hall" className="hall-photo" />')
        errors = self.errors()
        self.assertEqual(len(errors), 1)
        self.assertIn('alt attribute', errors[0])

    def test_a_comment_and_a_generic_are_not_text(self):
        self.scope()
        self.write(self.FILE, '// Heading of the panel\n/* Body text here */\nconst a: Array<string> = [];\n'
                   'export const Panel = () => <section>{a.length > 1 && <b />}</section>;\n')
        self.assertEqual(self.errors(), [])

    def test_a_file_outside_the_scope_is_not_judged(self):
        self.scope(files=())
        self.component('    <section><h2>No courses yet</h2></section>')
        self.assertEqual(self.errors(), [])

    def test_a_scoped_export_with_a_literal_fails(self):
        self.scope(files=(), exports=(f'{self.CATALOG}:emptyTitle',))
        self.write(self.CATALOG, 'export const emptyTitle = "No courses yet";\n')
        self.assertTrue(any('emptyTitle spells a string literal' in error for error in self.errors()))

    def test_a_scoped_export_that_reads_the_catalog_passes(self):
        self.scope(files=(), exports=(f'{self.CATALOG}:emptyTitle',))
        self.write(self.CATALOG, 'export const other = "Still literal";\nexport const emptyTitle = text("text.empty_title");\n')
        self.assertEqual(self.errors(), [])

    def test_a_stale_scope_site_fails(self):
        self.scope(files=(self.FILE,), exports=(f'{self.CATALOG}:gone',))
        self.write(self.CATALOG, 'export const other = text("a");\n')
        errors = self.errors()
        self.assertTrue(any('no longer exports' in error for error in errors))
        self.assertTrue(any('does not exist' in error for error in errors))

    def test_the_repository_visible_check_passes(self):
        # OU-DECOUPLE F4 (D-111): the pilot scope was Open University's; with no user-facing text left it lists nothing,
        # and the check stays for the next product that registers its files.
        self.assertEqual(text_check.check_visible(ROOT), [])


if __name__ == '__main__':
    unittest.main()
