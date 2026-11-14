"""The fronts in flight (VAZÃO F69): pure functions over in-memory ledger, lock and friction rows. No network, no git,
no real cache."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import fronts  # noqa: E402


def lane(unit, pr, merged, end, session='s2', weighted=1000):
    return {'role': 'lane', 'unit': unit, 'dir': unit.lower(), 'pr': pr, 'merged': merged, 'end': end, 'session': session,
            'wall_s': 600, 'tool_calls': 40, 'tokens': {'weighted': weighted, 'input': 1, 'cache_read': 2, 'cache_write': 3,
                                                        'output': 4}}


LEDGER = [lane('F50', 140, None, '2026-11-02T10:00Z', session='s1'),  # an older coordinator's lane: not a front now
          lane('F58', 157, None, '2026-11-03T21:00Z'), lane('F59', 159, 'b' * 40, '2026-11-03T21:10Z'),
          lane('F60', None, None, '2026-11-03T21:20Z'), {'role': 'coordinator', 'session': 's2', 'end': '2026-11-03T21:30Z'}]


class Status(unittest.TestCase):
    def test_a_front_is_an_unmerged_lane_of_the_newest_session_with_its_lock_wait_and_lost_time(self):
        waits = fronts.lock_waits([{'pr': 157, 'waited_s': 100.5}, {'pr': 157, 'waited_s': 20}, {'pr': 'x'}])
        lost = fronts.lost([{'lane': 'f58', 'seconds': 120}, {'lane': 'f58', 'seconds': 60}, {'what': 'no lane'}])
        found = fronts.status(LEDGER, waits, lost)
        self.assertEqual([row['unit'] for row in found], ['F60', 'F58'])
        self.assertEqual((found[1]['pr'], found[1]['lock_wait_s'], found[1]['lost_s'], found[1]['weighted']),
                         (157, 120.5, 180, 1000))
        self.assertIn('fronts in flight: 2', fronts.render(found))

    def test_no_lane_in_flight_says_so(self):
        self.assertEqual(fronts.status([], {}, {}), [])
        self.assertIn('none', fronts.render([]))

    def test_the_newest_transcripts_directory_is_found_and_a_broken_line_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(fronts.newest_transcripts(f'{tmp}/*/subagents'))
            (Path(tmp) / 'a' / 'subagents').mkdir(parents=True)
            self.assertEqual(fronts.newest_transcripts(f'{tmp}/*/subagents'), Path(tmp) / 'a' / 'subagents')
            log = Path(tmp) / 'log.jsonl'
            log.write_text('{"pr": 1}\nbroken\n[1]\n')
            self.assertEqual(fronts.jsonl(log), [{'pr': 1}])
            self.assertEqual(fronts.jsonl(Path(tmp) / 'missing.jsonl'), [])


if __name__ == '__main__':
    unittest.main()
