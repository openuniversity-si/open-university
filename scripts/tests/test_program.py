"""Programs as first-class objects (D-069 CO1): registry, graph checks and status folded from events."""
import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import forge_events  # noqa: E402
import program  # noqa: E402

SEED = 'reach-1000-prs-per-day'


def setUpModule():
    unittest.enterModuleContext(config.use_adapter(forge_events.MemoryAdapter()))


def event(kind, unit, pr=None):
    return {'type': kind, 'payload': {'unit': unit, 'pr': pr}}


def sample():
    return {'contract': 'program.v1', 'program': 'p', 'complaint': {'symptom': 's', 'evidence': 'e', 'goal': {
        'metric': 'm', 'comparator': 'gte', 'target': 1, 'unit': 'u'}}, 'units': [
        {'id': 'A1', 'depends_on': [], 'owner': 'o', 'model': 'm', 'wave': 1, 'done': ['d']},
        {'id': 'B1', 'depends_on': ['A1'], 'owner': 'o', 'model': 'm', 'wave': 2, 'done': ['d']}]}


class Registry(unittest.TestCase):
    def test_seed_program_is_sound(self):
        self.assertEqual(program.check(SEED), [])
        self.assertIn(SEED, program.names())
        self.assertNotIn(config.get('coordinator.template_dir'), program.names())

    def test_seed_holds_the_brief_units(self):
        ids = {unit['id'] for unit in program.load(SEED)['units']}
        self.assertTrue({'X1', 'TI1', 'GD1', 'PD1', 'GS1', 'TR1', 'KD1', 'GV1', 'LR1', 'CO1', 'U3b', 'U4'} <= ids)

    def test_new_program_from_template_has_every_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(ROOT / 'docs', Path(tmp) / 'docs', ignore=shutil.ignore_patterns('units', 'process', 'operations'))
            shutil.copytree(ROOT / 'contracts' / 'programs', Path(tmp) / 'contracts' / 'programs')
            target = program.create('fresh', Path(tmp))
            for file in config.get('coordinator.program_files'):
                self.assertTrue((target / file).is_file())
            self.assertIn('fresh', (target / 'plan.md').read_text())


class Graph(unittest.TestCase):
    def test_sound_graph(self):
        self.assertEqual(program.graph_problems(sample()), [])

    def test_unknown_dependency(self):
        bad = sample()
        bad['units'][1]['depends_on'] = ['Z9']
        self.assertIn('B1 depends on unknown Z9', program.graph_problems(bad))

    def test_cycle(self):
        bad = sample()
        bad['units'][0]['depends_on'] = ['B1']
        bad['units'][0]['wave'] = 2
        self.assertTrue(any(problem.startswith('cycle') for problem in program.graph_problems(bad)))

    def test_dependency_in_a_later_wave(self):
        bad = copy.deepcopy(sample())
        bad['units'][0]['wave'] = 3
        self.assertTrue(any('wave' in problem for problem in program.graph_problems(bad)))

    def test_duplicate_id(self):
        bad = sample()
        bad['units'].append(copy.deepcopy(bad['units'][0]))
        self.assertIn('duplicate unit id', program.graph_problems(bad))

    def test_schema_refuses_missing_field(self):
        text = '```json program.v1\n' + json.dumps({'contract': 'program.v1', 'program': 'p'}) + '\n```\n'
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / config.get('coordinator.programs_dir') / 'p'
            folder.mkdir(parents=True)
            (folder / 'plan.md').write_text(text)
            shutil.copytree(ROOT / 'contracts' / 'programs', Path(tmp) / 'contracts' / 'programs')
            with self.assertRaises(program.ProgramError):
                program.load('p', Path(tmp))


class Status(unittest.TestCase):
    def rows(self, events):
        return {row['id']: row for row in program.status(sample(), events)}

    def test_no_events_launchable_and_blocked(self):
        rows = self.rows([])
        self.assertEqual((rows['A1']['stage'], rows['A1']['blocked_by']), ('pending', []))
        self.assertEqual(rows['B1']['blocked_by'], ['A1'])

    def test_stage_follows_the_log(self):
        rows = self.rows([event('work.assigned', 'a1', 7), event('pr.opened', 'a1', 7)])
        self.assertEqual((rows['A1']['stage'], rows['A1']['pr']), ('open', 7))
        rows = self.rows([event('work.assigned', 'a1', 7), event('pr.ready', 'a1', 7), event('pr.merged', 'a1', 7)])
        self.assertEqual(rows['A1']['stage'], 'merged')
        self.assertEqual(rows['B1']['blocked_by'], [])

    def test_merged_is_final(self):
        rows = self.rows([event('pr.merged', 'a1', 7), event('session.failed', 'a1', 7)])
        self.assertEqual(rows['A1']['stage'], 'merged')

    def test_ended_without_a_pr_returns_to_pending_and_failure_marks_failed(self):
        self.assertEqual(self.rows([event('work.assigned', 'a1'), event('session.ended', 'a1')])['A1']['stage'], 'pending')
        self.assertEqual(self.rows([event('work.assigned', 'a1'), event('session.failed', 'a1')])['A1']['stage'], 'failed')

    def test_other_units_events_are_ignored(self):
        self.assertEqual(self.rows([event('pr.merged', 'zz9', 3)])['A1']['stage'], 'pending')

    def test_a_merged_pr_of_the_unit_is_its_evidence(self):
        # F1 (D-204): a unit done outside the launch carries the manifest id in pr.merged, not the program id; its PR is evidence.
        plan = sample()
        plan['units'][0]['pr'] = 1
        rows = {row['id']: row for row in program.status(plan, [{'type': 'pr.merged', 'payload': {'unit': 'engine-rules', 'pr': 1}}])}
        self.assertEqual((rows['A1']['stage'], rows['A1']['pr']), ('merged', 1))
        self.assertEqual(rows['B1']['blocked_by'], [])

    def test_same_log_same_view(self):
        log = [event('work.assigned', 'a1', 7), event('pr.merged', 'a1', 7)]
        self.assertEqual(program.status(sample(), log), program.status(sample(), list(log)))

    def test_render(self):
        text = program.render_status(sample(), program.status(sample(), [event('pr.merged', 'a1', 7)]))
        self.assertIn('1/2 merged', text)
        self.assertIn('B1', text)


class Migrate(unittest.TestCase):
    def test_queue_list_becomes_a_graph(self):
        plan = program.migrate_queue([{'id': 'A1', 'wave': 2}, {'id': 'B1', 'depends_on': ['A1']}], 'p')
        self.assertEqual([unit['id'] for unit in plan['units']], ['A1', 'B1'])
        self.assertEqual(plan['units'][0]['wave'], 2)
        self.assertEqual(plan['units'][1]['depends_on'], ['A1'])


if __name__ == '__main__':
    unittest.main()
