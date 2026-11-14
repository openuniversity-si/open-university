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
    def __init__(self, red=(), head=SHA, plan=PLAN, crowded=()):
        """crowded: tests red in the batch and green alone (VERIFY-ALONE)."""
        self.red, self.head, self.plan, self.calls, self.statuses = set(red), head, plan, [], []
        self.crowded = set(crowded)

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
            return (1, f'stage {args[2]} said why') if args[2] in self.red else (0, 'quiet')
        if args[:2] == ['scripts/gate-check', 'test']:
            return (1, f'FAIL {args[2]} alone: the traceback') if args[2] in self.red else (0, 'PASS')
        if args[:2] == ['scripts/gate-check', 'tests']:
            said = {test: 'FAIL' if test in self.red | self.crowded else 'PASS' for test in args[2].split(',')}
            Path(env['TOWER_ANSWER_FILE']).write_text(json.dumps({'tests': said}))
            return ((1, 'x' * 9000 + 'FAIL scripts/tests/y.test.sh: the traceback') if (self.red | self.crowded) & set(said)
                    else (0, 'quiet'))
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

    def test_a_red_stage_or_test_prints_the_end_of_its_output_and_a_green_one_prints_none(self):
        """VERIFY-TAIL: a hosted job keeps only what the verifier prints, so a red one prints why."""
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post'],
                               run=Fake(red=('structure check', 'scripts/tests/y.test.sh')))
        said = err.getvalue()
        self.assertIn('--- verify-commit: the end of the output of structure check ---\nstage structure check said why', said)
        self.assertIn('--- verify-commit: the end of the output of scripts/tests/y.test.sh (alone) ---\nFAIL scripts/tests/y.test.sh alone', said)
        self.assertLess(len(said), verify_commit.TAIL + 400)  # the end only
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post'], run=Fake())
        self.assertNotIn('the end of the output', err.getvalue())
        err = io.StringIO()
        with contextlib.redirect_stderr(err):  # a secret scan's output may quote the secret: never printed
            verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post'], run=Fake(red=('secret scan (tree)',)))
        self.assertIn('secret scan (tree) ---\nits output is not printed (a secret scan)', err.getvalue())
        self.assertNotIn('said why', err.getvalue())

    def test_a_test_red_in_the_batch_runs_alone_and_its_alone_verdict_counts_and_is_said(self):
        """VERIFY-ALONE: the engine's FULL-RUN-ALONE; a real regression is red alone too."""
        import contextlib
        import io
        fake, out = Fake(crowded=('scripts/tests/x.test.sh',)), io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE], run=fake), 0)
        self.assertIn(['scripts/gate-check', 'test', 'scripts/tests/x.test.sh'], fake.calls)
        self.assertNotIn(['scripts/gate-check', 'test', 'scripts/tests/y.test.sh'], fake.calls)  # green in the batch
        self.assertEqual(fake.statuses[-1][1], 'success')
        self.assertTrue(fake.statuses[-1][3].endswith(', 1 green only alone'), fake.statuses[-1][3])
        self.assertIn('red in the batch and green alone: scripts/tests/x.test.sh', out.getvalue())
        fake = Fake(red=('scripts/tests/y.test.sh',), crowded=('scripts/tests/x.test.sh',))
        self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE], run=fake), 1)
        self.assertEqual(fake.statuses[-1][1:], ('failure', 'tower/gate', 'red: scripts/tests/y.test.sh'))

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

    def test_the_deploy_doorbell_rings_on_a_merge_to_main_with_the_secrets_only(self):
        staged = (ROOT / 'services' / 'runner' / 'github' / 'deploy-doorbell.yml').read_text(encoding='utf-8')
        for line in ('  push:', '    branches: [main]', 'run: python3 scripts/lib/deploy.py ring',
                     '${{ secrets.TOWER_DEPLOY_DOORBELL_TOKEN }}', '  contents: read'):
            self.assertIn(line, staged)
        self.assertNotIn('pull_request', staged)  # never a pull request's code: only what main merged

    def test_the_tower_gate_workflow_is_the_one_allowed_and_runs_the_verifier_on_the_queue_too(self):
        # the Torre's choice (a), 14/11/2026: a GitHub-hosted job, free on a public repository, named as the check
        import config
        self.assertEqual(config.get('gate.allowed_workflows'), ['.github/workflows/tower-gate.yml', '.github/workflows/deploy-doorbell.yml'])
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
