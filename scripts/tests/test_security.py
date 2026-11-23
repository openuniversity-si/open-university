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
# the GitHub App tower-gate-attester (D-359 Salto 2): the only source of tower/gate-attested, verified in AWS
ATTESTER_APP = json.loads((Path(__file__).resolve().parent.parent.parent / 'infra' / 'aws' / 'attester' / 'app.json')
                          .read_text(encoding='utf-8'))['id']
ATTESTED_CONTEXT = 'tower/gate-attested'
BAR = {'critical': 7, 'high': 30, 'moderate': 90, 'low': 180}


class Controls(unittest.TestCase):
    def test_a_control_is_a_gap_until_something_that_exists_implements_it_with_explicit_coverage(self):
        body = {'applicable': True, 'implemented_by': ['STD-gone'], 'coverage': 'full'}
        self.assertEqual(model.control_state(body, {'STD-here'}), 'gap')
        self.assertEqual(model.control_state({'applicable': True, 'implemented_by': ['STD-here']}, {'STD-here'}), 'gap')
        self.assertEqual(model.control_state({**body, 'implemented_by': ['STD-here']}, {'STD-here'}), 'implemented')
        self.assertEqual(model.control_state({**body, 'implemented_by': ['STD-here'], 'coverage': 'partial'}, {'STD-here'}), 'partial')
        self.assertEqual(model.control_state({'applicable': False}, set()), 'not-applicable')

    def test_a_control_refuses_dormant_draft_judgment_or_unexercised_rules(self):
        def std(ident, state='blocking', kind='function'):
            return {'id': ident, 'type': 'STD', 'state': state, 'fingerprint': 'f', 'links': [],
                    'rule': {'id': ident, 'state': state, 'check': {'kind': kind, 'ref': 'scripts/lib/x.py:f'}}}

        found = {
            'STD-live': std('STD-live'),
            'STD-dormant': std('STD-dormant', state='dormant'),
            'STD-draft': std('STD-draft', state='draft'),
            'STD-judge': std('STD-judge', kind='judgment'),
            'STD-idle': std('STD-idle'),
        }
        unexercised = {'STD-idle'}
        for bad in ('STD-dormant', 'STD-draft', 'STD-judge', 'STD-idle'):
            only_bad = {'applicable': True, 'implemented_by': [bad], 'coverage': 'full'}
            self.assertEqual(model.control_state(only_bad, found, unexercised), 'gap', bad)
            mixed = {'applicable': True, 'implemented_by': ['STD-live', bad], 'coverage': 'full'}
            self.assertEqual(model.control_state(mixed, found, unexercised), 'partial', bad)
        ok = {'applicable': True, 'implemented_by': ['STD-live'], 'coverage': 'full'}
        self.assertEqual(model.control_state(ok, found, unexercised), 'implemented')
        found['CTRL-bad'] = {'id': 'CTRL-bad', 'type': 'CTRL', 'state': 'gap', 'fingerprint': 'f', 'links': [],
                             'body': {'applicable': True, 'implemented_by': ['STD-dormant']}}
        warnings = model.security_findings(found, today='2026-11-19')
        self.assertTrue(any('omits explicit coverage' in line for line in warnings), warnings)
        self.assertTrue(any('STD-dormant is inert (rule is dormant)' in line for line in warnings), warnings)

    def test_a_function_checked_control_requires_the_function_present_and_exercised(self):
        """D-352 (4): CTRL-ssdf-po.2 derives implemented only when independently_approved is present and exercised in
        live code; when absent or uncalled it stays partial and warns."""
        with tempfile.TemporaryDirectory(prefix='ctrl-fn-') as tmp:
            root = Path(tmp)
            model_py = root / 'scripts' / 'lib' / 'model.py'
            model_py.parent.mkdir(parents=True, exist_ok=True)
            std_indep = {
                'id': 'STD-model-independent-approval', 'type': 'STD', 'state': 'blocking', 'fingerprint': 'f',
                'links': [], 'rule': {'id': 'STD-model-independent-approval', 'state': 'blocking',
                                      'check': {'kind': 'function', 'ref': 'scripts/lib/model.py:independently_approved'}},
            }
            std_guard = {
                'id': 'STD-gate-production-guard', 'type': 'STD', 'state': 'blocking', 'fingerprint': 'f',
                'links': [], 'rule': {'id': 'STD-gate-production-guard', 'state': 'blocking',
                                      'check': {'kind': 'gate-stage', 'ref': 'production guard'}},
            }
            ctrl_body = {
                'applicable': True, 'coverage': 'full',
                'implemented_by': ['STD-model-independent-approval', 'STD-gate-production-guard'],
            }
            found = {
                'STD-model-independent-approval': std_indep,
                'STD-gate-production-guard': std_guard,
                'CTRL-ssdf-po.2': {'id': 'CTRL-ssdf-po.2', 'type': 'CTRL', 'state': 'gap', 'fingerprint': 'f',
                                   'links': [], 'body': ctrl_body},
            }
            model_py.write_text('def other():\n    return True\n')
            self.assertEqual(model.control_state(ctrl_body, found, root=root), 'partial')
            warnings = model.security_findings(found, root=root, today='2026-11-22')
            self.assertTrue(any('is not present' in line for line in warnings), warnings)

            model_py.write_text('def independently_approved(decision):\n    return bool(decision)\n')
            self.assertEqual(model.control_state(ctrl_body, found, root=root), 'partial')
            warnings = model.security_findings(found, root=root, today='2026-11-22')
            self.assertTrue(any('is not exercised in live code' in line for line in warnings), warnings)

            model_py.write_text(
                'def independently_approved(decision):\n    return bool(decision)\n'
                'def active_tailoring(found):\n    return [d for d in found if independently_approved(d)]\n'
            )
            self.assertEqual(model.control_state(ctrl_body, found, root=root), 'implemented')
            self.assertEqual(model.security_findings(found, root=root, today='2026-11-22'), [])

    def test_a_risk_checks_review_by_and_residual_acceptance(self):
        def risk(ident, state, **extra):
            return {'id': ident, 'type': 'RISK', 'state': state, 'fingerprint': 'f', 'links': [],
                    'body': {'id': ident, 'state': state, 'owner': 'Daniel', **extra}}

        found = {
            'RISK-ok': risk('RISK-ok', 'treated', review_by='2026-12-19', residual_accepted_by='Daniel'),
            'RISK-closed': risk('RISK-closed', 'closed', review_by='2025-01-01'),
            'RISK-no-date': risk('RISK-no-date', 'assessed'),
            'RISK-late': risk('RISK-late', 'treated', review_by='2026-11-01', residual_accepted_by='Daniel'),
            'RISK-unaccepted': risk('RISK-unaccepted', 'treated', review_by='2026-12-19'),
            'RISK-accepted-blank': risk('RISK-accepted-blank', 'accepted', review_by='2026-12-19', residual_accepted_by=''),
        }
        warnings = model.security_findings(found, today='2026-11-19')
        flagged = {line.split(':', 1)[0] for line in warnings}
        self.assertEqual(flagged, {'RISK-no-date', 'RISK-late', 'RISK-unaccepted', 'RISK-accepted-blank'})
        self.assertTrue(any('RISK-no-date: active risk has no review_by' in line for line in warnings))
        self.assertTrue(any('RISK-late: review_by 2026-11-01 has passed' in line for line in warnings))
        self.assertTrue(any('RISK-unaccepted: treated risk has no residual_accepted_by' in line for line in warnings))
        self.assertTrue(any('RISK-accepted-blank: accepted risk has no residual_accepted_by' in line for line in warnings))


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
        for item in controls:
            if item['body']['applicable']:
                self.assertIn(item['body'].get('coverage'), ('full', 'partial'), item['id'])

    def test_ctrl_ssdf_po2_is_implemented_via_d360_independent_approval_and_inert_rules_stay_flagged(self):
        found = model.objects(ROOT)
        ctrl = found['CTRL-ssdf-po.2']
        self.assertIn('STD-model-independent-approval', ctrl['body']['implemented_by'])
        self.assertNotIn('STD-train-ownership-refusals', ctrl['body']['implemented_by'])
        self.assertEqual(ctrl['state'], 'implemented')
        std = found['STD-model-independent-approval']
        self.assertEqual(std['state'], 'blocking')
        self.assertEqual(std['rule']['check'],
                         {'kind': 'function', 'ref': 'scripts/lib/model.py:independently_approved'})
        self.assertIn('STD-train-ownership-refusals', model.unexercised_rules(found, ROOT))
        warnings = model.security_findings(found, ROOT, today='2026-11-22')
        self.assertFalse(any(line.startswith('CTRL-ssdf-po.2:') for line in warnings), warnings)
        self.assertTrue(any('RISK-media-single-account: treated risk has no residual_accepted_by' in line
                            for line in warnings), warnings)

    def test_d352_recorded_prop_decided_and_open_security_risks_and_gate_threat_remain_open(self):
        found = model.objects(ROOT)
        decision = found['D-352']
        self.assertEqual((decision['state'], decision['authority']), ('accepted', 'owner'))
        self.assertTrue(model.independently_approved(decision))
        prop = found['PROP-security-supply-hardening']
        self.assertEqual(prop['state'], 'decided')
        self.assertEqual(prop['body']['decided_by'], 'D-352')
        self.assertEqual(found['TAIL-gate-fork-workflow']['state'], 'revoked')
        self.assertEqual(found['TAIL-ssdf-pw2-gate']['state'], 'revoked')
        self.assertEqual(found['THREAT-gate']['state'], 'written')
        risk = found['RISK-site-iac-outside-tree']
        self.assertEqual(risk['state'], 'assessed')
        self.assertEqual([link['target'] for link in risk['links']], ['ARC-web', 'SUP-aws'])
        for risk_id in ('RISK-media-single-account', 'RISK-personal-data-unregistered'):
            self.assertFalse(found[risk_id]['body'].get('residual_accepted_by'), risk_id)
        warnings = model.security_findings(found, ROOT, today='2026-11-22')
        for risk_id in ('RISK-media-single-account', 'RISK-personal-data-unregistered'):
            self.assertTrue(any(f'{risk_id}: treated risk has no residual_accepted_by' in line for line in warnings),
                            (risk_id, warnings))

    def test_every_required_check_is_bound_to_the_app_that_reports_it(self):
        """VULN-gate-check-source: a required check named by its context alone is satisfied by a status of that name from
        any credential that may write statuses (a session's own, through verify-commit without --no-post); bound to the
        GitHub Actions app (integration 15368), only the job's check counts."""
        for path in sorted((ROOT / '.github' / 'rulesets').glob('*.json')):
            for rule in json.loads(path.read_text()).get('rules', []):
                for item in (rule.get('parameters') or {}).get('required_status_checks', []):
                    want = ATTESTER_APP if item['context'] == ATTESTED_CONTEXT else GITHUB_ACTIONS
                    self.assertEqual(item.get('integration_id'), want, f'{path.name}: {item["context"]}')
        self.assertNotEqual(ATTESTER_APP, GITHUB_ACTIONS)  # THREAT-gate: a workflow cannot report the attested check

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
