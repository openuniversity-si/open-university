"""The agent provider port and its Claude adapter (D-069 items 6 and 7): a fake runner, a memory log. No network."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import forge_events  # noqa: E402
from adapters import agent, agent_claude, model_ladder  # noqa: E402

REPO = 'openuniversity-si/open-university'
SUBJECT = forge_events.subject(REPO, 7, 'a' * 40, ['P-02'])


class FakeClock:
    def __init__(self):
        self.moment = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)

    def now(self):
        self.moment += timedelta(milliseconds=250)
        return self.moment


class FakeRunner:
    def __init__(self, reply, returncode=0):
        self.reply, self.returncode, self.calls = reply, returncode, []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        stdout = self.reply if isinstance(self.reply, str) else json.dumps(self.reply)
        return subprocess.CompletedProcess(argv, self.returncode, stdout, '')


REPLY = {'type': 'result', 'is_error': False, 'result': 'done', 'session_id': 's-1',
         'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 5, 'cache_read_input_tokens': 85,
                   'output_tokens': 40},
         'modelUsage': {'served-model-id': {}}}


def port():
    return forge_events.ForgeEvents(forge_events.MemoryAdapter(), FakeClock(), 'r1-test', 'corr-1')


def measured(events_port):
    return [event['payload'] for event in events_port.read(REPO, 7) if event['type'] == 'engine.step.measured']


class Claude(unittest.TestCase):
    def test_one_turn_is_the_cli_in_print_json_mode_with_the_prompt_on_stdin(self):
        runner = FakeRunner(REPLY)
        result = agent_claude.ClaudeAdapter(runner).run(agent.AgentRequest('do it', 'opus', 'medium', '/tmp'))
        argv, kwargs = runner.calls[0]
        self.assertEqual(argv, [config.get('providers.agent_claude_cli'), '--print', '--output-format', 'json',
                                '--model', 'opus', '--effort', 'medium'])
        self.assertEqual((kwargs['input'], kwargs['cwd']), ('do it', '/tmp'))
        self.assertEqual(result, agent.AgentResult('claude', 'served-model-id', True, 'done', 100, 40, 's-1'))

    def test_an_error_reply_or_exit_is_not_ok_and_no_json_raises(self):
        self.assertFalse(agent_claude.ClaudeAdapter(FakeRunner(dict(REPLY, is_error=True))).run(
            agent.AgentRequest('x', 'opus', 'medium', None)).ok)
        self.assertFalse(agent_claude.ClaudeAdapter(FakeRunner(REPLY, returncode=1)).run(
            agent.AgentRequest('x', 'opus', 'medium', None)).ok)
        with self.assertRaises(agent_claude.ClaudeAdapterError):
            agent_claude.ClaudeAdapter(FakeRunner('not json', 1)).run(agent.AgentRequest('x', 'opus', 'medium', None))

    def test_it_serves_the_registry_ladder(self):
        claude = agent_claude.ClaudeAdapter(FakeRunner(REPLY))
        for rung in model_ladder.from_config().rungs:
            self.assertEqual(rung.provider, 'claude')
            self.assertTrue(claude.serves(rung.model), rung.model)
        self.assertFalse(claude.serves('other-vendor-model'))
        self.assertFalse(claude.serves(None))


class Port(unittest.TestCase):
    def test_the_default_is_the_registry_entry_and_slots_have_no_fake(self):
        self.assertEqual(agent.adapter().name, config.get('providers.agent_default'))
        for slot in ('codex', 'cursor'):
            with self.assertRaisesRegex(agent.AgentError, 'slot without an adapter'):
                agent.adapter(slot)
        with self.assertRaises(agent.AgentError):
            agent.adapter('other')

    def test_a_measured_turn_fills_provider_model_and_tokens(self):
        events = port()
        rung = model_ladder.from_config().rung('structural')
        claude = agent_claude.ClaudeAdapter(FakeRunner(REPLY))
        result = agent.run_rung(rung, 'go', None, events, 'agent.turn', SUBJECT, providers={'claude': claude})
        self.assertTrue(result.ok)
        [payload] = measured(events)
        self.assertEqual((payload['provider'], payload['model'], payload['tokens_in'], payload['tokens_out']),
                         ('claude', 'served-model-id', 100, 40))
        self.assertEqual((payload['step'], payload['result'], payload['duration_ms']), ('agent.turn', 'ok', 250))

    def test_a_failed_turn_is_measured_fail(self):
        events = port()
        claude = agent_claude.ClaudeAdapter(FakeRunner(dict(REPLY, is_error=True)))
        agent.run_measured(claude, agent.AgentRequest('x', 'sonnet', 'medium', None), events, 'agent.turn', SUBJECT)
        self.assertEqual(measured(events)[0]['result'], 'fail')

    def test_a_rung_the_provider_does_not_serve_is_refused(self):
        rung = model_ladder.Rung('leaf', 'claude', 'other-vendor-model', 'medium', 'leaf')
        claude = agent_claude.ClaudeAdapter(FakeRunner(REPLY))
        with self.assertRaisesRegex(agent.AgentError, 'does not serve'):
            agent.run_rung(rung, 'x', None, port(), 'agent.turn', SUBJECT, providers={'claude': claude})

    def test_the_port_never_touches_the_vendor(self):
        source = (ROOT / 'scripts/lib/adapters/agent.py').read_text()
        self.assertNotIn('subprocess', source)
        self.assertEqual(source.count('import agent_claude'), 1, 'only the lazy adapter factory loads the adapter')


if __name__ == '__main__':
    unittest.main(verbosity=1)
