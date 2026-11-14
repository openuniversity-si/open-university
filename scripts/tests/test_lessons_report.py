"""Pattern aggregator and brief query (LR1): fixture registry in a temp dir, injected clock, in-memory log. No network."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import forge_events  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge_doubles  # noqa: E402
import lessons  # noqa: E402
import lessons_brief  # noqa: E402
import lessons_report  # noqa: E402

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
STAGE = 'structure check'


class Clock:
    def __init__(self):
        self.moment = START

    def now(self):
        self.moment += timedelta(seconds=1)
        return self.moment


def failed(cost):
    return {'type': 'gate.failed', 'occurred_at': lessons.now_text(START), 'payload': {'stages': [{'name': STAGE, 'result': 'FAIL', 'duration_ms': cost, 'class': 'code'}], 'failing_tests': []}}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(ROOT / 'contracts' / 'lessons', self.tmp / 'contracts' / 'lessons')
        self.clock = Clock()
        self.classes, self.kinds, self.owners = (config.get(f'lessons.{k}') for k in ('classes', 'kinds', 'owners'))
        self.port = forge_events.ForgeEvents(forge_doubles.journal('scripts/lib/lessons.py'), self.clock, 'lessons', 'test')

    def add(self, title, cls, unit='GV1', area=(), signals=()):
        record, _ = lessons.add(self.tmp, title, unit, 'r.md', 5, title[:2], self.classes[cls], self.kinds[0], f'do {title}', self.owners[0], area, signals, clock=self.clock)
        return record

    def applied(self, record):
        return lessons.apply(self.tmp, record['id'], 3, 'x', clock=self.clock)


class ReportTest(Fixture):
    def test_classes_rank_by_time_lost_then_occurrences_then_lessons(self):
        signal = {'event': 'gate.failed', 'stage': STAGE, 'pattern': None}
        self.add('costly one', 0, signals=[signal])
        self.add('quiet one', 1)
        self.add('quiet two', 1, unit='KD1')
        records, _ = lessons.load(self.tmp)
        rows = lessons_report.classes(records, [failed(3000), failed(2000)])
        self.assertEqual([r['class'] for r in rows], [self.classes[0], self.classes[1]])
        self.assertEqual((rows[0]['occurrences'], rows[0]['lost_ms']), (2, 5000))
        self.assertEqual(rows[1]['units'], ['GV1', 'KD1'])
        self.assertFalse(rows[1]['measurable'])

    def test_render_is_deterministic_and_marks_unmeasurable_classes(self):
        self.add('quiet one', 1)
        records, _ = lessons.load(self.tmp)
        first = lessons_report.render(records)
        self.assertEqual(first, lessons_report.render(records))
        self.assertIn(config.get('lessons.report_unknown_cost'), first)
        self.assertIn(f'# {config.get("lessons.report_title")}', first)

    def test_event_published_once_per_distinct_report(self):
        self.add('quiet one', 1)
        records, _ = lessons.load(self.tmp)
        text = lessons_report.render(records)
        for _ in range(2):
            lessons_report.publish(self.port, records, [], text)
        sent = self.port.adapter.read(forge_events.Channel(config.get('forge-events.repo'), None))
        self.assertEqual([e['type'] for e in sent], ['lessons.reported'])
        self.assertEqual(self.port.rejected, [])
        self.assertEqual(sent[0]['payload']['digest'], lessons_report.digest(text))

    def test_cli_write_then_check_and_drift(self):
        self.add('quiet one', 1)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(lessons.main(['--root', str(self.tmp), 'report', '--write', '--no-emit']), 0)
            self.assertEqual(lessons.main(['--root', str(self.tmp), 'report', '--check']), 0)
            self.add('another', 2)
            self.assertEqual(lessons.main(['--root', str(self.tmp), 'report', '--check']), 1)

    def test_the_committed_report_matches_the_registry(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(lessons.main(['--root', str(ROOT), 'report', '--check']), 0)


class BriefTest(Fixture):
    def test_applied_lessons_for_an_area_then_general_ones(self):
        hit = self.applied(self.add('about commit check', 1, area=['scripts/lib/commit_*.py']))
        self.applied(self.add('elsewhere', 1, area=['web/src']))
        general = self.applied(self.add('for everyone', 2))
        self.add('not applied yet', 1, area=['scripts/lib/commit_check.py'])
        records, _ = lessons.load(self.tmp)
        found = lessons_brief.for_area(records, ['scripts/lib/commit_check.py'])
        self.assertEqual([r['id'] for r in found], [hit['id'], general['id']])

    def test_directory_prefix_and_limit(self):
        for number in range(3):
            self.applied(self.add(f'lesson {number}', 1, area=['scripts/lib']))
        records, _ = lessons.load(self.tmp)
        self.assertTrue(lessons_brief.matches('scripts/lib', 'scripts/lib/x.py'))
        self.assertTrue(lessons_brief.matches('scripts/lib/x.py', 'scripts/lib'))
        self.assertFalse(lessons_brief.matches('scripts/libx', 'scripts/lib/x.py'))
        self.assertLessEqual(len(lessons_brief.for_area(records, ['scripts/lib/x.py'])), config.get('lessons.brief_limit'))

    def test_cli_for_area_json(self):
        record = self.applied(self.add('about it', 1, area=['a/b.py']))
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(lessons.main(['--root', str(self.tmp), 'for-area', 'a/b.py', '--json']), 0)
        self.assertEqual([r['id'] for r in json.loads(out.getvalue())], [record['id']])


if __name__ == '__main__':
    unittest.main()
