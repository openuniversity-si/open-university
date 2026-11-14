"""The registry-<owner> targets (GATE-SPEED, D-095) on fixture checkouts: a registry file assembled from one file per key
equals its source content with keys in name order; a key named outside its owner or a header holding properties stops
the generator; two branches that each add a key touch different files, and the aggregate of their merge is the
regeneration with both keys; the repository's own split owners regenerate to their committed aggregates. No network."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import generate  # noqa: E402
import generate_registry  # noqa: E402

HEADER = {'$id': 'config/registry/demo.json', 'x-owner': 'demo', 'type': 'object'}


def parameter(default):
    return {'type': 'boolean', 'default': default, 'x-unit': 'flag', 'description': 'a flag', 'x-readers': ['x.py']}


class Split(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.folder = self.root / 'config' / 'registry' / 'demo'
        self.folder.mkdir(parents=True)
        (self.folder / generate_registry.HEADER).write_text(json.dumps(HEADER))

    def add(self, key, default=True):
        (self.folder / f'{key}.json').write_text(json.dumps(parameter(default)))

    def test_the_aggregate_is_the_header_and_every_key_in_name_order(self):
        self.add('demo.zeta')
        self.add('demo.alpha', False)
        data = json.loads(generate_registry.assemble(self.root, 'demo'))
        self.assertEqual(list(data['properties']), ['demo.alpha', 'demo.zeta'])
        self.assertEqual({key: value for key, value in data.items() if key != 'properties'}, HEADER)
        self.assertEqual(data['properties']['demo.alpha'], parameter(False))

    def test_split_then_assemble_round_trips_the_content(self):
        source = self.root / 'config' / 'registry' / 'other.json'
        source.write_text(json.dumps(dict(HEADER, properties={'other.b': parameter(True), 'other.a': parameter(False)})))
        generate_registry.split(self.root, 'other')
        self.assertEqual(json.loads(generate_registry.assemble(self.root, 'other')), json.loads(source.read_text()))

    def test_a_key_outside_its_owner_or_a_header_with_properties_stops_it(self):
        self.add('elsewhere.key')
        with self.assertRaises(generate_registry.RegistrySplitError):
            generate_registry.assemble(self.root, 'demo')
        (self.folder / 'elsewhere.key.json').unlink()
        (self.folder / generate_registry.HEADER).write_text(json.dumps(dict(HEADER, properties={})))
        with self.assertRaises(generate_registry.RegistrySplitError):
            generate_registry.assemble(self.root, 'demo')

    def test_two_additions_are_two_files_and_the_merge_is_the_regeneration(self):
        self.add('demo.base')
        ours, theirs = 'demo.ours', 'demo.theirs'
        self.add(ours)
        self.add(theirs)  # the merged sources: each branch added one file, nothing to resolve
        self.assertEqual(sorted(json.loads(generate_registry.assemble(self.root, 'demo'))['properties']),
                         ['demo.base', ours, theirs])


if __name__ == '__main__':
    unittest.main()
