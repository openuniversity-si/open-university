"""The agent provider port (D-069 item 7, plan v3.1 R1): the engine runs an agent here, never a vendor CLI or SDK.

Adapter interface (what Claude implements today and Codex or Cursor implement later, without changing callers):
  name            the provider id the model ladder and engine.step.measured name (`claude`).
  serves(model)   whether the provider runs this model id or alias.
  run(request)    run one non-interactive agent turn; an AgentResult, ok False when the agent reported an error.
providers.agent_default picks the adapter when a caller names none; a ladder rung names its own provider.

Slots without an adapter yet (no fake implementation of their APIs): codex (the OpenAI Codex CLI) and cursor (the
Cursor agent CLI). Each becomes agent_<name>.py with the three members above, an entry in ADAPTERS and in the enum of
providers.agent_default, and its CLI and hosts in the vendor catalog's adapter list.
"""
from collections import namedtuple
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

AgentRequest = namedtuple('AgentRequest', 'prompt model effort cwd')
AgentResult = namedtuple('AgentResult', 'provider model ok text tokens_in tokens_out session')
SLOTS = {
    'codex': 'the OpenAI Codex CLI; no adapter yet (documented slot, plan v3.1 R1)',
    'cursor': 'the Cursor agent CLI; no adapter yet (documented slot, plan v3.1 R1)',
}


class AgentError(RuntimeError):
    pass


def _claude():
    from adapters import agent_claude  # the vendor module loads only when the registry or a rung selects it
    return agent_claude.ClaudeAdapter()


ADAPTERS = {'claude': _claude}


def adapter(name=None):
    name = name or config.get('providers.agent_default')
    if name in SLOTS:
        raise AgentError(f'agent provider {name} is a slot without an adapter: {SLOTS[name]}')
    if name not in ADAPTERS:
        raise AgentError(f'unknown agent provider {name}')
    return ADAPTERS[name]()


def run_measured(provider, request, port, step, subject_fields):
    """Run one agent turn as a measured engine step: engine.step.measured carries the provider, model and tokens."""
    with port.measured(step, subject_fields) as measurement:
        measurement.provider, measurement.model = provider.name, request.model
        result = provider.run(request)
        measurement.model = result.model or request.model
        measurement.tokens_in, measurement.tokens_out = result.tokens_in, result.tokens_out
        if not result.ok:
            measurement.result = 'fail'
    return result


def run_rung(rung, prompt, cwd, port, step, subject_fields, providers=None):
    """Run a model ladder rung on the provider it names (providers maps a name to an adapter, for tests)."""
    provider = (providers or {}).get(rung.provider) or adapter(rung.provider)
    if not provider.serves(rung.model):
        raise AgentError(f'{rung.provider} does not serve {rung.model} (providers.model_ladder tier {rung.tier})')
    return run_measured(provider, AgentRequest(prompt, rung.model, rung.effort, cwd), port, step, subject_fields)
