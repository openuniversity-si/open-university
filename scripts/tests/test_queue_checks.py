"""The checks the merge queue requires (CHK, PADRAO-DEV F7d, D-320): derived from the workflows and the rulesets.
Hermetic: temporary repositories, and one test on this tree.

Verifies: REQ-github-truth
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import model  # noqa: E402
import queue_checks  # noqa: E402

GATE = 'on: pull_request\njobs:\n  part:\n    name: gate part (${{ matrix.part }})\n  gate:\n    name: tower/gate\n'
WEB = 'on: pull_request\njobs:\n  web:\n    name: web\n    steps: []\n'
LINT = 'on: pull_request\njobs:\n  lint:\n    runs-on: ubuntu-latest\n'


def write(root, path, data):
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data if isinstance(data, str) else json.dumps(data))


def ruleset(*contexts):
    return {'rules': [{'type': 'required_status_checks',
                       'parameters': {'required_status_checks': [{'context': name} for name in contexts]}}]}


class Checks(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='queue-checks-'))
        self.addCleanup(shutil.rmtree, self.root)

    def states(self):
        return {entry['name']: entry['state'] for entry in queue_checks.checks(self.root)}

    def test_a_job_is_named_by_its_name_else_its_id_and_a_matrix_name_is_left_out(self):
        self.assertEqual(queue_checks.job_names(GATE), ['tower/gate'])
        self.assertEqual(queue_checks.job_names(LINT), ['lint'])

    def test_the_state_follows_the_files_staged_installed_required(self):
        write(self.root, 'services/runner/github/web.yml', WEB)
        self.assertEqual(self.states(), {'web': 'staged'})
        write(self.root, '.github/workflows/web.yml', WEB)
        self.assertEqual(self.states(), {'web': 'installed'})
        write(self.root, '.github/rulesets/main.json', ruleset('web'))
        self.assertEqual(self.states(), {'web': 'required'})
        self.assertEqual(queue_checks.check(self.root), [])

    def test_a_required_check_no_installed_job_runs_is_refused(self):
        write(self.root, 'services/runner/github/web.yml', WEB)
        write(self.root, '.github/rulesets/main.json', ruleset('web', 'ghost'))
        errors = queue_checks.check(self.root)
        self.assertEqual(len(errors), len(['web', 'ghost']))
        self.assertTrue(all('no installed workflow runs it' in error for error in errors))

    def test_an_installed_workflow_that_differs_from_its_staged_copy_is_refused(self):
        write(self.root, 'services/runner/github/web.yml', WEB)
        write(self.root, '.github/workflows/web.yml', WEB.replace('steps: []', 'steps: [x]'))
        self.assertIn('differs from its staged copy', queue_checks.check(self.root)[0])

    def test_the_model_reads_each_check_as_a_chk_of_its_state(self):
        write(self.root, '.github/workflows/tower-gate.yml', GATE)
        write(self.root, '.github/rulesets/main.json', ruleset('tower/gate'))
        found = {item['id']: item['state'] for item in model.read_checks(self.root)}
        self.assertEqual(found, {'CHK-tower-gate': 'required'})


class RealRepository(unittest.TestCase):
    def test_every_required_check_runs_and_every_installed_workflow_is_its_staged_copy(self):
        self.assertEqual(queue_checks.check(ROOT), [])
        states = {entry['name']: entry['state'] for entry in queue_checks.checks(ROOT)}
        self.assertEqual(states['tower/gate'], 'required')


if __name__ == '__main__':
    unittest.main()
