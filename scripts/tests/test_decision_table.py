"""The table rows of the decision records (D1, D-217): one record gives one row of six columns, the pipes in its text are escaped,
rows come in number order, and a record without its front matter is refused. Fixed text; no files, no git.
"""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import decision_table  # noqa: E402

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'decision-table.json').read_text())


class Check(unittest.TestCase):
    def test_a_record_with_its_row_is_not_missing(self):
        record = decision_table.parse(FIXTURE['record'])
        self.assertEqual(decision_table.missing([record], FIXTURE['table']), [])

    def test_a_record_without_its_row_is_reported_by_number(self):
        record = decision_table.parse(FIXTURE['record'])
        self.assertEqual(decision_table.missing([record], FIXTURE['table_missing']), [record['number']])


class Row(unittest.TestCase):
    """A rendered row passes the structure check's row rules: six columns, and a proof it reads as a linked test."""

    def record(self, premises, proof):
        return decision_table.parse(FIXTURE['record'].replace('premises: none', f'premises: {premises}')
                                    .replace('proof: scripts/tests/decision-table.test.sh', f'proof: {proof}'))

    def test_a_pipe_in_the_premises_keeps_six_columns(self):
        line = decision_table.row(self.record('none | process', 'scripts/tests/decision-table.test.sh'))
        self.assertEqual(line.count('|'), FIXTURE['pipes_per_row'])

    def test_a_bare_test_path_is_quoted_and_a_test_script_or_quoted_path_is_kept(self):
        cases = {'scripts/tests/test_repeats.py': '`scripts/tests/test_repeats.py`',
                 'scripts/tests/decision-table.test.sh': 'scripts/tests/decision-table.test.sh',
                 '`scripts/tests/test_repeats.py` (Claims)': '`scripts/tests/test_repeats.py` (Claims)'}
        for proof, cell in cases.items():
            self.assertIn(f'| {cell} | recorded |', decision_table.row(self.record('none', proof)))


    def test_a_relative_link_is_moved_from_the_records_folder_to_the_tables(self):
        record = dict(decision_table.parse(FIXTURE['record']), body='See [the plan](../../units/U/plan.md), [D-1](D-1.md), [web](https://x.y/z) and [here](#a).')
        self.assertIn('[the plan](../units/U/plan.md), [D-1](decisions/D-1.md), [web](https://x.y/z) and [here](#a).', decision_table.row(record))

    def test_a_proposed_record_renders_status_proposed(self):
        record = decision_table.parse(FIXTURE['record'].replace('premises: none\n', 'status: proposed\npremises: none\n'))
        self.assertTrue(decision_table.row(record).endswith('| proposed |'))

FIRST = len(FIXTURE['table'])  # an id far above the fixture's own D-2 row
LATER_NUMBER, OLDER_NUMBER = FIRST + True, FIRST - True
NEWEST_NUMBER = LATER_NUMBER + True
LATER, OLDER, NEWEST, PREDATES = (f'D-{n}' for n in (LATER_NUMBER, OLDER_NUMBER, NEWEST_NUMBER, 0))


class Handwritten(unittest.TestCase):
    """The records are the only path to a new decision: a row typed into the table with no record is refused."""

    def records(self, *numbers):
        # numbers are ids relative to the fixture's own: first, then later ones
        return [decision_table.parse(FIXTURE['record'].replace(f"number: {decision_table.parse(FIXTURE['record'])['number']}\n", f'number: D-{number}\n')) for number in numbers]

    def test_a_row_after_the_first_record_with_no_record_is_refused(self):
        table = FIXTURE['table'] + f'\n| {LATER} | typed | by hand |'
        self.assertEqual(decision_table.handwritten(table, self.records(FIRST)), [LATER])

    def test_a_row_with_its_record_is_not_handwritten(self):
        table = FIXTURE['table'] + f'\n| {LATER} | typed | by hand |'
        self.assertEqual(decision_table.handwritten(table, self.records(FIRST, LATER_NUMBER)), [])

    def test_a_grandfathered_row_is_not_refused_and_a_new_one_still_is(self):
        table = f'\n| {OLDER} | old | by hand |\n| {NEWEST} | new | by hand |'
        self.assertEqual(decision_table.handwritten(table, self.records(FIRST), [OLDER]), [NEWEST])

    def test_a_row_older_than_the_first_record_predates_the_records(self):
        self.assertEqual(decision_table.handwritten(f'\n| {PREDATES} | old | by hand |', self.records(FIRST)), [])

    def test_with_no_record_nothing_is_judged(self):
        self.assertEqual(decision_table.handwritten(f'\n| {PREDATES} | old | by hand |', []), [])


class Write(unittest.TestCase):
    def test_the_missing_row_is_added_and_the_others_are_kept(self):
        record = decision_table.parse(FIXTURE['record'])
        out = decision_table.with_missing(FIXTURE['table_missing'], [record])
        self.assertIn(FIXTURE['row'], out.splitlines())
        self.assertIn('| D-99 | other |', out.splitlines())

    def test_a_second_write_adds_nothing(self):
        record = decision_table.parse(FIXTURE['record'])
        once = decision_table.with_missing(FIXTURE['table_missing'], [record])
        self.assertEqual(decision_table.with_missing(once, [record]), once)


class Columns(unittest.TestCase):
    def test_a_pipe_in_the_text_keeps_the_row_at_six_columns(self):
        record = decision_table.parse(FIXTURE['record'].replace('with a pipe', 'with | a pipe and | another'))
        self.assertEqual(decision_table.row(record).count('|'), FIXTURE['pipes_per_row'])


class Rows(unittest.TestCase):
    def test_one_record_gives_one_row_with_pipes_escaped(self):
        self.assertEqual(decision_table.row(decision_table.parse(FIXTURE['record'])), FIXTURE['row'])

    def test_rows_come_in_number_order(self):
        records = [decision_table.parse(FIXTURE['record'].replace('number: D-2', f'number: {number}')) for number in FIXTURE['order']]
        ids = [row.split('|')[1].strip() for row in decision_table.render(records)]
        self.assertEqual(ids, sorted(FIXTURE['order'], key=lambda item: int(item.split('-')[1])))

    def test_a_record_without_its_front_matter_is_refused(self):
        with self.assertRaises(ValueError):
            decision_table.parse('no front matter here\n')


class Duplicates(unittest.TestCase):
    def test_an_id_written_twice_is_named_once_in_number_order(self):
        table = '| Id |\n|---|\n| D-173 | a |\n| D-9 | b |\n| D-173 | c |\n| D-165 | d |\n| D-165 | e |\n'
        self.assertEqual(decision_table.duplicates(table), ['D-165', 'D-173'])

    def test_check_exits_one_and_names_the_duplicate(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'docs/domain').mkdir(parents=True)
            Path(root, 'docs/domain/DECISIONS.md').write_text('| Id |\n|---|\n| D-7 | a |\n| D-7 | b |\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = decision_table.main(['--check'], root=root)
        self.assertEqual(code, 1)
        self.assertIn('D-7: written twice in DECISIONS.md', out.getvalue())


class LiveRegister(unittest.TestCase):
    def test_the_register_names_each_id_once(self):
        text = (ROOT / 'docs' / 'domain' / 'DECISIONS.md').read_text()
        self.assertEqual(decision_table.duplicates(text), [])


class Renumbering(unittest.TestCase):
    def test_an_id_the_previous_register_had_and_this_one_lacks_is_named(self):
        previous = '| D-1 | a |\n| D-2 | b |\n| D-3 | c |\n'
        table = '| D-1 | a |\n| D-3 | c |\n| D-4 | d |\n'
        self.assertEqual(decision_table.lost(previous, table), ['D-2'])

    def test_a_register_that_only_adds_ids_loses_none(self):
        self.assertEqual(decision_table.lost('| D-1 | a |\n', '| D-1 | a |\n| D-2 | b |\n'), [])

    def test_check_exits_one_when_an_id_is_renumbered_away(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'docs/domain').mkdir(parents=True)
            table = Path(root, 'docs/domain/DECISIONS.md')
            table.write_text('| Id |\n|---|\n| D-1 | a |\n| D-3 | c |\n')
            previous = Path(root, 'previous.md')
            previous.write_text('| Id |\n|---|\n| D-1 | a |\n| D-2 | b |\n| D-3 | c |\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = decision_table.main(['--check', '--previous', str(previous)], root=root)
        self.assertEqual(code, 1)
        self.assertIn('D-2: the register had it and this one does not', out.getvalue())


class WriteRefusesAClash(unittest.TestCase):
    def test_a_record_whose_number_has_another_row_is_not_written(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            Path(root, 'docs/domain/decisions').mkdir(parents=True)
            Path(root, 'docs/domain/decisions/D-5.md').write_text('---\nnumber: D-5\ntime: 01/11 00:00 BRT\npremises: none\nproof: scripts/tests/decision-table.test.sh\n---\nnew rule\n')
            table = Path(root, 'docs/domain/DECISIONS.md')
            table.write_text('| Id |\n|---|\n| D-5 | old rule |\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = decision_table.main(['--write'], root=root)
            self.assertEqual(code, 1)
            self.assertEqual(table.read_text(), '| Id |\n|---|\n| D-5 | old rule |\n')
            self.assertIn('D-5: the register has another row under this number', out.getvalue())


if __name__ == '__main__':
    unittest.main()
