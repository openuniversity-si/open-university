"""The Operation system's data stores (DATA) and data subject requests (REQUEST), PADRAO-DEV F7d (D-320, D-321): states
derived from the records, never written. Hermetic: in-memory records and temporary repositories.

Verifies: REQ-chain-verified, REQ-web-lgpd-processing
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


def store(personal=False, method='automated', verified=None, **fields):
    backup = {'method': method, **({'last_restore_verified': verified} if verified else {})}
    return {'personal': personal, 'backup': backup, **fields}


class DataState(unittest.TestCase):
    def test_personal_data_without_purpose_basis_and_retention_is_unregistered_whatever_its_backup(self):
        self.assertEqual(model.data_state(store(personal=True, verified='2026-11-17'), '2026-11-17', 90), 'unregistered')
        complete = store(personal=True, verified='2026-11-17', purpose='p', legal_basis='b', retention='r')
        self.assertEqual(model.data_state(complete, '2026-11-17', 90), 'protected')

    def test_per_field_processing_registers_a_store_only_when_it_covers_every_personal_field(self):
        entry = {'fields': ['user.email'], 'purpose': 'p', 'legal_basis': 'b', 'retention': 'r'}
        partial = store(personal=True, verified='2026-11-17', personal_fields=['user.email', 'session.ip'], processing=[entry])
        self.assertEqual(model.data_state(partial, '2026-11-17', 90), 'unregistered')
        whole = {**partial, 'processing': [entry, {**entry, 'fields': ['session.ip']}]}
        self.assertEqual(model.data_state(whole, '2026-11-17', 90), 'protected')

    def test_a_backup_counts_only_with_a_restore_verified_within_the_window(self):
        self.assertEqual(model.data_state(store(), '2026-11-17', 90), 'unverified')
        self.assertEqual(model.data_state(store(verified='2026-08-01'), '2026-11-17', 90), 'unverified')
        self.assertEqual(model.data_state(store(verified='2026-09-01'), '2026-11-17', 90), 'protected')

    def test_no_backup_is_unprotected_and_a_rebuilt_store_is_regenerable(self):
        self.assertEqual(model.data_state(store(method='none'), '2026-11-17', 90), 'unprotected')
        self.assertEqual(model.data_state(store(method='regenerable'), '2026-11-17', 90), 'regenerable')


class RequestState(unittest.TestCase):
    def test_a_request_is_open_then_overdue_and_answered_on_time_or_late(self):
        body = {'received': '2026-11-01', 'due': '2026-11-16'}
        self.assertEqual(model.request_state(body, '2026-11-16'), 'open')
        self.assertEqual(model.request_state(body, '2026-11-17'), 'overdue')
        self.assertEqual(model.request_state({**body, 'answered': '2026-11-16'}, '2026-11-20'), 'answered')
        self.assertEqual(model.request_state({**body, 'answered': '2026-11-18'}, '2026-11-20'), 'answered-late')


class Readers(unittest.TestCase):
    def test_a_data_record_out_of_its_contract_is_a_problem_and_a_valid_one_links_its_supplier(self):
        root = Path(tempfile.mkdtemp(prefix='operation-data-'))
        self.addCleanup(shutil.rmtree, root)
        shutil.copytree(ROOT / 'contracts', root / 'contracts')
        good = {'id': 'DATA-a', 'name': 'a', 'kind': 'bucket', 'location': 'x', 'owner': 'o', 'personal': False,
                'supplier': 'SUP-x', 'backup': {'method': 'regenerable'}}
        (root / 'config/operation/data').mkdir(parents=True)
        (root / 'config/operation/data/DATA-a.json').write_text(json.dumps(good))
        (root / 'config/operation/data/DATA-b.json').write_text(json.dumps({**good, 'id': 'DATA-b', 'kind': 'tape'}))
        found = {item['id']: item for item in model.read_data(root)}
        self.assertEqual((found['DATA-a']['state'], found['DATA-a']['links']),
                         ('regenerable', [{'type': 'supplied-by', 'target': 'SUP-x'}]))
        self.assertTrue(found['DATA:DATA-b']['problems'])


if __name__ == '__main__':
    unittest.main()
