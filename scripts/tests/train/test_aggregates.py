"""The merge train v0 (plan v3 M3): aggregates (TX24: one file per feature; fixtures in scripts/tests/test_train.py)."""
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, ROOT, setUpModule  # noqa: E402,F401
import engine_role  # noqa: E402
import train_aggregates  # noqa: E402


class Aggregates(Fixture):
    """Plan v3 U1: what must stay in git is written by the train, never by a PR (docs/architecture/AGGREGATES.md)."""

    FILES = None  # the fixture's base tree, read from the checkout once per class (F20)

    def base_files(self):
        """What the status target reads to render (generate.targets, units.*): the registry aggregates, the unit
        contract, the manifests and the decisions table; not the per-key registry sources nor the other contracts."""
        if Aggregates.FILES is None:
            paths = [*(ROOT / 'config/registry').glob('*.json'), *(ROOT / 'contracts/units').rglob('*.json'),
                     *(ROOT / 'units').glob('*/unit.json'), ROOT / 'docs/domain/DECISIONS.md']
            Aggregates.FILES = {path.relative_to(ROOT).as_posix(): path.read_text() for path in paths}
        return dict(Aggregates.FILES)

    def keep(self):
        return self.run_git(self.work, 'rev-parse', '--verify', '--quiet', engine_role.setting('train.aggregates_ref'))

    def test_it_is_off_and_empty_by_default(self):
        self.assertFalse(engine_role.setting('train.publish_aggregates'))
        self.assertEqual(engine_role.setting('train.published_aggregates'), [])
        self.pr(1, {'c.txt': 'one\n'})
        self.train.run_batch(self.train.queue())
        with self.assertRaises(subprocess.CalledProcessError):
            self.keep()

    def test_the_snapshot_is_the_tip_tree_plus_the_rendered_aggregates_and_is_deterministic(self):
        tip = self.workspace.tip(self.base_branch)
        commit = train_aggregates.snapshot(self.workspace, tip, ['status'])
        self.assertEqual(self.run_git(self.work, 'rev-parse', f'{commit}^'), tip)
        shown = self.run_git(self.work, 'show', f'{commit}:docs/process/roadmap/STATUS-UNITS.md')
        self.assertIn('# Unit status', shown)
        self.assertEqual(self.run_git(self.work, 'show', f'{commit}:README'), 'base')
        self.assertEqual(train_aggregates.snapshot(self.workspace, tip, ['status']), commit)
        self.assertIsNone(train_aggregates.snapshot(self.workspace, tip, []))

    def test_an_unknown_target_is_refused(self):
        with self.assertRaisesRegex(Exception, 'unknown targets: nope'):
            train_aggregates.snapshot(self.workspace, self.workspace.tip(self.base_branch), ['nope'])

    def test_a_merged_batch_keeps_the_aggregates_commit_on_the_configured_ref(self):
        self.train.publish_aggregates, self.train.published_aggregates = True, ['status']
        self.pr(1, {'c.txt': 'one\n'})
        self.train.run_batch(self.train.queue())
        tip = self.workspace.tip(self.base_branch)
        kept = self.keep()
        self.assertEqual(self.run_git(self.work, 'rev-parse', f'{kept}^'), tip)
        self.assertIn('c.txt', self.run_git(self.work, 'ls-tree', '-r', '--name-only', kept))
        steps = [e['payload']['step'] for e in self.events(None, 'engine.step.measured')]
        self.assertIn(engine_role.setting('train.step_prefix') + 'aggregates', steps)


if __name__ == '__main__':
    unittest.main()
