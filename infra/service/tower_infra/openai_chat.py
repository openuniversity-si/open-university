"""OpenAI's Chat Completions shape, the dialect most model APIs speak (D-311): OpenAI, Google's Gemini API, xAI, Mistral,
DeepSeek, Azure OpenAI, Groq, OpenRouter and Together, each a base URL, a key and the header the key goes in.

Chat(base, key) is one function for api_sessions.Calls: POST <base>/chat/completions with the job's brief as the user's
message (after its system message, when the entry has one) and its max_tokens in the provider's own field (OpenAI's
reasoning models take max_completion_tokens). It answers the first choice's text and finish reason (a content filter
is a refusal), the served model and the usage: prompt_tokens in, completion_tokens out, which already count a reasoning
model's thinking. A 429 is the account's limit (Limited, for the seconds its Retry-After asks); any other refusal
raises with the status and what the API said. The key is read when used; Azure OpenAI's base is the installation's
resource (TOWER_AZURE_OPENAI_BASE). Standard library only.
"""
from http import HTTPStatus
import json
import urllib.error
import urllib.request

from . import api_sessions

PROVIDERS = {
    'openai': {'base': 'https://api.openai.com/v1', 'limit': 'max_completion_tokens'},
    'google': {'base': 'https://generativelanguage.googleapis.com/v1beta/openai'},
    'xai': {'base': 'https://api.x.ai/v1'},
    'mistral': {'base': 'https://api.mistral.ai/v1'},
    'deepseek': {'base': 'https://api.deepseek.com'},
    'azure-openai': {'base_from': 'TOWER_AZURE_OPENAI_BASE', 'header': 'api-key', 'limit': 'max_completion_tokens'},
    'groq': {'base': 'https://api.groq.com/openai/v1'},
    'openrouter': {'base': 'https://openrouter.ai/api/v1'},
    'together': {'base': 'https://api.together.xyz/v1'},
}
STOPS = {'content_filter': 'refusal'}


class Chat:
    def __init__(self, base, key, header='authorization', limit='max_tokens', opener=urllib.request.urlopen,
                 timeout_s=300.0):
        self.base, self.key, self.header, self.limit = (base or '').rstrip('/'), key, header, limit
        self.opener, self.timeout_s = opener, timeout_s

    def __call__(self, spec, model):
        if not self.base:
            raise RuntimeError('no base URL for this provider (its resource, from the environment)')
        key = api_sessions.key_of(self.key)
        messages = [{'role': 'system', 'content': spec['system']}] if spec.get('system') else []
        body = {'model': model, 'messages': [*messages, {'role': 'user', 'content': spec['brief']}]}
        if spec.get('max_tokens'):
            body[self.limit] = int(spec['max_tokens'])
        headers = {'Content-Type': 'application/json',
                   **({'Authorization': f'Bearer {key}'} if self.header == 'authorization' else {self.header: key})}
        request = urllib.request.Request(self.base + '/chat/completions', data=json.dumps(body).encode('utf-8'),
                                         headers=headers, method='POST')
        try:
            with self.opener(request, timeout=self.timeout_s) as answer:
                said = json.loads(answer.read() or b'{}')
        except urllib.error.HTTPError as error:
            if error.code == HTTPStatus.TOO_MANY_REQUESTS:
                raise api_sessions.Limited(f'{error.code} from the API',
                                           api_sessions.retry_after(error.headers)) from None
            raise RuntimeError(f'the API refused with {error.code}: {refusal_of(error)}') from None
        choice = (said.get('choices') or [{}])[0]
        usage = said.get('usage') or {}
        stop = choice.get('finish_reason')
        return api_sessions.completion((choice.get('message') or {}).get('content'), said.get('model') or model,
                                       usage.get('prompt_tokens'), usage.get('completion_tokens'),
                                       stop=STOPS.get(stop, stop), id=said.get('id'))


def refusal_of(error):
    try:
        return error.read().decode('utf-8', 'replace')[:api_sessions.SAID]
    except (OSError, AttributeError):
        return str(error)


def providers(models, key, environ, opener=urllib.request.urlopen):
    """Each provider of the table as a session provider: only the models the service allows it; key(name) its key."""
    made = {}
    for name, shape in PROVIDERS.items():
        base = shape.get('base') or environ.get(shape.get('base_from', ''), '')
        chat = Chat(base, key(name), header=shape.get('header', 'authorization'),
                    limit=shape.get('limit', 'max_tokens'), opener=opener)
        made[name] = api_sessions.Calls(chat, models=models.get(name, ()))
    return made
