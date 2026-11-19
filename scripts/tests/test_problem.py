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
import model  # noqa: E402
import problem_space  # noqa: E402

DAY = '2026-11-19'
LATER = '2026-11-20'


def write(root, rel, body):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def assume(text):
    return {'statement': text}


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
        node = {'tactic': 'INJ-proposal', 'owner': 'manager', 'source': 'x',
                'assumptions': {role: assume(role) for role in ('necessary', 'parallel', 'sufficiency')}}
        top, domain, program = range(1, len(problem_space.VALIDATORS))
        self.files['ST-top'] = {'id': 'ST-top', 'level': top, 'strategy': 'INT-x', 'owner_role': 'manager',
                                'validated': {'by': 'Daniel', 'date': DAY}, **node}
        self.files['ST-domain'] = {'id': 'ST-domain', 'level': domain, 'strategy': 'NC-goal', 'child_of': 'ST-top',
                                   'owner_role': 'manager', 'validated': {'by': 'Daniel', 'date': DAY}, **node}
        self.files['ST-program'] = {'id': 'ST-program', 'level': program, 'strategy': 'NC-part', 'child_of': 'ST-domain',
                                    'owner_role': 'domain-coordinator', 'decomposes_into': ['WORK-program-p'],
                                    'validated': {'by': 'manager', 'date': DAY}, **node}
        self.appraisal = {'id': 'D-1', 'decision': 'D-1', 'criteria': [{'nc': 'NC-goal', 'weight': 1}],
                          'criteria_fixed': DAY, 'options': ['INJ-do-nothing', 'INJ-do-minimum', 'INJ-proposal'],
                          'scores': [{'option': option, 'nc': 'NC-goal', 'value': 1, 'evidence': 'x'}
                                     for option in ('INJ-do-nothing', 'INJ-do-minimum', 'INJ-proposal')],
                          'scored': DAY, 'chosen': 'INJ-proposal', 'why': 'x', 'revert': 'x', 'owner': 'Daniel',
                          'source': 'x'}

    def found(self, states=None, edit=None, appraisal=None):
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
        found['WORK-program-p'] = {'id': 'WORK-program-p', 'type': 'WORK', 'state': 'in-progress', 'fingerprint': 'f',
                                   'links': [], 'source': 'x', 'body': {'program': 'p'}}
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
                files[ident]['tactic'] = 'the step'
        cases = ((cycle, 'has a cycle'), (no_cloud, 'no conflict perpetuates'), (no_minimum, 'no do-minimum'),
                 (stray_strategy, 'does not descend'), (unchosen_tactic, 'is no chosen injection'),
                 (wrong_writer, 'is written by the domain-coordinator'), (orphan, 'outside the strategy and tactics'),
                 (no_tactic, "no node's tactic"))
        for edit, said in cases:
            errors = problem_space.problem_errors(self.found(edit=edit))
            self.assertTrue(any(said in line for line in errors), (said, errors))

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
        open_ = [ident for ident, item in found.items() if item['type'] in kinds
                 and not model.covered(meta, item, into, found)]
        self.assertEqual(open_, [])


if __name__ == '__main__':
    unittest.main()
