"""PORT7-SWITCH: the post-deploy ACK smoke and its rollback, with an injected aws runner and HTTP poster. No network."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
import ack_smoke  # noqa: E402
from tower_infra import forge_webhooks  # noqa: E402

OUTPUTS = [{'OutputKey': 'PortUrl', 'OutputValue': 'https://x.execute-api.us-east-1.amazonaws.com'},
           {'OutputKey': 'AckPath', 'OutputValue': 'sqs'}]
ID = 'whd_smoke_test00000000'


class Fake:
    def __init__(self, outputs=OUTPUTS, drop='invalid signature: 503: no key', logs_error=None, status=202, seconds=0.2):
        self.calls, self.outputs, self.drop, self.logs_error = [], outputs, drop, logs_error
        self.posted, self.status, self.seconds, self.slept = [], status, seconds, []

    def aws(self, argv):
        self.calls.append(argv)
        if argv[1] == 'describe-stacks':
            return (0, json.dumps(self.outputs), '') if self.outputs is not None else (255, '', 'denied')
        if argv[0] == 'logs':
            if self.logs_error:
                return 254, '', self.logs_error
            line = json.dumps({'webhook_dropped': True, 'reason': self.drop, 'id': ID})
            return 0, json.dumps({'events': [{'message': line}] if self.drop else []}), ''
        return 0, 'ok', ''

    def post(self, url, body, headers):
        self.posted.append((url, body, headers))
        return self.status, self.seconds

    def main(self, *argv):
        lines = []
        code = ack_smoke.main(list(argv), runner=self.aws, poster=self.post, sleep=self.slept.append, out=lines.append)
        return code, lines


def rolled_back(fake):
    return [c for c in fake.calls if c[:2] == ['cloudformation', 'deploy']]


class AckSmoke(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(ack_smoke.uuid, 'uuid4', lambda: type('U', (), {'hex': 'test' + '0' * 28})())
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_route_is_the_forge_route(self):
        self.assertEqual(ack_smoke.ROUTE, forge_webhooks.PATH)

    def test_the_real_consumer_drops_the_smokes_delivery_as_an_invalid_signature(self):
        # ACK-SMOKE-SIGNATURE: the fake log below says what the consumer is expected to log; this runs the consumer itself
        # on the smoke's own request, which is what failed live (tag 'v1,': dropped as 400, the smoke red, AckPath=lambda)
        from tower_infra import webhook_consumer
        self.assertEqual(ack_smoke.SIGNATURE_TAG, forge_webhooks.TAG)
        fake = Fake()
        ack_smoke.run_smoke({o['OutputKey']: o['OutputValue'] for o in OUTPUTS}, fake.aws, fake.post,
                            clock=lambda: 1000.0, sleep=fake.slept.append, new_id=lambda: ID)
        _url, body, headers = fake.posted[0]
        record = {'body': body.decode(), 'attributes': {'SentTimestamp': '1000000'},
                  'messageAttributes': {name: {'stringValue': value} for name, value in headers.items()
                                        if name.startswith('webhook-')}}

        class Keys:
            def rows(self, sql, params=None):
                return [(json.dumps({'keys': [['k1', 'A' * 43]]}),)]
        rule = {'tolerance_s': 300, 'drop_stale': True, 'drop_bad_signature': True}
        with self.assertRaises(webhook_consumer.Dropped) as dropped:
            webhook_consumer.screen(record, Keys(), rule)
        self.assertTrue(str(dropped.exception).startswith('invalid signature'), dropped.exception)

    def test_a_fast_ack_and_a_dropped_invalid_signature_pass_and_nothing_is_rolled_back(self):
        fake = Fake()
        ok, said = ack_smoke.run_smoke({o['OutputKey']: o['OutputValue'] for o in OUTPUTS}, fake.aws, fake.post,
                                       clock=lambda: 1000.0, sleep=fake.slept.append, new_id=lambda: ID)
        self.assertTrue(ok, said)
        url, body, headers = fake.posted[0]
        self.assertEqual(url, 'https://x.execute-api.us-east-1.amazonaws.com' + forge_webhooks.PATH)
        self.assertEqual((headers['webhook-id'], headers['webhook-timestamp']), (ID, '1000'))
        self.assertEqual(headers['webhook-signature'], ack_smoke.UNSIGNED)
        self.assertTrue(any('dropped by the consumer: invalid signature' in line for line in said))
        self.assertEqual(rolled_back(fake), [])

    def test_main_passes_with_exit_0_and_does_not_roll_back(self):
        fake = Fake()
        code, lines = fake.main('--wait', '0')
        self.assertEqual((code, rolled_back(fake)), (0, []))

    def test_a_slow_ack_fails_and_rolls_back_to_lambda_with_the_role_and_commit(self):
        fake = Fake(seconds=1.2)
        code, lines = fake.main('--role-arn', 'arn:aws-partition:iam::1:role/x', '--commit', 'abc', '--wait', '0')
        self.assertEqual(code, 1)
        self.assertTrue(any('took 1.200 s' in line for line in lines))
        (call,) = rolled_back(fake)
        self.assertIn('AckPath=lambda', call)
        self.assertEqual(call[call.index('--stack-name') + 1], 'tower-app-port')
        self.assertEqual(call[call.index('--role-arn') + 1], 'arn:aws-partition:iam::1:role/x')
        self.assertEqual(call[-2:], ['project=tower', 'commit=abc'])
        self.assertTrue(any('rolled back: AckPath=lambda' in line for line in lines))

    def test_an_error_status_fails_and_rolls_back_without_waiting_for_a_drop(self):
        fake = Fake(status=403)
        code, lines = fake.main('--wait', '0')
        self.assertEqual((code, len(rolled_back(fake))), (1, 1))
        self.assertFalse([c for c in fake.calls if c[0] == 'logs'])

    def test_a_connection_failure_fails_and_rolls_back(self):
        fake = Fake(status=None)
        self.assertEqual((fake.main('--wait', '0')[0], len(rolled_back(fake))), (1, 1))

    def test_a_delivery_never_dropped_fails_after_the_wait(self):
        fake = Fake(drop=None)
        ok, said = ack_smoke.run_smoke({'AckPath': 'sqs', 'PortUrl': 'https://h'}, fake.aws, fake.post,
                                       sleep=fake.slept.append, wait_s=15, every_s=5, new_id=lambda: ID)
        self.assertFalse(ok)
        self.assertEqual(fake.slept, [5, 5, 5])
        self.assertTrue(any('no webhook_dropped line' in line for line in said))

    def test_a_drop_for_another_reason_fails(self):
        fake = Fake(drop='400: a webhook needs webhook-id')
        ok, said = ack_smoke.run_smoke({'AckPath': 'sqs', 'PortUrl': 'https://h'}, fake.aws, fake.post, new_id=lambda: ID)
        self.assertFalse(ok)
        self.assertTrue(any('wrong reason' in line for line in said))

    def test_an_unreadable_consumer_log_leaves_the_drop_unverified_but_the_ack_still_decides(self):
        fake = Fake(logs_error='AccessDeniedException: not authorized to perform logs:FilterLogEvents')
        ok, said = ack_smoke.run_smoke({'AckPath': 'sqs', 'PortUrl': 'https://h'}, fake.aws, fake.post, new_id=lambda: ID)
        self.assertTrue(ok)
        self.assertTrue(any(line.startswith('UNVERIFIED') for line in said))
        slow = Fake(logs_error='AccessDenied', seconds=2)
        self.assertFalse(ack_smoke.run_smoke({'AckPath': 'sqs', 'PortUrl': 'https://h'}, slow.aws, slow.post)[0])

    def test_the_result_is_one_final_json_line_and_unverified_is_never_red(self):
        fake = Fake(logs_error='AccessDenied')
        code, lines = fake.main('--wait', '0')
        self.assertEqual(code, 0)
        result = json.loads(lines[-1])
        self.assertEqual((result['ok'], result['http_status'], result['drop']), (True, 202, 'unverified'))
        self.assertEqual(set(result), {'ok', 'http_status', 'ms', 'body', 'headers', 'drop', 'reason'})
        good = Fake()
        self.assertEqual(json.loads(good.main('--wait', '0')[1][-1])['drop'], 'verified')

    def test_a_non_2xx_reports_headers_and_the_body_without_secrets(self):
        fake = Fake(status=500)
        fake.post = lambda url, body, headers: (500, 0.1, {'apigw-requestid': 'RID=', 'content-type': 'application/json',
                                                           'body': '{"message":"Internal","password":"hunter-two"}' + 'x' * 300})
        code, lines = fake.main('--no-rollback', '--wait', '0')
        self.assertEqual(code, 1)
        text = '\n'.join(lines)
        self.assertIn('apigw-requestid=RID=', text)
        self.assertIn('content-type=application/json', text)
        self.assertIn('Internal', text)
        self.assertNotIn('hunter-two', text)
        result = json.loads(lines[-1])
        self.assertEqual((result['ok'], result['http_status'], result['drop']), (False, 500, 'missing'))
        self.assertLessEqual(len(result['body']), 300)

    def test_a_400_with_no_body_still_shows_its_headers_in_the_lines_and_the_json(self):
        fake = Fake(status=400)
        fake.post = lambda url, body, headers: (400, 0.022, {'apigw-requestid': 'AbC=', 'content-type': 'application/json',
                                                             'x-amzn-errortype': 'BadRequestException', 'body': ''})
        code, lines = fake.main('--wait', '0')
        self.assertEqual(code, 1)
        text = '\n'.join(lines)
        self.assertIn('x-amzn-ErrorType=BadRequestException', text)
        self.assertIn('response body: (empty)', text)
        result = json.loads(lines[-1])
        self.assertEqual(result['headers'], {'apigw-requestid': 'AbC=', 'content-type': 'application/json',
                                             'x-amzn-errortype': 'BadRequestException'})
        self.assertEqual((result['http_status'], result['body']), (400, ''))

    def test_a_400_body_is_cut_at_300_chars_and_redacted_in_the_json(self):
        fake = Fake(status=400)
        fake.post = lambda url, body, headers: (400, 0.02, {'body': '{"message":"bad","token":"s3cr3t-value"}' + ' y' * 400})
        result = json.loads(fake.main('--no-rollback', '--wait', '0')[1][-1])
        self.assertLessEqual(len(result['body']), 300)
        self.assertIn('bad', result['body'])
        self.assertNotIn('s3cr3t-value', result['body'])

    def test_with_the_lambda_path_there_is_nothing_to_prove_and_no_request_is_made(self):
        fake = Fake(outputs=[{'OutputKey': 'AckPath', 'OutputValue': 'lambda'}])
        code, lines = fake.main()
        self.assertEqual((code, fake.posted, rolled_back(fake)), (0, [], []))

    def test_unreadable_outputs_give_no_verdict_and_no_rollback(self):
        fake = Fake(outputs=None)
        self.assertEqual((fake.main()[0], fake.posted, rolled_back(fake)), (2, [], []))

    def test_no_rollback_flag_keeps_sqs(self):
        fake = Fake(status=500)
        self.assertEqual((fake.main('--no-rollback', '--wait', '0')[0], rolled_back(fake)), (1, []))

    def test_the_rollback_target_is_the_template_parameter_and_deploy_sh_calls_the_smoke(self):
        template = json.loads((ROOT / 'infra/aws/stacks/40-port.json').read_text(encoding='utf-8'))
        self.assertIn('lambda', template['Parameters']['AckPath']['AllowedValues'])
        self.assertEqual(template['Parameters']['AckPath']['Default'], 'lambda')  # the template's default; production's value is parameters.json's
        self.assertIn('AckPath', template['Outputs'])  # the smoke reads it
        self.assertIn('PortUrl', template['Outputs'])
        deploy = (ROOT / 'infra/aws/deploy.sh').read_text(encoding='utf-8')
        self.assertIn('scripts/lib/ack_smoke.py', deploy)
        self.assertNotRegex(deploy, r'failed="\$failed ack-smoke')  # ACK-CANARY: the smoke never fails a build


def load(name):
    return json.loads((ROOT / 'infra/aws/stacks' / name).read_text(encoding='utf-8'))


class TheCanaryIsRetired(unittest.TestCase):
    """ACK-CANARY-RETIRE: the canary's experiment is closed (production answers by SQS, proved live). Its stack carried 56
    resources and a smoke of its own; the deployer may not delete a stack, so an update emptied it (#578), the account's
    owner deleted the empty stack (12/11), and ACK-CANARY-GONE took its template and its line of the order away."""

    def test_no_template_and_no_line_of_the_order_name_the_stack_that_was_deleted(self):
        stacks = sorted(path.name for path in (ROOT / 'infra/aws/stacks').glob('*.json'))
        self.assertEqual(stacks, ['10-network.json', '20-data.json', '30-service.json', '40-port.json', '50-runner.json'])
        order = json.loads((ROOT / 'infra/aws/order.json').read_text())
        self.assertEqual(sorted(order), ['data', 'network', 'port', 'runner', 'service'])  # a name with no file would wait for nothing
        for name in stacks:
            said = (ROOT / 'infra/aws/stacks' / name).read_text(encoding='utf-8')
            self.assertNotIn('CanaryUrl', said)
            self.assertNotIn('tower-ack-canary', said)

    def test_the_smoke_has_no_canary_half_and_the_deploy_runs_none(self):
        self.assertEqual([name for name in dir(ack_smoke) if 'canary' in name.lower()], [])
        with self.assertRaises(SystemExit), mock.patch('sys.stderr'):
            Fake().main('--canary')  # the option is gone: an old caller is told, not silently run against production
        deploy = (ROOT / 'infra/aws/deploy.sh').read_text(encoding='utf-8')
        self.assertNotIn('--canary', deploy)
        self.assertNotIn('45-ack-canary.json', deploy)  # not an ACK file any more: a change of it starts no smoke
        self.assertNotIn('$n = ack-canary', deploy)
        self.assertIn('nothing to prove, not run', deploy)  # AckPath=lambda: no smoke, where the canary's ran

    def test_the_default_poster_keeps_lowercase_header_names_on_the_wire(self):
        import http.client
        seen = {}

        class Conn:
            def __init__(self, host, timeout=None):
                seen['host'] = host

            def request(self, method, path, body=None, headers=None):
                seen.update(method=method, path=path, headers=headers)

            def getresponse(self):
                raise OSError('stop')

            def close(self):
                pass
        real, http.client.HTTPSConnection = http.client.HTTPSConnection, Conn
        try:
            status, _, info = ack_smoke.post('https://x.execute-api.us-east-1.amazonaws.com' + ack_smoke.ROUTE, b'{}',
                                              {'webhook-id': 'x', 'content-type': 'application/json'})
        finally:
            http.client.HTTPSConnection = real
        self.assertIsNone(status)
        self.assertEqual(seen['path'], ack_smoke.ROUTE)
        self.assertEqual(sorted(seen['headers']), ['content-type', 'webhook-id'])


if __name__ == '__main__':
    unittest.main()
