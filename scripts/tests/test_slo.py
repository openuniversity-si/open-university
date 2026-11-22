"""SLO registry entries, the slo.breached contract, the reader and the dashboard (O1, D-069 item 6). Hermetic."""
# Verifies: REQ-slo-budgets-slo-gate-failure-rate-max-percent, REQ-slo-budgets-slo-merged-prs-per-hour-min
from datetime import datetime, timedelta, timezone
import copy
import functools
import json
from pathlib import Path
import subprocess
import sys
import unittest
import unittest.mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402
import slo  # noqa: E402

REPO = 'openuniversity-si/open-university'
START = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
REGISTRY = json.loads((ROOT / 'config' / 'registry' / 'slo.json').read_text())['properties']
SLOS = ('slo.train_queue_time_p95_s', 'slo.merged_prs_per_hour_min',
        'slo.gate_failure_rate_max_percent')


class Registry(unittest.TestCase):
    def test_every_slo_is_declared_with_unit_and_reader(self):
        for name in SLOS:
            entry = REGISTRY[name]
            self.assertIn('x-unit', entry, name)
            self.assertTrue(entry['x-readers'], name)
            self.assertFalse(entry.get('deprecated'), name)
            self.assertEqual(config.get(name), entry['default'], name)

    def test_retired_tier1_slo_is_deprecated_and_budgets_tighten_only_unchanged(self):
        # D-351: slo.gate_tier1_p95_s (Origin-era local tier-1) is retired via registry deprecation, not loosened.
        self.assertTrue(REGISTRY['slo.gate_tier1_p95_s'].get('deprecated'))
        self.assertNotIn('slo.gate_tier1_p95_s', slo.NAMES)
        self.assertTrue(config.get('budgets.tighten_only'))

    def test_throughput_entry_is_the_plan_criterion(self):
        # plan v3 §9.2: the last 42 pr.merged within 60 minutes, held for at least 3 hours
        self.assertEqual((config.get('slo.merged_prs_per_hour_min'), config.get('slo.merged_window_s'),
                          config.get('slo.merged_hold_s')), (42, 3600, 10800))

    def test_no_value_has_a_second_name(self):
        defaults = [(entry['default'], entry['x-unit']) for name, entry in REGISTRY.items()
                    if not entry.get('deprecated') and entry['x-unit'] in ('s', 'percent')]
        self.assertEqual(len(defaults), len(set(defaults)))


class Clock:
    """Injected clock the test moves by hand."""

    def __init__(self):
        self.moment = START

    def now(self):
        return self.moment


def sha(n):
    return f'{n:040x}'


def setUpModule():
    """Read each registry value once per process: config.get replays the registry and the change store on every call,
    and the fixtures below make thousands of calls through the port. The registry does not change during the run."""
    patch = unittest.mock.patch.object(config, 'get', functools.cache(config.get))
    patch.start()
    unittest.addModuleCleanup(patch.stop)


BUILT = {}  # fixture key -> envelopes: building one validates it against the schemas, so each log is built once


def make_log(spec):
    """Envelopes from (seconds since START, type, pr, extra payload) tuples, built through the port (memoized)."""
    key = json.dumps(spec, sort_keys=True)
    if key not in BUILT:
        BUILT[key] = build_log(spec)
    return copy.deepcopy(BUILT[key])


def build_log(spec):
    clock = Clock()
    port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), clock, 'fixture', 'run-1')
    events = []
    for offset, kind, pr, extra in spec:
        clock.moment = START + timedelta(seconds=offset)
        payload = dict(forge_events.subject(REPO, pr, sha(pr)), **extra)
        events.append(port.build(kind, payload))
    return events


def gate(offset, pr, seconds, passed=True):
    return (offset, 'gate.passed' if passed else 'gate.failed', pr,
            {'tier': 1, 'plan': 'dev', 'missing_stages': [], 'input_hash': 'd' * 64,
             'stages': [{'name': 'lint', 'result': 'PASS' if passed else 'FAIL', 'duration_ms': int(seconds * 1000),
                         'class': None if passed else 'code'}]})


def ready(offset, pr):
    return (offset, 'pr.ready', pr, {'lane_id': 'lane-a', 'evidence': 'e' * 64})


def merged(offset, pr):
    return (offset, 'pr.merged', pr, {'merge_sha': sha(pr + 9000), 'batch_id': None})


BASE = slo.settings()  # the registry read once: each config.get replays the registry and the change store


def conf(**overrides):
    return dict(BASE, **{'slo.min_samples': 3}, **overrides)


def by_name(results):
    return {item['slo']: item for item in results}

class Fold(unittest.TestCase):
    def test_percentile_is_nearest_rank(self):
        self.assertEqual(slo.percentile(list(range(1, 101)), 95), 95)
        self.assertEqual(slo.percentile([3, 1, 2], 95), 3)
        self.assertEqual(slo.percentile([7], 50), 7)

    def test_the_slos_judge_the_whole_sample_so_one_slow_value_breaches(self):
        """D-336, D-337: slo.percentile is 100, the maximum; one slow verdict among many decides the window."""
        self.assertEqual(config.get('slo.percentile'), 100)
        self.assertEqual(slo.percentile(list(range(1, 1001)), 100), 1000)
        limit = config.get('slo.train_queue_time_p95_s')
        count = config.get('slo.min_samples')
        spec = []
        for pr in range(1, count + 1):
            spec += [ready(pr, pr), merged(pr + limit / (1 + 1), pr)]
        tail = count + 1
        slow = limit * (1 + 1 + 1)
        spec += [ready(tail, tail), merged(tail + slow, tail)]
        item = by_name(slo.evaluate(make_log(spec), conf(**{'slo.percentile': config.get('slo.percentile')})))[
            'slo.train_queue_time_p95_s']
        self.assertEqual((item['state'], item['value']), ('breached', slow))

    def test_retired_tier1_slo_is_not_evaluated_and_never_breaches(self):
        # D-351: tier-1 duration verdicts do not generate a false breach for retired slo.gate_tier1_p95_s.
        limit = config.get('gate.tier1_target_s')
        count = config.get('slo.min_samples')
        log = make_log([gate(i, i + 1, limit + limit) for i in range(count)])
        results = by_name(slo.evaluate(log, conf()))
        self.assertNotIn('slo.gate_tier1_p95_s', results)
        self.assertEqual(results['slo.gate_failure_rate_max_percent']['state'], 'ok')

    def test_queue_time_within_the_entry_is_ok(self):
        count = config.get('slo.min_samples')
        spec = []
        for pr in range(1, count + 1):
            spec += [ready(pr, pr), merged(pr + 1, pr)]
        self.assertEqual(by_name(slo.evaluate(make_log(spec), conf()))['slo.train_queue_time_p95_s']['state'], 'ok')

    def test_fewer_samples_than_the_floor_report_no_data(self):
        log = make_log([gate(i, i + 1, 99, passed=False) for i in range(2)])
        results = by_name(slo.evaluate(log, conf()))
        self.assertNotIn('slo.gate_tier1_p95_s', results)
        self.assertEqual(results['slo.gate_failure_rate_max_percent']['state'], 'no_data')

    def test_failure_rate_counts_failed_tier1_verdicts(self):
        log = make_log([gate(i, i + 1, 1, passed=i % 2 == 0) for i in range(10)])
        item = by_name(slo.evaluate(log, conf()))['slo.gate_failure_rate_max_percent']
        self.assertEqual((item['state'], item['value']), ('breached', 50.0))

    def test_other_gate_plans_are_not_tier1(self):
        spec = [gate(i, i + 1, 1) for i in range(5)]
        spec[0][3]['tier'] = None
        self.assertEqual(len(slo.fold(make_log(spec))['tier1']), 4)

    def test_queue_time_runs_from_pr_ready_to_pr_merged_of_the_same_head(self):
        limit = config.get('slo.train_queue_time_p95_s')
        spec = []
        for pr in range(1, 6):
            spec += [ready(pr * 10, pr), merged(pr * 10 + limit * 2, pr)]
        item = by_name(slo.evaluate(make_log(spec), conf()))['slo.train_queue_time_p95_s']
        self.assertEqual((item['state'], item['value']), ('breached', limit * 2))

    def test_a_merge_without_a_ready_is_not_a_queue_sample(self):
        self.assertEqual(slo.fold(make_log([merged(5, 1)]))['queue'], [])

    SCALE = {'slo.merged_window_s': 300, 'slo.merged_hold_s': 900, 'slo.merged_prs_per_hour_min': 5}

    def pace(self, every, seconds):
        spec = [merged(i * every, i + 1) for i in range(int(seconds // every))]
        return by_name(slo.evaluate(make_log(spec), conf(**self.SCALE)))['slo.merged_prs_per_hour_min']

    def test_merge_pace_holding_the_entry_for_the_hold_is_ok(self):
        self.assertEqual(self.pace(40, 1500)['state'], 'ok')

    def test_merge_pace_below_the_entry_breaches(self):
        item = self.pace(100, 1500)
        self.assertEqual((item['state'], item['value']), ('breached', 4))

    def test_merge_pace_needs_the_log_to_cover_the_hold(self):
        self.assertEqual(self.pace(30, 600)['state'], 'no_data')

    def test_replay_is_a_pure_function_of_the_log(self):
        spec = [gate(i * 3, i + 1, 2 + i % 7, passed=i % 5 != 0) for i in range(16)]
        spec += [ready(200 + i, 100 + i) for i in range(5)] + [merged(500 + i * 9, 100 + i) for i in range(5)]
        log = make_log(spec)
        expected = slo.evaluate(log, conf())
        self.assertEqual(slo.evaluate(list(reversed(log)), conf()), expected)
        self.assertEqual(slo.evaluate(log + log[:7], conf()), expected)

    def test_step_stats_fold_engine_step_measured(self):
        spec = [(i, 'engine.step.measured', i + 1, {'step': 'train:tier2', 'duration_ms': 100 * (i + 1),
                                                    'tokens_in': 0, 'tokens_out': 0, 'model': None,
                                                    'provider': None, 'result': 'fail' if i == 3 else 'ok',
                                                    'retries': 0}) for i in range(4)]
        stats = slo.step_stats(make_log(spec), 95)['train:tier2']
        self.assertEqual((stats['runs'], stats['failed'], stats['duration_ms']), (4, 1, 400))


class Emission(unittest.TestCase):
    def breaching(self):
        adapter = forge_events.MemoryAdapter()
        port = forge_events.ForgeEvents(adapter, Clock(), 'fixture', 'run-1')
        port.publish(make_log([gate(i, i + 1, 999, passed=False) for i in range(4)]))
        return adapter

    def test_a_breach_emits_slo_breached_on_the_repository_channel_and_a_rerun_is_a_noop(self):
        adapter = self.breaching()
        overrides = {'slo.min_samples': 3}
        slo.run(adapter, Clock(), REPO, range(1, 5), dict(BASE, **overrides))
        repository = forge_events.ForgeEvents(adapter, Clock(), 'reader', 'x').read(REPO)
        breached = {e['payload']['slo']: e['payload'] for e in repository if e['type'] == 'slo.breached'}
        self.assertEqual(set(breached), {'slo.gate_failure_rate_max_percent'})
        self.assertNotIn('slo.gate_tier1_p95_s', breached)
        self.assertEqual(breached['slo.gate_failure_rate_max_percent']['value'], 100.0)
        appends = adapter.appends
        slo.run(adapter, Clock(), REPO, range(1, 5), dict(BASE, **overrides))
        self.assertEqual(adapter.appends, appends)

    def test_the_run_is_measured_by_the_reader_itself(self):
        adapter = self.breaching()
        slo.run(adapter, Clock(), REPO, range(1, 5), conf())
        steps = [e['payload'] for e in forge_events.ForgeEvents(adapter, Clock(), 'r', 'x').read(REPO)
                 if e['type'] == 'engine.step.measured']
        self.assertEqual([s['step'] for s in steps], [config.get('slo.step')])
        self.assertEqual(steps[0]['result'], 'blocked')

    def test_nothing_is_emitted_when_every_slo_holds(self):
        adapter = forge_events.MemoryAdapter()
        forge_events.ForgeEvents(adapter, Clock(), 'fixture', 'run-1').publish(make_log([gate(i, i + 1, 1) for i in range(4)]))
        slo.run(adapter, Clock(), REPO, range(1, 5), conf())
        events = forge_events.ForgeEvents(adapter, Clock(), 'r', 'x').read(REPO)
        self.assertFalse([e for e in events if e['type'] == 'slo.breached'])

    def test_an_empty_log_emits_nothing(self):
        adapter = forge_events.MemoryAdapter()
        slo.run(adapter, Clock(), REPO)
        self.assertEqual(adapter.appends, 0)

    def test_collect_follows_the_prs_a_batch_names(self):
        adapter = forge_events.MemoryAdapter()
        port = forge_events.ForgeEvents(adapter, Clock(), 'fixture', 'run-1')
        port.publish(make_log([gate(0, 7, 1)]))
        port.emit('train.batch.started', dict(forge_events.subject(REPO, None, sha(5)), batch_id='b1', prs=[7]))
        self.assertEqual([e['type'] for e in slo.collect(adapter, REPO)].count('gate.passed'), 1)


class Dashboard(unittest.TestCase):
    def adapter(self):
        adapter = forge_events.MemoryAdapter()
        forge_events.ForgeEvents(adapter, Clock(), 'fixture', 'run-1').publish(
            make_log([gate(i, i + 1, 999, passed=False) for i in range(4)]))
        return adapter

    def test_render_shows_each_slo_with_value_entry_and_state(self):
        events = make_log([gate(i, i + 1, 999, passed=False) for i in range(4)])
        values = conf()
        text = slo.render(slo.evaluate(events, values), slo.step_stats(events, 95), slo.fold(events)['span'], values)
        for name in SLOS:
            self.assertIn(f'`{name}`', text)
        self.assertNotIn('`slo.gate_tier1_p95_s`', text)
        self.assertIn('| `slo.gate_failure_rate_max_percent` | 100 | <= ', text)
        self.assertIn('breached', text)
        self.assertIn('no_data', text)

    def test_dashboard_is_deterministic_and_written_to_a_gitignored_path(self):
        out = '.gate/dashboard/test-slo.md'
        first = slo.dashboard(self.adapter(), REPO, range(1, 5), {'slo.min_samples': 3}, out).read_text()
        second = slo.dashboard(self.adapter(), REPO, range(1, 5), {'slo.min_samples': 3}, out).read_text()
        self.assertEqual(first, second)
        (ROOT / out).unlink()

    def test_dashboard_refuses_a_path_that_git_would_track(self):
        with self.assertRaises(SystemExit):
            slo.dashboard(self.adapter(), REPO, range(1, 5), out='docs/slo-dashboard.md')
        self.assertFalse((ROOT / 'docs' / 'slo-dashboard.md').exists())

    def test_the_configured_dashboard_path_is_gitignored(self):
        path = ROOT / config.get('slo.dashboard_path')
        self.assertEqual(subprocess.run(['git', '-C', str(ROOT), 'check-ignore', '-q', str(path)]).returncode, 0)


class Expectation(unittest.TestCase):
    """GX-25: the ETA per stage from the ledger, the local history, then the registered fallback (numbers: fixtures/gate-eta.json)."""

    DATA = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'gate-eta.json').read_text())['expected_seconds']

    def steps(self, stage, millis):
        prefix = config.get('forge-events.gate_step_prefix')
        return make_log([(i, 'engine.step.measured', i + 1, {'step': prefix + stage, 'duration_ms': ms, 'tokens_in': 0,
                                                             'tokens_out': 0, 'model': None, 'provider': None,
                                                             'result': 'ok', 'retries': 0}) for i, ms in enumerate(millis)])

    def test_ledger_quantile_over_the_newest_window(self):
        data = self.DATA
        log = self.steps('lint', data['lint_ms'])
        quantile = config.get('gate-eta.eta_quantile')
        got = slo.expected_seconds(log, ['lint'], quantile, data['window'], data['fallback_s'])
        self.assertEqual(got['lint'], {'seconds': data['p50_s'], 'source': 'ledger'})  # the oldest (slowest) run is outside the window
        high = slo.expected_seconds(log, ['lint'], data['quantile_high'], data['window'], data['fallback_s'])
        self.assertEqual(high['lint']['seconds'], data['p90_s'])

    def test_local_history_then_registered_fallback_on_an_empty_ledger(self):
        data = self.DATA
        got = slo.expected_seconds([], ['lint', 'unit'], config.get('gate-eta.eta_quantile'), config.get('gate-eta.eta_history_events'),
                                   data['fallback_s'], local={'lint': data['local_s']})
        self.assertEqual(got, {'lint': {'seconds': data['local_s'], 'source': 'local'},
                               'unit': {'seconds': float(data['fallback_s']), 'source': 'fallback'}})

    def test_other_stages_and_other_steps_do_not_leak(self):
        data = self.DATA
        log = self.steps('lint', data['lint_ms'][:1]) + self.steps('unit', [data['unit_ms']])
        got = slo.expected_seconds(log, ['unit'], config.get('gate-eta.eta_quantile'), config.get('gate-eta.eta_history_events'),
                                   data['fallback_s'])
        self.assertEqual(got['unit']['seconds'], data['unit_s'])


class Contract(unittest.TestCase):
    def test_slo_breached_is_a_locked_event_with_a_replay_safe_key(self):
        schemas = event_contracts.registry()
        self.assertIn('slo.breached', event_contracts.catalog(schemas.directory))
        self.assertEqual(event_contracts.check(), [])
        key = schemas.load('slo.breached.v1.json')['x-natural-key']
        self.assertIn('/payload/evidence', key)


if __name__ == '__main__':
    unittest.main()
