"""One decision as one record (D1, D-217): the front matter carries the number, the time and the proof; a record is written once.

A temporary directory and fixed values; no git, no network.
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import decision_record  # noqa: E402

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'decision-record.json').read_text())


class Record(unittest.TestCase):
    def test_the_front_matter_carries_number_time_premises_and_proof(self):
        text = decision_record.record_text(FIXTURE['number'], FIXTURE['time'], FIXTURE['text'], FIXTURE['premises'], FIXTURE['proof'])
        self.assertIn(f"number: {FIXTURE['number']}", text)
        self.assertIn(f"time: {FIXTURE['time']}", text)
        self.assertIn(f"proof: {FIXTURE['proof']}", text)
        self.assertTrue(text.startswith('---\n'))
        self.assertTrue(text.endswith(FIXTURE['text'] + '\n'))

    def test_a_record_names_what_it_supersedes_only_when_asked(self):
        # D-335: the only way an accepted record changes state is a later record's supersedes: line
        plain = decision_record.record_text('D-9', 't', 'x', 'none', 'p.py')
        self.assertNotIn('supersedes:', plain)
        text = decision_record.record_text('D-9', 't', 'x', 'none', 'p.py', 'D-7, D-1')
        self.assertIn('\nsupersedes: D-7, D-1\nproof: p.py\n---\n', text)
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                decision_record.main(['--text', 't', '--proof', 'p.py', '--supersedes', 'the old one'], root=Path(directory))
            self.assertFalse((Path(directory) / 'docs/domain/decisions').exists())

    def test_a_record_is_written_once_and_never_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = (tmp, FIXTURE['number'], FIXTURE['time'], FIXTURE['text'], FIXTURE['premises'], FIXTURE['proof'])
            path = decision_record.write(*args)
            self.assertTrue(path.is_file())
            with self.assertRaises(FileExistsError):
                decision_record.write(*args)



class NextNumberTests(unittest.TestCase):
    def test_the_next_number_is_one_past_the_table_and_the_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(decision_record.next_number(root), 1)
            (root / 'docs/domain').mkdir(parents=True)
            (root / 'docs/domain/DECISIONS.md').write_text('| D-290 | x |\n| D-012 | y |\n')
            self.assertEqual(decision_record.next_number(root), 291)
            decision_record.write(root, 'D-291', '03/11 03:20 BRT', 'text', 'none', 'p.py')
            self.assertEqual(decision_record.next_number(root), 292)


class TableRowTests(unittest.TestCase):
    """VAZÃO F75: decision-record writes the record and its DECISIONS.md row in one step."""
    def test_main_writes_the_record_and_its_row(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs/domain').mkdir(parents=True)
            (root / 'docs/domain/DECISIONS.md').write_text('# Decisions\n\n| Id | Date | Decision | Invariant | Proof | Status |\n'
                                                           '|---|---|---|---|---|---|\n| D-290 | x | y | z | t | ok |\n\nAfter.\n')
            with contextlib.redirect_stdout(io.StringIO()):
                code = decision_record.main(['--text', 'the rule', '--proof', 'scripts/tests/x.test.sh'], root=root)
            self.assertEqual(code, 0)
            self.assertTrue((root / 'docs/domain/decisions/D-291.md').is_file())
            table = (root / 'docs/domain/DECISIONS.md').read_text()
            self.assertIn('| D-291 |', table)
            self.assertLess(table.index('| D-291 |'), table.index('After.'))

    def test_status_proposed_is_written_to_front_matter_and_table_row(self):
        import contextlib
        import io
        plain = decision_record.record_text('D-9', 't', 'x', 'none', 'p.py')
        self.assertNotIn('status:', plain)
        proposed = decision_record.record_text('D-9', 't', 'x', 'none', 'p.py', status='proposed')
        self.assertIn('\nstatus: proposed\nproof: p.py\n---\n', proposed)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs/domain').mkdir(parents=True)
            (root / 'docs/domain/DECISIONS.md').write_text('# Decisions\n\n| Id | Date | Decision | Invariant | Proof | Status |\n'
                                                           '|---|---|---|---|---|---|\n| D-290 | x | y | z | t | ok |\n')
            with contextlib.redirect_stdout(io.StringIO()):
                code = decision_record.main(['--text', 'pending rule', '--proof', 'scripts/tests/x.test.sh', '--status', 'proposed'],
                                            root=root)
            self.assertEqual(code, 0)
            self.assertIn('status: proposed\n', (root / 'docs/domain/decisions/D-291.md').read_text())
            self.assertIn('| proposed |', (root / 'docs/domain/DECISIONS.md').read_text())

    def test_main_without_a_table_keeps_the_record_and_says_so(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = decision_record.main(['--text', 't', '--proof', 'p.py'], root=root)
            self.assertEqual(code, 1)
            self.assertTrue((root / 'docs/domain/decisions/D-1.md').is_file())
            self.assertIn('no row written', err.getvalue())

    def test_main_with_proposed_status_writes_status_and_proposed_row(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs/domain').mkdir(parents=True)
            (root / 'docs/domain/DECISIONS.md').write_text('# Decisions\n\n| Id | Date | Decision | Invariant | Proof | Status |\n'
                                                           '|---|---|---|---|---|---|\n| D-290 | x | y | z | t | ok |\n')
            with contextlib.redirect_stdout(io.StringIO()):
                code = decision_record.main(['--text', 'the proposal', '--proof', 'scripts/tests/test_x.py › "test_a"',
                                             '--status', 'proposed'], root=root)
            self.assertEqual(code, 0)
            record = (root / 'docs/domain/decisions/D-291.md').read_text()
            self.assertIn('\nstatus: proposed\nproof: scripts/tests/test_x.py › "test_a"\n', record)
            table = (root / 'docs/domain/DECISIONS.md').read_text()
            self.assertIn('| `scripts/tests/test_x.py` › "test_a" | proposed |', table)


if __name__ == '__main__':
    unittest.main()
