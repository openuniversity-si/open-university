"""The Origin webhook ingress (PORT3): signature checked without a database, the delivery written to a durable queue,
202; a consumer records it once by its delivery id.

In-process: the ingress runs against a fake SSM (the forge's keys) and a fake SQS (a list), through the real SigV4
signing of infra/service/tower_infra/awsjson.py, and the consumer runs on a throwaway database of the toolchain's
PostgreSQL (TI1). Proven: a bad signature, a stale timestamp and a missing header answer 400/401/503 and write nothing
to the queue; a good one answers 202 after exactly one queue write and touches no database; the kept keys are read once
and read again (once per window) when a rotation makes them miss; a queue or key failure answers 503 (nothing accepted
that is not durable); the consumer records every queued delivery as the installation's forge event, a replay of the
same delivery id (Origin's retry or SQS's second delivery) leaves one event, a message it cannot record is reported for
retry and loses nothing; the module loads and runs without boto3, psycopg or a database connection. No network.
"""
import base64
import contextlib
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
from infra_db.psql import migrated  # noqa: E402
import test_db  # noqa: E402
from tower_infra import awsjson, ed25519, forge_webhooks, http_port, ingress, port, webhook_consumer  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
NOW = datetime.fromisoformat('2026-11-08T16:00:10+00:00')
SECRET, ROTATED = hashlib.sha256(b'the forge of the test').digest(), hashlib.sha256(b'its next key').digest()
ENVIRON = {'AWS_ACCESS_KEY_ID': 'AKIDEXAMPLE', 'AWS_SECRET_ACCESS_KEY': 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY',
           'AWS_SESSION_TOKEN': 'tok'}
QUEUE, PARAMETER = 'https://sqs.us-east-1.amazonaws.com/1/tower-port-webhooks', '/tower/port/forge-keys'
ACCEPTED, UNAUTHORIZED, BAD, RETRY, TOO_BIG = 202, 401, 400, 503, 413


def keys_of(*secrets):
    return {'keys': [[f'k{n}', base64.urlsafe_b64encode(ed25519.public_key(secret)).decode().rstrip('=')]
                     for n, secret in enumerate(secrets)]}


class Aws:
    """One fake transport for SSM and SQS: records every call, can fail on demand."""

    def __init__(self, keys):
        self.keys, self.queue, self.calls, self.fail_sqs, self.fail_ssm = keys, [], [], False, False

    def __call__(self, host, path, headers, body):
        action = headers['x-amz-target']
        self.calls.append(action)
        assert headers['authorization'].startswith('AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/'), headers
        assert path == '/' and 'x-amz-security-token' in headers
        payload = json.loads(body)
        if action == 'AmazonSSM.GetParameter':
            assert payload == {'Name': PARAMETER}
            return (500, b'{}') if self.fail_ssm else (200, json.dumps({'Parameter': {'Value': json.dumps(self.keys)}}).encode())
        assert action == 'AmazonSQS.SendMessage' and payload['QueueUrl'] == QUEUE
        if self.fail_sqs:
            return 500, b'{"__type":"InternalFailure"}'
        self.queue.append(payload['MessageBody'])
        return 200, b'{"MessageId":"m"}'


def make(aws, clock=None):
    return ingress.Ingress(awsjson.Client('sqs', 'us-east-1', '1.0', 'AmazonSQS', aws, ENVIRON),
                           awsjson.Client('ssm', 'us-east-1', '1.1', 'AmazonSSM', aws, ENVIRON), QUEUE, PARAMETER,
                           clock or (lambda: 0.0))


def delivery(kind='ping', installation=None, secret=SECRET, webhook='whd_1', when=NOW, sign=True):
    event = {'id': 'evt_1', 'type': kind, 'eventTime': '2026-11-08T16:00:00Z', 'payload': {'number': 7}}
    body = json.dumps({'deliveryId': webhook, 'appId': 'app_x', **({'installationId': installation}
                                                                     if installation else {}), 'event': event}).encode()
    stamp = str(int(when.timestamp()))
    signature = base64.b64encode(ed25519.sign(secret, forge_webhooks.digest(webhook, stamp, body).encode())).decode()
    headers = {'Webhook-Id': webhook, 'Webhook-Timestamp': stamp, 'Webhook-Event-Type': kind,
               'Webhook-Signature': f'v1ed,{signature}' if sign else 'v1ed,AAAA'}
    if installation:
        headers['Webhook-Installation-Id'] = installation
    return {'rawPath': forge_webhooks.PATH, 'requestContext': {'http': {'method': 'POST'}}, 'headers': headers,
            'body': body.decode()}


class Ingress(unittest.TestCase):
    def setUp(self):
        self.aws = Aws(keys_of(SECRET))
        self.ingress = make(self.aws)

    def test_an_accepted_delivery_is_exactly_one_durable_write_and_202(self):
        answered = self.ingress.handle(delivery(), NOW)
        self.assertEqual(answered['statusCode'], ACCEPTED)
        self.assertEqual(len(self.aws.queue), 1)
        queued = json.loads(self.aws.queue[0])
        self.assertEqual(queued['headers']['id'], 'whd_1')
        self.assertEqual(base64.b64decode(queued['body']), delivery()['body'].encode())  # the raw bytes, signed ones
        self.assertEqual(self.aws.calls, ['AmazonSSM.GetParameter', 'AmazonSQS.SendMessage'])

    def test_the_queued_message_carries_the_ingress_timing_with_no_extra_call_or_import(self):
        event = delivery()
        event['requestContext']['timeEpoch'] = int(NOW.timestamp() * 1000) - 1800  # a cold start's wait
        before = set(sys.modules)
        self.ingress.handle(event, NOW, cold=True, started=NOW.timestamp())
        self.assertEqual(self.aws.calls, ['AmazonSSM.GetParameter', 'AmazonSQS.SendMessage'])  # still one send
        self.assertEqual(set(sys.modules) - before, set())
        timing = json.loads(self.aws.queue[0])['ingress']
        self.assertEqual((timing['cold'], timing['gateway_to_handler_ms'], timing['origin_sent_to_handler_s']),
                         (True, 1800, 0.0))
        self.assertGreaterEqual(timing['pre_send_ms'], 1800)
        self.assertLess(len(self.aws.queue[0]) - len(json.dumps({k: v for k, v in json.loads(self.aws.queue[0]).items()
                                                                 if k != 'ingress'})), 200)  # a few numbers

    def test_the_keys_are_read_once_and_then_the_warm_path_is_one_queue_write(self):
        self.ingress.handle(delivery(webhook='a'), NOW)
        self.ingress.handle(delivery(webhook='b'), NOW)
        self.assertEqual(self.aws.calls.count('AmazonSSM.GetParameter'), 1)
        self.assertEqual(self.aws.calls.count('AmazonSQS.SendMessage'), 2)

    def test_a_signature_no_key_verifies_a_stale_timestamp_and_a_missing_header_write_nothing(self):
        refused = [
            (delivery(secret=ROTATED), RETRY),  # Origin retries; the keys may lag a rotation
            (delivery(sign=False), RETRY),
            (delivery(when=NOW - timedelta(seconds=forge_webhooks.TOLERANCE_S + 1)), UNAUTHORIZED)]
        for event, status in refused:
            self.assertEqual(self.ingress.handle(event, NOW)['statusCode'], status)
        event = delivery()
        del event['headers']['Webhook-Signature']
        self.assertEqual(self.ingress.handle(event, NOW)['statusCode'], BAD)
        tampered = delivery()
        tampered['body'] += ' '  # the body is what is signed
        self.assertEqual(self.ingress.handle(tampered, NOW)['statusCode'], RETRY)
        self.assertEqual(self.aws.queue, [])

    def test_a_401_and_a_400_touch_neither_the_keys_nor_the_queue(self):
        stale = delivery(when=NOW - timedelta(seconds=forge_webhooks.TOLERANCE_S + 1))
        self.assertEqual(self.ingress.handle(stale, NOW)['statusCode'], UNAUTHORIZED)
        self.assertEqual(self.ingress.handle({'rawPath': forge_webhooks.PATH, 'headers': {}, 'body': '{}',
                                              'requestContext': {'http': {'method': 'POST'}}}, NOW)['statusCode'], BAD)
        self.assertEqual(self.aws.calls, [])

    def test_a_rotation_is_picked_up_by_one_re_read_per_window(self):
        clock = [0.0]
        self.ingress = make(self.aws, lambda: clock[0])
        self.assertEqual(self.ingress.handle(delivery(), NOW)['statusCode'], ACCEPTED)
        self.aws.keys = keys_of(SECRET, ROTATED)
        clock[0] = 1.0  # inside the window: no new read, Origin is told to retry
        self.assertEqual(self.ingress.handle(delivery(secret=ROTATED, webhook='r1'), NOW)['statusCode'], RETRY)
        self.assertEqual(self.aws.calls.count('AmazonSSM.GetParameter'), 1)
        clock[0] = ingress.REFETCH_S + 1
        self.assertEqual(self.ingress.handle(delivery(secret=ROTATED, webhook='r2'), NOW)['statusCode'], ACCEPTED)
        self.assertEqual(self.aws.calls.count('AmazonSSM.GetParameter'), 2)

    def test_what_is_not_durable_is_not_accepted(self):
        self.aws.fail_sqs = True
        self.assertEqual(self.ingress.handle(delivery(), NOW)['statusCode'], RETRY)
        self.assertEqual(self.aws.queue, [])
        self.aws.fail_sqs, self.aws.fail_ssm = False, True
        self.ingress = make(self.aws)
        self.assertEqual(self.ingress.handle(delivery(), NOW)['statusCode'], RETRY)  # no keys, no verdict
        self.assertEqual(self.aws.queue, [])

    def test_only_the_webhook_route_and_a_bounded_body(self):
        self.assertEqual(self.ingress.handle({'rawPath': '/v1/jobs', 'requestContext': {'http': {'method': 'POST'}}},
                                             NOW)['statusCode'], 404)
        big = delivery()
        big['body'] = ' ' * (ingress.MAX_BODY + 1)
        self.assertEqual(self.ingress.handle(big, NOW)['statusCode'], TOO_BIG)

    def test_the_timing_line_carries_the_gateway_and_origin_stamps(self):
        event = delivery()
        event['requestContext']['timeEpoch'] = int(NOW.timestamp() * 1000) - 40
        line = json.loads(ingress.timing(event, NOW.timestamp(), {'statusCode': ACCEPTED}, True))
        self.assertEqual((line['ingress'], line['cold'], line['id'], line['gateway_to_handler_ms'],
                          line['origin_sent_to_handler_s']), (ACCEPTED, True, 'whd_1', 40, 0.0))

    def test_the_timing_line_flags_an_ack_over_the_limit_cold_or_warm_and_the_limit_is_the_registrys(self):
        event, now = delivery(), NOW.timestamp()
        # the handler's own clock is the injected one (D-069 item 5): it answers at `now`, the instant it started
        self.enterContext(mock.patch.object(ingress, 'time', types.SimpleNamespace(time=lambda: now)))
        event['requestContext']['timeEpoch'] = int(now * 1000) - 1200  # a cold start's wait before the handler
        slow = json.loads(ingress.timing(event, now, {'statusCode': ACCEPTED}, True))
        self.assertEqual((slow['over_limit'], slow['cold'], slow['limit_s']), (True, True, 1.0))
        self.assertGreaterEqual(slow['ack_ms'], 1200)
        event['requestContext']['timeEpoch'] = int(now * 1000) - 40
        fast = json.loads(ingress.timing(event, now, {'statusCode': ACCEPTED}, False))
        self.assertEqual((fast['over_limit'], fast['cold']), (False, False))
        self.assertTrue(json.loads(ingress.timing(event, now, {'statusCode': ACCEPTED}, False, 0.01))['over_limit'])
        registry = json.loads((ROOT / 'config/registry/medir/medir.webhook_ack_limit_s.json').read_text(encoding='utf-8'))
        self.assertEqual(ingress.ACK_LIMIT_S, registry['default'])

    def test_sigv4_matches_the_documented_shape(self):
        headers = awsjson.signed_headers('sqs.us-east-1.amazonaws.com', 'sqs', 'us-east-1', 'AmazonSQS.SendMessage', b'{}',
                                         '1.0', ENVIRON, NOW)
        self.assertIn('SignedHeaders=content-type;host;x-amz-date;x-amz-security-token;x-amz-target,', headers['authorization'])
        self.assertIn('Credential=AKIDEXAMPLE/20261108/us-east-1/sqs/aws4_request', headers['authorization'])
        self.assertEqual(headers, awsjson.signed_headers('sqs.us-east-1.amazonaws.com', 'sqs', 'us-east-1',
                                                         'AmazonSQS.SendMessage', b'{}', '1.0', ENVIRON, NOW))

    def test_the_ingress_loads_and_answers_without_boto3_psycopg_or_a_database(self):
        code = ('import sys\nsys.path.insert(0, %r)\nimport tower_infra.ingress as i\n'
                'print(",".join(n for n in ("boto3", "botocore", "psycopg", "sqlalchemy", "tower_infra.database", '
                '"tower_infra.port") if n in sys.modules))' % str(ROOT / 'infra' / 'service'))
        out = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, check=True,
                             timeout=60).stdout.strip()
        self.assertEqual(out, '')

    def test_a_cold_start_with_the_keys_in_the_environment_makes_no_ssm_call(self):
        """PORT5: TOWER_FORGE_KEYS (the stack copies the public keys in) seeds the ingress, so the first delivery needs
        only the queue write; a rotation (no seeded key verifies) re-reads the parameter at once, once."""
        environ = {**ENVIRON, 'AWS_REGION': 'us-east-1', 'TOWER_INGRESS_QUEUE_URL': QUEUE,
                   'TOWER_FORGE_KEYS_PARAMETER': PARAMETER, 'TOWER_FORGE_KEYS': json.dumps(keys_of(SECRET))}
        aws = Aws(keys_of(ROTATED))
        cold = ingress.build(environ)
        cold.sqs.transport = cold.ssm.transport = aws
        cold.sqs.environ = cold.ssm.environ = ENVIRON
        self.assertEqual(cold.handle(delivery(), NOW)['statusCode'], ACCEPTED)
        self.assertEqual(aws.calls, ['AmazonSQS.SendMessage'])
        rotated = cold.handle(delivery(secret=ROTATED, webhook='whd_2'), NOW)
        self.assertEqual(rotated['statusCode'], ACCEPTED)
        self.assertEqual(aws.calls, ['AmazonSQS.SendMessage', 'AmazonSSM.GetParameter', 'AmazonSQS.SendMessage'])
        for broken in ('', 'not json', '[]', '{"keys": []}'):
            self.assertIsNone(ingress.seeded({'TOWER_FORGE_KEYS': broken}))

    def run_fresh(self, root, environ):
        code = ('import sys, socket\nasked = []\n'
                'def refuse(host, *a, **k):\n    asked.append(host)\n    raise OSError("no network in the test")\n'
                'socket.getaddrinfo = refuse\nsys.path.insert(0, %r)\nimport time; t = time.perf_counter()\n'
                'import tower_infra.ingress\nms = (time.perf_counter() - t) * 1000\n'
                'import json\nprint(json.dumps({"modules": sorted(m for m in sys.modules if m.startswith("tower_infra")), '
                '"asked": asked, "ms": ms, "foreign": sorted(m.split(".")[0] for m in sys.modules if m.split(".")[0] '
                'not in sys.stdlib_module_names and not m.startswith(("tower_infra", "_", "sitecustomize")))}))' % str(root))
        out = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, check=True, timeout=60,
                             env={**os.environ, **environ}).stdout
        return json.loads(out.strip().splitlines()[-1])

    def test_the_ingress_imports_only_itself_and_the_standard_library_and_calls_no_ssm_at_init(self):
        """PORT5 import budget, fresh process: four tower_infra modules, nothing foreign, a short import, and (with
        the queue configured, as in Lambda) the init's only network attempt is the SQS connection, never SSM."""
        env = {'TOWER_INGRESS_QUEUE_URL': QUEUE, 'TOWER_FORGE_KEYS_PARAMETER': PARAMETER, 'AWS_REGION': 'us-east-1',
               'AWS_ACCESS_KEY_ID': 'a', 'AWS_SECRET_ACCESS_KEY': 'b', 'TOWER_FORGE_KEYS': json.dumps(keys_of(SECRET))}
        seen = self.run_fresh(ROOT / 'infra' / 'service', env)
        self.assertEqual(seen['modules'], ['tower_infra', 'tower_infra.awsjson', 'tower_infra.ed25519',
                                           'tower_infra.forge_webhooks', 'tower_infra.ingress'])
        self.assertEqual(seen['foreign'], [])
        self.assertEqual(seen['asked'], ['sqs.us-east-1.amazonaws.com'])
        self.assertLess(seen['ms'], 500)
        unseeded = self.run_fresh(ROOT / 'infra' / 'service', {**env, 'TOWER_FORGE_KEYS': ''})
        self.assertEqual(sorted(set(unseeded['asked'])), ['sqs.us-east-1.amazonaws.com', 'ssm.us-east-1.amazonaws.com'])

    def test_the_minimal_ingress_image_holds_exactly_the_modules_the_ingress_imports(self):
        import re
        import shutil
        import tempfile
        dockerfile = (ROOT / 'infra' / 'ingress' / 'Dockerfile').read_text(encoding='utf-8')
        copied = sorted(Path(name).name for name in re.findall(r'infra/service/tower_infra/(\S+\.py)', dockerfile))
        self.assertEqual(copied, ['awsjson.py', 'ed25519.py', 'forge_webhooks.py', 'ingress.py'])
        self.assertIn('FROM public.ecr.aws/lambda/python:3.12-arm64', dockerfile)
        self.assertIn('CMD ["tower_infra.ingress.handler"]', dockerfile)
        with tempfile.TemporaryDirectory() as root:  # the image's layout: the files, an empty package, nothing else
            package = Path(root) / 'tower_infra'
            package.mkdir()
            shutil.copy(ROOT / 'infra' / 'ingress' / '__init__.py', package / '__init__.py')
            for name in copied:
                shutil.copy(ROOT / 'infra' / 'service' / 'tower_infra' / name, package / name)
            seen = self.run_fresh(root, {})
        self.assertEqual(seen['foreign'], [])
        self.assertEqual(len(seen['modules']), 5)


class Stack(unittest.TestCase):
    """infra/aws/stacks/40-port.json: what makes the ingress fast and the queue safe."""

    def setUp(self):
        self.template = json.loads((ROOT / 'infra/aws/stacks/40-port.json').read_text(encoding='utf-8'))
        self.resources = self.template['Resources']

    def test_the_ingress_has_no_vpc_and_no_database_and_only_two_permissions(self):
        function = self.resources['IngressFunction']['Properties']
        self.assertNotIn('VpcConfig', function)
        self.assertEqual((function['Runtime'], function['Handler']), ('python3.12', 'tower_infra.ingress.handler'))
        self.assertEqual(function['MemorySize'], {'Ref': 'IngressMemory'})
        self.assertGreaterEqual(self.template['Parameters']['IngressMemory']['Default'], 1024)
        self.assertFalse([name for name in function['Environment']['Variables'] if name.startswith('TOWER_DB')])
        actions = [item['Action'] for item in self.resources['IngressRole']['Properties']['Policies'][0]
                   ['PolicyDocument']['Statement']]
        self.assertEqual(actions, [['logs:CreateLogStream', 'logs:PutLogEvents'], 'ssm:GetParameter', 'sqs:SendMessage'])

    def test_the_port_api_runs_on_256_mb_since_1024_did_not_shorten_its_cold_start(self):
        # PORT-MEMORY-BACK (the Torre, 13/11, answer to items 1 to 5): #686/#687 gave tower-port-api 1024 MB for its cold
        # start; measured from inside AWS, the init was 432 to 630 ms on 256 MB and 475 to 610 ms on 1024 MB (p50 502 ms,
        # p99 630 ms, N=10), every one begun before its call (the calls answered in 38/49 ms p50/p99), and the webhook ACK
        # (API Gateway -> SQS) never runs this Lambda. 256 MB again
        self.assertEqual(self.resources['PortFunction']['Properties']['MemorySize'], 256)
        # PORT-MEMORY-LIVE: the live alias names a published version, whose configuration (its memory too) is frozen at its
        # publication: #686 changed $LATEST to 1024 MB and the alias went on serving 256 MB. The version's description names
        # the memory, so a change of it publishes a version and the stack moves the alias to it
        memory = self.resources['PortFunction']['Properties']['MemorySize']
        self.assertIn(f'with {memory} MB', self.resources['PortVersion']['Properties']['Description']['Fn::Sub'])

    def test_the_stack_seeds_the_keys_and_runs_the_ingress_from_its_own_zip_behind_the_alias(self):
        function = self.resources['IngressFunction']['Properties']
        self.assertEqual(function['Environment']['Variables']['TOWER_FORGE_KEYS'], {'Ref': 'ForgeKeys'})
        self.assertEqual(self.template['Parameters']['ForgeKeys']['Default'], '/tower/port/forge-keys')
        self.assertEqual(function['Code']['S3Key'], {'Ref': 'IngressCode'})  # DEP8: the zip of lambda_package, not an image
        self.assertEqual(self.template['Parameters']['IngressCode']['Default'], 'artifacts/lambda/tower-port-ack-ingress/unset.zip')
        self.assertEqual((function['Runtime'], function['Handler'], function['Architectures']),
                         ('python3.12', 'tower_infra.ingress.handler', ['arm64']))
        self.assertNotIn('Layers', function)  # stdlib only

    def test_the_stack_hands_the_ack_limit_to_the_ingress_and_it_defaults_to_the_registrys(self):
        function = self.template['Resources']['IngressFunction']['Properties']
        self.assertEqual(function['Environment']['Variables']['TOWER_INGRESS_ACK_LIMIT_S'], {'Ref': 'IngressAckLimitS'})
        registry = json.loads((ROOT / 'config/registry/medir/medir.webhook_ack_limit_s.json').read_text(encoding='utf-8'))
        self.assertEqual(self.template['Parameters']['IngressAckLimitS']['Default'], registry['default'])

    def test_the_webhook_url_is_unchanged_and_the_template_default_is_the_lambda(self):
        route = self.resources['WebhookRoute']['Properties']
        self.assertEqual(route['RouteKey'], 'POST ' + forge_webhooks.PATH)
        self.assertEqual(route['Target'], {'Fn::If': ['AckBySqs', {'Fn::Sub': 'integrations/${AckIntegration}'},
                                                       {'Fn::Sub': 'integrations/${IngressIntegration}'}]})
        self.assertEqual(self.template['Conditions']['AckBySqs'], {'Fn::Equals': [{'Ref': 'AckPath'}, 'sqs']})
        self.assertEqual(self.template['Parameters']['AckPath']['Default'], 'lambda')  # the template Default is the fallback; production is sqs by infra/aws/parameters.json (PORT7-PROD), always passed by deploy.sh
        self.assertEqual(self.template['Parameters']['AckPath']['AllowedValues'], ['lambda', 'sqs'])
        self.assertEqual(self.resources['DefaultStage']['Properties']['StageName'], '$default')

    def test_the_sqs_ack_resources_exist_only_when_the_path_is_sqs(self):
        for name in ('AckRole', 'AckIntegration'):
            self.assertEqual(self.resources[name].get('Condition'), 'AckBySqs', name)
        for name, resource in self.resources.items():  # nothing unconditional may depend on them
            if name not in ('AckRole', 'AckIntegration', 'WebhookRoute'):
                self.assertNotIn('Ack', json.dumps({k: v for k, v in resource.items()}).replace('AckLimit', '').replace('IngressAck', ''), name)

    def test_the_rollback_keeps_the_old_lambda_path_whole(self):
        old = self.resources['IngressIntegration']['Properties']
        self.assertEqual(old['IntegrationUri'], {'Ref': 'IngressAlias'})  # DEP8: the alias live, the pointer the fast deploy swaps
        self.assertIn('InvokeIngressFromTheApi', self.resources)
        self.assertIn('AckPath=lambda', self.template['Parameters']['AckPath']['Description'])
        self.assertIn('IngressAlias', json.dumps(self.template['Resources']['IngressIntegration']))

    def test_the_ack_integration_sends_the_raw_delivery_to_the_one_queue_and_answers_from_the_mapping(self):
        integration = self.resources['AckIntegration']['Properties']
        self.assertEqual((integration['IntegrationType'], integration['IntegrationSubtype']), ('AWS_PROXY', 'SQS-SendMessage'))
        self.assertNotIn('IntegrationUri', integration)  # no Lambda anywhere in the ACK
        request = integration['RequestParameters']
        self.assertEqual(request['QueueUrl'], {'Ref': 'WebhookQueue'})
        self.assertEqual(request['MessageBody'], '$request.body')
        attributes = json.loads(request['MessageAttributes'])
        self.assertEqual(sorted(attributes), ['webhook-id', 'webhook-signature', 'webhook-timestamp'])  # probe variant C
        self.assertNotIn('requestTimeEpoch', json.dumps(request))  # probe variant D was refused by API Gateway
        self.assertEqual(attributes['webhook-signature']['StringValue'], '${request.header.webhook-signature}')  # PORT7-PROD: the proven kbare form
        self.assertNotIn('$request.header', request['MessageAttributes'].replace('${request.header', ''))  # `$request.header.x` in the string is a 400
        self.assertEqual(set(webhook_consumer.HEADERS), {name.split('-')[1] for name in attributes if name.startswith('webhook-')})
        self.assertNotIn('ResponseParameters', integration)  # PORT7-PROD: untested 200->202 mapping dropped; Origin takes any 2xx
        self.assertEqual(integration['CredentialsArn'], {'Fn::GetAtt': ['AckRole', 'Arn']})

    def test_the_production_integration_is_the_shape_the_canary_proved(self):
        # ACK-CANARY-RETIRE: the canary stack chose this shape (kbare, 09/11: all three headers by ${request.header.x}, the
        # role with no trust Condition) and left; what it held is said here by value
        prod = self.resources['AckIntegration']['Properties']
        attribute = lambda name: {'DataType': 'String', 'StringValue': '${request.header.%s}' % name}  # noqa: E731
        self.assertEqual(json.loads(prod['RequestParameters']['MessageAttributes']),
                         {name: attribute(name) for name in ('webhook-id', 'webhook-timestamp', 'webhook-signature')})
        self.assertEqual(prod['RequestParameters']['MessageBody'], '$request.body')
        self.assertEqual({key: prod[key] for key in ('IntegrationType', 'IntegrationSubtype', 'PayloadFormatVersion', 'TimeoutInMillis')},
                         {'IntegrationType': 'AWS_PROXY', 'IntegrationSubtype': 'SQS-SendMessage', 'PayloadFormatVersion': '1.0',
                          'TimeoutInMillis': 5000})
        self.assertEqual(set(prod), {'ApiId', 'CredentialsArn', 'IntegrationType', 'IntegrationSubtype', 'PayloadFormatVersion',
                                     'TimeoutInMillis', 'RequestParameters'})
        self.assertEqual(prod['RequestParameters']['QueueUrl'], {'Ref': 'WebhookQueue'})

    def test_the_ack_role_trust_has_no_condition(self):
        trust = self.resources['AckRole']['Properties']['AssumeRolePolicyDocument']
        self.assertEqual(trust, {'Version': '2012-10-17', 'Statement': [  # a Condition makes API Gateway answer 500 (live, 09/11)
            {'Effect': 'Allow', 'Principal': {'Service': 'apigateway.amazonaws.com'}, 'Action': 'sts:AssumeRole'}]})
        self.assertNotIn('Condition', json.dumps(trust))
        self.assertIn('Confused deputy', self.resources['AckRole']['Properties']['Description'])

    def test_the_ack_role_may_only_send_to_the_webhook_queue_inside_the_boundary(self):
        role = self.resources['AckRole']['Properties']
        self.assertTrue(role['RoleName'].startswith('tower-app-'))
        self.assertEqual(role['PermissionsBoundary'], {'Fn::Sub': 'arn:${AWS::Partition}:iam::${AWS::AccountId}:policy/tower-boundary'})
        self.assertEqual(role['AssumeRolePolicyDocument']['Statement'][0]['Principal'], {'Service': 'apigateway.amazonaws.com'})
        self.assertEqual(len(role['Policies']), 1)
        statements = role['Policies'][0]['PolicyDocument']['Statement']
        self.assertEqual([(item['Effect'], item['Action'], item['Resource']) for item in statements],
                         [('Allow', 'sqs:SendMessage', {'Fn::GetAtt': ['WebhookQueue', 'Arn']})])
        self.assertNotIn('*', json.dumps(statements))
        self.assertNotIn('ProvisionedConcurrencyConfig', json.dumps(self.template))

    def test_a_delivery_is_kept_until_recorded_and_ends_in_the_dead_letter_queue(self):
        queue = self.resources['WebhookQueue']['Properties']
        self.assertEqual(queue['RedrivePolicy']['deadLetterTargetArn'], {'Fn::GetAtt': ['WebhookDlq', 'Arn']})
        self.assertGreaterEqual(queue['RedrivePolicy']['maxReceiveCount'], 3)
        consumer = self.resources['WebhookFunction']['Properties']
        self.assertGreaterEqual(queue["VisibilityTimeout"], consumer["Timeout"])  # a message is not redelivered while it is processed
        self.assertEqual(self.resources['WebhookDlq']['Properties']['MessageRetentionPeriod'], 1209600)
        source = self.resources['WebhookSource']['Properties']
        self.assertEqual(source['FunctionResponseTypes'], ['ReportBatchItemFailures'])
        self.assertLessEqual(source['ScalingConfig']['MaximumConcurrency'], 2)  # the database connections stay few
        self.assertIn('VpcConfig', consumer)
        self.assertEqual(consumer['Handler'], 'tower_infra.webhook_consumer.handler')

    def test_the_service_publishes_the_keys_the_ingress_reads(self):
        service = (ROOT / 'infra/aws/stacks/30-service.json').read_text(encoding='utf-8')
        self.assertIn('"TOWER_FORGE_KEYS_PARAMETER"', service)
        self.assertEqual(service.count('parameter/tower/port/forge-keys'), 1)
        self.assertEqual(self.resources['IngressFunction']['Properties']['Environment']['Variables']
                         ['TOWER_FORGE_KEYS_PARAMETER'], '/tower/port/forge-keys')


class Consumer(unittest.TestCase):
    def setUp(self):
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        self.who = ('installation', None)
        self.tenant = port.register_tenant(self.db, self.who, 'torre', port.sha256('torre'))
        port.register_executor(self.db, self.who, 'origin-forge', 'forge', None, None)
        self.aws = Aws(keys_of(SECRET))
        self.ingress = make(self.aws)

    def installation(self):
        port.configure_executor(self.db, self.who, 'origin-forge', {'installations': {'i_x': self.tenant}})

    def batch(self):
        return {'Records': [{'messageId': f'm{n}', 'body': body} for n, body in enumerate(self.aws.queue)]}

    def events(self):
        return self.db.rows("select type, tenant_id::text from log.event where type like 'forge.%' order by occurred_at")

    def test_a_queued_delivery_becomes_one_event_even_when_replayed(self):
        self.installation()
        self.ingress.handle(delivery(kind='pull_request.created', installation='i_x', webhook='w1'), NOW)
        self.ingress.handle(delivery(kind='pull_request.created', installation='i_x', webhook='w1'), NOW)  # Origin's retry
        self.ingress.handle(delivery(kind='ping', webhook='w2'), NOW)
        self.assertEqual(len(self.aws.queue), 3)
        batch = self.batch()
        batch['Records'].append(batch['Records'][0])  # SQS delivering the same message twice
        self.assertEqual(webhook_consumer.consume(batch, self.db), {'batchItemFailures': []})
        self.assertEqual(sorted(self.events()), sorted([('forge.pull_request.created', self.tenant), ('forge.ping', None)]))

    def test_the_ingress_timing_is_stored_once_per_delivery_and_an_old_message_still_records(self):
        self.installation()
        event = delivery(kind='pull_request.created', installation='i_x', webhook='w1')
        event['requestContext']['timeEpoch'] = int(NOW.timestamp() * 1000) - 1500
        self.ingress.handle(event, NOW, cold=True, started=NOW.timestamp())
        self.ingress.handle(event, NOW, cold=False, started=NOW.timestamp())  # Origin's retry, a warm one
        old = json.loads(self.aws.queue[0])
        del old['ingress']
        old['headers']['id'] = 'w_old'
        self.aws.queue.append(json.dumps(old))
        self.assertEqual(webhook_consumer.consume(self.batch(), self.db), {'batchItemFailures': []})
        found = {name: json.loads(timing) if timing else None for name, timing in self.db.rows(
            "select payload->'webhook'->>'id', payload->'ingress' from log.event where type = 'forge.pull_request.created'")}
        self.assertEqual(set(found), {'w1', 'w_old'})
        self.assertEqual((found['w1']['cold'], found['w1']['gateway_to_handler_ms']), (True, 1500))  # the first, once
        self.assertGreaterEqual(found['w1']['pre_send_ms'], 1500)
        self.assertEqual(set(found['w1']), set(webhook_consumer.TIMING))
        self.assertIsNone(found['w_old'])

    def test_a_message_that_cannot_be_recorded_is_reported_for_retry_and_nothing_is_lost(self):
        self.ingress.handle(delivery(kind='pull_request.created', installation='i_x', webhook='w1'), NOW)
        self.ingress.handle(delivery(kind='ping', webhook='w2'), NOW)
        failed = webhook_consumer.consume(self.batch(), self.db)  # no executor maps i_x yet: the first fails
        self.assertEqual(failed, {'batchItemFailures': [{'itemIdentifier': 'm0'}]})
        self.assertEqual(self.events(), [('forge.ping', None)])
        self.installation()  # the mapping arrives; SQS redelivers the retained message
        self.assertEqual(webhook_consumer.consume({'Records': [self.batch()['Records'][0]]}, self.db),
                         {'batchItemFailures': []})
        self.assertEqual(sorted(self.events(), key=str), sorted([('forge.ping', None),
                                                                 ('forge.pull_request.created', self.tenant)], key=str))
        poison = {'Records': [{'messageId': 'p', 'body': 'not json'}]}
        self.assertEqual(webhook_consumer.consume(poison, self.db), {'batchItemFailures': [{'itemIdentifier': 'p'}]})

    def test_a_message_s_last_failed_receive_is_one_event_of_the_configuration_tenant(self):
        # WEBHOOK-DEAD-ALERT: nothing reads the dead-letter queue; the failure that sends a message there is written once
        def dead():
            return [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in self.db.rows(
                "select e.payload from log.event e join work.tenant t on t.id = e.tenant_id "
                "where e.type = %(type)s and t.name = 'torre' order by e.occurred_at", {'type': webhook_consumer.DEAD_EVENT})]

        def poison(receives):
            return {'Records': [{'messageId': 'p', 'body': 'not json', 'attributes': {'ApproximateReceiveCount': str(receives)}}]}
        with contextlib.redirect_stdout(io.StringIO()) as out:
            for receives in range(1, webhook_consumer.MAX_RECEIVES):
                self.assertEqual(webhook_consumer.consume(poison(receives), self.db), {'batchItemFailures': [{'itemIdentifier': 'p'}]})
            self.assertEqual((dead(), out.getvalue()), ([], ''))  # a receive that is not the last is only a retry
            for _ in (1, 2):  # the last, and SQS delivering it once more: one event
                self.assertEqual(webhook_consumer.consume(poison(webhook_consumer.MAX_RECEIVES), self.db),
                                 {'batchItemFailures': [{'itemIdentifier': 'p'}]})
        (said,) = dead()
        self.assertEqual((said['message'], said['receives'], said['webhook_id']), ('p', webhook_consumer.MAX_RECEIVES, None))
        self.assertIn('JSONDecodeError', said['error'])
        self.assertEqual(json.loads(out.getvalue().splitlines()[0])['webhook_dead'], True)
        redrive = json.loads((ROOT / 'infra/aws/stacks/40-port.json').read_text())['Resources']['WebhookQueue']['Properties']
        self.assertEqual(redrive['RedrivePolicy']['maxReceiveCount'], webhook_consumer.MAX_RECEIVES)

    def test_a_dead_message_whose_event_cannot_be_written_still_fails_as_before(self):
        class Away:
            def rows(self, sql, params=None):
                raise RuntimeError('the database is away')
        record = {'messageId': 'p', 'body': 'not json', 'attributes': {'ApproximateReceiveCount': '9'}}
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(webhook_consumer.consume({'Records': [record]}, Away()), {'batchItemFailures': [{'itemIdentifier': 'p'}]})


class Direct(unittest.TestCase):
    """PORT7: API Gateway queued the raw delivery; the consumer verifies it. No clock, no database server: a fake log."""

    def setUp(self):
        self.written, self.keys = [], [keys_of(SECRET)]
        self.tenant = 'tenant-1'

    def rows(self, sql, params=None):
        if sql == forge_webhooks.LATEST_KEYS:
            return [(json.dumps(self.keys[0]),)] if self.keys else []
        if sql == forge_webhooks.TENANT:
            return [(self.tenant,)]
        assert sql == forge_webhooks.WRITE, sql
        if any(item['seen'] == params['seen'] for item in self.written):
            return []
        self.written.append(params)
        return [(params['event'],)]

    def record(self, message, secret=SECRET, sent_after_ms=40, **overrides):
        """The SQS record API Gateway's mapping would produce from delivery(...), received sent_after_ms later."""
        event = delivery(kind='pull_request.created', installation='i_x', secret=secret, **overrides)
        headers = {name.lower(): value for name, value in event['headers'].items()}
        requested = int(NOW.timestamp() * 1000)
        attrs = {f'webhook-{name}': {'stringValue': headers[f'webhook-{name}'], 'dataType': 'String'}
                 for name in ('id', 'timestamp', 'signature')}
        return {'messageId': message, 'body': event['body'], 'messageAttributes': attrs,
                'attributes': {'SentTimestamp': str(requested + sent_after_ms)}}

    def consume(self, *records):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            answered = webhook_consumer.consume({'Records': list(records)}, self)
        return answered, [json.loads(line) for line in out.getvalue().splitlines()]

    def test_a_valid_delivery_is_recorded_once_with_the_api_gateway_ack_timing(self):
        record = self.record('m1')
        answered, logged = self.consume(record, record)
        self.assertEqual((answered, logged, len(self.written)), ({'batchItemFailures': []}, [], 1))
        payload = json.loads(self.written[0]['payload'])
        self.assertEqual(payload['webhook']['id'], 'whd_1')
        self.assertEqual(payload['ingress'], {'cold': False, 'gateway_to_handler_ms': None, 'pre_send_ms': None,
                                              'origin_sent_to_handler_s': 0.0, 'ack_path': 'sqs'})
        self.assertEqual(set(payload['ingress']), set(webhook_consumer.TIMING))
        self.assertEqual(payload['delivery']['event']['type'], 'pull_request.created')

    def test_the_exact_sqs_shape_of_the_kbare_attributes_is_recorded_with_the_sent_timestamp_as_gateway_time(self):
        """PORT7-PROD: what SQS delivers to the Lambda for MessageAttributes {DataType:String, StringValue:...} (lowercase header names):
        messageAttributes.<name> = {stringValue, stringListValues, binaryListValues, dataType}; attributes.SentTimestamp a string of ms."""
        made = self.record('m1', sent_after_ms=300)
        sqs_shape = {
            'messageId': 'a1b2c3d4-0000-4000-8000-000000000001', 'receiptHandle': 'AQEB...', 'body': made['body'],
            'attributes': {'ApproximateReceiveCount': '1', 'SentTimestamp': made['attributes']['SentTimestamp'],
                           'SenderId': 'AROAEXAMPLE:APIGateway', 'ApproximateFirstReceiveTimestamp': made['attributes']['SentTimestamp']},
            'messageAttributes': {name: {'stringValue': value['stringValue'], 'stringListValues': [], 'binaryListValues': [],
                                         'dataType': 'String'} for name, value in made['messageAttributes'].items()},
            'md5OfBody': 'x', 'md5OfMessageAttributes': 'y', 'eventSource': 'aws:sqs',
            'eventSourceARN': 'arn:aws-partition:sqs:sa-east-1:123456789012:tower-port-webhooks', 'awsRegion': 'sa-east-1'}
        self.assertEqual(sorted(sqs_shape['messageAttributes']), ['webhook-id', 'webhook-signature', 'webhook-timestamp'])
        answered, logged = self.consume(sqs_shape)
        self.assertEqual((answered, logged, len(self.written)), ({'batchItemFailures': []}, [], 1))
        ingress = json.loads(self.written[0]['payload'])['ingress']
        self.assertEqual((ingress['ack_path'], ingress['origin_sent_to_handler_s']), ('sqs', 0.3))  # SentTimestamp judged as gateway time

    def test_a_forged_signature_is_dropped_with_its_reason_and_never_reaches_the_registry(self):
        wrong = self.record('m1', secret=ROTATED)
        tampered = self.record('m2')
        tampered['body'] = tampered['body'].replace('"number": 7', '"number": 8')
        stale = self.record('m3', when=NOW - timedelta(seconds=forge_webhooks.TOLERANCE_S + 5))
        silent = self.record('m4')
        silent['attributes'] = {}
        answered, logged = self.consume(wrong, tampered, stale, silent)
        self.assertEqual(answered, {'batchItemFailures': []})  # a verdict, so deleted, not retried
        self.assertEqual(self.written, [])
        self.assertEqual([item['id'] for item in logged], ['whd_1'] * 4)
        self.assertTrue(all(item['webhook_dropped'] for item in logged))
        self.assertTrue(logged[0]['reason'].startswith('invalid signature: '))
        self.assertIn('no key of the forge verifies', logged[0]['reason'])
        self.assertIn('more than 300 s', logged[2]['reason'])
        self.assertIn('no SentTimestamp', logged[3]['reason'])

    def test_a_delivery_that_waited_in_the_queue_is_judged_at_its_sent_timestamp_not_at_the_consumers(self):
        waited = self.record('m1')  # SentTimestamp is set once and kept on redelivery: the consumer's clock never enters
        self.assertEqual(self.consume(waited)[0], {'batchItemFailures': []})
        self.assertEqual(len(self.written), 1)

    def test_a_missing_header_is_dropped_and_no_keys_yet_is_retried_not_dropped(self):
        bare = self.record('m1')
        del bare['messageAttributes']['webhook-signature']
        answered, logged = self.consume(bare)
        self.assertEqual((answered, len(logged)), ({'batchItemFailures': []}, 1))
        self.assertIn('needs webhook-id', logged[0]['reason'])
        self.keys = []
        answered, logged = self.consume(self.record('m2'))
        self.assertEqual((answered, logged, self.written), ({'batchItemFailures': [{'itemIdentifier': 'm2'}]}, [], []))

    def test_a_valid_delivery_for_an_unknown_installation_is_still_retried_as_before(self):
        self.tenant = None
        self.assertEqual(self.consume(self.record('m1'))[0], {'batchItemFailures': [{'itemIdentifier': 'm1'}]})

    def test_the_ingress_lambda_envelopes_of_the_rollback_path_are_still_recorded(self):
        aws = Aws(keys_of(SECRET))
        make(aws).handle(delivery(kind='pull_request.created', installation='i_x'), NOW)
        record = {'messageId': 'old', 'body': aws.queue[0]}  # no attributes: PORT3's shape
        self.assertEqual(self.consume(record)[0], {'batchItemFailures': []})
        self.assertEqual(len(self.written), 1)


if __name__ == '__main__':
    unittest.main()
