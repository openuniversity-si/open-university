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

    def test_a_check_bound_to_an_external_app_needs_no_workflow_and_refuses_one(self):
        """D-359 Salto 2 (THREAT-gate): tower/gate-attested comes from the App tower-gate-attester, not from a job."""
        jobs_app = len('github-actions')
        other_app = jobs_app + 1
        bound = {'rules': [{'type': 'required_status_checks', 'parameters': {'required_status_checks': [
            {'context': 'tower/gate', 'integration_id': jobs_app},
            {'context': 'tower/gate-attested', 'integration_id': other_app}]}}]}
        write(self.root, '.github/rulesets/main.json', bound)
        write(self.root, queue_checks.EXTERNAL_APPS[0], {'id': other_app})
        write(self.root, '.github/workflows/tower-gate.yml', GATE)
        write(self.root, 'services/runner/github/tower-gate.yml', GATE)
        self.assertEqual(queue_checks.check(self.root), [])
        attested = next(e for e in queue_checks.checks(self.root) if e['name'] == 'tower/gate-attested')
        self.assertEqual((attested['state'], attested['external']), ('required', True))
        spoof = GATE + '  fake:\n    name: tower/gate-attested\n'
        write(self.root, '.github/workflows/tower-gate.yml', spoof)
        write(self.root, 'services/runner/github/tower-gate.yml', spoof)
        self.assertTrue(any('no workflow may report it' in e for e in queue_checks.check(self.root)))

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

    def test_only_a_job_of_a_workflow_that_runs_on_pull_request_is_a_check(self):
        doorbell = 'on:\n  push:\n    branches: [main]\n  merge_group:\n    types: [checks_requested]\njobs:\n  ring:\n    name: deploy-prepare\n'
        suite = 'on:\n  push:\n    branches: [main]\n  workflow_dispatch:\njobs:\n  suite:\n    name: full-suite\n'
        gate = 'on:\n  pull_request:\n    branches: [main]\n  merge_group:\njobs:\n  gate:\n    name: tower/gate\n'
        self.assertEqual(queue_checks.triggers(doorbell), {'push', 'merge_group'})
        self.assertEqual(queue_checks.triggers(WEB), {'pull_request'})
        for name, text in (('deploy-doorbell.yml', doorbell), ('full-suite.yml', suite), ('tower-gate.yml', gate)):
            write(self.root, f'.github/workflows/{name}', text)
            write(self.root, f'services/runner/github/{name}', text)
        self.assertEqual(self.states(), {'tower/gate': 'installed'})
        write(self.root, '.github/rulesets/main.json', ruleset('tower/gate', 'deploy-prepare'))
        self.assertEqual(queue_checks.check(self.root),
                         ['check deploy-prepare: required by .github/rulesets/main.json but no installed workflow runs it'])

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
