"""The PR body from the commits (D-208): one checklist line per Plan trailer, the trailers and the footer (the effort block
left with D-328). Pure functions over given commit messages; no git, no network.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import pr_body  # noqa: E402
import commit_check  # noqa: E402
import structure  # noqa: E402

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'pr-body.json').read_text())


class Body(unittest.TestCase):
    def setUp(self):
        self.commits = [(message.split('\n', 1)[0], message) for message in FIXTURE['commits']]

    def text(self):
        return pr_body.body(FIXTURE['title'], self.commits, FIXTURE['session'])

    def test_each_plan_item_is_one_line_with_the_subject_of_its_first_commit(self):
        text = self.text()
        for item in FIXTURE['items']:
            self.assertIn(f"- [x] {item['number']}. {item['subject']}", text)

    def test_the_plan_is_one_line_per_item_named_by_a_trailer_with_the_first_subject(self):
        lines = pr_body.plan_from_commits([('first part', 'first part\n\nPlan: 1'), ('more', 'more\n\nPlan: 1, 2'),
                                           ('no item', 'no item')])
        self.assertEqual(lines, ['### Commit plan', '- [x] 1. first part', '- [x] 2. more'])

    def test_the_trailers_are_present_and_no_effort_block(self):
        text = self.text()
        self.assertNotIn('## Cheapest useful effort', text)  # D-328
        self.assertIn('Fit-Review: not reviewed (Daniel 2026-10-25: no review step)', text)
        self.assertIn('Premises: none', text)
        self.assertIn(f"Claude-Session: {FIXTURE['session']}", text)

    def test_the_body_passes_the_structure_check_with_no_warning(self):
        """What `scripts/structure-check --pr-body` judges of the body itself: B5 trailers and commit plan
        (`Premises: none` cites no premise, so the register is not read)."""
        text = self.text()
        errors, warnings = structure.fit_review(text, ROOT)
        errors += commit_check.plan_errors(text)
        self.assertEqual((errors, warnings), ([], []))

    def test_the_fit_review_is_the_one_the_lane_contract_names(self):
        contract = (ROOT / 'docs' / 'process' / 'lane.md').read_text()
        self.assertIn(f'`Fit-Review: {pr_body.FIT_REVIEW}`', contract)
        self.assertTrue(structure.NOT_REVIEWED.match(pr_body.FIT_REVIEW))

    def test_the_footer_is_the_attribution_line(self):
        self.assertIn('Generated with [Claude Code]', self.text())


class Session(unittest.TestCase):
    """The Claude-Session: trailer (D-007): --session, else $CLAUDE_SESSION_URL, else a refusal before git is read."""
    ARGS = ['--title', 't']

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


if __name__ == '__main__':
    unittest.main()
