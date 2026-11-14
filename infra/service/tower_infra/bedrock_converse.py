"""Amazon Bedrock's Converse (D-311): one API for the models Bedrock serves besides Claude's Messages endpoint (Amazon
Nova, Meta Llama, Mistral, DeepSeek, Qwen and the older Claude), signed with the service's task role: no key, and the
boundary allows bedrock:InvokeModel on foundation models and inference profiles only. boto3 is the image's; the client
is made when first used.

Converse(client_of) is one function for api_sessions.Calls: client.converse with the model id (a foundation model, or
an inference profile such as us.amazon.nova-micro-v1:0), the brief as the user's message, the entry's system and its
max_tokens (inferenceConfig.maxTokens). It answers the text blocks, the stop reason (a guardrail or a content filter is
a refusal), the usage (inputTokens, outputTokens, and the cache's reads and writes as their own meters), Bedrock's own
latency and the request id. boto3 retries a throttle itself; after that, ThrottlingException,
ServiceQuotaExceededException or TooManyRequestsException is Limited, for a minute; any other refusal is the call's.
"""
import threading

from . import api_sessions

LIMITED = ('ThrottlingException', 'ServiceQuotaExceededException', 'TooManyRequestsException')
STOPS = {'guardrail_intervened': 'refusal', 'content_filtered': 'refusal'}


def runtime(region):
    """Bedrock's runtime client in the stack's region, made when first used, with the task role's credentials."""
    def make():
        import boto3  # the image's; the service already reads Parameter Store and publishes to SNS with it
        return boto3.client('bedrock-runtime', region_name=region)
    return make


def code_of(error):
    return ((getattr(error, 'response', None) or {}).get('Error') or {}).get('Code')


class Converse:
    def __init__(self, client_of, wait_s=60.0):
        self.client_of, self.wait_s, self.client, self.lock = client_of, wait_s, None, threading.Lock()

    def made(self):
        with self.lock:
            if self.client is None:
                self.client = self.client_of()
            return self.client

    def __call__(self, spec, model):
        asked = {'modelId': model, 'messages': [{'role': 'user', 'content': [{'text': spec['brief']}]}]}
        if spec.get('system'):
            asked['system'] = [{'text': spec['system']}]
        if spec.get('max_tokens'):
            asked['inferenceConfig'] = {'maxTokens': int(spec['max_tokens'])}
        client = self.made()
        try:
            answer = client.converse(**asked)
        except Exception as error:  # noqa: BLE001 - botocore's ClientError carries the code; a throttle waits
            if code_of(error) in LIMITED:
                raise api_sessions.Limited(f'{code_of(error)} from Bedrock', self.wait_s) from None
            raise
        content = ((answer.get('output') or {}).get('message') or {}).get('content') or []
        usage, stop = answer.get('usage') or {}, answer.get('stopReason')
        return api_sessions.completion(
            ''.join(block.get('text', '') for block in content), model, usage.get('inputTokens'),
            usage.get('outputTokens'), stop=STOPS.get(stop, stop),
            meters={'tokens_cache_read': usage.get('cacheReadInputTokens'),
                    'tokens_cache_write': usage.get('cacheWriteInputTokens')},
            latency_ms=(answer.get('metrics') or {}).get('latencyMs'),
            request_id=(answer.get('ResponseMetadata') or {}).get('RequestId'))
