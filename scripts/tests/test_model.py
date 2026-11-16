"""scripts/model (PADRAO-DEV F1a): the metamodel as data, the objects of the systems that exist, the check, the chain,
the inventory and the conformance. Hermetic: no network; the error cases run on a temporary checkout."""
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
        }
        for id, item in types.items():
            write(self.root, f'config/model/types/{id}.json', {'id': id, 'name': id.lower(), **item, 'description': 'd'})
        for name, start, end in (('satisfies', ['ARC'], ['REQ']), ('realizes', ['UNIT'], ['ARC']),
                                 ('verifies', ['TEST'], ['REQ']), ('validates', ['VAL'], ['REQ']),
                                 ('derives-from', ['REQ'], ['REQ'])):
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

    def test_the_chain_is_verified_only_with_an_element_a_unit_a_test_and_a_validation(self):
        chain = [{'id': 'REQ-1', 'type': 'REQ', 'state': 'approved'},
                 {'id': 'ARC-1', 'type': 'ARC', 'links': [{'type': 'satisfies', 'target': 'REQ-1'}]},
                 {'id': 'UNIT:a', 'type': 'UNIT', 'links': [{'type': 'realizes', 'target': 'ARC-1'}]},
                 {'id': 'TEST:a', 'type': 'TEST', 'links': [{'type': 'verifies', 'target': 'REQ-1'}]},
                 {'id': 'VAL-1', 'type': 'VAL', 'state': 'defined', 'links': [{'type': 'validates', 'target': 'REQ-1'}]}]
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
        found = self.objects({'id': 'REQ-1', 'type': 'REQ', 'state': 'draft', 'source_id': 'D-3'})
        counted = model.inventory(self.meta(), found, self.root)['all']
        self.assertEqual((counted['ids'], counted['imported']), (len(['D-1', 'D-2', 'D-3', 'A', 'a.one', 'a.two']), 1))


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


class RealRepository(unittest.TestCase):
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
        self.assertIn(('verifies', f'TEST:{proof}'), model.incoming(found).get(number, []))
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

    def test_show_names_an_object_with_its_links_out_and_in(self):
        text = model.show('UNIT:engine-model', ROOT)
        self.assertIn('UNIT:engine-model  UNIT  active  units/engine-model/unit.json', text)
        self.assertIn('-> depends-on UNIT:engine-config', text)
        with self.assertRaises(model.ModelError):
            model.show('UNIT:no-such-unit', ROOT)


if __name__ == '__main__':
    unittest.main()
