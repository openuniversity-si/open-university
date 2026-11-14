"""F37 (D-299): the tower/gate check run is its own switch, apart from the comment panel (fixtures in test_gate_status.py)."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_gate_status import Base, MODE, SHA, T0, stage  # noqa: E402
import config  # noqa: E402
import gate_status as status  # noqa: E402


class CheckRunAlone(Base):
    """gate.check_run_enabled on, gate.status_enabled off: the verdict on the judged head, and nothing of the panel."""

    def setUp(self):
        super().setUp()
        self.switches = {'gate.status_enabled': False, 'gate.check_run_enabled': True}
        read = config.get
        self.enterContext(mock.patch.object(config, 'get', side_effect=lambda key, *args, **kwargs:
                                            self.switches[key] if key in self.switches else read(key, *args, **kwargs)))

    def run_gate(self, result='PASS', events=()):
        with mock.patch.object(status, 'expectation') as eta, mock.patch.object(status, 'publish_started') as started, \
                mock.patch.object(status, 'verdict_hooks') as hooks, mock.patch('subprocess.Popen') as detached:
            self.begin()
            stage(self.logs, 'structure check', result=result)
            status.stage_event(self.logs, 'structure check', False, publisher=self.pub, now=T0 + 1)
            status.stage_event(self.logs, 'structure check', True, publisher=self.pub, now=T0 + 2)
            done = status.final(self.logs, dict(sha=SHA, result=result, stages=[]), [], 0, [], [], list(events),
                                publisher=self.pub, now=T0 + 3)
        for call in (eta, started, hooks, detached):
            call.assert_not_called()
        return done

    def test_the_check_is_set_on_the_exact_head_with_the_verdict(self):
        verdict = dict(type='gate.passed', event_id='e', payload=dict(tier=1, plan=MODE))
        self.assertTrue(self.run_gate(events=[verdict]))
        self.assertEqual([(item['sha'], item['context'], item['state']) for item in self.rest.statuses],
                         [(SHA, config.get('forge-events.status_context_gate'), 'pending'),
                          (SHA, config.get('forge-events.status_context_gate'), 'success')])
        self.assertTrue(self.rest.statuses[-1]['description'].startswith('passed · tier 1 · plan dev'))

    def test_a_failed_run_sets_failure(self):
        self.run_gate('FAIL', [dict(type='gate.failed', payload=dict(tier=None, plan=MODE))])
        self.assertEqual(self.rest.statuses[-1]['state'], 'failure')

    def test_the_comment_panel_stays_off(self):
        self.run_gate()
        self.assertEqual(self.rest.comments, [])
        self.assertFalse([call for call in self.rest.calls if 'comments' in call[1]])
        state = json.loads((self.logs / status.STATE_FILE).read_text())
        self.assertIsNone(state['comment_id'])
        self.assertEqual(state['stages']['structure check']['state'], 'passed')

    def test_forge_events_status_enabled_still_turns_every_write_off(self):
        self.switches['forge-events.status_enabled'] = False
        self.run_gate()
        self.assertEqual(self.rest.statuses, [])

    def test_both_switches_off_create_no_state_and_no_forge_call(self):
        self.switches['gate.check_run_enabled'] = False
        with mock.patch.object(status, 'Publisher') as publisher:
            status.begin(self.logs, SHA, 573, MODE, self.record, now=T0)
        publisher.assert_not_called()
        self.assertFalse((self.logs / status.STATE_FILE).exists())
        self.assertEqual(self.rest.calls, [])

    def test_the_key_defaults_on_since_d313(self):
        self.assertIs(json.loads((Path(__file__).resolve().parents[3] / 'config/registry/gate/gate.check_run_enabled.json')
                                 .read_text())['default'], True)  # D-313: the infra judge publishes it too


if __name__ == '__main__':
    unittest.main()
