"""The train's resync regenerates generated files (TRAIN-VERDICT-FIX B1, D-075): train_git.combine_regenerated.

The fixture's base carries a stand-in for scripts/lib/generate.py with the real interface (`--check` prints
`FAIL <file>: ...; run scripts/generate <target>` and exits 1, `<target>` rewrites its output, `--root` names the
tree) and logs every call, so a test sees which targets the train ran. `count` is the number of files under src/
(two PRs that each add one agree on the text and merge clean, stale); `listing` names the files under lst/ (two PRs
that each add one conflict textually in it).
"""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import setUpModule  # noqa: E402,F401
from test_verdict import Verdict  # noqa: E402
import train_git  # noqa: E402

LOG = 'TRAIN_FAKE_GENERATE_LOG'
GENERATOR = '''import os, sys
from pathlib import Path
args = sys.argv[1:]
root = Path(args[args.index('--root') + 1])
with open(os.environ['%s'], 'a') as log:
    log.write(args[0] + '\\n')
targets = {'count': ('gen/count.txt', lambda: f"{len(list((root / 'src').iterdir()))}\\n"),
           'listing': ('gen/list.txt', lambda: ''.join(f'{p.name}\\n' for p in sorted((root / 'lst').iterdir())))}
if args[0] == '--check':
    bad = [f'FAIL {out}: differs from its regeneration; run scripts/generate {name}'
           for name, (out, render) in targets.items()
           if not (root / out).is_file() or (root / out).read_text() != render()]
    print('\\n'.join(bad))
    sys.exit(1 if bad else 0)
out, render = targets[args[0]]
(root / out).write_text(render())
''' % LOG


class Regenerate(Verdict):
    def base_files(self):
        return {str(train_git.GENERATOR): GENERATOR, 'src/a': 'a\n', 'lst/a': 'a\n', 'gen/count.txt': '1\n',
                'gen/list.txt': 'a\n'}

    def setUp(self):
        super().setUp()
        self.log = self.dir / 'generate.log'
        os.environ[LOG] = str(self.log)

    def calls(self):
        return self.log.read_text().split() if self.log.is_file() else []

    def resynced(self, number, path):
        return self.run_git(self.origin, 'show', f'refs/heads/pr-{number}:{path}')

    def test_a_clean_merge_with_a_stale_generated_file_is_regenerated_in_the_one_merge_commit(self):
        first, _ = self.verdict_pr({'src/x': 'x\n', 'gen/count.txt': '2\n'})
        second, head = self.verdict_pr({'src/y': 'y\n', 'gen/count.txt': '2\n'})
        outcome, printed = self.drain()
        self.assertEqual((outcome, self.forge.merges), ('drained', [first, second]))
        self.assertEqual(self.resynced(second, 'gen/count.txt'), '3')
        tip_before = self.run_git(self.origin, 'rev-parse', f'{self.base_branch}^1')
        self.assertEqual(self.parents(second), [head, tip_before], 'one merge commit, never a second one')
        self.assertEqual(self.calls(), ['--check', 'count', '--check'], 'only the target the check names runs')
        self.assertIn(f'#{second} resynced', printed)
        self.assertIn('(regenerated: count)', printed)

    def test_a_merge_with_nothing_stale_runs_no_target(self):
        first, _ = self.verdict_pr({'c.txt': 'one\n'})
        second, _ = self.verdict_pr({'d.txt': 'two\n'})
        self.assertEqual(self.drain()[0], 'drained')
        self.assertEqual((self.forge.merges, self.calls()), ([first, second], ['--check']))

    def test_a_tree_without_the_generator_is_left_to_the_plain_merge(self):
        workspace = train_git.GitWorkspace(self.work)
        self.assertEqual(workspace.regenerate_in(self.dir, 'tree', []), (None, []))

    def test_a_conflict_only_in_a_generated_file_is_resolved_by_regenerating_it(self):
        """#774: CODEOWNERS is generated; two PRs that each add an entry conflict in it and nowhere else."""
        first, _ = self.verdict_pr({'lst/x': 'x\n', 'gen/list.txt': 'a\nx\n'})
        second, head = self.verdict_pr({'lst/y': 'y\n', 'gen/list.txt': 'a\ny\n'})
        outcome, printed = self.drain()
        self.assertEqual((outcome, self.forge.merges), ('drained', [first, second]))
        self.assertEqual(self.resynced(second, 'gen/list.txt'), 'a\nx\ny')
        self.assertEqual(self.events(second, 'pr.conflicted'), [], 'not handed back')
        self.assertEqual(len(self.parents(second)), len([head, 'tip']))
        self.assertIn('(regenerated: listing)', printed)

    def test_a_conflict_outside_generated_files_still_goes_back_to_the_owner(self):
        first, _ = self.verdict_pr({'lst/x': 'x\n', 'gen/list.txt': 'a\nx\n', 'c.txt': 'one\n'})
        second, _ = self.verdict_pr({'lst/y': 'y\n', 'gen/list.txt': 'a\ny\n', 'c.txt': 'other\n'})
        self.drain()
        [conflicted] = self.events(second, 'pr.conflicted')
        self.assertEqual(conflicted['payload']['files'], ['c.txt', 'gen/list.txt'])
        self.assertEqual((self.forge.merges, self.gate_api.calls), ([first], []))


if __name__ == '__main__':
    unittest.main()
