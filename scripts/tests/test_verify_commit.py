"""The verifier thread's gate (scripts/verify-commit): the gate's plan run on the exact commit, its verdict published as
the commit's tower/gate status. Hermetic: a fake run answers git, gate-check and gh."""
import json
import re
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import verify_commit  # noqa: E402

SHA, BASE = 'a' * 40, 'b' * 40
TREE, HEAD_OF_PR = 'e' * 40, 'd' * 40  # VERDICT-REUSE: the judged tree; the queue commit's parents are BASE and the PR head
IMAGE = {'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'X64', 'ImageOS': 'ubuntu24', 'ImageVersion': '20261109.1'}
PLAN = {'stages': ['pr metadata', 'structure check', 'secret scan (tree)'], 'tests': ['scripts/tests/x.test.sh',
                                                                                     'scripts/tests/y.test.sh']}


class Fake:
    def __init__(self, red=(), head=SHA, plan=PLAN, crowded=(), tree=TREE, parents=(BASE, HEAD_OF_PR), artifacts=None):
        """crowded: tests red in the batch and green alone (VERIFY-ALONE). artifacts: what the artifacts listing
        answers (VERDICT-REUSE), a list of artifacts, or a (code, text) pair."""
        self.red, self.head, self.plan, self.calls, self.statuses = set(red), head, plan, [], []
        self.crowded, self.tree, self.parents, self.artifacts = set(crowded), tree, list(parents), artifacts

    def __call__(self, args, cwd=None, env=None):
        self.calls.append(list(args))
        if args[:3] == ['git', 'rev-parse', 'HEAD^{tree}']:
            return 0, self.tree + '\n'
        if args[:3] == ['git', 'rev-list', '--parents']:
            return 0, ' '.join([self.head, *self.parents]) + '\n'
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
        if args[:2] == ['gh', 'api'] and '-X' not in args:
            if isinstance(self.artifacts, tuple):
                return self.artifacts
            return 0, json.dumps({'total_count': len(self.artifacts or []), 'artifacts': self.artifacts or []})
        if args[:2] == ['gh', 'api']:
            fields = dict(each.split('=', 1) for each in args[args.index('-X') + 3:][1::2])
            self.statuses.append((args[4], fields['state'], fields['context'], fields['description']))
            return 0, '{}'
        raise AssertionError(args)


def made(name, head_sha=HEAD_OF_PR, repository=1, head_repository=1, expired=False):
    """An artifact of the listing, as GitHub answers it (VERDICT-REUSE)."""
    return {'id': 5, 'name': name, 'expired': expired,
            'workflow_run': {'id': 77, 'repository_id': repository, 'head_repository_id': head_repository,
                             'head_branch': 'pr', 'head_sha': head_sha}}


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

    def recorded_name(self, **fake):
        """The artifact name a green pull request run records (VERDICT-REUSE), and the record it wrote."""
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            with contextlib.redirect_stdout(io.StringIO()):
                code = verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post', '--record', f'{tmp}/verdict'],
                                          run=Fake(**fake), environ={**IMAGE, 'GITHUB_OUTPUT': str(output)})
            said = output.read_text() if output.is_file() else ''
            record = json.loads((Path(tmp) / 'verdict' / 'verdict.json').read_text()) if code == 0 else None
        return code, said, record

    def reuse(self, environ=IMAGE, **fake):
        import contextlib
        import io
        fake, out = Fake(**fake), io.StringIO()
        with contextlib.redirect_stdout(out):
            code = verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post', '--reuse'], run=fake, environ=environ)
        return code, fake, out.getvalue()

    def test_a_green_verdict_is_recorded_by_its_key_and_a_red_one_never(self):
        """VERDICT-REUSE: the key covers the tree, the parents, the base, the plan and the runner image."""
        code, said, record = self.recorded_name()
        self.assertEqual(code, 0)
        self.assertRegex(said, r'^verdict=tower-gate-green-[0-9a-f]{64}\n$')
        self.assertEqual(said.strip().split('-')[-1], record['key'])
        self.assertEqual((record['tree'], record['parents'], record['base'], record['sha']), (TREE, [BASE, HEAD_OF_PR], BASE, SHA))
        self.assertEqual(record['stages'], ['secret scan (tree)', 'structure check'])  # pr metadata never runs here
        self.assertEqual(record['tests'], PLAN['tests'])
        self.assertEqual(record['runner'], IMAGE)
        for red in ('structure check', 'scripts/tests/y.test.sh'):
            self.assertEqual(self.recorded_name(red=(red,))[:2], (1, ''))

    def test_the_tests_green_verdict_of_the_same_key_stands_and_the_stages_still_run(self):
        name = self.recorded_name()[1].strip().split('=', 1)[1]
        code, fake, out = self.reuse(artifacts=[made(name)])
        self.assertEqual(code, 0)
        self.assertFalse([call for call in fake.calls if call[:2] in (['scripts/gate-check', 'tests'],
                                                                      ['scripts/gate-check', 'test'])])
        stages = [call[2] for call in fake.calls if call[:2] == ['scripts/gate-check', 'stage']]
        self.assertEqual(stages, ['structure check', 'secret scan (tree)'])  # they read the commit itself: they run
        self.assertIn(['gh', 'api', f'repos/openuniversity-si/open-university/actions/artifacts?name={name}&per_page=100'],
                      fake.calls)
        self.assertIn(', tests green in run 77', out)
        self.assertIn("the tests' green verdict of run 77 stands", out)
        code, fake, out = self.reuse(artifacts=[made(name)], red=('structure check',))  # a red stage is red
        self.assertEqual(code, 1)
        self.assertIn('red: structure check', out)

    def test_any_other_tree_parents_base_plan_image_or_record_runs_the_tests(self):
        """VERDICT-REUSE: never a red tree passed: a miss for anything but the exact key of this repository's run."""
        name = self.recorded_name()[1].strip().split('=', 1)[1]
        other_plan = {**PLAN, 'tests': PLAN['tests'][:1]}
        misses = {
            'another tree': dict(tree='f' * 40, artifacts=[made(name)]),
            'another first parent': dict(parents=('c' * 40, HEAD_OF_PR), artifacts=[made(name)]),
            'another plan': dict(plan=other_plan, artifacts=[made(name)]),
            "a fork's run": dict(artifacts=[made(name, head_repository=2)]),
            'an expired record': dict(artifacts=[made(name, expired=True)]),
            "a run on no parent's head": dict(artifacts=[made(name, head_sha='9' * 40)]),
            'no record': dict(artifacts=[]),
            'a listing that fails': dict(artifacts=(1, 'HTTP 403: Resource not accessible by integration')),
            'a listing that is not JSON': dict(artifacts=(0, 'not json')),
        }
        for why, fake in misses.items():
            with self.subTest(why):
                code, ran, out = self.reuse(**fake)
                self.assertEqual(code, 0)
                self.assertTrue([call for call in ran.calls if call[:2] == ['scripts/gate-check', 'tests']], why)
                self.assertNotIn('tests green in run', out)
        for environ in ({**IMAGE, 'ImageVersion': '20261116.1'}, {}):  # another runner image, or none named
            code, ran, out = self.reuse(environ=environ, artifacts=[made(name)])
            self.assertTrue([call for call in ran.calls if call[:2] == ['scripts/gate-check', 'tests']])
        code, ran, out = self.reuse(artifacts=[made(name)], red=('scripts/tests/y.test.sh',), tree='f' * 40)
        self.assertEqual(code, 1)  # a miss judges the tests: a red one is red
        import contextlib
        import io
        fake = Fake(artifacts=[made(name)])
        with contextlib.redirect_stdout(io.StringIO()):  # another base
            verify_commit.main(['--sha', SHA, '--base', 'c' * 40, '--no-post', '--reuse'], run=fake, environ=IMAGE)
        self.assertTrue([call for call in fake.calls if call[:2] == ['scripts/gate-check', 'tests']])

    def test_without_reuse_no_record_is_looked_up(self):
        fake = Fake(artifacts=[made('anything')])
        verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post'], run=fake, environ=IMAGE)
        self.assertFalse([call for call in fake.calls if call[:2] == ['gh', 'api']])

    def test_the_toolchain_cache_keeps_the_binaries_never_the_test_cluster_and_is_one_entry(self):
        """CACHE-PGDATA: a cluster cached while its server ran broke setup.sh on a fresh runner (run 43606632818)."""
        def cache_step(name):
            text = (ROOT / 'services' / 'runner' / 'github' / name).read_text(encoding='utf-8')
            start = text.index('      - uses: actions/cache@v4')
            return text[start:text.index('      - name: toolchain', start)]
        gate = cache_step('tower-gate.yml')
        for excluded in ('pgdata', 'postgres.log', 'pgsocket', 'pghome'):
            self.assertIn(f'            !.toolchain/{excluded}\n', gate)
        self.assertIn('key: toolchain-bin-${{ runner.os }}-', gate)  # not the key of the entries that carried a cluster
        self.assertEqual(cache_step('full-suite.yml'), gate)  # main's run saves what the gate restores: one version
        made = (ROOT / 'scripts' / 'cloud' / 'postgres.py').read_text(encoding='utf-8')
        for excluded in ('pgdata', 'postgres.log', 'pgsocket', 'pghome'):  # what postgres.py makes under .toolchain
            self.assertIn(f" / '{excluded}'", made)

    def test_the_deploy_doorbell_rings_on_a_merge_to_main_with_the_secrets_only(self):
        staged = (ROOT / 'services' / 'runner' / 'github' / 'deploy-doorbell.yml').read_text(encoding='utf-8')
        for line in ('  push:', '    branches: [main]', 'run: python3 scripts/lib/deploy.py ring',
                     '${{ secrets.TOWER_DEPLOY_DOORBELL_TOKEN }}', '  contents: read'):
            self.assertIn(line, staged)
        self.assertNotIn('pull_request', staged)  # never a pull request's code: only what main merged or the queue merges

    def test_the_merge_queue_job_prepares_and_rings_at_the_merge_in_its_own_concurrency(self):
        """QUEUE-RELOAD: the merge_group job rings prepare and landed (scripts/lib/deploy.py queue) and never shares the
        push's concurrency group, which would hold or cancel the push's ring while it waits for its merge."""
        staged = (ROOT / 'services' / 'runner' / 'github' / 'deploy-doorbell.yml').read_text(encoding='utf-8')
        for line in ('  merge_group:', "if: github.event_name == 'merge_group'", "if: github.event_name == 'push'",
                     'group: deploy-prepare-${{ github.ref }}', '      group: deploy-doorbell',
                     'run: python3 scripts/lib/deploy.py queue --sha "${{ github.sha }}" --ref "${{ github.ref }}"'):
            self.assertIn(line, staged)
        self.assertNotIn('\nconcurrency:', staged)  # no workflow-wide group

    def test_all_judges_every_script_test_of_the_checkout(self):
        """FULL-SUITE-MAIN: the safety net after a merge judges the whole suite, not the diff's tests."""
        fake = Fake()
        self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post', '--all'], run=fake), 0)
        batch = next(call for call in fake.calls if call[:2] == ['scripts/gate-check', 'tests'])[2].split(',')
        every = sorted(path.relative_to(ROOT).as_posix() for path in (ROOT / 'scripts' / 'tests').glob('*.test.sh'))
        self.assertEqual(batch, every)
        self.assertGreater(len(batch), 100)
        self.assertIn(['scripts/gate-check', 'plan', 'checks', '--base', BASE], fake.calls)  # the stages are the plan's

    def test_the_full_suite_runs_after_each_merge_to_main_and_a_red_one_opens_an_issue(self):
        staged = (ROOT / 'services' / 'runner' / 'github' / 'full-suite.yml').read_text(encoding='utf-8')
        for line in ('  push:\n    branches: [main]', '  issues: write', '--no-post --all',
                     "if: failure() && steps.suite.outcome == 'failure'", 'gh issue create'):
            self.assertIn(line, staged)
        self.assertNotIn('pull_request', staged)  # never a check a merge waits for

    def test_the_tower_gate_workflow_is_the_one_allowed_and_runs_the_verifier_on_the_queue_too(self):
        # the Torre's choice (a), 14/11/2026: a GitHub-hosted job, free on a public repository, named as the check
        import config
        self.assertEqual(config.get('gate.allowed_workflows'), ['.github/workflows/tower-gate.yml', '.github/workflows/deploy-doorbell.yml',
                          '.github/workflows/full-suite.yml'])
        staged = (ROOT / 'services' / 'runner' / 'github' / 'tower-gate.yml').read_text(encoding='utf-8')
        for line in ('  pull_request:', '  merge_group:', '    name: tower/gate',
                     'scripts/verify-commit --sha "$GITHUB_SHA" --base "$base" --repo "$GITHUB_REPOSITORY" --no-post'):
            self.assertIn(line, staged)
        for line in ('  actions: read', '          GH_TOKEN: ${{ github.token }}',
                     'verdict=(--record "$RUNNER_TEMP/verdict")',
                     'if [ "$EVENT" = merge_group ]; then base="$QUEUE_BASE"; verdict=(--reuse); fi',
                     '--no-post "${verdict[@]}"', 'uses: actions/upload-artifact@v4',
                     "if: github.event_name == 'pull_request' && steps.verify.outputs.verdict != ''",
                     'name: ${{ steps.verify.outputs.verdict }}', 'continue-on-error: true'):
            self.assertIn(line, staged)  # VERDICT-REUSE: kept by a green pull request run, reused by the queue's only
        self.assertNotIn('contents: write', staged)
        ruleset = json.loads((ROOT / '.github' / 'rulesets' / 'main.json').read_text(encoding='utf-8'))
        rules = {rule['type']: rule.get('parameters') for rule in ruleset['rules']}
        self.assertEqual(rules['required_status_checks']['required_status_checks'], [{'context': 'tower/gate'}])
        self.assertEqual(rules['merge_queue']['merge_method'], 'MERGE')
        # QUEUE-RUN: entries build side by side and merge together, and every one of them must be green to merge
        # (ALLGREEN, never HEADGREEN), so each commit main takes was judged green; an entry whose check never answers
        # leaves the queue before the gate job's own timeout.
        queue = rules['merge_queue']
        self.assertEqual(queue['grouping_strategy'], 'ALLGREEN')
        self.assertGreater(queue['max_entries_to_build'], 1)
        self.assertLessEqual(queue['max_entries_to_merge'], queue['max_entries_to_build'])
        self.assertEqual((queue['min_entries_to_merge'], queue['min_entries_to_merge_wait_minutes']), (1, 0))
        timeout = re.search(r'timeout-minutes: (\d+)', staged)
        self.assertLess(queue['check_response_timeout_minutes'], int(timeout.group(1)))


if __name__ == '__main__':
    unittest.main()
