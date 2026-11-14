"""The regression verdict of the performance budgets: one hermetic test per refusal (B1, D-069 item 14)."""
from datetime import timedelta
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
import budgets  # noqa: E402
from test_budgets import BASE, F, log, settings  # noqa: E402


def conf(**extra):
    return settings(**dict({'budgets.min_samples': F['min_samples'], 'budgets.window_samples': F['check_window_samples'],
                            'budgets.regression_tolerance_percent': F['tolerance_percent']}, **extra))


def base(*items):
    return {'version': 1, 'percentile': F['percentile'], 'window_samples': F['check_window_samples'],
            'metrics': [{'metric': m, 'subject': s, 'value': v, 'samples': F['samples'], 'evidence': 'e'} for m, s, v in items]}


class Verdict(unittest.TestCase):
    def one(self, events, document, **extra):
        results = budgets.verdicts(events, document, conf(**extra))
        self.assertEqual(len(results), 1)
        return results[0]

    def test_within_the_tolerance_is_ok(self):
        row = self.one(log(battery=F['within_ms']), base((budgets.BATTERY, 'engine-slo', F['baseline_s'])))
        self.assertEqual((row['state'], row['value']), ('ok', F['within_p95_s']))

    def test_beyond_the_tolerance_is_a_regression_and_fails(self):
        results = budgets.verdicts(log(battery=F['regressed_ms']), base((budgets.BATTERY, 'engine-slo', F['baseline_s'])), conf())
        self.assertEqual(results[0]['state'], 'regressed')
        self.assertEqual(budgets.failing(results), results)

    def test_a_tighter_tolerance_refuses_what_a_looser_one_accepts(self):
        events, document = log(battery=F['edge_ms']), base((budgets.BATTERY, 'engine-slo', F['baseline_s']))
        self.assertEqual(self.one(events, document)['state'], 'ok')
        self.assertEqual(self.one(events, document, **{'budgets.regression_tolerance_percent': F['tight_tolerance_percent']})['state'], 'regressed')

    def test_beyond_the_battery_entry_is_over_limit_even_without_a_baseline(self):
        limit_ms = int(timedelta(seconds=BASE[budgets.BATTERY]) / timedelta(milliseconds=1))
        row = self.one(log(battery=[limit_ms + F['over_extra_ms']] * F['min_samples']), base())
        self.assertEqual((row['state'], row['limit']), ('over_limit', BASE[budgets.BATTERY]))

    def test_too_few_measurements_is_no_data_and_never_fails(self):
        results = budgets.verdicts(log(battery=F['huge_ms']), base((budgets.BATTERY, 'engine-slo', F['huge_baseline_s'])), conf())
        self.assertEqual([item['state'] for item in results], ['no_data'])
        self.assertEqual(budgets.failing(results), [])

    def test_an_empty_log_and_baseline_has_no_verdicts(self):
        self.assertEqual(budgets.verdicts([], base(), conf()), [])

    def test_a_missing_baseline_file_is_empty_not_guessed(self):
        self.assertEqual(budgets.load_baseline(conf(**{'budgets.baseline_path': 'config/baselines/none.json'}))['metrics'], [])

    def test_the_verdict_is_deterministic(self):
        events, document = log(battery=F['regressed_ms']), base((budgets.BATTERY, 'engine-slo', F['baseline_s']))
        self.assertEqual(budgets.verdicts(events, document, conf()), budgets.verdicts(list(reversed(events)), document, conf()))


if __name__ == '__main__':
    unittest.main()
