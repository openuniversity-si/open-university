"""The model ladder port (D-069 item 7, plan v3.1 §4): rungs as registry data, escalation up only. No network."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
from adapters import model_ladder  # noqa: E402

RUNGS = [
    {'tier': 'leaf', 'provider': 'claude', 'model': 'small', 'effort': 'medium', 'use': 'leaf'},
    {'tier': 'medium', 'provider': 'claude', 'model': 'middle', 'effort': 'medium', 'use': 'medium'},
    {'tier': 'structural', 'provider': 'claude', 'model': 'large', 'effort': 'medium', 'use': 'structural'},
]


def ladder(escalate_after=2, step=1):
    return model_ladder.ModelLadder(RUNGS, escalate_after, step)


class Registry(unittest.TestCase):
    def test_the_registry_ladder_holds_the_current_rule(self):
        current = model_ladder.from_config()
        self.assertEqual([rung.tier for rung in current.rungs], ['leaf', 'medium', 'structural'])
        self.assertEqual({rung.effort for rung in current.rungs}, {'medium'})
        self.assertEqual(current.escalate_after, config.get('providers.model_escalate_after_failures'))
        self.assertEqual(current.step, config.get('providers.model_escalation_step'))

    def test_a_tier_twice_is_refused(self):
        with self.assertRaises(model_ladder.LadderError):
            model_ladder.ModelLadder(RUNGS + [RUNGS[0]], 2, 1)
        with self.assertRaises(model_ladder.LadderError):
            model_ladder.ModelLadder([], 2, 1)


class Pick(unittest.TestCase):
    def test_a_tier_runs_on_its_rung(self):
        self.assertEqual(ladder().pick('leaf').rung.model, 'small')
        self.assertEqual(ladder().pick('structural').rung.model, 'large')
        self.assertFalse(ladder().pick('medium').escalated)

    def test_one_model_up_after_the_threshold_of_real_failures(self):
        self.assertEqual(ladder().pick('leaf', 'small', failures=1).rung.model, 'small')
        choice = ladder().pick('leaf', 'small', failures=2)
        self.assertEqual((choice.rung.model, choice.escalated), ('middle', True))
        self.assertEqual(ladder(escalate_after=3).pick('leaf', 'small', failures=2).rung.model, 'small')
        self.assertEqual(ladder(step=2).pick('leaf', 'small', failures=2).rung.model, 'large')

    def test_never_down_mid_pr(self):
        choice = ladder().pick('leaf', current='large')
        self.assertEqual((choice.rung.model, choice.escalated), ('large', False))
        self.assertIn('never down', choice.reason)

    def test_the_top_rung_stays_the_top(self):
        choice = ladder().pick('structural', 'large', failures=5)
        self.assertEqual((choice.rung.model, choice.escalated), ('large', False))
        self.assertEqual(ladder(step=5).pick('medium', 'middle', failures=2).rung.model, 'large')

    def test_an_unknown_tier_or_model_is_an_error_not_a_default(self):
        with self.assertRaises(model_ladder.LadderError):
            ladder().pick('huge')
        with self.assertRaises(model_ladder.LadderError):
            ladder().pick('leaf', current='other')


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/lib/adapters/model_ladder.py'), *args],
                              capture_output=True, text=True)

    def test_pick_prints_the_rung_as_json(self):
        done = self.run_cli('pick', '--tier', 'leaf')
        self.assertEqual(done.returncode, 0, done.stderr)
        rung = json.loads(done.stdout)
        self.assertEqual(rung['model'], model_ladder.from_config().rung('leaf').model)
        self.assertFalse(rung['escalated'])
        self.assertEqual(len(json.loads(self.run_cli('list').stdout)), len(model_ladder.from_config().rungs))

    def test_an_unknown_tier_exits_2(self):
        done = self.run_cli('pick', '--tier', 'huge')
        self.assertEqual(done.returncode, 2)
        self.assertIn('no rung', done.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=1)
