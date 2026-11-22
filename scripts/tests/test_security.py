"""Segurança, the 17th system (PADRAO-DEV F7d, D-321): controls with their applicability, vulnerabilities under the bug
bar, threat models of the architecture and risks. Hermetic: in-memory records and temporary repositories.

Verifies: REQ-chain-verified
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

GITHUB_ACTIONS = 15368  # the GitHub Actions app, the source of every check a workflow job reports
BAR = {'critical': 7, 'high': 30, 'moderate': 90, 'low': 180}


class Controls(unittest.TestCase):
    def test_a_control_is_a_gap_until_something_that_exists_implements_it(self):
        body = {'applicable': True, 'implemented_by': ['STD-gone']}
        self.assertEqual(model.control_state(body, {'STD-here'}), 'gap')
        self.assertEqual(model.control_state({**body, 'implemented_by': ['STD-here']}, {'STD-here'}), 'implemented')
        self.assertEqual(model.control_state({**body, 'implemented_by': ['STD-here'], 'coverage': 'partial'}, {'STD-here'}), 'partial')
        self.assertEqual(model.control_state({'applicable': False}, set()), 'not-applicable')


class Vulnerabilities(unittest.TestCase):
    def test_the_bug_bar_sets_the_deadline_and_a_fix_needs_its_verification(self):
        high = {'severity': 'high', 'found': '2026-11-01'}
        self.assertEqual(model.vuln_state(high, '2026-12-01', BAR), 'open')
        self.assertEqual(model.vuln_state(high, '2026-12-02', BAR), 'overdue')
        accepted = {**high, 'accepted_until': '2026-12-31', 'reason': 'waits on upstream', 'accepted_by': 'D-9'}
        self.assertEqual(model.vuln_state(accepted, '2026-12-02', BAR), 'accepted')
        # D-336: an acceptance needs its decision, its reason and an expiry not yet passed
        for missing in ('accepted_by', 'reason'):
            self.assertEqual(model.vuln_state({key: value for key, value in accepted.items() if key != missing}, '2026-12-02', BAR), 'overdue')
        self.assertEqual(model.vuln_state(accepted, '2027-01-01', BAR), 'overdue')
        self.assertEqual(model.vuln_state({**high, 'fixed': '2026-11-05'}, '2026-12-02', BAR), 'fixed')
        self.assertEqual(model.vuln_state({**high, 'fixed': '2026-11-05', 'verified_by': 'TEST:t'}, '2026-12-02', BAR), 'verified')


    def test_only_a_fixed_or_accepted_vulnerability_is_conformant_open_inside_its_deadline_is_not(self):
        """D-336 (2): the bug bar's deadline is the alarm that a fix is late, not a licence to stay open."""
        meta = model.metamodel(ROOT)
        kind = meta['types']['VULN']
        self.assertEqual(sorted(kind['unconformant_states']), ['open', 'overdue'])
        def item(state, links=()):
            return {'id': 'VULN-x', 'type': 'VULN', 'state': state, 'fingerprint': 'f',
                    'links': [{'type': 'threatens', 'target': 'ARC-gate'}, *links]}
        for state, conformant in (('open', False), ('overdue', False), ('fixed', True), ('verified', True)):
            self.assertEqual(model.covered(meta, item(state), {}, {}), conformant, state)
        accepted = item('accepted', [{'type': 'authorized-by', 'target': 'D-336'}])
        self.assertTrue(model.covered(meta, accepted, {}, {}))
        self.assertIn('authorized-by', [name for name, link in meta['links'].items() if 'VULN' in link['from']])


class Readers(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='security-'))
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copytree(ROOT / 'contracts', self.root / 'contracts')

    def write(self, path, body):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body))

    def test_a_threat_model_models_its_element_and_is_reviewed_only_with_a_review_date(self):
        body = {'id': 'THREAT-gate', 'models': 'ARC-gate', 'assets': ['main'], 'boundaries': [],
                'threats': [{'stride': 'tampering', 'statement': 's'}]}
        self.write('config/security/threats/THREAT-gate.json', body)
        item = model.read_threats(self.root)[0]
        self.assertEqual((item['state'], item['links']), ('written', [{'type': 'models', 'target': 'ARC-gate'}]))
        self.write('config/security/threats/THREAT-gate.json', {**body, 'reviewed': '2026-11-17'})
        self.assertEqual(model.read_threats(self.root)[0]['state'], 'reviewed')

    def test_a_stamped_threat_model_turns_suspect_when_its_architecture_element_changes(self):
        arc = {'id': 'ARC-gate', 'kind': 'component', 'name': 'Gate', 'statement': 'judges PRs',
               'state': 'active', 'owner': 'capacity'}
        threat = {'id': 'THREAT-gate', 'models': 'ARC-gate', 'assets': ['main'], 'boundaries': [],
                  'threats': [{'stride': 'tampering', 'statement': 's'}], 'reviewed': '2026-11-19'}
        self.write('config/architecture/ARC-gate.json', arc)
        self.write('config/security/threats/THREAT-gate.json', threat)
        readers = (model.read_architecture, model.read_threats)
        stamped = model.stamp(self.root, found=model.objects(self.root, readers=readers))
        self.assertEqual(stamped, ['config/security/threats/THREAT-gate.json'])
        meta = model.metamodel(ROOT)
        self.assertEqual(model.check(meta, model.objects(self.root, readers=readers)), ([], []))
        self.write('config/architecture/ARC-gate.json', {**arc, 'statement': 'judges PRs and merges'})
        _, warnings = model.check(meta, model.objects(self.root, readers=readers))
        self.assertIn('THREAT-gate: models ARC-gate is suspect (the target changed)', warnings)

    def test_a_risk_keeps_the_state_its_process_wrote_and_threatens_its_assets(self):
        self.write('config/security/risks/RISK-a.json', {'id': 'RISK-a', 'statement': 's', 'state': 'accepted', 'owner': 'Daniel',
                                                          'assets': ['DATA-x'], 'likelihood': 'low', 'impact': 'high',
                                                          'residual_accepted_by': 'Daniel'})
        item = model.read_risks(self.root)[0]
        self.assertEqual((item['state'], item['links']), ('accepted', [{'type': 'threatens', 'target': 'DATA-x'}]))


class RealRepository(unittest.TestCase):
    def test_the_nineteen_ssdf_practices_each_have_a_control_with_its_reason(self):
        controls = [item for item in model.read_controls(ROOT) if 'body' in item]
        self.assertEqual(len({item['body']['control'] for item in controls}), len(['PO.1', 'PO.2', 'PO.3', 'PO.4', 'PO.5',
                         'PS.1', 'PS.2', 'PS.3', 'PW.1', 'PW.2', 'PW.4', 'PW.5', 'PW.6', 'PW.7', 'PW.8', 'PW.9', 'RV.1', 'RV.2', 'RV.3']))
        self.assertTrue(all(item['body']['reason'] for item in controls))

    def test_every_required_check_is_bound_to_the_app_that_reports_it(self):
        """VULN-gate-check-source: a required check named by its context alone is satisfied by a status of that name from
        any credential that may write statuses (a session's own, through verify-commit without --no-post); bound to the
        GitHub Actions app (integration 15368), only the job's check counts."""
        for path in sorted((ROOT / '.github' / 'rulesets').glob('*.json')):
            for rule in json.loads(path.read_text()).get('rules', []):
                for item in (rule.get('parameters') or {}).get('required_status_checks', []):
                    self.assertEqual(item.get('integration_id'), GITHUB_ACTIONS, f'{path.name}: {item["context"]}')

    def test_every_threat_model_covers_stride_on_an_active_element_and_every_mitigation_exists(self):
        """The automated design review of SSDF PW.2.1: each threat model models an active architecture element, names
        all six STRIDE categories, and each of its threats is mitigated by something that exists (an object of the
        model, or a file of the tree). It reviews the models' structure and references, not whether the threats are
        the right ones."""
        meta = model.metamodel(ROOT)
        found = model.objects(ROOT)
        threats = [item for item in model.read_threats(ROOT) if 'body' in item]
        self.assertTrue(threats)
        stride = {'spoofing', 'tampering', 'repudiation', 'information-disclosure', 'denial-of-service',
                  'elevation-of-privilege'}
        for item in threats:
            body = item['body']
            element = found.get(body['models'])
            self.assertTrue(element and element['type'] == 'ARC' and model.is_active(meta, element), body['models'])
            self.assertEqual({threat['stride'] for threat in body['threats']}, stride, item['id'])
            for threat in body['threats']:
                self.assertTrue(threat.get('mitigated_by'), f'{item["id"]}: {threat["statement"]}')
                for target in threat['mitigated_by']:
                    exists = (target in found and found[target].get('fingerprint') is not None
                              and model.is_active(meta, found[target])) or (ROOT / target).is_file()
                    self.assertTrue(exists, f'{item["id"]}: {target}')


if __name__ == '__main__':
    unittest.main()
