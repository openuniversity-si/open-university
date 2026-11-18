"""scripts/model (PADRAO-DEV F1a): the metamodel as data, the objects of the systems that exist, the check, the chain,
the inventory and the conformance. Hermetic: no network; the error cases run on a temporary checkout."""
# Verifies: REQ-chain-verified
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import model  # noqa: E402


def write(root, path, data):
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data if isinstance(data, str) else json.dumps(data))


class TinyModel(unittest.TestCase):
    """A metamodel of four types, two systems and three links, and objects built in memory."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='model-test-'))
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copytree(ROOT / 'contracts' / 'model', self.root / 'contracts' / 'model')
        for name, system in (('reqs', 'Requirements'), ('build', 'Build')):
            write(self.root, f'config/model/systems/{name}.json', {'id': name, 'name': system, 'processes': ['p'],
                                                                    'owner': 'administration', 'measure': 'm',
                                                                    'description': 'd'})
        types = {
            'REQ': {'system': 'reqs', 'states': ['draft', 'approved', 'obsolete'], 'inactive_states': ['obsolete'],
                    'covered_by': [{'type': 'ARC', 'link': 'satisfies'}, {'type': 'TEST', 'link': 'verifies'}]},
            'ARC': {'system': 'build', 'states': ['active'], 'covered_by': [{'type': 'UNIT', 'link': 'realizes'}]},
            'UNIT': {'system': 'build', 'states': ['active'], 'must_link': ['realizes']},
            'TEST': {'system': 'build', 'states': ['active'], 'must_link': ['verifies']},
            'VAL': {'system': 'reqs', 'states': ['defined']},
            'CHG': {'system': 'build', 'states': ['merged'], 'must_link': ['implements']},
        }
        for id, item in types.items():
            write(self.root, f'config/model/types/{id}.json', {'id': id, 'name': id.lower(), **item, 'description': 'd'})
        for name, start, end in (('satisfies', ['ARC'], ['REQ']), ('realizes', ['UNIT'], ['ARC']),
                                 ('verifies', ['TEST'], ['REQ']), ('validates', ['VAL'], ['REQ']),
                                 ('derives-from', ['REQ'], ['REQ']), ('implements', ['CHG'], ['REQ'])):
            write(self.root, f'config/model/links/{name}.json', {'name': name, 'from': start, 'to': end,
                                                                 'description': 'd'})
        write(self.root, 'config/model/conformance.json', json.loads((ROOT / 'config/model/conformance.json').read_text()))

    def meta(self):
        return model.metamodel(self.root)

    def objects(self, *items):
        return {item['id']: {'state': 'active', 'source': 'x', 'fingerprint': 'f', 'links': [], **item} for item in items}

    def test_the_tiny_metamodel_is_valid(self):
        self.assertEqual(self.meta()['errors'], [])

    def test_a_link_to_a_type_that_does_not_exist_and_a_system_with_no_type_are_errors(self):
        write(self.root, 'config/model/links/realizes.json', {'name': 'realizes', 'from': ['GHOST'], 'to': ['ARC'],
                                                              'description': 'd'})
        write(self.root, 'config/model/systems/empty.json', {'id': 'empty', 'name': 'E', 'processes': ['p'],
                                                             'owner': 'o', 'measure': 'm', 'description': 'd'})
        errors = self.meta()['errors']
        self.assertTrue(any('link realizes: types GHOST' in error for error in errors), errors)
        self.assertTrue(any('systems empty manage no object type' in error for error in errors), errors)

    def test_a_file_whose_id_is_not_its_name_and_a_file_the_contract_refuses_are_errors(self):
        write(self.root, 'config/model/types/VAL.json', {'id': 'VALIDATION', 'name': 'v', 'system': 'reqs',
                                                         'states': [], 'description': 'd'})
        errors = self.meta()['errors']
        self.assertTrue(any('must equal the file name VAL' in error for error in errors), errors)
        self.assertTrue(any('config/model/types/VAL.json: $.states' in error for error in errors), errors)

    def test_an_unknown_type_a_wrong_state_and_a_link_the_metamodel_forbids_are_errors(self):
        found = self.objects({'id': 'X-1', 'type': 'GHOST'},
                             {'id': 'REQ-1', 'type': 'REQ', 'state': 'done'},
                             {'id': 'UNIT:a', 'type': 'UNIT', 'links': [{'type': 'verifies', 'target': 'REQ-1'}]})
        errors, warnings = model.check(self.meta(), found)
        self.assertEqual(warnings, [])
        self.assertTrue(any(error.startswith('X-1: type GHOST') for error in errors), errors)
        self.assertTrue(any(error.startswith('REQ-1: state done') for error in errors), errors)
        self.assertTrue(any(error.startswith('UNIT:a: a UNIT cannot hold a verifies link') for error in errors), errors)

    def test_a_link_to_an_object_that_does_not_exist_or_changed_is_a_warning(self):
        found = self.objects({'id': 'REQ-1', 'type': 'REQ', 'state': 'approved'},
                             {'id': 'TEST:a', 'type': 'TEST', 'links': [{'type': 'verifies', 'target': 'REQ-9'},
                                                                        {'type': 'verifies', 'target': 'REQ-1',
                                                                         'fingerprint': 'old'}]})
        errors, warnings = model.check(self.meta(), found)
        self.assertEqual(errors, [])
        self.assertTrue(any('REQ-9, which does not exist' in warning for warning in warnings), warnings)
        self.assertTrue(any('REQ-1 is suspect' in warning for warning in warnings), warnings)

    def test_the_chain_is_verified_only_with_an_element_a_unit_a_change_a_test_and_a_validation(self):
        chain = [{'id': 'REQ-1', 'type': 'REQ', 'state': 'approved'},
                 {'id': 'CHG-1', 'type': 'CHG', 'state': 'merged', 'links': [{'type': 'implements', 'target': 'REQ-1'}]},
                 {'id': 'ARC-1', 'type': 'ARC', 'links': [{'type': 'satisfies', 'target': 'REQ-1'}]},
                 {'id': 'UNIT:a', 'type': 'UNIT', 'links': [{'type': 'realizes', 'target': 'ARC-1'}]},
                 {'id': 'TEST:a', 'type': 'TEST', 'links': [{'type': 'verifies', 'target': 'REQ-1'}]},
                 {'id': 'VAL-1', 'type': 'VAL', 'state': 'met', 'links': [{'type': 'validates', 'target': 'REQ-1'}]}]
        for missing in range(len(chain)):
            if missing == 0:
                continue
            found = self.objects(*[item for index, item in enumerate(chain) if index != missing])
            self.assertFalse(model.chain_verified(found['REQ-1'], model.incoming(found), found), chain[missing]['id'])
        found = self.objects(*chain)
        self.assertTrue(model.chain_verified(found['REQ-1'], model.incoming(found), found))
        result = model.measure(self.root, self.meta(), found)
        self.assertEqual((result['chain']['verified'], result['chain']['share']), (1, 1))

    def test_an_inactive_requirement_leaves_the_chain_and_a_system_rates_its_conformant_share(self):
        found = self.objects({'id': 'REQ-1', 'type': 'REQ', 'state': 'obsolete'},
                             {'id': 'UNIT:a', 'type': 'UNIT'},
                             {'id': 'TEST:a', 'type': 'TEST', 'links': [{'type': 'verifies', 'target': 'REQ-1'}]})
        result = model.measure(self.root, self.meta(), found)
        self.assertEqual(result['chain']['active_requirements'], 0)
        build = result['systems']['build']
        self.assertEqual((build['objects'], build['conformant']), (len(['UNIT', 'TEST']), 1))
        self.assertEqual(build['level'], 'P')
        self.assertEqual(result['systems']['reqs']['level'], 'N')

    def test_an_object_no_rule_judges_is_known_not_judged_and_never_conformant(self):
        write(self.root, 'config/model/systems/know.json', {'id': 'know', 'name': 'Knowledge', 'processes': ['p'],
                                                            'owner': 'administration', 'measure': 'm', 'description': 'd'})
        write(self.root, 'config/model/types/K.json', {'id': 'K', 'name': 'known item', 'system': 'know',
                                                       'states': ['active'], 'description': 'd'})
        meta = self.meta()
        self.assertEqual(meta['errors'], [])
        self.assertFalse(model.judged(meta, 'K'))
        self.assertTrue(model.judged(meta, 'UNIT'))
        self.assertTrue(model.judged({'types': {'STD': {}}}, 'STD'), 'the findings of the standard judge its rules')
        many = len('abc')
        found = self.objects(*[{'id': f'K-{n}', 'type': 'K'} for n in range(many)],
                             {'id': 'VAL-1', 'type': 'VAL', 'state': 'defined'})
        result = model.measure(self.root, meta, found)
        known = result['systems']['know']
        self.assertEqual((known['objects'], known['conformant'], known['not_judged'], known['level']), (many, 0, many, 'N'))
        self.assertIn(f'know: N (0 of {many} conformant; {many} not judged: no rule of K)', model.summary(result))
        self.assertEqual(result['systems']['reqs']['not_judged'], 1)

    def test_a_requirement_verified_by_validation_is_covered_by_its_own_met_validation_as_the_chain_says(self):
        found = self.objects({'id': 'REQ-1', 'type': 'REQ', 'state': 'approved', 'body': {'verification': 'validation'}},
                             {'id': 'ARC-1', 'type': 'ARC', 'links': [{'type': 'satisfies', 'target': 'REQ-1'}]},
                             {'id': 'VAL-1', 'type': 'VAL', 'state': 'defined',
                              'links': [{'type': 'validates', 'target': 'REQ-1'}]})
        meta, into = self.meta(), model.incoming(found)
        self.assertFalse(model.covered(meta, found['REQ-1'], into, found))
        found['VAL-1']['state'] = 'met'
        self.assertTrue(model.covered(meta, found['REQ-1'], into, found))
        self.assertEqual(model.covered(meta, found['REQ-1'], into, found), model.requirement_tested(found['REQ-1'], into, found))
        del found['REQ-1']['body']['verification']
        self.assertFalse(model.covered(meta, found['REQ-1'], into, found), 'a test is still needed without it')

    def test_a_test_counted_without_a_verdict_source_says_what_it_counts(self):
        found = self.objects({'id': 'REQ-1', 'type': 'REQ', 'state': 'approved'},
                             {'id': 'TEST:a', 'type': 'TEST', 'links': [{'type': 'verifies', 'target': 'REQ-1'}]})
        result = model.measure(self.root, self.meta(), found)
        self.assertEqual(result['systems']['build']['verdicts_unread'],
                         {'TEST': {'verdict': 'VERD', 'means': 'linked to what they verify'}})
        line = next(line for line in model.summary(result).splitlines() if line.startswith('  build:'))
        self.assertIn('1 of 1 linked to what they verify; pass state not read: no VERD source', line)
        self.assertNotIn('conformant', line)

    def test_the_inventory_counts_distinct_ids_by_file_name_content_file_and_registry_key(self):
        write(self.root, 'docs/D-1.md', '| D-2 | x |\n| D-2 | again |')
        write(self.root, 'docs/D-3.md', '')
        write(self.root, 'docs/caps/A.md', '')
        write(self.root, 'reg.json', {'properties': {'a.one': {}, 'a.two': {}}})
        write(self.root, 'config/model/inventory/all.json', {
            'id': 'all', 'name': 'all', 'becomes': ['REQ'], 'description': 'd', 'parts': [
                {'kind': 'filename', 'glob': 'docs/D-*.md', 'pattern': '^(D-[0-9]+)\\.md$'},
                {'kind': 'content', 'glob': 'docs/D-1.md', 'pattern': '^\\| (D-[0-9]+) '},
                {'kind': 'files', 'glob': 'docs/caps/*.md'},
                {'kind': 'registry', 'glob': 'reg.json'}]})
        found = self.objects({'id': 'REQ-1', 'type': 'REQ', 'state': 'draft', 'source_id': 'D-3'},
                             {'id': 'D-1', 'type': 'REQ', 'state': 'draft'},
                             {'id': 'a.one', 'type': 'ARC'})
        counted = model.inventory(self.meta(), found, self.root)['all']
        self.assertEqual((counted['ids'], counted['imported']), (len(['D-1', 'D-2', 'D-3', 'A', 'a.one', 'a.two']), 2))
        write(self.root, 'config/model/inventory/all.json', {
            'id': 'all', 'name': 'all', 'becomes': ['REQ'], 'description': 'd',
            'parts': [{'kind': 'registry', 'glob': 'reg.json', 'pattern': 'two$'}]})
        self.assertEqual(model.inventory(self.meta(), found, self.root)['all']['ids'], 1)


class Rules(unittest.TestCase):
    """The rules of the standard (STD) on a temporary checkout with the real metamodel."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='model-rules-'))
        self.addCleanup(shutil.rmtree, self.root)
        for folder in ('contracts/model', 'config/model'):
            shutil.copytree(ROOT / folder, self.root / folder)
        write(self.root, 'scripts/lib/guard.py', 'def plan_errors(body):\n    return []\n')
        write(self.root, 'scripts/tests/covers/guard.json', {'script': 'scripts/tests/guard.test.sh',
                                                             'covers': ['scripts/lib/*.py']})
        write(self.root, 'scripts/tests/covers/other.json', {'script': 'scripts/tests/other.test.sh',
                                                             'covers': ['docs/**']})
        self.rule('STD-plan', state='blocking', basis=['D-1'], check={'kind': 'function', 'ref': 'scripts/lib/guard.py:plan_errors'})

    def rule(self, id, **fields):
        body = {'id': id, 'statement': 's', 'state': 'draft', 'owner': 'administration', 'applies_to': ['CHG'],
                'check': {'kind': 'judgment', 'ref': 'docs/x.md'}, **fields}
        write(self.root, f'config/standard/rules/{id}.json', body)

    def found(self):
        items = model.read_rules(self.root)
        merged = {}
        for item in items:
            merged.setdefault(item['id'], {**item, 'links': []})['links'] += item['links']
        return merged

    def test_a_rule_is_an_object_justified_by_its_decisions_and_verified_by_the_tests_whose_covers_name_its_check(self):
        found = self.found()
        self.assertEqual(found['STD-plan']['links'], [{'type': 'justified-by', 'target': 'D-1'}])
        self.assertEqual(found['TEST:scripts/tests/guard.test.sh']['links'], [{'type': 'verifies', 'target': 'STD-plan'}])
        self.assertNotIn('TEST:scripts/tests/other.test.sh', found)

    def test_a_rule_file_the_contract_refuses_is_an_error(self):
        self.rule('STD-bad', state='enforced')
        found = self.found()
        errors, _ = model.check(model.metamodel(self.root), found)
        self.assertTrue(any(error.startswith('STD:STD-bad: $.state') for error in errors), errors)

    def test_refusals_and_stages_without_a_rule_missing_checks_no_basis_and_no_deadline_are_warnings(self):
        self.rule('STD-gone', check={'kind': 'function', 'ref': 'scripts/lib/guard.py:gone_errors'}, basis=['D-1'])
        self.rule('STD-soon', state='warning', basis=['D-1'], check={'kind': 'gate-stage', 'ref': 'shellcheck'})
        warnings = model.rule_findings(self.found(), self.root,
                                       stops=['scripts/lib/guard.py:plan_errors', 'scripts/lib/guard.py:push_errors'],
                                       stages=['shellcheck', 'schema compat'])
        self.assertIn('scripts/lib/guard.py:push_errors: a refusal with no rule of the standard', warnings)
        self.assertNotIn('scripts/lib/guard.py:plan_errors: a refusal with no rule of the standard', warnings)
        self.assertIn('gate stage schema compat: a stage with no rule of the standard', warnings)
        self.assertIn('STD-gone: function scripts/lib/guard.py:gone_errors does not exist', warnings)
        self.assertIn('STD-soon: in warning with no deadline', warnings)
        self.assertFalse(any(line.startswith('STD-plan') for line in warnings), warnings)

    def test_a_judgment_rule_needs_its_document_and_a_rule_without_basis_is_reported(self):
        self.rule('STD-judge')
        warnings = model.rule_findings(self.found(), self.root, stops=[], stages=[])
        self.assertIn('STD-judge: its check docs/x.md does not exist', warnings)
        self.assertIn('STD-judge: no decision justifies it (basis)', warnings)

    def test_the_seed_has_a_rule_per_refusal_stage_principle_and_the_method_and_never_rewrites_one(self):
        write(self.root, 'scripts/lib/guard.py', 'def push_errors(push):\n    """One commit per push (D-25, D-7). More."""\n')
        write(self.root, model.PRINCIPLES, '### 1. One source of truth\n\n### 2. Contracts first\n\n## Shared contract\n### 3. Not a principle\n')
        write(self.root, model.METHOD, '# method')
        seeds = model.seeds(self.root, stops=['scripts/lib/guard.py:push_errors'], stages=['schema compat'])
        self.assertEqual(sorted(seeds), ['STD-d069-1-one-source-of-truth', 'STD-d069-2-contracts-first',
                                         'STD-gate-schema-compat', 'STD-guard-push-errors', 'STD-metodo'])
        push = seeds['STD-guard-push-errors']
        self.assertEqual((push['statement'], push['basis'], push['state']), ('One commit per push (D-25, D-7).', ['D-7', 'D-25'], 'blocking'))
        self.assertEqual(seeds['STD-d069-2-contracts-first']['check'], {'kind': 'judgment', 'ref': f'{model.PRINCIPLES}#2'})
        written = model.seed_rules(self.root, stops=['scripts/lib/guard.py:push_errors'], stages=['schema compat'])
        self.assertEqual(len(written), len(seeds))
        self.assertEqual(model.seed_rules(self.root, stops=['scripts/lib/guard.py:push_errors'], stages=['schema compat']), [])
        errors, _ = model.check(model.metamodel(self.root), self.found())
        self.assertEqual(errors, [])

    def test_the_standard_measures_its_executable_tested_justified_and_overdue_rules(self):
        self.rule('STD-judge', basis=['D-1'])
        self.rule('STD-late', state='warning', deadline='2026-01-01', check={'kind': 'gate-stage', 'ref': 'shellcheck'})
        self.rule('STD-old', state='replaced', replaced_by='STD-plan')
        found = self.found()
        found['TEST:scripts/tests/guard.test.sh']['fingerprint'] = 'f'
        counted = model.standard_measure(found, today='2026-11-16')
        self.assertEqual(counted, {'rules': len(['plan', 'judge', 'late']), 'executable': len(['plan', 'late']),
                                   'tested': 1, 'justified': len(['plan', 'judge']), 'overdue': 1})


class StandardManagement(unittest.TestCase):
    """Proposals, versions and exemptions of the standard on a temporary checkout with the real metamodel."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='model-management-'))
        self.addCleanup(shutil.rmtree, self.root)
        for folder in ('contracts/model', 'config/model'):
            shutil.copytree(ROOT / folder, self.root / folder)
        import config
        current = config.get('coordinator.padrao_version')
        self.current = current
        older, newer = f'v{int(current[1:]) - 1}', f'v{int(current[1:]) + 1}'
        for name in (older, current, newer):
            write(self.root, f'docs/padrao/{name}/padrao.json', {'rules': [{'id': 'save-often', 'file': 'save-often.md'}]})
        self.older, self.newer = older, newer
        write(self.root, 'docs/process/rule-challenges/RC-001.md', '# RC-001\n- Status: changed\n- D: D-9\n')
        write(self.root, 'docs/process/rule-challenges/RC-002.md', '# RC-002\n- Status: open\n- D: none\n')
        write(self.root, 'config/standard/rules/STD-padrao-save-often.json', {
            'id': 'STD-padrao-save-often', 'statement': 's', 'state': 'draft', 'owner': 'administration',
            'applies_to': ['WORK'], 'check': {'kind': 'judgment', 'ref': 'docs/x.md'}})

    def found(self):
        merged = {}
        for reader in (model.read_rules, model.read_proposals, model.read_versions, model.read_tailoring):
            for item in reader(self.root):
                merged.setdefault(item['id'], {**item, 'links': []})['links'] += item['links']
        return merged

    def test_a_rule_challenge_is_a_proposal_whose_status_and_decision_are_read_where_it_is(self):
        found = self.found()
        self.assertEqual((found['PROP-RC-001']['state'], found['PROP-RC-001']['links']),
                         ('applied', [{'type': 'decided-by', 'target': 'D-9'}]))
        self.assertEqual((found['PROP-RC-002']['state'], found['PROP-RC-002']['links']), ('open', []))

    def test_the_version_the_coordinator_names_is_effective_the_older_superseded_the_newer_a_draft(self):
        found = self.found()
        states = {id: item['state'] for id, item in found.items() if item['type'] == 'VER'}
        self.assertEqual(states, {f'VER-{self.older}': 'superseded', f'VER-{self.current}': 'effective',
                                  f'VER-{self.newer}': 'draft'})
        self.assertEqual(found[f'VER-{self.current}']['links'], [{'type': 'contains', 'target': 'STD-padrao-save-often'}])
        self.assertEqual(found[f'VER-{self.older}']['links'], [])

    def test_a_version_file_contains_the_whole_catalog_and_an_exemption_links_its_rule_and_decision(self):
        write(self.root, 'config/standard/versions/VER-v99.json', {'id': 'VER-v99', 'state': 'draft', 'statement': 's',
                                                                  'contains': 'catalog', 'supersedes': f'VER-{self.current}'})
        write(self.root, 'config/standard/tailoring/TAIL-x.json', {
            'id': 'TAIL-x', 'exempts': 'STD-padrao-save-often', 'scope': 'units/engine-x/**', 'reason': 'r',
            'authorized_by': 'D-9', 'valid_until': '2026-01-01', 'state': 'active'})
        found = self.found()
        self.assertEqual(found['VER-v99']['links'], [{'type': 'contains', 'target': 'STD-padrao-save-often'},
                                                     {'type': 'supersedes', 'target': f'VER-{self.current}'}])
        self.assertEqual(found['TAIL-x']['links'], [{'type': 'exempts', 'target': 'STD-padrao-save-often'},
                                                    {'type': 'authorized-by', 'target': 'D-9'}])
        _, warnings = model.management_findings(found, '2026-11-16')
        self.assertIn('TAIL-x: active past its validity 2026-01-01', warnings)

    def test_open_proposals_with_no_deadline_or_past_it_and_two_effective_versions_are_reported(self):
        write(self.root, 'config/standard/proposals/PROP-late.json', {
            'id': 'PROP-late', 'statement': 's', 'state': 'open', 'owner': 'administration',
            'changes': ['STD-padrao-save-often'], 'deadline': '2026-01-01'})
        write(self.root, 'config/standard/proposals/PROP-done.json', {
            'id': 'PROP-done', 'statement': 's', 'state': 'applied', 'owner': 'administration',
            'changes': ['STD-padrao-save-often']})
        found = self.found()
        errors, warnings = model.management_findings(found, '2026-11-16')
        self.assertEqual(errors, [])
        self.assertIn('PROP-RC-002: an open proposal with no deadline', warnings)
        self.assertIn('PROP-late: past its deadline 2026-01-01', warnings)
        self.assertIn('PROP-done: applied with no decision', warnings)
        counted = model.management_measure(found, '2026-11-16')
        self.assertEqual((counted['proposals'], counted['open'], counted['undated'], counted['overdue'], counted['closed']),
                         (len(['RC-001', 'RC-002', 'late', 'done']), len(['RC-002', 'late']), 1, 1, len(['RC-001', 'done'])))
        found['VER-v99'] = {**found[f'VER-{self.current}'], 'id': 'VER-v99'}
        errors, _ = model.management_findings(found, '2026-11-16')
        self.assertEqual(len(errors), 1)


class Requirements(unittest.TestCase):
    """Intentions, needs and requirements on a temporary checkout with the real metamodel."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='model-requirements-'))
        self.addCleanup(shutil.rmtree, self.root)
        for folder in ('contracts/model', 'config/model'):
            shutil.copytree(ROOT / folder, self.root / folder)
        for path in (self.root / 'config/model/inventory').glob('*.json'):
            path.unlink()
        write(self.root, 'config/intent/INT-ladder.json', {'id': 'INT-ladder', 'statement': '1,000 PRs a day',
                                                            'state': 'active', 'owner': 'Daniel', 'source': 'docs/SEMENTE.md#3'})
        write(self.root, 'config/intent/NEED-throughput.json', {'id': 'NEED-throughput', 'statement': 'many PRs',
                                                                'state': 'proposed', 'owner': 'Daniel',
                                                                'refines': ['INT-ladder'], 'source': 'x'})
        write(self.root, 'docs/CONTRACT.md', '- **INV-A1** Every course has one owner.\n- **G-B2** A batch is whole.\n')
        write(self.root, 'config/model/inventory/contract.json', {
            'id': 'contract', 'name': 'c', 'becomes': ['REQ'], 'description': 'd',
            'parts': [{'kind': 'content', 'glob': 'docs/CONTRACT.md', 'pattern': '\\b((?:INV|G)-[A-Z0-9-]+)'}]})
        write(self.root, 'config/registry/slo.json', {'properties': {'slo.gate_p95_s': {'description': 'The gate p95.'},
                                                                     'slo.producer': {'description': 'A name.'}}})
        write(self.root, 'config/model/inventory/slo.json', {
            'id': 'slo', 'name': 's', 'becomes': ['REQ'], 'description': 'd',
            'parts': [{'kind': 'registry', 'glob': 'config/registry/slo.json', 'pattern': '_p95_s$'}]})

    def found(self, *readers):
        merged = {}
        for reader in readers or (model.read_intent, model.read_requirements):
            for item in reader(self.root):
                merged.setdefault(item['id'], {**item, 'links': []})['links'] += item['links']
        return merged

    def test_intentions_and_needs_are_objects_and_a_need_refines_its_intention(self):
        found = self.found()
        self.assertEqual((found['INT-ladder']['type'], found['NEED-throughput']['type']), ('INT', 'NEED'))
        self.assertEqual(found['NEED-throughput']['links'], [{'type': 'refines', 'target': 'INT-ladder'}])

    def test_an_import_reads_a_sources_requirements_where_they_are_with_the_batch_state(self):
        write(self.root, 'config/requirements/imports/contract.json', {'id': 'contract', 'type': 'product',
                                                                       'state': 'obsolete', 'owner': 'Daniel',
                                                                       'retired_by': 'D-111'})
        write(self.root, 'config/requirements/imports/slo.json', {'id': 'slo', 'type': 'quality', 'state': 'approved',
                                                                  'owner': 'administration',
                                                                  'derives_from': {'*': 'NEED-throughput'},
                                                                  'overrides': {'slo.gate_p95_s': {'state': 'superseded',
                                                                                                    'retired_by': 'D-314'}}})
        found = self.found()
        req = found['REQ-contract-inv-a1']
        self.assertEqual((req['state'], req['source_id'], req['source']), ('obsolete', 'INV-A1', 'docs/CONTRACT.md'))
        self.assertIn('Every course has one owner', req['body']['statement'])
        self.assertIn('REQ-contract-g-b2', found)
        self.assertEqual(found['REQ-slo-slo-gate-p95-s']['links'], [{'type': 'derives-from', 'target': 'NEED-throughput'}])
        self.assertEqual((found['REQ-slo-slo-gate-p95-s']['state'], found['REQ-slo-slo-gate-p95-s']['body']['retired_by']),
                         ('superseded', 'D-314'))
        self.assertNotIn('REQ-slo-slo-producer', found)
        self.assertEqual(model.requirement_findings(found), [])

    def test_a_requirement_file_links_its_need_and_decision_and_gaps_are_warnings(self):
        write(self.root, 'config/requirements/REQ-gate-60s.json', {
            'id': 'REQ-gate-60s', 'type': 'constraint', 'statement': 'The gate answers in 60 s.', 'state': 'approved',
            'owner': 'Daniel', 'derives_from': ['NEED-throughput'], 'basis': ['D-314'], 'source': 'x'})
        write(self.root, 'config/requirements/REQ-alone.json', {
            'id': 'REQ-alone', 'type': 'quality', 'statement': 's', 'state': 'approved', 'owner': 'o', 'source': 'x'})
        write(self.root, 'config/requirements/REQ-old.json', {
            'id': 'REQ-old', 'type': 'quality', 'statement': 's', 'state': 'obsolete', 'owner': 'o', 'source': 'x'})
        write(self.root, 'config/requirements/imports/nowhere.json', {'id': 'nowhere', 'type': 'quality',
                                                                      'state': 'approved', 'owner': 'o'})
        found = self.found()
        self.assertEqual(found['REQ-gate-60s']['links'], [{'type': 'derives-from', 'target': 'NEED-throughput'},
                                                          {'type': 'justified-by', 'target': 'D-314'}])
        warnings = model.requirement_findings(found)
        self.assertIn('REQ-alone: derives from no need', warnings)
        self.assertIn('REQ-old: obsolete with no decision that retired it', warnings)
        errors, _ = model.check(model.metamodel(self.root), found)
        self.assertTrue(any(error.startswith('REQ:nowhere: names no inventory source') for error in errors), errors)


class Changes(unittest.TestCase):
    """Changes read from the merges of a temporary git repository."""

    def setUp(self):
        import subprocess
        self.root = Path(tempfile.mkdtemp(prefix='model-changes-'))
        self.addCleanup(shutil.rmtree, self.root)
        def git(*args):
            subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *args], cwd=self.root, check=True,
                           capture_output=True)
        self.git = git
        git('init', '-q', '-b', 'main')
        write(self.root, 'a.txt', 'a')
        git('add', '.')
        git('commit', '-q', '-m', 'start')
        git('checkout', '-q', '-b', 'work')
        write(self.root, 'b.txt', 'b')
        git('add', '.')
        git('commit', '-q', '-m', 'work: b\n\nImplements: REQ-a, UNIT:x')
        git('checkout', '-q', 'main')
        git('merge', '-q', '--no-ff', 'work', '-m', 'Merge pull request #5 from org/work')

    def test_a_merge_is_a_change_and_its_commits_implements_trailers_are_links(self):
        found = {item['id']: item for item in model.read_changes(self.root)}
        self.assertEqual(list(found), ['CHG-5'])
        self.assertEqual(found['CHG-5']['state'], 'merged')
        self.assertEqual(found['CHG-5']['links'], [{'type': 'implements', 'target': 'REQ-a'},
                                                   {'type': 'implements', 'target': 'UNIT:x'}])

    def test_a_requirement_is_implemented_by_a_merged_change_and_verified_when_a_test_also_verifies_it(self):
        found = {item['id']: item for item in model.read_changes(self.root)}
        found['REQ-a'] = {'id': 'REQ-a', 'type': 'REQ', 'state': 'approved', 'fingerprint': 'f', 'links': [],
                          'body': {'type': 'quality'}}
        found['REQ-b'] = {'id': 'REQ-b', 'type': 'REQ', 'state': 'approved', 'fingerprint': 'f', 'links': [],
                          'body': {'type': 'constraint'}}
        self.assertEqual(model.requirement_states(found), {'REQ-a': 'implemented', 'REQ-b': 'approved'})
        found['TEST:t'] = {'id': 'TEST:t', 'type': 'TEST', 'state': 'active', 'fingerprint': 'f',
                           'links': [{'type': 'verifies', 'target': 'REQ-a'}]}
        self.assertEqual(model.requirement_states(found)['REQ-a'], 'verified')
        counted = model.requirements_measure(found)
        self.assertEqual((counted['active'], counted['implemented'], counted['verified'], counted['with_test']), (len(['REQ-a', 'REQ-b']), 1, 1, 1))
        self.assertEqual(counted['by_type'], {'constraint': 1, 'quality': 1})

    def test_the_decisions_measure_counts_states_proofs_and_records_edited_after_they_were_written(self):
        write(self.root, 'docs/domain/decisions/D-1.md', 'one')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'D-1')
        write(self.root, 'docs/domain/decisions/D-1.md', 'one, edited')
        write(self.root, 'docs/domain/decisions/D-2.md', 'two')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'edit D-1, write D-2')
        found = {'D-1': {'id': 'D-1', 'type': 'D', 'state': 'accepted', 'fingerprint': 'f', 'links': []},
                 'D-2': {'id': 'D-2', 'type': 'D', 'state': 'superseded', 'fingerprint': 'f', 'links': []},
                 'TEST:t': {'id': 'TEST:t', 'type': 'TEST', 'state': 'active', 'fingerprint': 'f',
                            'links': [{'type': 'verifies', 'target': 'D-1'}]}}
        counted = model.decisions_measure(found, self.root)
        self.assertEqual(counted, {'by_state': {'accepted': 1, 'superseded': 1}, 'accepted': 1, 'proven': 1,
                                   'edited_records': 1})

    def test_a_validation_state_is_derived_from_its_measure_never_written(self):
        def val(id, measure, comparator, threshold, window=None):
            body = {'id': id, 'statement': 's', 'validates': ['NEED-x'], 'owner': 'o', 'measure': measure,
                    'comparator': comparator, 'threshold': threshold, **({'window': window} if window else {})}
            return {'id': id, 'type': 'VAL', 'state': 'defined', 'fingerprint': 'f', 'links': [], 'body': body}
        today = self.git_today()
        found = {item['id']: item for item in (
            val('VAL-pace', {'kind': 'merges-per-day'}, 'gte', 1, {'kind': 'days', 'size': 1}),
            val('VAL-fast', {'kind': 'merges-per-day'}, 'gte', len(['a', 'b']), {'kind': 'days', 'size': 1}),
            val('VAL-fix', {'kind': 'trailer-rate', 'trailer': 'Fixes-PR'}, 'lte', 0, {'kind': 'merges', 'size': 1}),
            val('VAL-long', {'kind': 'trailer-rate', 'trailer': 'Fixes-PR'}, 'lte', 0, {'kind': 'merges', 'size': len('long')}),
            val('VAL-none', {'kind': 'unwired', 'source': 'x'}, 'lte', 0))}
        model.derive_validations(found, self.root, today)
        self.assertEqual({id: item['state'] for id, item in found.items()},
                         {'VAL-pace': 'met', 'VAL-fast': 'not-met', 'VAL-fix': 'met', 'VAL-long': 'measuring',
                          'VAL-none': 'defined'})

    def test_an_incident_count_reads_the_records_of_its_kind_inside_the_window(self):
        today = self.git_today()
        write(self.root, 'docs/operations/incidents/I-1.md', f'---\nid: I-1\nkind: owner-stop\ntime: {today}T00:00:00Z\n---\n')
        write(self.root, 'docs/operations/incidents/I-2.md', f'---\nid: I-2\nkind: owner-stop\ntime: {self.git_day()}T00:00:00Z\n---\n')
        write(self.root, 'docs/operations/incidents/I-3.md', f'---\nid: I-3\nkind: gate-red\ntime: {self.git_day()}T00:00:00Z\n---\n')
        body = {'measure': {'kind': 'incident-count', 'incident': 'owner-stop'}, 'window': {'kind': 'days', 'size': 1}}
        self.assertEqual(model.measured(body, {}, self.root, today), (1, True))
        body['window']['size'] = len('long')
        self.assertEqual(model.measured(body, {}, self.root, today)[1], False)

    def test_a_code_scan_finds_a_sleep_inside_a_loop_and_not_one_outside(self):
        write(self.root, 'lib/poll.py', 'import time\nwhile True:\n    time.sleep(1)\ntime.sleep(1)\n')
        write(self.root, 'lib/poll.sh', '#!/usr/bin/env bash\nsleep 1\nuntil ready; do\n  sleep 2\ndone\n')
        write(self.root, 'lib/tests/t.py', 'import time\nwhile True:\n    time.sleep(1)\n')
        self.assertEqual(model.polling_sites(self.root, ['lib/**/*'], ['lib/tests/**/*']), ['lib/poll.py:3', 'lib/poll.sh:4'])

    def test_a_composite_validation_is_met_only_when_all_of_its_validations_are(self):
        def val(id, measure, comparator='lte', threshold=0):
            body = {'id': id, 'statement': 's', 'validates': ['NEED-x'], 'owner': 'o', 'measure': measure,
                    'comparator': comparator, 'threshold': threshold, 'window': {'kind': 'days', 'size': 1}}
            return {'id': id, 'type': 'VAL', 'state': 'defined', 'fingerprint': 'f', 'links': [], 'body': body}
        today = self.git_today()
        found = {item['id']: item for item in (
            val('VAL-all', {'kind': 'all-met', 'of': ['VAL-pace', 'VAL-none']}),
            val('VAL-pace', {'kind': 'merges-per-day'}, 'gte', 1),
            val('VAL-none', {'kind': 'unwired', 'source': 'x'}))}
        model.derive_validations(found, self.root, today)
        self.assertEqual(found['VAL-all']['state'], 'measuring')
        found['VAL-none']['body']['measure'] = {'kind': 'merges-per-day'}
        model.derive_validations(found, self.root, today)
        self.assertEqual(found['VAL-all']['state'], 'not-met')
        found['VAL-none']['body']['comparator'] = 'gte'
        model.derive_validations(found, self.root, today)
        self.assertEqual(found['VAL-all']['state'], 'met')

    def git_day(self):
        import subprocess
        return subprocess.run(['git', 'log', '-1', '--format=%ad', '--date=short'], cwd=self.root, capture_output=True,
                              text=True, check=True).stdout.strip()

    def git_today(self):
        from datetime import date, timedelta
        import subprocess
        day = subprocess.run(['git', 'log', '-1', '--format=%ad', '--date=short'], cwd=self.root, capture_output=True,
                             text=True, check=True).stdout.strip()
        return (date.fromisoformat(day) + timedelta(days=1)).isoformat()

    def test_a_requirements_chain_needs_a_validation_that_is_met(self):
        chain = {'REQ-1': {'id': 'REQ-1', 'type': 'REQ', 'state': 'approved', 'fingerprint': 'f', 'links': []},
                 'CHG-1': {'id': 'CHG-1', 'type': 'CHG', 'state': 'merged', 'fingerprint': 'f',
                           'links': [{'type': 'implements', 'target': 'REQ-1'}]},
                 'ARC-1': {'id': 'ARC-1', 'type': 'ARC', 'state': 'active', 'fingerprint': 'f',
                           'links': [{'type': 'satisfies', 'target': 'REQ-1'}]},
                 'UNIT:a': {'id': 'UNIT:a', 'type': 'UNIT', 'state': 'active', 'fingerprint': 'f',
                            'links': [{'type': 'realizes', 'target': 'ARC-1'}]},
                 'TEST:a': {'id': 'TEST:a', 'type': 'TEST', 'state': 'active', 'fingerprint': 'f',
                            'links': [{'type': 'verifies', 'target': 'REQ-1'}]},
                 'VAL-1': {'id': 'VAL-1', 'type': 'VAL', 'state': 'not-met', 'fingerprint': 'f',
                           'links': [{'type': 'validates', 'target': 'REQ-1'}]}}
        self.assertFalse(model.chain_verified(chain['REQ-1'], model.incoming(chain), chain))
        chain['VAL-1']['state'] = 'met'
        self.assertTrue(model.chain_verified(chain['REQ-1'], model.incoming(chain), chain))

    def test_a_runtime_requirement_is_verified_by_its_own_validation_met_in_place_of_a_test(self):
        chain = {'REQ-1': {'id': 'REQ-1', 'type': 'REQ', 'state': 'approved', 'fingerprint': 'f', 'links': [],
                           'body': {'verification': 'validation'}},
                 'CHG-1': {'id': 'CHG-1', 'type': 'CHG', 'state': 'merged', 'fingerprint': 'f',
                           'links': [{'type': 'implements', 'target': 'REQ-1'}]},
                 'ARC-1': {'id': 'ARC-1', 'type': 'ARC', 'state': 'active', 'fingerprint': 'f',
                           'links': [{'type': 'satisfies', 'target': 'REQ-1'}]},
                 'UNIT:a': {'id': 'UNIT:a', 'type': 'UNIT', 'state': 'active', 'fingerprint': 'f',
                            'links': [{'type': 'realizes', 'target': 'ARC-1'}]},
                 'VAL-1': {'id': 'VAL-1', 'type': 'VAL', 'state': 'not-met', 'fingerprint': 'f',
                           'links': [{'type': 'validates', 'target': 'REQ-1'}]}}
        self.assertFalse(model.chain_verified(chain['REQ-1'], model.incoming(chain), chain))
        chain['VAL-1']['state'] = 'met'
        self.assertTrue(model.chain_verified(chain['REQ-1'], model.incoming(chain), chain))
        del chain['REQ-1']['body']['verification']
        self.assertFalse(model.chain_verified(chain['REQ-1'], model.incoming(chain), chain))

    def test_a_verified_requirement_that_no_merged_change_implements_is_not_verified_end_to_end(self):
        chain = {'REQ-1': {'id': 'REQ-1', 'type': 'REQ', 'state': 'approved', 'fingerprint': 'f', 'links': []},
                 'ARC-1': {'id': 'ARC-1', 'type': 'ARC', 'state': 'active', 'fingerprint': 'f',
                           'links': [{'type': 'satisfies', 'target': 'REQ-1'}]},
                 'UNIT:a': {'id': 'UNIT:a', 'type': 'UNIT', 'state': 'active', 'fingerprint': 'f',
                            'links': [{'type': 'realizes', 'target': 'ARC-1'}]},
                 'TEST:a': {'id': 'TEST:a', 'type': 'TEST', 'state': 'active', 'fingerprint': 'f',
                            'links': [{'type': 'verifies', 'target': 'REQ-1'}]},
                 'VAL-1': {'id': 'VAL-1', 'type': 'VAL', 'state': 'met', 'fingerprint': 'f',
                           'links': [{'type': 'validates', 'target': 'REQ-1'}]},
                 'CHG-1': {'id': 'CHG-1', 'type': 'CHG', 'state': 'open', 'fingerprint': 'f',
                           'links': [{'type': 'implements', 'target': 'REQ-1'}]}}
        into = model.incoming(chain)
        self.assertFalse(model.implemented(chain['REQ-1'], into, chain))
        self.assertFalse(model.chain_verified(chain['REQ-1'], into, chain), 'verified but not implemented')
        chain['CHG-1']['state'] = 'merged'
        self.assertTrue(model.chain_verified(chain['REQ-1'], into, chain))
        self.assertEqual(model.requirement_states(chain)['REQ-1'], 'verified')

    def test_a_directory_that_is_not_a_repository_has_no_changes(self):
        other = Path(tempfile.mkdtemp(prefix='model-nogit-'))
        self.addCleanup(shutil.rmtree, other)
        self.assertEqual(model.read_changes(other), [])


class Supply(unittest.TestCase):
    """The Fornecimento system read from a temporary checkout: a lockfile, a supplier and an audit snapshot."""

    PACKAGES = [f'pkg-{letter}' for letter in 'abcdefghijklmnopqrst']

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='model-supply-'))
        self.addCleanup(shutil.rmtree, self.root)
        shutil.copytree(ROOT / 'contracts' / 'model', self.root / 'contracts' / 'model')
        shutil.copytree(ROOT / 'config' / 'model', self.root / 'config' / 'model')
        lock = "lockfileVersion: '9.0'\n\npackages:\n\n" + ''.join(
            f'  {name}@1.0.0:\n    resolution: {{integrity: sha512-{name}}}\n\n' for name in self.PACKAGES)
        write(self.root, 'pnpm-lock.yaml', lock)
        write(self.root, 'config/supply/suppliers/SUP-npm.json', {'id': 'SUP-npm', 'name': 'npm', 'state': 'active',
                                                                  'owner': 'engine-lane', 'kind': 'registry',
                                                                  'ecosystems': ['npm']})
        write(self.root, 'config/supply/advisories.json', {'advisories': [
            {'id': 'ADV-ghsa-aaaa', 'package': 'pkg-a', 'versions': ['1.0.0'], 'severity': 'low', 'patched': '>=2.0.0'}]})

    def measure(self):
        readers = (model.read_suppliers, model.read_dependencies, model.read_advisories)
        return model.measure(self.root, model.metamodel(self.root), model.objects(self.root, readers))['systems']['supply']

    def test_an_advisory_affecting_a_component_in_use_keeps_both_unconformant_and_the_system_below_f(self):
        found = model.objects(self.root, (model.read_suppliers, model.read_dependencies, model.read_advisories))
        meta, into = model.metamodel(self.root), model.incoming(found)
        for id in ('ADV-ghsa-aaaa', 'DEP:npm:pkg-a@1.0.0'):
            self.assertFalse(model.covered(meta, found[id], into, found), id)
        supply = self.measure()
        self.assertEqual(model.rate(supply['share'], meta['scale']), 'F', 'the share alone would rate it F')
        self.assertEqual((supply['weaknesses'], supply['level']), (1, 'L'))
        write(self.root, 'config/supply/exemptions/ADV-ghsa-aaaa.json', {'reason': 'r', 'deadline': '2099-01-01'})
        supply = self.measure()
        self.assertEqual((supply['weaknesses'], supply['level']), (0, 'F'))
        write(self.root, 'config/supply/exemptions/ADV-ghsa-aaaa.json', {'reason': 'r', 'deadline': '2000-01-01'})
        self.assertEqual(self.measure()['level'], 'L', 'an exemption past its deadline is not in force')


class Architecture(unittest.TestCase):
    """Architecture elements, capabilities, ADRs and the units that realize elements, on a temporary checkout."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='model-architecture-'))
        self.addCleanup(shutil.rmtree, self.root)
        for folder in ('contracts/model', 'config/model'):
            shutil.copytree(ROOT / folder, self.root / folder)
        write(self.root, 'config/architecture/ARC-gate.json', {
            'id': 'ARC-gate', 'kind': 'component', 'name': 'The gate', 'statement': 's', 'state': 'active',
            'owner': 'capacity', 'satisfies': ['REQ-gate-60s'], 'depends_on': ['ARC-config']})
        write(self.root, 'docs/capabilities/CAP-001-publish.md', '# CAP-001 — Publish\nstatus: approved 2026-10-22\n')
        write(self.root, 'docs/capabilities/CAP-012-defect.md', '# CAP-012 — Defects\nstatus: requested\n')
        write(self.root, 'config/architecture/imports/capabilities.json', {
            'id': 'capabilities', 'owner': 'administration', 'satisfies': {'CAP-012': ['REQ-escape-under-1']},
            'overrides': {'CAP-001': {'state': 'deprecated', 'retired_by': 'D-111'}}})
        write(self.root, 'docs/adr/ADR-24-no-actions.md', '# ADR-24\n\nStatus: superseded by D-314 (the gate runs on GitHub).\n')
        write(self.root, 'docs/adr/ADR-28-local.md', '# ADR-28\n\nDate: 2026-10-18 · Status: accepted, extends ADR-24.\n')
        write(self.root, 'docs/adr/ADR-11-player.md', '# ADR-11\n\nStatus: deprecated by D-111 (the product left).\n')
        write(self.root, 'docs/adr/ADR-06-spike.md', '# ADR-06\n\nNo status line.\n')

    def found(self):
        merged = {}
        for reader in (model.read_architecture, model.read_adrs):
            for item in reader(self.root):
                merged.setdefault(item['id'], {**item, 'links': []})['links'] += item['links']
        return merged

    def test_an_element_links_the_requirements_it_satisfies_and_the_elements_it_depends_on(self):
        self.assertEqual(self.found()['ARC-gate']['links'], [{'type': 'satisfies', 'target': 'REQ-gate-60s'},
                                                             {'type': 'depends-on', 'target': 'ARC-config'}])

    def test_a_capability_is_an_element_read_where_it_is_with_its_status_and_the_import_overrides(self):
        found = self.found()
        self.assertEqual((found['ARC-cap-001']['state'], found['ARC-cap-001']['body']['retired_by']), ('deprecated', 'D-111'))
        self.assertEqual(found['ARC-cap-012']['state'], 'proposed')
        self.assertEqual(found['ARC-cap-012']['links'], [{'type': 'satisfies', 'target': 'REQ-escape-under-1'}])
        self.assertEqual(found['ARC-cap-012']['source_id'], 'docs/capabilities/CAP-012-defect.md')

    def test_an_adr_is_a_decision_with_the_status_it_states_and_its_successor_supersedes_it(self):
        found = self.found()
        self.assertEqual({id: found[id]['state'] for id in ('ADR-24', 'ADR-28', 'ADR-11', 'ADR-06')},
                         {'ADR-24': 'superseded', 'ADR-28': 'accepted', 'ADR-11': 'deprecated', 'ADR-06': 'proposed'})
        self.assertEqual(found['D-314']['links'], [{'type': 'supersedes', 'target': 'ADR-24'}])
        self.assertEqual(found['ADR-11']['body']['retired_by'], 'D-111')

    def test_a_unit_realizes_the_elements_its_manifest_names_and_the_measure_counts_them(self):
        write(self.root, 'units/engine-gate/unit.json', {'id': 'engine-gate', 'requires': {}, 'realizes': ['ARC-gate']})
        found = {item['id']: item for item in model.read_units(self.root)}
        self.assertIn({'type': 'realizes', 'target': 'ARC-gate'}, found['UNIT:engine-gate']['links'])
        found.update(self.found())
        counted = model.architecture_measure(found)
        self.assertEqual((counted['satisfying'], counted['realized'], counted['units_realizing']), (len(['gate', 'cap-012']), 1, 1))
        self.assertEqual(counted['by_kind'], {'capability': 1, 'component': 1})

    def test_the_reflexion_model_tells_convergent_divergent_and_absent_dependencies_and_the_view_draws_them(self):
        def element(id, *deps):
            return {'id': id, 'type': 'ARC', 'state': 'active', 'fingerprint': 'f', 'body': {'kind': 'component', 'name': id},
                    'links': [{'type': 'depends-on', 'target': dep} for dep in deps]}
        def unit(id, realizes, *deps):
            return {'id': id, 'type': 'UNIT', 'state': 'active', 'fingerprint': 'f',
                    'links': [{'type': 'realizes', 'target': realizes}, *({'type': 'depends-on', 'target': dep} for dep in deps)]}
        found = {item['id']: item for item in (
            element('ARC-a', 'ARC-b', 'ARC-c'), element('ARC-b'), element('ARC-c'),
            unit('UNIT:a', 'ARC-a', 'UNIT:b'), unit('UNIT:b', 'ARC-b', 'UNIT:c'), unit('UNIT:c', 'ARC-c'),
            unit('UNIT:a2', 'ARC-a', 'UNIT:a'))}
        self.assertEqual(model.reflexion(found), {'convergences': [('ARC-a', 'ARC-b')], 'divergences': [('ARC-b', 'ARC-c')],
                                                  'absences': [('ARC-a', 'ARC-c')]})
        self.assertEqual(model.reflexion_share(found)['share'], 1 / len(['conv', 'div', 'abs']))
        drawn = model.view(found)
        self.assertIn('ARC_a --> ARC_b', drawn)
        self.assertIn('ARC_b -.-> ARC_c', drawn)
        self.assertIn('ARC_a --x ARC_c', drawn)

    def test_a_test_file_declares_what_it_verifies_on_a_verifies_line(self):
        root = Path(tempfile.mkdtemp(prefix='model-verifies-'))
        self.addCleanup(shutil.rmtree, root)
        write(root, 'scripts/tests/test_a.py', '"""A test.\n\nVerifies: REQ-a, D-1\n"""\n# Verifies: REQ-a, UNIT:x\n')
        write(root, 'scripts/tests/b.test.sh', '#!/bin/sh\n')
        found = {item['id']: item for item in model.read_tests(root)}
        self.assertEqual(found['TEST:scripts/tests/test_a.py']['links'], [{'type': 'verifies', 'target': 'REQ-a'},
                                                                           {'type': 'verifies', 'target': 'D-1'},
                                                                           {'type': 'verifies', 'target': 'UNIT:x'}])
        self.assertEqual(found['TEST:scripts/tests/b.test.sh']['links'], [])

    def test_a_script_test_verifies_the_units_whose_code_its_covers_names(self):
        found = {item['id']: item for item in model.read_tests(ROOT)}
        self.assertIn({'type': 'verifies', 'target': 'UNIT:engine-model'}, found['TEST:scripts/tests/model.test.sh']['links'])

    def test_this_checkouts_test_files_are_parts_of_the_script_tests_that_run_them(self):
        found = {item['id']: item for item in model.read_tests(ROOT)}
        self.assertNotIn('TEST:scripts/tests/test_model.py', found)
        self.assertIn('scripts/tests/test_model.py', found['TEST:scripts/tests/model.test.sh']['parts'])
        self.assertIn({'type': 'verifies', 'target': 'REQ-chain-verified'}, found['TEST:scripts/tests/model.test.sh']['links'])


ORPHANS_REGISTRY = ('contracts/config/registry.v1.json', 'contracts/events/config.changed.v1.json',
                    'config/registry/config.json', 'config/registry/test-orphans.json')


class FoldedTests(unittest.TestCase):
    """A test file a script test runs is part of that script test (the unit the gate selects and reports), not a
    test object of its own; a test file no script test runs stays one."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='model-folded-'))
        self.addCleanup(shutil.rmtree, self.root)
        for name in ORPHANS_REGISTRY:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(ROOT / name, self.root / name)
        write(self.root, 'scripts/tests/a.test.sh', 'exec python3 "$root"/scripts/tests/test_a*.py\n')
        write(self.root, 'scripts/tests/test_a.py', '# Verifies: D-1\n')
        write(self.root, 'scripts/tests/test_a_more.py', 'pass\n')
        write(self.root, 'scripts/tests/s1.test.sh', 'X_SHARD=1 python3 "$root"/scripts/tests/test_shared.py\n')
        write(self.root, 'scripts/tests/s2.test.sh', 'X_SHARD=2 python3 "$root"/scripts/tests/test_shared.py\n')
        write(self.root, 'scripts/tests/test_shared.py', 'pass\n')
        write(self.root, 'scripts/tests/test_zed.py', 'pass\n')

    def read(self):
        return {item['id']: item for item in model.read_tests(self.root)}

    def test_a_test_file_a_script_test_runs_is_one_of_its_parts_and_its_verifies_lines_are_the_script_tests_links(self):
        found = self.read()
        runner = found['TEST:scripts/tests/a.test.sh']
        self.assertEqual(runner['parts'], ['scripts/tests/test_a.py', 'scripts/tests/test_a_more.py'])
        self.assertEqual(runner['links'], [{'type': 'verifies', 'target': 'D-1'}])
        self.assertNotIn('TEST:scripts/tests/test_a.py', found)
        self.assertNotIn('TEST:scripts/tests/test_a_more.py', found)

    def test_a_test_file_no_script_test_runs_stays_a_test_of_its_own_with_no_link(self):
        found = self.read()
        self.assertEqual(found['TEST:scripts/tests/test_zed.py']['links'], [])
        self.assertNotIn('parts', found['TEST:scripts/tests/test_zed.py'])
        self.assertEqual(sorted(found), ['TEST:scripts/tests/a.test.sh', 'TEST:scripts/tests/s1.test.sh',
                                         'TEST:scripts/tests/s2.test.sh', 'TEST:scripts/tests/test_zed.py'])

    def test_a_file_each_shard_runs_is_a_part_of_every_shard_and_gives_none_a_link_it_does_not_hold(self):
        found = self.read()
        for shard in ('s1', 's2'):
            self.assertEqual(found[f'TEST:scripts/tests/{shard}.test.sh']['parts'], ['scripts/tests/test_shared.py'])
            self.assertEqual(found[f'TEST:scripts/tests/{shard}.test.sh']['links'], [])

    def test_the_script_tests_fingerprint_moves_when_a_part_changes(self):
        before = self.read()['TEST:scripts/tests/a.test.sh']['fingerprint']
        write(self.root, 'scripts/tests/test_a_more.py', 'pass  # changed\n')
        self.assertNotEqual(self.read()['TEST:scripts/tests/a.test.sh']['fingerprint'], before)

    def test_a_link_to_a_part_moves_to_its_script_test_and_a_gone_file_stays_claimed(self):
        found = {item['id']: item for item in model.read_tests(self.root)}
        found['TEST:scripts/tests/test_a_more.py'] = {
            'id': 'TEST:scripts/tests/test_a_more.py', 'type': 'TEST', 'state': 'active', 'claimed': True,
            'source': 'scripts/tests/test_a_more.py', 'fingerprint': None, 'links': [{'type': 'verifies', 'target': 'D-2'}]}
        found['TEST:scripts/tests/test_gone.py'] = {
            'id': 'TEST:scripts/tests/test_gone.py', 'type': 'TEST', 'state': 'active', 'claimed': True,
            'source': 'scripts/tests/test_gone.py', 'fingerprint': None, 'links': [{'type': 'verifies', 'target': 'D-3'}]}
        found['CTRL-x'] = {'id': 'CTRL-x', 'type': 'CTRL', 'state': 'met', 'fingerprint': 'f',
                           'links': [{'type': 'implemented-by', 'target': 'TEST:scripts/tests/test_shared.py'}]}
        model.fold_parts(found)
        self.assertNotIn('TEST:scripts/tests/test_a_more.py', found)
        self.assertIn({'type': 'verifies', 'target': 'D-2'}, found['TEST:scripts/tests/a.test.sh']['links'])
        self.assertIn('TEST:scripts/tests/test_gone.py', found)
        self.assertEqual(found['CTRL-x']['links'], [{'type': 'implemented-by', 'target': 'TEST:scripts/tests/s1.test.sh'},
                                                    {'type': 'implemented-by', 'target': 'TEST:scripts/tests/s2.test.sh'}])


class Layers(unittest.TestCase):
    def test_a_dependency_on_a_higher_layer_is_refused_and_one_on_the_same_or_lower_is_not(self):
        def arc(id, layer, *targets):
            return {'id': id, 'type': 'ARC', 'state': 'active', 'fingerprint': 'f', 'body': {'layer': layer},
                    'links': [{'type': 'depends-on', 'target': target} for target in targets]}
        found = {item['id']: item for item in (arc('ARC-low', 0), arc('ARC-mid', 1, 'ARC-low', 'ARC-same'),
                                               arc('ARC-same', 1), arc('ARC-up', 0, 'ARC-mid'))}
        errors = model.layer_errors(found)
        self.assertEqual(len(errors), 1)
        self.assertIn('ARC-up: depends on ARC-mid of a higher layer', errors[0])


class RealRepository(unittest.TestCase):
    def test_a_site_test_counts_only_when_it_declares_what_it_verifies_and_a_typescript_comment_declares_it(self):
        tests = {item['id']: item for item in model.read_tests(ROOT)}
        perf = tests['TEST:apps/web/scripts/lib/perf-budget-home.test.ts']
        self.assertEqual(perf['links'], [{'type': 'verifies', 'target': 'REQ-web-home-perf-budget'}])
        self.assertFalse([name for name in tests if name.startswith('TEST:apps/web/') and not tests[name]['links']])

    def test_the_metamodel_of_this_checkout_is_valid_and_has_a_type_for_every_system(self):
        meta = model.metamodel(ROOT)
        self.assertEqual(meta['errors'], [])
        self.assertEqual({kind['system'] for kind in meta['types'].values()}, set(meta['systems']))

    def test_every_object_of_this_checkout_fits_the_metamodel(self):
        errors, _ = model.check(model.metamodel(ROOT), model.objects(ROOT))
        self.assertEqual(errors, [])

    def test_a_decision_proof_becomes_a_verifies_link_on_the_test_and_a_gone_proof_a_warning(self):
        found = model.objects(ROOT)
        record = next(Path(ROOT).glob(model.DECISION_RECORDS))
        number = record.stem
        proof = model.FRONT.match(record.read_text()).group(1).split('proof:', 1)[1].split('\n', 1)[0].strip().strip('`')
        # A proof that names a test file a script test runs is a link on that script test (its part).
        holders = {f'TEST:{proof}'} | {item['id'] for item in found.values() if proof in item.get('parts', ())}
        self.assertTrue(holders & {source for kind, source in model.incoming(found).get(number, []) if kind == 'verifies'})
        _, warnings = model.check(model.metamodel(ROOT), found)
        gone = [item for item in found.values() if item.get('claimed') and item['fingerprint'] is None]
        self.assertEqual(len([line for line in warnings if 'no such file exists' in line]), len(gone))

    def test_the_measure_counts_every_inventory_source_and_rates_every_system(self):
        result = model.measure(ROOT)
        meta = model.metamodel(ROOT)
        self.assertEqual(set(result['inventory']['sources']), set(meta['inventory']))
        self.assertTrue(all(item['ids'] for item in result['inventory']['sources'].values()))
        levels = {level['level'] for level in meta['scale']}
        self.assertTrue(all(item['level'] in levels for item in result['systems'].values()))
        self.assertEqual(set(result['systems']), set(meta['systems']))
        self.assertIn('chain:', model.summary(result))

    def test_every_refusal_and_gate_stage_of_this_checkout_has_a_rule(self):
        warnings = model.rule_findings(model.objects(ROOT), ROOT)
        self.assertEqual([line for line in warnings if 'with no rule of the standard' in line], [])

    def test_every_premise_of_the_register_is_an_object_and_a_decision_assumes_the_premises_it_names(self):
        import premises
        records, _ = premises.load(ROOT)
        found = model.objects(ROOT)
        self.assertEqual({id for id, item in found.items() if item['type'] == 'P'}, set(records))
        assuming = next(item for item in found.values() if item['type'] == 'D'
                        and any(link['type'] == 'assumes' for link in item['links']))
        target = next(link['target'] for link in assuming['links'] if link['type'] == 'assumes')
        self.assertEqual(found[target]['type'], 'P')
        counted = model.knowledge_measure(found)
        self.assertEqual(counted['premises'], len(records))
        high = [record for record in records.values() if record['radius'] == 'high'
                and record['status'] not in ('confirmed', 'validated', 'refuted')]
        self.assertEqual(counted['high_unsettled'], len(high))

    def test_a_decision_that_says_it_refutes_a_premise_it_names_refutes_it_and_is_not_counted_as_assuming_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / Path(model.DECISION_RECORDS).parent
            folder.mkdir(parents=True)
            (folder / 'D-901.md').write_text('---\nnumber: D-901\npremises: P-1, P-2\n---\nThis refutes P-1 by measure.\n')
            links = next(item for item in model.read_decisions(tmp) if item['id'] == 'D-901')['links']
        self.assertEqual(links, [{'type': 'refutes', 'target': 'P-1'}, {'type': 'assumes', 'target': 'P-2'}])
        found = {'P-1': {'id': 'P-1', 'type': 'P', 'state': 'refuted', 'body': {}, 'links': []},
                 'P-2': {'id': 'P-2', 'type': 'P', 'state': 'refuted', 'body': {}, 'links': []},
                 'D-901': {'id': 'D-901', 'type': 'D', 'state': 'accepted', 'body': '', 'links': links}}
        self.assertEqual(model.knowledge_measure(found)['refuted_assumed'], 1)
        self.assertEqual(model.knowledge_measure(model.objects(ROOT))['refuted_assumed'], 0)

    def test_show_names_an_object_with_its_links_out_and_in(self):
        text = model.show('UNIT:engine-model', ROOT)
        self.assertIn('UNIT:engine-model  UNIT  active  units/engine-model/unit.json', text)
        self.assertIn('-> depends-on UNIT:engine-config', text)
        with self.assertRaises(model.ModelError):
            model.show('UNIT:no-such-unit', ROOT)


if __name__ == '__main__':
    unittest.main()
