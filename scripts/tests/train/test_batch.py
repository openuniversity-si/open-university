"""The merge train v0 (plan v3 M3): batch (TX24: one file per feature; fixtures in scripts/tests/test_train.py)."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, setUpModule  # noqa: E402,F401
import engine_role  # noqa: E402
import train  # noqa: E402


class CombinedHead(Fixture):
    def test_batch_id_is_deterministic(self):
        entries = [train.Entry(1, 'a' * 40, None, (), None, 't', 'e' * 64)]
        self.assertEqual(train.batch_id(self.base, entries), train.batch_id(self.base, entries))
        self.assertEqual(len(train.batch_id(self.base, entries)), len('b-') + engine_role.setting('train.batch_id_chars'))
        self.assertNotEqual(train.batch_id(self.base, entries), train.batch_id('f' * 40, entries))

    def test_combined_tree_has_every_member_and_conflicts_leave(self):
        self.pr(1, {'c.txt': 'one\n'})
        self.pr(2, {'a.txt': 'changed by two\n'})
        self.pr(3, {'a.txt': 'changed by three\n'})
        self.pr(4, {'d.txt': 'four\n'})
        port, bid, base, members, commits = self.train.start_batch(self.train.queue())
        self.assertEqual(base, self.base)
        self.assertEqual([e.pr for e in members], [1, 2, 4])
        tree = self.run_git(self.work, 'ls-tree', '-r', '--name-only', commits[-1]).split()
        self.assertEqual(sorted(tree), ['README', 'a.txt', 'b.txt', 'c.txt', 'd.txt'])
        self.assertEqual(self.run_git(self.work, 'show', f'{commits[-1]}:a.txt'), 'changed by two')
        [conflict] = self.events(3, 'pr.conflicted')
        self.assertEqual((conflict['payload']['files'], conflict['payload']['tip_sha']), (['a.txt'], self.base))
        self.assertEqual(self.train.queue()[0].pr, 1, 'the conflicted PR left the queue; the others wait')
        self.assertNotIn(3, [e.pr for e in self.train.queue()])
        [started] = self.events(None, 'train.batch.started')
        self.assertEqual((started['payload']['batch_id'], started['payload']['prs']), (bid, [1, 2, 4]))
        kept = self.run_git(self.work, 'rev-parse', engine_role.setting('train.combined_ref_prefix') + bid)
        self.assertEqual(kept, commits[-1])

    def test_the_build_is_measured_with_the_injected_clock(self):
        self.pr(1, {'c.txt': 'one\n'})
        self.train.start_batch(self.train.queue())
        [step] = self.events(None, 'engine.step.measured')
        self.assertEqual(step['payload']['step'], engine_role.setting('train.step_prefix') + 'build')
        self.assertEqual((step['payload']['result'], step['payload']['sha']), ('ok', self.base))
        self.assertGreater(step['payload']['duration_ms'], 0)

    def test_the_same_batch_on_the_same_tip_is_the_same_commits(self):
        self.pr(1, {'c.txt': 'one\n'})
        self.pr(2, {'d.txt': 'two\n'})
        first = self.train.start_batch(self.train.queue())[4]
        self.clock.moment += timedelta(days=1)
        second = self.train.start_batch(self.train.queue())[4]
        self.assertEqual(len(first), 2)
        self.assertEqual(first, second, 'dated from the parents, never from the clock')

    def test_the_session_checkout_is_never_touched(self):
        self.pr(1, {'c.txt': 'one\n'})
        before = self.run_git(self.work, 'status', '--porcelain', '--untracked-files=all')
        head = self.run_git(self.work, 'rev-parse', 'HEAD')
        self.train.start_batch(self.train.queue())
        self.assertEqual(self.run_git(self.work, 'status', '--porcelain', '--untracked-files=all'), before)
        self.assertEqual(self.run_git(self.work, 'rev-parse', 'HEAD'), head)


class GreenBatch(Fixture):
    def tip(self):
        return self.run_git(self.origin, 'rev-parse', f'refs/heads/{self.base_branch}')

    def test_tier2_on_the_combined_head_then_merges_and_tree_proof(self):
        self.pr(1, {'c.txt': 'one\n'})
        self.pr(2, {'d.txt': 'two\n'})
        merged = self.train.run_batch(self.train.queue())
        self.assertEqual([e.pr for e in merged], [1, 2])
        self.assertEqual(self.forge.merges, [1, 2])
        self.assertEqual(len(self.gate.runs), 1, 'one tier-2 run, on the combined head')
        tip = self.tip()
        self.assertEqual(self.run_git(self.work, 'rev-parse', f'{tip}^{{tree}}'),
                         self.run_git(self.work, 'rev-parse', f'{self.gate.runs[0]}^{{tree}}'))
        [green] = self.events(None, 'train.batch.green')
        self.assertEqual(green['payload']['prs'], [1, 2])
        self.assertEqual(green['payload']['merge_shas'][-1], tip)
        [advanced] = self.events(None, 'integration.advanced')
        self.assertEqual((advanced['payload']['sha'], advanced['payload']['prs_since_release']), (tip, 2))
        [first] = self.events(1, 'pr.merged')
        self.assertEqual(first['payload']['merge_sha'], green['payload']['merge_shas'][0])
        self.assertEqual(self.train.queue(), [], 'merged PRs leave the queue')
        steps = [e['payload']['step'] for e in self.events(None, 'engine.step.measured')]
        prefix = engine_role.setting('train.step_prefix')
        self.assertEqual(sorted(steps), sorted(prefix + name for name in ('build', 'tier2', 'merge', 'batch')))

    def test_red_batch_ejects_the_culprit_and_merges_the_proven_prefix(self):
        self.pr(1, {'c.txt': 'one\n'})
        self.pr(2, {'BREAK': 'x\n'})
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1])
        self.assertEqual(self.forge.merges, [1], 'D-297 (a): the prefix the bisection proved green merges')
        [red] = self.events(None, 'train.batch.red')
        self.assertEqual((red['payload']['prs'], red['payload']['stage']), ([1, 2], 'unit tests'))
        self.assertEqual(len(self.events(2, 'pr.ejected')), 1)
        self.assertEqual(self.train.queue(), [])
        tier2 = [e for e in self.events(None, 'engine.step.measured') if e['payload']['step'].endswith('tier2')]
        self.assertEqual(tier2[0]['payload']['result'], 'fail')

    def test_an_environment_failure_halts_and_ejects_nobody(self):
        self.pr(1, {'c.txt': 'one\n'})  # a batch of one: its only member would be the culprit (#690, 2026-10-27)
        self.gate.machine = ('FAIL local postgres did not start', 'local database', 'env')  # the 27/10 tier-2 abort
        with self.assertRaisesRegex(train.TrainHalt, 'class env'):
            self.train.run_batch(self.train.queue())
        self.assertEqual((self.forge.merges, self.events(1, 'pr.ejected')), ([], []))
        self.assertEqual([e.pr for e in self.train.queue()], [1], 'the batch stays queued for the fixed machine')
        self.assertEqual(len(self.events(None, 'train.batch.red')), 1)
        [drift] = self.events(None, 'env.drift')
        self.assertEqual((drift['payload']['stage'], drift['payload']['sha'], drift['payload']['pr']),
                         ('local database', self.gate.runs[-1], None))

    def test_a_contract_failure_halts_without_env_drift_and_ejects_nobody(self):
        self.pr(1, {'c.txt': 'one\n'})
        self.gate.machine = ('FAIL db schema', 'db schema', 'contract')
        with self.assertRaisesRegex(train.TrainHalt, 'class contract'):
            self.train.run_batch(self.train.queue())
        self.assertEqual((self.events(1, 'pr.ejected'), self.events(None, 'env.drift')), ([], []))
        self.assertEqual([e.pr for e in self.train.queue()], [1])

    def test_an_environment_failure_in_a_bisection_probe_halts_and_ejects_nobody(self):
        heads = ({'c.txt': 'one\n'}, {'BREAK': 'x\n'})  # the combined head is red with class code: the train bisects
        for number, files in enumerate(heads, start=1):
            self.pr(number, files)
        queued = [e.pr for e in self.train.queue()]
        self.gate.machine, self.gate.machine_from = ('FAIL local postgres did not start', 'local database', 'env'), 1
        with self.assertRaisesRegex(train.TrainHalt, 'class env'):
            self.train.run_batch(self.train.queue())
        combined, probe = self.gate.runs  # the combined head, then the first probe halts
        self.assertEqual(self.events(None, 'pr.ejected'), [])
        self.assertEqual([e['payload']['sha'] for e in self.events(None, 'env.drift')], [probe])
        self.assertEqual([e.pr for e in self.train.queue()], queued)

    def test_with_no_halt_classes_any_red_class_ejects_again(self):
        self.train.halt_classes = []  # train.halt_classes=[]: the one-key rollback
        self.pr(1, {'c.txt': 'one\n'})
        self.gate.machine = ('FAIL local postgres did not start', 'local database', 'env')
        self.train.run_batch(self.train.queue())
        [ejected] = self.events(1, 'pr.ejected')
        self.assertEqual((ejected['payload']['stage'], self.events(None, 'env.drift')), ('local database', []))

    def test_halt_classes_default_to_env_and_contract(self):
        self.assertEqual(engine_role.setting('train.halt_classes'), ['env', 'contract'])

    def refused_batch(self):
        made = self.make({'c.txt': 'one\n'}, {'d.txt': 'two\n'}, {'e.txt': 'three\n'})
        self.forge.refuse.add(made[1].number)
        return made

    def test_a_refused_merge_leaves_and_the_rest_merges_after_a_rebuild(self):
        first, refused, third = self.refused_batch()
        merged = self.train.run_batch(self.train.queue())
        self.assertEqual([e.pr for e in merged], [first.number, third.number], 'the proven prefix, then the rest')
        self.assertEqual(self.events(refused.number, 'pr.conflicted'), [], 'a clean refusal is no conflict (D-078)')
        started = [e['payload']['prs'] for e in self.events(None, 'train.batch.started')]
        self.assertEqual(started, [[first.number, refused.number, third.number], [third.number]])
        self.assertEqual(len(self.gate.runs), len(started), 'the rest is judged on the new tip, never merged unproven')
        self.assertEqual(self.gate.envs[-1][train.BATCH_MEMBERS_ENV].split(), [third.head])
        advanced = [e['payload']['prs'] for e in self.events(None, 'integration.advanced')]
        self.assertEqual(advanced, [[first.number], [third.number]])
        [_] = self.events(None, 'train.batch.green')  # the rebuilt batch of the rest
        self.assertEqual(self.train.queue(), [])

    def test_with_no_rebuilds_left_a_refused_merge_leaves_the_rest_queued(self):
        self.train.rebuild_max = 0  # the rollback: the behaviour before GX-30, this test's original body
        self.pr(1, {'c.txt': 'one\n'})
        self.pr(2, {'d.txt': 'two\n'})
        self.pr(3, {'e.txt': 'three\n'})
        self.forge.refuse.add(2)
        merged = self.train.run_batch(self.train.queue())
        self.assertEqual([e.pr for e in merged], [1])
        self.assertEqual(self.events(2, 'pr.conflicted'), [], 'a clean refusal is no conflict (D-078)')
        self.assertEqual(self.events(None, 'train.batch.green'), [])
        self.assertEqual(self.events(None, 'integration.advanced')[0]['payload']['prs'], [1])
        self.assertEqual([e.pr for e in self.train.queue()], [3], 'the PR after the refusal waits for the next batch')

    def move_base_on_merge(self, times):
        """The integration tip moves (a commit outside the train) right before the merge step reads it, `times` times."""
        real_tip, moved, opening = self.workspace.tip, [], [False]

        def moving(branch):
            merge, opening[0] = opening[0], not opening[0]  # the build reads the tip, then the merge does
            if merge and len(moved) < times:
                self.run_git(self.seed, 'fetch', '--quiet', str(self.origin), self.base_branch)
                self.run_git(self.seed, 'checkout', '--quiet', '--detach', 'FETCH_HEAD')
                self.write({f'outside{len(moved)}.txt': 'x\n'})
                moved.append(self.commit('outside the train'))
                self.run_git(self.seed, 'push', '--quiet', str(self.origin), f'HEAD:refs/heads/{self.base_branch}')
            return real_tip(branch)

        self.workspace.tip = moving
        return moved

    def test_a_tip_that_moved_rebuilds_the_batch_on_the_new_tip(self):
        made = self.make({'c.txt': 'one\n'}, {'d.txt': 'two\n'})
        moved = self.move_base_on_merge(1)
        merged = self.train.run_batch(self.train.queue())
        self.assertEqual([e.pr for e in merged], [pr.number for pr in made])
        [old, new] = self.gate.envs  # judged on the old tip, then once on the new one
        self.assertEqual((old[train.BATCH_BASE_ENV], [new[train.BATCH_BASE_ENV]]), (self.base, moved))
        self.assertIn('outside0.txt', self.run_git(self.work, 'ls-tree', '-r', '--name-only', self.tip()).split())

    def test_a_tip_that_keeps_moving_halts_after_train_rebuild_max(self):
        self.make({'c.txt': 'one\n'})
        rebuilds = engine_role.setting('train.rebuild_max')
        self.move_base_on_merge(rebuilds + 1)
        with self.assertRaisesRegex(train.TrainHalt, 'train.rebuild_max'):
            self.train.run_batch(self.train.queue())
        self.assertEqual(self.forge.merges, [])
        self.assertEqual(len(self.gate.runs), rebuilds + 1, 'one tier-2 run per build, never more')

    def test_a_merged_tree_that_differs_from_the_tested_one_halts(self):
        self.pr(1, {'c.txt': 'one\n'})
        real_merge = self.forge.merge

        def interfering(repo, number, head_sha):
            merged = real_merge(repo, number, head_sha)
            self.run_git(self.seed, 'fetch', '--quiet', str(self.origin), self.base_branch)
            self.run_git(self.seed, 'checkout', '--quiet', '--detach', merged)
            self.write({'z.txt': 'someone else\n'})
            other = self.commit('outside the train')
            self.run_git(self.seed, 'push', '--quiet', str(self.origin), f'{other}:refs/heads/{self.base_branch}')
            return other

        self.forge.merge = interfering
        with self.assertRaises(train.TrainHalt):
            self.train.run_batch(self.train.queue())
        self.assertEqual(len(self.events(1, 'pr.merged')), 1, 'the merge happened and is recorded')
        self.assertEqual(self.events(None, 'integration.advanced'), [])


class Bisection(Fixture):
    def test_the_first_red_prefix_names_the_culprit_and_the_rest_is_retried(self):
        for number in range(1, 6):
            self.pr(number, {f'f{number}.txt': 'x\n', **({'BREAK': 'x\n'} if number == 4 else {})})
        self.assertEqual([e.pr for e in self.train.run_batch(self.train.queue())], [1, 2, 3])
        self.assertLessEqual(len(self.gate.runs) - 2, train.bisection_runs(5), 'tier 2, the bisection, the recheck')
        [ejected] = self.events(4, 'pr.ejected')
        self.assertEqual((ejected['payload']['cause'], ejected['payload']['stage']), ('culprit', 'unit tests'))
        self.assertEqual(sum(len(self.events(n, 'pr.ejected')) for n in range(1, 6)), 1)
        self.assertEqual([e.pr for e in self.train.queue()], [5], 'only the members after the culprit wait')
        merged = self.train.run_batch(self.train.queue())
        self.assertEqual([e.pr for e in merged], [5])
        bisect = [e for e in self.events(None, 'engine.step.measured') if e['payload']['step'].endswith('bisect')]
        self.assertEqual(len(bisect), len(self.gate.runs) - 3, 'two tier-2 runs and the recheck (D-297)')

    def test_the_proven_prefix_merges_on_its_green_probe_without_another_run(self):
        for number in range(1, 5):
            self.pr(number, {f'f{number}.txt': 'x\n', **({'BREAK': 'x\n'} if number == 3 else {})})
        merged = self.train.run_batch(self.train.queue())
        self.assertEqual([e.pr for e in merged], [1, 2])
        runs = list(self.gate.runs)
        self.assertEqual(len(runs), 1 + train.bisection_runs(4) + 1, 'the culprit recheck, no run for the prefix itself')
        tip = self.run_git(self.origin, 'rev-parse', f'refs/heads/{self.base_branch}')
        green_probe = [commit for commit in runs[1:]
                       if self.run_git(self.work, 'rev-parse', f'{commit}^{{tree}}')
                       == self.run_git(self.work, 'rev-parse', f'{tip}^{{tree}}')]
        self.assertEqual(len(green_probe), 1, 'the tip has the tree of the green probe (the tree proof)')
        self.assertEqual(self.events(None, 'train.batch.green'), [], 'a red batch is never announced green')
        [red] = self.events(None, 'train.batch.red')
        for number in (1, 2):
            [done] = self.events(number, 'pr.merged')
            self.assertEqual(done['payload']['batch_id'], red['payload']['batch_id'])
        [advanced] = self.events(None, 'integration.advanced')
        self.assertEqual((advanced['payload']['prs'], advanced['payload']['sha']), ([1, 2], tip))

    def test_with_the_key_off_the_proven_prefix_stays_queued(self):
        self.train.merge_proven_prefix = False
        self.pr(1, {'c.txt': 'one\n'})
        self.pr(2, {'BREAK': 'x\n'})
        self.assertEqual(self.train.run_batch(self.train.queue()), [])
        self.assertEqual((self.forge.merges, [e.pr for e in self.train.queue()]), ([], [1]))
        self.assertIs(engine_role.setting('train.merge_proven_prefix'), True, 'on by default')

    def test_a_culprit_first_merges_nothing(self):
        self.pr(1, {'BREAK': 'x\n'})
        self.pr(2, {'d.txt': 'two\n'})
        self.assertEqual(self.train.run_batch(self.train.queue()), [])
        self.assertEqual((self.forge.merges, [e.pr for e in self.train.queue()]), ([], [2]))

    def test_a_tip_that_moved_leaves_the_proven_prefix_queued(self):
        self.pr(1, {'c.txt': 'one\n'})
        self.pr(2, {'BREAK': 'x\n'})
        bisect = self.train.bisect

        def moving(*args):
            found = bisect(*args)
            other = self.commit('outside the train')
            self.run_git(self.seed, 'push', '--quiet', str(self.origin), f'{other}:refs/heads/{self.base_branch}')
            return found

        self.train.bisect = moving
        self.assertEqual(self.train.run_batch(self.train.queue()), [])
        self.assertEqual(self.forge.merges, [])
        self.assertEqual([e.pr for e in self.train.queue()], [1])

    def test_a_single_member_is_the_culprit_after_one_recheck(self):
        self.pr(1, {'BREAK': 'x\n'})
        self.train.run_batch(self.train.queue())
        self.assertEqual(len(self.gate.runs), 2, 'tier 2 and the recheck (D-297), no bisection')
        self.assertEqual(len(self.events(1, 'pr.ejected')), 1)

    def test_runs_needed_by_the_batch_size(self):
        self.assertEqual([train.bisection_runs(n) for n in (1, 2, 3, 8, 9)], [0, 1, 2, 3, 4])
        self.assertLessEqual(train.bisection_runs(engine_role.setting('train.batch_size')),
                             engine_role.setting('train.bisection_max_runs'))


if __name__ == '__main__':
    unittest.main()
