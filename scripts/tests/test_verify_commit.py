"""The verifier thread's gate (scripts/verify-commit): the gate's plan run on the exact commit, its verdict published as
the commit's tower/gate status. Hermetic: a fake run answers git, gate-check and gh."""
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import verify_commit  # noqa: E402

SHA, BASE = 'a' * 40, 'b' * 40
PLAN = {'stages': ['pr metadata', 'structure check', 'secret scan (tree)'], 'tests': ['scripts/tests/x.test.sh',
                                                                                     'scripts/tests/y.test.sh']}


class Fake:
    def __init__(self, red=(), head=SHA, plan=PLAN):
        self.red, self.head, self.plan, self.calls, self.statuses = set(red), head, plan, [], []

    def __call__(self, args, cwd=None, env=None):
        self.calls.append(list(args))
        if args[:2] == ['git', 'rev-parse']:
            return 0, self.head + '\n'
        if args[:2] == ['git', 'remote']:
            return 0, 'https://github.com/openuniversity-si/open-university.git\n'
        if args[:3] == ['scripts/gate-check', 'plan', 'checks']:
            Path(env['TOWER_ANSWER_FILE']).write_text(json.dumps({'plan': self.plan}))
            return 0, 'planned'
        if args[:2] == ['scripts/gate-check', 'stage']:
            return (1 if args[2] in self.red else 0), ''
        if args[:2] == ['scripts/gate-check', 'tests']:
            said = {test: 'FAIL' if test in self.red else 'PASS' for test in args[2].split(',')}
            Path(env['TOWER_ANSWER_FILE']).write_text(json.dumps({'tests': said}))
            return (1 if self.red & set(said) else 0), ''
        if args[:2] == ['gh', 'api']:
            fields = dict(each.split('=', 1) for each in args[args.index('-X') + 3:][1::2])
            self.statuses.append((args[4], fields['state'], fields['context'], fields['description']))
            return 0, '{}'
        raise AssertionError(args)


class TheVerifier(unittest.TestCase):
    def test_a_green_commit_is_pending_then_success_on_its_own_sha(self):
        fake = Fake()
        self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE], run=fake), 0)
        url = f'repos/openuniversity-si/open-university/statuses/{SHA}'
        self.assertEqual([(each[0], each[1], each[2]) for each in fake.statuses],
                         [(url, 'pending', 'tower/gate'), (url, 'success', 'tower/gate')])
        self.assertTrue(fake.statuses[-1][3].startswith('green: 4 check(s)'))  # 2 stages (pr metadata skipped) + 2 tests

    def test_only_the_plans_stages_and_tests_run_and_pr_metadata_is_skipped(self):
        fake = Fake()
        verify_commit.main(['--sha', SHA, '--base', BASE], run=fake)
        stages = [call[2] for call in fake.calls if call[:2] == ['scripts/gate-check', 'stage']]
        self.assertEqual(stages, ['structure check', 'secret scan (tree)'])
        self.assertIn(['scripts/gate-check', 'tests', 'scripts/tests/x.test.sh,scripts/tests/y.test.sh'], fake.calls)
        self.assertIn(['scripts/gate-check', 'plan', 'checks', '--base', BASE], fake.calls)

    def test_a_red_stage_or_test_is_a_failure_naming_it(self):
        fake = Fake(red=('structure check', 'scripts/tests/y.test.sh'))
        self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE], run=fake), 1)
        self.assertEqual(fake.statuses[-1][1:3], ('failure', 'tower/gate'))
        self.assertEqual(fake.statuses[-1][3], 'red: structure check, scripts/tests/y.test.sh')

    def test_a_commit_that_is_not_the_checkout_is_never_judged_nor_published(self):
        fake = Fake(head='c' * 40)
        self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE], run=fake), 2)
        self.assertEqual(fake.statuses, [])

    def test_no_post_judges_and_publishes_nothing(self):
        fake = Fake()
        self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post'], run=fake), 0)
        self.assertEqual(fake.statuses, [])

    def test_a_plan_that_cannot_be_made_is_an_error_status(self):
        fake = Fake(plan=None)
        fake.plan = None

        def broken(args, cwd=None, env=None):
            if args[:3] == ['scripts/gate-check', 'plan', 'checks']:
                return 1, 'no base'
            return fake(args, cwd, env)
        self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE], run=broken), 1)
        self.assertEqual(fake.statuses[-1][1], 'error')

    def test_the_tower_gate_workflow_is_the_one_allowed_and_runs_the_verifier_on_the_queue_too(self):
        # the Torre's choice (a), 14/11/2026: a GitHub-hosted job, free on a public repository, named as the check
        import config
        self.assertEqual(config.get('gate.allowed_workflows'), ['.github/workflows/tower-gate.yml'])
        staged = (ROOT / 'services' / 'runner' / 'github' / 'tower-gate.yml').read_text(encoding='utf-8')
        for line in ('  pull_request:', '  merge_group:', '    name: tower/gate',
                     'scripts/verify-commit --sha "$GITHUB_SHA" --base "$base" --repo "$GITHUB_REPOSITORY" --no-post'):
            self.assertIn(line, staged)
        ruleset = json.loads((ROOT / '.github' / 'rulesets' / 'main.json').read_text(encoding='utf-8'))
        rules = {rule['type']: rule.get('parameters') for rule in ruleset['rules']}
        self.assertEqual(rules['required_status_checks']['required_status_checks'], [{'context': 'tower/gate'}])
        self.assertEqual(rules['merge_queue']['merge_method'], 'MERGE')


if __name__ == '__main__':
    unittest.main()
