"""Claude through the official Anthropic SDK (D-310, D-311): on the Anthropic API, with the key read when first used
(/tower/sessions/anthropic), and on Claude in Amazon Bedrock, the Messages API at bedrock-mantle signed with the
service's task role (no key; the boundary allows bedrock-mantle:CreateInference). The SDK (anthropic[bedrock], pinned in
the image) is imported when a client is first made, so this module and its tests load without it.

Claude(client_of) is one function for api_sessions.Calls: client.messages.create with the model, the entry's
max_tokens (16000 by default: a ceiling, not a spend), its system and its effort (output_config). It answers the text
blocks (thinking is left out), the stop reason (a refusal is named with its category), the served model, the request
id and the usage: input and output tokens, and the cache's writes and reads as their own meters, priced apart. The SDK
retries what it should (connection errors, 408, 409, 429, 5xx) and raises RateLimitError after that: Limited, for the
seconds its Retry-After asks; any other error is the call's.
"""
import threading

from . import api_sessions

MAX_TOKENS = 16000


def sdk():
    import anthropic  # the image's anthropic[bedrock]; imported when a client is first made
    return anthropic


def anthropic_api(key, timeout_s=600.0, max_retries=2):
    """The Anthropic API's client, made when first used, with the key read then (NoKey without one)."""
    def make():
        found = api_sessions.key_of(key)
        return sdk().Anthropic(api_key=found, timeout=timeout_s, max_retries=max_retries)
    return make


def bedrock(region, timeout_s=600.0, max_retries=2):
    """Claude in Amazon Bedrock's client: the Messages API at bedrock-mantle, signed with the task role's credentials."""
    return lambda: sdk().AnthropicBedrockMantle(aws_region=region, timeout=timeout_s, max_retries=max_retries)


class Claude:
    def __init__(self, client_of, limited=lambda: sdk().RateLimitError):
        self.client_of, self.limited, self.client, self.lock = client_of, limited, None, threading.Lock()

    def made(self):
        with self.lock:
            if self.client is None:
                self.client = self.client_of()
            return self.client

    def __call__(self, spec, model):
        asked = {'model': model, 'max_tokens': int(spec.get('max_tokens') or MAX_TOKENS),
                 'messages': [{'role': 'user', 'content': spec['brief']}]}
        if spec.get('system'):
            asked['system'] = spec['system']
        if spec.get('effort'):
            asked['output_config'] = {'effort': spec['effort']}
        client = self.made()
        try:
            message = client.messages.create(**asked)
        except Exception as error:  # noqa: BLE001 - the SDK's RateLimitError, after its own retries, waits
            if isinstance(error, self.limited()):
                raise api_sessions.Limited(str(error), api_sessions.retry_after(error.response.headers)) from None
            raise
        usage = message.usage
        details = getattr(message, 'stop_details', None)
        return api_sessions.completion(
            ''.join(block.text for block in message.content if block.type == 'text'), message.model,
            usage.input_tokens, usage.output_tokens, stop=message.stop_reason,
            meters={'tokens_cache_write': usage.cache_creation_input_tokens,
                    'tokens_cache_read': usage.cache_read_input_tokens},
            id=message.id, request_id=getattr(message, '_request_id', None),
            **({'refusal': getattr(details, 'category', None)} if message.stop_reason == 'refusal' else {}))
