"""Retro ingestion (LR1): the KD1 and GV1 retros and a synthetic one; idempotent, registry-driven."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import lesson_ingest  # noqa: E402
import lessons  # noqa: E402

RETRO = """# X retro

## 3. Execution
1. not a lesson, wrong section

## 5. Lessons: change, owner
1. Registry keys and their readers land in the same commit; add a helper (F1). Owner: engine lane.
2. **Brief**: name the principle items.
   It spans two lines. Owner: A Torre.
3. Run `scripts/lib/x.py` through the gate's wrapper. Owner: nobody known.

## 6. After
1. also not a lesson
"""


class Clock:
    def __init__(self):
        self.moment = datetime(2026, 10, 27, 3, 0, tzinfo=timezone.utc)

    def now(self):
        self.moment += timedelta(seconds=1)
        return self.moment


class ParseTest(unittest.TestCase):
    def parse(self):
        return lesson_ingest.parse(RETRO, 'X1', 'docs/units/X1/retro.md')

    def test_only_the_lessons_section_is_read(self):
        self.assertEqual([c['ref'] for c in self.parse()], ['L1', 'L2', 'L3'])

    def test_owner_class_and_kind_come_from_the_registry_lists(self):
        first, second, third = self.parse()
        self.assertEqual((first['owner'], first['cls']), ('engine-lane', 'ordering'))
        self.assertEqual((second['owner'], second['cls'], second['kind']), ('a-torre', 'brief', 'brief-template'))
        self.assertEqual((third['owner'], third['cls']), (config.get('lessons.unknown_owner'), 'env'))

    def test_a_continuation_line_joins_its_item_and_markup_is_dropped(self):
        second = self.parse()[1]
        self.assertIn('It spans two lines', second['change'])
        self.assertNotIn('**', second['change'])
        self.assertEqual(second['title'], 'Brief: name the principle items')

    def test_identifiers_keep_their_underscores_and_a_long_title_ends_on_a_word(self):
        found = lesson_ingest.parse('## 5. Lessons\n1. Set `OU_CONFIG_STORE` in the test ' + 'word ' * 40 + '. Owner: x.', 'X1', 'r.md')[0]
        self.assertIn('OU_CONFIG_STORE', found['change'])
        self.assertLessEqual(len(found['title']), config.get('lessons.title_max_chars'))
        self.assertTrue(found['title'].endswith('word'))

    def test_backticked_paths_become_the_area(self):
        self.assertEqual(self.parse()[2]['area'], ['scripts/lib/x.py'])

    def test_a_class_with_a_registered_signal_carries_it(self):
        self.assertEqual(self.parse()[0]['signals'][0]['stage'], 'structure check')

    def test_a_retro_comment_is_found_by_its_title(self):
        comments = [{'body': 'hello'}, {'body': '## RETRO\n\n## 5. Lessons\n1. x'}]
        self.assertTrue(lesson_ingest.comment_text(comments).startswith('## RETRO'))
        self.assertIsNone(lesson_ingest.comment_text([{'body': 'nope'}]))


class IngestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(ROOT / 'contracts' / 'lessons', self.tmp / 'contracts' / 'lessons')
        self.clock = Clock()

    def test_ingesting_twice_registers_each_item_once(self):
        found = lesson_ingest.parse(RETRO, 'X1', 'docs/units/X1/retro.md')
        first = lesson_ingest.ingest(self.tmp, found, clock=self.clock)
        second = lesson_ingest.ingest(self.tmp, found, clock=self.clock)
        self.assertEqual([o for _, o in first], ['created'] * 3)
        self.assertEqual([o for _, o in second], ['exists'] * 3)
        self.assertEqual(lessons.check(self.tmp)[1], [])

    def test_an_edited_retro_does_not_duplicate_a_lesson(self):
        lesson_ingest.ingest(self.tmp, lesson_ingest.parse(RETRO, 'X1', 'docs/units/X1/retro.md'), clock=self.clock)
        edited = RETRO.replace('Registry keys and their readers land', 'Keys and readers land')
        outcome = lesson_ingest.ingest(self.tmp, lesson_ingest.parse(edited, 'X1', 'docs/units/X1/retro.md'), clock=self.clock)
        self.assertEqual(outcome[0][1], 'exists')
        self.assertEqual(len(lessons.load(self.tmp)[0]), 3)


    def test_the_cli_reads_a_retro_file_twice_without_a_second_record(self):
        import contextlib, io
        retro = self.tmp / 'docs' / 'units' / 'X1' / 'retro.md'
        retro.parent.mkdir(parents=True)
        retro.write_text(RETRO)
        for expected in ('created', 'exists'):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = lessons.main(['--root', str(self.tmp), 'ingest', '--no-emit'], self.tmp)
            self.assertEqual(code, 0)
            self.assertEqual(out.getvalue().split().count(expected), 3)
        self.assertEqual(len(lessons.load(self.tmp)[0]), 3)


class SeedTest(unittest.TestCase):
    def test_the_kd1_and_gv1_retros_yield_their_numbered_lessons(self):
        found = lesson_ingest.candidates_of_files(ROOT)
        by_unit = {}
        for candidate in found:
            by_unit.setdefault(candidate['unit'], []).append(candidate)
        self.assertEqual(len(by_unit['KD1']), 9)
        self.assertEqual(len(by_unit['GV1']), 5)
        for candidate in found:
            self.assertIn(candidate['cls'], config.get('lessons.classes'))
            self.assertIn(candidate['owner'], config.get('lessons.owners'))


if __name__ == '__main__':
    unittest.main()
