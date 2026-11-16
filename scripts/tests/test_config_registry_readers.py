"""Registry readers found in the code (GATE-SPEED wave 2, R5; D-100): every file that spells a key is in that key's
x-readers, so a selection by the readers of the changed keys cannot miss a reader. A fixture checkout shows what counts
as a reader (sources yes; tests, generated modules and other files no) and that --fix declares exactly the gaps."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import registry_readers  # noqa: E402

IDENTITY = ('-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-c', 'commit.gpgsign=false')


class Repository(unittest.TestCase):
    def test_every_reader_in_the_code_is_declared(self):
        self.assertEqual(registry_readers.missing(ROOT), [])


class Fixture(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        owner = self.root / 'config' / 'registry' / 'demo'
        owner.mkdir(parents=True)
        (owner / '_owner.json').write_text('{}')
        (owner / 'demo.flag.json').write_text(json.dumps({'default': True, 'x-readers': ['scripts/lib/known.py']}))
        (self.root / 'config' / 'registry' / 'demo.json').write_text(json.dumps(
            {'properties': {'demo.flag': {'default': True, 'x-readers': ['scripts/lib/known.py']}}}))
        files = {'scripts/lib/known.py': "config.get('demo.flag')\n", 'scripts/lib/new.py': "setting('demo.flag')\n",
                 'scripts/tests/test_new.py': "config.get('demo.flag')\n",
                 'scripts/lib/generated/mod.py': "'demo.flag'\n", 'docs/note.md': "'demo.flag'\n"}
        for name, text in files.items():
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            (self.root / name).write_text(text)
        subprocess.run(['git', '-C', str(self.root), *IDENTITY, 'init', '-q'], check=True)
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)

    def test_configuration_relation_is_metadata_not_an_effective_value_reader(self):
        relation = self.root / 'scripts/lib/operation_config_relations.json'
        relation.write_text(json.dumps({'keys': [{'name': 'demo.flag'}]}))
        # The read-only boundary inventories metadata, without spelling effective keys.
        (self.root / 'scripts/lib/operation_config.py').write_text(
            "import json\n" "def registry(path):\n    return json.loads(path.read_text()).get('x-readers', [])\n")
        subprocess.run(['git', '-C', str(self.root), 'add', '.'], check=True)
        self.assertNotIn('scripts/lib/operation_config.py', registry_readers.sites(self.root)['demo.flag'])
        self.assertEqual(registry_readers.missing(self.root), [('demo.flag', 'scripts/lib/new.py')])

    def test_only_sources_read_and_fix_declares_the_gap(self):
        self.assertEqual(registry_readers.missing(self.root), [('demo.flag', 'scripts/lib/new.py')])
        self.assertEqual(registry_readers.fix(self.root), 1)
        item = json.loads((self.root / 'config' / 'registry' / 'demo' / 'demo.flag.json').read_text())
        self.assertEqual(item['x-readers'], ['scripts/lib/known.py', 'scripts/lib/new.py'])



class Expand(Fixture):
    """R5 A2 (D-102): a split key's change selects by its readers; anything not explained keeps the aggregate."""
    KEY, AGGREGATE = 'config/registry/demo/demo.flag.json', 'config/registry/demo.json'

    def test_a_key_with_readers_replaces_the_aggregate_by_its_declared_and_its_derived_readers(self):
        self.assertEqual(registry_readers.expand([self.KEY, self.AGGREGATE, 'docs/x.md'], self.root),
                         [self.KEY, 'docs/x.md', 'scripts/lib/known.py', 'scripts/lib/new.py'])

    def test_a_reader_nobody_declared_is_selected_from_the_code(self):
        (self.root / self.KEY).write_text(json.dumps({'default': True, 'x-readers': []}))
        self.assertEqual(registry_readers.expand([self.KEY, self.AGGREGATE], self.root),
                         [self.KEY, 'scripts/lib/known.py', 'scripts/lib/new.py'])

    def test_fail_closed_keeps_the_aggregate(self):
        header = 'config/registry/demo/_owner.json'
        gone = 'config/registry/demo/demo.gone.json'
        for extra in (header, gone):
            self.assertIn(self.AGGREGATE, registry_readers.expand([self.KEY, extra, self.AGGREGATE], self.root), extra)
        lonely = 'config/registry/demo/demo.lonely.json'
        (self.root / lonely).write_text(json.dumps({'default': True, 'x-readers': []}))
        aggregate = json.loads((self.root / self.AGGREGATE).read_text())
        aggregate['properties']['demo.lonely'] = {'default': True, 'x-readers': []}
        (self.root / self.AGGREGATE).write_text(json.dumps(aggregate))
        self.assertEqual(registry_readers.expand([lonely, self.AGGREGATE], self.root), [lonely, self.AGGREGATE])

    def test_the_selection_uses_it_only_while_the_switch_is_on(self):
        import gate_script_tests
        from unittest import mock
        mapping = {'scripts': ('a.test.sh', 'b.test.sh', 'c.test.sh'), 'fallback': [], 'tests': [
            {'script': 'a.test.sh', 'covers': ['scripts/lib/known.py', 'scripts/lib/new.py']},
            {'script': 'b.test.sh', 'covers': [self.AGGREGATE]},
            {'script': 'c.test.sh', 'covers': ['config/registry/*/*.json']}]}
        real = gate_script_tests.config.get

        def switch(on):
            return lambda name, root=None: on if name == 'gate.select_by_readers' else real(name, root)
        with mock.patch.object(gate_script_tests.config, 'get', side_effect=switch(True)), \
                mock.patch.object(gate_script_tests.Path, 'cwd', return_value=self.root):
            chosen, _ = gate_script_tests.select([self.KEY, self.AGGREGATE], mapping)
        self.assertEqual(chosen, ('a.test.sh', 'c.test.sh'))
        with mock.patch.object(gate_script_tests.config, 'get', side_effect=switch(False)):
            chosen, _ = gate_script_tests.select([self.KEY, self.AGGREGATE], mapping)
        self.assertEqual(chosen, ('b.test.sh', 'c.test.sh'))

if __name__ == '__main__':
    unittest.main()
