"""The repository's own split registry owners regenerate to their committed aggregates (D-173), read from the live tree."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import generate  # noqa: E402
import generate_registry  # noqa: E402


class Repository(unittest.TestCase):
    def test_the_command_writes_and_checks_the_aggregate(self):
        self.assertEqual(generate_registry.main(['generate_registry.py', 'gate', '--check']), 0)

    def test_every_split_owner_regenerates_to_its_committed_aggregate(self):
        owners = generate_registry.owners(ROOT)
        self.assertIn('gate', owners)
        for owner in owners:
            self.assertEqual(generate_registry.assemble(ROOT, owner), (ROOT / 'config' / 'registry' / f'{owner}.json').read_text(),
                             owner)
        split = generate.targets(ROOT)['registry']
        self.assertEqual(sorted(generate_registry.render(ROOT, split)),
                         sorted(f'config/registry/{owner}.json' for owner in owners))

    def test_the_owners_the_generator_reads_stay_whole(self):
        """generate.targets and the config store's settings are read to run the generator: they are not split."""
        self.assertFalse({'generate', 'config'} & set(generate_registry.owners(ROOT)))


if __name__ == '__main__':
    unittest.main()
