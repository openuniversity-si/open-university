"""Gemini's own shape (D-311), for Vertex AI in express mode, where a key calls Google's models (/tower/sessions/vertex).
Google's Gemini API also speaks OpenAI's shape (openai_chat's google); Vertex AI's OpenAI endpoint asks for an OAuth
token instead, which a key in express mode does not give.

Gemini(base, key) is one function for api_sessions.Calls: POST <base>/publishers/google/models/<model>:generateContent
with the key in x-goog-api-key (never in the URL, which errors and logs repeat), the brief as the user's content, the
entry's system (systemInstruction) and its max_tokens (generationConfig.maxOutputTokens). It answers the first
candidate's text parts (a thought is left out) and its finish reason (a safety, prohibited-content, blocklist,
personal-data or recitation stop is a refusal, and so is a prompt blocked before any candidate), the served model
version and the usage: the prompt's tokens less the cached ones in, the candidates' and the thoughts' tokens out
(thinking is billed as output), and the cache's reads apart. A 429 is the account's limit (Limited, for its
Retry-After); any other refusal raises with the status and what the API said. Standard library only.
"""
from http import HTTPStatus
import json
import urllib.error
import urllib.parse
import urllib.request

from . import api_sessions, openai_chat

BASE = 'https://aiplatform.googleapis.com/v1'
REFUSALS = {'SAFETY', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'SPII', 'RECITATION', 'IMAGE_SAFETY'}


class Gemini:
    def __init__(self, base, key, opener=urllib.request.urlopen, timeout_s=300.0):
        self.base, self.key, self.opener, self.timeout_s = base.rstrip('/'), key, opener, timeout_s

    def __call__(self, spec, model):
        key = api_sessions.key_of(self.key)
        body = {'contents': [{'role': 'user', 'parts': [{'text': spec['brief']}]}]}
        if spec.get('system'):
            body['systemInstruction'] = {'parts': [{'text': spec['system']}]}
        if spec.get('max_tokens'):
            body['generationConfig'] = {'maxOutputTokens': int(spec['max_tokens'])}
        url = f"{self.base}/publishers/google/models/{urllib.parse.quote(model, safe='.-_')}:generateContent"
        request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8'), method='POST',
                                         headers={'Content-Type': 'application/json', 'x-goog-api-key': key})
        try:
            with self.opener(request, timeout=self.timeout_s) as answer:
                said = json.loads(answer.read() or b'{}')
        except urllib.error.HTTPError as error:
            if error.code == HTTPStatus.TOO_MANY_REQUESTS:
                raise api_sessions.Limited(f'{error.code} from the API',
                                           api_sessions.retry_after(error.headers)) from None
            raise RuntimeError(f'the API refused with {error.code}: {openai_chat.refusal_of(error)}') from None
        candidate = (said.get('candidates') or [{}])[0]
        parts = (candidate.get('content') or {}).get('parts') or []
        usage = said.get('usageMetadata') or {}
        cached = int(usage.get('cachedContentTokenCount') or 0)
        stop = candidate.get('finishReason') or (said.get('promptFeedback') or {}).get('blockReason')
        return api_sessions.completion(
            ''.join(part.get('text', '') for part in parts if not part.get('thought')), said.get('modelVersion') or model,
            int(usage.get('promptTokenCount') or 0) - cached,
            int(usage.get('candidatesTokenCount') or 0) + int(usage.get('thoughtsTokenCount') or 0),
            stop='refusal' if stop in REFUSALS else stop, meters={'tokens_cache_read': cached},
            id=said.get('responseId'), **({'refused_for': stop} if stop in REFUSALS else {}))
