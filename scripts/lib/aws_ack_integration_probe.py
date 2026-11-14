"""PORT7-FIX: which RequestParameters does API Gateway accept for an HTTP API SQS-SendMessage integration?

The first template was refused by CloudFormation ("Invalid selection expression for MessageAttributes") after a 13-minute
deploy. This probe asks the real API in seconds instead: it creates a scratch HTTP API (and, when the stack's ack role does not
exist, a scratch role), tries each candidate variant with create-integration against the real queue, prints ACCEPTED or the
exact API error, and deletes everything it made. It never sends a message and prints no credential.

Needs the aws CLI with admin credentials (apigatewayv2, sqs, iam). Usage: scripts/aws-ack-integration-probe [--region R]
[--queue NAME] [--role-arn ARN] [--only A,B] [--keep]. Exit 0 when it ran (read the table), 2 when it could not run.
"""
import argparse
import json
import subprocess
import sys
import time
import uuid

QUEUE = 'tower-port-webhooks'
ACK_ROLE = 'tower-app-port-ack'
HEADERS = ('webhook-id', 'webhook-timestamp', 'webhook-signature')


def attrs(**values):
    """MessageAttributes is ONE string holding JSON: {name: {DataType, StringValue}}."""
    return json.dumps({k: {'DataType': 'String', 'StringValue': v} for k, v in values.items()}, separators=(',', ':'))


def header_attrs(ref):
    return attrs(**{h: ref(h) for h in HEADERS})


def variants(queue_url):
    """(name, what it tests, RequestParameters, ResponseParameters or None), in the order they run."""
    base = {'QueueUrl': queue_url, 'MessageBody': '$request.body'}
    one = dict(base, MessageAttributes=attrs(**{'webhook-id': '$request.header.webhook-id'}))
    three = dict(base, MessageAttributes=header_attrs(lambda h: '$request.header.' + h))
    return [
        ('A', 'body only', dict(base), None),
        ('B', 'body + one header attribute', one, None),
        ('C', 'body + the three webhook headers', three, None),
        ('D', 'C + $context.requestTimeEpoch', dict(three, MessageAttributes=json.dumps(
            dict(json.loads(three['MessageAttributes']),
                 **{'request-time-ms': {'DataType': 'String', 'StringValue': '$context.requestTimeEpoch'}}),
            separators=(',', ':'))), None),
        ('E', 'MessageSystemAttributes (AWSTraceHeader from a header) + a static attribute', dict(
            base, MessageAttributes=attrs(source='origin'),
            MessageSystemAttributes=json.dumps({'AWSTraceHeader': {'DataType': 'String',
                                                                   'StringValue': '$request.header.x-amzn-trace-id'}},
                                               separators=(',', ':'))), None),
        ('F', 'headers referenced with the braced form ${request.header.NAME}', dict(
            base, MessageAttributes=header_attrs(lambda h: '${request.header.%s}' % h)), None),
        ('G', 'MessageAttributes all static (is the JSON string itself valid?)', dict(
            base, MessageAttributes=attrs(**{h: 'x' for h in HEADERS})), None),
        ('H', 'A + the 202 response mapping', dict(base), {'200': {'overwrite:statuscode': '202'}}),
    ]


def run_aws(argv):
    done = subprocess.run(['aws', *argv], capture_output=True, text=True)
    return done.returncode, done.stdout, done.stderr


class Probe:
    def __init__(self, runner=run_aws, region=None, queue=QUEUE, role_arn=None, sleep=time.sleep, out=print):
        self.run, self.region, self.queue, self.role_arn = runner, region, queue, role_arn
        self.sleep, self.out, self.scratch_role, self.api_id = sleep, out, None, None

    def aws(self, *argv):
        extra = ['--region', self.region] if self.region else []
        return self.run([*argv, *extra, '--output', 'json'])

    def ok(self, *argv):
        rc, out, err = self.aws(*argv)
        if rc:
            raise RuntimeError(' '.join(argv[:2]) + ': ' + (err.strip().splitlines() or ['failed'])[-1])
        return json.loads(out) if out.strip() else {}

    def integration_args(self, params, response):
        args = ['apigatewayv2', 'create-integration', '--api-id', self.api_id, '--integration-type', 'AWS_PROXY',
                '--integration-subtype', 'SQS-SendMessage', '--payload-format-version', '1.0',
                '--credentials-arn', self.role_arn, '--timeout-in-millis', '5000',
                '--request-parameters', json.dumps(params, separators=(',', ':'))]
        if response:
            args += ['--response-parameters', json.dumps(response, separators=(',', ':'))]
        return args

    def prepare(self):
        queue_url = self.ok('sqs', 'get-queue-url', '--queue-name', self.queue)['QueueUrl']
        if not self.role_arn:
            rc, out, _ = self.aws('iam', 'get-role', '--role-name', ACK_ROLE)
            if rc == 0:
                self.role_arn = json.loads(out)['Role']['Arn']
            else:  # the stack never created it (that is the point of this probe): a scratch role, same shape
                name = 'tower-ack-probe-' + uuid.uuid4().hex[:8]
                queue_arn = self.ok('sqs', 'get-queue-attributes', '--queue-url', queue_url, '--attribute-names',
                                    'QueueArn')['Attributes']['QueueArn']
                trust = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Action': 'sts:AssumeRole',
                                                                'Principal': {'Service': 'apigateway.amazonaws.com'}}]}
                self.role_arn = self.ok('iam', 'create-role', '--role-name', name, '--assume-role-policy-document',
                                        json.dumps(trust))['Role']['Arn']
                self.scratch_role = name
                policy = {'Version': '2012-10-17', 'Statement': [
                    {'Effect': 'Allow', 'Action': 'sqs:SendMessage', 'Resource': queue_arn}]}
                self.ok('iam', 'put-role-policy', '--role-name', name, '--policy-name', 'ack',
                        '--policy-document', json.dumps(policy))
                self.sleep(10)  # IAM propagation
        self.api_id = self.ok('apigatewayv2', 'create-api', '--name', 'tower-ack-probe-' + uuid.uuid4().hex[:8],
                              '--protocol-type', 'HTTP')['ApiId']
        self.ok('apigatewayv2', 'create-route', '--api-id', self.api_id, '--route-key', 'POST /probe')
        return queue_url

    def cleanup(self):
        if self.api_id:
            self.aws('apigatewayv2', 'delete-api', '--api-id', self.api_id)
        if self.scratch_role:
            self.aws('iam', 'delete-role-policy', '--role-name', self.scratch_role, '--policy-name', 'ack')
            self.aws('iam', 'delete-role', '--role-name', self.scratch_role)

    def results(self, only=None, keep=False):
        rows = []
        try:
            queue_url = self.prepare()
            for name, what, params, response in variants(queue_url):
                if only and name not in only:
                    continue
                rc, out, err = self.aws(*self.integration_args(params, response))
                verdict = 'ACCEPTED' if rc == 0 else 'REJECTED ' + ((err.strip().splitlines() or ['?'])[-1])
                rows.append((name, what, params, verdict))
                self.out(f'{name}  {verdict}\n   {what}\n   MessageAttributes={params.get("MessageAttributes", "-")}')
        finally:
            if not keep:
                self.cleanup()
        return rows


def main(argv=None, runner=run_aws, sleep=time.sleep):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--region')
    parser.add_argument('--queue', default=QUEUE)
    parser.add_argument('--role-arn')
    parser.add_argument('--only', help='comma list of variant names, e.g. A,C')
    parser.add_argument('--keep', action='store_true', help='leave the scratch API/role (debugging)')
    args = parser.parse_args(argv)
    only = set(args.only.split(',')) if args.only else None
    probe = Probe(runner, args.region, args.queue, args.role_arn, sleep)
    try:
        rows = probe.results(only, args.keep)
    except RuntimeError as error:
        print('probe could not run: ' + str(error), file=sys.stderr)
        return 2
    print('\nSummary: ' + ', '.join(f'{n}={"ok" if v == "ACCEPTED" else "no"}' for n, _, _, v in rows))
    print('Send this table to the coordinator; the template is switched to the first accepted variant that carries the headers.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
