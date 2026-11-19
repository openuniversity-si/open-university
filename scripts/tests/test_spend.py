"""The AWS spend as a validation source (D-331): the snapshot recorded from the deploy build's daily Cost Explorer reading
and the aws-spend measure of VAL-aws-200. Hermetic: in-memory answers and temporary folders.

Verifies: REQ-aws-200
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
                       {'spend': {**READING, 'usd': -1}}, {'spend': {**READING, 'from': '2026-10-01'}}):
            self.assertIsNone(spend.reading(answer), answer)

    def test_record_writes_the_snapshot_and_refuses_an_input_with_no_reading(self):
        root = Path(tempfile.mkdtemp(prefix='spend-'))
        self.addCleanup(shutil.rmtree, root)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(spend.main(['record'], root, io.StringIO(json.dumps({'last_build': {}}))), 1)
            self.assertIsNone(spend.read(root))
            self.assertEqual(spend.main(['record'], root, io.StringIO(json.dumps({'last_build': {'spend': READING}}))), 0)
        written = spend.read(root)
        self.assertEqual((written['day'], written['from'], written['usd']), ('2026-11-19', '2026-11-01', CENTS))
        self.assertIn('Cost Explorer', written['source'])


class Measure(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='spend-'))
        self.addCleanup(shutil.rmtree, self.root)
        self.body = json.loads((ROOT / 'config/validation/VAL-aws-200.json').read_text())

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


if __name__ == '__main__':
    unittest.main()
