"""The generated aggregates (D-067, D-069 item 1, plan v3 U1): each is a pure function of the manifests and the
registry, so no pull request writes it. The context map, contexts, intents and gate-suite renames left with Open
University's cells (OU-DECOUPLE F4 (D-111)); the unit status remains. Fixture repositories in a temporary directory;
no network, no clock.
"""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import generate  # noqa: E402
import generate_status  # noqa: E402


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / 'config/registry', self.root / 'config/registry')
        shutil.copytree(ROOT / 'contracts', self.root / 'contracts', ignore=shutil.ignore_patterns('generated'))
        self.unit('alpha-domain', 'alpha')
        self.unit('beta-domain', 'beta')

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, document):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(document if isinstance(document, str) else json.dumps(document, indent=2) + '\n')

    def unit(self, unit, cell):
        self.write(f'units/{unit}/unit.json', {'id': unit, 'purpose': 'A test unit.', 'cell': cell,
                                                 'owner': 'engine-lane', 'paths': [f'src/{unit}/**']})

    def generate(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = generate.main([*argv, '--root', str(self.root)])
        return code, out.getvalue()


class Status(Fixture):
    def test_one_row_per_unit_with_its_slots_and_a_count_line(self):
        manifest = json.loads((self.root / 'units/alpha-domain/unit.json').read_text())
        manifest.update(contract={'entry': 'index.ts', 'version': '1.2.0'}, battery={'command': 'scripts/unit-battery alpha-domain'},
                        intents=['x.y'])
        self.write('units/alpha-domain/unit.json', manifest)
        text = generate_status.render(self.root, None)[generate_status.PATH]
        self.assertIn('| `alpha-domain` | alpha | engine-lane | 1 | `1.2.0` | `scripts/unit-battery alpha-domain` | 1 |', text)
        self.assertIn('| `beta-domain` | beta | engine-lane | 1 | — | — | — |', text)
        self.assertIn('2 units; 1 with a contract, 1 with a battery.', text)

    def test_the_hand_written_step_log_is_not_replaced(self):
        self.assertTrue((ROOT / 'docs/process/roadmap/STATUS.md').is_file())
        self.assertNotEqual(generate_status.PATH, 'docs/process/roadmap/STATUS.md')
        self.assertFalse((ROOT / generate_status.PATH).exists(), 'the unit status is generated, not committed (V4)')


if __name__ == '__main__':
    unittest.main()
