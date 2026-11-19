"""The verifier thread's gate (scripts/verify-commit): the gate's plan run on the exact commit, its verdict published as
the commit's tower/gate status. Hermetic: a fake run answers git, gate-check and gh."""
# Verifies: REQ-github-truth
import io
import json
import re
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

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
            took = {test: self.seconds[test] for test in said if test in getattr(self, 'seconds', {})}
            Path(env['TOWER_ANSWER_FILE']).write_text(json.dumps({'tests': said, 'seconds': took}))
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
    def setUp(self):  # hermetic: a run inside tower/gate's own job must not read that job's pull request
        patched = mock.patch.dict(os.environ)
        patched.start()
        self.addCleanup(patched.stop)
        for name in ('GITHUB_EVENT_PATH', 'GITHUB_EVENT_NAME', 'GITHUB_REF', 'GITHUB_HEAD_REF'):
            os.environ.pop(name, None)

    def test_a_green_commit_is_pending_then_success_on_its_own_sha(self):
        fake = Fake()
        self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE], run=fake), 0)
        url = f'repos/openuniversity-si/open-university/statuses/{SHA}'
        self.assertEqual([(each[0], each[1], each[2]) for each in fake.statuses],
                         [(url, 'pending', 'tower/gate'), (url, 'success', 'tower/gate')])
        self.assertTrue(fake.statuses[-1][3].startswith('green: 5 check(s)'))  # 3 stages (pr metadata too, D-329) + 2 tests

    def test_only_the_plans_stages_and_tests_run_and_pr_metadata_is_not_gate_checks(self):
        fake = Fake()
        verify_commit.main(['--sha', SHA, '--base', BASE], run=fake)
        stages = [call[2] for call in fake.calls if call[:2] == ['scripts/gate-check', 'stage']]
        self.assertEqual(stages, ['structure check', 'secret scan (tree)'])
        self.assertIn(['scripts/gate-check', 'tests', 'scripts/tests/x.test.sh,scripts/tests/y.test.sh'], fake.calls)
        self.assertIn(['scripts/gate-check', 'plan', 'checks', '--base', BASE], fake.calls)

    def test_stages_only_runs_the_plans_stages_and_no_test(self):
        """PINNED-ON-GITHUB (D-335): the pinned job judges a gate change's stages with the base's gate, no test."""
        fake = Fake(red=('scripts/tests/y.test.sh',))
        with mock.patch('verify_commit.pr_metadata', return_value=(0, 'quiet')):
            self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post', '--stages-only'], run=fake), 0)
        self.assertEqual([call[2] for call in fake.calls if call[:2] == ['scripts/gate-check', 'stage']],
                         ['structure check', 'secret scan (tree)'])
        self.assertFalse([call for call in fake.calls if call[:2] in (['scripts/gate-check', 'test'], ['scripts/gate-check', 'tests'])])
        red = Fake(red=('structure check',))
        with mock.patch('verify_commit.pr_metadata', return_value=(0, 'quiet')):
            self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post', '--stages-only'], run=red), 1)
        with self.assertRaises(SystemExit):
            verify_commit.main(['--sha', SHA, '--base', BASE, '--stages-only', '--part', 'main'], run=Fake())

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

    def test_an_isolated_test_runs_by_itself_beside_a_batch_of_one_worker_fewer(self):
        """GATE-ISOLATED: the named timing-bound test is never in the batch; it runs alone at the same time, and the
        batch of the others is told one worker fewer than the runner's CPUs."""
        envs = []

        class Seen(Fake):
            def __call__(self, args, cwd=None, env=None):
                if args[:2] == ['scripts/gate-check', 'tests']:
                    envs.append(dict(env))
                return super().__call__(args, cwd, env)
        fake = Seen()
        green, red, planned, _ = verify_commit.judge(BASE, run=fake, isolated=lambda: ['scripts/tests/x.test.sh'],
                                                     cpus=lambda: 4)
        self.assertEqual((green, red), (True, []))
        self.assertIn(['scripts/gate-check', 'test', 'scripts/tests/x.test.sh'], fake.calls)
        self.assertIn(['scripts/gate-check', 'tests', 'scripts/tests/y.test.sh'], fake.calls)  # the batch is the rest
        self.assertEqual(envs[0][verify_commit.WORKERS], '3')
        self.assertEqual(planned['tests'], PLAN['tests'])  # the plan, and its count of checks, is unchanged

    def test_an_isolated_test_red_beside_the_batch_runs_once_more_alone(self):
        """GATE-ISOLATED: red by itself beside the batch and green alone after it is green, and said; red twice is red."""
        class Once(Fake):
            tries = 0

            def __call__(self, args, cwd=None, env=None):
                if args == ['scripts/gate-check', 'test', 'scripts/tests/x.test.sh']:
                    Once.tries += 1
                    if Once.tries == 1:
                        self.calls.append(list(args))
                        return 1, 'FAIL beside the batch'
                return super().__call__(args, cwd, env)
        alone = []
        green, red, _, _ = verify_commit.judge(BASE, run=Once(), alone=alone, isolated=lambda: ['scripts/tests/x.test.sh'],
                                               cpus=lambda: 4)
        self.assertEqual((green, red, alone), (True, [], ['scripts/tests/x.test.sh']))
        green, red, _, _ = verify_commit.judge(BASE, run=Fake(red=('scripts/tests/x.test.sh',)),
                                               isolated=lambda: ['scripts/tests/x.test.sh'], cpus=lambda: 4)
        self.assertEqual((green, red), (False, ['scripts/tests/x.test.sh']))

    def test_a_plan_of_isolated_tests_only_runs_no_batch(self):
        fake = Fake()
        green, _, _, _ = verify_commit.judge(BASE, run=fake, isolated=lambda: PLAN['tests'], cpus=lambda: 2)
        self.assertTrue(green)
        self.assertFalse([call for call in fake.calls if call[:2] == ['scripts/gate-check', 'tests']])

    def test_the_registry_names_the_timing_bound_tests_that_exist(self):
        named = verify_commit.isolated_tests()
        self.assertIn('scripts/tests/infra-intask-standby.test.sh', named)
        for test in named:
            self.assertTrue((ROOT / test).is_file(), test)

    def test_the_parts_split_the_plan_whole_and_the_same_way_in_every_job(self):
        """GATE-PARTS: alone holds the timing-bound tests first; every part the others, longest first to the least loaded
        worker (GATE-SPLIT-BY-WORKER, GATE-ALONE-SHARE)."""
        hints = {'scripts/tests/a.test.sh': 50, 'scripts/tests/b.test.sh': 30, 'scripts/tests/c.test.sh': 25,
                 'scripts/tests/d.test.sh': 20, 'scripts/tests/e.test.sh': 10, 'scripts/tests/f.test.sh': 8,
                 'scripts/tests/g.test.sh': 7, 'scripts/tests/h.test.sh': 4, 'scripts/tests/slow.test.sh': 6}
        tests = sorted(hints)
        parts = verify_commit.split(tests, {'scripts/tests/slow.test.sh'}, hints)
        # GATE-PER-RUNNER: each test to the part it ends earliest on, by its workers and by its runner's load over
        # RUNNER_LOAD 3 (main's STAGES_S 15 in its load and its floor; alone after its slow 6): a ends 50 on main and
        # shard1 (main first); b, c, d end 30, 25, 25 on shard1 (main 31.7, 30, 28.3); e, f, g, h end 16, 14, 13, 15.7 on
        # alone (shard1 at 85/3 = 28.3, main at 25 and more): the heavy tests no longer stack on one runner
        self.assertEqual(parts, {'main': ['scripts/tests/a.test.sh'],
                                 'shard1': ['scripts/tests/b.test.sh', 'scripts/tests/c.test.sh', 'scripts/tests/d.test.sh'],
                                 'alone': ['scripts/tests/slow.test.sh', 'scripts/tests/e.test.sh', 'scripts/tests/f.test.sh',
                                           'scripts/tests/g.test.sh', 'scripts/tests/h.test.sh']})
        unhinted = verify_commit.split(['scripts/tests/e.test.sh', 'scripts/tests/f.test.sh', 'scripts/tests/g.test.sh'],
                                       set(), {'scripts/tests/a.test.sh': 10})  # no hint weighs the median, never 0
        self.assertEqual((len(unhinted['main']), len(unhinted['shard1'])), (0, 3))  # 10 each: shard1's 4 workers hold the three
        self.assertEqual(parts, verify_commit.split(list(reversed(tests)), {'scripts/tests/slow.test.sh'}, hints))
        self.assertEqual(sorted(sum(parts.values(), [])), sorted(tests))

    def test_the_heavy_tests_spread_over_the_three_runners(self):
        """GATE-PER-RUNNER: #279's queue gate, eight deploy-slow parts of ~30 s, put four on alone and four on shard1 (four
        at once on a 4-vCPU runner: 40-55 s each); by the runner's load they go 3/3/2 and no part ends past ~40 s."""
        hints = {f'scripts/tests/deploy-slow-{name}.test.sh': 30 for name in 'abcdefgh'}
        hints.update({'scripts/tests/deploy.test.sh': 21, 'scripts/tests/deploy-smoke.test.sh': 21, 'scripts/tests/x.test.sh': 1})
        parts = verify_commit.split(sorted(hints), set(), hints)
        heavy = {part: sum('deploy-slow' in test for test in tests) for part, tests in parts.items()}
        self.assertEqual(sorted(heavy.values()), [2, 3, 3])
        for part, tests in parts.items():
            self.assertLessEqual(sum(hints[test] for test in tests) + (verify_commit.STAGES_S if part == 'main' else 0),
                                 40 * verify_commit.RUNNER_LOAD, part)

    def test_each_part_judges_its_share_and_only_main_runs_the_stages(self):
        plan = {'stages': PLAN['stages'], 'tests': ['scripts/tests/x.test.sh', 'scripts/tests/y.test.sh',
                                                    'scripts/tests/slow.test.sh']}
        hints = lambda: {'scripts/tests/x.test.sh': 10, 'scripts/tests/y.test.sh': 5}  # noqa: E731
        seen = {}
        for part in verify_commit.PARTS:
            fake = Fake(plan=plan)
            green, _, planned, _ = verify_commit.judge(BASE, run=fake, part=part, hints=hints,
                                                       isolated=lambda: ['scripts/tests/slow.test.sh'])
            self.assertTrue(green)
            seen[part] = ([call[2] for call in fake.calls if call[:2] == ['scripts/gate-check', 'stage']],
                          [call[2] for call in fake.calls if call[:2] in (['scripts/gate-check', 'tests'],
                                                                          ['scripts/gate-check', 'test'])],
                          planned['judged'], planned['tests'])
        # main starts heavier by its stages (STAGES_S 15): x 10 and y 5 both go to shard1
        self.assertEqual(seen['main'][:3], (['structure check', 'secret scan (tree)'], [], len(PLAN['stages'])))  # and pr metadata
        self.assertEqual(seen['shard1'][:3], ([], ['scripts/tests/x.test.sh,scripts/tests/y.test.sh'], 2))
        self.assertEqual(seen['alone'][:3], ([], ['scripts/tests/slow.test.sh'], 1))  # by itself, `gate-check test`
        self.assertEqual({tuple(each[3]) for each in seen.values()}, {tuple(plan['tests'])})  # the key's plan: whole

    def test_alone_runs_its_timing_bound_tests_by_themselves_and_then_its_share_on_every_worker(self):
        """GATE-ALONE-SHARE: alone's slow test first, by itself; then its share of the batch, with no worker kept."""
        others = [f'scripts/tests/{name}.test.sh' for name in 'abcdefgh']
        hints = {**dict.fromkeys(others, 10), 'scripts/tests/i.test.sh': 1, 'scripts/tests/slow.test.sh': 1}
        plan = {'stages': PLAN['stages'], 'tests': sorted(hints)}

        class Alone(Fake):
            def __call__(self, args, cwd=None, env=None):
                if args[:2] == ['scripts/gate-check', 'tests']:
                    self.workers = env.get(verify_commit.WORKERS)
                return super().__call__(args, cwd, env)
        fake = Alone(plan=plan)
        green, _, planned, _ = verify_commit.judge(BASE, run=fake, part='alone', hints=hints.copy,
                                                   isolated=lambda: ['scripts/tests/slow.test.sh'], cpus=lambda: 4)
        self.assertTrue(green)
        # GATE-PER-RUNNER: a-c end 10 on shard1; d, e, f 11 on alone (shard1's load 40/3 = 13.3); g 13.3 on shard1 against
        # alone's 14.3; h 14.3 on alone (main's floor 15); i on shard1 (13.7 against alone's 14.7); main none
        self.assertEqual([call[1:3] for call in fake.calls if call[:2] in (['scripts/gate-check', 'test'],
                                                                         ['scripts/gate-check', 'tests'])],
                         [['test', 'scripts/tests/slow.test.sh'], ['tests', ','.join(others[3:6] + others[7:])]])
        self.assertEqual((fake.workers, planned['judged']), (None, 5))  # the whole runner: no worker kept for slow
        shares = verify_commit.split(plan['tests'], {'scripts/tests/slow.test.sh'}, hints)
        self.assertEqual((shares['shard1'], shares['main']), (others[:3] + others[6:7] + ['scripts/tests/i.test.sh'], []))

    def test_the_main_part_runs_its_stages_beside_its_batch_and_says_the_pace(self):
        """GATE-PACE: the stages of the main part run while its batch runs (one worker fewer), not before it; a red stage
        is still named first, and the job log names what each one took."""
        import threading as thread
        started, stage_seen_batch = thread.Event(), []

        class Beside(Fake):
            def __call__(self, args, cwd=None, env=None):
                if args[:2] == ['scripts/gate-check', 'tests']:
                    started.set()
                    self.workers = env.get(verify_commit.WORKERS)
                if args[:2] == ['scripts/gate-check', 'stage']:
                    stage_seen_batch.append(started.wait(5))  # the batch began while the stages run
                return super().__call__(args, cwd, env)
        plan = {'stages': PLAN['stages'], 'tests': ['scripts/tests/x.test.sh', 'scripts/tests/y.test.sh']}
        fake, paces = Beside(plan=plan, red={'structure check', 'scripts/tests/y.test.sh'}), []
        hints = {'scripts/tests/x.test.sh': 40, 'scripts/tests/y.test.sh': 20}.copy  # with no stages' head start, both to main
        with mock.patch.object(verify_commit, 'STAGES_S', 0):
            green, red, _, _ = verify_commit.judge(BASE, run=fake, part='main', hints=hints, isolated=list,
                                                   cpus=lambda: 4, paces=paces)
        self.assertFalse(green)
        self.assertEqual(red, ['structure check', 'scripts/tests/y.test.sh'])
        self.assertEqual((stage_seen_batch, fake.workers), ([True, True], '3'))
        self.assertEqual(sorted(name for name, _ in paces), ['pr metadata', 'secret scan (tree)', 'structure check',
                                                             'the batch of tests'])
        unparted = Fake(plan=plan)
        verify_commit.judge(BASE, run=unparted, isolated=list, cpus=lambda: 4)  # local and full-suite: in order
        kinds = [call[1] for call in unparted.calls if call[0] == 'scripts/gate-check' and call[1] in ('stage', 'tests')]
        self.assertEqual(kinds, ['stage', 'stage', 'tests'])

    def test_the_pace_of_the_batch_names_its_three_slowest_tests(self):
        fake, paces = Fake(plan={'stages': [], 'tests': [f'scripts/tests/t{n}.test.sh' for n in range(5)]}), []
        fake.seconds = {f'scripts/tests/t{n}.test.sh': float(n * 10) for n in range(5)}
        verify_commit.judge(BASE, run=fake, isolated=list, paces=paces)
        [(name, _)] = paces
        self.assertEqual(name, 'the batch of tests (t4 40.0 s, t3 30.0 s, t2 20.0 s)')

    def test_the_job_log_names_every_test_of_five_seconds_or_more_with_its_wall(self):
        # GATE-WALLS: not only the three slowest; a test under WALL_MIN_S is left out
        import contextlib
        import io
        fake = Fake(plan={'stages': [], 'tests': [f'scripts/tests/t{n}.test.sh' for n in range(6)]})
        fake.seconds = {f'scripts/tests/t{n}.test.sh': float(n * 2.5) for n in range(6)}  # 0, 2.5, 5, 7.5, 10, 12.5
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post'], run=fake), 0)
        [line] = [each for each in out.getvalue().splitlines() if each.startswith('verify-commit: walls: ')]
        self.assertEqual(line, 'verify-commit: walls: t5 12.5 s, t4 10.0 s, t3 7.5 s, t2 5.0 s')

    def test_the_job_log_names_the_pace_of_a_part(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(verify_commit, 'STAGES_S', 0):  # main gets a test
            self.assertEqual(verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post', '--part', 'main'], run=Fake()), 0)
        line = next(each for each in out.getvalue().splitlines() if each.startswith('verify-commit: pace: '))
        for name in ('structure check', 'secret scan (tree)', 'the batch of tests'):
            self.assertIn(name, line)

    def test_a_part_keeps_its_own_verdict_and_the_queue_reuses_only_one_run_that_kept_all_three(self):
        """GATE-PARTS: <name>-<part> per part; a run that kept two of the three is a miss, and so are parts of two runs."""
        import tempfile as temp
        fake = Fake()
        with temp.TemporaryDirectory() as tmp:
            name = verify_commit.record(Path(tmp), BASE, {**PLAN, 'part': 'shard1'}, SHA, fake, environ=IMAGE)
            whole = verify_commit.record(Path(tmp), BASE, PLAN, SHA, fake, environ=IMAGE)
        self.assertEqual(name, whole + '-shard1')
        key = whole[len(verify_commit.VERDICT):]

        def listing(kept):
            def answer(args, cwd=None, env=None):
                if args[:2] == ['gh', 'api']:
                    asked = args[2].split('name=')[1].split('&')[0]
                    return 0, json.dumps({'artifacts': [made(asked) | {'workflow_run': {
                        **made(asked)['workflow_run'], 'id': run_id}} for part, run_id in kept if asked.endswith(part)]})
                return fake(args, cwd, env)
            return answer
        both = [('-main', 7), ('-shard1', 7), ('-alone', 7)]
        self.assertEqual(verify_commit.recorded('o/r', key, [HEAD_OF_PR], listing(both), verify_commit.PARTS), 7)
        self.assertIsNone(verify_commit.recorded('o/r', key, [HEAD_OF_PR], listing(both[:2]), verify_commit.PARTS))
        mixed = [('-main', 7), ('-shard1', 8), ('-alone', 7)]
        self.assertIsNone(verify_commit.recorded('o/r', key, [HEAD_OF_PR], listing(mixed), verify_commit.PARTS))

    def test_a_queue_part_reuses_its_own_shares_verdict_whatever_the_other_parts_kept(self):
        """GATE-PARTS-REUSE: a part's key holds its job's runner image, and one run's three jobs may land on different
        images (#142, 16/11: alone's key was not main's), so a queue part asks for its own record only."""
        asked = []

        def run(args, cwd=None, env=None):
            if args[:2] == ['gh', 'api'] and 'artifacts' in args[2]:
                asked.append(args[2].split('name=')[1].split('&')[0])
                return 0, json.dumps({'artifacts': [made(asked[-1])]})
            return Fake()(args, cwd, env)
        with mock.patch.object(verify_commit, 'judge', return_value=(True, [], {**PLAN, 'judged': 1}, 1.0)) as judged:
            verify_commit.main(['--sha', SHA, '--base', BASE, '--no-post', '--part', 'shard1', '--reuse'], run=run,
                               environ=IMAGE)
        reuse = judged.call_args.kwargs['reuse']
        self.assertEqual(reuse(PLAN), 77)  # the run that kept this part's verdict
        self.assertEqual(len(asked), 1)
        self.assertTrue(asked[0].endswith('-shard1'))

    def test_the_staged_gate_is_three_parts_and_a_tower_gate_job_green_only_when_every_part_is(self):
        staged = (ROOT / 'services' / 'runner' / 'github' / 'tower-gate.yml').read_text(encoding='utf-8')
        for line in ('    name: gate part (${{ matrix.part }})', '      fail-fast: false', '        part: [main, shard1, alone]',
                     '    name: tower/gate', '    needs: [part, pinned]', '    if: always()', '          PARTS: ${{ needs.part.result }}',
                     '          test "$PARTS" = success', '          PINNED: ${{ needs.pinned.result }}',
                     '          test "$PINNED" = success'):
            self.assertIn(line, staged)
        self.assertEqual(staged.count('    name: tower/gate'), 1)  # only the job the merge queue requires has the name
        self.assertEqual(list(verify_commit.PARTS), ['main', 'shard1', 'alone'])

    def test_the_staged_gate_judges_a_gate_change_with_the_bases_gate_too(self):
        """PINNED-ON-GITHUB (D-070, D-335, VULN-gate-judged-by-own-head): the base's gate_pin.py, run from a worktree of
        the base, puts the base's gate files back in the head's checkout, and the plan's stages run there."""
        staged = (ROOT / 'services' / 'runner' / 'github' / 'tower-gate.yml').read_text(encoding='utf-8')
        for line in ('  pinned:', 'git worktree add --detach "$RUNNER_TEMP/base" "$base"',
                     'python3 "$RUNNER_TEMP/base/scripts/lib/gate_pin.py" overlay --root "$GITHUB_WORKSPACE" --base "$base"',
                     'scripts/verify-commit --sha "$GITHUB_SHA" --base "$BASE" --repo "$GITHUB_REPOSITORY" --no-post --stages-only'):
            self.assertIn(line, staged)
        pinned = staged.split('  pinned:', 1)[1].split('\n  gate:', 1)[0]
        self.assertLess(pinned.index('gate_pin.py" overlay'), pinned.index('--stages-only'))  # the overlay first
        self.assertLess(pinned.index('gate_pin.py" overlay'), pinned.index('bash scripts/cloud/setup.sh'))
        # D-335: no cache the pull request's scope could have saved under the base's key reaches the base's gate.
        self.assertNotIn('actions/cache', pinned)

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
        self.assertEqual(record['stages'], ['pr metadata', 'secret scan (tree)', 'structure check'])  # D-329: it runs
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
            start = text.index('      - uses: actions/cache@')
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
        apart = [call[2] for call in fake.calls if call[:2] == ['scripts/gate-check', 'test']]  # GATE-ISOLATED
        self.assertEqual(sorted(batch + apart), every)
        self.assertEqual(apart, [test for test in every if test in verify_commit.isolated_tests()])
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
                          '.github/workflows/full-suite.yml', '.github/workflows/web.yml'])  # web.yml: the site's checks (D-319)
        staged = (ROOT / 'services' / 'runner' / 'github' / 'tower-gate.yml').read_text(encoding='utf-8')
        for line in ('  pull_request:', '  merge_group:', '    name: tower/gate',
                     'scripts/verify-commit --sha "$GITHUB_SHA" --base "$base" --repo "$GITHUB_REPOSITORY" --no-post'):
            self.assertIn(line, staged)
        for line in ('  actions: read', '          GH_TOKEN: ${{ github.token }}',
                     'verdict=(--record "$RUNNER_TEMP/verdict")',
                     'if [ "$EVENT" = merge_group ]; then base="$QUEUE_BASE"; verdict=(--reuse); fi',
                     '--no-post --part "$PART" "${verdict[@]}"', 'uses: actions/upload-artifact@',
                     "if: github.event_name == 'pull_request' && steps.verify.outputs.verdict != ''",
                     'name: ${{ steps.verify.outputs.verdict }}', 'continue-on-error: true'):
            self.assertIn(line, staged)  # VERDICT-REUSE: kept by a green pull request run, reused by the queue's only
        self.assertNotIn('contents: write', staged)
        ruleset = json.loads((ROOT / '.github' / 'rulesets' / 'main.json').read_text(encoding='utf-8'))
        rules = {rule['type']: rule.get('parameters') for rule in ruleset['rules']}
        # web: the site's checks (D-319); the gate pinned to the base (D-335); each bound to the GitHub Actions app, so no
        # other status writer satisfies it (VULN-gate-check-source)
        self.assertEqual(rules['required_status_checks']['required_status_checks'],
                         [{'context': context, 'integration_id': 15368} for context in
                          ('tower/gate', 'web', 'gate pinned to the base')])
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


REPO = 'openuniversity-si/open-university'
ONE, TWO, MERGE_BASE = '1' * len(SHA), '2' * len(SHA), '3' * len(SHA)
NUMBER = len(REPO)  # the fake gh's pull request: any number (no new literal, the census LT1)
BODY = '## Commit plan\n- [ ] 1. The rule.\n- [ ] 2. Its use.\n'


class GitHub(Fake):
    """A fake gh for PR-METADATA-GITHUB (D-329): pull request NUMBER on GitHub, two commits pushed one by one."""

    def __init__(self, body=BODY, messages=('The rule\n\nPlan: 1', 'Its use\n\nPlan: 2'), files=(['src/a.py'], ['src/b.py']),
                 comments=(), forced=(), broken=None, merge_base=MERGE_BASE, **fake):
        super().__init__(**fake)
        self.body, self.messages, self.files, self.comments, self.forced = body, messages, files, list(comments), list(forced)
        self.merge_base = merge_base
        self.broken, self.read = broken, []

    def lines(self, items):
        return 0, ''.join(json.dumps(item) + '\n' for item in items)

    def __call__(self, args, cwd=None, env=None):
        said = ' '.join(args)
        if not said.startswith('gh api ') or '-X' in args or 'actions/artifacts' in said:
            return super().__call__(args, cwd, env)
        path = next(arg for arg in args if arg.startswith('repos/'))
        self.read.append(path)
        if self.broken and self.broken in path:
            return 1, 'HTTP 403: Resource not accessible by integration'
        pull = f'repos/{REPO}/pulls/{NUMBER}'
        if path == pull:
            return 0, json.dumps({'number': NUMBER, 'body': self.body, 'draft': False, 'created_at': '2026-11-18T20:00:00Z',
                                  'head': {'ref': 'claude/d-329', 'sha': TWO}, 'base': {'ref': 'main', 'sha': BASE}})
        if path.startswith(f'{pull}/commits'):
            return self.lines([{'sha': ONE, 'message': self.messages[0], 'parents': [MERGE_BASE]},
                               {'sha': TWO, 'message': self.messages[1], 'parents': [ONE]}])
        if path.startswith(f'{pull}/files'):
            return self.lines(sorted({name for each in self.files for name in each}))
        if path.startswith(f'repos/{REPO}/activity?ref=refs%2Fheads%2Fclaude%2Fd-329&activity_type=push'):
            return self.lines([{'before': '0' * len(SHA), 'after': ONE, 'timestamp': '2026-11-18T20:01:00Z'},
                               {'before': ONE, 'after': TWO, 'timestamp': '2026-11-18T20:02:00Z'}])
        if path.startswith(f'repos/{REPO}/activity?ref=refs%2Fheads%2Fclaude%2Fd-329&activity_type=force_push'):
            return self.lines(self.forced)
        if path.startswith(f'repos/{REPO}/issues/{NUMBER}/comments'):
            return self.lines([{'body': each, 'created_at': '2026-11-18T20:01:30Z'} for each in self.comments])
        if path == f'repos/{REPO}/compare/main...{TWO}':
            return 0, json.dumps({'behind_by': 0, 'merge_base_commit': {'sha': self.merge_base}})
        if path.startswith(f'repos/{REPO}/commits/'):
            return self.lines(self.files[[ONE, TWO].index(path.rsplit('/', 1)[1])])
        raise AssertionError(path)


QUEUE = {'GITHUB_EVENT_NAME': 'merge_group', 'GITHUB_REF': f'refs/heads/gh-readonly-queue/main/pr-{NUMBER}-{BASE}'}


class ThePullRequestMetadata(unittest.TestCase):
    """D-329 (PR-METADATA-GITHUB): tower/gate runs `pr metadata` on the GitHub pull request, read with gh, not Origin."""

    def setUp(self):
        import gate_discipline
        lanes = mock.patch.object(gate_discipline, 'lane_errors', return_value=[])  # no lane: the fake shas are not here
        regime = mock.patch.object(gate_discipline, 'regime', None)  # no exception regime lifts a lock here (D-260)
        for patched in (lanes, regime):
            patched.start()
            self.addCleanup(patched.stop)

    def judged(self, environ=QUEUE, argv=(), **fake):
        fake = GitHub(**fake)
        code = verify_commit.main(['--sha', SHA, '--base', BASE, '--repo', REPO, *argv], run=fake, environ=environ)
        return code, fake

    def test_the_stage_runs_on_the_merge_queue_commit_reading_the_pull_request_its_branch_names(self):
        code, fake = self.judged()
        self.assertEqual(code, 0, fake.statuses)
        self.assertIn(f'repos/{REPO}/pulls/{NUMBER}', fake.read)
        self.assertTrue(fake.statuses[-1][-1].startswith('green: 5 check(s)'))  # pr metadata is one of them
        self.assertNotIn(['scripts/gate-check', 'stage', 'pr metadata', '--base', BASE], fake.calls)  # in process

    def test_the_pull_request_is_the_events_else_the_queue_branchs_else_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / 'event.json'
            event.write_text(json.dumps({'pull_request': {'number': NUMBER, 'head': {'sha': TWO}}}))
            self.assertEqual(verify_commit.pull_request({'GITHUB_EVENT_NAME': 'pull_request',
                                                         'GITHUB_EVENT_PATH': str(event)}), (NUMBER, TWO, True))
            event.write_text(json.dumps({'merge_group': {'head_ref': f'refs/heads/gh-readonly-queue/main/pr-{len(BASE)}-{BASE}'}}))
            self.assertEqual(verify_commit.pull_request({'GITHUB_EVENT_NAME': 'merge_group',
                                                         'GITHUB_EVENT_PATH': str(event)}), (len(BASE), None, True))
        self.assertEqual(verify_commit.pull_request(QUEUE), (NUMBER, None, True))
        self.assertEqual(verify_commit.pull_request({'GITHUB_REF': f'refs/pull/{NUMBER}/merge'}), (NUMBER, None, False))
        self.assertEqual(verify_commit.pull_request({'GITHUB_EVENT_NAME': 'merge_group'}), (None, None, True))
        self.assertEqual(verify_commit.pull_request({'GITHUB_REF': 'refs/heads/main'}), (None, None, False))
        self.assertEqual(verify_commit.pull_request({}, given=NUMBER), (NUMBER, None, False))

    def test_the_machine_decided_rules_are_red_on_the_github_pull_request(self):
        for fake, rule in (({'body': 'No plan here.'}, 'plan'),
                           ({'messages': ('The rule\n\nPlan: 1', 'fixup! The rule\n\nPlan: 2')}, 'fixup'),
                           ({'files': (['src/a.py'], ['scripts/gate-dev'])}, 'gate'),
                           ({'comments': ['The merge is held for Daniel.']}, 'decision-wait'),
                           ({'body': BODY + 'Item 2 waits on Daniel.\n'}, 'decision-wait'),
                           ({'forced': [{'before': ONE, 'after': TWO, 'timestamp': '2026-11-18T20:03:00Z'}]}, 'force-push')):
            out = io.StringIO()
            with mock.patch('sys.stderr', out), mock.patch('sys.stdout', io.StringIO()):
                code, ran = self.judged(**fake)
            self.assertEqual(code, 1, (rule, ran.statuses))
            self.assertEqual(ran.statuses[-1][-1], 'red: pr metadata', rule)
            self.assertRegex(out.getvalue(), rf'FAIL {rule}: ', rule)

    def test_the_review_check_refuses_an_approved_trailer_no_review_of_the_head_approves(self):
        """THREAT-planning spoofing (D-335): structure.review_errors runs in `pr metadata`. An `approved` Fit-Review with
        no APPROVED review comment of the gated head, or with a review that requests changes, is red; a `not reviewed`
        or `not structural` body with no review comment is green, so no review step is asked for (D-055)."""
        approved = f'Fit-Review: approved by A Torre (independent reviewer session, head {TWO}) 2026-11-19'
        review = 'Independent fit review (reviewer session, head {}): {}'
        for fake, green in (({'body': f'{BODY}\nFit-Review: not structural\n'}, True),
                            ({'body': f'{BODY}\n{approved}\n'}, False),
                            ({'body': f'{BODY}\n{approved}\n', 'comments': [review.format(TWO, 'APPROVED')]}, True),
                            ({'body': f'{BODY}\n{approved}\n', 'comments': [review.format(ONE, 'APPROVED')]}, False),
                            ({'body': BODY, 'comments': [review.format(TWO, 'CHANGES_REQUESTED')]}, False)):
            out = io.StringIO()
            with mock.patch('sys.stderr', out), mock.patch('sys.stdout', io.StringIO()):
                code, ran = self.judged(**fake)
            self.assertEqual(code, 0 if green else 1, (fake, ran.statuses))
            if not green:
                self.assertEqual(ran.statuses[-1][-1], 'red: pr metadata', fake)
                self.assertRegex(out.getvalue(), r'FAIL (no "Independent fit review|the latest independent fit review)', fake)

    def test_a_pull_request_github_cannot_answer_or_an_event_naming_none_is_red(self):
        for environ, fake in ((QUEUE, {'broken': '/activity'}), ({'GITHUB_EVENT_NAME': 'merge_group'}, {})):
            out = io.StringIO()
            with mock.patch('sys.stderr', out), mock.patch('sys.stdout', io.StringIO()):
                code, ran = self.judged(environ=environ, **fake)
            self.assertEqual((code, ran.statuses[-1][-1]), (1, 'red: pr metadata'))
            self.assertRegex(out.getvalue(), r'not readable on GitHub|names no pull request')

    def test_a_local_run_naming_no_pull_request_judges_nothing_and_pr_names_one(self):
        code, ran = self.judged(environ={})
        self.assertEqual(code, 0)
        self.assertEqual(ran.read, [])
        code, ran = self.judged(environ={}, argv=('--pr', str(NUMBER)))
        self.assertEqual(code, 0)
        self.assertIn(f'repos/{REPO}/pulls/{NUMBER}', ran.read)


class ThePullRequestMetadataAsRecorded(unittest.TestCase):
    """THREAT-planning (D-335, D-340): `pr metadata` under the regime the registry records (none since D-340), with real
    unit manifests: a ready PR with an item no commit ticks and a PR across two lanes' units are red, a clean one green.
    The lane rule is the train's ownership rule with the lane lane_of() gives it (LANE-OWN), run from the diff and the
    manifests at the merge base, without the train."""

    LANES = {'engine': ('lane-a', 'scripts/engine/**'), 'admin': ('lane-b', 'apps/admin/**')}

    def setUp(self):
        import regime
        pinned = list(regime._JUDGE)
        regime.pin(None)  # the registry's view, not the hermetic hook's
        self.addCleanup(lambda: regime.pin(pinned[0] if pinned else None))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for unit, (lane, glob) in self.LANES.items():
            path = self.root / 'units' / unit / 'unit.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'id': unit, 'owner': lane, 'paths': [glob]}))
        git = ['git', '-C', tmp.name, '-c', 'user.email=t@example.com', '-c', 'user.name=T']
        for args in (['init', '-q'], ['add', '-A'], ['commit', '-q', '-m', 'base']):
            subprocess.run([*git, *args], check=True, capture_output=True)
        self.base = subprocess.run([*git, 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True).stdout.strip()

    def judged(self, **fake):
        out = io.StringIO()
        with mock.patch('sys.stderr', out):
            code, said = verify_commit.pr_metadata(REPO, NUMBER, run=GitHub(merge_base=self.base, **fake), root=self.root)
        return code, said + out.getvalue()

    def test_the_recorded_regime_lifts_no_lock_of_the_stage(self):
        import gate_discipline
        self.assertFalse(gate_discipline.lifted('structure'))
        self.assertFalse(gate_discipline.lifted('commit-plan'))

    def test_a_clean_pull_request_is_green(self):
        code, said = self.judged(files=(['scripts/engine/a.py'], ['scripts/engine/b.py']))
        self.assertEqual(code, 0, said)
        self.assertNotIn('lifted', said)

    def test_an_item_no_commit_ticks_is_refused(self):
        code, said = self.judged(messages=('The rule\n\nPlan: 1', 'Its use'))
        self.assertEqual(code, 1, said)
        self.assertRegex(said, r'FAIL plan: item\(s\) 2 not ticked')

    def test_a_change_across_two_lanes_units_is_refused(self):
        code, said = self.judged(files=(['scripts/engine/a.py'], ['apps/admin/r.ts']))
        self.assertEqual(code, 1, said)
        self.assertRegex(said, r'FAIL lane undecidable: .*admin \(lane-b\), engine \(lane-a\)')


class GateMode(unittest.TestCase):
    def test_the_verifier_names_its_checkout_so_its_change_store_is_never_read(self):
        """D-335: what verify-commit runs inherits $OU_CONFIG_REGISTRY_ONLY=<this checkout>; config then ignores
        the checkout's .tower/config (scripts/tests/test_config_api.py GateMode proves the read)."""
        import config
        environ = verify_commit.gate_mode({})
        self.assertEqual(environ, {config.REGISTRY_ONLY_ENV: str(ROOT)})
        with mock.patch.dict(os.environ, environ):
            self.assertTrue(config.registry_only())


if __name__ == '__main__':
    unittest.main()
