"""The planner's lesson path (LP7, D-071): apply_lesson leaves an audit line and a lesson.applied event, and the lesson
reaches the next launch brief."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_lessons  # noqa: E402
from test_lessons import ROOT, config, lessons  # noqa: E402

sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import audit_chain  # noqa: E402
import forge_events  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge_doubles  # noqa: E402
import lessons_brief  # noqa: E402

DECISION = 'plan-log:2026-10-27#4'


class ApplyLessonTest(test_lessons.Fixture):
    def port(self):
        self.adapter = forge_doubles.journal('scripts/lib/lessons.py')
        self.adapter.comments = mock.Mock(side_effect=AssertionError('applying a lesson must not read PR feedback'))
        return forge_events.ForgeEvents(self.adapter, self.clock, lessons.setting('producer'), 'test')

    def test_a_proposed_lesson_is_not_in_the_brief_until_the_planner_applies_it(self):
        record, _ = self.add()
        self.assertEqual(lessons_brief.brief_lines(self.tmp, ['config/registry/x.json']), [])
        port = self.port()
        applied, outcome = lessons.apply_lesson(self.tmp, record['id'], DECISION, by='planner', clock=self.clock, port=port)
        self.assertEqual((outcome, applied['status']), ('applied', 'applied'))
        self.assertIsNone(applied['applied']['pr'])
        last = applied['trail'][-1]
        self.assertEqual((last['action'], last['by'], last['to']), ('applied', 'planner', 'applied'))
        self.assertIn(DECISION, last['note'])
        self.assertEqual(audit_chain.chain_errors(applied['trail'], 'x', lessons.setting('digest_algorithm'),
                                                  lessons.setting('genesis_digest')), [])
        events = self.adapter.read(forge_events.Channel(config.get('forge-events.repo'), None))
        self.assertEqual([e['type'] for e in events], ['lesson.applied'])
        self.assertEqual((events[0]['payload']['lesson'], events[0]['payload']['ref']), (record['id'], DECISION))
        lines = lessons_brief.brief_lines(self.tmp, ['config/registry/x.json'])
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith(record['id']))
        self.assertEqual(lessons_brief.brief_lines(self.tmp, ['products/demo/src/a.ts']), [])

    def test_applying_twice_is_a_no_op(self):
        record, _ = self.add()
        first, _ = lessons.apply_lesson(self.tmp, record['id'], DECISION, clock=self.clock)
        again, outcome = lessons.apply_lesson(self.tmp, record['id'], DECISION, clock=self.clock)
        self.assertEqual((outcome, again['trail']), ('already', first['trail']))

    def test_a_retired_or_unknown_lesson_is_refused_by_name(self):
        record, _ = self.add()
        lessons.retire(self.tmp, record['id'], 'superseded', clock=self.clock)
        with self.assertRaisesRegex(lessons.LessonError, 'cannot become'):
            lessons.apply_lesson(self.tmp, record['id'], DECISION, clock=self.clock)
        with self.assertRaisesRegex(lessons.LessonError, 'unknown lesson'):
            lessons.apply_lesson(self.tmp, 'LR-000000', DECISION, clock=self.clock)


if __name__ == '__main__':
    unittest.main()
