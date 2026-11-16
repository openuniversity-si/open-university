"""Lesson events and the measured effect (LR1). In-memory forge log, injected clock, no network."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import forge_doubles  # noqa: E402
import lessons  # noqa: E402
import lessons_effect  # noqa: E402

START = datetime(2026, 10, 1, tzinfo=timezone.utc)
STAGE = 'structure check'
SIGNAL = {'event': 'gate.failed', 'stage': STAGE, 'pattern': None}
PATTERN_SIGNAL = {'event': 'gate.failed', 'stage': None, 'pattern': 'KD-|Items in the first set'}


class Clock:
    def __init__(self, moment=START):
        self.moment = moment

    def now(self):
        self.moment += timedelta(seconds=1)
        return self.moment


def gate_failed(at, stage_name=STAGE, duration=1000, signature=None):
    payload = {'stages': [{'name': stage_name, 'result': 'FAIL', 'duration_ms': duration, 'class': 'code'}],
               'failing_tests': [{'id': 'scripts/tests/x.test.sh', 'stage': 'script tests', 'signature': signature}] if signature else []}
    return {'type': 'gate.failed', 'occurred_at': lessons.now_text(at), 'payload': payload}


def lesson(signals, applied_at):
    return {'signals': signals, 'applied': {'pr': 5, 'at': lessons.now_text(applied_at), 'ref': 'x'}}


class Fixture(unittest.TestCase):
    def setUp(self):
        # Lesson event tests isolate their journal double from forge compatibility.
        self.enterContext(mock.patch.object(forge_events, '_require_compatibility'))
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        shutil.copytree(ROOT / 'contracts' / 'lessons', self.tmp / 'contracts' / 'lessons')
        self.clock = Clock()
        self.port = forge_events.ForgeEvents(forge_doubles.journal('scripts/lib/lessons.py'), self.clock, 'lessons', 'test')
        self.port.adapter.comments = mock.Mock(side_effect=AssertionError('recording a lesson must not read PR feedback'))

    def types(self):
        return [e['type'] for e in self.port.adapter.read(forge_events.Channel(config.get('forge-events.repo'), None))]


class EventsTest(Fixture):
    def test_add_apply_retire_publish_valid_events_once(self):
        kinds, owners = config.get('lessons.kinds'), config.get('lessons.owners')
        record, _ = lessons.add(self.tmp, 'Push the audit alone', 'GV1', 'r.md', 5, 'L1', config.get('lessons.classes')[1], kinds[5], 'check', owners[1],
                                clock=self.clock, port=self.port)
        again, outcome = lessons.add(self.tmp, 'Push the audit alone', 'GV1', 'r.md', 5, 'L1', config.get('lessons.classes')[1], kinds[5], 'check', owners[1],
                                     clock=self.clock, port=self.port)
        self.assertEqual(outcome, 'exists')
        lessons.apply(self.tmp, record['id'], 9, 'scripts/lib/local_checks.py', clock=self.clock, port=self.port)
        lessons.retire(self.tmp, record['id'], 'superseded', clock=self.clock, port=self.port)
        self.assertEqual(self.types(), ['lesson.recorded', 'lesson.applied', 'lesson.retired'])
        self.assertEqual(self.port.rejected, [])

    def test_the_catalog_names_the_lesson_events(self):
        self.assertTrue({'lesson.recorded', 'lesson.applied', 'lesson.retired', 'lessons.reported'} <= set(event_contracts.catalog()))


class EffectTest(unittest.TestCase):
    NOW = START + timedelta(days=60)
    APPLIED = START + timedelta(days=30)

    def days(self, *offsets, **kw):
        return [gate_failed(START + timedelta(days=30 + offset), **kw) for offset in offsets]

    def test_fewer_occurrences_after_is_improved(self):
        result = lessons_effect.measure(lesson([SIGNAL], self.APPLIED), self.days(-3, -2, -1, 2), self.NOW)
        self.assertEqual((result['before'], result['after'], result['verdict']), (3, 1, 'improved'))

    def test_more_after_is_worse_and_equal_is_unchanged(self):
        worse = lessons_effect.measure(lesson([SIGNAL], self.APPLIED), self.days(-1, 1, 2), self.NOW)
        same = lessons_effect.measure(lesson([SIGNAL], self.APPLIED), self.days(-1, 1), self.NOW)
        self.assertEqual((worse['verdict'], same['verdict']), ('worse', 'unchanged'))

    def test_an_after_window_not_yet_over_is_insufficient_data(self):
        result = lessons_effect.measure(lesson([SIGNAL], self.APPLIED), self.days(-1, 1), self.APPLIED + timedelta(days=3))
        self.assertEqual(result['verdict'], 'insufficient-data')

    def test_no_occurrence_in_either_window_is_insufficient_data(self):
        self.assertEqual(lessons_effect.measure(lesson([SIGNAL], self.APPLIED), [], self.NOW)['verdict'], 'insufficient-data')

    def test_a_lesson_never_applied_has_no_effect(self):
        self.assertIsNone(lessons_effect.measure({'signals': [SIGNAL], 'applied': None}, [], self.NOW))

    def test_events_outside_the_window_are_not_counted(self):
        far = self.days(-200, 200)
        result = lessons_effect.measure(lesson([SIGNAL], self.APPLIED), far + self.days(-1), self.NOW)
        self.assertEqual((result['before'], result['after']), (1, 0))

    def test_another_stage_or_a_passing_stage_is_not_an_occurrence(self):
        other = self.days(-1, stage_name='script tests')
        passed = gate_failed(self.APPLIED - timedelta(days=1))
        passed['payload']['stages'][0]['result'] = 'PASS'
        self.assertEqual(lessons_effect.measure(lesson([SIGNAL], self.APPLIED), other + [passed], self.NOW)['before'], 0)

    def test_a_pattern_signal_matches_the_failing_test_signature(self):
        hits = self.days(-1, signature='Items in the first set but not the second')
        misses = self.days(-2, signature='other')
        result = lessons_effect.measure(lesson([PATTERN_SIGNAL], self.APPLIED), hits + misses, self.NOW)
        self.assertEqual(result['before'], 1)

    def test_an_event_matching_two_signals_counts_once(self):
        result = lessons_effect.measure(lesson([SIGNAL, SIGNAL], self.APPLIED), self.days(-1), self.NOW)
        self.assertEqual(result['before'], 1)

    def test_record_effect_stores_the_block_and_chains_the_trail(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copytree(ROOT / 'contracts' / 'lessons', tmp / 'contracts' / 'lessons')
        clock = Clock()
        kinds, owners = config.get('lessons.kinds'), config.get('lessons.owners')
        record, _ = lessons.add(tmp, 't', 'GV1', 'r.md', 5, 'L1', config.get('lessons.classes')[1], kinds[5], 'c', owners[1], signals=[SIGNAL], clock=clock)
        lessons.apply(tmp, record['id'], 1, 'x', clock=clock)
        effect = {'measured_at': lessons.now_text(clock.now()), 'window_days': 14, 'before': 2, 'after': 0, 'verdict': 'improved'}
        stored = lessons.record_effect(tmp, record['id'], effect)
        self.assertEqual((stored['effect']['verdict'], stored['trail'][-1]['action']), ('improved', 'measured'))
        self.assertEqual(lessons.check(tmp)[1], [])


if __name__ == '__main__':
    unittest.main()
