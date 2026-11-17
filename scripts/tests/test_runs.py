"""Run durations as a validation source (PADRAO-DEV F8d): the recorded snapshot of a workflow's runs and the
run-durations measure. Hermetic: in-memory answers and temporary repositories.

Verifies: REQ-gate-60s
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
import runs  # noqa: E402


def run(id, started, updated, conclusion='success'):
    return {'id': id, 'event': 'pull_request', 'status': 'completed', 'conclusion': conclusion,
            'run_started_at': started, 'updated_at': updated}


class Snapshot(unittest.TestCase):
    def test_a_run_lasts_from_its_start_to_its_last_update_and_a_cancelled_run_does_not_count(self):
        answer = {'workflow_runs': [run(1, '2026-11-17T10:00:00Z', '2026-11-17T10:00:40Z'),
                                    run(2, '2026-11-17T11:00:00Z', '2026-11-17T11:00:05Z', 'cancelled')]}
        self.assertEqual([(item['id'], item['seconds']) for item in runs.normalize(answer)], [(1, 40)])

    def test_the_nearest_rank_percentile(self):
        values = list(range(1, len('abcdefghij') + 1))
        self.assertEqual((runs.percentile(values, 50), runs.percentile(values, 99), runs.percentile([], 50)), (5, 10, None))


class Measure(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='runs-'))
        self.addCleanup(shutil.rmtree, self.root)
        answer = [run(i, '2026-11-17T10:00:00Z', f'2026-11-17T10:00:{30 + i:02d}Z') for i in range(len('abc'))]
        target = self.root / runs.FOLDER / 'tower-gate.json'
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(runs.snapshot('tower-gate', answer, now='2026-11-17T12:00:00Z')))
        self.body = {'measure': {'kind': 'run-durations', 'workflow': 'tower-gate', 'percentile': 99,
                                 'min_runs': len('abc'), 'max_age_days': 7}}

    def test_a_fresh_snapshot_with_enough_runs_gives_its_percentile(self):
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-18'), (32, True))

    def test_a_stale_or_short_snapshot_is_still_measuring(self):
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-30')[1], False)
        self.body['measure']['min_runs'] = len('abcd')
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-18')[1], False)

    def test_no_snapshot_is_no_source(self):
        self.body['measure']['workflow'] = 'other'
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-18'), (None, False))


if __name__ == '__main__':
    unittest.main()
