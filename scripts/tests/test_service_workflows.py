"""ADR-24 as amended by ADR-41 (D-086): the gate's `no GitHub Actions workflows` stage refuses any Actions file that
gate.allowed_workflows does not name, and the staged runner workflow is the one the registry allows."""
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
        staged = sorted(path.name for path in STAGED.glob('*.yml'))
        installed = sorted(Path(name).name for name in config.get('gate.allowed_workflows'))
        self.assertEqual(staged, installed)


if __name__ == '__main__':
    unittest.main()
