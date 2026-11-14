"""The merge train v0 (plan v3 M3): plan (TX24: one file per feature; fixtures in scripts/tests/test_train.py)."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import CHAIN, Fixture, ROOT, setUpModule  # noqa: E402,F401
import engine_role  # noqa: E402
import forge_events  # noqa: E402
import train  # noqa: E402
import train_git  # noqa: E402
import train_queue  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)


class UnionPlan(Fixture):
    """GX-30, B-20 (a): tier 2 is scripts/gate-batch --tier 2, the union plan of the judged commit's members."""

    def test_tier2_is_gate_batch_and_gets_the_members_of_each_judged_commit(self):
        self.assertEqual(engine_role.setting('train.tier2_command'), ['scripts/gate-batch', '--tier', '2'])
        heads = [pr.head for pr in self.make({'f.txt': 'x\n'}, {'g.txt': 'x\n'}, {'BREAK': 'x\n'})]
        self.train.run_batch(self.train.queue())
        combined, *probes = [env[train.BATCH_MEMBERS_ENV].split() for env in self.gate.envs]
        self.assertEqual(combined, heads, 'the combined head holds every member')
        self.assertTrue(probes and all(probe == heads[:len(probe)] for probe in probes), 'a probe gets its prefix')
        self.assertTrue(all(env[train.BATCH_BASE_ENV] == self.base for env in self.gate.envs))

    def union_repo(self):
        """A repository with this checkout's registry and unit manifests, so the union plan maps real paths."""
        root = self.dir / 'union'
        fixture_copy.folders(root, ('config/registry', 'contracts/units', 'contracts/config', 'docs/domain', 'units'))
        self.run_git(self.dir, 'init', '--quiet', '-b', 'main', str(root))
        for name in ('products/demo/src/catalog/union.ts', 'products/demo/src/ui/union.ts', 'scripts/lib/union.py'):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text('base\n')
        self.run_git(root, 'add', '-A')
        self.run_git(root, 'commit', '--quiet', '-m', 'base')
        base = self.run_git(root, 'rev-parse', 'HEAD')
        heads = {}
        for name in ('products/demo/src/catalog/union.ts', 'products/demo/src/ui/union.ts', 'scripts/lib/union.py'):
            self.run_git(root, 'checkout', '--quiet', '-B', 'pr', base)
            (root / name).write_text('changed\n')
            self.run_git(root, 'commit', '--quiet', '-am', name)
            heads[name] = self.run_git(root, 'rev-parse', 'HEAD')
        return root, base, heads

    def combined(self, root, base, shas):
        workspace, tip = train_git.GitWorkspace(root), base
        for sha in shas:
            tip, _ = workspace.combine(tip, sha, f'train: merge {sha}')
        return tip

    def test_a_batch_of_app_only_prs_runs_no_script_test_stage(self):
        import gate_batch
        import units
        self.addCleanup(units.reset)
        root, base, heads = self.union_repo()
        units.reset()
        app = [heads['products/demo/src/catalog/union.ts'], heads['products/demo/src/ui/union.ts']]
        head = self.combined(root, base, app)
        plan = gate_batch.plan(root, base, app, head)
        self.assertEqual(plan['head'], head, 'the train\'s own combined commit is the one gated')
        self.assertEqual(plan['included'], app)
        # OU-DECOUPLE F2 (D-108), F5 (D-113): a product path no engine area maps plans the always stages only, and no script test.
        import gate_areas
        self.assertEqual(plan['devPlan']['stages'], list(gate_areas.load().always))
        self.assertNotIn('script tests', plan['devPlan']['stages'])
        # D-106: an unmapped path anywhere in the union plans the always stages for all of it, so the tooling member is
        # judged alone: it selects the script tests.
        tooling = [heads['scripts/lib/union.py']]
        self.assertIn('script tests', gate_batch.plan(root, base, tooling, self.combined(root, base, tooling))['devPlan']['stages'])
        mixed = app + tooling
        self.assertNotIn('script tests', gate_batch.plan(root, base, mixed, self.combined(root, base, mixed))['devPlan']['stages'])

    def test_a_given_head_without_the_union_tree_is_refused(self):
        import gate_batch
        import units
        self.addCleanup(units.reset)
        root, base, heads = self.union_repo()
        units.reset()
        app = [heads['products/demo/src/catalog/union.ts'], heads['products/demo/src/ui/union.ts']]
        with self.assertRaisesRegex(gate_batch.BatchError, 'does not have the tree'):
            gate_batch.plan(root, base, app, self.combined(root, base, app[:1]))

    def test_gate_batch_tier_2_needs_the_members_and_one_commit(self):
        script = str(ROOT / 'scripts' / 'gate-batch')
        clean = {key: value for key, value in os.environ.items() if not key.startswith('GATE_BATCH_')}
        batch = dict(clean, GATE_BATCH_BASE='HEAD', GATE_BATCH_MEMBERS='HEAD')
        for args, env in ((['--tier', '2', 'HEAD'], clean), (['--tier', '3', 'HEAD'], batch), (['--tier', '2'], batch)):
            with self.subTest(args=args):
                done = subprocess.run([script, *args], capture_output=True, text=True, env=env, cwd=ROOT)
                self.assertNotEqual(done.returncode, 0, done.stderr)
                self.assertNotIn('combined head', done.stdout, 'a usage error never starts a gate')


class CriticalPath(Fixture):
    """GX-30 (MQ1's merge order): members of a batch go critical path first, so prefixes and bisection follow it."""

    def test_dependents_count_transitive_requirers(self):
        self.assertEqual(train_queue.dependents(CHAIN), {'core': len(['mid', 'top']), 'mid': 1, 'top': 0, 'side': 0})

    def test_critical_first_then_fifo(self):
        stamps = [forge_events.rfc3339(self.clock.now()) for _ in CHAIN]
        units = [None, 'mid', 'core', None]
        entries = [train.Entry(pr, 'a' * 40, unit, (), None, stamp, None)
                   for pr, (unit, stamp) in enumerate(zip(units, stamps), start=1)]
        ordered = train_queue.critical_first(entries, train_queue.dependents(CHAIN))
        self.assertEqual([e.unit for e in ordered], ['core', 'mid', None, None])
        self.assertEqual([e.ready_at for e in ordered[-len(['', '']):]], [stamps[0], stamps[-1]], 'then oldest first')

    def test_the_combined_head_and_the_bisection_follow_the_critical_path(self):
        self.train.weights = train_queue.dependents(CHAIN)
        first, second, third = self.make({'c.txt': 'one\n'}, ({'d.txt': 'two\n'}, 'core'), ({'BREAK': 'x\n'}, 'mid'))
        self.train.run_batch(self.train.queue())
        members = [env[train.BATCH_MEMBERS_ENV].split() for env in self.gate.envs]
        self.assertEqual(members[0], [second.head, third.head, first.head])
        self.assertEqual(members[1:], [[second.head, third.head], [second.head], [second.head, third.head]],
                         'probes are critical-path prefixes; the recheck reruns the culprit prefix (D-297)')
        [_] = self.events(third.number, 'pr.ejected')
        self.assertEqual(self.forge.merges, [second.number], 'the critical-path prefix proved green merges (D-297 (a))')
        self.assertEqual([e.pr for e in self.train.queue()], [first.number], 'the member after the culprit waits')

    def test_without_weights_the_batch_keeps_fifo(self):
        self.train.weights = {}
        heads = [pr.head for pr in self.make({'f.txt': 'x\n'}, {'g.txt': 'x\n'})]
        self.train.run_batch(self.train.queue())
        self.assertEqual(self.gate.envs[0][train.BATCH_MEMBERS_ENV].split(), heads)

    def test_the_real_unit_map_gives_weights(self):
        self.assertEqual(self.train.critical_first([]), [])
        self.assertGreater(max(self.train.weights.values()), 0, 'units of this checkout require one another')


if __name__ == '__main__':
    unittest.main()
