"""The flow check (D-197): one report from the parts, a failed part is named and does not stop the others, the clock is BRT.

The commands are replaced by a fake runner and the clock by a fixed time; no network, no git writes.
"""
from datetime import datetime, timedelta
import unittest.mock
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import flow_check  # noqa: E402
import decision_next  # noqa: E402

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'flow-check.json').read_text())


class Report(unittest.TestCase):
    def fake(self, failing=()):
        calls = []

        def runner(root, args):
            calls.append(args)
            return (args[0] not in failing), f'output of {args[0]} {args[-1]}'
        return runner, calls

    def test_every_part_runs_and_the_clock_is_brt(self):
        runner, calls = self.fake()
        with unittest.mock.patch.object(flow_check.decision_next, 'base_text', return_value=FIXTURE['base']), \
                unittest.mock.patch.object(flow_check.decision_next, 'open_pulls', return_value=[]), \
                unittest.mock.patch.object(flow_check.decision_next, '_repo', return_value='x/y'):
            text = flow_check.report(ROOT, runner=runner, now=datetime.fromisoformat(FIXTURE['clock']['utc']))
        self.assertIn(f"flow check, {FIXTURE['clock']['brt']}", text)
        for name in FIXTURE['sections']:
            self.assertIn(f'## {name}', text)
        self.assertEqual(len(calls), len(FIXTURE['commands']))
        self.assertIn(f"D-{FIXTURE['next_decision']}", text)

    def test_a_failed_part_is_named_and_the_others_still_run(self):
        runner, calls = self.fake(failing=(FIXTURE['failing'],))
        with unittest.mock.patch.object(flow_check.decision_next, 'base_text', return_value=FIXTURE['base']), \
                unittest.mock.patch.object(flow_check.decision_next, 'open_pulls', return_value=[]), \
                unittest.mock.patch.object(flow_check.decision_next, '_repo', return_value='x/y'):
            text = flow_check.report(ROOT, runner=runner, now=datetime.fromisoformat(FIXTURE['clock']['utc']))
        self.assertIn('(failed)', text)
        self.assertEqual(len(calls), len(FIXTURE['commands']))


class Idle(unittest.TestCase):
    """flow-check --idle: a lane with no merged pull request in the last hour is idle; one with an open pull request is in
    review ready; the plan's launches are the next steps (D-241)."""
    SUBJECTS = ['Merge pull request #1 from the-owner/claude/fluxo-amplo-v8-lane2-x',
                'Merge pull request #2 from the-owner/claude/fluxo-amplo-v8-m15-unit-fold',
                'Merge pull request #3 from the-owner/claude/fluxo-amplo-v8-lanes16-y']
    PULLS = [{'number': FIXTURE['review_pr'], 'head_ref': 'claude/fluxo-amplo-v8-lane3-foo'}]
    NEXT = '{"action": "launch", "attempt": 1, "plan_version": 0, "unit": "B1"}\n{"action": "open_fix_unit", "defect": "KD-1"}\n'

    def runner(self, root, args):
        return True, self.NEXT

    def test_idle_lanes_review_state_and_next_launches(self):
        lines = flow_check.idle_report(ROOT, runner=self.runner, subjects=self.SUBJECTS, pulls=self.PULLS).splitlines()
        self.assertIn(f"lane 3 (review ready, PR #{FIXTURE['review_pr']})", lines[0])
        self.assertIn('lane 4,', lines[0] + ',')
        self.assertNotIn('lane 4 (review', lines[0])
        for active in ('lane 2', 'lane 15', 'lane 16'):
            self.assertNotIn(active + ' ', lines[0] + ' ')
            self.assertNotIn(active + ',', lines[0])
        self.assertEqual(lines[1], 'next launches: B1')

    def test_no_history_is_named(self):
        with unittest.mock.patch.object(flow_check, 'merged_subjects', return_value=None):
            text = flow_check.idle_report(ROOT, runner=self.runner, pulls=[])
        self.assertIn('merge history unknown', text)


class RepeatRow(unittest.TestCase):
    """The repeat register's nudge row names the read that replaces the nudge (D-193, the repeat routine D-208)."""

    def test_the_nudge_row_names_flow_check_idle(self):
        row = [line for line in (ROOT / 'docs' / 'process' / 'repeats.md').read_text().splitlines()
               if line.startswith('| Messages to other sessions to nudge them')]
        self.assertEqual(len(row), 1)
        self.assertIn('scripts/flow-check --idle', row[0])
        # the status cell is the register's open word for adoption pending: systematised, not adopted (not plain systematised)
        self.assertIn('systematised, not adopted', [cell.strip() for cell in row[0].strip('|').split('|')])


class Train(unittest.TestCase):
    """flow-check's train part: alive or not, the last merge, the woken PRs waiting; red past RED_AFTER_S (D-209)."""
    NOW = datetime.fromisoformat('2026-11-01T13:20:00+00:00')

    def runner(self, status, queue):
        def run_fake(root, args):
            return True, status if args[0] == 'scripts/lane-status' else queue
        return run_fake

    def test_a_dead_train_with_a_waiting_pr_is_red(self):
        text = flow_check.train_report(ROOT, self.runner('train: NO train serve process; queue: 1 waiting', '#1012 abc ready 2026-11-01T13:19:00.000Z'), self.NOW, merged_at=self.NOW.timestamp() - timedelta(minutes=1).total_seconds())
        self.assertTrue(text.splitlines()[0].startswith('RED:'))
        self.assertIn('NOT running', text)

    def test_a_pr_waiting_past_fifteen_minutes_is_red_even_with_a_live_train(self):
        text = flow_check.train_report(ROOT, self.runner('train: running', '#1012 abc ready 2026-11-01T13:00:00.000Z'), self.NOW, merged_at=self.NOW.timestamp() - timedelta(minutes=1).total_seconds())
        self.assertIn('PR #1012 ready for 20 min', text.splitlines()[0])

    def test_a_fresh_queue_with_a_live_train_is_ok(self):
        text = flow_check.train_report(ROOT, self.runner('train: running', '#1012 abc ready 2026-11-01T13:19:00.000Z'), self.NOW, merged_at=self.NOW.timestamp() - timedelta(minutes=1).total_seconds())
        self.assertEqual(text.splitlines()[0], 'ok')
        self.assertIn('running', text)

    def test_an_empty_queue_is_ok_even_with_the_train_down(self):
        text = flow_check.train_report(ROOT, self.runner('train: NO train serve process', ''), self.NOW, merged_at=None)
        self.assertEqual(text.splitlines()[0], 'ok')
        self.assertIn('last merge: unknown', text)


class HelpMatchesDoc(unittest.TestCase):
    """The five commands flow-check replaces are the same in its docstring and in lane.md's section (D-230)."""
    COMMANDS = ('scripts/flow-metrics --cycles', 'scripts/lane-status', 'scripts/service health',
                'scripts/gate-shadow latest', 'scripts/coordinator status')

    def test_docstring_and_lane_guide_name_the_same_five(self):
        doc = flow_check.__doc__
        section = (ROOT / 'docs' / 'process' / 'lane.md').read_text().split('## The status in one entry (D-230)', 1)[1]
        section = section.split('\n## ', 1)[0]
        for command in self.COMMANDS:
            self.assertIn(command, doc)
            self.assertIn(command, section)
        self.assertNotIn('decision-next', doc.split('It replaces', 1)[1].split('`--unit', 1)[0])

    def test_the_guide_names_the_unit_and_idle_modes(self):
        section = (ROOT / 'docs' / 'process' / 'lane.md').read_text().split('## The status in one entry (D-230)', 1)[1]
        for mode in ('--unit ID', '--idle'):
            self.assertIn(mode, section.split('\n## ', 1)[0])


class UnitView(unittest.TestCase):
    """flow-check --unit ID prints that unit's stage from the coordinator's status, and no other unit's (D-206 (c))."""
    STATUS = 'fluxo-amplo: 0/24 merged\n  w1 B1     pending \n  w1 C1     running \n  w1 C10    pending \n'

    def runner(self, root, args):
        return True, self.STATUS

    def test_one_unit_only(self):
        text = flow_check.report(ROOT, runner=self.runner, unit='C1')
        self.assertEqual(text.splitlines()[0], 'unit C1 of fluxo-amplo')
        self.assertIn('w1 C1     running', text)
        self.assertNotIn('C10', text)
        self.assertNotIn('B1', text)

    def test_an_unknown_unit_says_so(self):
        self.assertIn('(no status)', flow_check.report(ROOT, runner=self.runner, unit='Z9'))


class StatusEntry(unittest.TestCase):
    """The loop of lane.md names one status entry (D-230): the five commands flow-check replaces are not separate steps."""
    STATUS = ('scripts/flow-metrics --cycles', 'scripts/lane-status', 'scripts/service status', 'scripts/service health',
              'scripts/gate-shadow latest', 'scripts/coordinator status')

    def test_the_loop_names_flow_check_and_no_status_command(self):
        text = (ROOT / 'docs' / 'process' / 'lane.md').read_text()
        loop = text.split('## The loop, per PR', 1)[1].split('\n## ', 1)[0]
        self.assertIn('scripts/flow-check', loop)
        for command in self.STATUS:
            self.assertNotIn(command, loop, f'{command} is a separate step; flow-check is the one entry (D-230)')


if __name__ == '__main__':
    import unittest.mock
    unittest.main()
