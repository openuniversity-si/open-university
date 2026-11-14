"""The ack-integration probe with an injected aws runner: the variant table, the create-integration arguments, the verdict
per variant (accepted / exact error), and the cleanup of everything it created even after a failure. No network."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import aws_ack_integration_probe as probe  # noqa: E402

QUEUE = 'https://sqs.us-east-1.amazonaws.com/123456789012/tower-port-webhooks'


class FakeAws:
    def __init__(self, reject=(), role_exists=False, fail_on=None):
        self.calls, self.reject, self.role_exists, self.fail_on = [], set(reject), role_exists, fail_on

    def __call__(self, argv):
        self.calls.append(argv)
        key = argv[:2]
        if self.fail_on == key[1]:
            return 1, '', 'boom'
        if key == ['sqs', 'get-queue-url']:
            return 0, json.dumps({'QueueUrl': QUEUE}), ''
        if key == ['iam', 'get-role']:
            return (0, json.dumps({'Role': {'Arn': 'arn:aws-partition:iam::1:role/tower-app-port-ack'}}), '') if self.role_exists else (255, '', 'NoSuchEntity')
        if key == ['sqs', 'get-queue-attributes']:
            return 0, json.dumps({'Attributes': {'QueueArn': 'arn:aws-partition:sqs:r:1:tower-port-webhooks'}}), ''
        if key == ['iam', 'create-role']:
            return 0, json.dumps({'Role': {'Arn': 'arn:aws-partition:iam::1:role/scratch'}}), ''
        if key == ['apigatewayv2', 'create-api']:
            return 0, json.dumps({'ApiId': 'api123'}), ''
        if key == ['apigatewayv2', 'create-integration']:
            params = json.loads(argv[argv.index('--request-parameters') + 1])
            if any(token in json.dumps(params) for token in self.reject):
                return 254, '', 'An error occurred (BadRequestException): Invalid selection expression for MessageAttributes'
            return 0, json.dumps({'IntegrationId': 'i1'}), ''
        return 0, '{}', ''

    def verbs(self):
        return [' '.join(c[:2]) for c in self.calls]


def run(fake, *args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = probe.main(list(args), runner=fake, sleep=lambda s: None)
    return code, out.getvalue()


class Variants(unittest.TestCase):
    def setUp(self):
        self.table = {name: (what, params, response) for name, what, params, response in probe.variants(QUEUE)}

    def test_the_table_has_the_six_asked_variants_plus_two_diagnostics(self):
        self.assertEqual(list(self.table), list('ABCDEFGH'))

    def test_every_variant_names_the_queue_and_sends_the_body(self):
        for name, (_, params, _) in self.table.items():
            self.assertEqual((params['QueueUrl'], params['MessageBody']), (QUEUE, '$request.body'), name)

    def test_a_has_no_attributes_b_one_header_c_three_d_adds_the_epoch(self):
        self.assertNotIn('MessageAttributes', self.table['A'][1])
        self.assertEqual(list(json.loads(self.table['B'][1]['MessageAttributes'])), ['webhook-id'])
        self.assertEqual(list(json.loads(self.table['C'][1]['MessageAttributes'])), list(probe.HEADERS))
        d = json.loads(self.table['D'][1]['MessageAttributes'])
        self.assertEqual(d['request-time-ms']['StringValue'], '$context.requestTimeEpoch')
        self.assertEqual(d['webhook-signature']['StringValue'], '$request.header.webhook-signature')

    def test_e_uses_system_attributes_and_f_the_braced_reference(self):
        self.assertIn('AWSTraceHeader', json.loads(self.table['E'][1]['MessageSystemAttributes']))
        f = json.loads(self.table['F'][1]['MessageAttributes'])
        self.assertEqual(f['webhook-id']['StringValue'], '${request.header.webhook-id}')

    def test_message_attributes_is_a_json_string_with_datatype_and_stringvalue(self):
        value = self.table['C'][1]['MessageAttributes']
        self.assertIsInstance(value, str)
        for entry in json.loads(value).values():
            self.assertEqual(set(entry), {'DataType', 'StringValue'})
            self.assertEqual(entry['DataType'], 'String')

    def test_h_carries_the_response_mapping(self):
        self.assertEqual(self.table['H'][2], {'200': {'overwrite:statuscode': '202'}})


class Run(unittest.TestCase):
    def test_accepted_and_rejected_are_printed_with_the_exact_error(self):
        fake = FakeAws(reject=('$context.requestTimeEpoch', '${request'))
        code, text = run(fake)
        self.assertEqual(code, 0)
        self.assertIn('A  ACCEPTED', text)
        self.assertIn('D  REJECTED An error occurred (BadRequestException): Invalid selection expression for MessageAttributes', text)
        self.assertIn('Summary: A=ok, B=ok, C=ok, D=no, E=ok, F=no', text)

    def test_the_create_integration_arguments_are_the_sqs_subtype_with_the_role(self):
        fake = FakeAws(role_exists=True)
        run(fake, '--only', 'C', '--region', 'us-east-1')
        call = next(c for c in fake.calls if c[:2] == ['apigatewayv2', 'create-integration'])
        for pair in (('--integration-type', 'AWS_PROXY'), ('--integration-subtype', 'SQS-SendMessage'),
                     ('--payload-format-version', '1.0'), ('--credentials-arn', 'arn:aws-partition:iam::1:role/tower-app-port-ack'),
                     ('--api-id', 'api123'), ('--region', 'us-east-1')):
            self.assertEqual(call[call.index(pair[0]) + 1], pair[1])
        self.assertEqual(len([c for c in fake.calls if c[:2] == ['apigatewayv2', 'create-integration']]), 1)

    def test_a_scratch_role_is_made_when_the_ack_role_is_missing_and_everything_is_deleted(self):
        fake = FakeAws()
        run(fake)
        verbs = fake.verbs()
        for made, undone in (('iam create-role', 'iam delete-role'), ('apigatewayv2 create-api', 'apigatewayv2 delete-api')):
            self.assertIn(made, verbs)
            self.assertIn(undone, verbs)
        self.assertEqual(verbs[-1], 'iam delete-role')

    def test_an_existing_ack_role_is_used_and_never_deleted(self):
        fake = FakeAws(role_exists=True)
        run(fake)
        self.assertNotIn('iam create-role', fake.verbs())
        self.assertNotIn('iam delete-role', fake.verbs())

    def test_a_failure_while_preparing_still_cleans_up_and_exits_2(self):
        fake = FakeAws(fail_on='create-route')
        code, text = run(fake)
        self.assertEqual(code, 2)
        self.assertIn('probe could not run', text)
        self.assertIn('apigatewayv2 delete-api', fake.verbs())

    def test_keep_leaves_the_scratch_resources(self):
        fake = FakeAws()
        run(fake, '--keep')
        self.assertNotIn('apigatewayv2 delete-api', fake.verbs())


if __name__ == '__main__':
    unittest.main()
