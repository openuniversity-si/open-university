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
import unittest.mock

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

    def test_val_deploy_1s_reads_the_median_of_the_deploys_snapshot(self):
        # the snapshot scripts/deploy status records (deploy.record): the same reader as the gate's, at its median
        body = json.loads((ROOT / 'config/validation/VAL-deploy-1s.json').read_text())
        builds = [{'id': f'p:b{i}', 'event': 'deploy', 'conclusion': 'success', 'started': '2026-11-19T01:00:00Z',
                   'seconds': seconds} for i, seconds in enumerate((26, 17, 9))]
        (self.root / runs.FOLDER / 'deploy.json').write_text(json.dumps({'workflow': 'deploy', 'at': '2026-11-19T02:00:00Z',
                                                                         'runs': builds}))
        self.assertEqual(model.measured(body, {}, self.root, '2026-11-19'), (17, False))  # fewer than min_runs: measuring
        body['measure']['min_runs'] = len(builds)
        self.assertEqual(model.measured(body, {}, self.root, '2026-11-19'), (17, True))
        self.assertEqual(model.measured(body, {}, self.root, '2026-11-30')[1], False)

    def test_no_snapshot_is_no_source(self):
        self.body['measure']['workflow'] = 'other'
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-18'), (None, False))


def check(id, name, started, completed, conclusion='success'):
    return {'id': id, 'name': name, 'status': 'completed', 'conclusion': conclusion, 'started_at': started,
            'completed_at': completed}


class Refresh(unittest.TestCase):
    """The snapshot renews itself where it is measured, from GitHub's check runs of main's last merges (never the
    Actions API): a day-old snapshot is rebuilt, a fresh one is kept, and an API that does not answer keeps the
    recorded one."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='runs-'))
        self.addCleanup(shutil.rmtree, self.root)
        self.asked = []
        runs.write(self.root, runs.snapshot('tower-gate', [run(1, '2026-11-17T10:00:00Z', '2026-11-17T10:00:30Z')],
                                            now='2026-11-17T12:00:00Z'))

    def reader(self, answer):
        def read(workflow):
            self.asked.append(workflow)
            return answer
        return read

    def test_a_run_lasts_from_its_first_part_to_the_end_of_its_final_check(self):
        checks = [check(1, 'gate part (main)', '2026-11-19T01:42:15Z', '2026-11-19T01:42:41Z'),
                  check(2, 'gate part (shard1)', '2026-11-19T01:42:16Z', '2026-11-19T01:43:13Z'),
                  check(3, 'web', '2026-11-19T01:40:00Z', '2026-11-19T01:42:34Z'),
                  check(4, 'tower/gate', '2026-11-19T01:43:15Z', '2026-11-19T01:43:17Z')]
        self.assertEqual(runs.from_checks('merge_group', checks, 'tower/gate', 'gate part'),
                         {'id': 4, 'event': 'merge_group', 'conclusion': 'success', 'started': '2026-11-19T01:42:15Z',
                          'seconds': 62})
        cancelled = [check(5, 'tower/gate', '2026-11-19T01:43:15Z', '2026-11-19T01:43:17Z', 'cancelled')]
        self.assertEqual([runs.from_checks('pull_request', each, 'tower/gate', 'gate part') for each in ([], cancelled)],
                         [None, None])

    def test_the_runs_are_read_on_the_merge_commit_and_the_pull_requests_head(self):
        log = type('Done', (), {'returncode': 0, 'stdout': 'm1 p1 h1\nm2 p2 h2\n'})()
        paths = []

        def api(path):
            paths.append(path)
            return {'check_runs': [check(len(paths), 'tower/gate', f'2026-11-19T0{len(paths)}:00:00Z',
                                         f'2026-11-19T0{len(paths)}:00:40Z')]}
        found = runs.fetch(self.root, 'tower-gate', repo='o/r', api=api, run=lambda *a, **k: log)
        self.assertEqual(paths, [f'repos/o/r/commits/{sha}/check-runs?per_page=100' for sha in ('m1', 'h1', 'm2', 'h2')])
        self.assertEqual([(item['event'], item['seconds']) for item in found],
                         [('pull_request', 40), ('merge_group', 40), ('pull_request', 40), ('merge_group', 40)])
        self.assertFalse(any('/actions/' in path for path in paths))

    def test_an_api_that_refuses_or_an_offline_session_reads_nothing(self):
        log = type('Done', (), {'returncode': 0, 'stdout': 'm1 p1 h1\n'})()

        def refused(path):
            raise RuntimeError('gh api: 403')
        self.assertIsNone(runs.fetch(self.root, 'tower-gate', repo='o/r', api=refused, run=lambda *a, **k: log))
        with unittest.mock.patch.dict('os.environ', {'TOWER_OFFLINE': '1'}):
            self.assertIsNone(runs.fetch(self.root, 'tower-gate', repo='o/r', api=refused, run=lambda *a, **k: log))
        self.assertIsNone(runs.fetch(self.root, 'deploy', repo='o/r', api=refused, run=lambda *a, **k: log))

    def test_a_day_old_snapshot_is_rebuilt_with_the_newest_runs(self):
        found = [{'id': i, 'event': 'pull_request', 'conclusion': 'success', 'started': '2026-11-19T10:00:00Z', 'seconds': 40}
                 for i in range(runs.KEEP + 3)]
        made = runs.refresh(self.root, 'tower-gate', now=runs.stamp('2026-11-19T12:00:00Z'), reader=self.reader(found))
        self.assertEqual((made['at'], len(made['runs']), runs.read(self.root, 'tower-gate')['at']),
                         ('2026-11-19T12:00:00Z', runs.KEEP, '2026-11-19T12:00:00Z'))

    def test_a_fresh_snapshot_is_not_read_again(self):
        runs.refresh(self.root, 'tower-gate', now=runs.stamp('2026-11-17T20:00:00Z'), reader=self.reader([]))
        self.assertEqual(self.asked, [])

    def test_an_api_that_does_not_answer_keeps_the_recorded_snapshot(self):
        kept = runs.refresh(self.root, 'tower-gate', now=runs.stamp('2026-11-30T12:00:00Z'), reader=self.reader(None))
        self.assertEqual((self.asked, kept['at']), (['tower-gate'], '2026-11-17T12:00:00Z'))

    def test_the_measure_refreshes_only_the_snapshots_github_checks_hold(self):
        found = {name: {'type': 'VAL', 'body': {'measure': {'kind': 'run-durations', 'workflow': name}}}
                 for name in ('tower-gate', 'other')}
        renewed = {'at': '2026-11-19T12:00:00Z'}
        with unittest.mock.patch.object(runs, 'refresh', side_effect=lambda root, name: self.asked.append(name) or renewed):
            self.assertEqual((model.refresh_runs(found, self.root), self.asked), (['tower-gate'], ['tower-gate']))
        with unittest.mock.patch.object(runs, 'refresh', return_value=runs.read(self.root, 'tower-gate')):
            self.assertEqual(model.refresh_runs(found, self.root), [])


if __name__ == '__main__':
    unittest.main()
