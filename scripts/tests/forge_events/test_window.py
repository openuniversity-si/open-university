"""D-085: repository-channel readers use the shared journal window."""
from pathlib import Path
import unittest


class EveryReaderUsesTheWindow(unittest.TestCase):
    """D-085: no module of scripts/lib reads the repository channel whole again; each goes through read_recent."""

    WHOLE = ('.read(repo)', '.read(self.repo, None', ".read(config.get('forge-events.repo'), None",
             '.read(repo, None, kinds')

    def test_no_library_module_reads_the_repository_channel_whole(self):
        lib = Path(__file__).resolve().parents[1].parent / 'lib'
        found = [f'{path.name}: {needle}' for path in sorted(lib.glob('*.py'))
                 for needle in self.WHOLE if needle in path.read_text()]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
