"""The expected script-test cost per PR from the covers (D-167). Hermetic: mapping, costs and diffs are plain data."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import covers_cost  # noqa: E402

MAPPING = {
    'scripts': ('scripts/tests/a.test.sh', 'scripts/tests/b.test.sh'),
    'fallback': [],
    'tests': [
        {'script': 'scripts/tests/a.test.sh', 'covers': ['scripts/lib/a.py', 'scripts/lib/*.py']},
        {'script': 'scripts/tests/b.test.sh', 'covers': ['scripts/lib/b.py']},
    ],
}
COSTS = {'scripts/tests/a.test.sh': 1, 'scripts/tests/b.test.sh': 1 + 1 + 1}
RUNS = lambda paths: {'kind': 'scoped', 'stages': ['script tests'], 'paths': paths}  # noqa: E731 - a plan that runs the stage


class CoversCostTests(unittest.TestCase):
    def test_a_paths_name_is_the_bare_test_or_its_script_and_an_unknown_one_is_none(self):
        self.assertEqual(covers_cost.script_of('a', MAPPING), 'scripts/tests/a.test.sh')
        self.assertEqual(covers_cost.script_of('scripts/tests/b.test.sh', MAPPING), 'scripts/tests/b.test.sh')
        self.assertIsNone(covers_cost.script_of('scripts/tests/covers/*.json', MAPPING))
        self.assertIsNone(covers_cost.script_of('nope', MAPPING))

    def test_the_expected_cost_is_miss_rate_times_cost_summed(self):
        only_b = ['scripts/lib/b.py']
        diffs = [['scripts/lib/a.py'], only_b, ['scripts/lib/other.py'], only_b]
        hits, count, expected, _skipped = covers_cost.measure(diffs, MAPPING, COSTS, RUNS)
        a_hits = len(diffs)  # a covers lib/*.py, so every diff selects it
        b_hits = diffs.count(only_b)
        self.assertEqual((hits['scripts/tests/a.test.sh'], hits['scripts/tests/b.test.sh'], count), (a_hits, b_hits, len(diffs)))
        self.assertEqual(expected, (a_hits * COSTS['scripts/tests/a.test.sh'] + b_hits * COSTS['scripts/tests/b.test.sh']) / len(diffs))

    def test_the_broad_pattern_shows_by_its_count(self):
        diffs = [['scripts/lib/a.py'], ['scripts/lib/other.py']]
        met = covers_cost.patterns_met(diffs, MAPPING, 'scripts/tests/a.test.sh')
        self.assertEqual((met['scripts/lib/*.py'], met['scripts/lib/a.py']), (len(diffs), 1))

    def test_the_report_lists_the_costliest_share_first(self):
        hits, count, expected, _skipped = covers_cost.measure([['scripts/lib/a.py']], MAPPING, COSTS, RUNS)
        lines = covers_cost.report(hits, count, expected, COSTS)
        self.assertIn('1 PRs', lines[0])
        self.assertIn('scripts/tests/a.test.sh', lines[1])


class GatePlan(unittest.TestCase):
    """F41: covers-cost asks the gate's area plan first, as the gate does."""

    def test_a_plan_without_the_script_test_stage_pays_no_test(self):
        plans = iter([{'kind': 'scoped', 'stages': ['structure check'], 'paths': ['docs/x.md']},
                      {'kind': 'scoped', 'stages': ['script tests'], 'paths': ['scripts/lib/a.py']}])
        hits, count, expected, skipped = covers_cost.measure([['docs/x.md'], ['scripts/lib/a.py']], MAPPING, COSTS,
                                                             lambda paths: next(plans))
        self.assertEqual((count, skipped), (2, 1))
        self.assertNotIn('scripts/tests/b.test.sh', hits)

    def test_a_full_plan_pays_the_whole_suite(self):
        full = lambda paths: {'kind': 'full', 'stages': ['script tests'], 'paths': paths}  # noqa: E731
        hits, count, expected, skipped = covers_cost.measure([['config/x.json']], MAPPING, COSTS, full)
        self.assertEqual(set(hits), set(MAPPING['scripts']))
        self.assertEqual(expected, sum(COSTS.values()))
        self.assertEqual(skipped, 0)


class NarrowedCovers(unittest.TestCase):
    """The covers D-179 narrowed still meet what the tests read (real manifests)."""

    def selected(self, path):
        return covers_cost.gate_script_tests.select([path])[0]

    def test_the_cache_test_still_follows_the_toolchain_pins_it_asserts_on(self):
        self.assertIn('scripts/tests/gate-result-cache.test.sh', self.selected('config/registry/toolchain.json'))

    def test_a_train_feature_test_does_not_select_the_reuse_test(self):
        self.assertNotIn('scripts/tests/train-reuse.test.sh', self.selected('scripts/tests/train/test_flakes.py'))
        self.assertIn('scripts/tests/train-reuse.test.sh', self.selected('scripts/tests/test_train.py'))


if __name__ == '__main__':
    unittest.main()
