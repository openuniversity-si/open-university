"""The program gate and program retro (D-069 CO1): all units merged, the goal measured from events, retros aggregated."""
from datetime import datetime, timedelta, timezone
import io
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import coordinator_launch  # noqa: E402
import forge_events  # noqa: E402
import program_gate  # noqa: E402

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)


def setUpModule():
    unittest.enterModuleContext(config.use_adapter(forge_events.MemoryAdapter()))


def plan(target=2, comparator='gte', metric='prs_merged_per_day'):
    return {'contract': 'program.v1', 'program': 'p', 'complaint': {'symptom': 's', 'evidence': 'e', 'goal': {
        'metric': metric, 'comparator': comparator, 'target': target, 'unit': 'u'}}, 'units': [
        {'id': 'A1', 'title': 'first', 'depends_on': [], 'owner': 'o', 'model': 'm', 'wave': 1, 'done': ['d']},
        {'id': 'B1', 'depends_on': ['A1'], 'owner': 'o', 'model': 'm', 'wave': 2, 'done': ['d']}]}


def merged(unit, number, ago_s=60):
    return {'type': 'pr.merged', 'payload': {'unit': unit, 'pr': number}, 'occurred_at': (NOW - timedelta(seconds=ago_s)).isoformat()}


class Gate(unittest.TestCase):
    def test_passes_when_all_merged_and_goal_met(self):
        result = program_gate.evaluate(plan(), [merged('a1', 1), merged('b1', 2)], NOW)
        self.assertTrue(result['passed'])
        self.assertEqual((result['merged'], result['total'], result['value']), (2, 2, 2.0))

    def test_fails_while_a_unit_is_unmerged(self):
        result = program_gate.evaluate(plan(target=1), [merged('a1', 1)], NOW)
        self.assertFalse(result['passed'])
        self.assertEqual(result['unmerged'], ['B1'])
        self.assertTrue(result['goal_met'])

    def test_fails_when_goal_not_met_even_if_all_merged(self):
        result = program_gate.evaluate(plan(target=3), [merged('a1', 1), merged('b1', 2)], NOW)
        self.assertFalse(result['passed'])
        self.assertFalse(result['goal_met'])

    def test_merges_outside_the_window_do_not_count(self):
        old = config.get('coordinator.goal_window_s') + 10
        self.assertEqual(program_gate.measure('prs_merged_per_day', [merged('a1', 1, ago_s=old)], NOW), 0)

    def test_per_hour_scales_the_window(self):
        window = config.get('coordinator.goal_window_s')
        self.assertEqual(program_gate.measure('prs_merged_per_hour', [merged('a1', 1)], NOW), 3600 / window)

    def test_lte_comparator(self):
        result = program_gate.evaluate(plan(target=5, comparator='lte'), [merged('a1', 1), merged('b1', 2)], NOW)
        self.assertTrue(result['goal_met'])

    def test_unknown_metric_is_refused(self):
        with self.assertRaises(program_gate.GateError):
            program_gate.measure('vibes', [], NOW)

    def test_render_names_verdict_and_waiting_units(self):
        text = program_gate.render_gate(plan(), program_gate.evaluate(plan(), [merged('a1', 1)], NOW))
        self.assertIn('FAIL', text)
        self.assertIn('waiting: B1', text)


class Retro(unittest.TestCase):
    RETRO = '# A1 retro\n\n## 1. Brief\nfine\n\n## 5. Lessons\n\n- one\n- two\n\n### sub\nkept\n\n## 6. Next\nnot carried\n'

    def folder(self, with_retro=True):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if with_retro:
            path = Path(tmp.name) / config.get('coordinator.unit_retro_path').format(unit='A1')
            path.parent.mkdir(parents=True)
            path.write_text(self.RETRO)
        return Path(tmp.name)

    def test_lessons_section_stops_at_the_next_same_level_heading(self):
        lines = program_gate.lessons_section(self.RETRO, 40)
        self.assertEqual(lines, ['- one', '- two', '### sub', 'kept'])

    def test_section_is_cut_at_the_registered_limit(self):
        self.assertEqual(len(program_gate.lessons_section(self.RETRO, 2)), 2)

    def test_retro_carries_sections_and_names_units_without_one(self):
        text = program_gate.retro(plan(), root=self.folder())
        self.assertIn('## A1: first', text)
        self.assertIn('- one', text)
        self.assertNotIn('not carried', text)
        self.assertIn('## Units without a retro\n\n- B1', text)

    def test_padrao_candidates_are_marked(self):
        class Lessons(coordinator_launch.NullLessons):
            def candidates(self, unit_ids):
                return ['LR-1 [rule] change the template']
        marker = config.get('coordinator.retro_marker')
        text = program_gate.retro(plan(), Lessons(), root=self.folder())
        self.assertIn(f'- {marker}: LR-1 [rule] change the template', text)
        self.assertIn('None.', program_gate.retro(plan(), root=self.folder(False)))

    def test_cli_check_exit_code_follows_the_gate(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = program_gate.main(['check', 'reach-1000-prs-per-day', '--events', '/dev/null', '--now', NOW.isoformat()])
        self.assertEqual(code, 1)
        self.assertIn('FAIL', out.getvalue())


if __name__ == '__main__':
    unittest.main()
