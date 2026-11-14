"""Claude adapter of the agent provider port: the only engine module that runs the Claude Code CLI.

One turn is `<providers.agent_claude_cli> --print --output-format json --model M --effort E` with the prompt on
stdin. The JSON result gives the text, is_error, the session id, the token usage and, in modelUsage, the model id
that actually served the turn (an alias in the ladder resolves there). The runner is injected so tests need no CLI.
"""
import json
import re
import subprocess

import config


class ClaudeAdapterError(RuntimeError):
    pass


class ClaudeAdapter:
    name = 'claude'

    def __init__(self, runner=subprocess.run):
        self.command = config.get('providers.agent_claude_cli')
        self.models = re.compile(config.get('providers.agent_claude_model_pattern'))
        self.runner = runner

    def serves(self, model):
        return bool(self.models.fullmatch(model or ''))

    def argv(self, request):
        return [self.command, '--print', '--output-format', 'json', '--model', request.model, '--effort', request.effort]

    def run(self, request):
        from adapters.agent import AgentResult
        done = self.runner(self.argv(request), input=request.prompt, capture_output=True, text=True, cwd=request.cwd)
        try:
            reply = json.loads(done.stdout)
        except ValueError:
            raise ClaudeAdapterError(f'claude: exit {done.returncode}, no JSON result') from None
        usage = reply.get('usage') or {}
        tokens_in = sum(int(usage.get(key) or 0) for key in
                        ('input_tokens', 'cache_creation_input_tokens', 'cache_read_input_tokens'))
        served = next(iter(reply.get('modelUsage') or {}), None)
        return AgentResult(self.name, served or request.model, done.returncode == 0 and not reply.get('is_error'),
                           reply.get('result') or '', tokens_in, int(usage.get('output_tokens') or 0),
                           reply.get('session_id'))
