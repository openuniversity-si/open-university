"""One line per fact of the lane (D-156). Hermetic: plain values, no git, no process list."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import lane_status  # noqa: E402


class LaneStatusTests(unittest.TestCase):
    def test_the_pace_is_the_mean_over_the_hours_and_empty_is_zero(self):
        counts = [len('xxxx'), 0, len('xx')]
        pace = lane_status.rates(counts)
        self.assertEqual((pace['last_hour'], pace['mean'], pace['hours']), (counts[0], sum(counts) / len(counts), len(counts)))
        self.assertEqual(lane_status.rates([])['mean'], 0.0)

    def test_a_train_serve_in_the_process_list_is_alive_and_its_grep_is_not(self):
        self.assertTrue(lane_status.serve_alive('bash\npython3 scripts/train serve\n'))
        self.assertTrue(lane_status.serve_alive('python3 scripts/lib/train.py serve\n'))
        self.assertFalse(lane_status.serve_alive('grep train serve\nbash\n'))

    def test_the_render_says_the_rate_the_train_and_the_base(self):
        shadow = {'passed': False, 'sha': 'abc', 'wall_s': 'slow'}
        counts = [len('xxxxx'), len('xxx')]
        text = lane_status.render(counts, '1 waiting', False, shadow)
        self.assertIn(f'{sum(counts) / len(counts):.1f} counted/hour over the last {len(counts)} h', text)
        self.assertIn('NO train serve process', text)
        self.assertIn('BASE BROKEN', text)
        late = lane_status.render(counts, None, True, dict(shadow, passed=True), len(counts))
        self.assertIn(f'{len(counts)} merge(s) behind the base tip', late)
        self.assertIn('no shadow gate result yet', lane_status.render([1], None, True, None))

    def test_json_mode_prints_the_facts_as_one_object(self):
        import json
        from unittest import mock
        facts = ([len('xx'), 0], '0 waiting', True, None, None, None, None, None)
        with mock.patch.object(lane_status, 'gather', return_value=facts), mock.patch('sys.stdout') as out:
            lane_status.main(['--json'])
        printed = json.loads(''.join(call.args[0] for call in out.write.call_args_list))
        self.assertEqual(printed['counted_per_hour'], facts[0])
        self.assertTrue(printed['train_serve'])
        self.assertNotIn('channel', printed)

    def test_no_line_reads_the_github_repository_channel_the_event_log_left(self):
        """The log is on forge-events.log_adapter (git-ref, D-300), so GitHub's comment limit of the old channel issue is no fact."""
        source = (ROOT / 'scripts' / 'lib' / 'lane_status.py').read_text()
        for gone in ('github_cli', 'channel_line'):
            self.assertNotIn(gone, source)

    def test_the_regime_line_names_a_drift_from_bypass_on_and_runner_paused(self):
        self.assertNotIn('DRIFT', lane_status.regime_line(True, True))
        self.assertIn('DRIFT', lane_status.regime_line(False, True))
        self.assertIn('DRIFT', lane_status.regime_line(False, True))
        self.assertIn('D-191', lane_status.regime_line(True, False))
        self.assertNotIn('DRIFT', lane_status.regime_line(True, False))

    def test_the_train_checkout_is_read_from_the_serve_process_and_the_newest_shadow_wins(self):
        process = 'bash\nwt/.toolchain/bin/python3 wt/scripts/lib/train.py serve\n'
        self.assertEqual(lane_status.train_checkout(process), 'wt')
        self.assertIsNone(lane_status.train_checkout('bash\n'))
        older, newer = {'sha': 'a', 'at': len('x')}, {'sha': 'b', 'at': len('xxx')}
        self.assertEqual(lane_status.newest(older, newer)['sha'], 'b')
        self.assertEqual(lane_status.newest(None, older)['sha'], 'a')
        self.assertIsNone(lane_status.newest(None, None))

    def test_the_guards_line_names_each_ratio_it_is_given(self):
        text = lane_status.guards_line({'split': 1 / len('abcd'), 'tangled': 1 / len('abc'), 'docsonly': 1 / len('ab'), 'plan_linked': 1, 'other': 1})
        for name in ('split', 'tangled', 'docsonly', 'plan_linked'):
            self.assertIn(name, text)
        self.assertNotIn('other', text)

    def test_the_status_reads_only_the_recent_days(self):
        import datetime
        now = datetime.datetime.fromisoformat('2026-10-31T21:40:00')
        self.assertEqual(lane_status.recent_since(now=now), '2026-10-29 00:00')
        self.assertEqual(lane_status.recent_since(1, now), '2026-10-30 00:00')

    def test_the_lanes_line_gives_each_lane_its_own_mean(self):
        text = lane_status.lanes_line({'lane1': [len('xxxx'), 0], 'lane2': [1, 1]})
        self.assertIn('lane1 2.0/h (4 0)', text)
        self.assertIn('lane2 1.0/h (1 1)', text)


if __name__ == '__main__':
    unittest.main()
