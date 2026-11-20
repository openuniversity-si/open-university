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

    def test_a_fresh_at_stamp_over_old_runs_is_still_stale(self):
        old = [run(i, '2026-11-01T10:00:00Z', f'2026-11-01T10:00:{30 + i:02d}Z') for i in range(len('abc'))]
        (self.root / runs.FOLDER / 'tower-gate.json').write_text(
            json.dumps(runs.snapshot('tower-gate', old, now='2026-11-19T12:00:00Z')))
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-19')[1], False,
                         'freshness judges the newest run date too, not only the query timestamp')
        mixed = old[:-1] + [run(len('abc'), '2026-11-18T10:00:00Z', '2026-11-18T10:00:35Z')]
        (self.root / runs.FOLDER / 'tower-gate.json').write_text(
            json.dumps(runs.snapshot('tower-gate', mixed, now='2026-11-19T12:00:00Z')))
        self.assertEqual(model.measured(self.body, {}, self.root, '2026-11-19')[1], True)

    def test_val_deploy_1s_reads_the_slowest_landing_to_live_of_the_snapshot(self):
        # REQ-deploy-1s counts a code-only merge's landing to live (QUEUE-RELOAD), the snapshot scripts/deploy status
        # records (deploy.record_live), not the builds' seconds (deploy.json): the same reader as the gate's, on the whole
        # sample, its maximum (D-337)
        body = json.loads((ROOT / 'config/validation/VAL-deploy-1s.json').read_text())
        self.assertEqual(body['measure']['workflow'], 'deploy-live')
        builds = [{'id': f'm{i}', 'event': 'swap', 'conclusion': 'success', 'started': '2026-11-19T01:00:00Z',
                   'seconds': seconds} for i, seconds in enumerate((26, 17, 9))]
        (self.root / runs.FOLDER / 'deploy-live.json').write_text(json.dumps({'workflow': 'deploy-live',
                                                                              'at': '2026-11-19T02:00:00Z', 'runs': builds}))
        slow = [dict(builds[0], seconds=sum(run['seconds'] for run in builds))]  # a build's seconds: not what it reads
        (self.root / runs.FOLDER / 'deploy.json').write_text(json.dumps({'workflow': 'deploy', 'at': '2026-11-19T02:00:00Z',
                                                                         'runs': slow}))
        slowest = max(run['seconds'] for run in builds)
        self.assertEqual(model.measured(body, {}, self.root, '2026-11-19'), (slowest, False))  # fewer than min_runs
        body['measure']['min_runs'] = len(builds)
        self.assertEqual(model.measured(body, {}, self.root, '2026-11-19'), (slowest, True))
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


def at(minutes):
    return f'2026-11-19T{minutes // 60:02d}:{minutes % 60:02d}:00Z'


class Slo(unittest.TestCase):
    """The four SLOs of config/registry/slo.json read from GitHub (never the Actions API, never the forge event log):
    merge times, the merge queue's wait and the tower/gate runs of the commits the pull requests pushed."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='runs-slo-'))
        self.addCleanup(shutil.rmtree, self.root)

    def api(self, paths):
        timelines = {
            7: [{'event': 'committed', 'sha': 'a', 'committer': {'date': at(1)}},
                {'event': 'committed', 'sha': 'b', 'committer': {'date': at(5)}},
                {'event': 'added_to_merge_queue', 'created_at': at(6)},
                {'event': 'removed_from_merge_queue', 'created_at': at(7)},
                {'event': 'added_to_merge_queue', 'created_at': at(8)},
                {'event': 'merged', 'created_at': at(10)}],
            8: [{'event': 'committed', 'sha': 'c', 'committer': {'date': at(3)}}]}
        checks = {'a': [check(1, 'tower/gate', at(2), '2026-11-19T00:02:20Z', 'failure')],
                  'b': [check(2, 'gate part (main)', at(5), at(5)), check(3, 'tower/gate', at(6), '2026-11-19T00:06:30Z')],
                  'c': [check(4, 'tower/gate', at(4), at(4), 'cancelled')]}

        def answer(path):
            paths.append(path)
            if '/pulls?state=closed' in path:
                return [{'number': 7, 'merged_at': at(10)}, {'number': 6, 'merged_at': None}]
            if '/pulls?state=all' in path:
                return [{'number': 8}, {'number': 7}]
            if '/timeline' in path:
                return timelines[int(path.split('/issues/')[1].split('/')[0])]
            return {'check_runs': checks[path.split('/commits/')[1].split('/')[0]]}
        return answer

    def test_the_samples_are_the_merges_the_queue_wait_and_each_pushed_commits_gate(self):
        paths = []
        found = runs.slo_fetch(repo='o/r', api=self.api(paths))
        self.assertEqual(found['merges'], [{'pr': 7, 'at': at(10)}])
        self.assertEqual(found['queue'], [{'pr': 7, 'at': at(10), 'seconds': 120}])  # the last enqueue to the merge
        self.assertEqual([(item['sha'], item['passed'], item['seconds']) for item in found['verdicts']],
                         [('b', True, 90), ('a', False, 20)])  # c's run was cancelled: superseded, not judged
        self.assertFalse(any('/actions/' in path for path in paths))

    def test_an_api_that_refuses_or_an_offline_session_reads_nothing(self):
        def refused(path):
            raise RuntimeError('gh api: 403')
        self.assertIsNone(runs.slo_fetch(repo='o/r', api=refused))
        with unittest.mock.patch.dict('os.environ', {'TOWER_OFFLINE': '1'}):
            self.assertIsNone(runs.slo_fetch(repo='o/r', api=self.api([])))

    def test_a_day_old_snapshot_is_rebuilt_and_a_fresh_one_is_kept(self):
        asked = []
        samples = {'merges': [], 'queue': [], 'verdicts': []}
        made = runs.slo_refresh(self.root, now=runs.stamp('2026-11-19T12:00:00Z'),
                                reader=lambda: asked.append(1) or samples)
        runs.slo_refresh(self.root, now=runs.stamp('2026-11-19T20:00:00Z'), reader=lambda: asked.append(2) or samples)
        kept = runs.slo_refresh(self.root, now=runs.stamp('2026-11-21T12:00:00Z'), reader=lambda: asked.append(3))
        self.assertEqual((asked, made['at'], kept['at'], runs.read_slo(self.root)['at']),
                         ([1, 3], '2026-11-19T12:00:00Z', '2026-11-19T12:00:00Z', '2026-11-19T12:00:00Z'))

    def test_the_model_folds_the_snapshot_with_the_slo_reader_and_judges_its_age(self):
        verdicts = [{'pr': i, 'sha': str(i), 'id': i, 'at': at(i), 'passed': i % 4 != 0, 'seconds': 5 + i}
                    for i in range(20)]
        merges = [{'pr': i, 'at': at(i * 15)} for i in range(17)]  # one every 15 minutes over four hours
        queue = [{'pr': i, 'at': at(i * 12), 'seconds': 60 * (i + 1)} for i in range(20)]
        runs.slo_write(self.root, {'merges': merges, 'queue': queue, 'verdicts': verdicts}, runs.stamp(at(0)))
        registry = {'slo.merged_prs_per_hour_min': {'default': 4}, 'slo.min_samples': {'default': 20}}
        values = model.slo_values(self.root, registry, today='2026-11-20')
        self.assertEqual({name: (item['value'], item['state'], item['fresh']) for name, item in values.items()}, {
            'slo.gate_tier1_p95_s': (24, 'breached', True),  # the maximum (D-337); the limit is the smaller of 10 and its target
            'slo.train_queue_time_p95_s': (1200, 'breached', True),
            'slo.merged_prs_per_hour_min': (5, 'ok', True),  # five merges in every hour, ends included
            'slo.gate_failure_rate_max_percent': (25.0, 'breached', True)})
        stale = model.slo_values(self.root, registry, today='2026-11-25')
        self.assertFalse(any(item['fresh'] for item in stale.values()))
        self.assertEqual(model.slo_values(Path(tempfile.mkdtemp(dir=self.root)), registry), {})


class Verdicts(unittest.TestCase):
    """The full-suite's verdicts on main (model.derive_verdicts reads a test's pass state from them): the newest
    completed full-suite check run of each merge commit, read from GitHub's check runs (never the Actions API)."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='runs-verdicts-'))
        self.addCleanup(shutil.rmtree, self.root)
        self.log = type('Done', (), {'returncode': 0, 'stdout': 'm1 p1 h1\nm2 p2 h2\nm3 p3 h3\n'})()

    def test_each_merge_commit_gives_its_newest_completed_full_suite_run(self):
        paths = []
        checks = {'m1': [check(1, 'full-suite', at(1), at(4), 'failure'), check(2, 'full-suite', at(5), at(9)),
                         check(3, 'tower/gate', at(1), at(2))],
                  'm2': [check(4, 'full-suite', at(1), at(3), 'cancelled')],
                  'm3': [check(5, 'full-suite', at(1), at(2), 'failure')]}

        def api(path):
            paths.append(path)
            return {'check_runs': checks[path.split('/commits/')[1].split('/')[0]]}
        found = runs.verdicts_fetch(self.root, repo='o/r', api=api, run=lambda *a, **k: self.log)
        self.assertEqual(sorted(paths), [f'repos/o/r/commits/{sha}/check-runs?check_name=full-suite&per_page=100'
                                         for sha in ('m1', 'm2', 'm3')], 'the merge commits only, where the suite runs')
        self.assertEqual(found, [{'sha': 'm1', 'id': 2, 'conclusion': 'success', 'completed': at(9)},
                                 {'sha': 'm3', 'id': 5, 'conclusion': 'failure', 'completed': at(2)}])

    def test_an_api_that_refuses_or_an_offline_session_reads_nothing_and_a_fresh_snapshot_is_kept(self):
        def refused(path):
            raise RuntimeError('gh api: 403')
        self.assertIsNone(runs.verdicts_fetch(self.root, repo='o/r', api=refused, run=lambda *a, **k: self.log))
        with unittest.mock.patch.dict('os.environ', {'TOWER_OFFLINE': '1'}):
            self.assertIsNone(runs.verdicts_fetch(self.root, repo='o/r', api=refused, run=lambda *a, **k: self.log))
        asked, found = [], [{'sha': 'm1', 'id': 2, 'conclusion': 'success', 'completed': at(9)}]
        made = runs.verdicts_refresh(self.root, now=runs.stamp(at(10)), reader=lambda root: asked.append(1) or found)
        runs.verdicts_refresh(self.root, now=runs.stamp(at(20)), reader=lambda root: asked.append(2) or found)
        kept = runs.verdicts_refresh(self.root, now=runs.stamp('2026-11-21T00:00:00Z'), reader=lambda root: asked.append(3))
        self.assertEqual((asked, made['runs'], kept['at'], runs.read_verdicts(self.root)['check']),
                         ([1, 3], found, at(10), 'full-suite'))


if __name__ == '__main__':
    unittest.main()
