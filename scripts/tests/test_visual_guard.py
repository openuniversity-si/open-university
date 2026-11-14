"""SG1: STATUS.md and undeclared visual edits are refused (D-006, D-069). Hermetic: temporary git repositories, no network."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import visual_guard  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

VISUAL = ['products/demo/src/**/*.css', 'products/demo/src/ui/**/*.tsx']  # the engine registry declares none (D-113)
CAP = '---\nstatus: approved 2026-10-26\nvisual: {visual}\n{figma}---\n'


def git(root, *args):
    subprocess.run(['git', '-C', str(root), '-c', 'user.email=t@t', '-c', 'user.name=t', *args], check=True, capture_output=True)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        fixture_copy.registry(self.root)
        owner = self.root / 'config' / 'registry' / 'structure.json'
        registry = json.loads(owner.read_text())
        registry['properties']['structure.visual_paths']['default'] = VISUAL
        owner.write_text(json.dumps(registry, indent=2) + '\n')
        self.write('products/demo/src/ui/Card.tsx', 'export function Card() {\n  return <div className="a">x</div>\n}\n')
        self.write('products/demo/src/ui/util.tsx', 'export const total = (a: number) => a + 1\n')
        self.write('products/demo/src/ui/card.css', '.a { color: red }\n')
        self.write('docs/process/roadmap/STATUS.md', 'log\n')
        self.write('docs/capabilities/CAP-900-plain.md', CAP.format(visual='no', figma=''))
        self.write('docs/capabilities/CAP-901-nofigma.md', CAP.format(visual='yes', figma=''))
        self.write('docs/capabilities/CAP-902-figma.md', CAP.format(visual='yes', figma='figma: 12:34\n'))
        git(self.root, 'init', '-q', '-b', 'base')
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-qm', 'base')
        git(self.root, 'checkout', '-qb', 'work')

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def run_check(self, edits, body='', branch='mod/feature'):
        for path, text in edits.items():
            self.write(path, text)
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-qm', 'change')
        files = subprocess.run(['git', '-C', str(self.root), 'diff', '--name-only', 'base...HEAD'],
                               capture_output=True, text=True).stdout.split()
        return visual_guard.check(self.root, 'base', body, files, branch)


class Protected(Fixture):
    def test_status_outside_integration_is_refused(self):
        errors, _ = self.run_check({'docs/process/roadmap/STATUS.md': 'edited\n'})
        self.assertEqual(len(errors), 1)
        self.assertIn('STATUS.md', errors[0])

    def test_generated_aggregates_are_refused(self):
        errors, _ = self.run_check({'docs/architecture/CONTEXTS.md': 'x\n', 'docs/domain/INTENTS.md': 'y\n'})
        self.assertEqual(len(errors), 2)

    def test_integration_branch_may_change_them(self):
        errors, _ = self.run_check({'docs/process/roadmap/STATUS.md': 'edited\n'}, branch='mod/roadmap-integration')
        self.assertEqual(errors, [])

    def test_ordinary_file_passes(self):
        self.assertEqual(self.run_check({'docs/note.md': 'n\n'}), ([], []))


class Visual(Fixture):
    def test_css_without_capability_is_refused(self):
        errors, _ = self.run_check({'products/demo/src/ui/card.css': '.a { color: blue }\n'})
        self.assertEqual(len(errors), 1)
        self.assertIn('no "Capability: CAP-NNN"', errors[0])

    def test_markup_change_with_non_visual_capability_is_refused(self):
        errors, _ = self.run_check({'products/demo/src/ui/Card.tsx': 'export function Card() {\n  return <div className="b">x</div>\n}\n'},
                                   body='Capability: CAP-900')
        self.assertIn('not "visual: yes"', errors[0])

    def test_visual_capability_without_figma_is_refused(self):
        errors, _ = self.run_check({'products/demo/src/ui/card.css': '.a { color: blue }\n'}, body='Capability: CAP-901')
        self.assertIn('no "figma:" node', errors[0])

    def test_visual_capability_with_figma_passes(self):
        errors, _ = self.run_check({'products/demo/src/ui/card.css': '.a { color: blue }\n'}, body='Capability: CAP-902')
        self.assertEqual(errors, [])

    def test_logic_only_tsx_passes_without_capability(self):
        self.assertEqual(self.run_check({'products/demo/src/ui/util.tsx': 'export const total = (a: number) => a + 2\n'}), ([], []))

    def test_tsx_test_files_never_count(self):
        self.assertEqual(self.run_check({'products/demo/src/ui/Card.test.tsx': 'it("x", () => <div className="z" />)\n'}), ([], []))

    def test_css_outside_visual_paths_passes(self):
        self.assertEqual(self.run_check({'docs/site.css': 'a{}\n'}), ([], []))

    def retire_fixture(self):
        self.write('units/ui/unit.json', '{"id": "ui", "owner": "ui-lane", "paths": ["products/demo/src/ui/**"]}\n')
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-qm', 'a unit')
        git(self.root, 'branch', '-qf', 'base')

    def test_d112_a_deleted_file_of_a_retired_unit_is_not_visual(self):
        self.retire_fixture()
        (self.root / 'units/ui/unit.json').unlink()
        (self.root / 'products/demo/src/ui/Card.tsx').unlink()
        (self.root / 'products/demo/src/ui/card.css').unlink()
        self.assertEqual(self.run_check({}), ([], []))

    def test_d112_a_deleted_file_of_a_live_unit_is_still_visual(self):
        self.retire_fixture()
        (self.root / 'products/demo/src/ui/card.css').unlink()
        errors, _ = self.run_check({})
        self.assertIn('products/demo/src/ui/card.css', errors[0])

    def test_f5_the_engine_registry_declares_no_visual_path(self):
        """OU-DECOUPLE F5 (D-113): with the engine's own registry, no file is a visual change."""
        (self.root / 'config' / 'registry').joinpath('structure.json').write_text((ROOT / 'config/registry/structure.json').read_text())
        self.assertEqual(self.run_check({'products/demo/src/ui/card.css': '.a { color: blue }\n'}), ([], []))

    def test_no_changed_files_judges_nothing(self):
        self.assertEqual(visual_guard.check(self.root, 'base', '', [], None), ([], []))


if __name__ == '__main__':
    unittest.main()
