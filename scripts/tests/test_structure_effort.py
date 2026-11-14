"""The cheapest-useful-effort check (EFFORT-STEP; D-069 items 4, 8 and 9, D-065 (5)): the block's four fields, the owner
rule, the shrink-only plan baseline and the repository's own plans. Fixture repositories in a temporary directory with a
copy of the registry; no network, no clock, no random source.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import effort  # noqa: E402
import structure  # noqa: E402

REGISTRY = ('config/registry/effort.json', 'config/registry/units.json', 'config/registry/config.json',
            'contracts/config/registry.v1.json')
COMPLETE = '''# Plan

## Cheapest useful effort
Action: the final gate-dev on the head.
Cost: 15 min wall.
Requirement: Daniel needs the merge door to prove the refusal.
Cheaper rejected: the targeted tests only (they do not run the real stage plan).

## Next
'''


def block(**values):
    fields = {'Action': 'run the battery', 'Cost': '15 min', 'Requirement': 'Daniel, before the release',
              'Cheaper rejected': 'gate-dev only (never runs WebKit)'}
    fields.update(values)
    lines = [f'{name}: {value}' for name, value in fields.items() if value is not None]
    return '## Cheapest useful effort\n' + '\n'.join(lines) + '\n'


def git(root, *args):
    subprocess.run(['git', '-C', str(root), '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True,
                   capture_output=True)


class Block(unittest.TestCase):
    def errors(self, text):
        return effort.errors(text, 'plan.md', ROOT)

    def test_a_complete_block_is_green(self):
        self.assertEqual(self.errors(COMPLETE), [])
        self.assertEqual(self.errors(block()), [])

    def test_bullets_bold_and_continuation_lines_are_read(self):
        text = ('## Cheapest useful effort\n- **Action:** the battery\n- **Cost:** 15 min\n'
                '- **Requirement:** the learner\n- **Cheaper rejected:**\n  gate-dev only, it never runs WebKit\n')
        self.assertEqual(effort.fields(text, effort.settings(ROOT))['Cheaper rejected'], 'gate-dev only, it never runs WebKit')
        self.assertEqual(self.errors(text), [])

    def test_no_block_is_red_and_names_the_fields_and_the_rule(self):
        [error] = self.errors('# Plan\n\nAction: x\n')
        self.assertIn('has no `## Cheapest useful effort` block', error)
        self.assertIn('`Cheaper rejected:`', error)
        self.assertIn(config.get('effort.rule_doc', ROOT), error)

    def test_a_plan_without_cheaper_rejected_is_red(self):
        [error] = self.errors(block(**{'Cheaper rejected': None}))
        self.assertIn('`Cheaper rejected:` is missing', error)
        self.assertIn('docs/padrao/v4/effort.md', error)

    def test_each_missing_field_is_named(self):
        for name in config.get('effort.fields', ROOT):
            with self.subTest(name):
                errors = self.errors(block(**{name: None}))
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(f'`{name}:` is missing', errors[0])

    def test_an_empty_or_placeholder_field_is_red(self):
        for value in ('', 'none', 'N/A', '`TBD`', '-', '...'):
            with self.subTest(value):
                errors = self.errors(block(**{'Cheaper rejected': value}))
                self.assertEqual(len(errors), 1, errors)
                self.assertIn('`Cheaper rejected:` is empty or a placeholder', errors[0])

    def test_a_requirement_that_names_the_gate_the_train_or_the_tests_is_red(self):
        for value, word in (('the pr-mode gate is green', 'gate'), ('the train merges it', 'train'),
                            ('the tests pass', 'tests'), ('gate-dev passes on the head', 'gate-dev')):
            with self.subTest(value):
                [error] = self.errors(block(Requirement=value))
                self.assertIn('`Requirement:` names', error)
                self.assertIn(word, error)
                self.assertIn('(a machine) instead of an owner', error)

    def test_a_requirement_with_no_owner_is_red(self):
        [error] = self.errors(block(Requirement='faster builds'))
        self.assertIn('`Requirement:` names no owner', error)

    def test_a_person_a_role_or_a_lane_satisfies_the_owner_rule(self):
        for value in ('Daniel needs the gate green to merge', 'A Torre, for the train', 'the learner',
                      'engine-lane needs the tests to pass'):
            with self.subTest(value):
                self.assertEqual(self.errors(block(Requirement=value)), [])

    def test_the_lanes_come_from_the_registry_list_the_owner_registry_names(self):
        lanes = config.get(config.get('effort.owner_registry', ROOT), ROOT)
        self.assertTrue(lanes)
        self.assertTrue(set(lanes) <= set(effort.settings(ROOT)['owners']))

    def test_a_fenced_example_is_not_the_block(self):
        self.assertEqual(len(self.errors('# Rule\n```\n' + block() + '```\n')), 1)

    def test_the_block_ends_at_the_next_heading(self):
        text = '## Cheapest useful effort\nAction: a\nCost: b\n\n## Later\nRequirement: Daniel\nCheaper rejected: c\n'
        missing = [error for error in self.errors(text) if 'is missing' in error]
        self.assertEqual([('`Requirement:`' in error, '`Cheaper rejected:`' in error) for error in missing],
                         [(True, False), (False, True)])

    def test_the_check_never_judges_the_content(self):
        self.assertEqual(self.errors(block(Cost='three weeks and a new vendor', Action='rewrite everything')), [])

    def test_body_errors_names_the_pr_body(self):
        [error] = effort.body_errors('Summary only.\n', ROOT)
        self.assertIn('the PR body has no', error)


class Bodies(unittest.TestCase):
    """The body's own grandfathering.

    The two mutations that prove these tests bite, run on 28/10 and restored afterwards:
    (1) `body_grandfathered` always False -> `test_a_pr_opened_before_the_rule_is_not_judged_by_it` fails, alone;
    (2) the "it carries a block" guard removed -> `test_an_old_pr_that_carries_a_block_is_judged_by_it` fails, alone.
    A test that no mutation can break is a test that measures nothing.: a PR opened before the rule existed cannot carry the block, and the gate of
    28/10 refused all twenty open PRs for exactly that, each with nineteen stages green."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        for name in REGISTRY:
            (self.dir / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.dir / name)
        git(self.dir, 'init', '-q')
        (self.dir / 'config/registry/effort.json').unlink()
        (self.dir / 'README.md').write_text('x\n')
        self.commit_at('2026-10-20T10:00:00-03:00')     # before the rule
        shutil.copy(ROOT / 'config/registry/effort.json', self.dir / 'config/registry/effort.json')
        self.commit_at('2026-10-28T17:00:00-03:00')     # the rule lands (20:00 UTC)

    def commit_at(self, when):
        import os
        env = dict(os.environ, GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
        git(self.dir, 'add', '-A')
        subprocess.run(['git', '-C', str(self.dir), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q',
                        '-m', 'x'], check=True, env=env)

    def errors(self, body, created):
        return effort.body_errors(body, self.dir, created=created)

    def test_a_pr_opened_before_the_rule_is_not_judged_by_it(self):
        self.assertEqual(self.errors('Summary only.\n', '2026-10-27T13:20:00Z'), [])

    def test_a_pr_opened_after_the_rule_is_judged(self):
        [error] = self.errors('Summary only.\n', '2026-10-28T21:00:00Z')  # 18:00 local, after the rule
        self.assertIn('the PR body has no', error)

    def test_an_old_pr_that_carries_a_block_is_judged_by_it(self):
        """The exemption is for having no block, not for being old: a block with a missing field is still red."""
        found = self.errors('## Cheapest useful effort\nAction: a\nCost: b\n', '2026-10-27T13:20:00Z')
        self.assertTrue([e for e in found if 'Requirement' in e], found)
        self.assertTrue([e for e in found if 'Cheaper rejected' in e], found)

    def test_without_a_birth_date_the_body_is_judged(self):
        [error] = self.errors('Summary only.\n', None)
        self.assertIn('the PR body has no', error)

    def test_without_the_rule_in_the_checkout_the_body_is_judged(self):
        (self.dir / 'config/registry/effort.json').unlink()
        self.commit_at('2026-10-28T22:00:00-03:00')
        [error] = self.errors('Summary only.\n', '2026-10-27T13:20:00Z')
        self.assertIn('the PR body has no', error)

    def test_an_unreadable_stamp_does_not_exempt_anything(self):
        [error] = self.errors('Summary only.\n', 'not a date')
        self.assertIn('the PR body has no', error)


class Stage(unittest.TestCase):
    """The `pr metadata` stage (structure-check --metadata) refuses a body without the block, through --pr-body and
    through --pr; the `structure check` stage (the tree part) refuses a plan without it."""

    BODY = 'Summary.\n\nPremises: none\nFit-Review: not reviewed (Daniel 2026-10-25: no review step)\n'

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def metadata(self, body):
        path = self.dir / 'body.md'
        path.write_text(body)
        env = {name: value for name, value in os.environ.items() if name != structure.TREE_ONLY_ENV}
        result = subprocess.run(['bash', str(ROOT / 'scripts/structure-check'), '--metadata', '--pr-body', str(path)],
                                capture_output=True, text=True, env=env, cwd=ROOT)
        return result.returncode, result.stdout + result.stderr

    def test_the_stage_refuses_a_real_body_without_the_block_and_accepts_it_with(self):
        code, out = self.metadata(self.BODY)
        self.assertEqual(code, 1, out)
        self.assertIn('effort: the PR body has no `## Cheapest useful effort` block', out)
        self.assertIn('docs/padrao/v4/effort.md', out)
        code, out = self.metadata(block() + '\n' + self.BODY)
        self.assertNotIn('effort:', out)

    def test_the_stage_names_the_missing_field(self):
        code, out = self.metadata(block(**{'Cheaper rejected': None}) + '\n' + self.BODY)
        self.assertEqual(code, 1, out)
        self.assertIn('`Cheaper rejected:` is missing', out)

    def test_the_pr_branch_judges_the_fetched_body(self):
        args = argparse.Namespace(pr_body=None, pr='N', sha=None, review=None, base=None)
        pr = {'body': self.BODY, 'commits': [], 'files': [], 'branch': 'mod/x', 'base': {}}
        with patch.object(structure, 'gated_fetch', return_value=pr), \
                patch.object(structure.commit_check, 'check', return_value=[]):
            errors, _, _ = structure.metadata_part(ROOT, args)
            self.assertTrue([error for error in errors if error.startswith('effort: the PR body has no')], errors)
            pr['body'] = block() + '\n' + self.BODY
            errors, _, _ = structure.metadata_part(ROOT, args)
            self.assertFalse([error for error in errors if error.startswith('effort:')], errors)


class Repository(unittest.TestCase):
    def test_the_rule_and_the_checklist_name_every_field_the_check_reads(self):
        rule = (ROOT / config.get('effort.rule_doc', ROOT)).read_text()
        checklist = (ROOT / config.get('effort.rule_doc', ROOT)).with_name('audit-and-plan.md').read_text()
        heading = config.get('effort.heading', ROOT)
        for text in (rule, checklist):
            self.assertIn(f'## {heading}', text)
            for name in config.get('effort.fields', ROOT):
                self.assertIn(f'`{name}:`', text)


if __name__ == '__main__':
    unittest.main()
