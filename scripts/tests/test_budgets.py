"""Performance budgets: registry entries, the measurements folded from the log, and the baseline (B1, D-069 item 14).
Hermetic: an in-memory adapter, an injected clock, explicit overrides; no network."""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import budgets  # noqa: E402
import config  # noqa: E402
import forge_events  # noqa: E402

REPO = 'openuniversity-si/open-university'
F = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'budgets.json').read_text())
START = datetime.fromisoformat(F['start'])
REGISTRY = json.loads((ROOT / 'config' / 'registry' / 'budgets.json').read_text())['properties']
SHA = hashlib.sha1(b'').hexdigest()
BASE = budgets.settings()  # one read of the registry store: config.get replays it on every call


def settings(**overrides):
    return dict(BASE, **overrides)


class Clock:
    def __init__(self):
        self.moment = START

    def now(self):
        self.moment += timedelta(seconds=1)
        return self.moment


def log(battery=(), other=(), unit='engine-slo'):
    """Events as the port stores them, built by hand (no validation, so no config reads): one battery step and one
    sub-step per entry of `battery` (ms), and one budget.measured of the train's REST calls per `other` value (a
    metric this tool does not budget)."""
    clock, step, events = Clock(), BASE['battery.unit_step'], []
    subject = forge_events.subject(REPO, None, SHA, (), unit)

    def event(kind, payload):
        events.append({'event_id': f'{kind}-{len(events)}', 'type': kind, 'version': 1, 'producer': 'test',
                       'correlation_id': 'c', 'occurred_at': forge_events.rfc3339(clock.now()), 'payload': payload})

    for ms in battery:
        event('engine.step.measured', forge_events.step_payload(subject, step, ms, 'ok'))
        event('engine.step.measured', forge_events.step_payload(subject, f'{step}.types', ms // F['substep_divisor'], 'ok'))
    for value in other:
        event('budget.measured', dict(subject, metric='train.rest_calls_per_run_max', value=value))
    return events


class Registry(unittest.TestCase):
    NAMES = ('budgets.regression_tolerance_percent', 'budgets.window_samples', 'budgets.min_samples',
             'budgets.baseline_path', 'budgets.percent_whole', 'budgets.tighten_only')

    def test_every_entry_is_declared_with_unit_description_and_reader(self):
        for name in self.NAMES:
            self.assertIn(name, REGISTRY)
            for field in ('x-unit', 'description', 'x-readers', 'default'):
                self.assertIn(field, REGISTRY[name], f'{name} {field}')

    def test_every_tighten_only_entry_names_a_live_entry(self):
        # budget_check skips a name the registry lacks, so a dangling entry would guard nothing.
        for item in REGISTRY['budgets.tighten_only']['default']:
            self.assertIsNotNone(config.get(item['name']), item['name'])
        self.assertIn(budgets.BATTERY, {item['name'] for item in REGISTRY['budgets.tighten_only']['default']})

    def test_the_battery_budget_has_one_name(self):
        self.assertFalse([name for name in REGISTRY if 'battery' in name or 'unit_time' in name])
        self.assertEqual(config.get(budgets.BATTERY), BASE[budgets.BATTERY])

    def test_settings_apply_overrides(self):
        self.assertEqual(budgets.settings({'budgets.min_samples': F['window_samples']})['budgets.min_samples'], F['window_samples'])
        self.assertEqual(BASE['budgets.min_samples'], config.get('budgets.min_samples'))


class Baseline(unittest.TestCase):
    def conf(self, **extra):
        return settings(**dict({'budgets.min_samples': F['min_samples'], 'budgets.window_samples': F['window_samples']}, **extra))

    def test_the_battery_baseline_is_the_p95_of_the_whole_battery_in_seconds(self):
        document = budgets.baseline(log(battery=F['rising_ms']), self.conf())
        self.assertEqual(document['metrics'], [{'metric': budgets.BATTERY, 'subject': 'engine-slo', 'value': F['rising_p95_s'],
                                                'samples': F['window_samples'], 'evidence': document['metrics'][0]['evidence']}])
        self.assertEqual(budgets.schema_errors(document), [])

    def test_only_the_newest_window_counts(self):
        document = budgets.baseline(log(battery=F['old_then_new_ms']), self.conf())
        self.assertEqual((document['metrics'][0]['value'], document['metrics'][0]['samples']), (F['newest_window_p95_s'], F['window_samples']))

    def test_fewer_than_min_samples_is_no_baseline_not_a_guess(self):
        self.assertEqual(budgets.baseline(log(battery=F['two_ms']), self.conf())['metrics'], [])
        self.assertEqual(budgets.baseline([], self.conf())['metrics'], [])

    def test_a_budget_measured_of_an_unbudgeted_metric_is_not_folded(self):
        self.assertEqual(budgets.baseline(log(other=F['other_values']), self.conf())['metrics'], [])
        self.assertEqual(budgets.baseline(log(battery=F['three_ms'], other=F['other_values']), self.conf()),
                         budgets.baseline(log(battery=F['three_ms']), self.conf()))

    def test_events_published_through_the_port_are_read_as_built_by_hand(self):
        import event_contracts
        adapter, clock = forge_events.MemoryAdapter(), Clock()
        schemas = event_contracts.registry()
        subject = forge_events.subject(REPO, None, SHA, (), 'engine-slo')
        for index, ms in enumerate(F['step_ms']):
            port = forge_events.ForgeEvents(adapter, clock, 'test', f'run-{index}', schemas)
            port.emit('engine.step.measured', forge_events.step_payload(subject, BASE['battery.unit_step'], ms, 'ok'))
        document = budgets.baseline(adapter.read(forge_events.Channel(REPO, None)), self.conf())
        self.assertEqual([(m['metric'], m['subject'], m['value']) for m in document['metrics']],
                         [(budgets.BATTERY, 'engine-slo', max(F['step_ms']) / F['rising_ms'][0])])

    def test_the_baseline_is_a_pure_function_of_the_log(self):
        events = log(battery=F['three_ms'], other=F['other_values'])
        self.assertEqual(budgets.baseline(events, self.conf()), budgets.baseline(list(reversed(events)), self.conf()))
        self.assertEqual(budgets.baseline(events, self.conf()), budgets.baseline(events + events, self.conf()))

    def test_write_validates_and_writes_the_registered_path(self):
        document = budgets.baseline(log(battery=F['three_ms']), self.conf())
        with tempfile.TemporaryDirectory() as root:
            path = budgets.write_baseline(document, self.conf(), root)
            self.assertEqual(path, Path(root) / config.get('budgets.baseline_path'))
            self.assertEqual(json.loads(path.read_text()), document)
            with self.assertRaises(SystemExit):
                budgets.write_baseline({'version': F['samples']}, self.conf(), root)


if __name__ == '__main__':
    unittest.main()
