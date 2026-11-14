"""GX-25: per-stage quantiles, the critical path and the ETA error of the gate timing report. Hermetic.
Every number lives in fixtures/gate-eta.json (D-068: a test writes no engine value)."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1].parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import gate_timing_report as timing  # noqa: E402

DATA = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'gate-eta.json').read_text())
PREFIX = config.get('forge-events.gate_step_prefix')


def step(index, stage, seconds):
    return {'event_id': f'step-{index}', 'type': 'engine.step.measured', 'occurred_at': f'2026-10-28T01:00:{index:02d}Z',
            'payload': {'step': PREFIX + stage, 'duration_ms': int(timedelta(seconds=seconds) / timedelta(milliseconds=1))}}


def lifecycle(kind, pr, minute, **extra):
    return {'event_id': f'{kind}-{pr}-{minute}', 'type': kind, 'occurred_at': f'2026-10-28T02:{minute:02d}:00Z',
            'payload': dict({'pr': pr, 'sha': hashlib.sha1(b'').hexdigest(), 'plan': 'dev'}, **extra)}


def gate_events(gate):
    events = [lifecycle('gate.started', gate['pr'], gate['start'], expected_wall_s=float(gate['expected']))]
    if gate['end'] is not None:
        events.append(lifecycle(gate['verdict'], gate['pr'], gate['end']))
    return events


class CriticalPath(unittest.TestCase):
    def test_cases(self):
        for case in DATA['critical_path']:
            seconds, path = timing.critical_path(case['durations'], case['needs'], case['names'])
            self.assertEqual(seconds, case['seconds'], case)
            if case['path']:
                self.assertEqual(path, case['path'], case)

    def test_longest_path_not_the_sum(self):
        case = DATA['critical_path'][0]
        self.assertLess(case['seconds'], sum(case['durations'].values()))


class Quantiles(unittest.TestCase):
    def test_registry_default_labels(self):
        self.assertEqual(list(timing.quantiles()), DATA['quantiles']['labels'])

    def test_nearest_rank(self):
        quantile = DATA['quantiles']
        self.assertEqual(timing.percentile(quantile['samples'], quantile['fraction']), quantile['value'])
        self.assertIsNone(timing.percentile([], quantile['fraction']))


class EtaError(unittest.TestCase):
    def test_error_is_wall_minus_expected_for_the_newest_gates(self):
        events = [event for gate in DATA['eta']['gates'] for event in gate_events(gate)]  # the last gate has no verdict: no row
        rows = timing.eta_errors(events, len(DATA['eta']['gates']))
        self.assertEqual([[row['pr'], row['error_s']] for row in rows], DATA['eta']['errors'])
        self.assertEqual([row['pr'] for row in timing.eta_errors(events, len(DATA['eta']['newest_only']))], DATA['eta']['newest_only'])

    def test_report_summarises_stage_quantiles_and_the_error(self):
        case = DATA['report']
        events = [step(index, 'lint', seconds) for index, seconds in enumerate(case['lint_s'])]
        events += [step(len(events), 'unit', case['unit_s'])] + gate_events(case['gate'])
        data = timing.report(timing.stage_samples(events), timing.eta_errors(events, len(events)), {'unit': ['lint']})
        self.assertEqual([data['stages']['lint']['p50'], data['stages']['lint']['p90']], case['lint'])
        self.assertEqual((data['critical_path'], data['critical_path_s']), (case['path'], case['path_s']))
        self.assertEqual(data['eta']['mean_abs_error_s'], case['mean_abs_error_s'])


class Cli(unittest.TestCase):
    def test_events_file_prints_quantiles_and_eta_error(self):
        case = DATA['cli']
        events = [step(index, 'lint', seconds) for index, seconds in enumerate(case['lint_s'])] + gate_events(case['gate'])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'events.json'
            path.write_text(json.dumps(events))
            done = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'lib' / 'gate_timing_report.py'), '--events', str(path)],
                                  capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        for line in case['lines']:
            self.assertIn(line, done.stdout)


if __name__ == '__main__':
    unittest.main()
