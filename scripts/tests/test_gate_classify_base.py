"""The base class (F73): a red stage whose every failing test, still the PR's after the known-defect step and the flake
re-run, is red on the base head too is classed base; the stage stays red. Fakes stand for the base run. No network."""
import hashlib
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
import defect_detect  # noqa: E402
import gate_classify  # noqa: E402

HEAD = hashlib.sha1(b'head').hexdigest()
BASE = hashlib.sha1(b'base').hexdigest()
A, B = 'scripts/tests/a.test.sh', 'scripts/tests/b.test.sh'
ASSERTION = 'AssertionError: 0 != 1'
STAGE = 'script tests'


class BaseClass(unittest.TestCase):
    def test_a_stage_whose_failing_tests_are_red_on_the_base_is_base(self):
        log = '\n'.join([ASSERTION, gate_classify.base_red(A, BASE), gate_classify.base_red(B, BASE)])
        self.assertEqual(gate_classify.classify(STAGE, log), 'base')

    def test_one_test_green_on_the_base_keeps_the_stage_code(self):
        log = '\n'.join([ASSERTION, gate_classify.base_red(A, BASE),
                         gate_classify.base_own(B, 'it passes on the base head')])
        self.assertEqual(gate_classify.classify(STAGE, log), 'code')

    def test_env_contract_and_flake_keep_their_class(self):
        self.assertEqual(gate_classify.classify('gate preflight', gate_classify.base_red(A, BASE)), 'env')
        self.assertEqual(gate_classify.classify(STAGE, 'conflicting rules\n' + gate_classify.base_red(A, BASE)), 'contract')
        self.assertEqual(gate_classify.classify(STAGE, gate_classify.flake_passed(A)), 'flake')

    def test_the_human_and_machine_lines_name_the_base_action(self):
        log = gate_classify.base_red(A, BASE)
        self.assertTrue(gate_classify.line(STAGE, log).startswith('class: base — nothing to rework in this PR'))
        self.assertEqual(gate_classify.class_line(STAGE, 'base'), f"{config.get('gate.class_line_prefix')} {STAGE}\tbase")


class AttributeBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = self.tmp / 'logs'
        self.logs.mkdir()
        self.asked = []

    def records(self, *tests):
        (self.logs / 'script-tests.json').write_text(json.dumps(
            [{'test': t, 'result': 'FAIL', 'cached': False, 'key': '', 'source': 'x', 'tail': [f'{ASSERTION} {t}']}
             for t in tests]))

    def report(self, **extra):
        return {'sha': HEAD, 'result': 'FAIL', 'stages': [{'name': STAGE, 'result': 'FAIL', 'seconds': 1}], **extra}

    def attribute(self, report, results, present=lambda test, sha: True):
        def outcome(test, sha):
            self.asked.append((test, sha))
            return {'result': results[test], 'signature': 'sig'}
        return gate_classify.attribute_base(report, self.logs, BASE, self.tmp, outcome, present)

    def last_class(self):
        lines = gate_classify.stage_log(self.logs, STAGE).read_text().splitlines()
        return [line for line in lines if line.startswith(config.get('gate.class_line_prefix'))][-1].rsplit('\t', 1)[1]

    def test_every_failing_test_red_on_the_base_head_classes_the_stage_base_and_keeps_it_red(self):
        self.records(A, B)
        report = self.report()
        red = self.attribute(report, {A: defect_detect.FAIL, B: defect_detect.FAIL})
        self.assertEqual([item['id'] for item in red], [A, B])
        self.assertEqual((report['result'], report['stages'][0]['result'], report['stages'][0]['class']), ('FAIL', 'FAIL', 'base'))
        self.assertEqual(self.last_class(), 'base')
        self.assertEqual(self.asked, [(A, BASE), (B, BASE)])

    def test_a_test_green_on_the_base_head_keeps_the_stage_code(self):
        self.records(A, B)
        report = self.report()
        self.attribute(report, {A: defect_detect.FAIL, B: defect_detect.PASS})
        self.assertEqual(report['stages'][0]['class'], 'code')
        self.assertIn(gate_classify.base_own(B, 'it passes on the base head'), gate_classify.stage_log(self.logs, STAGE).read_text())

    def test_a_test_that_could_not_run_on_the_base_keeps_the_stage_code(self):
        self.records(A)
        report = self.report()
        self.attribute(report, {A: defect_detect.ERROR})
        self.assertEqual(report['stages'][0]['class'], 'code')

    def test_a_test_the_base_does_not_have_is_the_prs_own_and_never_run_there(self):
        self.records(A)
        report = self.report()
        self.attribute(report, {A: defect_detect.FAIL}, present=lambda test, sha: False)
        self.assertEqual((report['stages'][0]['class'], self.asked), ('code', []))

    def test_known_defects_and_flakes_are_not_run_again(self):
        self.records(A, B)
        report = self.report(known_defects=[{'id': A}])
        self.attribute(report, {B: defect_detect.FAIL})
        self.assertEqual((self.asked, report['stages'][0]['class']), ([(B, BASE)], 'base'))

    def test_a_green_report_or_no_base_runs_nothing(self):
        self.records(A)
        self.assertEqual(gate_classify.attribute_base(dict(self.report(), result='PASS'), self.logs, BASE), [])
        self.assertEqual(gate_classify.attribute_base(self.report(), self.logs, None), [])

    def test_on_base_reads_the_base_tree(self):
        repo = self.tmp / 'repo'
        git = ['git', '-C', str(repo), '-c', 'user.email=t@t', '-c', 'user.name=t', '-c', 'commit.gpgsign=false']
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        (repo / 'scripts' / 'tests').mkdir(parents=True)
        (repo / A).write_text('exit 1\n')
        subprocess.run(git + ['add', '.'], check=True)
        subprocess.run(git + ['commit', '-qm', 'a'], check=True)
        sha = subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip()
        self.assertEqual((gate_classify.on_base(A, sha, repo), gate_classify.on_base(B, sha, repo)), (True, False))


if __name__ == '__main__':
    unittest.main()
