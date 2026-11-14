"""The production freeze and the release unit (D-054). No network."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import release_policy as policy  # noqa: E402

REAL = 'https://api.github.com'
FAKE = 'http://127.0.0.1:9'


class ReleasePolicy(unittest.TestCase):
    def setUp(self):
        self.frozen = policy.load()
        self.open = dict(self.frozen, frozen=False)

    def test_d054_the_repository_policy_is_frozen_until_step_8(self):
        self.assertTrue(self.frozen['frozen'])
        self.assertEqual(self.frozen['decision'], 'D-054')
        for key in ('queue', 'rules'):
            self.assertTrue((policy.POLICY.parents[1] / self.frozen[key]).is_file(), key)

    def test_d054_a_frozen_policy_refuses_the_real_host_and_names_the_queue(self):
        with self.assertRaises(policy.Refused) as refused:
            policy.refuse_frozen('neon-migrate prod', 'https://console.neon.tech', self.frozen)
        self.assertIn('production is frozen', str(refused.exception))
        self.assertIn(self.frozen['queue'], str(refused.exception))

    def test_d054_a_loopback_fake_is_not_production(self):
        policy.refuse_frozen('neon-migrate prod', FAKE, self.frozen)
        policy.refuse_frozen('neon-migrate prod', 'http://localhost:1', self.frozen)
        for origin in ('', 'https://127.0.0.1:9', 'http://127.0.0.1.example.com', 'http://evil.test'):
            with self.subTest(origin=origin), self.assertRaises(policy.Refused):
                policy.refuse_frozen('x', origin, self.frozen)

    def test_d054_an_open_policy_allows_the_real_host(self):
        policy.refuse_frozen('neon-migrate prod', REAL, self.open)

    def test_d054_a_merge_into_main_must_come_from_the_release_branch(self):
        for state in (self.frozen, self.open):
            with self.subTest(frozen=state['frozen']), self.assertRaises(policy.Refused) as refused:
                policy.refuse_merge('main', 'cursor/feature', FAKE, state)
            self.assertIn('a release merges mod/roadmap-integration', str(refused.exception))
        policy.refuse_merge('main', 'mod/roadmap-integration', FAKE, self.frozen)
        policy.refuse_merge('main', 'mod/roadmap-integration', REAL, self.open)
        with self.assertRaises(policy.Refused):
            policy.refuse_merge('main', 'mod/roadmap-integration', REAL, self.frozen)

    def test_d054_a_fork_head_is_not_a_release(self):
        with self.assertRaises(policy.Refused):
            policy.refuse_merge('main', 'mod/roadmap-integration', FAKE, self.open, same_repository=False)

    def test_d054_a_merge_into_the_integration_branch_is_not_a_release(self):
        policy.refuse_merge('mod/roadmap-integration', 'mod/step1-x', REAL, self.frozen)

    def test_merge_phase_settings_come_from_the_registry(self):
        import config
        for name, key in (('allowed-bases', 'delivery.merge_allowed_bases'), ('closes-pattern', 'delivery.closes_pattern'),
                          ('repository', 'forge-events.repo')):
            with self.subTest(name=name):
                shown = []
                with patch('builtins.print', lambda text: shown.append(text)):
                    self.assertEqual(policy.main([name]), 0)
                value = config.get(key)
                self.assertEqual(shown, [' '.join(value) if isinstance(value, list) else value])
        self.assertEqual(policy.main(['unknown']), 2)
        # ORIGIN-FINISH F9: the merge command left with merge-phase; a merge is judged by the adapter that merges
        self.assertEqual(policy.main(['merge', 'main', 'mod/roadmap-integration']), 2)

    def test_load_reads_a_given_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'policy.json'
            path.write_text(json.dumps(self.open))
            self.assertFalse(policy.load(path)['frozen'])


if __name__ == '__main__':
    unittest.main()
