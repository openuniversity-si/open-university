"""The polling scan's decisions (PADRAO-DEV F8b): every candidate of VAL-events-no-polling decided by file and function;
backoff, dormant, test infrastructure and measurement do not count, a wait on a state does. Hermetic: temporary
repositories, and the decisions of this tree.

Verifies: REQ-events-no-polling
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import json_schema  # noqa: E402
import model  # noqa: E402

CODE = 'import time\n\ndef retry():\n    while True:\n        time.sleep(1)\n\ndef wait():\n    for _ in range(3):\n        time.sleep(1)\n'


def write(root, path, data):
    target = Path(root) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(data if isinstance(data, str) else json.dumps(data))


class Decisions(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='polling-'))
        self.addCleanup(shutil.rmtree, self.root)
        write(self.root, 'lib/x.py', CODE)
        write(self.root, 'lib/run.sh', '#!/usr/bin/env bash\nwait_up() {\n  until ok; do\n    sleep 1\n  done\n}\n')

    def test_each_candidate_is_named_by_its_file_and_function(self):
        self.assertEqual([(path, function) for path, function, _ in model.polling_candidates(self.root, ['lib/*'], [])],
                         [('lib/run.sh', 'wait_up'), ('lib/x.py', 'retry'), ('lib/x.py', 'wait')])

    def test_a_backoff_does_not_count_and_a_wait_on_a_state_or_an_undecided_one_does(self):
        write(self.root, 'config/validation/polling/POLL-a.json', {'id': 'POLL-a', 'site': 'lib/x.py::retry', 'class': 'backoff', 'reason': 'r'})
        write(self.root, 'config/validation/polling/POLL-b.json', {'id': 'POLL-b', 'site': 'lib/x.py::wait', 'class': 'state-wait', 'reason': 'r'})
        left = [(path, function) for path, function, _ in model.polling_left(self.root, ['lib/*'], [])]
        self.assertEqual(left, [('lib/run.sh', 'wait_up'), ('lib/x.py', 'wait')])


class RealRepository(unittest.TestCase):
    def setUp(self):
        self.measure = json.loads((ROOT / 'config/validation/VAL-events-no-polling.json').read_text())['measure']

    def test_every_candidate_is_decided_and_every_decision_names_a_candidate_and_fits_its_contract(self):
        candidates = {f'{path}::{function}' for path, function, _ in
                      model.polling_candidates(ROOT, self.measure['paths'], self.measure.get('exclude', []))}
        decided = model.polling_decisions(ROOT)
        self.assertEqual(sorted(candidates - set(decided)), [], 'a new sleep inside a loop needs its decision')
        self.assertEqual(sorted(set(decided) - candidates), [], 'a decision whose site is gone is removed')
        schema = json.loads((ROOT / 'contracts/model/polling.v1.json').read_text())
        for path in sorted((ROOT / 'config/validation/polling').glob('POLL-*.json')):
            body = json.loads(path.read_text())
            self.assertEqual(list(json_schema.validate(schema, body)) + ([] if body['id'] == path.stem else ['id']), [], path.name)


if __name__ == '__main__':
    unittest.main()
