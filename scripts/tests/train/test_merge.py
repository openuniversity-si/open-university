"""The merge train v0 (plan v3 M3): merge (TX24: one file per feature; fixtures in scripts/tests/test_train.py)."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, setUpModule  # noqa: E402,F401
import config  # noqa: E402
import merge_behind  # noqa: E402
import engine_role  # noqa: E402
import train  # noqa: E402


class MergeRule(Fixture):
    """GX-30 (from GX-22): the train reads the merge rule of config/registry/merge.json."""

    def setting_with(self, name, value):
        real = engine_role.setting
        patch = mock.patch.object(engine_role, 'setting', lambda key: value if key == name else real(key))
        patch.start()
        self.addCleanup(patch.stop)

    def test_without_an_exact_head_the_train_refuses_before_any_run(self):
        self.make({'c.txt': 'one\n'})
        self.setting_with('merge.require_exact_head', False)
        with self.assertRaisesRegex(train.TrainHalt, 'merge.require_exact_head'):
            self.train.run_batch(self.train.queue())
        self.assertEqual((self.gate.runs, self.forge.merges), ([], []))

    def test_each_member_gets_the_verdict_line_of_the_merge_rule(self):
        [behind] = self.make({'c.txt': 'one\n'})
        self.run_git(self.seed, 'checkout', '--quiet', '--detach', self.base)
        self.write({'outside.txt': 'x\n'})
        self.commit('outside the train')
        self.run_git(self.seed, 'push', '--quiet', str(self.origin), f'HEAD:refs/heads/{self.base_branch}')
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            merged = self.train.run_batch(self.train.queue())
        self.assertEqual([e.pr for e in merged], [behind.number], 'a member behind the tip merges: tier 2 re-proved it')
        line = merge_behind.limit_line(len([self.base]), engine_role.setting('merge.max_behind_base'))
        self.assertIn(f'#{behind.number} {line}', printed.getvalue())

    def test_the_merge_rule_keys_are_the_shared_registry_values(self):
        # merge.require_mergeable left with merge-phase, its only reader (OU-DECOUPLE F4 (D-111)); the train meets it
        # by construction (a member that does not merge onto the combined head leaves with pr.conflicted).
        for name in ('merge.require_exact_head', 'merge.max_behind_base', 'merge.tier1_requires_base_merge'):
            with self.subTest(name=name):
                self.assertEqual(engine_role.setting(name), config.get(name))


class VerdictLink(Fixture):
    """GX-30 (from GX-12): the batch names the event_id of its tier-2 verdict on the log."""

    def test_the_batch_verdict_is_the_tier2_measurement_on_the_log(self):
        self.make({'c.txt': 'one\n'})
        self.train.run_batch(self.train.queue())
        [started] = self.events(None, 'train.batch.started')
        tier2 = [e for e in self.events(None, 'engine.step.measured') if e['payload']['step'].endswith('tier2')]
        self.assertEqual(self.train.verdicts[started['payload']['batch_id']], tier2[-1]['event_id'])
        self.assertEqual(tier2[-1]['payload']['sha'], self.gate.runs[0])


if __name__ == '__main__':
    unittest.main()
