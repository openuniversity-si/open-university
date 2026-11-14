"""GX-12: the publish rule of the gate, tier 1 (PR) and tier 2 (repository channel, pr null). Hermetic."""
import hashlib
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import gate_publish  # noqa: E402
import gate_tier  # noqa: E402

SHA = hashlib.sha1(b'combined head').hexdigest()
TIER2 = 'tier-two'


class PublishRule(unittest.TestCase):
    def test_tier1_rule_is_unchanged(self):
        self.assertTrue(gate_publish.should_publish('dev', '7', SHA))
        self.assertFalse(gate_publish.should_publish('dev', '', SHA))
        self.assertFalse(gate_publish.should_publish('dev', '7', 'working-tree'))
        self.assertFalse(gate_publish.should_publish(None, '7', SHA))

    def test_no_pr_full_sha_publishes_on_the_repository_channel(self):
        self.assertTrue(gate_publish.publishes('dev', '', SHA))
        self.assertTrue(gate_publish.repository_run('dev', None, SHA))
        self.assertIsNone(gate_publish.change_number(''))
        self.assertEqual(gate_publish.change_number('7'), int('7'))

    def test_neither_full_sha_nor_mode_publishes_nothing(self):
        self.assertFalse(gate_publish.publishes('dev', '', 'working-tree'))
        self.assertFalse(gate_publish.publishes('dev', '', SHA[:-len('0')]))
        self.assertFalse(gate_publish.publishes(None, '', SHA))
        self.assertFalse(gate_publish.publishes(None, '7', SHA))

    def test_tier_is_2_without_a_pr_and_the_mode_tier_with_one(self):
        tier = gate_publish.tier
        self.assertEqual(tier('dev', '', ['dev'], gate_tier.current, TIER2), TIER2)
        self.assertEqual(tier('dev', '7', ['dev'], gate_tier.current, TIER2), gate_tier.current('dev', ['dev']))
        self.assertIsNone(tier('pr', '7', ['dev'], gate_tier.current, TIER2))


if __name__ == '__main__':
    unittest.main()
