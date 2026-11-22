"""`scripts/lane brief`: the queue row, the delivery contract and the worktree in one brief (VAZÃO F68). Hermetic: no network."""
import contextlib
import io
import os
import re
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import lane  # noqa: E402
import generate_lane_digest  # noqa: E402

QUEUE = """# fila

| # | Unidade | Evidência | Valor | Escopo (arquivos) | PRs | Tam. |
|---|---|---|---|---|---|---|
| F58 | a suíte no log | ev 58 | v 58 | `scripts/test-suite` | 1 | S |
| F70 | o lote | ev | v | x | 1 | S |
| F64 | **[capacidade]** o lote liga | ev 64 a \\| b | v 64 | `deliver.py`. Depois de F58 (`x.py`) e de F62 (`y`). Não F70 | 1-2 | M |

## Deixadas de fora

| F99 | not in the active table | - | - | - | 1 | S |
"""

CONTRACT = """# The lane

Intro.

## The delivery contract (VAZÃO F68)
1. **Worktree:** `git worktree add -b units/<fxx> <worktree>`.
3. Trailers `Claude-Session: <session>`.

## Starting a new script
Not carried.

## Chaining (VAZÃO F63, 03/11)
Chain the next unit.
"""

DIGEST = """<!-- generated from docs/process/lane.md (Rules digest) -->
1. `scripts/lane worktree <Fxx>` in <worktree>.
3. Trailers `Claude-Session: <session>`.
"""


class LaneBriefTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.write(lane.QUEUE, QUEUE)
        self.write(lane.CONTRACT, CONTRACT)
        self.write(lane.DIGEST, DIGEST)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = lane.main(['brief', *argv, '--root', str(self.root)])
        return code, out.getvalue(), err.getvalue()

    def test_brief_carries_row_contract_and_worktree(self):
        code, out, _ = self.run_main('f64', '--worktree-root', '/w/', '--session', 'https://s/1')
        self.assertEqual(code, 0)
        self.assertIn('# Lane brief: F64, o lote liga', out)
        self.assertIn('`scripts/lane worktree F64`', out)
        self.assertIn('- **Evidência:** ev 64 a | b', out)
        self.assertIn('- **Tam.:** M', out)
        # F78: the queue row is closed by deliver and the manager's batch, never by the lane.
        self.assertIn('Close: do not edit docs/programs/vazao/fila.md; `deliver` records the closed F64 row', out)
        self.assertIn('the manager closes rows in a batch', out)
        # The digest stands in for the contract, its placeholders filled and its generated header dropped.
        self.assertIn('1. `scripts/lane worktree F64` in /w/f64.', out)
        self.assertIn('Claude-Session: https://s/1', out)
        self.assertNotIn('<!--', out)
        self.assertNotIn('Chain the next unit', out)
        self.assertNotIn('### The delivery contract', out)

    def test_missing_digest_refuses(self):
        (self.root / lane.DIGEST).unlink()
        code, _, err = self.run_main('F58')
        self.assertEqual(code, 1)
        self.assertIn('lane-digest.md: missing; run scripts/generate lane-digest', err)

    def test_live_brief_stays_under_3_kb(self):
        live = (ROOT / lane.DIGEST).read_text(encoding='utf-8')  # the fixture row with the live digest
        self.write(lane.DIGEST, live)
        out = lane.brief('F64', root=self.root)
        most = generate_lane_digest.limit(ROOT)
        self.assertLessEqual(len(out.encode('utf-8')), most + most, out)  # F78: the brief stays at 3 KB or less

    def test_open_dependencies_are_named(self):
        _, out, _ = self.run_main('F64')
        self.assertIn('**Waits on:** F58 (still in the queue)', out)  # F62 has no row; F70 is another sentence
        _, out, _ = self.run_main('F58')
        self.assertNotIn('Waits on', out)

    def test_unknown_unit_and_missing_contract_refuse(self):
        code, out, err = self.run_main('F99')
        self.assertEqual((code, out), (1, ''))
        self.assertIn('F99: no row in the active table', err)
        self.write(lane.CONTRACT, '# The lane\n\n## Chaining\nx\n')
        code, _, err = self.run_main('F58')
        self.assertEqual(code, 1)
        self.assertIn('no section `## The delivery contract`', err)

    def test_named_unit_gets_digest_and_no_row(self):
        """A unit with no F-id (gitattr) gets its worktree and the digest, and no queue row."""
        code, out, err = self.run_main('gitattr', '--worktree-root', '/w')
        self.assertEqual((code, err), (0, ''))
        self.assertIn('# Lane brief: gitattr (no queue row)', out)
        self.assertIn('Worktree: `/w/gitattr`, branch `units/gitattr`', out)
        self.assertIn('1. `scripts/lane worktree gitattr` in /w/gitattr.', out)
        self.assertIn('Session for the trailers: <session>', out)
        self.assertNotIn('## The unit', out)
        self.assertNotIn('Evidência', out)
        self.assertNotIn('<!--', out)
        code, out, err = self.run_main('bad name!')
        self.assertEqual((code, out), (1, ''))
        self.assertIn('or a name of letters, digits', err)

    def test_brief_carries_cited_decisions_and_dependencies(self):
        """F77: the D lines and the units of "Depois de", with their merge, so the lane opens no other doc."""
        self.write(lane.QUEUE, QUEUE.replace('| F70 | o lote | ev | v | x |',
                                             '| F70 | o lote | D-297 e D-297, D-404, D-012 | v | x. Depois de F64, F55 e F20 |')
                   + '\nF55 entrou em #140 com a trava.\n')
        self.write(lane.DECISIONS, '| ID | Date | Decision | Inv | Proof | State |\n|---|---|---|---|---|---|\n'
                   '| D-012 | 2026-10-01 | Old **rule** | - | - | proven |\n'
                   f'| D-297 | 03/11 | The batch {"x" * 400} | - | - | proven |\n')
        self.write(lane.RESUME, '# Retomar\n\nF20 ficou no caminho.\n')
        logs = {'F64': '', 'F55': 'b2 docs: queue closes F55\nb1 VAZÃO F55: the lock (#140)\n',
                'F20': 'c1 docs: rows (F20, F21 enter)\n'}
        calls = []

        def run(argv, **_):
            calls.append(argv)
            unit = re.search(r'F\d+', argv[-3]).group(0)
            return subprocess.CompletedProcess(argv, 0, logs[unit], '')

        out = lane.brief('F70', root=self.root, run=run)
        self.assertIn('- D-297 (03/11): The batch xxx', out)
        self.assertIn('- D-404: no row in docs/domain/DECISIONS.md', out)
        self.assertIn('- D-012 (2026-10-01): Old **rule**', out)
        self.assertEqual(out.count('D-297 (03/11)'), 1)
        self.assertLess(max(len(l) for l in out.splitlines() if l.startswith('- D-')), lane.CONTEXT_LINE + 3)
        self.assertIn('- F64: not merged (no commit on the base delivers it); open, row F64: o lote liga', out)
        self.assertIn('- F55: merged b1 VAZÃO F55: the lock (#140); docs/programs/vazao/fila.md: F55 entrou em #140', out)
        self.assertIn('- F20: not merged (no commit on the base delivers it); docs/RETOMAR.md: F20 ficou no caminho.', out)
        self.assertEqual(calls[0][3:6], ['log', '--first-parent', '-E'])
        self.assertEqual(calls[0][-1], 'origin/main')
        # A row that cites nothing gets neither section.
        out = lane.brief('F58', root=self.root, run=run)
        self.assertNotIn('## Decisions', out)
        self.assertNotIn('## The units it comes after', out)

    def test_red_on_the_base(self):
        """F83: the brief lists the tests red on the base head, from base.red then the F73 cache, each test once."""
        sha = 'a' * 40
        head = lambda argv, **_: subprocess.CompletedProcess(argv, 0, sha + '\n', '')  # noqa: E731
        signal = lambda got: {('scripts/tests/b.test.sh', 'script tests'): 'sig'} if got == sha else None  # noqa: E731
        cached = lambda got: ['scripts/tests/b.test.sh', 'scripts/tests/c.test.sh']  # noqa: E731
        reds = lane.base_reds(sha, signal=signal, cached=cached)
        self.assertEqual([r[0] for r in reds], ['scripts/tests/b.test.sh', 'scripts/tests/c.test.sh'])
        out = '\n'.join(lane.red_section(self.root, 'b', run=head, reds=lambda got: reds))
        self.assertIn('## Red on the base at aaaaaaaaaaaa', out)
        self.assertIn('- `scripts/tests/b.test.sh` (script tests): base.red, the last gate verdict on the base head', out)
        self.assertIn('- `scripts/tests/c.test.sh`: F73 cache: it failed on the base head', out)
        self.assertIn('Red on the base: none known at aaaaaaaaaaaa', ''.join(lane.red_section(self.root, 'b', run=head,
                                                                                              reds=lambda got: [])))
        nothing = lambda argv, **_: subprocess.CompletedProcess(argv, 1, '', '')  # noqa: E731
        self.assertIn('unknown (origin/b does not resolve here)', ''.join(lane.red_section(self.root, 'b', run=nothing)))

        def broken(got):
            raise OSError('no forge')
        self.assertEqual(lane.base_reds(sha, signal=broken, cached=broken), [])  # an unreadable source lists nothing
        many = lambda got: [f't{i}' for i in range(lane.CONTEXT_MAX + 2)]  # noqa: E731
        self.assertIn('- and 2 more', '\n'.join(lane.red_section(self.root, 'b', run=head, reds=lambda got:
                                                                   lane.base_reds(got, signal=broken, cached=many))))
        # The brief carries the section (the fixture root is no checkout, so its base head is unknown).
        self.assertIn('Red on the base: unknown (origin/main', lane.brief('F58', root=self.root))

    def test_delivery_subjects(self):
        self.assertTrue(lane.delivers('F62', 'deliver: docs-only (F62, D-301) (#163)'))
        self.assertTrue(lane.delivers('F58', 'VAZÃO F58: the suite (#157)'))
        self.assertTrue(lane.delivers('F60', 'deliver: the note (F60) (#155)'))
        self.assertFalse(lane.delivers('F60', 'docs: queue batch (F60, F61 enter)'))
        self.assertFalse(lane.delivers('F6', 'VAZÃO F65: x'))

    def test_repo_contract_has_the_required_section(self):
        self.assertTrue(lane.sections((ROOT / lane.CONTRACT).read_text(encoding='utf-8')))


class LaneWorktreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        (self.home / '.toolchain').mkdir(parents=True)
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_run(self, code=0):
        def run(argv, **_):
            self.calls.append(argv)
            if 'worktree' in argv and code == 0:
                Path(argv[-2]).mkdir(parents=True)
            return subprocess.CompletedProcess(argv, code, '', 'boom')
        return run

    def test_creates_worktree_and_links_toolchain(self):
        path, created = lane.worktree('f68', home=self.home, worktree_root=str(self.base / 'wt'), run=self.fake_run())
        self.assertEqual(path, self.base / 'wt' / 'f68')
        self.assertEqual((path / '.toolchain').resolve(), (self.home / '.toolchain').resolve())
        self.assertEqual(self.calls[0][3:], ['fetch', '-q', 'origin', 'main'])
        self.assertEqual(self.calls[1][3:], ['worktree', 'add', '-q', '-b', 'units/f68', str(path),
                                             'origin/main'])
        self.assertTrue(created)

    def test_defaults_read_flow_registry_and_environment_never_origin_box_paths(self):
        self.assertEqual(lane.BASE, 'main')
        with mock.patch.object(lane.config, 'get', side_effect=lambda k: {
            'flow.base_ref': 'origin/release', 'flow.worktree_root': '/reg/wt', 'flow.home_checkout': '/reg/home',
        }[k]):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(lane.default_base(), 'release')
                self.assertEqual(lane.default_worktree_root(), '/reg/wt')
                self.assertEqual(lane.default_home_checkout(), Path('/reg/home'))
            with mock.patch.dict(os.environ, {'TOWER_WORKTREE_ROOT': '/env/wt', 'TOWER_HOME_CHECKOUT': '/env/home'}, clear=True):
                self.assertEqual(lane.default_worktree_root(), '/env/wt')
                self.assertEqual(lane.default_home_checkout(), Path('/env/home'))
        with mock.patch.object(lane.config, 'get', side_effect=lambda k: {
            'flow.base_ref': 'main', 'flow.worktree_root': '', 'flow.home_checkout': '',
        }[k]):
            with mock.patch.dict(os.environ, {}, clear=True):
                self.assertEqual(lane.default_base(), 'main')
                self.assertEqual(lane.default_worktree_root(), str(lane.ROOT.parent))
                self.assertEqual(lane.default_home_checkout(), lane.ROOT)

    def test_accepts_a_name_that_is_not_a_queue_unit(self):
        path, _ = lane.worktree('Census-2', home=self.home, worktree_root=str(self.base / 'wt'), run=self.fake_run())
        self.assertEqual(path, self.base / 'wt' / 'census-2')
        self.assertIn('units/census-2', self.calls[1])
        with self.assertRaisesRegex(lane.BriefError, 'worktree name'):
            lane.worktree('../x', home=self.home, worktree_root=str(self.base / 'wt'), run=self.fake_run())

    def test_an_existing_worktree_gets_the_base_merged_and_its_link_back(self):
        path = self.base / 'wt' / 'f68'
        path.mkdir(parents=True)
        (path / '.git').write_text('gitdir: x\n')
        got, created = lane.worktree('F68', home=self.home, worktree_root=str(self.base / 'wt'), run=self.fake_run())
        self.assertEqual((got, created), (path, False))
        self.assertEqual(self.calls[1], ['git', '-C', str(path), 'merge', '-q', '--no-edit',
                                         'origin/main'])
        self.assertTrue((path / '.toolchain').is_symlink())
        self.calls.clear()

        def conflict(argv, **_):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 1 if argv[3:4] == ['merge'] else 0, '', 'conflict')
        with self.assertRaisesRegex(lane.BriefError, 'merge -q failed: conflict'):
            lane.worktree('F68', home=self.home, worktree_root=str(self.base / 'wt'), run=conflict)
        self.assertEqual(self.calls[-1], ['git', '-C', str(path), 'merge', '--abort'])  # the tree is left as it was

    def test_started_prints_the_brief_and_the_command_line(self):
        root = self.base / 'repo'
        for rel, text in ((lane.QUEUE, QUEUE), (lane.CONTRACT, CONTRACT), (lane.DIGEST, DIGEST)):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text, encoding='utf-8')
        nothing = lambda argv, **_: subprocess.CompletedProcess(argv, 1, '', '')  # noqa: E731
        out = lane.started('F64', self.base / 'wt' / 'f64', session='https://s/1', root=root, run=nothing)
        self.assertIn('# Lane brief: F64, o lote liga', out)
        self.assertIn('https://s/1', out)
        self.assertIn('Branch units/f64. ', out)
        self.assertIn('no `git fetch`/`merge FETCH_HEAD`', out)
        self.assertIn(f'Each command: `cd {self.base / "wt" / "f64"} && <command>`', out)
        self.assertIn('(no brief: F77:', lane.started('F77', self.base / 'wt' / 'f77', root=root, run=nothing))
        self.assertIn('# Lane brief: census (no queue row)',
                      lane.started('census', self.base / 'wt' / 'census', root=root, run=nothing))

    def test_refuses_existing_path_missing_toolchain_and_git_failure(self):
        (self.base / 'wt' / 'f68').mkdir(parents=True)
        with self.assertRaisesRegex(lane.BriefError, 'not a git worktree'):
            lane.worktree('F68', home=self.home, worktree_root=str(self.base / 'wt'), run=self.fake_run())
        with self.assertRaisesRegex(lane.BriefError, 'is missing'):
            lane.worktree('F69', home=self.base / 'nowhere', worktree_root=str(self.base / 'wt'), run=self.fake_run())
        with self.assertRaisesRegex(lane.BriefError, 'failed: boom'):
            lane.worktree('F70', home=self.home, worktree_root=str(self.base / 'wt'), run=self.fake_run(code=1))
        self.assertEqual(self.calls, [self.calls[0]])  # nothing ran before the refusals; git stopped at the fetch


if __name__ == '__main__':
    unittest.main()
