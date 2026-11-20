"""The problem space, leap 1 (D-348): scripts/lib/problem_space.py and its place in scripts/model."""
import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import model
import problem_space

DAY = '2026-11-19'
LATER = '2026-11-20'


def write(root, rel, body):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def assume(text, premise=None):
    return {'statement': text, **({'premise': premise} if premise else {})}


class ProblemSpace(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='problem-space-'))
        self.addCleanup(shutil.rmtree, self.root)
        for folder in ('contracts/model', 'config/model'):
            shutil.copytree(ROOT / folder, self.root / folder)
        unwired = {'kind': 'unwired', 'source': 'x'}
        base = {'owner': 'Daniel', 'source': 'x', 'comparator': 'gte', 'threshold': 1, 'measure': unwired,
                'baseline': {'value': 0, 'date': DAY, 'source': 'x'}}
        self.files = {
            'NC-goal': {'id': 'NC-goal', 'statement': 'more', 'level': 'csf', 'necessary_for': ['INT-x'], **base},
            'NC-part': {'id': 'NC-part', 'statement': 'part', 'level': 'nc', 'necessary_for': ['NC-goal'], **base},
            'UDE-slow': {'id': 'UDE-slow', 'statement': 'slow', 'violates': ['NC-goal'], 'evidence': ['a reading'],
                         'state': 'observed', 'owner': 'manager', 'source': 'x'},
            'CAUSE-core': {'id': 'CAUSE-core', 'statement': 'why', 'kind': 'core', 'causes': ['CAUSE-mid'],
                           'accepted': {'by': 'Daniel', 'date': DAY}, 'owner': 'manager', 'source': 'x'},
            'CAUSE-mid': {'id': 'CAUSE-mid', 'statement': 'how', 'kind': 'intermediate', 'causes': ['UDE-slow'],
                          'owner': 'manager', 'source': 'x'},
            'CONFLICT-cloud': {'id': 'CONFLICT-cloud', 'a': 'a', 'b': 'b', 'c': 'c', 'd': 'd', 'd_prime': 'e',
                               'objective': 'NC-goal', 'perpetuates': ['CAUSE-core'],
                               'assumptions': [{'arrow': 'B-D', 'statement': 'only this way', 'premise': 'P-1'}],
                               'owner': 'manager', 'source': 'x'},
        }
        for option, state in (('do-nothing', 'rejected'), ('do-minimum', 'rejected'), ('proposal', 'chosen')):
            ident = f'INJ-{option}'
            self.files[ident] = {
                'id': ident, 'statement': option, 'option': option, 'kind': 'policy', 'addresses': ['CAUSE-core'],
                'effects': [{'statement': 'fast', 'inverts': 'UDE-slow'}] if option == 'proposal' else [],
                'branches': [{'effect': 'a cost', 'severity': 'low', 'trimmed_by': 'a guard'}],
                'invalidates': ['P-1'] if option == 'proposal' else [],
                'cost': {'level': 'low', 'basis': 'x'}, 'state': state, 'decided_by': ['D-1'], 'owner': 'manager',
                'source': 'x'}
        assumptions = {'necessary': assume('necessary', 'P-2'), 'parallel': assume('parallel'),
                       'sufficiency': assume('sufficiency')}
        node = {'owner': 'manager', 'source': 'x', 'assumptions': assumptions}
        top, domain, program = range(1, len(problem_space.VALIDATORS))
        self.files['ST-top'] = {'id': 'ST-top', 'level': top, 'strategy': 'INT-x', 'tactic': 'INJ-proposal',
                                'owner_role': 'manager', 'validated': {'by': 'Daniel', 'date': DAY}, **node}
        self.files['ST-domain'] = {'id': 'ST-domain', 'level': domain, 'strategy': 'NC-goal',
                                   'tactic': 'focus one front on the measured constraint', 'child_of': 'ST-top',
                                   'owner_role': 'manager', 'validated': {'by': 'Daniel', 'date': DAY}, **node}
        self.files['ST-program'] = {'id': 'ST-program', 'level': program, 'strategy': 'NC-part',
                                    'tactic': 'deliver the program units under the constraint', 'child_of': 'ST-domain',
                                    'owner_role': 'domain-coordinator', 'decomposes_into': ['WORK-program-p'],
                                    'validated': {'by': 'manager', 'date': DAY}, **node}
        low, mid, high = 0, 1, 1 + 1
        self.weight, self.low, self.mid, self.high = 1 + 1, low, mid, high
        self.appraisal = {'id': 'D-1', 'decision': 'D-1', 'criteria': [{'nc': 'NC-goal', 'weight': self.weight}],
                          'criteria_fixed': DAY, 'options': ['INJ-do-nothing', 'INJ-do-minimum', 'INJ-proposal'],
                          'scores': [
                              {'option': 'INJ-do-nothing', 'nc': 'NC-goal', 'value': low, 'evidence': 'x'},
                              {'option': 'INJ-do-minimum', 'nc': 'NC-goal', 'value': mid, 'evidence': 'x'},
                              {'option': 'INJ-proposal', 'nc': 'NC-goal', 'value': high, 'evidence': 'x'},
                          ],
                          'scored': DAY, 'chosen': 'INJ-proposal', 'why': 'x', 'revert': 'x', 'owner': 'Daniel',
                          'source': 'x'}

    def found(self, states=None, edit=None, appraisal=None, extra=None):
        """The problem space read from the fixture (after `edit` of its files), with each NC's state set (as
        derive_validations would from a wired measure), attached to D-1 and a program of work, and derived."""
        files = copy.deepcopy(self.files)
        if edit:
            edit(files)
        shutil.rmtree(self.root / 'config/problem', ignore_errors=True)
        for ident, body in files.items():
            write(self.root, f'config/problem/{ident}.json', body)
        write(self.root, 'config/problem/appraisal/D-1.json', appraisal or self.appraisal)
        found = {item['id']: item for item in model.read_problem(self.root)}
        found['D-1'] = {'id': 'D-1', 'type': 'D', 'state': 'accepted', 'fingerprint': 'f', 'links': [], 'source': 'x'}
        found['INT-x'] = {'id': 'INT-x', 'type': 'INT', 'state': 'active', 'fingerprint': 'f', 'links': [], 'source': 'x'}
        found['P-1'] = {'id': 'P-1', 'type': 'P', 'state': 'refuted', 'fingerprint': 'f', 'links': [], 'source': 'x',
                        'body': {}}
        found['P-2'] = {'id': 'P-2', 'type': 'P', 'state': 'confirmed', 'fingerprint': 'f', 'links': [], 'source': 'x',
                        'body': {}}
        found['WORK-program-p'] = {'id': 'WORK-program-p', 'type': 'WORK', 'state': 'in-progress', 'fingerprint': 'f',
                                   'links': [], 'source': 'x', 'body': {'program': 'p', 'kind': 'program'}}
        if extra:
            found.update(extra)
        for ident, state in (states or {'NC-goal': 'not-met', 'NC-part': 'met'}).items():
            found[ident]['state'] = state
        problem_space.attach(found, self.root, model._declared)
        problem_space.derive(found)
        return found

    def conforms(self, found, ident):
        return model.covered(model.metamodel(self.root), found[ident], model.incoming(found), found)

    def test_a_complete_problem_space_has_no_error_and_every_object_conforms(self):
        found = self.found()
        self.assertEqual(problem_space.problem_errors(found), [])
        self.assertEqual(found['CAUSE-core']['body']['coverage'], 1.0)
        self.assertEqual(found['D-1']['appraisal']['chosen'], 'INJ-proposal')
        self.assertEqual(found['ST-domain']['state'], 'not-met', "a node's state is its strategy's condition")
        self.assertEqual(found['ST-top']['state'], 'not-met', 'a level-1 node reads the conditions of its intention')
        for ident in ('NC-goal', 'NC-part', 'UDE-slow', 'CAUSE-core', 'CAUSE-mid', 'CONFLICT-cloud', 'INJ-proposal'):
            self.assertTrue(self.conforms(found, ident), ident)
        self.assertEqual(problem_space.gaps(found)['NC-goal']['baseline'], 0)
        self.assertEqual(model.knowledge_measure(found)['refuted_assumed'], 0,
                         'a cloud records the premise its chosen injection broke; it no longer assumes it')

    def test_each_structural_rule_is_an_error_of_check(self):
        def cycle(files):
            files['CAUSE-mid']['causes'] = ['CAUSE-core', 'UDE-slow']
        def no_cloud(files):
            del files['CONFLICT-cloud']
        def no_minimum(files):
            del files['INJ-do-minimum']
        def stray_strategy(files):
            files['ST-program']['strategy'] = 'NC-other'
            files['NC-other'] = {**files['NC-part'], 'id': 'NC-other', 'necessary_for': ['INT-x']}
        def unchosen_tactic(files):
            files['ST-domain']['tactic'] = 'INJ-do-minimum'
        def wrong_writer(files):
            files['ST-program']['owner_role'] = 'manager'
        def orphan(files):
            files['ST-program']['decomposes_into'] = []
        def no_tactic(files):
            for ident in ('ST-top', 'ST-domain', 'ST-program'):
                files[ident]['tactic'] = f'step {ident}'
        def repeats_parent(files):
            files['ST-domain']['tactic'] = files['ST-top']['tactic']
        def dup_sibling(files):
            files['ST-program-b'] = copy.deepcopy(files['ST-program'])
            files['ST-program-b']['id'] = 'ST-program-b'
            files['ST-program-b']['decomposes_into'] = []
        def no_premise(files):
            files['ST-domain']['assumptions']['necessary'].pop('premise', None)
        def unknown_premise(files):
            files['ST-domain']['assumptions']['necessary']['premise'] = 'P-999'
        def missing_work(files):
            files['ST-program']['decomposes_into'] = ['WORK-program-p', 'WORK-program-ghost']
        cases = ((cycle, 'has a cycle'), (no_cloud, 'no conflict perpetuates'), (no_minimum, 'no do-minimum'),
                 (stray_strategy, 'does not descend'), (unchosen_tactic, 'is no chosen injection'),
                 (wrong_writer, 'is written by the domain-coordinator'), (orphan, 'outside the strategy and tactics'),
                 (no_tactic, "no node's tactic"), (repeats_parent, 'repeats its parent'),
                 (dup_sibling, 'duplicates sibling'), (no_premise, 'link no premise'),
                 (unknown_premise, 'not in the premise register'), (missing_work, 'is not a work item'))
        for edit, said in cases:
            errors = problem_space.problem_errors(self.found(edit=edit))
            self.assertTrue(any(said in line for line in errors), (said, errors))
        delivered = {'WORK-program-p': {'id': 'WORK-program-p', 'type': 'WORK', 'state': 'delivered', 'fingerprint': 'f',
                                        'links': [], 'source': 'x', 'body': {'program': 'p', 'kind': 'program'}}}
        self.assertTrue(any('no longer active' in line for line in problem_space.problem_errors(self.found(extra=delivered))))
        unit_work = {'WORK-p-u1': {'id': 'WORK-p-u1', 'type': 'WORK', 'state': 'queued', 'fingerprint': 'f',
                                   'links': [], 'source': 'x', 'body': {'program': 'p', 'kind': 'unit'}}}
        def unit_on_l3(files):
            files['ST-program']['decomposes_into'] = ['WORK-program-p', 'WORK-p-u1']
        self.assertTrue(any('is not a program' in line for line in problem_space.problem_errors(
            self.found(edit=unit_on_l3, extra=unit_work))))
        def program_on_leaf(files):
            files['ST-leaf'] = {
                'id': 'ST-leaf', 'level': len(problem_space.VALIDATORS), 'strategy': 'NC-part', 'tactic': 'execute unit u1',
                'child_of': 'ST-program', 'decomposes_into': ['WORK-program-p'], 'owner_role': 'lane',
                'validated': {'by': 'coordinator', 'date': DAY}, 'owner': 'lane', 'source': 'x',
                'assumptions': {'necessary': assume('n', 'P-2'), 'parallel': assume('p'), 'sufficiency': assume('s')}}
        self.assertTrue(any('a program on a leaf node' in line for line in problem_space.problem_errors(
            self.found(edit=program_on_leaf))))

    def test_an_appraisal_takes_criteria_from_conditions_fixed_before_the_scores_and_every_option(self):
        late = {**self.appraisal, 'criteria_fixed': LATER}
        self.assertTrue(any('fixed after its scores' in line for line in problem_space.problem_errors(
            self.found(appraisal=late))))
        narrow = {**self.appraisal, 'options': ['INJ-do-nothing', 'INJ-proposal'],
                  'scores': [score for score in self.appraisal['scores'] if score['option'] != 'INJ-do-minimum']}
        self.assertTrue(any('leave out the do-minimum' in line for line in problem_space.problem_errors(
            self.found(appraisal=narrow))))
        stray = {**self.appraisal, 'criteria': [{'nc': 'NC-none', 'weight': 1}]}
        self.assertTrue(any('no condition of the Goal Tree' in line for line in problem_space.problem_errors(
            self.found(appraisal=stray))))
        unscored = {**self.appraisal, 'scores': self.appraisal['scores'][:1]}
        self.assertTrue(any('scores missing' in line for line in problem_space.problem_errors(
            self.found(appraisal=unscored))))
        losing = {**self.appraisal, 'scores': [
            {'option': 'INJ-do-nothing', 'nc': 'NC-goal', 'value': self.high + 1, 'evidence': 'x'},
            {'option': 'INJ-do-minimum', 'nc': 'NC-goal', 'value': self.mid, 'evidence': 'x'},
            {'option': 'INJ-proposal', 'nc': 'NC-goal', 'value': self.high, 'evidence': 'x'},
        ]}
        self.assertTrue(any('does not beat' in line for line in problem_space.problem_errors(
            self.found(appraisal=losing))))
        tied = {**self.appraisal, 'scores': [
            {'option': 'INJ-do-nothing', 'nc': 'NC-goal', 'value': self.high, 'evidence': 'x'},
            {'option': 'INJ-do-minimum', 'nc': 'NC-goal', 'value': self.mid, 'evidence': 'x'},
            {'option': 'INJ-proposal', 'nc': 'NC-goal', 'value': self.high, 'evidence': 'x'},
        ]}
        self.assertTrue(any('does not beat' in line for line in problem_space.problem_errors(
            self.found(appraisal=tied))))
        duplicated = {**self.appraisal, 'scores': self.appraisal['scores'] + [
            {'option': 'INJ-proposal', 'nc': 'NC-goal', 'value': self.mid, 'evidence': 'y'}]}
        self.assertTrue(any('duplicate scores' in line for line in problem_space.problem_errors(
            self.found(appraisal=duplicated))))
        self.assertEqual(problem_space.appraisal_totals(self.appraisal),
                         {'INJ-do-nothing': float(self.weight * self.low),
                          'INJ-do-minimum': float(self.weight * self.mid),
                          'INJ-proposal': float(self.weight * self.high)})
        def undecided(files):
            files['INJ-proposal']['decided_by'] = []
        self.assertTrue(any('no decision that holds an appraisal' in line
                            for line in problem_space.problem_errors(self.found(edit=undecided))))

    def test_what_depends_on_a_reading_is_conformance_never_an_error(self):
        def untracked(files):
            files['UDE-slow']['violates'] = ['NC-part']
        found = self.found(edit=untracked)
        self.assertFalse(self.conforms(found, 'NC-goal'), 'out of target with no effect that says so')
        self.assertEqual(problem_space.problem_errors(found), [])
        found = self.found(states={'NC-goal': 'met', 'NC-part': 'met'})
        self.assertFalse(self.conforms(found, 'UDE-slow'), 'still observed while its condition is met')
        self.assertEqual(problem_space.problem_errors(found), [])
        def returned(files):
            files['UDE-slow']['state'] = 'returned'
        found = self.found(states={'NC-goal': 'met', 'NC-part': 'met'}, edit=returned)
        self.assertFalse(self.conforms(found, 'UDE-slow'), 'still returned while its condition is met')
        def open_branch(files):
            files['INJ-proposal']['branches'] = [{'effect': 'a risk', 'severity': 'high'}]
        self.assertFalse(self.conforms(self.found(edit=open_branch), 'INJ-proposal'), 'an open negative branch')
        def unaccepted(files):
            del files['CAUSE-core']['accepted']
        self.assertFalse(self.conforms(self.found(edit=unaccepted), 'CAUSE-core'), 'a core cause Daniel did not accept')
        def unvalidated(files):
            files['ST-domain']['validated'] = {'by': 'manager', 'date': DAY}
        found = self.found(edit=unvalidated)
        self.assertEqual(found['ST-domain']['state'], 'proposed', 'level 2 is validated by Daniel')
        self.assertFalse(self.conforms(found, 'ST-domain'))
        def refuted_premise(files):
            files['ST-domain']['assumptions']['necessary']['premise'] = 'P-1'
        found = self.found(edit=refuted_premise)
        self.assertEqual(found['ST-domain']['state'], 'proposed', 'rule 11: a refuted premise reopens the ST node')
        self.assertTrue(found['ST-domain']['body']['reopened_by_premise'])
        self.assertFalse(self.conforms(found, 'ST-domain'))
        self.assertEqual(problem_space.problem_errors(found), [])

    def test_diagnostics_reports_duplicate_measures_and_unvalidated_needs(self):
        found = self.found(extra={
            'VAL-goal': {'id': 'VAL-goal', 'type': 'VAL', 'state': 'defined', 'fingerprint': 'f', 'links': [],
                         'body': {'measure': {'kind': 'unwired', 'source': 'x'}, 'comparator': 'gte', 'threshold': 1}},
            'NEED-a': {'id': 'NEED-a', 'type': 'NEED', 'state': 'proposed', 'fingerprint': 'f', 'links': []},
            'NEED-b': {'id': 'NEED-b', 'type': 'NEED', 'state': 'active', 'fingerprint': 'f', 'links': []},
        })
        diag = problem_space.diagnostics(found)
        self.assertEqual(diag['duplicate_measures'], [('NC-goal', 'VAL-goal'), ('NC-part', 'VAL-goal')])
        self.assertEqual(diag['unvalidated_needs'], ['NEED-a'])
        levels = range(1, len(problem_space.VALIDATORS) + 1)
        self.assertEqual(diag['st_levels'], {level: int(level < len(problem_space.VALIDATORS)) for level in levels})
        self.assertEqual(diag['appraisals']['D-1']['INJ-proposal'], float(self.weight * self.high))

    def test_proposed_needs_are_unconformant_until_validated(self):
        extra = {
            'NEED-x': {'id': 'NEED-x', 'type': 'NEED', 'state': 'proposed', 'fingerprint': 'f',
                       'links': [{'type': 'serves', 'target': 'NC-goal'}]},
            'REQ-x': {'id': 'REQ-x', 'type': 'REQ', 'state': 'approved', 'fingerprint': 'f',
                      'links': [{'type': 'derives-from', 'target': 'NEED-x'}]},
            'VAL-x': {'id': 'VAL-x', 'type': 'VAL', 'state': 'met', 'fingerprint': 'f',
                      'links': [{'type': 'validates', 'target': 'NEED-x'}]},
        }
        found = self.found(extra=extra)
        self.assertFalse(self.conforms(found, 'NEED-x'), 'a proposed NEED does not conform before owner validation')
        found['NEED-x']['state'] = 'validated'
        self.assertTrue(self.conforms(found, 'NEED-x'))
        found['NEED-x']['state'] = 'active'
        self.assertTrue(self.conforms(found, 'NEED-x'))

    def test_a_proposed_decision_record_stays_proposed_and_does_not_supersede(self):
        folder = self.root / 'docs/domain/decisions'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'D-998.md').write_text(
            '---\nnumber: D-998\ntime: 19/11 10:00 BRT\npremises: none\nproof: scripts/tests/test_problem.py\n---\nold.\n')
        (folder / 'D-999.md').write_text(
            '---\nnumber: D-999\ntime: 19/11 11:00 BRT\nstatus: proposed\npremises: none\nsupersedes: D-998\n'
            'proof: scripts/tests/test_problem.py\n---\nproposal.\n')
        decisions = {item['id']: item for item in model.read_decisions(self.root) if item['type'] == 'D'}
        self.assertEqual(decisions['D-999']['state'], 'proposed')
        self.assertEqual(decisions['D-998']['state'], 'accepted')
        self.assertEqual(model.row_state('proposed'), 'proposed')

    def test_a_condition_reads_an_slo_and_a_composite_of_conditions(self):
        write(self.root, 'config/registry/slo.json', json.loads((ROOT / 'config/registry/slo.json').read_text()))
        self.assertEqual(model.measured({'measure': {'kind': 'slo', 'name': 'slo.none'}}, {}, self.root, DAY), (None, False))
        found = {'NC-a': {'state': 'met'}, 'NC-b': {'state': 'not-met'}}
        self.assertEqual(model.measured({'measure': {'kind': 'all-met', 'of': ['NC-a', 'NC-b']}}, found, self.root, DAY),
                         (1, True))

    def test_the_torre_s_own_problem_space_is_complete(self):
        found = model.objects(ROOT)
        self.assertEqual(problem_space.problem_errors(found), [])
        meta, into = model.metamodel(ROOT), model.incoming(found)
        kinds = {kind for kind, _ in problem_space.KINDS}
        open_ = sorted(ident for ident, item in found.items() if item['type'] in kinds
                       and not model.covered(meta, item, into, found))
        # Level-2 ST nodes were updated with distinct domain tactics and P-NN premise links; they stay proposed
        # until Daniel validates them (D-354).
        self.assertEqual(open_, ['ST-administration', 'ST-capacity', 'ST-efficiency'])
        diag = problem_space.diagnostics(found)
        self.assertEqual(diag['duplicate_measures'], [
            ('NC-autonomy', 'VAL-autonomy'), ('NC-cost', 'VAL-aws-200'), ('NC-deploy-1s', 'VAL-deploy-1s'),
            ('NC-gate-time', 'VAL-gate-60s'), ('NC-quality', 'VAL-escape-under-1'),
            ('NC-reflexion', 'VAL-changeability'), ('NC-requirements-tested', 'VAL-knowledge'),
            ('NC-throughput', 'VAL-ladder-1')])
        self.assertEqual(diag['unvalidated_needs'], [
            'NEED-autonomy', 'NEED-changeability', 'NEED-cost', 'NEED-knowledge', 'NEED-quality', 'NEED-throughput'])
        d348 = json.loads((ROOT / 'config/problem/appraisal/D-348.json').read_text())
        weights = {item['nc']: item['weight'] for item in d348['criteria']}
        expected = {option: float(sum(weights[s['nc']] * s['value'] for s in d348['scores'] if s['option'] == option))
                    for option in d348['options']}
        self.assertEqual(diag['appraisals']['D-348'], expected)
        self.assertGreater(expected['INJ-tree-governance'], expected['INJ-do-minimum'])
        self.assertGreater(expected['INJ-do-minimum'], expected['INJ-do-nothing'])
        deploy_runs = json.loads((ROOT / 'config/validation/runs/deploy-live.json').read_text())['runs']
        deploy_p100 = max(run['seconds'] for run in deploy_runs)
        self.assertEqual(diag['gaps']['NC-deploy-1s']['baseline'], deploy_p100)
        self.assertEqual(diag['gaps']['NC-deploy-1s']['reading'], deploy_p100)


if __name__ == '__main__':
    unittest.main()
