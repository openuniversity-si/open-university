"""Blameless postmortems name an existing check and an existing test (D-069 item 9; postmortem_check.py).

Fixture trees in a temporary directory; the registry is read from the repository, no network, no clock.
"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import postmortem_check  # noqa: E402

DIR = config.get('process.postmortem_dir')
HEADING = config.get('process.postmortem_check_heading')
CHECK, TEST = config.get('process.postmortem_ref_check'), config.get('process.postmortem_ref_test')
CHECK_FILE = 'scripts/lib/a_check.py'
TEST_FILE = 'scripts/tests/test_a_check.py'
GOOD_TEST = 'test_the_class_stays_closed'


def postmortem(*refs, heading=HEADING):
    lines = [f'- {label}: {value}' for label, value in refs]
    return f'# Postmortem\n\n## What happened\n\nText.\n\n## {heading}\n\n' + '\n'.join(lines) + '\n'


class PostmortemCheck(unittest.TestCase):
    def tree(self, files):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / CHECK_FILE).parent.mkdir(parents=True)
        (root / CHECK_FILE).write_text('CHECK = True\n')
        (root / TEST_FILE).parent.mkdir(parents=True)
        (root / TEST_FILE).write_text(f'class T:\n    def {GOOD_TEST}(self):\n        pass\n')
        for name, text in files.items():
            (root / DIR / name).parent.mkdir(parents=True, exist_ok=True)
            (root / DIR / name).write_text(text)
        return root

    def test_the_repository_postmortems_name_existing_checks_and_tests(self):
        self.assertEqual(postmortem_check.check(ROOT), [])

    def test_a_postmortem_without_the_section_is_refused(self):
        root = self.tree({'2026-01-01-no-section.md': '# Postmortem\n\n## What happened\n\nText.\n'})
        errors = postmortem_check.check(root)
        self.assertEqual(len(errors), 1)
        self.assertIn(HEADING, errors[0])

    def test_a_section_naming_no_check_or_no_test_is_refused(self):
        root = self.tree({
            '2026-01-01-no-check.md': postmortem((TEST, f'{TEST_FILE}::{GOOD_TEST}')),
            '2026-01-02-no-test.md': postmortem((CHECK, CHECK_FILE)),
        })
        messages = ' '.join(postmortem_check.check(root))
        self.assertIn(f'names no check ("- {CHECK}: <file>")', messages)
        self.assertIn(f'names no test ("- {TEST}: <file>::<name>")', messages)

    def test_a_missing_check_file_is_refused(self):
        root = self.tree({'2026-01-01-missing-check.md': postmortem((CHECK, 'scripts/lib/gone.py'),
                                                                    (TEST, f'{TEST_FILE}::{GOOD_TEST}'))})
        self.assertEqual(postmortem_check.check(root), [
            f'{DIR}/2026-01-01-missing-check.md: check scripts/lib/gone.py does not exist'])

    def test_a_test_name_that_is_not_defined_is_refused(self):
        root = self.tree({'2026-01-01-missing-test.md': postmortem((CHECK, CHECK_FILE),
                                                                   (TEST, f'{TEST_FILE}::test_not_written'))})
        self.assertEqual(postmortem_check.check(root), [
            f'{DIR}/2026-01-01-missing-test.md: test {TEST_FILE}::test_not_written does not exist'])

    def test_a_test_name_only_mentioned_in_a_comment_is_refused(self):
        root = self.tree({'2026-01-01-mention.md': postmortem((CHECK, CHECK_FILE), (TEST, f'{TEST_FILE}::{GOOD_TEST}'))})
        (root / TEST_FILE).write_text(f'# {GOOD_TEST} was planned\n')
        errors = postmortem_check.check(root)
        self.assertEqual(len(errors), 1)
        self.assertIn('does not exist', errors[0])

    def test_a_complete_postmortem_passes(self):
        root = self.tree({'2026-01-01-complete.md': postmortem((CHECK, CHECK_FILE), (TEST, f'{TEST_FILE}::{GOOD_TEST}'))})
        self.assertEqual(postmortem_check.check(root), [])

    def test_a_bad_file_name_is_refused(self):
        root = self.tree({'not-dated.md': postmortem((CHECK, CHECK_FILE), (TEST, f'{TEST_FILE}::{GOOD_TEST}'))})
        errors = postmortem_check.check(root)
        self.assertEqual(len(errors), 1)
        self.assertIn('YYYY-MM-DD-slug.md', errors[0])

    def test_the_template_is_not_an_incident_and_uses_the_heading(self):
        root = self.tree({config.get('process.postmortem_template'): '# Template\n\nNo section here.\n'})
        self.assertEqual(postmortem_check.check(root), [])
        template = (ROOT / DIR / config.get('process.postmortem_template')).read_text(encoding='utf-8')
        self.assertIn(f'## {HEADING}', template)


if __name__ == '__main__':
    unittest.main(verbosity=1)
