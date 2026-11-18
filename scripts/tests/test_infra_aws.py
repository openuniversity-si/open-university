"""The factory's AWS infrastructure (engine-infra-aws, D-303). Hermetic: reads the declared budget and the CloudFormation
templates under infra/aws as JSON and checks Daniel's decision and the guardrails; no AWS call, no network.
"""
# Verifies: REQ-aws-200
from fnmatch import fnmatchcase
import hashlib
import json
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
INFRA = ROOT / 'infra' / 'aws'
RECORD = ROOT / 'docs/domain/decisions/D-303.md'
BUDGET_RECORD = ROOT / 'docs/domain/decisions/D-315.md'  # D-315 amends D-303's numbers (US$ 150, ceiling US$ 200)


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
    return value


def conditions_hold(condition, context):
    for operator, pairs in (condition or {}).items():
        for key, wanted in pairs.items():
            given, wanted = context.get(key), resolved(wanted)
            if operator in ('StringEquals', 'ArnEquals') and given != wanted:
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
    APPLIED = '76a21a0e2550ce0182bdaa552c5dd464d63e4053e589598135918c81d9b88501'

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
        for action in ('iam:CreateUser', 'iam:CreateAccessKey', 'iam:PutRolePermissionsBoundary',
                       'iam:DeleteRolePermissionsBoundary', 'budgets:*', 'ec2:RunInstances', 'ec2:CreateNatGateway'):
            self.assertIn(action, denied)
        workload = next(item for item in statements if item['Sid'] == 'WorkloadServicesInTheStackRegion')
        self.assertEqual(workload['Condition'], {'StringEquals': {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}})

    def test_the_boundary_lets_an_app_role_reach_the_database_by_iam_only_in_the_stack_region(self):
        # The service connects to tower-data as an IAM database user (P2 F2, P3 F1): rds-db:connect is its own service
        # prefix, outside rds:*, and an app role's permission to it is the intersection with this boundary.
        statements = self.resources['Boundary']['Properties']['PolicyDocument']['Statement']
        workload = next(item for item in statements if item['Sid'] == 'WorkloadServicesInTheStackRegion')
        self.assertIn('rds-db:connect', workload['Action'])
        self.assertEqual(workload['Condition'], {'StringEquals': {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}})

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
        self.assertEqual(actions, {'codebuild:StartBuild', 'lambda:InvokeFunction', 'logs:CreateLogStream', 'logs:PutLogEvents'})
        # QUEUE-RELOAD: and pass the merge queue's words to the port's alias, nothing else
        invoke = [item for item in self.policy('DoorbellRole') if 'lambda:InvokeFunction' in as_list(item['Action'])]
        self.assertEqual([item['Resource'] for item in invoke], [
            {'Fn::Sub': 'arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:tower-port-api:live'}])
        code = self.resources['DoorbellFunction']['Properties']['Code']['ZipFile']
        self.assertIn('timingSafeEqual', code)
        self.assertIn("createHash('sha256')", code)
        token = self.template['Parameters']['DoorbellTokenSha256']
        self.assertTrue(token['NoEcho'])
        self.assertEqual(token['AllowedPattern'], '^[0-9a-f]{64}$')

    def test_the_deploy_state_rule_may_invoke_only_the_port_alias(self):
        # DEP-EVENTS (the Torre, 09/11 17:19 BRT): CodeBuild Build State Change of tower-infra-deploy -> tower-port-api:live,
        # the invoke permission limited to that rule's ARN and this account
        rule = self.resources['DeployStateRule']['Properties']
        self.assertEqual(rule['EventPattern'], {'source': ['aws.codebuild'], 'detail-type': ['CodeBuild Build State Change'],
                                                'detail': {'project-name': ['tower-infra-deploy']}})
        target = {'Fn::Sub': 'arn:${AWS::Partition}:lambda:${AWS::Region}:${AWS::AccountId}:function:tower-port-api:live'}
        self.assertEqual([each['Arn'] for each in rule['Targets']], [target])
        permission = self.resources['DeployStateInvokePermission']['Properties']
        self.assertEqual((permission['FunctionName'], permission['Principal'], permission['SourceArn']),
                         (target, 'events.amazonaws.com', {'Fn::GetAtt': ['DeployStateRule', 'Arn']}))

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


DEPLOY_STUBS = '''
aws() {
  echo "aws $1 $2" >> "$CALLS_FILE"
  case "$1 $2" in
    "ecr describe-images") [ -n "$IMAGE_EXISTS" ] ;;
    "ecr get-login-password") echo token ;;
    "ssm get-parameter") echo "$LAST" ;;
    "cloudformation describe-stack-events") printf '%s\tService\tUPDATE_FAILED\tthe reason\n' "$(date -u +%Y-%m-%dT%H:%M:%S.000000+00:00)" ;;
    "cloudformation deploy") case " $* " in *" --stack-name $FAIL_STACK "*) return 1 ;; esac ;;
    "ssm put-parameter") echo "put $4" >> "$CALLS_FILE" ;;
  esac
}
docker() { echo "docker $1" >> "$CALLS_FILE"; }
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
            script = DEPLOY_STUBS + f'bash {INFRA / "deploy.sh"}\n'
            env = {**os.environ, 'IMAGE_REGISTRY': 'registry', 'CFN_EXEC_ROLE_ARN': 'role', 'DEPLOY_REPO': str(repo),
                   'LAST': sha if head == last else 'H1', 'FAIL_STACK': fail_stack or 'none',
                   'IMAGE_EXISTS': image_exists, 'CALLS_FILE': str(calls), 'DEPLOY_LAMBDA_PACKAGE_CMD': "echo '{}'"}
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
        self.assertNotIn('aws cloudformation', ' '.join(calls))


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
    1316-byte Description (cap 1024). `deploy` without an S3 bucket sends the body, so 51200 bytes applies."""

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
            self.assertLessEqual(len(raw), 51200, f'{path.name} is {len(raw)} bytes')
            report.append(f'{path.name}: {len(raw)} bytes, headroom {51200 - len(raw)}')
        print('\n' + '\n'.join(report))

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

    def test_it_is_in_the_order_and_needs_no_other_stack(self):
        self.assertEqual(load(INFRA / 'order.json')['media'], [])
        self.assertNotIn('Fn::ImportValue', json.dumps(self.template))

    def test_the_first_deploy_is_the_buckets_alone_and_waits_on_nothing(self):
        # the template's Defaults are what CloudFormation creates with, for any parameter deploy.sh does not pass
        self.assertEqual({name: spec['Default'] for name, spec in self.template['Parameters'].items()},
                         {'Cdn': 'off', 'CertificateArn': '', 'Alias': ''})
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
        for values in ({'Cdn': 'on'}, {'Cdn': 'on', 'Alias': 'media.example.org'}, {**self.parameters, 'Cdn': 'on'},
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

    def test_no_stack_requests_a_certificate_or_touches_dns(self):
        # an ACM certificate waiting for DNS validation inside a stack would hang the deploy of every merge
        for path in sorted((INFRA / 'stacks').glob('*.json')):
            kinds = {resource['Type'] for resource in load(path)['Resources'].values()}
            self.assertEqual({kind for kind in kinds if kind.startswith(('AWS::CertificateManager::', 'AWS::Route53'))},
                             set(), path.name)
        boundary = load(INFRA / 'bootstrap.json')['Resources']['Boundary']['Properties']['PolicyDocument']['Statement']
        workload = next(item for item in boundary if item['Sid'] == 'WorkloadServicesInTheStackRegion')
        self.assertIn('cloudfront:*', workload['Action'])
        self.assertEqual(sorted(action for action in workload['Action'] if action.startswith('acm:')),
                         ['acm:DescribeCertificate', 'acm:ListCertificates'])
        self.assertFalse([action for action in workload['Action'] if action.startswith('route53')])

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


if __name__ == '__main__':
    unittest.main(verbosity=1)
