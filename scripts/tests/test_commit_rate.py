"""The commit rate of the last 60 minutes (D-201): each unit is the window's count scaled to the unit; the render names the
time and the raw count. Pure functions; no git, no network.
"""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import commit_rate  # noqa: E402

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'commit-rate.json').read_text())


class Rates(unittest.TestCase):
    def test_each_unit_is_the_count_scaled_to_it(self):
        rates = commit_rate.rates(FIXTURE['counted'])
        self.assertAlmostEqual(rates['per_hour'], FIXTURE['per_hour'])
        self.assertAlmostEqual(rates['per_minute'], FIXTURE['per_minute'])
        self.assertAlmostEqual(rates['per_second'], FIXTURE['per_second'])
        self.assertAlmostEqual(rates['per_day'], FIXTURE['per_day'])

    def test_an_empty_window_is_zero_everywhere(self):
        self.assertEqual(set(commit_rate.rates(0).values()), {0})

    def test_the_render_names_the_time_and_the_raw_count(self):
        data = dict(commit_rate.rates(FIXTURE['counted']), raw=FIXTURE['raw'])
        text = commit_rate.render(data, now=FIXTURE['now'])
        self.assertIn('UTC', text)
        self.assertIn(f"raw {FIXTURE['raw']}", text)
        self.assertIn('per day', text)


if __name__ == '__main__':
    unittest.main()
