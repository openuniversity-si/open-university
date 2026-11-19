"""The factory's AWS infrastructure (engine-infra-aws, D-303). Hermetic: reads the declared budget and the CloudFormation
templates under infra/aws as JSON and checks Daniel's decision and the guardrails; no AWS call, no network.
"""
# Verifies: REQ-aws-200
from datetime import timedelta
import hashlib
from http import HTTPStatus
import json
import os
import re
import shutil
import sys
import types
import unittest
from fnmatch import fnmatchcase
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INFRA = ROOT / 'infra' / 'aws'
BODY_LIMIT = 51200  # a template sent as its body (deploy.sh without an S3 bucket, the stacks)
URL_LIMIT = 1048576  # BOOTSTRAP-URL: a template read from S3 (--template-url), how the Torre applies the bootstrap
RECORD = ROOT / 'docs/domain/decisions/D-303.md'
BUDGET_RECORD = ROOT / 'docs/domain/decisions/D-315.md'  # D-315 amends D-303's numbers (US$ 150, ceiling US$ 200)
sys.path.insert(0, str(ROOT / 'scripts/lib'))
import agent_env  # noqa: E402
import agent_env_stack  # noqa: E402


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def decided():
    """Daniel's numbers as D-315 states them (it amends D-303's): the monthly limit, the actual alerts and the forecast alert."""
    text = BUDGET_RECORD.read_text(encoding='utf-8')
    ceiling = int(re.search(r'US\$ (\d+) a month, unblended', text).group(1))
    actual = [int(value) for value in re.search(r'actual (\d+)/(\d+)/(\d+) %', text).groups()]
    forecast = int(re.search(r'forecast (\d+) %', text).group(1))
    return ceiling, actual, forecast


class BudgetTests(unittest.TestCase):
    """The ceiling Daniel approved on 04/11 01:39 BRT, as the Torre created it in the console at 01:44, raised by D-315."""

    def setUp(self):
        self.budget = load(INFRA / 'budget.json')

    def test_the_ceiling_is_the_decided_one(self):
        ceiling, _, _ = decided()
        # the console budget keeps the name it was created with under D-303's US$ 60; D-315 changed only its limit
        self.assertEqual(self.budget['name'], 'torre-motor-teto-60')
        self.assertIn('`torre-motor-teto-60`', BUDGET_RECORD.read_text(encoding='utf-8'))
        self.assertIn('US$ 200 monthly ceiling', BUDGET_RECORD.read_text(encoding='utf-8'))
        self.assertIn('US$ 200 monthly ceiling', self.budget['contract'])
        self.assertEqual(self.budget['amended']['approved'], 'Daniel through the Torre, 14/11/2026')
        self.assertEqual((self.budget['budget_type'], self.budget['time_unit']), ('COST', 'MONTHLY'))
        self.assertEqual(self.budget['limit'], {'amount': ceiling, 'unit': 'USD'})

    def test_the_alerts_are_the_decided_ones(self):
        _, actual, forecast = decided()
        notifications = self.budget['notifications']
        self.assertEqual(sorted(n['threshold'] for n in notifications if n['type'] == 'ACTUAL'), actual)
        self.assertEqual([n['threshold'] for n in notifications if n['type'] == 'FORECASTED'], [forecast])
        for notification in notifications:
            self.assertEqual((notification['comparison'], notification['threshold_type']), ('GREATER_THAN', 'PERCENTAGE'))

    def test_it_measures_the_credit_it_spends(self):
        # AWS includes credits and refunds by default; a budget net of credits stays near zero while the credit lasts.
        cost_types = self.budget['cost_types']
        self.assertIs(cost_types['include_credit'], False)
        self.assertIs(cost_types['include_refund'], False)

    def test_it_is_unblended_cost_in_the_cost_types_form(self):
        # The AWS API does not accept Metrics together with CostTypes (the Torre, 04/11 09:00 BRT): unblended cost is
        # CostTypes without blending or amortization.
        self.assertNotIn('metrics', self.budget)
        self.assertIs(self.budget['cost_types']['use_blended'], False)
        self.assertIs(self.budget['cost_types']['use_amortized'], False)

    def test_no_email_address_in_the_repository(self):
        self.assertIsNone(re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', json.dumps(self.budget)))


class DecisionTests(unittest.TestCase):
    def test_the_record_cites_daniel_and_names_this_proof(self):
        record = RECORD.read_text(encoding='utf-8')
        self.assertIn('proof: scripts/tests/test_infra_aws.py', record)
        self.assertIn('Daniel 04/11 01:39 BRT', record)
        self.assertIn('Aprovo: A1 a 1 PR/min', record)

    def test_the_register_has_the_row(self):
        register = (ROOT / 'docs/domain/DECISIONS.md').read_text(encoding='utf-8')
        self.assertRegex(register, r'(?m)^\| D-303 \|')

    def test_the_unit_owns_the_infrastructure(self):
        unit = load(ROOT / 'units/engine-infra-aws/unit.json')
        self.assertIn('infra/aws/**', unit['paths'])
        self.assertIn('D-303', unit['decisions'])


def as_list(value):
    return value if isinstance(value, list) else [value]


def role_arns():
    """The ARN of every named role of the bootstrap, by logical id, for a policy that names a role by Fn::GetAtt."""
    resources = load(INFRA / 'bootstrap.json')['Resources']
    return {name: f"arn:aws-partition:iam::ACCOUNT:role/{item['Properties']['RoleName']}" for name, item in resources.items()
            if item['Type'] == 'AWS::IAM::Role' and 'RoleName' in item['Properties']}


def resolved(value):
    """A policy value with the account and the region of a stack in place of their pseudo parameters."""
    if isinstance(value, dict) and 'Fn::GetAtt' in value and value['Fn::GetAtt'][-1] == 'Arn':
        return role_arns().get(value['Fn::GetAtt'][0], str(value))
    if isinstance(value, dict) and 'Fn::Sub' in value:
        return value['Fn::Sub'].replace('${AWS::AccountId}', 'ACCOUNT').replace('${AWS::Region}', 'REGION').replace('${AWS::Partition}', 'aws-partition')
    if isinstance(value, dict) and value.get('Ref') == 'AWS::Region':
        return 'REGION'
    if isinstance(value, dict) and value.get('Ref') == 'ReplicaRegion':  # MEDIA-REPLICA: the bootstrap's parameter
        return 'REPLICA-REGION'
    if isinstance(value, list):
        return [resolved(item) for item in value]
    return value


def conditions_hold(condition, context):
    for operator, pairs in (condition or {}).items():
        for key, wanted in pairs.items():
            given, wanted = context.get(key), resolved(wanted)
            if operator in ('StringEquals', 'ArnEquals') and given not in as_list(wanted):  # a list: any of its values
                return False
            if operator == 'StringNotLike' and given is not None and fnmatchcase(given, wanted):
                return False
            if operator == 'Bool' and str(given).lower() != str(wanted).lower():
                return False
    return True


def decide(statements, action, resource, context=None):
    """IAM's order on a set of statements: an explicit deny wins, then an allow, else the implicit deny."""
    context = {'aws:RequestedRegion': 'REGION', **(context or {})}

    def matches(item):
        listed = as_list(item.get('Action', item.get('NotAction')))
        named = any(fnmatchcase(action, pattern) for pattern in listed)
        resources = [str(resolved(value)) for value in as_list(item.get('Resource', '*'))]
        return ((named if 'Action' in item else not named) and any(fnmatchcase(resource, value) for value in resources)
                and conditions_hold(item.get('Condition'), context))
    found = [item['Effect'] for item in statements if matches(item)]
    return 'deny' if 'Deny' in found else 'allow' if 'Allow' in found else 'implicit'



class BootstrapTests(unittest.TestCase):
    """The keyless bootstrap: every role bounded, no user or key, the deployer limited to the app stacks."""

    def setUp(self):
        self.template = load(INFRA / 'bootstrap.json')
        self.resources = self.template['Resources']

    def policy(self, resource):
        return self.resources[resource]['Properties']['Policies'][0]['PolicyDocument']['Statement']

    # BOOTSTRAP-MIRROR: only the Torre applies the bootstrap, so this file is a mirror, never a wish: a change of it is asked to
    # the Torre with the exact JSON, applied, and only then lands here with the hash the account gave back. The hash is of
    # the canonical form (keys sorted, no space): CloudFormation gives the template back in its own bytes, not the file's.
    # 12/11: get-template of tower-bootstrap, read by the Torre (the req1455 rules: tower-app-stack-state, tower-engine-impaired)
    # 12/11 16:51 UTC: change set req-ecs-stops-1350 (ECS-STOPS-IN-LOG: tower-ecs-task-stopped, tower-ecs-service-action), 24 resources
    # 13/11 ~17:15 UTC: change set req-667-reach (BOOTSTRAP-REACH: the stack's drift readable, Bedrock named, the alerts to the
    # Torre by event: tower-alerts-torre), UPDATE_COMPLETE, read back by the Torre with get-template, 27 resources
    # PUBLIC-BOOTSTRAP (the public repository, 14/11/2026): the template carries no account and no partition; the ARNs
    # say ${AWS::Partition} and ${AWS::AccountId}, which CloudFormation fills in when the Torre applies it. The pin is the
    # public template's. The account still runs the template applied before publication (fe8c30de...1300), the same
    # policy in the aws partition; the Torre re-applies this one at the next bootstrap change, nothing before it.
    # BUILD-NO-ORIGIN (Daniel through the Torre, 14/11/2026): the deploy build clones the public GitHub repository with
    # plain git, so its BuildSpec drops the Origin CLI, its login and the /tower/origin/api-key parameter. The Torre
    # re-applies tower-bootstrap with this template after the merge (UsePreviousValue for its parameters); the pin is
    # what the account has once re-applied.
    # QUEUE-RELOAD (the Torre, 15/11/2026): the doorbell passes the merge queue's words {event, sha} to tower-port-api:live
    # (lambda:InvokeFunction on that alias alone) and starts no build for them. The Torre re-applies tower-bootstrap with
    # this template after the merge (UsePreviousValue for its parameters), as for BUILD-NO-ORIGIN.
    # ORIGIN-ACCESS-GONE (the Torre, 15/11/2026): the deployer no longer reads /tower/origin/* (its statement is
    # ReadTheLastDeploy, /tower/deploy/* alone), so the Torre deletes the Origin parameters after this lands. The Torre
    # re-applies tower-bootstrap with this template after the merge (UsePreviousValue for its parameters).
    # AWS-REVIEW (the Torre, 16/11/2026 06:20:44 UTC): change set req-aws-review, UPDATE_COMPLETE, parameters
    # UsePreviousValue, nothing replaced; the topic policy to the account root, the boundary's three denies of the alerting
    # path, the GitHub defaults, the doorbell's concurrency, alarm and dead letters, the dead log grant gone; and the
    # Torre's two deviations: CloudWatch alarms may publish to the topic, and the deploy log denied is the real
    # /tower/infra-deploy too. The file is the applied one (raw sha256 28402007...42ac).
    # AWS-REVIEW DLQ alarm (the Torre, 17/11/2026 17:50:22 UTC): change set req-dlq-alarm, UPDATE_COMPLETE, one resource
    # added (EventsDeadLettersAlarm, tower-events-dlq-messages); raw sha256 a0d4e34e...be14.
    # MEDIA-S3 (D-323 step 2, 18/11/2026): the boundary's workload statement adds cloudfront:* (the media stack's
    # distribution, its origin access control and its cache policy; CloudFront answers in us-east-1, the stack region) and
    # two reads of ACM (DescribeCertificate, ListCertificates) for a certificate the Torre issues; no stack may request
    # one (MediaStackTests). The Torre re-applies tower-bootstrap with this template after the merge (UsePreviousValue for
    # its parameters), as for QUEUE-RELOAD; until then the media stack stays at Cdn off (parameters.json), buckets only.
    # DNS-ROUTE53 (D-323 step 3, 18/11/2026): the boundary gains TheSiteZoneOnRoute53, seven route53 actions and patterns for what the
    # dns stack's hosted zone and record sets call (no health check, no key-signing key, no query log, no route53domains;
    # Route 53 is global, so the statement has no region condition; patterns, because the file is 32 bytes under the
    # 51,200 a template body may be). The Torre re-applies tower-bootstrap with this
    # template after the merge (UsePreviousValue for its parameters), one re-apply for MEDIA-S3 and this; until then the
    # dns stack stays at Zone off (parameters.json), a wait-condition handle alone.
    # APPLIED (the Torre, 18/11/2026 18:01:00 UTC): change set req-d323-cloudfront-route53 from main 3613e9ed, one change
    # (Boundary, Modify, no replacement): cloudfront:* and the two ACM reads, and TheSiteZoneOnRoute53; raw sha256
    # 996cb23a...f01f. The media stack goes to Cdn on and the dns stack may go to Zone on.
    # MAIL-SES (D-323, the Cloudflare exit, 18/11/2026): the boundary's workload statement adds ses:* (the mail stack's SES
    # identity, receipt rule set and rules, and the forwarder's send; region-bound like the rest). To make room (the file was
    # 32 bytes under the 51,200 limit) two denies of NoUsersKeysOrBoundaryChanges became patterns that deny as much or more:
    # iam:CreatePolicy* (CreatePolicy, CreatePolicyVersion) and iam:*LoginProfile (Create, Update, and now Get and Delete).
    # 51,104 bytes. The Torre re-applies tower-bootstrap with this template after the merge (UsePreviousValue for its
    # parameters); until then the mail stack stays at Mail off (parameters.json), a wait-condition handle alone.
    # MEDIA-REPLICA (RISK-media-single-account, Daniel 18/11 21:29 BRT: a copy of the media in a second region, under
    # US$ 1 a month): a new parameter ReplicaRegion (default empty: one region, as before) and the workload statement's
    # region condition becomes [the stack region, ReplicaRegion], so the deployer and the execution role may run the
    # media-replica stack there (cloudformation:*, s3:*) and the replication role may write the copy; the deployer's
    # app-stack ARNs say cloudformation:* for the region (the boundary still holds them to the two). No template fixes a
    # region (D-304): the Torre passes ReplicaRegion=us-west-2 at the re-apply. To make room (96 bytes were left) three
    # denies of TheDeployerIsOutOfReach and one of NoUsersKeysOrBoundaryChanges became patterns that deny as much or
    # more: codebuild:*Project, lambda:DeleteFunction*, lambda:*Permission, iam:*RolePermissionsBoundary. 51,155 bytes.
    # The Torre re-applies tower-bootstrap with this template BEFORE the merge that deploys the media-replica stack
    # (UsePreviousValue for the other parameters): without it that stack's apply is refused, in us-west-2.
    # AWS-SPEND (D-331, VAL-aws-200): the deployer reads the month's spend, ce:GetCostAndUsage (Resource *, as AWS requires;
    # its only endpoint is us-east-1, the stack region), at most once a UTC day (deploy.sh). The boundary's workload
    # statement allows that one action, and its deny of ce:* goes: the boundary allows no other ce action, so the rest
    # stays implicitly denied to every role under it. To make room (45 bytes were left) the template's Description says
    # "Applied by hand" without "in the console", and "from GitHub" where it said Origin (BUILD-NO-ORIGIN). 51,196 bytes.
    # The Torre re-applies tower-bootstrap with this template BEFORE the merge (UsePreviousValue for every parameter):
    # until then the build's read is refused and the record keeps no spend; nothing fails.
    # BOOTSTRAP-URL (D-327, 19/11/2026): the file stood at 51,196 of the 51,200 bytes a template body may be, so the Torre
    # applies it from S3 with --template-url (1 MB) and the room-making above stops (docs/programs/padrao-dev/
    # fornecimento-cloudflare.md, "Aplicar o bootstrap"). RING-QUEUE (D-331, POLL-scripts-lib-deploy-py-ring-until-free): a
    # 409 while a build runs leaves the ring pending in /tower/deploy/ring-pending (the doorbell's KeepTheRingPending:
    # get, put, delete of that one parameter), and DeployStateRule's second target, the doorbell, starts it at the running
    # build's end; deploy.py's push ring takes that queued 409 as final and loops no more. One re-apply with AWS-SPEND,
    # BEFORE the merge (UsePreviousValue for every parameter). 53,556 bytes.
    # GITHUB-HOOK (POLL-scripts-lib-deploy-py-queue): the owner's repository webhook 713861741 (push only, JSON) posts to
    # the doorbell's Function URL; the doorbell checks X-Hub-Signature-256 (HMAC-SHA256 of the raw body, constant time)
    # with the secret of SecureString /tower/deploy/github-webhook-secret, read once per container (ReadTheGitHubHookSecret:
    # ssm:GetParameter of that one parameter; the AWS-managed aws/ssm key's policy allows the decrypt through SSM and the
    # boundary allows kms:Decrypt, so the role names no key), and a push to main is the queue's `landed`; anything else
    # signed is a 204. deploy.py queue rings `prepare` and ends, with no watch. The code was trimmed to 4,059 of the 4,096
    # characters a ZipFile may be (the next change of it moves it to S3). The Torre applies it BEFORE the merge, then turns
    # the webhook on (the runbook's "Aplicar o bootstrap pelo S3"). 54,065 bytes.
    # PUSH-STEPS (REQ-deploy-1s, 19/11/2026): the doorbell passes the port the instant it heard a queue word (`heard`,
    # epoch seconds), so `scripts/deploy status` splits the push-to-live seconds into steps; the 400's body says "not
    # JSON" to make room: 4,088 of the 4,096 characters (the next change of it moves it to S3). Old and new code on either
    # side read each other (the port ignores a missing `heard`), so the Torre applies it with no order to the merge
    # (the runbook's "PUSH-STEPS"). 54,095 bytes.
    # SIGNED-HOOK (REQ-deploy-1s, 19/11/2026): the doorbell forwards every signed GitHub event to the port as {event: hook,
    # kind, ref, after, deleted} and drops its own push/ref check; the port lands a push to main alone, signed, and the
    # look skips its git ls-remote of main for it. The D-303 comment went to make room: 4,018 of the 4,096 characters. The
    # old port ignores a hook word, so the Torre applies it AFTER the merge's deploy (the runbook's "PUSH-STEPS", one
    # apply for both changes). 54,021 bytes.
    # AGENT-ENV-BOUNDARY (D-341, 19/11/2026): the boundary's AgentEnvSecrets lets a role read (GetSecretValue,
    # DescribeSecret) the Secrets Manager secrets tower/agent-env/* and tower/torre-webhook-* of the stack region, and
    # nothing else of Secrets Manager; tower-cfn-exec, whose one policy is the boundary, already creates the later stack's
    # tower-app-* functions, roles and SSM parameters. The Torre applies it from S3 (the runbook's "AGENT-ENV-BOUNDARY"),
    # with no order to the merge: nothing reads those secrets yet. 54,636 bytes.
    APPLIED = '38bdc05f44129bb5795761b728715a19c9cb419ff9c510a830e45f060cec6e2e'

    # MEDIA-REPLICA: the workload services in the stack region and in the media replica's, nowhere else
    REGIONS = {'StringEquals': {'aws:RequestedRegion': [{'Ref': 'AWS::Region'}, {'Ref': 'ReplicaRegion'}]}}

    def test_the_workload_reaches_the_replica_region_and_no_third_one(self):
        statements = self.resources['Boundary']['Properties']['PolicyDocument']['Statement']
        self.assertEqual(self.template['Parameters']['ReplicaRegion'].get('Default'), '')  # none until the Torre names it
        bucket = 'arn:aws-partition:s3:::tower-media-replica-ACCOUNT-REPLICA-REGION/x'
        for region in ('REGION', 'REPLICA-REGION'):
            for action in ('cloudformation:CreateChangeSet', 's3:CreateBucket', 's3:ReplicateObject', 's3:PutReplicationConfiguration'):
                self.assertEqual(decide(statements, action, bucket, {'aws:RequestedRegion': region}), 'allow', (action, region))
        for action in ('cloudformation:CreateChangeSet', 's3:CreateBucket', 's3:ReplicateObject', 'ec2:CreateVpc'):
            self.assertEqual(decide(statements, action, '*', {'aws:RequestedRegion': 'ELSEWHERE'}), 'implicit', action)
        # the deployer's own app-stack statement names any region; the boundary above is what holds it to the two
        [stacks] = [item for item in self.policy('DeployerRole') if item['Sid'] == 'DeployOnlyAppStacks']
        for arn in stacks['Resource']:
            self.assertIn(':cloudformation:*:${AWS::AccountId}:', arn['Fn::Sub'])
        # the denies compacted to make room still deny what they named, on the deployer's project and the doorbell
        project = 'arn:aws-partition:codebuild:REGION:ACCOUNT:project/tower-infra-deploy'
        doorbell = 'arn:aws-partition:lambda:REGION:ACCOUNT:function:tower-deploy-doorbell'
        for action, resource in (('codebuild:UpdateProject', project), ('codebuild:DeleteProject', project),
                                 ('lambda:DeleteFunction', doorbell), ('lambda:DeleteFunctionUrlConfig', doorbell),
                                 ('lambda:AddPermission', doorbell), ('lambda:RemovePermission', doorbell),
                                 ('lambda:UpdateFunctionCode', doorbell), ('lambda:UpdateFunctionUrlConfig', doorbell)):
            self.assertEqual(decide(statements, action, resource), 'deny', action)
        self.assertLessEqual(len((INFRA / 'bootstrap.json').read_bytes()), URL_LIMIT)

    def test_the_file_is_the_template_the_account_has_applied(self):
        canonical = json.dumps(self.template, sort_keys=True, separators=(',', ':'))
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), self.APPLIED,
                         'infra/aws/bootstrap.json is not what the Torre applied: ask the Torre to apply it, then record the hash')

    def test_only_the_account_root_alarms_budgets_and_the_impaired_rule_reach_the_topic_and_only_to_publish_or_read(self):
        # AWS-REVIEW: the owner's statement named Principal * with Delete, SetAttributes, Subscribe and the permissions
        [owner, budgets, impaired, alarms] = self.resources['AlertsTopicPolicy']['Properties']['PolicyDocument']['Statement']
        self.assertEqual((owner['Sid'], owner['Principal']),
                         ('OwnerAccount', {'AWS': {'Fn::Sub': 'arn:${AWS::Partition}:iam::${AWS::AccountId}:root'}}))
        self.assertEqual(sorted(owner['Action']), ['SNS:GetTopicAttributes', 'SNS:ListSubscriptionsByTopic', 'SNS:Publish'])
        self.assertEqual((budgets['Sid'], impaired['Sid']),
                         ('BudgetsPublishTheDeployCostAlarm', 'EventBridgePublishesTheEngineImpairedRule'))
        # the Torre's deviation (a): without Principal * the account's alarms (stacks 20, 30, 40, the doorbell's) publish
        # by this statement alone, and only as alarms of this account
        self.assertEqual((alarms['Sid'], alarms['Principal'], alarms['Action']),
                         ('CloudWatchAlarmsOfTheAccountPublish', {'Service': 'cloudwatch.amazonaws.com'}, 'SNS:Publish'))
        self.assertEqual(alarms['Condition'], {
            'StringEquals': {'aws:SourceAccount': {'Ref': 'AWS::AccountId'}},
            'ArnLike': {'aws:SourceArn': {'Fn::Sub': 'arn:${AWS::Partition}:cloudwatch:${AWS::Region}:${AWS::AccountId}:alarm:*'}}})
        for statement in (budgets, impaired, alarms):
            self.assertEqual(statement['Action'], 'SNS:Publish')

    def test_the_boundary_keeps_the_alerting_path_out_of_reach(self):
        # AWS-REVIEW: no factory role deletes or rewires the topic, the Torre's queue or the deploy's log
        denies = {s['Sid']: s for s in self.resources['Boundary']['Properties']['PolicyDocument']['Statement']
                  if s['Effect'] == 'Deny'}
        topic, queue, log = (denies[sid] for sid in ('TheAlertTopicIsOutOfReach', 'TheTorreQueueIsOutOfReach',
                                                     'TheDeployLogIsOutOfReach'))
        self.assertEqual((topic['Resource'], sorted(topic['Action'])), ({'Ref': 'AlertsTopic'}, [
            'sns:DeleteTopic', 'sns:RemovePermission', 'sns:SetTopicAttributes', 'sns:Subscribe', 'sns:Unsubscribe']))
        self.assertEqual((queue['Resource'], sorted(queue['Action'])), ({'Fn::GetAtt': ['AlertsToTorreQueue', 'Arn']}, [
            'sqs:DeleteQueue', 'sqs:PurgeQueue', 'sqs:SetQueueAttributes']))
        self.assertEqual(sorted(log['Action']), ['logs:DeleteLogGroup', 'logs:DeleteRetentionPolicy', 'logs:PutRetentionPolicy'])
        groups = [each['Fn::Sub'].split('log-group:')[1] for each in log['Resource']]
        # the Torre's deviation (b): the build's real group is /tower/infra-deploy (DeployProject's LogsConfig)
        self.assertEqual(self.resources['DeployProject']['Properties']['LogsConfig']['CloudWatchLogs']['GroupName'],
                         '/tower/infra-deploy')
        self.assertEqual(sorted(groups), ['/aws/codebuild/tower-infra-deploy', '/aws/codebuild/tower-infra-deploy:*',
                                          '/tower/infra-deploy', '/tower/infra-deploy:*'])

    def test_the_public_doorbell_is_throttled_and_alarmed_and_every_rule_keeps_its_dead_letters(self):
        # AWS-REVIEW: the doorbell URL is public (AuthType NONE, a token): two at once at most, an error pages the topic
        self.assertEqual(self.resources['DoorbellFunction']['Properties']['ReservedConcurrentExecutions'], 2)
        alarm = self.resources['DoorbellErrorsAlarm']['Properties']
        self.assertEqual((alarm['Namespace'], alarm['MetricName'], alarm['Dimensions'], alarm['Statistic'], alarm['Period'],
                          alarm['Threshold'], alarm['ComparisonOperator'], alarm['AlarmActions']),
                         ('AWS/Lambda', 'Errors', [{'Name': 'FunctionName', 'Value': {'Ref': 'DoorbellFunction'}}], 'Sum', 300,
                          1, 'GreaterThanOrEqualToThreshold', [{'Ref': 'AlertsTopic'}]))
        rules = sorted(name for name, each in self.resources.items() if each['Type'] == 'AWS::Events::Rule')
        for name in rules:
            for target in self.resources[name]['Properties']['Targets']:
                self.assertEqual(target['DeadLetterConfig'], {'Arn': {'Fn::GetAtt': ['EventsDeadLetterQueue', 'Arn']}}, name)
                self.assertEqual(target['RetryPolicy'], {'MaximumRetryAttempts': 10, 'MaximumEventAgeInSeconds': 3600}, name)
        [send] = self.resources['EventsDeadLetterQueuePolicy']['Properties']['PolicyDocument']['Statement']
        self.assertEqual((send['Principal'], send['Action']), ({'Service': 'events.amazonaws.com'}, 'sqs:SendMessage'))
        self.assertEqual(sorted(each['Fn::GetAtt'][0] for each in send['Condition']['ArnEquals']['aws:SourceArn']), rules)

    def test_an_event_in_the_dead_letter_queue_alarms_the_topic(self):
        # AWS-REVIEW: an event whose 10 retries ran out lands in tower-events-dlq; one message there pages the topic
        alarm = self.resources['EventsDeadLettersAlarm']
        self.assertEqual(alarm['Type'], 'AWS::CloudWatch::Alarm')
        said = alarm['Properties']
        self.assertEqual((said['AlarmName'], said['Namespace'], said['MetricName'], said['Statistic'], said['Period']),
                         ('tower-events-dlq-messages', 'AWS/SQS', 'ApproximateNumberOfMessagesVisible', 'Maximum', 300))
        self.assertEqual(said['Dimensions'], [{'Name': 'QueueName',
                                               'Value': {'Fn::GetAtt': ['EventsDeadLetterQueue', 'QueueName']}}])
        self.assertEqual((said['Threshold'], said['ComparisonOperator'], said['TreatMissingData']),
                         (1, 'GreaterThanOrEqualToThreshold', 'notBreaching'))
        self.assertEqual(said['AlarmActions'], [{'Ref': 'AlertsTopic'}])
        self.assertEqual(self.resources['EventsDeadLetterQueue']['Properties']['QueueName'], 'tower-events-dlq')

    def test_the_deployer_reads_no_log_of_a_function_that_is_gone(self):
        # AWS-REVIEW: ReadTheConsumerLogForTheAckSmoke read /aws/lambda/tower-port-webhooks, deleted on 14/11
        sids = [statement['Sid'] for statement in self.policy('DeployerRole')]
        self.assertNotIn('ReadTheConsumerLogForTheAckSmoke', sids)
        self.assertNotIn('tower-port-webhooks', json.dumps(self.policy('DeployerRole')))

    def test_the_platforms_topic_is_tower_platform_events(self):
        # INFRA-AWS 3 (P6 F2): only the name changes; the resource and the deployer's variable keep theirs.
        self.assertIn('o tópico `tower-alerts` vira `tower-platform-events`',
                      (ROOT / 'docs/arquitetura-referencia/PLANO-DE-IMPLEMENTACAO.md').read_text(encoding='utf-8'))
        self.assertEqual(self.resources['AlertsTopic']['Properties']['TopicName'], 'tower-platform-events')
        # the old topic's name, whole: the Torre's queue (tower-alerts-torre, req-667-reach) only begins with it
        self.assertNotIn('"tower-alerts"', (INFRA / 'bootstrap.json').read_text(encoding='utf-8'))
        build = self.resources['DeployProject']['Properties']['Environment']['EnvironmentVariables']
        self.assertIn({'Name': 'ALERTS_TOPIC_ARN', 'Value': {'Ref': 'AlertsTopic'}}, build)

    def test_no_user_key_group_and_one_budget_the_deploy_cost_alarm(self):
        kinds = {resource['Type'] for resource in self.resources.values()}
        for kind in ('AWS::IAM::User', 'AWS::IAM::AccessKey', 'AWS::IAM::Group'):
            self.assertNotIn(kind, kinds)
        # BOOTSTRAP-MIRROR (the Torre, 09/11 17:19 BRT): the DEP7 deploy cost alarm is an AWS Budget (the account has no
        # AWS/Billing metrics), CodeBuild only, US$ 20 a month, credits excluded, to the platform topic; the only budget here
        budgets = {name: resource for name, resource in self.resources.items() if resource['Type'] == 'AWS::Budgets::Budget'}
        self.assertEqual(list(budgets), ['DeployCostAlarm'])
        budget = budgets['DeployCostAlarm']['Properties']
        self.assertEqual((budget['Budget']['BudgetLimit'], budget['Budget']['CostFilters']),
                         ({'Amount': 20, 'Unit': 'USD'}, {'Service': ['CodeBuild']}))
        self.assertEqual(budget['Budget']['CostTypes'], {'IncludeCredit': False, 'IncludeRefund': False})
        self.assertEqual(budget['NotificationsWithSubscribers'][0]['Subscribers'],
                         [{'SubscriptionType': 'SNS', 'Address': {'Ref': 'AlertsTopic'}}])

    def test_every_role_carries_the_boundary(self):
        roles = {name for name, resource in self.resources.items() if resource['Type'] == 'AWS::IAM::Role'}
        self.assertEqual(roles, {'CfnExecRole', 'DeployerRole', 'DoorbellRole'})
        for name in roles:
            self.assertEqual(self.resources[name]['Properties']['PermissionsBoundary'], {'Ref': 'Boundary'}, name)

    def test_the_boundary_denies_users_keys_budgets_and_the_costly(self):
        statements = self.resources['Boundary']['Properties']['PolicyDocument']['Statement']
        denied = {action for item in statements if item['Effect'] == 'Deny' for action in as_list(item.get('Action'))}
        for action in ('iam:CreateUser', 'iam:CreateAccessKey', 'budgets:*', 'ec2:RunInstances', 'ec2:CreateNatGateway'):
            self.assertIn(action, denied)
        # MEDIA-REPLICA: the two boundary denies are one pattern now (iam:*RolePermissionsBoundary)
        for action in ('iam:PutRolePermissionsBoundary', 'iam:DeleteRolePermissionsBoundary'):
            self.assertEqual(decide(statements, action, 'arn:aws-partition:iam::ACCOUNT:role/tower-app-x'), 'deny', action)
        workload = next(item for item in statements if item['Sid'] == 'WorkloadServicesInTheStackRegion')
        self.assertEqual(workload['Condition'], self.REGIONS)

    def test_the_deployer_reads_the_months_spend_and_nothing_else_of_cost_explorer(self):
        # AWS-SPEND (D-331): the identity policy and the boundary both allow ce:GetCostAndUsage, in the stack region only
        boundary = self.resources['Boundary']['Properties']['PolicyDocument']['Statement']
        deployer = self.policy('DeployerRole')
        self.assertEqual(decide(deployer, 'ce:GetCostAndUsage', '*'), 'allow')
        self.assertEqual(decide(boundary, 'ce:GetCostAndUsage', '*'), 'allow')
        self.assertEqual(decide(boundary, 'ce:GetCostAndUsage', '*', {'aws:RequestedRegion': 'ELSEWHERE'}), 'implicit')
        for action in ('ce:CreateAnomalyMonitor', 'ce:UpdateCostAllocationTagsStatus', 'ce:DeleteCostCategoryDefinition',
                       'ce:GetCostAndUsageWithResources', 'ce:GetCostForecast'):
            self.assertNotEqual(decide(boundary, action, '*'), 'allow', action)
            self.assertNotEqual(decide(deployer, action, '*'), 'allow', action)
        self.assertEqual(decide(boundary, 'budgets:ModifyBudget', '*'), 'deny')

    def test_the_boundary_lets_an_app_role_reach_the_database_by_iam_only_in_the_stack_region(self):
        # The service connects to tower-data as an IAM database user (P2 F2, P3 F1): rds-db:connect is its own service
        # prefix, outside rds:*, and an app role's permission to it is the intersection with this boundary.
        statements = self.resources['Boundary']['Properties']['PolicyDocument']['Statement']
        workload = next(item for item in statements if item['Sid'] == 'WorkloadServicesInTheStackRegion')
        self.assertIn('rds-db:connect', workload['Action'])
        self.assertEqual(workload['Condition'], self.REGIONS)

    def test_the_boundary_keeps_the_description_it_was_created_with(self):
        # A named ManagedPolicy is replaced when its description changes, and its fixed name makes the replacement fail
        # (the Torre, 04/11 13:47 BRT: 409 AlreadyExists, UPDATE_ROLLBACK_COMPLETE). The text comes from the stack's
        # region, so no template fixes one (D-304), and in this installation it resolves to the deployed text.
        described = self.resources['Boundary']['Properties']['Description']['Fn::Sub']
        self.assertEqual(described.replace('${AWS::Region}', 'us-east-1'),
                         'Upper limit of every factory role (D-303): the A1 services in us-east-1, IAM only for '
                         'tower-app-* roles that carry this boundary, and nothing on users, keys, budgets, the account '
                         'or the bootstrap')

    def test_the_deployer_touches_only_app_stacks_and_passes_one_role(self):
        for item in self.policy('DeployerRole'):
            for action in as_list(item['Action']):
                if action.startswith('cloudformation:') and action not in ('cloudformation:ValidateTemplate',
                                                                           'cloudformation:ListStacks'):
                    # BOOTSTRAP-DRIFT (req-667-reach): the bootstrap stack read, never written, for its drift
                    if action in ('cloudformation:DescribeStacks', 'cloudformation:GetTemplate') and \
                            'stack/tower-bootstrap/' in json.dumps(item['Resource']):
                        continue
                    self.assertIn('stack/tower-app-*', json.dumps(item['Resource']), action)
                if action == 'iam:PassRole':
                    self.assertEqual(item['Resource'], {'Fn::GetAtt': ['CfnExecRole', 'Arn']})
                    trusted = self.resources['CfnExecRole']['Properties']['AssumeRolePolicyDocument']
                    service = trusted['Statement'][0]['Principal']['Service']
                    self.assertEqual(item['Condition'], {'StringEquals': {'iam:PassedToService': service}})

    def boundary(self):
        return self.resources['Boundary']['Properties']['PolicyDocument']['Statement']

    def test_the_deployer_may_pass_the_execution_role_and_only_to_cloudformation(self):
        # The first deploy with stacks (the Torre, 04/11 15:25 BRT, build dcfdc4c8) was refused: an explicit deny of
        # iam:* on tower-cfn-exec in the boundary beat the allow, so the deployer could never pass the role.
        role = 'arn:aws-partition:iam::ACCOUNT:role/tower-cfn-exec'
        service = self.resources['CfnExecRole']['Properties']['AssumeRolePolicyDocument']['Statement'][0]['Principal']
        to_cloudformation = {'iam:PassedToService': service['Service']}
        self.assertEqual(decide(self.boundary(), 'iam:PassRole', role, to_cloudformation), 'allow')
        self.assertEqual(decide(self.policy('DeployerRole'), 'iam:PassRole', role, to_cloudformation), 'allow')
        self.assertNotEqual(decide(self.boundary(), 'iam:PassRole', role, {'iam:PassedToService': 'other.service'}),
                            'allow')

    def test_nothing_else_reaches_the_roles_and_the_boundary_of_the_bootstrap(self):
        for action in ('iam:PutRolePolicy', 'iam:UpdateAssumeRolePolicy', 'iam:AttachRolePolicy', 'iam:DeleteRole'):
            for role in ('tower-cfn-exec', 'tower-infra-deployer', 'tower-doorbell'):
                self.assertEqual(decide(self.boundary(), action, f'arn:aws-partition:iam::ACCOUNT:role/{role}'), 'deny',
                                 f'{action} {role}')
        for role in ('tower-infra-deployer', 'tower-doorbell'):
            self.assertNotEqual(decide(self.boundary(), 'iam:PassRole', f'arn:aws-partition:iam::ACCOUNT:role/{role}'), 'allow')
        self.assertEqual(decide(self.boundary(), 'iam:CreatePolicyVersion', 'arn:aws-partition:iam::ACCOUNT:policy/tower-boundary'),
                         'deny')

    def test_cloudformation_may_update_and_read_an_app_role_and_nothing_of_the_bootstraps(self):
        # The deploy of 04/11 17:41 BRT (build a7b56cb1) was refused iam:UpdateRoleDescription on tower-app-service: a
        # stack that edits a role's description or session, or reads its tags and instance profiles, needs these.
        for action in ('iam:UpdateRoleDescription', 'iam:UpdateRole', 'iam:ListRoleTags',
                       'iam:ListInstanceProfilesForRole'):
            self.assertEqual(decide(self.boundary(), action, 'arn:aws-partition:iam::ACCOUNT:role/tower-app-service'), 'allow',
                             action)
            for role in ('tower-cfn-exec', 'tower-infra-deployer', 'tower-doorbell'):
                self.assertEqual(decide(self.boundary(), action, f'arn:aws-partition:iam::ACCOUNT:role/{role}'), 'deny',
                                 f'{action} {role}')

    def test_an_app_role_may_infer_with_claude_in_bedrock_and_nothing_else_of_bedrock(self):
        # D-310 (Daniel 04/11 18:25 BRT): the session executor's API providers; Claude in Amazon Bedrock signs each
        # call to bedrock-mantle with the task role. Its global endpoint routes across regions, so no region condition.
        for region in ('REGION', 'other-region'):
            self.assertEqual(decide(self.boundary(), 'bedrock-mantle:CreateInference', '*',
                                    {'aws:RequestedRegion': region}), 'allow', region)
        for action in ('bedrock:CreateModelCustomizationJob', 'bedrock:CreateProvisionedModelThroughput',
                       'bedrock-mantle:AnyOtherAction', 'bedrock:CallWithBearerToken'):
            self.assertNotEqual(decide(self.boundary(), action, '*'), 'allow', action)

    def test_an_app_role_may_converse_with_bedrocks_models_but_never_with_provisioned_or_custom_ones(self):
        # D-311: Converse for Nova, Llama, Mistral and the others; a cross-region inference profile invokes the model in
        # another region, so no region condition. Provisioned throughput and custom models bill by the hour: out.
        model = 'arn:aws-partition:bedrock:other-region::foundation-model/amazon.nova-micro-v1:0'
        profile = 'arn:aws-partition:bedrock:other-region:ACCOUNT:inference-profile/us.amazon.nova-micro-v1:0'
        for resource in (model, profile):
            self.assertEqual(decide(self.boundary(), 'bedrock:InvokeModel', resource,
                                    {'aws:RequestedRegion': 'other-region'}), 'allow', resource)
        for resource in ('arn:aws-partition:bedrock:REGION:ACCOUNT:provisioned-model/abc', 'arn:aws-partition:bedrock:REGION:ACCOUNT:custom-model/x',
                         '*'):
            self.assertNotEqual(decide(self.boundary(), 'bedrock:InvokeModel', resource), 'allow', resource)

    # AGENT-ENV-BOUNDARY (D-341): the two Secrets Manager prefixes the boundary lets a role read, and the later stack's names
    SECRET = 'arn:aws-partition:secretsmanager:REGION:ACCOUNT:secret:'
    AGENT_ENV_SECRETS = ('tower/agent-env/*', 'tower/torre-webhook-*')
    SECRET_READS = ('secretsmanager:GetSecretValue', 'secretsmanager:DescribeSecret')
    A_TOKEN = 'tower/agent-env/the-tower/token-AbCdEf'

    def test_the_boundary_reads_secrets_only_under_the_agent_env_and_the_torre_webhook_prefixes(self):
        statements = self.boundary()
        [agent_env] = [item for item in statements if item['Sid'] == 'AgentEnvSecrets']
        self.assertEqual(agent_env['Effect'], 'Allow')
        self.assertEqual(sorted(agent_env['Action']), sorted(self.SECRET_READS))
        self.assertEqual(sorted(resolved(agent_env['Resource'])), sorted(self.SECRET + name for name in self.AGENT_ENV_SECRETS))
        # no other statement names Secrets Manager, and none allows it on every resource
        for item in statements:
            if item is agent_env:
                continue
            listed = as_list(item.get('Action', item.get('NotAction')))
            self.assertFalse([action for action in listed if action.startswith('secretsmanager:') or action == '*'],
                             item['Sid'])
        for action in self.SECRET_READS:
            for name in (self.A_TOKEN, 'tower/torre-webhook-key-AbCdEf', 'tower/torre-webhook-url-AbCdEf'):
                self.assertEqual(decide(statements, action, self.SECRET + name), 'allow', (action, name))
            for name in ('tower/other-AbCdEf', 'tower/agent-envoy-AbCdEf', 'site/database-url-AbCdEf'):
                self.assertEqual(decide(statements, action, self.SECRET + name), 'implicit', (action, name))
            self.assertEqual(decide(statements, action, '*'), 'implicit', action)
            elsewhere = self.SECRET.replace(':REGION:', ':ELSEWHERE:') + self.A_TOKEN
            self.assertEqual(decide(statements, action, elsewhere), 'implicit', action)

    def test_the_boundary_allows_no_secrets_manager_write(self):
        statements = self.boundary()
        for verb in ('PutSecretValue', 'CreateSecret', 'DeleteSecret', 'UpdateSecret', 'UpdateSecretVersionStage',
                     'RotateSecret', 'CancelRotateSecret', 'RestoreSecret', 'PutResourcePolicy', 'TagResource',
                     'ListSecrets', 'BatchGetSecretValue'):
            for resource in ('*', self.SECRET + self.A_TOKEN):
                self.assertNotEqual(decide(statements, f'secretsmanager:{verb}', resource), 'allow', (verb, resource))

    def test_the_bootstrap_names_no_account_id(self):
        # every ARN says ${AWS::AccountId}; a literal 12-digit account would leak it and pin the template to one account
        text = (INFRA / 'bootstrap.json').read_text(encoding='utf-8')
        self.assertEqual(re.findall(r'(?<![0-9])[0-9]{12}(?![0-9])', text), [])

    def test_the_execution_role_creates_the_agent_env_functions_roles_and_parameters(self):
        # tower-cfn-exec's one policy is the boundary, so its patterns already reach the later stack (45-agent-env)
        exec_role = self.resources['CfnExecRole']['Properties']
        self.assertEqual(exec_role['ManagedPolicyArns'], [{'Ref': 'Boundary'}])
        self.assertNotIn('Policies', exec_role)
        statements = self.boundary()
        bounded = {'iam:PermissionsBoundary': 'arn:aws-partition:iam::ACCOUNT:policy/tower-boundary'}
        for name in ('tower-app-agent-env-the-tower', 'tower-app-torre-relay'):
            function = f'arn:aws-partition:lambda:REGION:ACCOUNT:function:{name}'
            for action in ('lambda:CreateFunction', 'lambda:UpdateFunctionCode', 'lambda:AddPermission', 'lambda:DeleteFunction'):
                self.assertEqual(decide(statements, action, function), 'allow', (action, name))
            role = f'arn:aws-partition:iam::ACCOUNT:role/{name}'
            for action in ('iam:CreateRole', 'iam:PutRolePolicy'):
                self.assertEqual(decide(statements, action, role, bounded), 'allow', (action, name))
                self.assertEqual(decide(statements, action, role), 'implicit', (action, name))
            self.assertEqual(decide(statements, 'iam:PassRole', role), 'allow', name)
        for path in ('/tower/agent-env/the-tower/token-sha256', '/tower/torre-relay/allowed'):
            parameter = f'arn:aws-partition:ssm:REGION:ACCOUNT:parameter{path}'
            for action in ('ssm:PutParameter', 'ssm:GetParameter', 'ssm:GetParametersByPath', 'ssm:DeleteParameter'):
                self.assertEqual(decide(statements, action, parameter), 'allow', (action, path))
            self.assertEqual(decide(statements, 'ssm:GetParameter', parameter, {'aws:RequestedRegion': 'ELSEWHERE'}),
                             'implicit', path)

    def test_key_grants_go_only_to_aws_services(self):
        # RDS encrypts tower-data with the AWS managed key, which needs a grant made for the service.
        self.assertEqual(decide(self.boundary(), 'kms:CreateGrant', '*', {'kms:GrantIsForAWSResource': 'true'}), 'allow')
        self.assertNotEqual(decide(self.boundary(), 'kms:CreateGrant', '*', {'kms:GrantIsForAWSResource': 'false'}),
                            'allow')

    def test_the_deployer_reads_every_parameter_its_stacks_name(self):
        # CloudFormation may resolve a stack's SSM parameters and dynamic references with the caller's identity.
        named = set()
        for path in sorted((INFRA / 'stacks').glob('*.json')):
            text = path.read_text(encoding='utf-8')
            named |= set(re.findall(r'\{\{resolve:ssm(?:-secure)?:(/[^:}]+)', text))
            named |= {item['Default'] for item in load(path).get('Parameters', {}).values()
                      if item['Type'].startswith('AWS::SSM::Parameter::Value')}
        self.assertTrue(named)
        for name in sorted(named):
            self.assertEqual(decide(self.policy('DeployerRole'), 'ssm:GetParameters',
                                    f'arn:aws-partition:ssm:REGION:ACCOUNT:parameter{name}'), 'allow', name)

    def test_the_doorbell_can_only_start_the_deploy(self):
        actions = {action for item in self.policy('DoorbellRole') for action in as_list(item['Action'])}
        self.assertEqual(actions, {'codebuild:StartBuild', 'lambda:InvokeFunction', 'logs:CreateLogStream', 'logs:PutLogEvents',
                                   'ssm:GetParameter', 'ssm:PutParameter', 'ssm:DeleteParameter'})
        # RING-QUEUE: the SSM actions on the one pending-ring parameter, nothing else
        [pending] = [item for item in self.policy('DoorbellRole') if item['Sid'] == 'KeepTheRingPending']
        self.assertEqual(pending['Resource'], {'Fn::Sub': 'arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}'
                                                          ':parameter/tower/deploy/ring-pending'})
        # QUEUE-RELOAD: and pass the merge queue's words to the port's alias, nothing else
        invoke = [item for item in self.policy('DoorbellRole') if 'lambda:InvokeFunction' in as_list(item['Action'])]
        self.assertEqual([item['Resource'] for item in invoke], [
            {'Fn::Sub': 'arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:tower-port-api:live'}])
        # GITHUB-HOOK: and read the webhook's secret, that one parameter alone
        [hook] = [item for item in self.policy('DoorbellRole') if item['Sid'] == 'ReadTheGitHubHookSecret']
        self.assertEqual((hook['Action'], hook['Resource']), ('ssm:GetParameter', {
            'Fn::Sub': 'arn:${AWS::Partition}:ssm:${AWS::Region}:${AWS::AccountId}:parameter/tower/deploy/github-webhook-secret'}))
        code = self.resources['DoorbellFunction']['Properties']['Code']['ZipFile']
        self.assertIn('timingSafeEqual', code)
        self.assertIn("createHash('sha256')", code)
        self.assertIn("createHmac('sha256', secret)", code)
        self.assertLessEqual(len(code), 4096)  # CloudFormation's ZipFile limit
        # SIGNED-HOOK: every signed event goes to the port as a hook word; the port, not the doorbell, picks the push to main
        self.assertIn("said = { event: 'hook', kind: h['x-github-event'], ref: said.ref, after: said.after, deleted: !!said.deleted }",
                      code)
        self.assertNotIn("!== 'push'", code)
        token = self.template['Parameters']['DoorbellTokenSha256']
        self.assertTrue(token['NoEcho'])
        self.assertEqual(token['AllowedPattern'], '^[0-9a-f]{64}$')

    def test_the_deploy_state_rule_may_invoke_only_the_port_alias_and_the_doorbell(self):
        # DEP-EVENTS (the Torre, 09/11 17:19 BRT): CodeBuild Build State Change of tower-infra-deploy -> tower-port-api:live,
        # the invoke permission limited to that rule's ARN and this account
        rule = self.resources['DeployStateRule']['Properties']
        self.assertEqual(rule['EventPattern'], {'source': ['aws.codebuild'], 'detail-type': ['CodeBuild Build State Change'],
                                                'detail': {'project-name': ['tower-infra-deploy']}})
        target = {'Fn::Sub': 'arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:tower-port-api:live'}
        doorbell = {'Fn::GetAtt': ['DoorbellFunction', 'Arn']}  # RING-QUEUE: a build's end starts the pending ring
        self.assertEqual([each['Arn'] for each in rule['Targets']], [target, doorbell])
        for name, function in (('DeployStateInvokePermission', target), ('DeployStateDoorbellPermission', doorbell)):
            permission = self.resources[name]['Properties']
            self.assertEqual((permission['FunctionName'], permission['Principal'], permission['SourceArn'],
                              permission['SourceAccount'], permission['Action']),
                             (function, 'events.amazonaws.com', {'Fn::GetAtt': ['DeployStateRule', 'Arn']},
                              {'Ref': 'AWS::AccountId'}, 'lambda:InvokeFunction'))

    def test_a_stack_s_end_wakes_the_port_and_an_engine_ecs_cannot_keep_up_goes_to_the_topic(self):
        # The Torre applied both on 11/11 14:58 UTC (change set req1455-rules); this is their mirror. StackStateRule
        # (SLOW-PATH-NO-ROLLOUT-WAIT): the end of an operation of a tower-app-* stack -> tower-port-api:live, so the build
        # that verifies a rollout is rung by the stack's end, not before it. EngineImpairedRule: ECS's own events of a
        # service it cannot keep up -> the platform's topic, with no code of the engine in the path
        target = {'Fn::Sub': 'arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:tower-port-api:live'}
        stack = self.resources['StackStateRule']['Properties']
        self.assertEqual(stack['EventPattern']['source'], ['aws.cloudformation'])
        self.assertEqual(stack['EventPattern']['detail']['stack-id'],
                         [{'prefix': {'Fn::Sub': 'arn:${AWS::Partition}:cloudformation:${AWS::Region}:${AWS::AccountId}:stack/tower-app-'}}])
        self.assertIn('UPDATE_ROLLBACK_COMPLETE', stack['EventPattern']['detail']['status-details']['status'])
        self.assertEqual([each['Arn'] for each in stack['Targets']], [target])
        permission = self.resources['StackStateInvokePermission']['Properties']
        self.assertEqual((permission['FunctionName'], permission['Principal'], permission['SourceArn']),
                         (target, 'events.amazonaws.com', {'Fn::GetAtt': ['StackStateRule', 'Arn']}))
        impaired = self.resources['EngineImpairedRule']['Properties']
        self.assertEqual(impaired['EventPattern'], {
            'source': ['aws.ecs'], 'detail-type': ['ECS Service Action', 'ECS Deployment State Change'],
            'detail': {'eventName': ['SERVICE_TASK_START_IMPAIRED', 'SERVICE_DEPLOYMENT_FAILED', 'SERVICE_TASK_PLACEMENT_FAILURE']}})
        self.assertEqual([each['Arn'] for each in impaired['Targets']], [{'Ref': 'AlertsTopic'}])
        allowed = [each for each in self.resources['AlertsTopicPolicy']['Properties']['PolicyDocument']['Statement']
                   if each.get('Sid') == 'EventBridgePublishesTheEngineImpairedRule']
        self.assertEqual([(each['Principal'], each['Action'], each['Condition']) for each in allowed],
                         [({'Service': 'events.amazonaws.com'}, 'SNS:Publish',
                           {'ArnEquals': {'aws:SourceArn': {'Fn::GetAtt': ['EngineImpairedRule', 'Arn']}}})])

    def test_a_stopped_task_and_a_service_s_warning_of_the_engine_s_cluster_wake_the_port(self):
        # ECS-STOPS-IN-LOG: the Torre applied both on 12/11 16:51 UTC (change set req-ecs-stops-1350); this is their
        # mirror. A task of the cluster tower that STOPPED (its stopCode and stoppedReason: ECS forgets them in an hour)
        # and a service's WARN or ERROR (a placement failure, a start impaired) -> tower-port-api:live, which writes
        # platform.ecs.task_stopped and platform.ecs.service_action (tower_infra.http_port.ecs_state)
        target = {'Fn::Sub': 'arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:tower-port-api:live'}
        stopped = self.resources['EcsTaskStoppedRule']['Properties']
        self.assertEqual((stopped['Name'], stopped['State'], stopped['EventPattern']), ('tower-ecs-task-stopped', 'ENABLED', {
            'source': ['aws.ecs'], 'detail-type': ['ECS Task State Change'], 'detail': {
                'clusterArn': [{'Fn::Sub': 'arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:cluster/tower'}],
                'lastStatus': ['STOPPED']}}))
        action = self.resources['EcsServiceActionRule']['Properties']
        self.assertEqual((action['Name'], action['State'], action['EventPattern']), ('tower-ecs-service-action', 'ENABLED', {
            'source': ['aws.ecs'], 'detail-type': ['ECS Service Action'],
            'resources': [{'prefix': {'Fn::Sub': 'arn:${AWS::Partition}:ecs:${AWS::Region}:${AWS::AccountId}:service/tower/'}}],
            'detail': {'eventType': ['WARN', 'ERROR']}}))
        for rule, permission in (('EcsTaskStoppedRule', 'EcsTaskStoppedInvokePermission'),
                                 ('EcsServiceActionRule', 'EcsServiceActionInvokePermission')):
            [only] = self.resources[rule]['Properties']['Targets']
            self.assertEqual((only['Id'], only['Arn']), ('tower-port-api-live', target))
            allowed = self.resources[permission]['Properties']
            self.assertEqual((allowed['FunctionName'], allowed['Action'], allowed['Principal'], allowed['SourceArn']),
                             (target, 'lambda:InvokeFunction', 'events.amazonaws.com', {'Fn::GetAtt': [rule, 'Arn']}))

    def test_the_public_url_carries_both_permissions(self):
        # Since October 2025 a function URL with AuthType NONE also needs lambda:InvokeFunction limited to calls that
        # come through the URL; with only lambda:InvokeFunctionUrl it answers 403 (the Torre, 04/11 09:00 BRT).
        permissions = {resource['Properties']['Action']: resource['Properties']
                       for name, resource in self.resources.items()
                       if resource['Type'] == 'AWS::Lambda::Permission' and name.startswith('Doorbell')}
        self.assertEqual(permissions['lambda:InvokeFunctionUrl']['FunctionUrlAuthType'], 'NONE')
        self.assertIs(permissions['lambda:InvokeFunction']['InvokedViaFunctionUrl'], True)
        for permission in permissions.values():
            self.assertEqual(permission['FunctionName'], {'Ref': 'DoorbellFunction'})

    def test_the_build_clones_the_public_repository_without_a_key(self):
        # BUILD-NO-ORIGIN (D-314): the base is a public GitHub repository, so the clone needs no credential; the build
        # installs no Origin CLI and reads no Parameter Store key, and a revoked Cursor key can no longer fail it.
        spec = self.resources['DeployProject']['Properties']['Source']['BuildSpec']
        for gone in ('parameter-store', 'CURSOR_', '/tower/origin/', 'downloads.cursor.com', 'origin auth', 'origin --version'):
            self.assertNotIn(gone, spec)
        self.assertLess(spec.index('git clone'), spec.index('bash repo/infra/aws/deploy.sh'))

    def test_the_build_never_exits_its_shell(self):
        # CodeBuild runs the commands of a buildspec 0.2 in one shell; an exit there ends the phase early.
        spec = self.resources['DeployProject']['Properties']['Source']['BuildSpec']
        self.assertIsNone(re.search(r'(^|[;&|\s])exit\b', spec))

    def test_the_build_deploys_the_base_head_as_app_stacks(self):
        project = self.resources['DeployProject']['Properties']
        self.assertEqual(project['ConcurrentBuildLimit'], 1)
        self.assertEqual(project['Source']['Type'], 'NO_SOURCE')
        spec = project['Source']['BuildSpec']
        spec += (INFRA / 'deploy.sh').read_text()  # DEP1: the deploy logic is in the repo, the buildspec runs it
        for needle in ('--branch "$BASE_BRANCH"', '--stack-name "tower-app-$n"',
                       '--role-arn "$CFN_EXEC_ROLE_ARN"', '/tower/deploy/last-sha', 'bash repo/infra/aws/deploy.sh'):
            self.assertIn(needle, spec)
        # AWS-REVIEW: a re-apply with the defaults deploys GitHub's main, never Origin's mod/roadmap-integration
        self.assertEqual(self.template['Parameters']['BaseBranch']['Default'], 'main')
        self.assertEqual(self.template['Parameters']['OriginRepoUrl']['Default'],
                         'https://github.com/openuniversity-si/open-university.git')

    def test_the_deployer_pushes_only_tower_images_and_records_only_its_own_parameters(self):
        # INFRA-SVC 1a: the boundary lets a stack start CodeBuild but never create a project, so the deployer builds
        # the images itself; it may push only to tower-* repositories and write only the last head and the images.
        for item in self.policy('DeployerRole'):
            for action in as_list(item['Action']):
                if action.startswith('ecr:') and action != 'ecr:GetAuthorizationToken':
                    self.assertIn('repository/tower-*', json.dumps(item['Resource']), action)
                if action == 'ssm:PutParameter':
                    self.assertRegex(json.dumps(item['Resource']), r'parameter/tower/deploy/(last-sha|last-build|image/\*)"')

    def test_the_deployer_publishes_the_lambda_packages_to_one_prefix_and_nothing_else(self):
        # DEPLOYER-ARTIFACT-IAM: DEP8 puts the zips and the layer zip at artifacts/lambda/ of the outputs bucket (the build was
        # refused with AccessDenied on s3:PutObject). Exactly put and get on that prefix: no bucket-wide ARN, no delete, no
        # list; the layer is an AWS::Lambda::LayerVersion of the stack (the execution role), so no lambda:*Layer* for the deployer.
        policy = self.policy('DeployerRole')
        prefix = 'arn:aws-partition:s3:::tower-outputs-ACCOUNT-REGION/artifacts/lambda/'
        for action in ('s3:PutObject', 's3:GetObject'):
            self.assertEqual(decide(policy, action, prefix + 'tower-port/0123abc.zip'), 'allow', action)
            self.assertEqual(decide(policy, action, prefix + 'deps/0123abc.zip'), 'allow', action)
            self.assertEqual(decide(policy, action, 'arn:aws-partition:s3:::tower-outputs-ACCOUNT-REGION/other/x.zip'), 'implicit', action)
            self.assertEqual(decide(policy, action, 'arn:aws-partition:s3:::another-bucket/artifacts/lambda/x.zip'), 'implicit', action)
        for action in ('s3:DeleteObject', 's3:ListBucket', 's3:PutBucketPolicy', 's3:PutObjectAcl'):
            self.assertEqual(decide(policy, action, prefix + 'tower-port/0123abc.zip'), 'implicit', action)
        for item in policy:
            for action in as_list(item['Action']):
                if action.startswith('s3:'):
                    self.assertIn(action, ('s3:PutObject', 's3:GetObject'))
                    self.assertEqual(resolved(item['Resource']), prefix + '*')
                self.assertFalse(action.startswith('lambda:'), action)
        # the execution role reads the same keys through the boundary, which lets s3 and lambda (the unchanged boundary)
        boundary = self.resources['Boundary']['Properties']['PolicyDocument']['Statement']
        self.assertEqual(decide(boundary, 's3:GetObject', prefix + 'deps/0123abc.zip'), 'allow')
        self.assertEqual(decide(boundary, 'lambda:PublishLayerVersion', 'arn:aws-partition:lambda:REGION:ACCOUNT:layer:tower-port-deps'), 'allow')

    def test_the_build_makes_arm_images_tagged_by_their_content(self):
        environment = self.resources['DeployProject']['Properties']['Environment']
        self.assertEqual(environment['Type'], 'ARM_CONTAINER')  # the service runs on Fargate ARM
        self.assertIs(environment['PrivilegedMode'], True)  # Docker needs it
        self.assertIn('IMAGE_REGISTRY', {variable['Name'] for variable in environment['EnvironmentVariables']})
        spec = (INFRA / 'deploy.sh').read_text()  # DEP1: the images are built by the script the buildspec runs
        for needle in ('/infra/*/Dockerfile', 'rev-parse "HEAD:infra/$name" "HEAD:infra/db"',
                       '--image-tag-mutability IMMUTABLE', '/tower/deploy/image/$name'):
            self.assertIn(needle, spec)
        self.assertLess(spec.index('docker push'), spec.rindex('  deploy_stacks\n'))


# STUBS-ON-PATH (the Torre, 18/11/2026): the stubs are executables on PATH as well as exported functions. deploy.sh runs
# some calls through `timeout 60 aws ...`, and timeout executes the aws on PATH, not a shell function: on GitHub's runner
# that was the real AWS CLI (installed there, absent here), 77 calls of a run that waited on its credential lookup
# (infra-aws: 35.8 s in #215's gate, 56.4 s in #158's, 4 s locally), and a run with credentials would have reached AWS.
AWS_BODY = """  echo "aws $1 $2" >> "$CALLS_FILE"
  case "$1 $2" in
    "ecr describe-images") [ -n "$IMAGE_EXISTS" ] ;;
    "ecr get-login-password") echo token ;;
    "ssm get-parameter") echo "$LAST" ;;
    "cloudformation describe-stack-events") printf '%s\\tService\\tUPDATE_FAILED\\tthe reason\\n' "$(date -u +%Y-%m-%dT%H:%M:%S.000000+00:00)" ;;
    "cloudformation deploy") case " $* " in *" --stack-name $FAIL_STACK "*) return 1 2>/dev/null || exit 1 ;; esac ;;
    "ssm put-parameter") echo "put $4" >> "$CALLS_FILE" ;;
  esac
"""
DOCKER_BODY = """  echo "docker $1" >> "$CALLS_FILE"
"""
DEPLOY_STUBS = f'''
aws() {{
{AWS_BODY}}}
docker() {{
{DOCKER_BODY}}}
export -f aws docker
'''


class DeployScriptTests(unittest.TestCase):
    """infra/aws/deploy.sh, the deploy the buildspec delegates to, run in bash on a throwaway checkout with aws and docker
    stubbed: what is recorded as deployed is what deployed, so a failed stack is deployed again by the next ring.
    (test_deploy.py covers the recorded outcome; this keeps the original behaviour tests.)"""

    def run_deploy(self, head='H2', last='H1', fail_stack='', image_exists=''):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            for name in ('infra/service/Dockerfile', 'infra/db/migration.sql', 'infra/aws/stacks/10-first.json',
                         'infra/aws/stacks/20-second.json'):
                (repo / name).parent.mkdir(parents=True, exist_ok=True)
                (repo / name).write_text('{}\n')
            git = ['git', '-C', str(repo), '-c', 'user.name=test', '-c', 'user.email=test', '-c', 'commit.gpgsign=false']
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            subprocess.run(git + ['add', '-A'], check=True)
            subprocess.run(git + ['commit', '-q', '-m', 'base'], check=True)
            sha = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True, text=True,
                                 check=True).stdout.strip()
            calls = Path(tmp) / 'calls'
            bin_dir = Path(tmp) / 'bin'  # STUBS-ON-PATH: what `timeout aws` finds, never the real CLI
            bin_dir.mkdir()
            for name, body in (('aws', AWS_BODY), ('docker', DOCKER_BODY)):
                (bin_dir / name).write_text('#!' + (shutil.which('bash') or '/bin/bash') + '\n' + body)
                (bin_dir / name).chmod(0o755)
            script = DEPLOY_STUBS + f'bash {INFRA / "deploy.sh"}\n'
            env = {**os.environ, 'IMAGE_REGISTRY': 'registry', 'CFN_EXEC_ROLE_ARN': 'role', 'DEPLOY_REPO': str(repo),
                   'LAST': sha if head == last else 'H1', 'FAIL_STACK': fail_stack or 'none',
                   'IMAGE_EXISTS': image_exists, 'CALLS_FILE': str(calls), 'DEPLOY_LAMBDA_PACKAGE_CMD': "echo '{}'",
                   'PATH': f'{bin_dir}:{os.environ["PATH"]}'}
            done = subprocess.run(['bash', '-c', script], cwd=tmp, capture_output=True, text=True, check=False, env=env)
            self.stdout = done.stdout
            return str(done.returncode), calls.read_text().splitlines()

    def test_a_failed_stack_keeps_the_last_deployed_head_and_fails_the_build(self):
        status, calls = self.run_deploy(fail_stack='tower-app-second')
        self.assertNotEqual(status, '0')
        self.assertNotIn('put /tower/deploy/last-sha', calls)
        self.assertIn('put /tower/deploy/image/service', calls)

    def test_a_failed_stack_prints_its_failed_events_into_the_log(self):
        self.stdout = ''
        self.run_deploy(fail_stack='tower-app-second')
        self.assertIn('Service\tUPDATE_FAILED\tthe reason', self.stdout)

    def test_a_clean_deploy_records_the_image_and_then_the_head(self):
        status, calls = self.run_deploy()
        self.assertEqual(status, '0')
        self.assertIn('docker build', calls)
        self.assertLess(calls.index('put /tower/deploy/image/service'), calls.index('put /tower/deploy/last-sha'))

    def test_an_image_already_built_is_not_built_again(self):
        status, calls = self.run_deploy(image_exists='yes')
        self.assertEqual(status, '0')
        self.assertNotIn('docker build', calls)
        self.assertIn('put /tower/deploy/image/service', calls)

    def test_the_head_already_deployed_deploys_nothing(self):
        status, calls = self.run_deploy(head='H1', last='H1')
        self.assertEqual(status, '0')
        # STUBS-ON-PATH: the one CloudFormation call is the read of the bootstrap's template (BOOTSTRAP-DRIFT, every build);
        # before, it went through `timeout` to the real CLI and was not seen here. No stack is read, changed or deployed.
        self.assertEqual([call for call in calls if call.startswith('aws cloudformation')], ['aws cloudformation get-template'])


IAM_PREFIX = {'ApiGatewayV2': 'apigateway', 'ApplicationAutoScaling': 'application-autoscaling'}
DENIED_TYPES = ('AWS::EC2::NatGateway', 'AWS::EC2::EIP', 'AWS::EC2::Instance', 'AWS::IAM::User',
                'AWS::IAM::AccessKey', 'AWS::RDS::DBCluster')


class StackTests(unittest.TestCase):
    """The stacks the deployer applies stay inside the boundary the bootstrap draws, so a merged template cannot ask
    for more than the execution role may do."""

    def setUp(self):
        boundary = load(INFRA / 'bootstrap.json')['Resources']['Boundary']['Properties']['PolicyDocument']
        workload = next(item for item in boundary['Statement'] if item['Sid'] == 'WorkloadServicesInTheStackRegion')
        self.allowed = {action.split(':')[0] for action in workload['Action'] if action.endswith(':*')}
        # DNS-ROUTE53: Route 53 has its own statement (DnsStackTests), the zone and its records only
        self.allowed |= {'route53'} if any(item['Sid'] == 'TheSiteZoneOnRoute53' for item in boundary['Statement']) else set()
        self.stacks = sorted((INFRA / 'stacks').glob('*.json'))

    def test_every_file_names_its_stack(self):
        self.assertTrue(self.stacks)
        for path in self.stacks:
            self.assertRegex(path.name, r'^\d+-[a-z0-9-]+\.json$')

    def test_every_resource_is_a_service_the_boundary_allows(self):
        for path in self.stacks:
            for name, resource in load(path)['Resources'].items():
                kind = resource['Type']
                self.assertNotIn(kind, DENIED_TYPES, f'{path.name} {name}')
                if kind == 'AWS::IAM::Role':
                    boundary = resource['Properties'].get('PermissionsBoundary')
                    self.assertIn('policy/tower-boundary', json.dumps(boundary), f'{path.name} {name}')
                    continue
                service = kind.split('::')[1]
                self.assertIn(IAM_PREFIX.get(service, service.lower()), self.allowed, f'{path.name} {name} {kind}')

    def test_every_ecs_health_check_is_inside_the_limits_ecs_enforces(self):
        found = 0
        for path in self.stacks:
            for name, resource in load(path)['Resources'].items():
                if resource['Type'] != 'AWS::ECS::TaskDefinition':
                    continue
                for container in resource['Properties']['ContainerDefinitions']:
                    check = container.get('HealthCheck')
                    if not check:
                        continue
                    found += 1
                    where = f'{path.name} {name} {container.get("Name")}'
                    self.assertLessEqual(check.get('StartPeriod', 0), 300, where)
                    self.assertTrue(5 <= check.get('Interval', 30) <= 300, where)
                    self.assertTrue(1 <= check.get('Retries', 3) <= 10, where)
                    self.assertLess(check.get('Timeout', 5), check.get('Interval', 30), where)
        self.assertGreaterEqual(found, 1)  # the service's (SPOT-STANDBY-GONE: the standby's left with its task definition)

    def test_the_network_has_no_nat_and_a_private_database(self):
        resources = load(INFRA / 'stacks/10-network.json')['Resources']
        kinds = [resource['Type'] for resource in resources.values()]
        subnets = [name for name, resource in resources.items() if resource['Type'] == 'AWS::EC2::Subnet']
        self.assertEqual(sorted(subnets), ['PrivateSubnetA', 'PrivateSubnetB', 'PublicSubnetA', 'PublicSubnetB'])
        self.assertIn('AWS::EC2::VPCEndpoint', kinds)
        routes = [resource['Properties'] for resource in resources.values() if resource['Type'] == 'AWS::EC2::Route']
        self.assertEqual([route['RouteTableId'] for route in routes], [{'Ref': 'PublicRouteTable'}])
        ingress = [resource['Properties'] for resource in resources.values()
                   if resource['Type'] == 'AWS::EC2::SecurityGroupIngress']
        self.assertEqual([rule['SourceSecurityGroupId'] for rule in ingress], [{'Ref': 'TasksSecurityGroup'}])
        groups = [resource['Properties'] for resource in resources.values()
                  if resource['Type'] == 'AWS::EC2::SecurityGroup']
        self.assertFalse(any('SecurityGroupIngress' in group for group in groups))
        # AWS-REVIEW: the database opens no connection, so its group keeps no default allow-all egress
        [egress] = resources['DatabaseSecurityGroup']['Properties']['SecurityGroupEgress']
        self.assertEqual((egress['CidrIp'], egress['IpProtocol'], egress['FromPort'], egress['ToPort']),
                         ('127.0.0.1/32', 'icmp', 252, 86))

    def test_the_cluster_offers_fargate_alone(self):
        # AWS-REVIEW: nothing places a task on Spot since SPOT-STANDBY-GONE (the service and the runner are FARGATE)
        cluster = load(INFRA / 'stacks/30-service.json')['Resources']['Cluster']['Properties']
        self.assertEqual(cluster['CapacityProviders'], ['FARGATE'])


PLAN = ROOT / 'docs/arquitetura-referencia/PLANO-DE-IMPLEMENTACAO.md'
POSTGRES = ROOT / 'config/registry/toolchain/toolchain.postgres_version.json'


class DataStackTests(unittest.TestCase):
    """P2 F2: the A1 database as the plan sizes it (D-303), private, with no password in the repository, holding only the
    infrastructure's schemas (D-306) and growing by its parameters alone."""

    def setUp(self):
        self.template = load(INFRA / 'stacks/20-data.json')
        self.database = self.template['Resources']['Database']
        self.properties = self.database['Properties']

    def default(self, prop):
        return self.template['Parameters'][self.properties[prop]['Ref']]['Default']

    def test_the_windows_are_the_templates_and_the_ones_the_account_had(self):
        # RDS-WINDOWS-MIRROR (architecture review, finding 25): the instance had the windows AWS chose when it was made
        # and the template said none, so nothing kept a maintenance from moving. Read in the account on 12/11 (UTC):
        # maintenance thu:07:57-thu:08:27, backup 07:12-07:42. The same values: the apply changes nothing in the instance
        self.assertEqual(self.properties['PreferredMaintenanceWindow'], {'Ref': 'MaintenanceWindow'})
        self.assertEqual(self.properties['PreferredBackupWindow'], {'Ref': 'BackupWindow'})
        maintenance, backup = self.default('PreferredMaintenanceWindow'), self.default('PreferredBackupWindow')
        self.assertEqual((maintenance, backup), ('thu:07:57-thu:08:27', '07:12-07:42'))

        def minutes(clock):
            return int(clock[:2]) * 60 + int(clock[3:])
        day, start, _, end = maintenance[:3], maintenance[4:9], maintenance[10:13], maintenance[14:]
        opened, closed = backup.split('-')
        self.assertGreaterEqual(minutes(end) - minutes(start), 30)  # RDS's least, for each
        self.assertGreaterEqual(minutes(closed) - minutes(opened), 30)
        self.assertTrue(minutes(closed) <= minutes(start) or minutes(opened) >= minutes(end))  # they may not overlap
        self.assertEqual(day, 'thu')
        for name in ('MaintenanceWindow', 'BackupWindow'):
            self.assertRegex(self.template['Parameters'][name]['Default'], self.template['Parameters'][name]['AllowedPattern'])

    def test_it_is_the_database_the_plan_sizes(self):
        size, storage = re.search(r'RDS PostgreSQL (db\.t4g\.\w+) numa zona, (\d+) GB, backup contínuo',
                                  PLAN.read_text(encoding='utf-8')).groups()
        self.assertEqual(self.default('DBInstanceClass'), size)
        self.assertEqual(str(self.default('AllocatedStorage')), storage)
        self.assertEqual(self.default('MultiAZ'), 'false')
        self.assertGreaterEqual(self.default('BackupRetentionPeriod'), 1)  # retention keeps point-in-time recovery
        self.assertEqual(self.properties['StorageType'], 'gp3')

    def test_the_server_s_shared_buffers_leave_the_micro_s_memory_to_what_runs_on_it(self):
        """DATA-SHARED-BUFFERS: the engine's own reading of the database's host (12/11 05:19 and 05:39 UTC): 943 MB of
        memory, 550 to 620 MB in swap at any load, `shared_buffers` 184648 kB (RDS's default, a quarter of the class's
        memory) for a database of 147 MB. What wakes waits for the disk: the stall at each landing. The stack has its own
        parameter group (the default one cannot be changed) and sizes shared_buffers by a parameter: 64 MB."""
        group = self.template['Resources']['ServerParameters']
        self.assertEqual(group['Type'], 'AWS::RDS::DBParameterGroup')
        self.assertEqual(group['Properties']['Family'],  # the major version's family, whatever minor the parameter names
                         {'Fn::Join': ['', ['postgres', {'Fn::Select': [0, {'Fn::Split': ['.', {'Ref': 'EngineVersion'}]}]}]]})
        # DATA-WORK-MEM: and what a vacuum or a maintenance command may take, and no parallel workers: the engine read
        # maintenance_work_mem and autovacuum_work_mem at 64 MB each with three autovacuum workers (12/11 07:16 UTC), on
        # a host of 943 MB that pages; a parallel worker is a process more to start on it. None of the three restarts
        # the database (they are dynamic)
        self.assertEqual(group['Properties']['Parameters'], {
            'shared_buffers': {'Ref': 'SharedBuffers'}, 'maintenance_work_mem': '32768', 'autovacuum_work_mem': '16384',
            'max_parallel_workers_per_gather': '0'})
        self.assertEqual(self.properties['DBParameterGroupName'], {'Ref': 'ServerParameters'})
        sized = self.template['Parameters']['SharedBuffers']
        self.assertEqual((sized['Type'], sized['Default'], sized['Default'] * 8 // 1024), ('Number', 8192, 64))  # 8 kB pages

    def test_it_runs_the_postgresql_the_acceptance_test_runs_on(self):
        # work and log use uuidv7(), so the database is the toolchain's major version, where scripts/tests/infra-db runs.
        self.assertEqual(self.properties['Engine'], 'postgres')
        self.assertEqual(self.default('EngineVersion'), load(POSTGRES)['default'].split('.')[0])

    def test_it_is_private_and_reached_only_from_the_tasks(self):
        self.assertIs(self.properties['PubliclyAccessible'], False)
        self.assertEqual(self.properties['VPCSecurityGroups'], [{'Fn::ImportValue': 'tower-network-database-sg'}])
        self.assertEqual(self.template['Resources']['SubnetGroup']['Properties']['SubnetIds'],
                         {'Fn::Split': [',', {'Fn::ImportValue': 'tower-network-private-subnets'}]})
        network = load(INFRA / 'stacks/10-network.json')['Outputs'].values()
        self.assertLessEqual({'tower-network-database-sg', 'tower-network-private-subnets'},
                             {output['Export']['Name'] for output in network})

    def test_no_password_in_the_repository_and_iam_for_the_service(self):
        # A SecureString the Torre creates, read by reference; Secrets Manager (ManageMasterUserPassword) is outside
        # the boundary, and the service connects with IAM authentication.
        self.assertRegex(self.properties['MasterUserPassword'], r'^\{\{resolve:ssm-secure:/tower/db/[\w-]+:\d+\}\}$')
        self.assertNotIn('ManageMasterUserPassword', self.properties)
        self.assertIs(self.properties['EnableIAMDatabaseAuthentication'], True)

    def test_it_keeps_its_data(self):
        self.assertIs(self.properties['StorageEncrypted'], True)
        self.assertIs(self.properties['DeletionProtection'], True)
        self.assertEqual((self.database['DeletionPolicy'], self.database['UpdateReplacePolicy']), ('Snapshot', 'Snapshot'))

    def test_the_service_finds_it_by_its_exports(self):
        self.assertEqual({output['Export']['Name'] for output in self.template['Outputs'].values()},
                         {'tower-data-endpoint', 'tower-data-port', 'tower-data-resource-id', 'tower-data-name'})


LAYERS = ROOT / 'docs/domain/decisions/D-304.md'
EXECUTORS = ROOT / 'docs/domain/decisions/D-305.md'
BOUNDARY = ROOT / 'docs/domain/decisions/D-306.md'
# D-306 (amending D-304 and D-305): the infrastructure knows only work, so its schemas are work and log, with the
# orchestrator's dbos; and the words of management and leadership that no infrastructure name may carry.
CORE_SCHEMAS = {'work', 'log', 'dbos'}
UPPER_LAYERS = {'objective', 'objetivo', 'bet', 'aposta', 'escolha', 'intention', 'intencao', 'lesson', 'licao',
                'hypothesis', 'retro', 'retrospective', 'retrospectiva', 'planner', 'planejador', 'pattern', 'padrao',
                'premise', 'premissa', 'decision', 'decisao', 'leadership', 'lideranca'}
# D-305: the core runs any executor, so its SQL names no kind of executor; an adapter's template may.
EXECUTOR_KINDS = {'agent', 'agents', 'session', 'sessions', 'llm', 'prompt', 'prompts', 'model', 'models', 'provider',
                  'providers'}
# D-306: no context field, no chosen measure and no management concept in the infrastructure's SQL.
BOUNDARY_WORDS = {'goal', 'goals', 'meta', 'program', 'programs', 'programa', 'project', 'projects', 'projeto',
                  'priority', 'prioridade', 'requester', 'solicitante', 'hierarchy', 'label', 'labels', 'annotation',
                  'annotations', 'context', 'template', 'templates', 'step', 'steps', 'metric', 'metrics', 'dashboard',
                  'alert', 'alerts', 'report', 'reports', 'billing', 'cost', 'costs', 'budget', 'budgets'}
SQL_SCHEMA = re.compile(r'(?i)\bcreate\s+schema\s+(?:if\s+not\s+exists\s+)?"?(\w+)')
SQL_OBJECT = re.compile(r'(?i)\bcreate\s+(?:unlogged\s+)?(?:table|view|materialized\s+view|sequence|function)\s+'
                        r'(?:if\s+not\s+exists\s+)?"?(\w+)"?\.')
SQL_COMMENT = re.compile(r'--[^\n]*|/\*.*?\*/', re.S)
ACCOUNT_ID = re.compile(r'(?<![0-9])[0-9]{12}(?![0-9])')  # an AWS account id is twelve digits
REGION_CODE = re.compile(r'\b(?:us|eu|ap|sa|ca|me|af|il|mx)(?:-gov)?-[a-z]+-[0-9]\b')  # us-east-1, sa-east-1


def words(name):
    """The lowercase words of an identifier: camelCase, snake_case and kebab-case split alike."""
    return {word.lower() for word in re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+', name)}


def template_names(template):
    """Every name a template gives: the logical ids, and the values of the properties whose key ends in Name."""
    names = [key for section in ('Parameters', 'Resources', 'Outputs', 'Conditions') for key in template.get(section, {})]

    def walk(value, key=''):
        if isinstance(value, dict):
            for inner, item in value.items():
                walk(item, inner if inner != 'Fn::Sub' else key)
        elif isinstance(value, list):
            for item in value:
                walk(item, key)
        elif isinstance(value, str) and key.endswith('Name'):
            names.append(value)

    walk(template.get('Resources', {}))
    return names


def name_problems(template):
    return sorted({name for name in template_names(template) if words(name) & UPPER_LAYERS})


def sql_problems(text):
    """The schemas outside the core and the upper-layer words a SQL file under infra/ names, comments aside."""
    code = SQL_COMMENT.sub(' ', text)
    schemas = set(SQL_SCHEMA.findall(code)) | set(SQL_OBJECT.findall(code))
    found = [f'schema {schema}' for schema in sorted(schemas - CORE_SCHEMAS)]
    found += [f'word {word}' for word in sorted(words(code) & (UPPER_LAYERS | EXECUTOR_KINDS | BOUNDARY_WORDS))]
    return found


class LayerTests(unittest.TestCase):
    """D-304: the infrastructure is the technical core of phase 1, agnostic to the program, the method and the account.
    Management and leadership run on top of it as programs, so nothing under infra/ may name them."""

    def templates(self):
        return [INFRA / 'bootstrap.json'] + sorted((INFRA / 'stacks').glob('*.json'))

    def test_the_record_cites_daniel_and_names_this_proof(self):
        record = LAYERS.read_text(encoding='utf-8')
        self.assertIn('proof: scripts/tests/test_infra_aws.py', record)
        for said in ('Daniel 04/11 11:37 and 11:39 BRT', 'manda bala', 'agnóstica ao programa rodado nela'):
            self.assertIn(said, record)
        register = (ROOT / 'docs/domain/DECISIONS.md').read_text(encoding='utf-8')
        self.assertRegex(register, r'(?m)^\| D-304 \|')
        self.assertIn('D-304', load(ROOT / 'units/engine-infra-aws/unit.json')['decisions'])

    def test_the_executor_record_cites_daniel_and_amends_the_schema_list(self):
        record = EXECUTORS.read_text(encoding='utf-8')
        self.assertIn('proof: scripts/tests/test_infra_aws.py', record)
        for said in ('Daniel 04/11 12:05 and 12:08 BRT', 'separar o máximo possível a minha infraestrutura',
                     'Amends D-304: the core schema agents becomes execution'):
            self.assertIn(said, record)
        register = (ROOT / 'docs/domain/DECISIONS.md').read_text(encoding='utf-8')
        self.assertRegex(register, r'(?m)^\| D-305 \|')
        self.assertIn('D-305', load(ROOT / 'units/engine-infra-aws/unit.json')['decisions'])
        self.assertNotIn('agents', CORE_SCHEMAS)

    def test_the_boundary_record_cites_daniel_and_sets_work_and_log(self):
        record = BOUNDARY.read_text(encoding='utf-8')
        self.assertIn('proof: scripts/tests/test_infra_aws.py', record)
        for said in ('Daniel 04/11 12:19 BRT', 'Consolida sim', 'Aqui eu tô olhando trabalho', 'Amends D-304 and D-305'):
            self.assertIn(said, record)
        register = (ROOT / 'docs/domain/DECISIONS.md').read_text(encoding='utf-8')
        self.assertRegex(register, r'(?m)^\| D-306 \|')
        self.assertIn('D-306', load(ROOT / 'units/engine-infra-aws/unit.json')['decisions'])
        self.assertEqual(CORE_SCHEMAS, {'work', 'log', 'dbos'})

    def test_no_template_names_management_or_leadership(self):
        for path in self.templates():
            self.assertEqual(name_problems(load(path)), [], path.name)

    def test_the_name_check_sees_a_management_name(self):
        template = {'Resources': {'BetQueue': {'Type': 'AWS::SQS::Queue',
                                               'Properties': {'QueueName': 'tower-work-items'}}},
                    'Outputs': {'LessonTopicArn': {}}}
        self.assertEqual(name_problems(template), ['BetQueue', 'LessonTopicArn'])

    def test_sql_under_infra_creates_only_core_schemas(self):
        for path in sorted((ROOT / 'infra').rglob('*.sql')):
            self.assertEqual(sql_problems(path.read_text(encoding='utf-8')), [], path.name)

    def test_the_sql_check_sees_a_management_table_and_ignores_comments(self):
        self.assertEqual(sql_problems('create table work.item (id uuid); -- a aposta mora nas annotations'), [])
        self.assertEqual(sql_problems('create schema direction;\ncreate table direction.objective (bet_id uuid);'),
                         ['schema direction', 'word bet', 'word objective'])

    def test_the_sql_check_sees_an_executor_kind_in_the_core(self):
        # A script runs without an AI session: the core keeps runs, not sessions, and meters, not tokens columns.
        self.assertEqual(sql_problems('create table work.run (id uuid, external_id text);'), [])
        self.assertEqual(sql_problems('create table agents.session (provider text, model text);'),
                         ['schema agents', 'word agents', 'word model', 'word provider', 'word session'])

    def test_the_sql_check_sees_a_context_field_or_a_chosen_measure(self):
        # D-306: the infrastructure keeps nothing of management, not even a free context field.
        self.assertEqual(sql_problems('create table work.job (id uuid, input_uri text, input_digest text);'), [])
        self.assertEqual(sql_problems('create table work.job (id uuid, priority int, labels jsonb, cost_usd numeric);'),
                         ['word cost', 'word labels', 'word priority'])
        self.assertEqual(sql_problems('create table execution.run (id uuid);'), ['schema execution'])

    def test_no_template_fixes_an_account(self):
        # An installation passes its account through the stack (AWS::AccountId), never as a literal of the core.
        for path in self.templates():
            self.assertIsNone(ACCOUNT_ID.search(path.read_text(encoding='utf-8')), path.name)

    def test_no_template_fixes_a_region(self):
        # The same for the region (AWS::Region): the stack runs in whatever region an installation deploys it to.
        for path in self.templates():
            self.assertIsNone(REGION_CODE.search(path.read_text(encoding='utf-8')), path.name)
        self.assertIsNotNone(REGION_CODE.search('arn:aws-partition:ssm:sa-east-1:'))


class SpotStandbyGoneTests(unittest.TestCase):
    """SPOT-STANDBY-GONE (D-316): the live service ran Spot standbys of an authoring head's bundle (IMAGE-PREWARM-B2, the
    prewarm); the prewarm left, and with it the standby's task definition (tower-service-standby), the task role's grant to
    run, stop, tag and pass roles to tasks, and the standbys' network in the service's environment. The cluster's name
    stays: the prune reads it (TOWER_STANDBY_CLUSTER)."""
    def setUp(self):
        self.template = load(INFRA / 'stacks/30-service.json')
        self.resources = self.template['Resources']
        self.statements = [each for policy in self.resources['TaskRole']['Properties']['Policies']
                           for each in policy['PolicyDocument']['Statement']]

    def test_no_standby_task_definition_and_no_prewarm_policy(self):
        definitions = {name: item['Properties']['Family'] for name, item in self.resources.items()
                       if item['Type'] == 'AWS::ECS::TaskDefinition'}
        self.assertEqual(definitions, {'TaskDefinition': 'tower-service'})
        self.assertNotIn('prewarm', [policy['PolicyName'] for policy in self.resources['TaskRole']['Properties']['Policies']])

    def test_the_task_role_runs_stops_tags_and_passes_nothing(self):
        granted = {action for item in self.statements if item['Effect'] == 'Allow' for action in as_list(item['Action'])}
        self.assertEqual(granted & {'ecs:RunTask', 'ecs:StopTask', 'ecs:DescribeTasks', 'ecs:TagResource', 'iam:PassRole'}, set())
        self.assertFalse([action for action in granted if action in ('ecs:*', 'iam:*', '*')])

    def test_the_service_knows_the_cluster_and_no_standby_network(self):
        service = next(each for each in self.resources['TaskDefinition']['Properties']['ContainerDefinitions']
                       if each['Name'] == 'service')
        given = {item['Name']: item['Value'] for item in service['Environment']}
        self.assertEqual(given['TOWER_STANDBY_CLUSTER'], {'Ref': 'Cluster'})  # the prune's (prune.start)
        self.assertEqual([name for name in given if name.startswith('TOWER_STANDBY_') and name != 'TOWER_STANDBY_CLUSTER'], [])


class CloudFormationLimitTests(unittest.TestCase):
    """The hard limits CloudFormation enforces at CreateChangeSet, checked offline: the deploy of #398/#399 failed on a
    1316-byte Description (cap 1024). `deploy` without an S3 bucket sends the body, so 51200 bytes applies to the stacks;
    the Torre applies the bootstrap from S3 (--template-url, BOOTSTRAP-URL), so 1 MB applies to it."""

    def setUp(self):
        self.paths = sorted((INFRA / 'stacks').glob('*.json')) + [INFRA / 'bootstrap.json']

    def test_description_resource_parameter_output_counts_and_body_size(self):
        report = []
        for path in self.paths:
            raw = path.read_bytes()
            template = json.loads(raw)
            self.assertLessEqual(len(template.get('Description', '').encode('utf-8')), 1024, path.name)
            self.assertLessEqual(len(template['Resources']), 500, path.name)
            self.assertLessEqual(len(template.get('Parameters', {})), 200, path.name)
            self.assertLessEqual(len(template.get('Outputs', {})), 200, path.name)
            limit = URL_LIMIT if path.name == 'bootstrap.json' else BODY_LIMIT
            self.assertLessEqual(len(raw), limit, f'{path.name} is {len(raw)} bytes')
            report.append(f'{path.name}: {len(raw)} bytes, headroom {limit - len(raw)}')
        print('\n' + '\n'.join(report))

    def test_no_parameter_shares_its_name_with_a_resource(self):
        # The deploy of #213 failed at CreateChangeSet: "all resources and parameters must have unique names.
        # Common name(s):[Zone]" (70-dns had a Zone parameter and a Zone hosted zone).
        for path in self.paths:
            template = json.loads(path.read_bytes())
            shared = set(template.get('Parameters', {})) & set(template['Resources'])
            self.assertEqual(shared, set(), f'{path.name}: parameter and resource named {sorted(shared)}')

    def test_logical_ids_are_alphanumeric_and_export_names_unique(self):
        exports = []
        for path in self.paths:
            template = json.loads(path.read_text(encoding='utf-8'))
            for section in ('Resources', 'Parameters', 'Outputs'):
                for name in template.get(section, {}):
                    self.assertRegex(name, r'^[A-Za-z0-9]+$', f'{path.name} {section} {name}')
            for name, output in template.get('Outputs', {}).items():
                if 'Export' in output:
                    exports.append(json.dumps(output['Export']['Name'], sort_keys=True))
        self.assertEqual(len(exports), len(set(exports)), 'duplicate export names')

    def test_route_keys_are_unique_per_api(self):
        for path in self.paths:
            seen = set()
            for name, resource in json.loads(path.read_text(encoding='utf-8'))['Resources'].items():
                if resource['Type'] != 'AWS::ApiGatewayV2::Route':
                    continue
                key = (json.dumps(resource['Properties']['ApiId'], sort_keys=True), resource['Properties']['RouteKey'])
                self.assertNotIn(key, seen, f'{path.name} {name} repeats {key[1]}')
                seen.add(key)


class PortFunctionNamesTests(unittest.TestCase):
    """PORT-ZIP-RENAME: DEP8 changed the port Lambdas from Image to Zip, which replaces them; CloudFormation cannot replace a
    custom-named resource, so the zip functions carry NEW fixed names (still inside the boundary's tower-port* scope).
    GATE-SHUTDOWN: the ingress and the consumer left the port stack; the service's task role still names them (30-service.json
    is not changed here), which grants nothing on a function that does not exist."""
    OLD = ('tower-port', 'tower-port-ingress', 'tower-port-webhooks')
    NEW = {'PortFunction': 'tower-port-api'}
    GONE = ('tower-port-ack-ingress', 'tower-port-webhook-consumer')

    def test_the_zip_functions_have_new_names_and_everything_follows_them(self):
        port = load(INFRA / 'stacks' / '40-port.json')['Resources']
        service = load(INFRA / 'stacks' / '30-service.json')['Resources']
        for logical, name in self.NEW.items():
            self.assertNotIn('PackageType', port[logical]['Properties'])  # Zip is the default
            self.assertEqual(port[logical]['Properties']['FunctionName'], name)
            self.assertNotIn(name, self.OLD)
            self.assertTrue(fnmatchcase(name, 'tower-port*'))
            self.assertEqual(port[logical]['Properties']['Runtime'][:6], 'python')
        # the api and the permission follow the alias (Ref/GetAtt), never a name
        text = json.dumps(port)
        for old in self.OLD + self.GONE:
            self.assertNotIn(f'"FunctionName": "{old}"', text)
            self.assertNotIn(f'function:{old}', text)
        self.assertEqual([r['Properties']['FunctionName'] for r in port.values() if r['Type'] == 'AWS::Lambda::Function'],
                         list(self.NEW.values()))
        self.assertEqual(port['InvokeFromTheApi']['Properties']['FunctionName'], {'Ref': 'PortAlias'})
        # the task role's fast path names exactly these functions, with and without the alias qualifier
        listed = json.dumps(service)
        for name in self.NEW.values():
            self.assertIn(f':function:{name}"', listed)
            self.assertIn(f':function:{name}:*"', listed)
        for old in self.OLD:
            self.assertNotIn(f':function:{old}"', listed)


PSEUDO = {'AWS::AccountId', 'AWS::Region', 'AWS::Partition', 'AWS::NoValue', 'AWS::StackName', 'AWS::URLSuffix'}


def resolve(template, values):
    """The template CloudFormation would create for these parameter values, offline: the conditions evaluated, the resources
    and outputs of a false condition dropped, every Fn::If taken and AWS::NoValue removed from objects and lists."""
    params = {name: values.get(name, spec.get('Default')) for name, spec in template.get('Parameters', {}).items()}
    conditions = {}

    def cond(node):
        if isinstance(node, dict) and len(node) == 1:
            (key, arg), = node.items()
            if key == 'Condition':
                if arg not in conditions:
                    conditions[arg] = cond(template['Conditions'][arg])
                return conditions[arg]
            if key == 'Fn::Equals':
                return value(arg[0]) == value(arg[1])
            if key == 'Fn::Not':
                return not cond(arg[0])
            if key == 'Fn::And':
                return all(cond(item) for item in arg)
            if key == 'Fn::Or':
                return any(cond(item) for item in arg)
        raise AssertionError(f'not a condition: {node}')

    def value(node):
        if isinstance(node, dict) and set(node) == {'Ref'} and node['Ref'] in params:
            return params[node['Ref']]
        return node

    def walk(node):
        if isinstance(node, dict):
            if set(node) == {'Fn::If'}:
                name, yes, no = node['Fn::If']
                return walk(yes if cond({'Condition': name}) else no)
            if node == {'Ref': 'AWS::NoValue'}:
                return None
            out = {key: walk(item) for key, item in node.items()}
            return {key: item for key, item in out.items() if item is not None}
        if isinstance(node, list):
            return [item for item in (walk(item) for item in node) if item is not None]
        return node

    keep = lambda section: {name: walk(item) for name, item in template.get(section, {}).items()
                            if 'Condition' not in item or cond({'Condition': item['Condition']})}
    return {'Resources': keep('Resources'), 'Outputs': keep('Outputs'), 'Parameters': params}


def references(node):
    """Every name a node points at: Ref, Fn::GetAtt and the ${X} or ${X.Attr} of Fn::Sub."""
    found = set()
    if isinstance(node, dict):
        for key, item in node.items():
            if key == 'Ref':
                found.add(item)
            elif key == 'Fn::GetAtt':
                found.add(item[0] if isinstance(item, list) else item.split('.')[0])
            elif key == 'Fn::Sub':
                text = item if isinstance(item, str) else item[0]
                found |= {name.split('.')[0] for name in re.findall(r'\$\{([^}!]+)\}', text)}
                if isinstance(item, list):
                    found |= references(item[1])
            else:
                found |= references(item)
            if key == 'DependsOn':
                found |= set(as_list(item))
    elif isinstance(node, list):
        for item in node:
            found |= references(item)
    return found


class MediaStackTests(unittest.TestCase):
    """MEDIA-S3 (D-323 step 2): the site's media bucket and its distribution. A merge to main deploys every stack, so the
    stack must create cleanly with no certificate and no DNS, and before the Torre re-applies the bootstrap with
    cloudfront:* in the boundary: Cdn off is the buckets alone, Cdn on without a certificate is the distribution on its
    default domain, and the alias only comes with a certificate ARN the Torre already issued and validated."""
    PATH = INFRA / 'stacks/60-media.json'

    def setUp(self):
        self.template = load(self.PATH)
        self.parameters = load(INFRA / 'parameters.json')['media']

    def created(self, **values):
        resolved = resolve(self.template, values)
        names = set(resolved['Resources']) | set(resolved['Parameters']) | PSEUDO
        for section in ('Resources', 'Outputs'):
            for name, item in resolved[section].items():
                dangling = references(item) - names
                self.assertEqual(dangling, set(), f'{section} {name} points at what this deploy does not create')
        return resolved

    def test_it_is_in_the_order_after_its_replica_and_imports_nothing(self):
        # MEDIA-REPLICA: the replica is another region's stack, named by its pattern (no ImportValue crosses regions)
        self.assertEqual(load(INFRA / 'order.json')['media'], ['media-replica'])
        self.assertNotIn('Fn::ImportValue', json.dumps(self.template))

    def test_the_first_deploy_is_the_buckets_alone_and_waits_on_nothing(self):
        # the template's Defaults are what CloudFormation creates with, for any parameter deploy.sh does not pass
        self.assertEqual({name: spec['Default'] for name, spec in self.template['Parameters'].items()},
                         {'Cdn': 'off', 'CertificateArn': '', 'Alias': '', 'ReplicaRegion': ''})
        first = self.created()
        self.assertEqual(sorted(first['Resources']), ['Media', 'MediaLogs', 'MediaLogsPolicy', 'MediaPolicy'])
        self.assertEqual(sorted(first['Outputs']), ['BucketName', 'LogsBucketName'])
        statements = first['Resources']['MediaPolicy']['Properties']['PolicyDocument']['Statement']
        self.assertEqual([item['Sid'] for item in statements], ['OnlyOverTls'])

    def test_parameters_json_turns_on_only_what_the_account_can_take(self):
        # deploy.sh passes infra/aws/parameters.json's media object. Cdn on needs the bootstrap with cloudfront:* applied
        # (the Torre, after this lands); a certificate needs Cdn on, an alias, and CloudFront's region, us-east-1.
        self.assertIn(self.parameters.get('Cdn', 'off'), ('off', 'on'))
        self.created(**self.parameters)
        arn = self.parameters.get('CertificateArn', '')
        if arn:
            self.assertEqual(self.parameters.get('Cdn'), 'on')
            self.assertTrue(self.parameters.get('Alias'))
            self.assertRegex(arn, r'^arn:aws:acm:us-east-1:\d{12}:certificate/[0-9a-f-]{36}$')
        if self.parameters.get('Cdn', 'off') == 'off':
            self.assertNotIn('Distribution', self.created(**self.parameters)['Resources'])

    def test_an_empty_certificate_gives_the_default_domain_and_no_alias(self):
        for values in ({'Cdn': 'on'}, {'Cdn': 'on', 'Alias': 'media.example.org'}, {**self.parameters, 'Cdn': 'on', 'CertificateArn': ''},
                       {'Cdn': 'on', 'CertificateArn': self.arn()}):  # an ARN without an alias is no alias either
            config = self.created(**values)['Resources']['Distribution']['Properties']['DistributionConfig']
            self.assertNotIn('Aliases', config, values)
            self.assertEqual(config['ViewerCertificate'], {'CloudFrontDefaultCertificate': True}, values)
            self.assertNotIn('CertificateArn', json.dumps(config))

    def test_a_certificate_and_an_alias_give_the_alias_over_sni(self):
        config = self.created(Cdn='on', Alias='media.openuniversity.si', CertificateArn=self.arn())[
            'Resources']['Distribution']['Properties']['DistributionConfig']
        self.assertEqual(config['Aliases'], [{'Ref': 'Alias'}])
        self.assertEqual(config['ViewerCertificate'], {'AcmCertificateArn': {'Ref': 'CertificateArn'},
                                                       'SslSupportMethod': 'sni-only', 'MinimumProtocolVersion': 'TLSv1.2_2021'})
        pattern = re.compile(self.template['Parameters']['CertificateArn']['AllowedPattern'])
        self.assertTrue(pattern.fullmatch('') and pattern.fullmatch(self.arn()))
        self.assertIsNone(pattern.fullmatch('arn:aws:iam::123456789012:server-certificate/media'))

    def test_no_stack_requests_a_certificate_and_only_the_dns_stack_touches_dns(self):
        # an ACM certificate waiting for DNS validation inside a stack would hang the deploy of every merge; the zone and
        # its records are the dns stack's alone (DnsStackTests), and nothing there validates a certificate
        for path in sorted((INFRA / 'stacks').glob('*.json')):
            kinds = {resource['Type'] for resource in load(path)['Resources'].values()}
            self.assertEqual({kind for kind in kinds if kind.startswith('AWS::CertificateManager::')}, set(), path.name)
            if path.name not in ('70-dns.json', '62-redirect.json'):  # REDIRECT-TOU: the zone of theopenuniversity.si
                self.assertEqual({kind for kind in kinds if kind.startswith('AWS::Route53')}, set(), path.name)
        boundary = load(INFRA / 'bootstrap.json')['Resources']['Boundary']['Properties']['PolicyDocument']['Statement']
        workload = next(item for item in boundary if item['Sid'] == 'WorkloadServicesInTheStackRegion')
        self.assertIn('cloudfront:*', workload['Action'])
        self.assertEqual(sorted(action for action in workload['Action'] if action.startswith('acm:')),
                         ['acm:DescribeCertificate', 'acm:ListCertificates'])
        self.assertFalse([action for action in workload['Action'] if action.startswith('route53')])  # DnsStackTests

    def test_the_bucket_is_private_versioned_encrypted_and_kept(self):
        resources = self.template['Resources']
        for name in ('Media', 'MediaLogs'):
            bucket = resources[name]
            self.assertEqual((bucket['DeletionPolicy'], bucket['UpdateReplacePolicy']), ('Retain', 'Retain'), name)
            props = bucket['Properties']
            self.assertEqual(set(props['PublicAccessBlockConfiguration'].values()), {True}, name)
            self.assertEqual(len(props['PublicAccessBlockConfiguration']), 4, name)
            self.assertEqual(props['OwnershipControls'], {'Rules': [{'ObjectOwnership': 'BucketOwnerEnforced'}]}, name)
            self.assertEqual(props['BucketEncryption']['ServerSideEncryptionConfiguration'][0]
                             ['ServerSideEncryptionByDefault']['SSEAlgorithm'], 'AES256', name)
        media = resources['Media']['Properties']
        self.assertEqual(media['VersioningConfiguration'], {'Status': 'Enabled'})
        [rule] = media['LifecycleConfiguration']['Rules']
        self.assertEqual(rule['NoncurrentVersionExpiration'], {'NoncurrentDays': 90})
        self.assertNotIn('ExpirationInDays', rule)  # a current object never expires: the bucket is the media's home
        self.assertEqual(media['LoggingConfiguration']['DestinationBucketName'], {'Ref': 'MediaLogs'})
        self.assertIn('MediaLogsPolicy', as_list(resources['Media']['DependsOn']))  # logging needs the grant first

    def test_with_a_replica_region_every_new_version_goes_to_the_replica_and_no_delete_does(self):
        # MEDIA-REPLICA (RISK-media-single-account): off, nothing of replication exists; on, one rule for the whole bucket
        self.assertNotIn('ReplicationConfiguration', self.created()['Resources']['Media']['Properties'])
        self.assertNotIn('ReplicationRole', self.created()['Resources'])
        on = self.created(ReplicaRegion='replica-region-1')
        config = on['Resources']['Media']['Properties']['ReplicationConfiguration']
        self.assertEqual(config['Role'], {'Fn::GetAtt': ['ReplicationRole', 'Arn']})
        [rule] = config['Rules']
        self.assertEqual((rule['Status'], rule['Filter'], rule['DeleteMarkerReplication']),
                         ('Enabled', {'Prefix': ''}, {'Status': 'Disabled'}))  # a deletion here leaves the copy whole
        target = 'arn:${AWS::Partition}:s3:::tower-media-replica-${AWS::AccountId}-${ReplicaRegion}'
        self.assertEqual(rule['Destination'], {'Bucket': {'Fn::Sub': target}, 'StorageClass': 'GLACIER_IR'})
        # the name is the replica stack's own pattern, in its region (regions.json), and the order puts that stack first
        replica = load(INFRA / 'stacks/58-media-replica.json')['Resources']['Replica']['Properties']['BucketName']
        self.assertEqual(replica, {'Fn::Sub': 'tower-media-replica-${AWS::AccountId}-${AWS::Region}'})
        self.assertEqual(on['Outputs']['ReplicaBucketName']['Value'],
                         {'Fn::Sub': 'tower-media-replica-${AWS::AccountId}-${ReplicaRegion}'})
        pattern = re.compile(self.template['Parameters']['ReplicaRegion']['AllowedPattern'])
        self.assertTrue(pattern.fullmatch('') and pattern.fullmatch(load(INFRA / 'regions.json')['media-replica']))
        self.assertIsNone(pattern.fullmatch('us-west-2; drop'))

    def test_the_replication_role_reads_the_media_and_writes_only_the_replica(self):
        role = self.created(ReplicaRegion='replica-region-1')['Resources']['ReplicationRole']['Properties']
        self.assertEqual(role['RoleName'], 'tower-app-media-replication')  # AppRolesCarryThisBoundary: tower-app-*
        self.assertEqual(role['PermissionsBoundary'],
                         {'Fn::Sub': 'arn:${AWS::Partition}:iam::${AWS::AccountId}:policy/tower-boundary'})
        [trust] = role['AssumeRolePolicyDocument']['Statement']
        self.assertEqual(sorted(trust['Principal']['Service']), ['batchoperations.s3.amazonaws.com', 's3.amazonaws.com'])
        self.assertEqual(trust['Condition'], {'StringEquals': {'aws:SourceAccount': {'Ref': 'AWS::AccountId'}}})
        [policy] = role['Policies']
        granted = {}
        for item in policy['PolicyDocument']['Statement']:
            self.assertEqual(item['Effect'], 'Allow')
            for action in as_list(item['Action']):
                granted.setdefault(action, set()).add(item['Resource']['Fn::Sub'])
        media = 'arn:${AWS::Partition}:s3:::tower-media-${AWS::AccountId}-${AWS::Region}'
        replica = 'arn:${AWS::Partition}:s3:::tower-media-replica-${AWS::AccountId}-${ReplicaRegion}/*'
        writes = {action for action, where in granted.items() if replica in where}
        self.assertEqual(writes, {'s3:ReplicateObject', 's3:ReplicateTags'})  # no ReplicateDelete: deletes stay here
        for action, where in granted.items():
            self.assertEqual(len(where), 1, action)
            if action not in writes:
                self.assertIn(next(iter(where)), (media, media + '/*'), action)
        self.assertIn('s3:InitiateReplication', granted)  # the one-off Batch Replication job of the older objects
        self.assertFalse([action for action in granted if action.endswith('*') or 'Delete' in action
                          or (action.startswith('s3:Put') and action != 's3:PutInventoryConfiguration')])

    def test_only_the_distribution_reads_the_bucket_and_only_over_tls(self):
        on = self.created(Cdn='on')['Resources']
        statements = on['MediaPolicy']['Properties']['PolicyDocument']['Statement']
        deny, allow = statements
        self.assertEqual((deny['Effect'], deny['Condition']), ('Deny', {'Bool': {'aws:SecureTransport': 'false'}}))
        self.assertEqual(allow['Principal'], {'Service': 'cloudfront.amazonaws.com'})
        self.assertEqual(allow['Action'], 's3:GetObject')
        self.assertIn('distribution/${Distribution}', allow['Condition']['StringEquals']['AWS:SourceArn']['Fn::Sub'])
        logs = on['MediaLogsPolicy']['Properties']['PolicyDocument']['Statement']
        self.assertEqual([item['Principal'] for item in logs if item['Effect'] == 'Allow'],
                         [{'Service': 'logging.s3.amazonaws.com'}])
        access = on['MediaAccess']['Properties']['OriginAccessControlConfig']
        self.assertEqual((access['SigningBehavior'], access['SigningProtocol'], access['OriginAccessControlOriginType']),
                         ('always', 'sigv4', 's3'))

    def test_the_distribution_is_https_only_cached_as_immutable_and_has_nothing_that_bills(self):
        on = self.created(Cdn='on')['Resources']
        config = on['Distribution']['Properties']['DistributionConfig']
        behavior = config['DefaultCacheBehavior']
        self.assertEqual(behavior['ViewerProtocolPolicy'], 'https-only')
        self.assertEqual(behavior['AllowedMethods'], ['GET', 'HEAD'])
        self.assertEqual(behavior['CachePolicyId'], {'Ref': 'Immutable'})
        [origin] = config['Origins']
        self.assertEqual(origin['OriginAccessControlId'], {'Fn::GetAtt': ['MediaAccess', 'Id']})
        self.assertEqual(origin['S3OriginConfig'], {'OriginAccessIdentity': ''})
        self.assertEqual(config['PriceClass'], 'PriceClass_100')
        # what costs beyond the free tier: logs, a web ACL, edge functions, an origin shield, a second origin
        for key in ('Logging', 'WebACLId', 'OriginGroups', 'CacheBehaviors', 'ContinuousDeploymentPolicyId'):
            self.assertNotIn(key, config)
        for key in ('LambdaFunctionAssociations', 'FunctionAssociations', 'RealtimeLogConfigArn'):
            self.assertNotIn(key, behavior)
        self.assertNotIn('OriginShield', origin)
        cache = on['Immutable']['Properties']['CachePolicyConfig']
        self.assertEqual((cache['DefaultTTL'], cache['MaxTTL']), (31536000, 31536000))
        keyed = cache['ParametersInCacheKeyAndForwardedToOrigin']
        self.assertEqual((keyed['CookiesConfig'], keyed['HeadersConfig'], keyed['QueryStringsConfig']),
                         ({'CookieBehavior': 'none'}, {'HeaderBehavior': 'none'}, {'QueryStringBehavior': 'none'}))

    def test_the_outputs_name_the_bucket_and_the_distribution(self):
        on = self.created(Cdn='on')['Outputs']
        self.assertEqual(on['BucketName']['Value'], {'Ref': 'Media'})
        self.assertEqual(on['DistributionId']['Value'], {'Ref': 'Distribution'})
        self.assertEqual(on['DistributionDomain']['Value'], {'Fn::GetAtt': ['Distribution', 'DomainName']})
        # the dns stack's media alias imports it (DnsStackTests): exported only with the distribution, never with Cdn off
        self.assertEqual(on['DistributionDomain']['Export'], {'Name': 'tower-media-distribution-domain'})
        self.assertEqual(self.template['Outputs']['DistributionDomain']['Condition'], 'CdnOn')
        self.assertEqual([name for name, output in self.template['Outputs'].items() if 'Export' in output],
                         ['DistributionDomain'])
        self.assertNotIn('DistributionDomain', self.created()['Outputs'])

    def test_the_cost_it_declares_is_the_real_numbers_and_far_under_the_budget(self):
        # The Torre's reading of R2 on 17/11 (docs/programs/padrao-dev/fornecimento-cloudflare.md): 3.388 GB in
        # open-university-media; 21,373 GetObject and 81,462 HeadObject in 30 days, 2.459 GB read. S3 Standard at
        # US$ 0.023/GB-month and US$ 0.0004 per 1,000 GET/HEAD; CloudFront's free tier is 1 TB and 10M requests a month.
        storage = 3.388 * 0.023
        reads = (21373 + 81462) / 1000 * 0.0004
        self.assertLess(2.459, 1024)
        self.assertLess(21373 + 81462, 10_000_000)
        declared = float(re.search(r'About US\$ ([\d.]+) a month', self.template['Description']).group(1))
        self.assertGreaterEqual(declared, round(storage + reads, 2))
        self.assertLess(declared, 0.01 * load(INFRA / 'budget.json')['limit']['amount'])
        for number in ('3.4 GB', '2.5 GB', '1 TB'):
            self.assertIn(number, self.template['Description'])

    @staticmethod
    def arn():
        return 'arn:aws:acm:us-east-1:123456789012:certificate/0123abcd-0123-4567-89ab-0123456789ab'


class MediaReplicaStackTests(unittest.TestCase):
    """MEDIA-REPLICA (RISK-media-single-account, Daniel 18/11 21:29 BRT): the second copy of the media, a stack of its own in a
    second region (infra/aws/regions.json), deployed before the media stack whose replication rule writes into it."""
    PATH = INFRA / 'stacks/58-media-replica.json'

    def setUp(self):
        self.template = load(self.PATH)

    def test_it_lives_in_another_region_and_comes_first(self):
        regions = load(INFRA / 'regions.json')
        self.assertEqual(set(regions), {'media-replica'})
        self.assertRegex(regions['media-replica'], r'^[a-z]{2}-[a-z]+-[0-9]$')
        self.assertNotEqual(regions['media-replica'], 'us-east-1')  # not the media's region: another failure domain
        self.assertEqual(load(INFRA / 'order.json')['media-replica'], [])
        self.assertEqual(load(INFRA / 'parameters.json')['media'].get('ReplicaRegion', regions['media-replica']),
                         regions['media-replica'])  # the media stack names the replica's region, or none yet
        self.assertNotIn('Parameters', self.template)
        self.assertNotIn('Fn::ImportValue', json.dumps(self.template))
        self.assertFalse([output for output in self.template['Outputs'].values() if 'Export' in output])  # nobody imports it

    def test_the_bucket_is_private_versioned_encrypted_kept_and_drops_old_versions_at_90_days(self):
        resources = self.template['Resources']
        self.assertEqual(sorted(resources), ['Replica', 'ReplicaPolicy'])
        bucket = resources['Replica']
        self.assertEqual((bucket['DeletionPolicy'], bucket['UpdateReplacePolicy']), ('Retain', 'Retain'))
        props = bucket['Properties']
        self.assertEqual(props['VersioningConfiguration'], {'Status': 'Enabled'})  # replication needs it on both sides
        self.assertEqual(set(props['PublicAccessBlockConfiguration'].values()), {True})
        self.assertEqual(len(props['PublicAccessBlockConfiguration']), 4)
        self.assertEqual(props['OwnershipControls'], {'Rules': [{'ObjectOwnership': 'BucketOwnerEnforced'}]})
        self.assertEqual(props['BucketEncryption']['ServerSideEncryptionConfiguration'][0]
                         ['ServerSideEncryptionByDefault']['SSEAlgorithm'], 'AES256')
        [rule] = props['LifecycleConfiguration']['Rules']
        self.assertEqual(rule['NoncurrentVersionExpiration'], {'NoncurrentDays': 90})
        self.assertNotIn('ExpirationInDays', rule)  # a current copy never expires
        self.assertNotIn('Transitions', rule)  # replicated straight into GLACIER_IR (the media stack's rule): no transition fee
        [deny] = resources['ReplicaPolicy']['Properties']['PolicyDocument']['Statement']
        self.assertEqual((deny['Effect'], deny['Principal'], deny['Condition']),
                         ('Deny', '*', {'Bool': {'aws:SecureTransport': 'false'}}))

    def test_the_cost_it_declares_is_the_cheapest_class_and_far_under_the_owners_dollar(self):
        # 3.388 GB in ~32k objects (the media bucket, 18/11). Per GB-month: Standard US$ 0.023, Standard-IA US$ 0.0125 and
        # Glacier Instant Retrieval US$ 0.004, the last two billing an object under 128 KB as 128 KB. Even with every
        # object billed 128 KB on top of its size (at most 3.388 GB + 32k x 128 KiB) Glacier IR is the cheapest; its
        # PUT is US$ 0.02 per 1k (once for the 32k), and a restore of all of it US$ 0.03 per GB.
        gb, objects = 3.388, 32_000
        worst = gb + objects * 128 / 1024 / 1024
        monthly = {'STANDARD': gb * 0.023, 'STANDARD_IA': worst * 0.0125, 'GLACIER_IR': worst * 0.004}
        self.assertEqual(min(monthly, key=monthly.get), 'GLACIER_IR')
        declared = float(re.search(r'About US\$ ([\d.]+) a month', self.template['Description']).group(1))
        self.assertGreaterEqual(declared, round(monthly['GLACIER_IR'], 2))
        self.assertLess(declared, 1.0)  # the owner's ceiling (18/11 21:29 BRT)
        once = objects / 1000 * 0.02 + gb * 0.02 + 0.25 + objects / 1e6 * 1.0
        self.assertLess(once, 1.1)
        self.assertIn('about US$ 1', self.template['Description'])
        media = load(INFRA / 'stacks/60-media.json')['Resources']['Media']['Properties']
        rule = media['ReplicationConfiguration']['Fn::If'][1]['Rules'][0]
        self.assertEqual(rule['Destination']['StorageClass'], 'GLACIER_IR')


class DnsStackTests(unittest.TestCase):
    """DNS-ROUTE53 (D-323 step 3): the zone of openuniversity.si, generated by scripts/dns-zone from the checked-in record
    list. A merge deploys every stack, so it must create cleanly before the Torre re-applies the bootstrap with route53 in
    the boundary (Zone off: a wait-condition handle, nothing that bills) and before the export arrives (Zone on with an
    empty list: the hosted zone alone, its name servers an output). media's alias imports the media stack's export and,
    since the e-mail cut (18/11), the DKIM CNAMEs import the mail stack's, so the dns stack comes after both in order.json."""
    PATH = INFRA / 'stacks/70-dns.json'

    def setUp(self):
        self.template = load(self.PATH)
        self.parameters = load(INFRA / 'parameters.json')['dns']
        self.records = load(INFRA / 'dns/openuniversity.si.json')

    def created(self, **values):
        resolved = resolve(self.template, values)
        names = set(resolved['Resources']) | set(resolved['Parameters']) | PSEUDO
        for section in ('Resources', 'Outputs'):
            for name, item in resolved[section].items():
                dangling = references(item) - names
                self.assertEqual(dangling, set(), f'{section} {name} points at what this deploy does not create')
        return resolved

    def test_it_comes_after_every_stack_whose_export_it_imports(self):
        # After the e-mail cut (D-323, 18/11) dns imports media's distribution domain and mail's three Easy DKIM tokens:
        # every stack that exports what dns imports is an edge of dns in order.json, and its file number is lower.
        imported = set()

        def walk(node):
            if isinstance(node, dict):
                for key, item in node.items():
                    if key == 'Fn::ImportValue':
                        self.assertIsInstance(item, str, 'an import names its export literally')
                        imported.add(item)
                    else:
                        walk(item)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(self.template['Resources'])
        exporters = {}
        for path in sorted((INFRA / 'stacks').glob('[0-9]*-*.json')):
            for output in load(path).get('Outputs', {}).values():
                name = output.get('Export', {}).get('Name')
                if isinstance(name, str):
                    exporters[name] = path
        self.assertTrue(imported)
        self.assertLessEqual(imported, set(exporters), 'dns imports an export no stack of the tree makes')
        sources = {exporters[name] for name in imported}
        edges = sorted(path.stem.split('-', 1)[1] for path in sources)
        self.assertEqual(sorted(load(INFRA / 'order.json')['dns']), edges)
        self.assertEqual(edges, ['mail', 'media'])
        number = lambda path: int(path.stem.split('-', 1)[0])
        self.assertTrue(all(number(path) < number(self.PATH) for path in sources))
        self.assertIn('tower-media-distribution-domain', imported)
        self.assertEqual(imported - {'tower-media-distribution-domain'},
                         {f'tower-mail-dkim-{kind}-{n}' for kind in ('name', 'value') for n in (1, 2, 3)})
        parameters = load(INFRA / 'parameters.json')
        self.assertEqual(parameters['media'].get('Cdn'), 'on',
                         'the dns stack imports the distribution domain, which the media stack exports only with Cdn on')
        self.assertNotEqual(parameters['mail'].get('Mail', 'off'), 'off',
                            'the dns stack imports the DKIM tokens, which the mail stack exports only with Mail on')

    def test_media_is_an_alias_a_and_aaaa_to_the_media_distribution(self):
        on = self.created(**self.parameters)['Resources']
        media = {item['Properties']['Type']: item for item in on.values()
                 if item['Properties'].get('Name') == 'media.openuniversity.si.'}
        self.assertEqual(sorted(media), ['A', 'AAAA'])
        for item in media.values():
            self.assertEqual(item['Condition'], 'ZoneOn')
            self.assertEqual(item['Properties']['AliasTarget'],
                             {'DNSName': {'Fn::ImportValue': 'tower-media-distribution-domain'},
                              'HostedZoneId': 'Z2FDTNDATAQYW2', 'EvaluateTargetHealth': False})
        # the distribution answers on IPv6 too, so the AAAA alias has addresses to give, and it carries the alias
        config = load(INFRA / 'stacks/60-media.json')['Resources']['Distribution']['Properties']['DistributionConfig']
        self.assertTrue(config['IPV6Enabled'])
        self.assertEqual(load(INFRA / 'parameters.json')['media']['Alias'], 'media.openuniversity.si')

    def test_the_first_deploy_waits_on_nothing_and_bills_nothing(self):
        self.assertEqual({name: spec['Default'] for name, spec in self.template['Parameters'].items()},
                         {'Zone': 'off', 'SiteDistribution': ''})
        for values in ({}, self.parameters):
            first = self.created(**values)
            if values.get('Zone', 'off') == 'off':
                self.assertEqual({name: item['Type'] for name, item in first['Resources'].items()},
                                 {'Pending': 'AWS::CloudFormation::WaitConditionHandle'})
                self.assertEqual(first['Outputs'], {})

    def test_parameters_json_turns_on_only_what_the_account_can_take(self):
        # Zone on needs the bootstrap with TheSiteZoneOnRoute53 applied (BootstrapTests pins the hash the Torre applied on
        # 18/11). The zone is created with every record (no name server points at it until the Torre switches them at the
        # registrar), never empty and never before the list is right. SiteDistribution is the apex CNAME of the export.
        self.assertIn(self.parameters.get('Zone'), ('off', 'on'))
        if self.parameters.get('Zone') == 'on':
            self.assertEqual(self.records['needs_target'], [], 'a record still needs its real target')
            self.assertTrue(self.records['records'])
        aliases = [item for item in self.records['records']
                   if item.get('route53', '').startswith('alias') and not item.get('alias_import')]
        if aliases:
            self.assertEqual(self.parameters.get('SiteDistribution'), aliases[0]['values'][0].rstrip('.'),
                             'the apex aliases the CloudFront domain of the export: set dns.SiteDistribution')
        else:
            self.assertNotIn('SiteDistribution', self.parameters)

    def test_zone_on_is_the_retained_zone_and_one_record_set_per_name_and_type(self):
        on = self.created(Zone='on', SiteDistribution='d111111abcdef8.cloudfront.net')
        zone = on['Resources']['HostedZone']
        self.assertEqual(zone['Type'], 'AWS::Route53::HostedZone')
        self.assertEqual((zone['DeletionPolicy'], zone['UpdateReplacePolicy']), ('Retain', 'Retain'))
        self.assertEqual(zone['Properties']['Name'], 'openuniversity.si.')
        self.assertNotIn('VPCs', zone['Properties'])
        self.assertNotIn('QueryLoggingConfig', zone['Properties'])
        sets = [item['Properties'] for name, item in on['Resources'].items() if name != 'HostedZone']
        # a Name or a value may be an intrinsic (the DKIM CNAMEs import their names, the MX writes the region by Fn::Sub):
        # compare them by their JSON text
        self.assertEqual(len(sets), len({(json.dumps(item['Name'], sort_keys=True), item['Type']) for item in sets}))
        mx = [item for item in sets if (item['Name'], item['Type']) == ('openuniversity.si.', 'MX')]
        if self.records.get('mail') == 'ses':
            [mx] = mx
            self.assertEqual(mx['ResourceRecords'], [{'Fn::Sub': '10 inbound-smtp.${AWS::Region}.amazonaws.com.'}])
            self.assertEqual(references(mx['ResourceRecords']) - PSEUDO, set())
        self.assertTrue(all(item['HostedZoneId'] == {'Ref': 'HostedZone'} for item in sets))
        self.assertEqual({kind['Type'] for kind in on['Resources'].values()},
                         {'AWS::Route53::HostedZone'} | ({'AWS::Route53::RecordSet'} if sets else set()))
        self.assertEqual(on['Outputs']['NameServers']['Value'],
                         {'Fn::Join': [',', {'Fn::GetAtt': ['HostedZone', 'NameServers']}]})
        self.assertEqual(len(sets), len(self.records['records'])
                         + sum(1 for item in self.records['records'] if item.get('route53', '').startswith('alias'))
                         + (3 if self.records.get('mail') == 'ses' else 0))  # MAIL-SES: the three DKIM CNAMEs it imports

    def test_the_boundary_allows_the_zone_and_its_records_and_nothing_that_bills_beyond_them(self):
        boundary = load(INFRA / 'bootstrap.json')['Resources']['Boundary']['Properties']['PolicyDocument']['Statement']
        [dns] = [item for item in boundary if any(action.startswith('route53') for action in as_list(item.get('Action', [])))]
        self.assertEqual((dns['Sid'], dns['Effect'], dns['Resource']), ('TheSiteZoneOnRoute53', 'Allow', '*'))
        self.assertTrue(all(action.startswith('route53:') and action != 'route53:*' for action in dns['Action']))
        allows = lambda action: any(fnmatchcase(action, pattern) for pattern in dns['Action'])
        # what the CloudFormation handlers of HostedZone and RecordSet call
        for needed in ('CreateHostedZone', 'GetHostedZone', 'DeleteHostedZone', 'UpdateHostedZoneComment', 'ListHostedZones',
                       'ListQueryLoggingConfigs', 'ChangeResourceRecordSets', 'ListResourceRecordSets', 'GetChange',
                       'ChangeTagsForResource', 'ListTagsForResource'):
            self.assertTrue(allows(f'route53:{needed}'), needed)
        # what bills or reaches beyond the zone's records
        for billed in ('CreateHealthCheck', 'UpdateHealthCheck', 'CreateKeySigningKey', 'EnableHostedZoneDNSSEC',
                       'CreateQueryLoggingConfig', 'CreateTrafficPolicy', 'CreateTrafficPolicyInstance', 'CreateCidrCollection',
                       'CreateReusableDelegationSet'):
            self.assertFalse(allows(f'route53:{billed}'), billed)

    def test_the_cost_it_declares_is_under_the_budget(self):
        # US$ 0.50 a hosted zone a month and US$ 0.40 per million standard queries (the first billion); alias queries to
        # CloudFront are free. The query volume is not measured, so the bound is 10 million queries a month.
        bound = 0.50 + 10 * 0.40
        declared = float(re.search(r'at most US\$ ([\d.]+) a month', self.template['Description']).group(1))
        self.assertGreaterEqual(declared, bound)
        self.assertLess(declared, 0.05 * load(INFRA / 'budget.json')['limit']['amount'])
        for number in ('US$ 0.50 a month', 'US$ 0.40 per million', '10 million queries'):
            self.assertIn(number, self.template['Description'])


REDIRECT_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const scope = {};
vm.createContext(scope);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), scope);
console.log(JSON.stringify(JSON.parse(process.argv[3]).map(event => scope.handler(event))));
"""


class RedirectStackTests(unittest.TestCase):
    """REDIRECT-TOU (D-323, the Cloudflare exit; Daniel 18/11 17:42 BRT): theopenuniversity.si keeps its 301 to
    openuniversity.si, now on AWS, in place of the Cloudflare Page Rule. A merge deploys every stack, so Redirect off (the
    default) creates nothing that bills; Redirect on is a CloudFront Function that answers every request, its distribution
    (default domain until the Torre's certificate) and the retained zone, whose alias records come with the certificate."""
    PATH = INFRA / 'stacks/62-redirect.json'
    ALIASES = ['theopenuniversity.si', 'www.theopenuniversity.si']

    def setUp(self):
        self.template = load(self.PATH)
        self.parameters = load(INFRA / 'parameters.json').get('redirect', {})

    def created(self, **values):
        resolved = resolve(self.template, values)
        names = set(resolved['Resources']) | set(resolved['Parameters']) | PSEUDO
        for section in ('Resources', 'Outputs'):
            for name, item in resolved[section].items():
                self.assertEqual(references(item) - names, set(), f'{section} {name} points at what this deploy does not create')
        return resolved

    def config(self, **values):
        return self.created(**values)['Resources']['Distribution']['Properties']['DistributionConfig']

    @staticmethod
    def arn():
        return 'arn:aws:acm:us-east-1:123456789012:certificate/0123abcd-0123-4567-89ab-0123456789ab'

    def test_it_is_in_the_order_needs_no_stack_and_exports_nothing(self):
        self.assertEqual(load(INFRA / 'order.json')['redirect'], [])
        text = json.dumps(self.template)
        self.assertNotIn('Fn::ImportValue', text)
        self.assertNotIn('Export', text)
        names = [re.sub(r'^\d+-', '', path.stem) for path in sorted((INFRA / 'stacks').glob('*.json'))]
        self.assertLess(names.index('media'), names.index('redirect'))
        self.assertLess(names.index('redirect'), names.index('mail'))

    def test_redirect_off_is_the_default_and_creates_nothing_that_bills(self):
        self.assertEqual({name: spec['Default'] for name, spec in self.template['Parameters'].items()},
                         {'Redirect': 'off', 'CertificateArn': ''})
        self.assertIn(self.parameters.get('Redirect', 'off'), ('off', 'on'))
        for values in ({}, {'CertificateArn': self.arn()}, self.parameters if self.parameters.get('Redirect', 'off') == 'off' else {}):
            off = self.created(**values)
            self.assertEqual({name: item['Type'] for name, item in off['Resources'].items()},
                             {'Pending': 'AWS::CloudFormation::WaitConditionHandle'}, values)
            self.assertEqual(off['Outputs'], {}, values)

    def test_parameters_json_turns_on_only_what_the_account_can_take(self):
        self.created(**self.parameters)
        arn = self.parameters.get('CertificateArn', '')
        if arn:  # CloudFront reads its certificate in us-east-1, and an ARN means Redirect is on
            self.assertEqual(self.parameters.get('Redirect'), 'on')
            self.assertRegex(arn, r'^arn:aws:acm:us-east-1:\d{12}:certificate/[0-9a-f-]{36}$')

    def test_redirect_on_without_a_certificate_is_the_default_domain_the_zone_and_no_record(self):
        on = self.created(Redirect='on')
        self.assertEqual({name: item['Type'] for name, item in on['Resources'].items()},
                         {'ToTheApex': 'AWS::CloudFront::Function', 'Distribution': 'AWS::CloudFront::Distribution',
                          'HostedZone': 'AWS::Route53::HostedZone'})
        config = on['Resources']['Distribution']['Properties']['DistributionConfig']
        self.assertNotIn('Aliases', config)
        self.assertEqual(config['ViewerCertificate'], {'CloudFrontDefaultCertificate': True})
        self.assertEqual(sorted(on['Outputs']), ['DistributionDomain', 'DistributionId', 'NameServers', 'ZoneId'])
        self.assertEqual(on['Outputs']['NameServers']['Value'], {'Fn::Join': [',', {'Fn::GetAtt': ['HostedZone', 'NameServers']}]})

    def test_a_certificate_gives_both_aliases_over_sni_and_their_alias_records(self):
        on = self.created(Redirect='on', CertificateArn=self.arn())['Resources']
        config = on['Distribution']['Properties']['DistributionConfig']
        self.assertEqual(config['Aliases'], self.ALIASES)
        self.assertEqual(config['ViewerCertificate'], {'AcmCertificateArn': {'Ref': 'CertificateArn'},
                                                       'SslSupportMethod': 'sni-only', 'MinimumProtocolVersion': 'TLSv1.2_2021'})
        records = [item['Properties'] for item in on.values() if item['Type'] == 'AWS::Route53::RecordSet']
        self.assertEqual(sorted((item['Name'], item['Type']) for item in records),
                         sorted((f'{name}.', kind) for name in self.ALIASES for kind in ('A', 'AAAA')))
        for item in records:
            self.assertEqual(item['HostedZoneId'], {'Ref': 'HostedZone'})
            self.assertEqual(item['AliasTarget'], {'DNSName': {'Fn::GetAtt': ['Distribution', 'DomainName']},
                                                   'HostedZoneId': 'Z2FDTNDATAQYW2', 'EvaluateTargetHealth': False})
        self.assertTrue(config['IPV6Enabled'])  # the AAAA aliases have addresses to give
        pattern = re.compile(self.template['Parameters']['CertificateArn']['AllowedPattern'])
        self.assertTrue(pattern.fullmatch('') and pattern.fullmatch(self.arn()))
        self.assertIsNone(pattern.fullmatch('arn:aws:iam::123456789012:server-certificate/redirect'))

    def test_the_zone_is_retained_public_and_has_no_mail(self):
        zone = self.template['Resources']['HostedZone']
        self.assertEqual((zone['DeletionPolicy'], zone['UpdateReplacePolicy']), ('Retain', 'Retain'))
        self.assertEqual(zone['Properties']['Name'], 'theopenuniversity.si.')
        self.assertNotIn('VPCs', zone['Properties'])
        self.assertNotIn('QueryLoggingConfig', zone['Properties'])
        # the Torre's export of the zone (18/11): the placeholder and the Page Rule alone, so no MX, TXT or anything but aliases
        kinds = {item['Properties']['Type'] for item in self.template['Resources'].values()
                 if item['Type'] == 'AWS::Route53::RecordSet'}
        self.assertEqual(kinds, {'A', 'AAAA'})

    def test_no_certificate_resource_and_unique_names(self):
        kinds = {item['Type'] for item in self.template['Resources'].values()}
        self.assertEqual({kind for kind in kinds if kind.startswith('AWS::CertificateManager::')}, set())
        self.assertEqual(set(self.template['Parameters']) & set(self.template['Resources']), set())
        self.assertEqual(set(self.template['Outputs']) & set(self.template['Resources']), set())
        for name in list(self.template['Resources']) + list(self.template['Parameters']) + list(self.template['Outputs']):
            self.assertRegex(name, r'^[A-Za-z0-9]+$')
        # the function's name is account-wide in CloudFront: no other stack names it
        name = self.template['Resources']['ToTheApex']['Properties']['Name']
        for path in sorted((INFRA / 'stacks').glob('*.json')):
            if path != self.PATH:
                self.assertNotIn(f'"{name}"', path.read_text(encoding='utf-8'), path.name)

    def test_the_function_answers_every_request_so_the_origin_is_never_reached(self):
        on = self.created(Redirect='on')['Resources']
        function = on['ToTheApex']['Properties']
        self.assertEqual((function['AutoPublish'], function['FunctionConfig']['Runtime']), (True, 'cloudfront-js-2.0'))
        self.assertLess(len(function['FunctionCode'].encode('utf-8')), 10240)  # CloudFront Functions' code limit
        config = on['Distribution']['Properties']['DistributionConfig']
        behavior = config['DefaultCacheBehavior']
        self.assertEqual(behavior['FunctionAssociations'],
                         [{'EventType': 'viewer-request', 'FunctionARN': {'Fn::GetAtt': ['ToTheApex', 'FunctionARN']}}])
        self.assertEqual(behavior['ViewerProtocolPolicy'], 'allow-all')  # http:// goes to https://openuniversity.si in one hop
        self.assertEqual(behavior['AllowedMethods'], ['GET', 'HEAD'])
        self.assertEqual(behavior['CachePolicyId'], '4135ea2d-6df8-44a3-9df3-4b5a84be39ad')  # managed CachingDisabled
        [origin] = config['Origins']
        self.assertEqual((origin['Id'], behavior['TargetOriginId'], origin['DomainName']),
                         ('never-reached', 'never-reached', 'openuniversity.si'))
        self.assertEqual(origin['CustomOriginConfig']['OriginProtocolPolicy'], 'https-only')
        self.assertEqual(config['PriceClass'], 'PriceClass_100')
        for key in ('Logging', 'WebACLId', 'OriginGroups', 'CacheBehaviors', 'ContinuousDeploymentPolicyId', 'CustomErrorResponses'):
            self.assertNotIn(key, config)
        for key in ('LambdaFunctionAssociations', 'RealtimeLogConfigArn', 'OriginRequestPolicyId'):
            self.assertNotIn(key, behavior)
        self.assertNotIn('OriginShield', origin)

    def test_the_boundary_allows_the_function_the_distribution_and_the_second_zone(self):
        boundary = load(INFRA / 'bootstrap.json')['Resources']['Boundary']['Properties']['PolicyDocument']['Statement']
        workload = next(item for item in boundary if item['Sid'] == 'WorkloadServicesInTheStackRegion')
        dns = next(item for item in boundary if item['Sid'] == 'TheSiteZoneOnRoute53')
        allows = lambda statement, action: any(fnmatchcase(action, pattern) for pattern in as_list(statement['Action']))
        for needed in ('CreateFunction', 'DescribeFunction', 'PublishFunction', 'UpdateFunction', 'DeleteFunction',
                       'CreateDistribution', 'UpdateDistribution', 'GetDistribution', 'TagResource'):
            self.assertTrue(allows(workload, f'cloudfront:{needed}'), needed)
        self.assertEqual(dns['Resource'], '*')  # not scoped to one zone: a second zone needs no change of the boundary
        for needed in ('CreateHostedZone', 'GetHostedZone', 'ChangeResourceRecordSets', 'ListResourceRecordSets', 'GetChange',
                       'ChangeTagsForResource'):
            self.assertTrue(allows(dns, f'route53:{needed}'), needed)
        self.assertNotIn('Condition', dns)

    def test_the_cost_it_declares_is_under_the_budget(self):
        # US$ 0.50 a hosted zone a month and US$ 0.40 per million queries (alias queries to CloudFront are free); CloudFront
        # Functions US$ 0.10 per million invocations; the 301s are inside CloudFront's free 10M requests and 1 TB. A
        # redirect of a retired name is low traffic: the bound is 1 million requests and 1 million queries a month.
        bound = 0.50 + 1 * 0.40 + 1 * 0.10
        declared = float(re.search(r'at most US\$ ([\d.]+) a month', self.template['Description']).group(1))
        self.assertGreaterEqual(declared, round(bound, 2))
        self.assertLess(declared, 0.01 * load(INFRA / 'budget.json')['limit']['amount'])
        for number in ('US$ 0.50 a month', 'US$ 0.40 per million', 'US$ 0.10 per million', '1 million requests'):
            self.assertIn(number, self.template['Description'])

    # --- the function's code, run under node against fake viewer-request events -----------------------------------------

    def run_function(self, *requests):
        import subprocess
        import tempfile
        code = self.template['Resources']['ToTheApex']['Properties']['FunctionCode']
        toolchain = ROOT / '.toolchain' / 'bin' / 'node'
        node = str(toolchain) if toolchain.exists() else (shutil.which('node') or 'node')
        events = [{'version': '1.0', 'context': {'eventType': 'viewer-request'}, 'viewer': {'ip': '192.0.2.1'},
                   'request': {'method': 'GET', 'headers': {'host': {'value': 'www.theopenuniversity.si'}}, 'cookies': {},
                               **request}} for request in requests]
        with tempfile.TemporaryDirectory() as directory:
            source, harness = Path(directory, 'index.js'), Path(directory, 'run.js')
            source.write_text(code, encoding='utf-8')
            harness.write_text(REDIRECT_HARNESS, encoding='utf-8')
            done = subprocess.run([node, str(harness), str(source), json.dumps(events)], capture_output=True, text=True,
                                  timeout=30, check=True)
        return json.loads(done.stdout)

    def test_the_function_answers_301_to_the_apex_keeping_the_path_and_the_query(self):
        cases = [
            ({'uri': '/', 'querystring': {}}, 'https://openuniversity.si/'),
            ({'uri': '/courses/intro', 'querystring': {}}, 'https://openuniversity.si/courses/intro'),
            ({'uri': '/a/b.html', 'querystring': {'q': {'value': 'a%20b'}, 'flag': {'value': ''},
                                                  'tag': {'value': 'x', 'multiValue': [{'value': 'x'}, {'value': 'y'}]}}},
             'https://openuniversity.si/a/b.html?q=a%20b&flag&tag=x&tag=y'),
        ]
        answers = self.run_function(*(request for request, _ in cases))
        for (request, location), answer in zip(cases, answers):
            self.assertEqual((answer['statusCode'], answer['statusDescription']), (301, 'Moved Permanently'), request)
            self.assertEqual(answer['headers']['location'], {'value': location}, request)
            self.assertEqual(answer['headers']['cache-control'], {'value': 'max-age=3600'})
            self.assertNotIn('body', answer)
        # a HEAD, an http:// viewer or another host gets the same answer: the function never hands the request on
        [head] = self.run_function({'method': 'HEAD', 'uri': '/x', 'querystring': {},
                                    'headers': {'host': {'value': 'theopenuniversity.si'}}})
        self.assertEqual((head['statusCode'], head['headers']['location']['value']), (301, 'https://openuniversity.si/x'))
        self.assertNotIn('return request', self.template['Resources']['ToTheApex']['Properties']['FunctionCode'])


ADDRESS = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b')  # an e-mail address literal
RESERVED = re.compile(r'@(?:[a-z0-9-]+\.)*(?:example\.(?:org|com|net)|invalid)$')  # RFC 2606 names, for fake addresses


class MailStackTests(unittest.TestCase):
    """MAIL-SES (D-323, the Cloudflare exit): the domain's mail on SES receiving, the substitute for Cloudflare Email Routing.
    A merge deploys every stack, so Mail off (the default, parameters.json) creates nothing that bills; Mail on with no map
    stores every message and sends nothing; only a map (an SSM parameter the Torre writes, never the tree) forwards."""
    PATH = INFRA / 'stacks/65-mail.json'

    def setUp(self):
        self.template = load(self.PATH)
        self.parameters = load(INFRA / 'parameters.json')['mail']

    def created(self, **values):
        resolved = resolve(self.template, values)
        names = set(resolved['Resources']) | set(resolved['Parameters']) | PSEUDO
        for section in ('Resources', 'Outputs'):
            for name, item in resolved[section].items():
                self.assertEqual(references(item) - names, set(), f'{section} {name} points at what this deploy does not create')
        return resolved

    def code(self):
        return self.template['Resources']['Forwarder']['Properties']['Code']['ZipFile']

    def test_it_is_in_the_order_needs_no_stack_and_comes_before_dns(self):
        order = load(INFRA / 'order.json')
        self.assertEqual(order['mail'], [])
        self.assertNotIn('Fn::ImportValue', json.dumps(self.template))
        names = [re.sub(r'^\d+-', '', path.stem) for path in sorted((INFRA / 'stacks').glob('*.json'))]
        self.assertLess(names.index('mail'), names.index('dns'))  # the cut gives dns the edge mail (scripts/dns-zone --mail ses)

    def test_mail_off_is_the_default_and_creates_nothing_that_bills(self):
        self.assertEqual({name: spec['Default'] for name, spec in self.template['Parameters'].items()},
                         {'Mail': 'off', 'MapParameter': '', 'Domain': 'openuniversity.si', 'SenderLocalPart': 'forward',
                          'SenderName': 'Open University', 'TestDomain': ''})
        # The Torre re-applied the bootstrap with ses:* (req-d323-ses, 18/11 21:11:50Z, the APPLIED hash above), so the live
        # parameters may turn Mail on; until the map's name is set it only stores (test_mail_on_with_an_empty_map...)
        self.assertIn(self.parameters.get('Mail', 'off'), ('off', 'on'))
        # the map's name may be set once the Torre has written it (18/11 21:4xZ); its content never comes to the tree
        self.assertIn(self.parameters.get('MapParameter', '/tower/mail/forward-map'), ('/tower/mail/forward-map',))
        self.assertNotIn('@', json.dumps(self.parameters))
        for values in ({}, {'MapParameter': '/tower/mail/forward-map'}):
            off = self.created(**values)
            self.assertEqual({name: item['Type'] for name, item in off['Resources'].items()},
                             {'Pending': 'AWS::CloudFormation::WaitConditionHandle'}, values)
            self.assertEqual(off['Outputs'], {}, values)

    def test_a_test_domain_is_a_second_recipient_of_both_rules_and_nothing_else(self):
        # 18/11: the Torre's host cannot reach inbound-smtp:25, so SES receiving is tested on a subdomain whose own MX
        # points at SES while the domain's MX stays on Cloudflare; empty, the rules accept the domain alone
        rules = [name for name, item in self.template['Resources'].items() if item['Type'] == 'AWS::SES::ReceiptRule']
        on = self.created(Mail='on', MapParameter='/tower/mail/forward-map', TestDomain='mailtest.openuniversity.si')
        off = self.created(Mail='on', MapParameter='/tower/mail/forward-map')
        for name in rules:
            if name in on['Resources']:
                self.assertEqual(on['Resources'][name]['Properties']['Rule']['Recipients'],
                                 [{'Ref': 'Domain'}, {'Ref': 'TestDomain'}])
            if name in off['Resources']:
                self.assertEqual(off['Resources'][name]['Properties']['Rule']['Recipients'], [{'Ref': 'Domain'}])
        self.assertRegex('mailtest.openuniversity.si', self.template['Parameters']['TestDomain']['AllowedPattern'])

    def test_mail_on_with_an_empty_map_stores_and_never_sends(self):
        on = self.created(Mail='on')
        self.assertEqual({name: item['Type'] for name, item in on['Resources'].items()},
                         {'Identity': 'AWS::SES::EmailIdentity', 'Inbox': 'AWS::S3::Bucket', 'InboxPolicy': 'AWS::S3::BucketPolicy',
                          'RuleSet': 'AWS::SES::ReceiptRuleSet', 'StoreRule': 'AWS::SES::ReceiptRule'})
        rule = on['Resources']['StoreRule']['Properties']['Rule']
        self.assertEqual(rule['Actions'], [{'S3Action': {'BucketName': {'Ref': 'Inbox'}, 'ObjectKeyPrefix': 'inbox/'}}])
        self.assertEqual((rule['Recipients'], rule['Enabled'], rule['ScanEnabled']), ([{'Ref': 'Domain'}], True, True))
        text = json.dumps(on['Resources'])
        for sends in ('ses:Send', 'LambdaAction', 'SNSAction', 'BounceAction', 'AWS::Lambda::'):
            self.assertNotIn(sends, text)
        self.assertEqual(on['Resources']['StoreRule']['DependsOn'], ['InboxPolicy'])  # SES checks it may write before the rule

    def test_a_map_adds_the_forwarder_after_the_store_and_its_permission_first(self):
        on = self.created(Mail='on', MapParameter='/tower/mail/forward-map')
        resources = on['Resources']
        self.assertNotIn('StoreRule', resources)
        self.assertEqual(sorted(name for name in resources if name.startswith('Forward')),
                         ['ForwardRule', 'Forwarder', 'ForwarderInvoke', 'ForwarderLogs', 'ForwarderRole'])
        rule = resources['ForwardRule']
        self.assertEqual(sorted(rule['DependsOn']), ['ForwarderInvoke', 'InboxPolicy'])
        actions = rule['Properties']['Rule']['Actions']
        self.assertEqual([next(iter(action)) for action in actions], ['S3Action', 'LambdaAction'])  # stored first, always
        self.assertEqual(actions[1]['LambdaAction']['InvocationType'], 'Event')
        invoke = resources['ForwarderInvoke']['Properties']
        self.assertEqual((invoke['Principal'], invoke['SourceAccount']), ('ses.amazonaws.com', {'Ref': 'AWS::AccountId'}))
        self.assertIn(':receipt-rule-set/tower-mail:receipt-rule/tower-mail-forward', invoke['SourceArn']['Fn::Sub'])
        self.assertNotEqual(resources['ForwardRule']['Properties']['Rule']['Name'],
                            self.template['Resources']['StoreRule']['Properties']['Rule']['Name'])  # replaced, not renamed
        env = resources['Forwarder']['Properties']['Environment']['Variables']
        self.assertEqual(env['MAP'], {'Ref': 'MapParameter'})
        self.assertEqual(env['SENDER'], {'Fn::Sub': '${SenderLocalPart}@${Domain}'})
        self.assertEqual(env['SENDER_NAME'], {'Ref': 'SenderName'})  # MAIL-SENDER-NAME: the Torre, 18/11

    def test_the_bucket_is_private_encrypted_written_only_by_this_rule_set_and_emptied_after_30_days(self):
        props = self.template['Resources']['Inbox']['Properties']
        self.assertEqual(props['PublicAccessBlockConfiguration'], {'BlockPublicAcls': True, 'BlockPublicPolicy': True,
                                                                   'IgnorePublicAcls': True, 'RestrictPublicBuckets': True})
        self.assertEqual(props['OwnershipControls'], {'Rules': [{'ObjectOwnership': 'BucketOwnerEnforced'}]})
        self.assertEqual(props['BucketEncryption']['ServerSideEncryptionConfiguration'][0]['ServerSideEncryptionByDefault'],
                         {'SSEAlgorithm': 'AES256'})
        [rule] = props['LifecycleConfiguration']['Rules']
        self.assertEqual((rule['Status'], rule['ExpirationInDays']), ('Enabled', 30))
        self.assertIn('30 days', self.template['Description'])
        [tls, ses] = self.template['Resources']['InboxPolicy']['Properties']['PolicyDocument']['Statement']
        self.assertEqual((tls['Effect'], tls['Condition']), ('Deny', {'Bool': {'aws:SecureTransport': 'false'}}))
        self.assertEqual((ses['Principal'], ses['Action']), ({'Service': 'ses.amazonaws.com'}, 's3:PutObject'))
        self.assertEqual(ses['Condition']['StringEquals'], {'AWS:SourceAccount': {'Ref': 'AWS::AccountId'}})
        self.assertIn(':receipt-rule-set/tower-mail:receipt-rule/*', ses['Condition']['ArnLike']['AWS:SourceArn']['Fn::Sub'])

    def test_the_forwarder_reads_only_the_map_and_its_message_and_sends_only_as_the_domain_sender(self):
        role = self.template['Resources']['ForwarderRole']['Properties']
        self.assertIn('policy/tower-boundary', json.dumps(role['PermissionsBoundary']))
        self.assertTrue(role['RoleName'].startswith('tower-app-'))
        statements = {item['Sid']: item for item in role['Policies'][0]['PolicyDocument']['Statement']}
        self.assertEqual(statements['ReadTheStoredMessage']['Action'], 's3:GetObject')
        self.assertTrue(statements['ReadTheMap']['Resource']['Fn::Sub'].endswith(':parameter${MapParameter}'))
        self.assertEqual(sorted(statements['SendAsTheDomain']['Action']), ['ses:SendEmail', 'ses:SendRawEmail'])
        self.assertEqual(statements['SendAsTheDomain']['Condition'],
                         {'StringEquals': {'ses:FromAddress': {'Fn::Sub': '${SenderLocalPart}@${Domain}'}}})
        self.assertEqual(statements['DecryptTheMapThroughSsm']['Condition'],
                         {'StringEquals': {'kms:ViaService': {'Fn::Sub': 'ssm.${AWS::Region}.amazonaws.com'}}})

    def test_the_active_rule_set_is_left_to_the_torre(self):
        # CloudFormation's ReceiptRuleSet has no "active" property: SetActiveReceiptRuleSet is the Torre's (the runbook),
        # and no custom resource here calls it
        self.assertEqual(self.template['Resources']['RuleSet']['Properties'], {'RuleSetName': 'tower-mail'})
        self.assertNotIn('Custom::', json.dumps(self.template))
        self.assertIn('made active by the Torre', self.template['Description'])

    def test_the_boundary_allows_ses_in_the_stack_region(self):
        boundary = load(INFRA / 'bootstrap.json')['Resources']['Boundary']['Properties']['PolicyDocument']['Statement']
        workload = next(item for item in boundary if item['Sid'] == 'WorkloadServicesInTheStackRegion')
        self.assertIn('ses:*', workload['Action'])
        for action in ('ses:CreateReceiptRule', 'ses:CreateEmailIdentity', 'ses:SendRawEmail'):
            self.assertEqual(decide(boundary, action, '*'), 'allow', action)
            self.assertEqual(decide(boundary, action, '*', {'aws:RequestedRegion': 'ELSEWHERE'}), 'implicit', action)
        for action in ('iam:CreatePolicy', 'iam:CreatePolicyVersion', 'iam:CreateLoginProfile', 'iam:UpdateLoginProfile'):
            self.assertEqual(decide(boundary, action, '*'), 'deny', action)  # the denies compacted to make room for ses:*
        self.assertLessEqual(len((INFRA / 'bootstrap.json').read_bytes()), URL_LIMIT)

    def test_the_cost_it_declares_is_under_the_budget(self):
        # bound: 10,000 messages a month, each one 256 KB chunk and forwarded once (about 1 GB). SES receiving US$ 0.10 per
        # 1,000 messages and US$ 0.09 per 1,000 chunks; sending US$ 0.10 per 1,000 and US$ 0.12 a GB; S3 at most 1 GB kept
        # (30 days) at US$ 0.023 and 10,000 PUTs at US$ 0.005 per 1,000; Lambda inside its free tier (1M requests)
        bound = 10 * 0.10 + 10 * 0.09 + 10 * 0.10 + 1 * 0.12 + 0.023 + 10 * 0.005
        declared = float(re.search(r'at most US\$ ([\d.]+) a month', self.template['Description']).group(1))
        self.assertGreaterEqual(declared, bound)
        self.assertLess(declared, 0.05 * load(INFRA / 'budget.json')['limit']['amount'])
        for number in ('US$ 1.00 plus US$ 0.90', '10,000 messages'):
            self.assertIn(number, self.template['Description'])

    def test_no_address_of_anyone_is_in_the_tree(self):
        # the map (recipient -> destination) is owner configuration in SSM, read by the Lambda; only names of parameters here
        paths = [path for path in INFRA.rglob('*') if path.is_file()]
        paths += [ROOT / 'scripts/lib/dns_zone.py', ROOT / 'docs/programs/padrao-dev/fornecimento-cloudflare.md']
        for path in paths:
            found = [item for item in ADDRESS.findall(path.read_text(encoding='utf-8')) if not RESERVED.search(item)]
            self.assertEqual(found, [], path.name)
        self.assertEqual(ADDRESS.findall('${SenderLocalPart}@${Domain}'), [])
        self.assertTrue(ADDRESS.findall('someone' + '@' + 'openuniversity.si'))

    # --- the forwarder's code, run offline against stubs of boto3 ----------------------------------------------------------

    def run_forwarder(self, table, recipients, raw, verdict='PASS', name=None):
        import sys
        import types
        calls = []

        class Client:
            def __init__(self, name):
                self.name = name

            def get_parameter(self, **kw):
                calls.append(('ssm', kw))
                return {'Parameter': {'Value': json.dumps(table)}}

            def get_object(self, **kw):
                calls.append(('s3', kw))
                return {'Body': types.SimpleNamespace(read=lambda: raw)}

            def send_email(self, **kw):
                calls.append(('sesv2', kw))

        stub = types.ModuleType('boto3')
        stub.client = Client
        saved = sys.modules.get('boto3')
        sys.modules['boto3'] = stub
        try:
            scope = {}
            exec(compile(self.code(), 'index.py', 'exec'), scope)
            event = {'Records': [{'ses': {'mail': {'messageId': 'm1'}, 'receipt': {
                'recipients': recipients, 'spamVerdict': {'status': verdict}, 'virusVerdict': {'status': 'PASS'}}}}]}
            env = {'MAP': '/tower/mail/forward-map', 'BUCKET': 'inbox', 'PREFIX': 'inbox/',
                   'SENDER': 'forward' + '@' + 'example.org',
                   'SENDER_NAME': name or self.template['Parameters']['SenderName']['Default']}
            saved_env = dict(os.environ)
            os.environ.update(env)
            try:
                with contextlib_redirect() as out:
                    scope['handler'](event, None)
            finally:
                os.environ.clear()
                os.environ.update(saved_env)
        finally:
            if saved is None:
                sys.modules.pop('boto3')
            else:
                sys.modules['boto3'] = saved
        return calls, out.getvalue()

    RAW = (b'Return-Path: <a@sender.example.net>\r\nDKIM-Signature: v=1; d=sender.example.net;\r\n b=abc\r\n'
           b'From: "Ana Q" <ana@sender.example.net>\r\nTo: info@example.org\r\nSubject: hi\r\n'
           b'Message-ID: <1@sender.example.net>\r\n\r\nbody\r\n')

    def test_the_code_fits_inline(self):
        self.assertLess(len(self.code().encode('utf-8')), 4096)  # CloudFormation's ZipFile limit
        compile(self.code(), 'index.py', 'exec')

    def test_an_empty_map_reads_no_message_and_sends_nothing(self):
        calls, out = self.run_forwarder({}, ['info' + '@' + 'example.org'], self.RAW)
        self.assertEqual([call[0] for call in calls], ['ssm'])
        self.assertIn('"forwarded": 0', out)
        self.assertNotIn('@', out)  # the log names no address

    def test_spam_is_kept_in_the_bucket_and_not_forwarded(self):
        calls, out = self.run_forwarder({'info': 'dest' + '@' + 'example.com'}, ['info' + '@' + 'example.org'], self.RAW, 'FAIL')
        self.assertEqual(calls, [])
        self.assertIn('spam or virus', out)

    def test_a_mapped_recipient_gets_the_message_from_the_domain_with_reply_to_the_sender(self):
        dest, other = 'dest' + '@' + 'example.com', 'other' + '@' + 'example.com'
        table = {'info': dest, 'team' + '@' + 'example.org': [dest, other]}
        calls, out = self.run_forwarder(table, ['INFO' + '@' + 'example.org', 'team' + '@' + 'example.org',
                                                'nobody' + '@' + 'example.org'], self.RAW)
        self.assertEqual([call[0] for call in calls], ['ssm', 's3', 'sesv2'])
        self.assertEqual(calls[1][1], {'Bucket': 'inbox', 'Key': 'inbox/m1'})
        sent = calls[2][1]
        self.assertEqual(sent['Destination'], {'ToAddresses': [dest, other]})
        # the end-to-end test of 18/11 received From forward@... without the name: with raw content SES writes the From
        # from FromEmailAddress, so it carries the display name too
        self.assertEqual(sent['FromEmailAddress'], 'Open University <forward' + '@' + 'example.org>')
        data = sent['Content']['Raw']['Data']
        head = data.split(b'\r\n\r\n')[0].split(b'\r\n')
        self.assertEqual(head[0], b'From: Open University <forward' + b'@example.org>')  # MAIL-SENDER-NAME
        self.assertEqual(head[1], b'Reply-To: "Ana Q" <ana' + b'@sender.example.net>')
        for gone in (b'Return-Path', b'DKIM-Signature', b' b=abc', b'Message-ID'):
            self.assertFalse(any(line.startswith(gone) for line in head), gone)
        self.assertIn(b'Subject: hi', head)
        self.assertTrue(data.endswith(b'\r\n\r\nbody\r\n'))
        self.assertIn('"forwarded": 2', out)

    def test_the_display_name_is_the_parameter_and_the_sender_s_name_is_not_in_the_from(self):
        # MAIL-SENDER-NAME (the Torre, 18/11): the forwarded From reads "Open University", never "<name> via <domain>"
        spec = self.template['Parameters']['SenderName']
        self.assertEqual(spec['Default'], 'Open University')
        pattern = re.compile(spec['AllowedPattern'])
        self.assertTrue(pattern.fullmatch('Open University') and pattern.fullmatch('The Tower'))
        for bad in ('', ' x', 'a\r\nBcc: x', 'a"b', 'a<b>'):
            self.assertIsNone(pattern.fullmatch(bad), bad)
        for name, want in (('Open University', b'From: Open University <forward' + b'@example.org>'),
                           ('O. U.', b'From: "O. U." <forward' + b'@example.org>')):
            calls, _ = self.run_forwarder({'info': 'dest' + '@' + 'example.com'}, ['info' + '@' + 'example.org'], self.RAW, name=name)
            head = calls[2][1]['Content']['Raw']['Data'].split(b'\r\n\r\n')[0].split(b'\r\n')
            self.assertEqual(head[0], want)
            self.assertNotIn(b'Ana Q', head[0])
            self.assertNotIn(b' via ', head[0])
        self.assertNotIn(' via ', self.code())

    def test_an_existing_reply_to_is_kept(self):
        raw = self.RAW.replace(b'Subject: hi', b'Reply-To: list' + b'@sender.example.net\r\nSubject: hi')
        calls, _ = self.run_forwarder({'info': 'dest' + '@' + 'example.com'}, ['info' + '@' + 'example.org'], raw)
        head = calls[2][1]['Content']['Raw']['Data'].split(b'\r\n\r\n')[0].split(b'\r\n')
        self.assertEqual([line for line in head if line.startswith(b'Reply-To')], [b'Reply-To: list' + b'@sender.example.net'])


TOKEN = 'token-of-the-test'  # a fake bearer; its sha256 is the fake SSM's token-sha256
PREFIX = '/tower/agent-env/the-tower/'
SECRETS = {'gh-token': 'GH_TOKEN', 'api-key': 'API_KEY'}


class FakeSsm:
    """SSM in process: a parameter store, one parameter a page, and the calls it answered."""

    def __init__(self, parameters):
        self.parameters, self.calls = parameters, []

    def get_parameter(self, Name):
        self.calls.append(('get_parameter', Name))
        return {'Parameter': {'Name': Name, 'Value': self.parameters[Name]}}

    def get_parameters_by_path(self, Path, WithDecryption, NextToken='0'):
        self.calls.append(('get_parameters_by_path', Path, WithDecryption))
        names = sorted(name for name in self.parameters if name.startswith(Path) and '/' not in name[len(Path):])
        start = int(NextToken)
        page = {'Parameters': [{'Name': name, 'Value': self.parameters[name]} for name in names[start:start + 1]]}
        if start + 1 < len(names):
            page['NextToken'] = str(start + 1)
        return page


class AgentEnvStackTests(unittest.TestCase):
    """AGENT-ENV (D-341): the stack that serves each environment's bundle, generated from config/agent-env/ and the deny
    list; one Lambda and one role per declaration, each reading its own SSM prefix alone, SSM SecureString only."""
    PATH = INFRA / 'stacks/45-agent-env.json'

    def setUp(self):
        self.template = load(self.PATH)
        self.resources = self.template['Resources']
        self.functions = {name: item for name, item in self.resources.items() if item['Type'] == 'AWS::Lambda::Function'}

    def of_type(self, kind):
        return [item['Properties'] for item in self.resources.values() if item['Type'] == kind]

    def test_the_committed_stack_is_its_generation(self):
        self.assertEqual(self.PATH.read_text(encoding='utf-8'), agent_env_stack.render(ROOT))

    def test_one_function_and_one_role_per_declaration(self):
        ids = sorted(path.stem for path in agent_env.declarations(ROOT))
        self.assertTrue(ids)
        want = sorted(agent_env_stack.NAME.format(id=ident) for ident in ids)
        self.assertEqual(sorted(item['Properties']['FunctionName'] for item in self.functions.values()), want)
        self.assertEqual(sorted(role['RoleName'] for role in self.of_type('AWS::IAM::Role')), want)
        self.assertEqual(sorted(item['Properties']['Environment']['Variables']['ENV_ID'] for item in self.functions.values()), ids)
        port = load(INFRA / 'stacks/40-port.json')['Resources']['PortFunction']['Properties']
        for function in self.functions.values():
            properties = function['Properties']
            self.assertNotIn('VpcConfig', properties)
            self.assertEqual(properties['Runtime'], port['Runtime'])
            self.assertLessEqual(properties['MemorySize'], port['MemorySize'])
            self.assertLess(len(properties['Code']['ZipFile'].encode('utf-8')), agent_env_stack.skeleton()['zipfile_limit'])
        kept = load(INFRA / 'stacks/40-port.json')['Resources']['Logs']['Properties']['RetentionInDays']
        for group in self.of_type('AWS::Logs::LogGroup'):
            self.assertEqual(group['RetentionInDays'], kept)  # 14 days, as the port's

    def test_each_role_reads_its_own_prefix_alone_under_the_boundary(self):
        boundary = load(INFRA / 'stacks/40-port.json')['Resources']['PortRole']['Properties']['PermissionsBoundary']
        for role in self.of_type('AWS::IAM::Role'):
            ident = role['RoleName'][len(agent_env_stack.NAME.format(id='')):]
            self.assertEqual(role['PermissionsBoundary'], boundary)
            [policy] = role['Policies']
            statements = policy['PolicyDocument']['Statement']
            parameters = 'arn:aws-partition:ssm:REGION:ACCOUNT:parameter/tower/'
            own = f'{parameters}agent-env/{ident}'
            for action in ('ssm:GetParameter', 'ssm:GetParametersByPath'):
                self.assertEqual(decide(statements, action, f'{own}/token-sha256'), 'allow')
                self.assertEqual(decide(statements, action, own), 'allow')
                for other in (f'{own}-x/token-sha256', f'{parameters}agent-env/other/a', f'{parameters}port/installation-token-sha256'):
                    self.assertEqual(decide(statements, action, other), 'implicit', other)
            key = 'arn:aws-partition:kms:REGION:ACCOUNT:key/k'
            self.assertEqual(decide(statements, 'kms:Decrypt', key, {'kms:ViaService': 'ssm.REGION.amazonaws.com'}), 'allow')
            self.assertEqual(decide(statements, 'kms:Decrypt', key, {'kms:ViaService': 's3.REGION.amazonaws.com'}), 'implicit')
            actions = {action for item in statements for action in as_list(item['Action'])}
            self.assertEqual(actions, {'logs:CreateLogStream', 'logs:PutLogEvents', 'ssm:GetParameter',
                                       'ssm:GetParametersByPath', 'kms:Decrypt'})
            [condition] = [item['Condition'] for item in statements if item['Action'] == 'kms:Decrypt']
            self.assertEqual(condition, {'StringEquals': {'kms:ViaService': {'Fn::Sub': 'ssm.${AWS::Region}.amazonaws.com'}}})

    def test_no_secrets_manager_and_no_literal_account_id(self):
        text = self.PATH.read_text(encoding='utf-8')
        self.assertNotIn('secretsmanager', text)
        self.assertIsNone(ACCOUNT_ID.search(text))
        self.assertIsNone(REGION_CODE.search(text))
        for secret in ({'name': 'A', 'store': 'secretsmanager', 'ref': 'tower/agent-env/x/a'},
                       {'name': 'A', 'store': 'ssm', 'ref': '/tower/agent-env/x/a/b'}):
            with self.assertRaises(agent_env_stack.StackError):
                agent_env_stack.secret_map({'id': 'x', 'secrets': [secret]})

    def test_the_deny_list_is_embedded_and_is_the_registry_s(self):
        for function in self.functions.values():
            embedded = json.loads(function['Properties']['Environment']['Variables']['DENIED'])
            self.assertTrue(embedded)
            self.assertEqual(embedded, agent_env.denied_patterns(ROOT))

    def test_the_route_is_on_the_port_s_api_and_the_port_exports_it(self):
        exports = [output['Export']['Name'] for output in load(INFRA / 'stacks/40-port.json')['Outputs'].values()]
        self.assertIn(agent_env_stack.API_EXPORT, exports)
        self.assertEqual(load(INFRA / 'order.json')['agent-env'], ['port'])
        routes = sorted(route['RouteKey'] for route in self.of_type('AWS::ApiGatewayV2::Route'))
        self.assertEqual(routes, sorted(agent_env_stack.ROUTE.format(id=path.stem) for path in agent_env.declarations(ROOT)))
        for route in self.of_type('AWS::ApiGatewayV2::Route') + self.of_type('AWS::ApiGatewayV2::Integration'):
            self.assertEqual(route['ApiId'], {'Fn::ImportValue': agent_env_stack.API_EXPORT})

    def handler_scope(self, ssm, clock):
        stub = types.ModuleType('boto3')
        stub.client = lambda name: ssm
        saved = sys.modules.get('boto3')
        sys.modules['boto3'] = stub
        try:
            scope = {}
            [function] = self.functions.values()
            exec(compile(function['Properties']['Code']['ZipFile'], 'index.py', 'exec'), scope)
        finally:
            if saved is None:
                del sys.modules['boto3']
            else:
                sys.modules['boto3'] = saved
        scope['CLOCK'] = clock
        return scope

    def call(self, scope, header, variables=None, secrets=None, denied=('AUTH_*',)):
        env = {'ENV_ID': 'the-tower', 'PREFIX': PREFIX, 'VARIABLES': json.dumps(variables or {}),
               'SECRETS': json.dumps(SECRETS if secrets is None else secrets), 'DENIED': json.dumps(list(denied))}
        saved = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        try:
            with contextlib_redirect() as out:
                answer = scope['handler']({'headers': {'authorization': header} if header else {}}, None)
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key)
                else:
                    os.environ[key] = value
        return answer, out.getvalue()

    def run_handler(self, header, **given):
        ssm = FakeSsm(self.store())
        answer, out = self.call(self.handler_scope(ssm, lambda: 0), header, **given)
        return answer, out, ssm

    @staticmethod
    def store(**extra):
        return {PREFIX + 'token-sha256': hashlib.sha256(TOKEN.encode()).hexdigest(), PREFIX + 'gh-token': 'value-one',
                PREFIX + 'api-key': 'value-two', **{PREFIX + key: value for key, value in extra.items()}}

    def test_a_wrong_or_missing_token_answers_401_and_reads_no_secret(self):
        for header in ('Bearer wrong', '', TOKEN, 'Basic ' + TOKEN, 'Bearer '):
            answer, out, ssm = self.run_handler(header)
            self.assertEqual(answer['statusCode'], HTTPStatus.UNAUTHORIZED, header)
            self.assertEqual(json.loads(answer['body']), {})
            self.assertEqual([call[0] for call in ssm.calls], ['get_parameter'])
            self.assertEqual(json.loads(out), {'env': 'the-tower', 'status': HTTPStatus.UNAUTHORIZED, 'names': []})

    def test_the_right_token_answers_the_declared_names_and_values_and_logs_no_value(self):
        answer, out, ssm = self.run_handler('Bearer ' + TOKEN, variables={'MODE': 'cloud'})
        self.assertEqual(answer['statusCode'], HTTPStatus.OK)
        self.assertEqual(json.loads(answer['body']), {'variables': {'MODE': 'cloud'},
                                                      'secrets': {'GH_TOKEN': 'value-one', 'API_KEY': 'value-two'}})
        self.assertIn(('get_parameters_by_path', PREFIX, True), ssm.calls)
        self.assertEqual(json.loads(out), {'env': 'the-tower', 'status': HTTPStatus.OK, 'names': ['API_KEY', 'GH_TOKEN', 'MODE']})
        for value in ('value-one', 'value-two', 'cloud', TOKEN, hashlib.sha256(TOKEN.encode()).hexdigest()):
            self.assertNotIn(value, out)

    def test_a_denied_or_undeclared_name_refuses_the_whole_bundle(self):
        cases = (({'secrets': {'gh-token': 'GH_TOKEN', 'api-key': 'AUTH_SECRET'}}, ['AUTH_SECRET']),
                 ({'variables': {'AUTH_URL': 'x'}}, ['AUTH_URL']),
                 ({'secrets': {'gh-token': 'GH_TOKEN'}}, ['api-key']))
        for given, bad in cases:
            answer, out, _ = self.run_handler('Bearer ' + TOKEN, **given)
            self.assertEqual(answer['statusCode'], HTTPStatus.INTERNAL_SERVER_ERROR, given)
            self.assertEqual(json.loads(answer['body']), {})
            self.assertEqual(json.loads(out), {'env': 'the-tower', 'status': HTTPStatus.INTERNAL_SERVER_ERROR, 'names': bad})
            self.assertNotIn('value-', out)

    def test_the_reads_are_cached_for_sixty_seconds_or_less(self):
        ssm, now = FakeSsm(self.store()), [0]
        scope = self.handler_scope(ssm, lambda: now[0])
        self.assertLessEqual(scope['TTL'], timedelta(minutes=1).total_seconds())
        self.assertEqual(self.call(scope, 'Bearer ' + TOKEN)[0]['statusCode'], HTTPStatus.OK)
        first = len(ssm.calls)
        for at, calls in ((scope['TTL'] - 1, first), (scope['TTL'] + 1, first + first)):
            now[0] = at
            self.assertEqual(self.call(scope, 'Bearer ' + TOKEN)[0]['statusCode'], HTTPStatus.OK)
            self.assertEqual(len(ssm.calls), calls, at)


def contextlib_redirect():
    import contextlib
    import io
    buffer = io.StringIO()

    class Redirect(contextlib.redirect_stdout):
        def __enter__(self):
            super().__enter__()
            return buffer
    return Redirect(buffer)


if __name__ == '__main__':
    unittest.main(verbosity=1)
