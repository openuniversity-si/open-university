"""The registry check that refuses a looser budget and a rewritten-upward baseline (B1, D-069 item 14). Hermetic: a
temporary git repository per case, no network."""
# Verifies: REQ-slo-budgets-budgets-pr-commits-min, REQ-slo-budgets-budgets-pr-commits-max, REQ-slo-budgets-budgets-regression-tolerance-percent, REQ-slo-budgets-budgets-tighten-only
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
F = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'budgets.json').read_text())
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import budget_check  # noqa: E402
import budgets  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

REGISTRY = ROOT / 'config' / 'registry'
PIN = ('-c', 'user.name=t', '-c', 'user.email=t@example.test', '-c', 'commit.gpgsign=false')


def git(root, *args):
    subprocess.run(['git', *PIN, '-C', str(root), *args], check=True, capture_output=True)


class Repo:
    """A repository with the real registry and decisions committed as the base, then edited on top."""

    def __enter__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        fixture_copy.registry(self.root)
        shutil.copytree(ROOT / 'contracts' / 'budgets', self.root / 'contracts' / 'budgets')
        (self.root / 'docs' / 'domain').mkdir(parents=True)
        (self.root / 'docs' / 'domain' / 'DECISIONS.md').write_text('| D-069 | x |\n| D-070 | y |\n', encoding='utf-8')
        git(self.root, 'init', '-q', '-b', 'main')
        git(self.root, 'add', '-A')
        git(self.root, 'commit', '-q', '-m', 'base')
        return self

    def __exit__(self, *exc):
        self.dir.cleanup()

    def entry(self, owner, name, **changes):
        path = self.root / 'config' / 'registry' / f'{owner}.json'
        document = json.loads(path.read_text(encoding='utf-8'))
        document['properties'][name].update(changes)
        path.write_text(json.dumps(document, indent=True) + '\n', encoding='utf-8')

    def baseline(self, *items, commit=False):
        path = self.root / 'config' / 'baselines' / 'budgets.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {'version': 1, 'percentile': F['percentile'], 'window_samples': F['window_samples'],
                    'metrics': [{'metric': m, 'subject': s, 'value': v, 'samples': F['samples'], 'evidence': 'e'} for m, s, v in items]}
        path.write_text(json.dumps(document), encoding='utf-8')
        if commit:
            git(self.root, 'add', '-A')
            git(self.root, 'commit', '-q', '-m', 'baseline')

    def errors(self, base='HEAD'):
        return budget_check.check(self.root, base)[0]


class Looser(unittest.TestCase):
    def test_the_unchanged_registry_passes(self):
        with Repo() as repo:
            self.assertEqual(repo.errors(), [])

    def test_a_larger_max_budget_is_refused(self):
        # The admin API, web bundle and page latency budgets left with Open University (OU-DECOUPLE F4 (D-111),
        # VAZÃO F44); every remaining tighten-only max is still exercised here.
        for owner, name in (('battery', 'battery.unit_time_limit'), ('budgets', 'budgets.regression_tolerance_percent')):
            with Repo() as repo, self.subTest(name):
                value = json.loads((repo.root / 'config' / 'registry' / f'{owner}.json').read_text())['properties'][name]['default']
                repo.entry(owner, name, default=value + 1)
                errors = repo.errors()
                self.assertEqual(len(errors), 1)
                self.assertIn('looser', errors[0])
                self.assertIn(name, errors[0])

    def test_a_smaller_budget_is_a_tightening_and_needs_nothing(self):
        with Repo() as repo:
            repo.entry('battery', 'battery.unit_time_limit', default=F['tightened_limit'])
            self.assertEqual(repo.errors(), [])

    def test_a_decision_recorded_in_decisions_allows_the_loosening(self):
        with Repo() as repo:
            repo.entry('battery', 'battery.unit_time_limit', default=F['loosened_limit'], **{'x-source': 'D-065 (4); D-069 item 14; D-070'})
            self.assertEqual(repo.errors(), [])

    def test_a_decision_that_is_not_recorded_or_already_cited_does_not_count(self):
        with Repo() as repo:
            repo.entry('battery', 'battery.unit_time_limit', default=F['loosened_limit'], **{'x-source': 'D-065 (4); D-069 item 14; D-999'})
            self.assertEqual(len(repo.errors()), 1)
        with Repo() as repo:
            repo.entry('battery', 'battery.unit_time_limit', default=F['loosened_limit'])
            self.assertEqual(len(repo.errors()), 1)

    def test_a_min_budget_may_not_shrink(self):
        with Repo() as repo:
            entries = json.loads((repo.root / 'config' / 'registry' / 'budgets.json').read_text())['properties']
            tighten = copy.deepcopy(entries['budgets.tighten_only']['default']) + [{'name': 'budgets.pr_commits_min', 'bound': 'min'}]
            repo.entry('budgets', 'budgets.tighten_only', default=tighten)
            current = entries['budgets.pr_commits_min']['default']
            repo.entry('budgets', 'budgets.pr_commits_min', default=current + 1, **{'x-source': 'D-022, D-025'})
            git(repo.root, 'add', '-A')
            git(repo.root, 'commit', '-q', '-m', 'list min')
            repo.entry('budgets', 'budgets.pr_commits_min', default=1)
            self.assertEqual(len(repo.errors()), 1)


class Baseline(unittest.TestCase):
    def test_a_valid_baseline_passes(self):
        with Repo() as repo:
            repo.baseline((budgets.BATTERY, 'engine-slo', F['baseline_s']))
            self.assertEqual(repo.errors(), [])

    def test_a_baseline_that_breaks_its_schema_is_refused(self):
        with Repo() as repo:
            repo.baseline((budgets.BATTERY, 'engine-slo', -1))
            self.assertTrue(any('baseline.v1' in e or 'budgets.json' in e for e in repo.errors()))

    def test_a_metric_that_is_not_budgeted_is_refused(self):
        with Repo() as repo:
            repo.baseline(('budgets.pr_commits_max', 'x', F['baseline_s']))
            self.assertTrue(any('not budgeted' in e for e in repo.errors()))

    def test_a_baseline_rewritten_upward_is_refused(self):
        with Repo() as repo:
            repo.baseline((budgets.BATTERY, 'engine-slo', F['baseline_s']), commit=True)
            repo.baseline((budgets.BATTERY, 'engine-slo', F['upward_s']))
            self.assertTrue(any('never rewritten upward' in e for e in repo.errors()))

    def test_a_baseline_within_the_tolerance_or_lower_passes(self):
        with Repo() as repo:
            repo.baseline((budgets.BATTERY, 'engine-slo', F['baseline_s']), commit=True)
            repo.baseline((budgets.BATTERY, 'engine-slo', F['small_upward_s']))
            self.assertEqual(repo.errors(), [])
            repo.baseline((budgets.BATTERY, 'engine-slo', F['lower_s']))
            self.assertEqual(repo.errors(), [])

    def test_the_repository_registry_passes_against_itself(self):
        self.assertEqual(budget_check.check(ROOT, 'HEAD')[0], [])


if __name__ == '__main__':
    unittest.main()
