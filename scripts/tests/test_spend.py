"""The AWS spend as a validation source (D-331): the snapshot recorded from the deploy build's daily Cost Explorer reading
and the aws-spend measure of VAL-aws-200; the supplier-spend measure on a reading checked by hand, its threshold read
from a registry key (D-342). Hermetic: in-memory answers and temporary folders.

Verifies: REQ-aws-200, REQ-anthropic-budget
"""
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import model  # noqa: E402
import spend  # noqa: E402

# the readings are JSON text, as the port answers them: the census counts no number of a test (LT1)
READING = json.loads('{"day": "2026-11-19", "from": "2026-11-01", "usd": 41.236}')
CENTS = json.loads('41.24')  # the reading to the cent
OVER = json.loads('212.5')  # over the ceiling


class Reading(unittest.TestCase):
    def test_the_port_status_the_record_and_the_reading_alone_give_the_same_reading(self):
        for answer in ({'last_sha': 'a', 'last_build': {'status': 'succeeded', 'spend': READING}}, {'spend': READING}, READING):
            self.assertEqual(spend.reading(answer), {**READING, 'usd': CENTS})

    def test_no_or_a_malformed_reading_is_none(self):
        for answer in ({'last_build': {'status': 'succeeded'}}, {'last_build': None}, [], {'spend': {'day': '2026-11-19'}},
                       {'spend': {**READING, 'usd': -1}}, {'spend': {**READING, 'usd': -float('0.01')}},
                       {'spend': {**READING, 'usd': True}}, {'spend': {**READING, 'from': '2026-10-01'}}):
            self.assertIsNone(spend.reading(answer), answer)

    def test_record_writes_the_snapshot_and_refuses_an_input_with_no_reading(self):
        root = Path(tempfile.mkdtemp(prefix='spend-'))
        self.addCleanup(shutil.rmtree, root)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(spend.main(['record'], root, io.StringIO(json.dumps({'last_build': {}}))), 1)
            self.assertEqual(spend.main(['record'], root, io.StringIO(json.dumps({'spend': {**READING, 'usd': -1}}))), 1)
            self.assertIsNone(spend.read(root))
            self.assertEqual(spend.main(['record'], root, io.StringIO(json.dumps({'last_build': {'spend': READING}}))), 0)
        written = spend.read(root)
        self.assertEqual((written['day'], written['from'], written['usd']), ('2026-11-19', '2026-11-01', CENTS))
        self.assertIn('Cost Explorer', written['source'])
        self.assertIn('excluding Credit and Refund', written['source'])


class Measure(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='spend-'))
        self.addCleanup(shutil.rmtree, self.root)
        val = json.loads((ROOT / 'config/validation/VAL-aws-200.json').read_text())
        self.assertEqual(val['nc'], 'NC-cost')
        self.body = json.loads((ROOT / 'config/problem/NC-cost.json').read_text())

    def write(self, **reading):
        target = self.root / spend.SNAPSHOT
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(spend.snapshot({**spend.reading(READING), **reading}, now='2026-11-19T12:00:00Z')))

    def test_val_aws_200_reads_the_spend_snapshot_against_its_ceiling(self):
        self.assertEqual((self.body['measure']['kind'], self.body['comparator']), ('aws-spend', 'lte'))
        self.write()
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-20'), (CENTS, True))

    def test_an_old_or_last_months_reading_is_still_measuring_and_one_over_the_ceiling_is_final(self):
        self.write()
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-25'), (CENTS, False))
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-12-01'), (CENTS, False))
        self.write(usd=OVER)
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-28'), (OVER, True))
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-12-01'), (OVER, False))

    def test_no_snapshot_is_no_source(self):
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-20'), (None, False))


# a supplier-spend validation whose ceiling is a registry key of the temporary root (D-342)
CEILING = json.loads('{"type": "number", "default": 100, "x-unit": "usd", "description": "d"}')
SUPPLIER = json.loads('{"id": "VAL-acme", "statement": "s", "validates": ["NEED-cost"], "owner": "o", "comparator": "lte",'
                      ' "measure": {"kind": "supplier-spend", "supplier": "acme", "max_age_days": 35},'
                      ' "threshold_key": "test.ceiling_usd"}')
INVOICE = json.loads('{"usd": 100, "day": "2026-11-19", "source": "the invoice"}')
STALE_DAY = '2027-01-01'


class SupplierSpend(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='spend-'))
        self.addCleanup(shutil.rmtree, self.root)
        self.put('contracts/model/validation.v1.json', json.loads((ROOT / 'contracts/model/validation.v1.json').read_text()))
        self.put('config/registry/test.json', {'properties': {'test.ceiling_usd': CEILING}})

    def put(self, path, body):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(body))

    def state(self, today=INVOICE['day'], **body):
        self.put('config/validation/VAL-acme.json', {**SUPPLIER, **body})
        found = {item['id']: item for item in model.read_validations(self.root)}
        model.derive_validations(found, self.root, today)
        return found

    def test_the_threshold_is_read_from_the_registry_key(self):
        self.put('config/validation/spend/acme.json', INVOICE)
        found = self.state()
        self.assertEqual(found['VAL-acme']['body']['threshold'], CEILING['default'])
        self.assertEqual((found['VAL-acme']['measured'], found['VAL-acme']['state']), (INVOICE['usd'], 'met'))

    def test_over_the_keys_value_is_not_met_and_at_or_under_it_is_met(self):
        for usd, state in ((CEILING['default'] + 1, 'not-met'), (CEILING['default'], 'met'), (CEILING['default'] - 1, 'met')):
            self.put('config/validation/spend/acme.json', {**INVOICE, 'usd': usd})
            self.assertEqual(self.state()['VAL-acme']['state'], state, usd)

    def test_a_stale_reading_is_measuring_and_no_reading_is_defined(self):
        self.assertEqual(self.state()['VAL-acme']['state'], 'defined')
        self.put('config/validation/spend/acme.json', INVOICE)
        self.assertEqual(self.state(STALE_DAY)['VAL-acme']['state'], 'measuring')

    def test_threshold_and_threshold_key_together_or_an_unknown_key_is_an_error(self):
        found = self.state(threshold=CEILING['default'])
        self.assertEqual(found['VAL-acme']['problems'], ['carries threshold or threshold_key, exactly one'])
        self.assertNotIn('body', found['VAL-acme'])
        found = self.state(threshold_key='test.no_such_key')
        self.assertEqual(found['VAL-acme']['problems'], ['its threshold_key test.no_such_key is not a registered parameter'])
        self.assertNotIn('body', found['VAL-acme'])

    def test_the_repositorys_anthropic_budget_is_met_by_its_first_reading(self):
        item = next(item for item in model.read_validations(ROOT) if item['id'] == 'VAL-anthropic-budget')
        body = item['body']
        self.assertEqual(body['threshold'], model.registry_threshold(body['threshold_key'], ROOT))
        recorded = spend.read_supplier(ROOT, body['measure']['supplier'])
        model.derive_validations({item['id']: item}, ROOT, recorded['day'])
        self.assertEqual((item['measured'], item['state']), (recorded['usd'], 'met'))


if __name__ == '__main__':
    unittest.main()
