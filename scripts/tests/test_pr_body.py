"""The PR body from the commits (D-208): one checklist line per Plan trailer, the effort block from four fields, the trailers
and the footer. Pure functions over given commit messages; no git, no network.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import pr_body  # noqa: E402
import commit_check  # noqa: E402
import effort  # noqa: E402
import structure  # noqa: E402

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'pr-body.json').read_text())


class Body(unittest.TestCase):
    def setUp(self):
        self.commits = [(message.split('\n', 1)[0], message) for message in FIXTURE['commits']]

    def text(self):
        return pr_body.body(FIXTURE['title'], self.commits, FIXTURE['action'], FIXTURE['cost'], FIXTURE['requirement'],
                            FIXTURE['cheaper'], FIXTURE['session'])

    def test_each_plan_item_is_one_line_with_the_subject_of_its_first_commit(self):
        text = self.text()
        for item in FIXTURE['items']:
            self.assertIn(f"- [x] {item['number']}. {item['subject']}", text)

    def test_the_plan_is_one_line_per_item_named_by_a_trailer_with_the_first_subject(self):
        lines = pr_body.plan_from_commits([('first part', 'first part\n\nPlan: 1'), ('more', 'more\n\nPlan: 1, 2'),
                                           ('no item', 'no item')])
        self.assertEqual(lines, ['### Commit plan', '- [x] 1. first part', '- [x] 2. more'])

    def test_the_effort_block_and_the_trailers_are_present(self):
        text = self.text()
        self.assertIn('## Cheapest useful effort', text)
        self.assertIn(f"- Requirement: {FIXTURE['requirement']}", text)
        self.assertIn('Fit-Review: not reviewed (Daniel 2026-10-25: no review step)', text)
        self.assertIn('Premises: none', text)
        self.assertIn(f"Claude-Session: {FIXTURE['session']}", text)

    def test_the_body_passes_the_structure_check_with_no_warning(self):
        """What `scripts/structure-check --pr-body` judges of the body itself: B5 trailers, commit plan and effort block
        (`Premises: none` cites no premise, so the register is not read)."""
        text = self.text()
        errors, warnings = structure.fit_review(text, ROOT)
        errors += commit_check.plan_errors(text) + effort.body_errors(text, ROOT)
        self.assertEqual((errors, warnings), ([], []))

    def test_the_fit_review_is_the_one_the_lane_contract_names(self):
        contract = (ROOT / 'docs' / 'process' / 'lane.md').read_text()
        self.assertIn(f'`Fit-Review: {pr_body.FIT_REVIEW}`', contract)
        self.assertTrue(structure.NOT_REVIEWED.match(pr_body.FIT_REVIEW))

    def test_the_footer_is_the_attribution_line(self):
        self.assertIn('Generated with [Claude Code]', self.text())


class Session(unittest.TestCase):
    """The Claude-Session: trailer (D-007): --session, else $CLAUDE_SESSION_URL, else a refusal before git is read."""
    ARGS = ['--title', 't', '--action', 'a', '--cost', 'c', '--requirement', 'engine-lane needs it', '--cheaper', 'x']

    def run_main(self, argv, env):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(pr_body.plan_tick, 'commit_messages',
                                                                              return_value=['one\n\nPlan: 1\n']), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pr_body.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_the_session_defaults_to_the_environment(self):
        code, out, _ = self.run_main(self.ARGS, {pr_body.SESSION_ENV: FIXTURE['session']})
        self.assertEqual(code, 0)
        self.assertIn(f"Claude-Session: {FIXTURE['session']}", out)

    def test_the_option_wins_over_the_environment(self):
        code, out, _ = self.run_main(self.ARGS + ['--session', 'session-of-the-option'], {pr_body.SESSION_ENV: FIXTURE['session']})
        self.assertEqual(code, 0)
        self.assertIn('Claude-Session: session-of-the-option', out)
        self.assertNotIn(FIXTURE['session'], out)

    def test_no_session_is_refused(self):
        code, out, err = self.run_main(self.ARGS, {pr_body.SESSION_ENV: ''})
        self.assertTrue(code)
        self.assertEqual(out, '')
        self.assertIn('--session URL or set CLAUDE_SESSION_URL', err)


class Requirement(unittest.TestCase):
    """VAZÃO F75: the body is refused before it is built when its requirement names no owner the gate accepts."""
    VALUES = {'owners': ['Daniel', 'coordinator', 'engine-lane'], 'effort.owners': ['Daniel', 'coordinator'],
              'effort.owner_registry': 'units.owners', 'effort.rule_doc': 'docs/padrao/v4/effort.md'}

    def test_an_owner_word_or_a_lane_passes(self):
        self.assertIsNone(pr_body.requirement_problem('the coordinator needs the rows', self.VALUES))
        self.assertIsNone(pr_body.requirement_problem('engine-lane, before the next unit', self.VALUES))

    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        unit = Path(self.root.name) / 'units' / 'engine-gate-tests'
        unit.mkdir(parents=True)
        (unit / 'unit.json').write_text(json.dumps({'id': 'engine-gate-tests', 'owner': 'engine-lane'}))
        self.addCleanup(self.root.cleanup)

    def test_no_owner_is_refused_with_the_valid_owners_and_concrete_examples_listed(self):
        problem = pr_body.requirement_problem('the manager and the lanes need it', self.VALUES, self.root.name)
        self.assertIn('names no owner', problem)
        self.assertIn('Daniel, coordinator', problem)
        self.assertIn('1 lanes of units.owners (engine-lane)', problem)
        self.assertIn('--requirement "engine-lane needs one body per PR"', problem)
        self.assertIn('--requirement "Daniel needs', problem)

    def test_a_unit_name_is_refused_as_the_gate_refuses_it_and_its_owner_lane_is_named(self):
        """effort.py accepts owners and lanes, never unit ids; pr-body does not loosen that, it points at the lane."""
        requirement = 'engine-gate-tests needs the selection'
        self.assertTrue(effort.errors(f'## Cheapest useful effort\n- Action: a\n- Cost: c\n- Requirement: {requirement}\n'
                                      '- Cheaper rejected: x\n', 'body', ROOT))
        problem = pr_body.requirement_problem(requirement, self.VALUES, self.root.name)
        self.assertIn('"engine-gate-tests" is a unit, not an owner: name its owner lane engine-lane.', problem)
        self.assertIn('--requirement "engine-lane needs one body per PR"', problem)

    def test_every_suggested_example_passes_the_gate(self):
        problem = pr_body.requirement_problem('engine-gate-tests needs it', root=ROOT)
        examples = [part.split('"')[1] for part in problem.split('For example: ')[1].split('; ')]
        self.assertTrue(examples)
        for example in examples:
            self.assertIsNone(pr_body.requirement_problem(example, root=ROOT), example)

    def test_main_refuses_before_reading_git(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = pr_body.main(['--title', 't', '--action', 'a', '--cost', 'c', '--requirement', 'the gate is green',
                                 '--cheaper', 'x', '--session', 's', '--base', 'no-such-ref'])
        self.assertEqual(code, 2)
        self.assertIn('names no owner', err.getvalue())


if __name__ == '__main__':
    unittest.main()
