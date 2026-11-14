"""Writes docs/process/templates/ from the intake registry (D-205). Hermetic: no network, temporary folders only."""
import copy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import intake_templates  # noqa: E402


class Drift(unittest.TestCase):
    def test_committed_templates_are_the_registry_render(self):
        self.assertEqual(intake_templates.check(), [])

    def test_every_registry_section_is_in_its_template(self):
        for name, wanted in intake_templates.registry_sections().items():
            self.assertTrue(set(wanted) <= set(intake_templates.headings(name)), name)

    def test_a_hand_edit_is_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(ROOT / 'docs' / 'process' / 'templates', Path(tmp) / 'docs' / 'process' / 'templates')
            edited = Path(tmp) / 'docs' / 'process' / 'templates' / 'intake.md'
            edited.write_text(edited.read_text() + '\nhand edit\n')
            problems = intake_templates.check(root=tmp)
        self.assertEqual(len(problems), 1)
        self.assertIn('differs from the registry render', problems[0])

    def test_a_section_the_checker_reads_must_be_in_its_template(self):
        sections = copy.deepcopy(config.get('intake.template_sections'))
        intake = next(item for item in sections if item['name'] == 'intake')
        intake['sections'] = [s for s in intake['sections'] if s['heading'] != 'Lacunas']
        problems = intake_templates.check(sections=sections)
        self.assertTrue(any('"Lacunas"' in problem for problem in problems), problems)

    def test_a_missing_template_is_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            problems = intake_templates.check(root=tmp)
        self.assertEqual(len(problems), len(intake_templates.TEMPLATES))


class Script(unittest.TestCase):
    def test_check_passes_on_the_repository(self):
        self.assertEqual(intake_templates.main(['--check']), 0)

    def test_writing_reproduces_the_committed_files(self):
        before = {name: intake_templates.template_file(name).read_text() for name in intake_templates.TEMPLATES}
        self.assertEqual(intake_templates.main([]), 0)
        self.assertEqual({name: intake_templates.template_file(name).read_text() for name in intake_templates.TEMPLATES}, before)


if __name__ == '__main__':
    unittest.main()
