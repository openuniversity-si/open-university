"""The live plan (live-planning LP3, D-071): fold, digest chain, op validation, the plan log and its CLI."""
import contextlib
import copy
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import forge_events  # noqa: E402
import plan_live  # noqa: E402
import program  # noqa: E402

FIXTURE = json.loads(plan_live.FIXTURE.read_text())


def setUpModule():
    unittest.enterModuleContext(config.use_adapter(forge_events.MemoryAdapter()))


def change(plan, ops, version=None, parent=None, **fields):
    """A plan.changed payload on top of `plan` (a folded plan), its digest computed."""
    version = version if version is not None else plan_live.initial(plan)['version'] + 1
    line = {'program': plan['program'], 'version': version,
            'parent': parent if parent is not None else {'version': version - 1, 'digest': ''},
            'ops': ops, 'inputs': ['ev'], 'judgment': ['j'], 'intention': 'i', 'expected_effect': 'e',
            'decided_by': 'A Torre', 'reversible': True, 'escalated': False, **fields}
    line['digest'] = plan_live.digest(line)
    return line


class Fold(unittest.TestCase):
    def test_reproduces_the_fixture_at_every_version(self):
        for version, expected in FIXTURE['expected_at'].items():
            with self.subTest(version=version):
                self.assertEqual(plan_live.fold(FIXTURE['plan'], FIXTURE['changes'][:int(version)]), expected)
        self.assertEqual(plan_live.fold(FIXTURE['plan'], FIXTURE['changes']), FIXTURE['expected'])

    def test_fold_is_pure(self):
        plan, changes = copy.deepcopy(FIXTURE['plan']), copy.deepcopy(FIXTURE['changes'])
        plan_live.fold(plan, changes)
        self.assertEqual((plan, changes), (FIXTURE['plan'], FIXTURE['changes']))

    def test_fixture_digests_are_the_canonical_hash(self):
        for line in FIXTURE['changes']:
            self.assertEqual(plan_live.digest(line), line['digest'])

    def test_digest_ignores_its_own_field_and_key_order(self):
        line = FIXTURE['changes'][0]
        reordered = dict(reversed(list({**line, 'digest': 'x'}.items())))
        self.assertEqual(plan_live.digest(reordered), line['digest'])

    def test_chain_break_is_refused(self):
        changes = copy.deepcopy(FIXTURE['changes'])
        changes[1]['parent']['digest'] = '0' * len(changes[0]['digest'])
        changes[1]['digest'] = plan_live.digest(changes[1])
        with self.assertRaisesRegex(plan_live.PlanError, 'chain broken'):
            plan_live.fold(FIXTURE['plan'], changes)

    def test_tampered_line_is_refused(self):
        changes = copy.deepcopy(FIXTURE['changes'])
        changes[0]['intention'] = 'rewritten'
        with self.assertRaisesRegex(plan_live.PlanError, 'digest'):
            plan_live.fold(FIXTURE['plan'], changes)

    def test_hold_all_and_release(self):
        plan = plan_live.initial(FIXTURE['plan'])
        held = plan_live.fold(plan, [change(plan, [{'op': 'hold', 'unit': None, 'args': {'reason': 'r', 'release_when': 'w'}}])])
        self.assertEqual(held['holds'], {plan_live.ALL: {'reason': 'r', 'release_when': 'w'}})

    def test_reorder_remove_and_records(self):
        plan = plan_live.initial(FIXTURE['plan'])
        ops = [{'op': 'reorder', 'unit': None, 'args': {'order': ['A2', 'A3']}},
               {'op': 'brief_line', 'unit': 'A3', 'args': {'line': 'l'}},
               {'op': 'set_unit', 'unit': 'A2', 'args': {'model': 'm2'}},
               {'op': 'note', 'unit': None, 'args': {'text': 'n'}},
               {'op': 'set_estimate', 'unit': 'A2', 'args': {'hours': 1}},
               {'op': 'remove_unit', 'unit': 'A3'}]
        folded = plan_live.fold(plan, [change(plan, ops)])
        self.assertEqual([unit['id'] for unit in folded['units']], ['A1', 'A2'])
        self.assertEqual(folded['priority'], {'A2': 1})
        self.assertEqual(folded['brief_lines'], {})
        self.assertEqual(plan_live.graph(folded)['units'][1]['model'], 'm2')
        self.assertEqual([record['op'] for record in folded['records']], ['note', 'set_estimate'])


class Validate(unittest.TestCase):
    def setUp(self):
        self.plan = plan_live.fold(FIXTURE['plan'], FIXTURE['changes'])

    def errors(self, ops, **fields):
        line = change(self.plan, ops, parent=plan_live.head(FIXTURE['changes']), **fields)
        return plan_live.validate(self.plan, line)

    def test_a_sound_change_has_no_error(self):
        self.assertEqual(self.errors([{'op': 'set_deps', 'unit': 'A3', 'args': {'depends_on': ['A0']}}]), [])

    def test_stale_parent(self):
        line = change(self.plan, [{'op': 'note', 'unit': None, 'args': {}}], version=self.plan['version'],
                      parent=plan_live.head(FIXTURE['changes'][:1]))
        self.assertTrue(any('stale parent' in error for error in plan_live.validate(self.plan, line)))

    def test_unknown_unit(self):
        self.assertIn('unknown unit', ' '.join(self.errors([{'op': 'hold', 'unit': 'Z9', 'args': {'reason': 'r', 'release_when': 'w'}}])))

    def test_missing_dependency(self):
        self.assertIn('depends on unknown Z9', ' '.join(self.errors([{'op': 'set_deps', 'unit': 'A2', 'args': {'depends_on': ['Z9']}}])))

    def test_cycle(self):
        self.assertIn('cycle', ' '.join(self.errors([{'op': 'set_deps', 'unit': 'A1', 'args': {'depends_on': ['A2']}},
                                                     {'op': 'set_unit', 'unit': 'A1', 'args': {'wave': self.plan['units'][1]['wave']}}])))

    def test_removing_a_dependency_breaks_the_graph(self):
        self.assertIn('depends on unknown A1', ' '.join(self.errors([{'op': 'remove_unit', 'unit': 'A1'}])))

    def test_schema_of_an_added_unit(self):
        self.assertTrue(self.errors([{'op': 'add_unit', 'unit': 'B1', 'args': {'depends_on': []}}]))

    def test_unknown_op_and_wrong_program(self):
        self.assertIn('not one of the plan.changed ops', ' '.join(self.errors([{'op': 'insert_unit', 'unit': 'A1'}])))
        self.assertIn('program', ' '.join(self.errors([{'op': 'note', 'unit': None}], program='other')))

    def test_fold_refuses_an_invalid_change(self):
        line = change(self.plan, [{'op': 'release', 'unit': 'A3'}], parent=plan_live.head(FIXTURE['changes']))
        with self.assertRaisesRegex(plan_live.PlanError, 'not held'):
            plan_live.fold(FIXTURE['plan'], FIXTURE['changes'] + [line])


class Log(unittest.TestCase):
    """A temp checkout with a fixture program; the log is written by append() and read back."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        shutil.copytree(ROOT / 'contracts' / 'programs', self.tmp / 'contracts' / 'programs')
        folder = program.programs_dir(self.tmp) / 'fixture'
        folder.mkdir(parents=True)
        block = json.dumps(FIXTURE['plan'])
        (folder / config.get('coordinator.plan_file')).write_text(
            f'# fixture\n\n```{config.get("coordinator.plan_fence")}\n{block}\n```\n')

    def write_fixture_log(self):
        for line in FIXTURE['changes']:
            plan_live.append('fixture', line, self.tmp)

    def test_append_then_read_reproduces_every_version(self):
        self.write_fixture_log()
        self.assertEqual(plan_live.read_log('fixture', self.tmp), FIXTURE['changes'])
        for version, expected in FIXTURE['expected_at'].items():
            self.assertEqual(plan_live.plan_at('fixture', int(version), self.tmp), expected)
        self.assertEqual(plan_live.plan_at('fixture', root=self.tmp), FIXTURE['expected'])

    def test_missing_log_is_version_zero(self):
        self.assertEqual(plan_live.read_log('fixture', self.tmp), [])
        self.assertEqual(plan_live.plan_at('fixture', root=self.tmp), FIXTURE['expected_at']['0'])

    def test_stale_parent_is_refused_and_nothing_written(self):
        self.write_fixture_log()
        before = plan_live.log_path('fixture', self.tmp).read_text()
        late = change(FIXTURE['expected_at']['1'], [{'op': 'note', 'unit': None, 'args': {}}],
                      parent=plan_live.head(FIXTURE['changes'][:1]))
        with self.assertRaisesRegex(plan_live.PlanError, 'stale parent'):
            plan_live.append('fixture', late, self.tmp)
        self.assertEqual(plan_live.log_path('fixture', self.tmp).read_text(), before)

    def test_invalid_graph_is_refused(self):
        self.write_fixture_log()
        line = change(FIXTURE['expected'], [{'op': 'remove_unit', 'unit': 'A0'}],
                      parent=plan_live.head(FIXTURE['changes']))
        with self.assertRaisesRegex(plan_live.PlanError, 'depends on unknown A0'):
            plan_live.append('fixture', line, self.tmp)

    def test_append_computes_the_digest(self):
        line = dict(FIXTURE['changes'][0])
        del line['digest']
        self.assertEqual(plan_live.append('fixture', line, self.tmp)['digest'], FIXTURE['changes'][0]['digest'])

    def test_edited_log_line_breaks_the_chain(self):
        self.write_fixture_log()
        path = plan_live.log_path('fixture', self.tmp)
        lines = path.read_text().splitlines()
        lines[0] = lines[0].replace('fixture change 1', 'fixture change one')
        path.write_text('\n'.join(lines) + '\n')
        with self.assertRaisesRegex(plan_live.PlanError, 'chain broken'):
            plan_live.read_log('fixture', self.tmp)

    def test_read_through_a_git_ref(self):
        self.write_fixture_log()
        git = ['git', '-C', str(self.tmp), '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false']
        subprocess.run(git + ['init', '-q'], check=True)
        subprocess.run(git + ['add', '-A'], check=True)
        subprocess.run(git + ['commit', '-qm', 'log'], check=True)
        plan_live.log_path('fixture', self.tmp).unlink()
        self.assertEqual(plan_live.read_log('fixture', self.tmp, 'HEAD'), FIXTURE['changes'])
        self.assertEqual(plan_live.read_log('fixture', self.tmp, 'refs/heads/absent'), [])

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = program.main(list(argv) + ['--root', str(self.tmp), '--worktree'])
        return code, out.getvalue()

    def test_cli_plan_and_log_round_trip(self):
        self.write_fixture_log()
        for version, expected in FIXTURE['expected_at'].items():
            code, out = self.cli('plan', 'fixture', '--at', version)
            self.assertEqual((code, json.loads(out)), (0, expected))
        code, out = self.cli('plan', 'fixture')
        self.assertEqual((code, json.loads(out)), (0, FIXTURE['expected']))
        code, out = self.cli('log', 'fixture')
        rows = [row.split('\t') for row in out.splitlines()]
        self.assertEqual(code, 0)
        first, last = FIXTURE['changes'][0], FIXTURE['changes'][-1]
        self.assertEqual([row[0] for row in rows], [str(line['version']) for line in FIXTURE['changes']])
        self.assertEqual(rows[-1], [str(last['version']), str(first['version']), last['decided_by'], last['intention'], last['digest']])

    def test_cli_refuses_a_version_past_the_head(self):
        self.write_fixture_log()
        self.assertEqual(self.cli('plan', 'fixture', '--at', str(len(FIXTURE['changes']) + 1))[0], 1)


if __name__ == '__main__':
    unittest.main()
