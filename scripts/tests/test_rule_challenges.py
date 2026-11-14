"""Rule-challenge records (D-138): the format check and the listing. Hermetic: throwaway folders."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import rule_challenges  # noqa: E402


def record(number='001', grade='2', status='open', decision='', d='none'):
    return (f'# RC-{number} — a rule\n- Grade: {grade}\n- Status: {status}\n- Rule: r\n- Evidence: e\n- Harm: h\n'
            f'- Proposal: p\n- Impact: i\n- Decision: {decision}\n- D: {d}\n')


class RuleChallengeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / rule_challenges.FOLDER
        self.folder.mkdir(parents=True)

    def put(self, text, number='001'):
        (self.folder / f'RC-{number}.md').write_text(text)

    def problems(self):
        return rule_challenges.check(self.tmp.name)

    def test_sound_records_pass(self):
        self.put(record())
        self.put(record('002', '1', 'changed', 'done by the executor', 'D-200'), '002')
        self.assertEqual(self.problems(), [])

    def test_the_repository_records_are_sound(self):
        self.assertEqual(rule_challenges.check(ROOT), [])

    def test_a_missing_line_is_named(self):
        self.put(record().replace('- Harm: h\n', ''))
        self.assertIn('Harm', self.problems()[0])

    def test_unknown_grade_and_status_fail(self):
        self.put(record(grade='9', status='maybe'))
        text = ' '.join(self.problems())
        self.assertIn('Grade', text)
        self.assertIn('Status', text)

    def test_a_decided_record_needs_a_decision(self):
        self.put(record(status='lifted'))
        self.assertIn('needs a Decision', self.problems()[0])

    def test_a_grade_one_change_needs_a_d_number(self):
        self.put(record(grade='1', status='changed', decision='mine'))
        self.assertIn('D-NNN', self.problems()[0])

    def test_a_grade_three_changes_only_by_daniel(self):
        self.put(record(grade='3', status='lifted', decision='the executor lifted it'))
        self.assertIn('only by Daniel', self.problems()[0])
        self.put(record(grade='3', status='lifted', decision='Daniel, in chat'))
        self.assertEqual(self.problems(), [])

    def test_numbers_are_consecutive(self):
        self.put(record())
        self.put(record(number='003'), '003')
        self.assertIn('next free', self.problems()[0])

    def test_open_grade_two_and_three_list_first(self):
        self.put(record(grade='1', status='changed', decision='x', d='D-200'))
        self.put(record('002', '2', 'open'), '002')
        self.assertIn('RC-002', rule_challenges.listing(self.tmp.name)[0])


if __name__ == '__main__':
    unittest.main()
