"""The session executor by API (engine-infra-service; D-310, D-311, P4 F3): one call to a model's API as a session.

The common layer (api_sessions.Calls): a call that returns ends with its text and its usage as meters (tokens in and
out per model, the call's seconds); a model the service does not allow this provider is refused, and with no model
allowed every launch is; a rate limit waits until the time it names and the call is sent again at resume; an error ends
failed with its type named, a refusal ends failed and still reports its tokens; a session this process does not know is
lost, and end forgets a call. Then each dialect against a stand-in for its API: OpenAI's Chat Completions shape for the
providers that speak it (the key in its header, the limit in its field, a 429 that waits, a refusal named); Claude
through the official SDK's surface (the message it creates, its text without the thinking, its usage with the cache's
reads and writes apart, a rate limit after the SDK's own retries, a refusal with its category, the clients made when
first used); Amazon Bedrock's Converse for the other Bedrock models (the call, its text and usage, a throttle that
waits, a guardrail as a refusal, the client made once); Gemini's own shape for Vertex AI in express mode (the key in
its header, the thoughts out of the text but in the tokens, the cache apart, a safety stop or a blocked prompt as a
refusal); and the providers the service registers (every one, each with only the models its configuration names, the
keys read by name). No network, no database, no SDK installed; the clocks are the test's.
"""
from concurrent.futures import wait
from datetime import datetime, timedelta
from http import HTTPStatus
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock
import urllib.error

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
from tower_infra import api_providers, api_sessions, bedrock_converse, claude_api, gemini_api, openai_chat  # noqa: E402

NOW = datetime.fromisoformat('2026-11-04T21:30:00+00:00')
SOMEWHERE = '://'.join(('https', 'resource.example.invalid'))  # a host that never answers
MODEL = 'model-of-the-test'


class Ticks:
    """A clock that moves by the given seconds on each read."""

    def __init__(self, *readings):
        self.readings = list(readings)

    def __call__(self):
        return self.readings.pop(0)


def answering(*answers):
    """A dialect that answers each call with the next answer, raising it when it is an exception."""
    asked = []

    def complete(spec, model):
        asked.append((spec['brief'], model))
        answer = answers[len(asked) - 1] if len(asked) <= len(answers) else answers[-1]
        if isinstance(answer, Exception):
            raise answer
        return answer
    complete.asked = asked
    return complete


def finished(calls, session):
    wait([calls.calls[session]['future']])
    return calls.follow(session)


class TheCommonLayer(unittest.TestCase):
    def calls(self, complete, models=(MODEL,), clock=None):
        return api_sessions.Calls(complete, models=models, clock=clock or Ticks(float('10'), float('11.25')),
                                  now=lambda: NOW)

    def test_a_call_that_returns_ends_with_its_text_and_its_usage_as_meters(self):
        done = api_sessions.completion('OK', 'served-model', int('12'), int('3'), stop='end_turn', id='msg-1')
        calls = self.calls(answering(done))
        session = calls.launch({'brief': 'say OK', 'model': MODEL})
        seen = finished(calls, session)
        self.assertEqual((seen['state'], seen['outcome'], seen['error']), ('ended', 'succeeded', None))
        self.assertEqual(seen['result'], {'text': 'OK', 'model': 'served-model', 'stop': 'end_turn', 'id': 'msg-1'})
        self.assertEqual(seen['tokens'], {MODEL: int('15')})
        self.assertEqual(seen['usage'], {f'tokens_in:{MODEL}': int('12'), f'tokens_out:{MODEL}': int('3'),
                                         f'api_s:{MODEL}': float('1.25')})

    def test_a_model_the_service_does_not_allow_is_refused_and_with_none_allowed_every_one_is(self):
        complete = answering(api_sessions.completion('OK', MODEL, 1, 1))
        with self.assertRaisesRegex(api_sessions.NotAllowed, 'other-model'):
            self.calls(complete).launch({'brief': 'x', 'model': 'other-model'})
        with self.assertRaisesRegex(api_sessions.NotAllowed, 'allowed: none'):
            self.calls(complete, models=()).launch({'brief': 'x', 'model': MODEL})
        with self.assertRaises(api_sessions.NotAllowed):
            self.calls(complete).launch({'brief': 'x'})
        self.assertEqual(complete.asked, [])

    def test_a_rate_limit_waits_until_the_time_it_names_and_is_sent_again_at_resume(self):
        complete = answering(api_sessions.Limited('slow down', retry_after_s=float('30')),
                             api_sessions.completion('OK', MODEL, 1, 1))
        calls = self.calls(complete, clock=Ticks(float('0'), float('1'), float('2')))
        session = calls.launch({'brief': 'say OK', 'model': MODEL})
        until = (NOW + timedelta(seconds=int('30'))).isoformat()
        self.assertEqual(finished(calls, session), {'state': 'waiting', 'until': until})
        self.assertEqual(calls.follow(session), {'state': 'waiting', 'until': until})
        calls.resume(session)
        self.assertEqual(finished(calls, session)['outcome'], 'succeeded')
        self.assertEqual(len(complete.asked), len(('first', 'again')))

    def test_an_error_ends_failed_with_its_type_and_a_refusal_still_reports_its_tokens(self):
        calls = self.calls(answering(RuntimeError('the API said 400: bad model')))
        seen = finished(calls, calls.launch({'brief': 'x', 'model': MODEL}))
        self.assertEqual((seen['state'], seen['outcome'], seen['error']), ('ended', 'failed', 'RuntimeError'))
        self.assertIn('bad model', seen['result']['error'])
        calls = self.calls(answering(api_sessions.completion('', MODEL, int('9'), 0, stop='refusal')))
        seen = finished(calls, calls.launch({'brief': 'x', 'model': MODEL}))
        self.assertEqual((seen['outcome'], seen['error'], seen['usage'][f'tokens_in:{MODEL}']),
                         ('failed', 'refusal', int('9')))

    def test_a_session_this_process_does_not_know_is_lost_and_end_forgets_a_call(self):
        calls = self.calls(answering(api_sessions.completion('OK', MODEL, 1, 1)))
        self.assertEqual(calls.follow('unknown')['error'], 'lost')
        session = calls.launch({'brief': 'x', 'model': MODEL})
        wait([calls.calls[session]['future']])
        calls.end(session)
        self.assertEqual(calls.follow(session)['error'], 'lost')

    def test_the_meters_a_dialect_counts_apart_are_their_own_and_count_in_the_total(self):
        done = api_sessions.completion('OK', MODEL, int('10'), int('2'), meters={'tokens_cache_read': int('30'),
                                                                                 'tokens_cache_write': 0})
        calls = self.calls(answering(done))
        seen = finished(calls, calls.launch({'brief': 'x', 'model': MODEL}))
        self.assertEqual(seen['usage'][f'tokens_cache_read:{MODEL}'], int('30'))
        self.assertNotIn(f'tokens_cache_write:{MODEL}', seen['usage'])
        self.assertEqual(seen['tokens'], {MODEL: int('42')})
        self.assertNotIn('meters', seen['result'])

    def test_a_key_is_read_when_used_and_none_is_refused(self):
        self.assertEqual(api_sessions.key_of(lambda: 'the-key'), 'the-key')
        with self.assertRaises(api_sessions.NoKey):
            api_sessions.key_of(lambda: None)
        self.assertEqual(api_sessions.retry_after({'retry-after': '7'}), float('7'))
        self.assertEqual(api_sessions.retry_after({'retry-after': 'soon'}), float('60'))


class Answer:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Stand:
    """A stand-in for an API over HTTP: it keeps each request and answers the next answer (an exception is raised)."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def __call__(self, request, timeout):
        self.asked.append({'url': request.full_url, 'headers': dict(request.header_items()),
                           'body': json.loads(request.data)})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return Answer(json.dumps(answer))


def refused(status, said='', headers=None):
    return urllib.error.HTTPError(SOMEWHERE, status, 'refused', headers or {}, io.BytesIO(said.encode()))


CHAT = {'id': 'chatcmpl-1', 'model': 'served-model', 'usage': {'prompt_tokens': int('11'), 'completion_tokens': 1},
        'choices': [{'message': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': 'stop'}]}


class OpenAICompatible(unittest.TestCase):
    def chat(self, name, stand, environ=None):
        made = openai_chat.providers({name: (MODEL,)}, lambda provider: lambda: f'key-of-{provider}', environ or {},
                                     opener=stand)
        return made[name].complete

    def test_a_call_posts_the_brief_with_the_key_and_answers_the_text_the_stop_and_the_tokens(self):
        stand = Stand(CHAT)
        done = self.chat('openai', stand)({'brief': 'say OK', 'system': 'be brief', 'max_tokens': int('64')}, MODEL)
        asked, = stand.asked
        self.assertEqual(asked['url'], openai_chat.PROVIDERS['openai']['base'] + '/chat/completions')
        self.assertEqual(asked['headers']['Authorization'], 'Bearer key-of-openai')
        self.assertEqual(asked['body'], {'model': MODEL, 'max_completion_tokens': int('64'), 'messages': [
            {'role': 'system', 'content': 'be brief'}, {'role': 'user', 'content': 'say OK'}]})
        self.assertEqual(done, api_sessions.completion('OK', 'served-model', int('11'), 1, stop='stop', id='chatcmpl-1'))

    def test_each_provider_takes_its_key_in_its_header_and_its_limit_in_its_field(self):
        stand = Stand(CHAT, CHAT)
        resource = SOMEWHERE + '/openai/v1'
        self.chat('azure-openai', stand, {'TOWER_AZURE_OPENAI_BASE': resource})({'brief': 'x', 'max_tokens': 1}, MODEL)
        self.chat('mistral', stand)({'brief': 'x', 'max_tokens': 1}, MODEL)
        azure, mistral = stand.asked
        self.assertEqual((azure['url'], azure['headers']['Api-key']), (resource + '/chat/completions',
                                                                       'key-of-azure-openai'))
        self.assertNotIn('Authorization', azure['headers'])
        self.assertEqual((azure['body']['max_completion_tokens'], mistral['body']['max_tokens']), (1, 1))
        with self.assertRaisesRegex(RuntimeError, 'no base URL'):
            self.chat('azure-openai', Stand())({'brief': 'x'}, MODEL)

    def test_a_429_waits_for_its_retry_after_and_another_refusal_is_named(self):
        limited = self.chat('xai', Stand(refused(HTTPStatus.TOO_MANY_REQUESTS, headers={'retry-after': '5'})))
        with self.assertRaises(api_sessions.Limited) as caught:
            limited({'brief': 'x'}, MODEL)
        self.assertEqual(caught.exception.retry_after_s, float('5'))
        with self.assertRaisesRegex(RuntimeError, 'refused with 400: model not found'):
            self.chat('deepseek', Stand(refused(HTTPStatus.BAD_REQUEST, 'model not found')))({'brief': 'x'}, MODEL)
        filtered = dict(CHAT, choices=[{'message': {'content': None}, 'finish_reason': 'content_filter'}])
        self.assertEqual(self.chat('google', Stand(filtered))({'brief': 'x'}, MODEL)['stop'], 'refusal')

    def test_every_provider_of_the_table_runs_only_its_allowed_models_with_its_own_key(self):
        asked = []
        made = openai_chat.providers({'groq': (MODEL,)}, lambda name: asked.append(name) or (lambda: None), {})
        self.assertEqual(set(made), set(openai_chat.PROVIDERS))
        self.assertEqual(asked, list(openai_chat.PROVIDERS))
        self.assertEqual({name: provider.models for name, provider in made.items() if provider.models},
                         {'groq': (MODEL,)})
        for name, shape in openai_chat.PROVIDERS.items():
            self.assertTrue((shape.get('base') or '').startswith('https://') or shape.get('base_from'), name)
        with self.assertRaises(api_sessions.NoKey):
            made['groq'].complete({'brief': 'x'}, MODEL)


class RateLimited(Exception):
    """The SDK's RateLimitError, as far as the dialect reads it: the response's headers."""

    def __init__(self, headers):
        super().__init__('429 rate_limit_error')
        self.response = SimpleNamespace(headers=headers)


class Client:
    """The SDK's client, as far as the dialect calls it: messages.create answers the next answer."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []
        self.messages = self

    def create(self, **asked):
        self.asked.append(asked)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def message(text='OK', stop='end_turn', category=None, cache_read=None, cache_write=None):
    return SimpleNamespace(
        id='msg_01', model='claude-haiku-5-5', stop_reason=stop, _request_id='req_01',
        stop_details=SimpleNamespace(type='refusal', category=category) if category else None,
        content=[SimpleNamespace(type='thinking', thinking=''), SimpleNamespace(type='text', text=text)],
        usage=SimpleNamespace(input_tokens=int('12'), output_tokens=int('5'), cache_creation_input_tokens=cache_write,
                              cache_read_input_tokens=cache_read))


class ClaudeThroughTheSDK(unittest.TestCase):
    def claude(self, client):
        return claude_api.Claude(lambda: client, limited=lambda: RateLimited)

    def test_a_call_creates_the_message_and_answers_its_text_its_stop_and_its_usage(self):
        client = Client(message(cache_read=int('3')))
        done = self.claude(client)({'brief': 'Answer only OK.', 'system': 'be brief', 'effort': 'low'}, MODEL)
        self.assertEqual(client.asked, [{'model': MODEL, 'max_tokens': claude_api.MAX_TOKENS, 'system': 'be brief',
                                         'messages': [{'role': 'user', 'content': 'Answer only OK.'}],
                                         'output_config': {'effort': 'low'}}])
        self.assertEqual(done, api_sessions.completion('OK', 'claude-haiku-5-5', int('12'), int('5'), stop='end_turn',
                                                       meters={'tokens_cache_read': int('3')}, id='msg_01',
                                                       request_id='req_01'))

    def test_a_rate_limit_after_the_sdks_retries_waits_and_a_refusal_is_named_with_its_category(self):
        with self.assertRaises(api_sessions.Limited) as caught:
            self.claude(Client(RateLimited({'retry-after': '7'})))({'brief': 'x'}, MODEL)
        self.assertEqual(caught.exception.retry_after_s, float('7'))
        with self.assertRaisesRegex(ValueError, 'bad model'):
            self.claude(Client(ValueError('bad model')))({'brief': 'x'}, MODEL)
        done = self.claude(Client(message(text='', stop='refusal', category='cyber')))({'brief': 'x'}, MODEL)
        self.assertEqual((done['stop'], done['refusal']), ('refusal', 'cyber'))

    def test_the_clients_are_made_when_first_used_with_the_key_read_then(self):
        made = []
        fake = SimpleNamespace(Anthropic=lambda **options: made.append(('api', options)) or Client(message()),
                               AnthropicBedrockMantle=lambda **options: made.append(('bedrock', options)))
        with mock.patch.object(claude_api, 'sdk', lambda: fake):
            with self.assertRaises(api_sessions.NoKey):
                claude_api.anthropic_api(lambda: None)()
            self.assertEqual(made, [])
            claude = claude_api.Claude(claude_api.anthropic_api(lambda: 'key-of-anthropic'), limited=lambda: RateLimited)
            claude({'brief': 'x'}, MODEL)
            claude_api.bedrock('region-of-the-stack')()
        (api, options), (signed, region) = made
        self.assertEqual((api, options['api_key'], signed, region['aws_region']),
                         ('api', 'key-of-anthropic', 'bedrock', 'region-of-the-stack'))


class ClientError(Exception):
    """botocore's ClientError, as far as the dialect reads it: the response's error code."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {'Error': {'Code': code, 'Message': code}}


class Runtime:
    """Bedrock's runtime client, as far as the dialect calls it: converse answers the next answer."""

    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def converse(self, **asked):
        self.asked.append(asked)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


CONVERSED = {'output': {'message': {'role': 'assistant', 'content': [{'text': 'O'}, {'text': 'K'}]}},
             'stopReason': 'end_turn', 'metrics': {'latencyMs': int('321')},
             'usage': {'inputTokens': int('8'), 'outputTokens': int('2'), 'totalTokens': int('10'),
                       'cacheReadInputTokens': 0},
             'ResponseMetadata': {'RequestId': 'req-bedrock-1'}}
NOVA = 'us.amazon.nova-micro-v1:0'


class BedrocksConverse(unittest.TestCase):
    def test_a_call_converses_with_the_model_and_answers_its_text_its_stop_and_its_usage(self):
        runtime = Runtime(CONVERSED)
        done = bedrock_converse.Converse(lambda: runtime)({'brief': 'say OK', 'system': 'be brief',
                                                           'max_tokens': int('16')}, NOVA)
        self.assertEqual(runtime.asked, [{'modelId': NOVA, 'system': [{'text': 'be brief'}],
                                          'messages': [{'role': 'user', 'content': [{'text': 'say OK'}]}],
                                          'inferenceConfig': {'maxTokens': int('16')}}])
        self.assertEqual(done, api_sessions.completion('OK', NOVA, int('8'), int('2'), stop='end_turn',
                                                       latency_ms=int('321'), request_id='req-bedrock-1'))

    def test_a_throttle_waits_a_guardrail_is_a_refusal_and_another_refusal_is_the_calls(self):
        with self.assertRaises(api_sessions.Limited) as caught:
            bedrock_converse.Converse(lambda: Runtime(ClientError('ThrottlingException')))({'brief': 'x'}, NOVA)
        self.assertEqual(caught.exception.retry_after_s, float('60'))
        with self.assertRaisesRegex(ClientError, 'AccessDeniedException'):
            bedrock_converse.Converse(lambda: Runtime(ClientError('AccessDeniedException')))({'brief': 'x'}, NOVA)
        guarded = dict(CONVERSED, stopReason='guardrail_intervened')
        self.assertEqual(bedrock_converse.Converse(lambda: Runtime(guarded))({'brief': 'x'}, NOVA)['stop'], 'refusal')

    def test_the_client_is_made_once_when_first_used(self):
        made = []
        converse = bedrock_converse.Converse(lambda: made.append('client') or Runtime(CONVERSED, CONVERSED))
        self.assertEqual(made, [])
        converse({'brief': 'x'}, NOVA)
        converse({'brief': 'y'}, NOVA)
        self.assertEqual(made, ['client'])


GENERATED = {'responseId': 'resp-1', 'modelVersion': 'gemini-flash-lite-of-the-test',
             'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model', 'parts': [
                 {'text': 'thinking it over', 'thought': True}, {'text': 'OK'}]}}],
             'usageMetadata': {'promptTokenCount': int('40'), 'cachedContentTokenCount': int('30'),
                               'candidatesTokenCount': int('2'), 'thoughtsTokenCount': int('5')}}


class VertexInExpressMode(unittest.TestCase):
    def gemini(self, stand):
        return gemini_api.Gemini(gemini_api.BASE, lambda: 'key-of-vertex', opener=stand)

    def test_a_call_generates_with_the_key_in_its_header_and_answers_the_text_and_the_tokens(self):
        stand = Stand(GENERATED)
        done = self.gemini(stand)({'brief': 'say OK', 'system': 'be brief', 'max_tokens': int('16')}, 'gemini-x')
        asked, = stand.asked
        self.assertEqual(asked['url'], gemini_api.BASE + '/publishers/google/models/gemini-x:generateContent')
        self.assertEqual(asked['headers']['X-goog-api-key'], 'key-of-vertex')
        self.assertNotIn('key-of-vertex', asked['url'])
        self.assertEqual(asked['body'], {'contents': [{'role': 'user', 'parts': [{'text': 'say OK'}]}],
                                         'systemInstruction': {'parts': [{'text': 'be brief'}]},
                                         'generationConfig': {'maxOutputTokens': int('16')}})
        self.assertEqual(done, api_sessions.completion('OK', 'gemini-flash-lite-of-the-test', int('10'), int('7'),
                                                       stop='STOP', meters={'tokens_cache_read': int('30')},
                                                       id='resp-1'))

    def test_a_safety_stop_or_a_blocked_prompt_is_a_refusal_and_a_429_waits(self):
        unsafe = dict(GENERATED, candidates=[{'finishReason': 'SAFETY', 'content': {'parts': []}}])
        self.assertEqual(self.gemini(Stand(unsafe))({'brief': 'x'}, 'gemini-x')['stop'], 'refusal')
        blocked = {'promptFeedback': {'blockReason': 'PROHIBITED_CONTENT'}, 'usageMetadata': {'promptTokenCount': 1}}
        done = self.gemini(Stand(blocked))({'brief': 'x'}, 'gemini-x')
        self.assertEqual((done['stop'], done['refused_for'], done['text']), ('refusal', 'PROHIBITED_CONTENT', ''))
        with self.assertRaises(api_sessions.Limited):
            self.gemini(Stand(refused(HTTPStatus.TOO_MANY_REQUESTS)))({'brief': 'x'}, 'gemini-x')
        with self.assertRaises(api_sessions.NoKey):
            gemini_api.Gemini(gemini_api.BASE, lambda: '', opener=Stand())({'brief': 'x'}, 'gemini-x')


class TheServicesProviders(unittest.TestCase):
    def test_every_provider_is_registered_with_only_the_models_its_configuration_names(self):
        asked = []
        models = api_providers.allowed('{"bedrock": ["anthropic.claude-haiku-5-5"], "openai": ["model-x"], '
                                       '"typo-provider": ["y"], "groq": "not a list"}')
        made = api_providers.providers(models, lambda name: asked.append(name) or (lambda: None), 'region-of-the-stack',
                                       {})
        self.assertEqual(set(made), set(openai_chat.PROVIDERS) | {'anthropic', 'bedrock', 'bedrock-converse', 'vertex'})
        self.assertEqual({name: provider.models for name, provider in made.items() if provider.models},
                         {'bedrock': ('anthropic.claude-haiku-5-5',), 'openai': ('model-x',)})
        self.assertEqual(api_providers.unknown(models, made), ['typo-provider'])
        self.assertEqual(sorted(asked), sorted([*openai_chat.PROVIDERS, 'anthropic', 'vertex']))  # Bedrock: no key
        self.assertEqual(api_providers.allowed(None), {})
        with self.assertRaises(ValueError):
            api_providers.allowed('["bedrock"]')


if __name__ == '__main__':
    unittest.main()
