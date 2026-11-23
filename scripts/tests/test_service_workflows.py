"""ADR-24 as amended by ADR-41 (D-086): the gate's `no GitHub Actions workflows` stage refuses any Actions file that
gate.allowed_workflows does not name, and the staged runner workflow is the one the registry allows."""
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))

import config  # noqa: E402
import gate_workflows  # noqa: E402

ROOT = Path(__file__).resolve().parents[1].parent
STAGED = ROOT / 'services' / 'runner' / 'github'


class Stage(unittest.TestCase):
    def tree(self, *names):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name in names:
            path = Path(directory.name) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('on: push\n')
        return directory.name

    def test_no_workflow_passes(self):
        self.assertEqual(gate_workflows.main([self.tree()]), 0)

    def test_an_allowlisted_workflow_passes_and_any_other_file_fails(self):
        allowed = config.get('gate.allowed_workflows')
        self.assertEqual(gate_workflows.refused(self.tree(*allowed)), [])
        extra = '.github/workflows/ci.yml'
        self.assertEqual(gate_workflows.refused(self.tree(*allowed, extra)), [extra])
        self.assertEqual(gate_workflows.refused(self.tree('.github/actions/setup/action.yml')),
                         ['.github/actions/setup/action.yml'])

    def test_every_staged_workflow_is_the_one_its_installed_path_allows(self):
        staged = {path.name for path in STAGED.glob('*.yml')}
        proposed_dir = STAGED / 'proposed'
        proposed = {path.name for path in proposed_dir.glob('*.yml')} if proposed_dir.is_dir() else set()
        allowed = {Path(name).name for name in config.get('gate.allowed_workflows')}
        self.assertTrue(staged <= allowed, f'staged workflow not in gate.allowed_workflows: {sorted(staged - allowed)}')
        # D-087 / D-359: an allowlisted workflow is staged in services/runner/github/ (or in proposed/ ahead of Torre installation).
        self.assertTrue(allowed <= staged | proposed,
                        f'allowlisted workflow has no staged copy: {sorted(allowed - (staged | proposed))}')

    def test_d359_site_canary_is_allowlisted_with_existing_workflows_and_unlisted_stay_refused(self):
        existing = (
            '.github/workflows/tower-gate.yml',
            '.github/workflows/deploy-doorbell.yml',
            '.github/workflows/full-suite.yml',
            '.github/workflows/web.yml',
        )
        canary = '.github/workflows/site-canary.yml'
        expected = [*existing, canary]
        allowed = config.get('gate.allowed_workflows')
        self.assertEqual(allowed, expected)
        self.assertIn(canary, allowed)
        for name in existing:
            self.assertIn(name, allowed)
        self.assertEqual(gate_workflows.refused(self.tree(canary)), [])
        self.assertEqual(gate_workflows.main([self.tree(canary)]), 0)
        self.assertEqual(gate_workflows.main([self.tree(*expected)]), 0)
        salto2 = '.github/workflows/tower-gate-attest.yml'  # D-359 Salto 2: staged in proposed/, not allowlisted here
        unlisted = '.github/workflows/unlisted.yml'
        action = '.github/actions/unlisted/action.yml'
        self.assertEqual(gate_workflows.refused(self.tree(canary, salto2, unlisted, action)),
                         sorted([salto2, unlisted, action]))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = gate_workflows.main([self.tree(canary, unlisted)])
        self.assertEqual(rc, 1)
        self.assertIn(f'FAIL {unlisted}:', out.getvalue())
        self.assertNotIn(canary, out.getvalue())


if __name__ == '__main__':
    unittest.main()
