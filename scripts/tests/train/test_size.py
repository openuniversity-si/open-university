"""VAZÃO F36: the batch size on the box from the observed red share (train.batch_size_by_red, design-trem.md §3)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, setUpModule  # noqa: E402,F401
import engine_role  # noqa: E402
import train  # noqa: E402

TABLE = [{'red_max': 0.10, 'size': 8}, {'red_max': 0.15, 'size': 4}, {'red_max': 0.25, 'size': 2}]


class SizeForRed(unittest.TestCase):
    def test_the_design_table(self):
        sizes = [train.size_for_red(red, TABLE, 8) for red in (0.0, 0.10, 0.133, 0.15, 0.20, 0.25, 0.30)]
        self.assertEqual(sizes, [8, 8, 4, 4, 2, 2, 1])

    def test_the_registry_default_is_the_design_table(self):
        self.assertEqual(engine_role.setting('train.batch_size_by_red'), TABLE)

    def test_never_above_train_batch_size(self):
        self.assertEqual(train.size_for_red(0.0, TABLE, 3), 3)

    def test_an_unknown_red_share_is_no_batch(self):
        self.assertEqual(train.size_for_red(None, TABLE, 8), 1)

    def test_every_default_size_fits_the_bisection_bound(self):
        self.assertEqual(train.check_sizes(engine_role.setting('train.batch_size_by_red'),
                                           engine_role.setting('train.bisection_max_runs')), [])

    def test_a_size_past_the_bisection_bound_or_bounds_out_of_order_are_refused(self):
        errors = train.check_sizes([{'red_max': 0.2, 'size': 2}, {'red_max': 0.1, 'size': 32}], 4)
        self.assertEqual(len(errors), 2)
        self.assertIn('ascend', errors[0])
        self.assertIn('size 32 needs 5 bisection runs', errors[1])


class ObservedRed(unittest.TestCase):
    def test_p_of_the_window_and_none_when_the_meter_cannot_answer(self):
        windows = []
        self.assertEqual(train.observed_red(50, lambda count: windows.append(count) or {'runs': 4, 'p': 0.25}), 0.25)
        self.assertEqual(windows, [50])
        self.assertIsNone(train.observed_red(50, lambda count: {'prs': [], 'error': 'RuntimeError: no credential'}))
        self.assertIsNone(train.observed_red(50, lambda count: {'runs': 0, 'p': 0.0}))


class SizeNow(Fixture):
    def test_one_leadership_reads_p_once_and_maps_it(self):
        calls = []
        size, red = self.train.size_now(lambda count: calls.append(count) or {'runs': 10, 'p': 0.133})
        self.assertEqual((size, red), (4, 0.133))
        self.assertEqual(calls, [engine_role.setting('train.batch_red_window')])

    def test_a_table_the_bisection_cannot_cover_refuses_the_train(self):
        original = engine_role.setting

        def setting(name):
            return [{'red_max': 0.5, 'size': 64}] if name == 'train.batch_size_by_red' else original(name)

        engine_role.setting = setting
        self.addCleanup(setattr, engine_role, 'setting', original)
        with self.assertRaises(train.TrainError):
            train.Train(self.forge, self.clock, self.workspace, self.gate, "r")


if __name__ == '__main__':
    unittest.main()
