"""scripts/friction (VAZÃO F85): one JSON line per friction with the clock ts, the lane and a closed cause; --summary
sums seconds by cause per hour. Hermetic: no network; the log is a temporary file and the clock is injected."""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import friction  # noqa: E402

CLOCK = datetime(2026, 11, 3, 22, 41, 7, tzinfo=timezone.utc)


class FrictionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / 'cache' / 'frictions.jsonl'

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *argv):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = friction.main(list(argv), log=self.log, clock=lambda: CLOCK, cwd=self.tmp.name)
        return code, out.getvalue()

    def test_a_friction_is_one_line_with_the_clock_ts_the_lane_and_the_cause(self):
        self.assertEqual(self.run_main('env', '120', 'no', 'toolchain', '--lane', 'f85')[0], 0)
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), {'ts': '2026-11-03T22:41:07Z', 'lane': 'f85', 'cause': 'env',
                                                'what': 'no toolchain', 'seconds': 120})

    def test_a_cause_outside_the_closed_list_or_no_seconds_is_refused(self):
        for argv in (('slow', '60', 'x'), ('env', '0', 'x'), ('env', '60'), ()):
            with self.assertRaises(SystemExit):
                self.run_main(*argv)
        self.assertFalse(self.log.exists())

    def test_the_lane_comes_from_the_units_branch_of_the_worktree(self):
        repo = Path(self.tmp.name) / 'wt'
        repo.mkdir()
        git = ['git', '-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t']
        subprocess.run(git + ['init', '-q', '-b', 'units/f99'], check=True)
        subprocess.run(git + ['commit', '-q', '--allow-empty', '-m', 'x'], check=True)
        self.assertEqual(friction.lane_of(repo), 'f99')
        subprocess.run(git + ['checkout', '-q', '-b', 'other'], check=True)
        self.assertEqual(friction.lane_of(repo), 'wt')

    def test_summary_sums_seconds_by_cause_per_hour_and_drops_future_ts(self):
        rows = [{'ts': '2026-11-03T22:10:00Z', 'lane': 'a', 'cause': 'env', 'what': 'x', 'seconds': 60},
                {'ts': '2026-11-03T22:30:00Z', 'lane': 'b', 'cause': 'env', 'what': 'x', 'seconds': 40},
                {'ts': '2026-11-03T21:05:00Z', 'lane': 'b', 'cause': 'hang', 'what': 'x', 'seconds': 300},
                {'ts': '2026-11-03T21:15:00Z', 'lane': 'c', 'what': 'before F85', 'seconds': 30},
                {'ts': '2026-11-03T23:50:00Z', 'lane': 'd', 'cause': 'rule', 'what': 'future', 'seconds': 9},
                {'ts': '2026-11-02T10:00:00Z', 'lane': 'e', 'cause': 'rule', 'what': 'old', 'seconds': 9}]
        table, future = friction.summary(rows, 3, CLOCK)
        self.assertEqual(table, {'2026-11-03T22:00:00Z': {'env': 100},
                                 '2026-11-03T21:00:00Z': {'hang': 300, 'unknown': 30}})
        self.assertEqual(future, 1)
        self.assertEqual(list(table), sorted(table, reverse=True))

    def test_summary_reads_the_log_and_prints_a_table_or_json(self):
        self.run_main('conflict', '90', 'merge', '--lane', 'f85')
        with self.log.open('a') as handle:
            handle.write('not json\n')
        code, out = self.run_main('--summary', '--json')
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {'hours': {'2026-11-03T22:00:00Z': {'conflict': 90}}, 'future': 0})
        self.assertIn('conflict', self.run_main('--summary')[1])

    def test_summary_without_a_log_is_empty(self):
        self.assertEqual(friction.read(self.log), [])


if __name__ == '__main__':
    unittest.main()
