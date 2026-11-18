#!/usr/bin/env python3
"""DEPLOY-FILES (16/11/2026): what the deploy's own files say, read as files: the stack templates and the parameters
deploy.sh applies. test_deploy_sh.py runs deploy.sh on a fixture repository and never reads them, so a change of a
template or of the parameters selects this test (about a second), not its six slow parts (deploy-slow-a..f, 75-92 s each
on the runner: #210's queue gate took 158 s for a stack and its classification). No AWS call, no deploy run."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
AWS = ROOT / 'infra' / 'aws'


def load(name):
    return json.loads((AWS / name).read_text(encoding='utf-8'))


class DeployFiles(unittest.TestCase):
    def test_the_webhook_path_left_the_port_stack(self):
        """GATE-SHUTDOWN: the port stack has no webhook route, no queue, no ingress and no consumer, and the parameters
        pass it nothing (the deployer gives it PortCode and DepsKey only: test_deploy_sh)."""
        port = load('stacks/40-port.json')
        resources = port['Resources']
        self.assertEqual([r['Properties']['RouteKey'] for r in resources.values() if r['Type'] == 'AWS::ApiGatewayV2::Route'],
                         ['$default'])
        self.assertEqual([r['Properties']['FunctionName'] for r in resources.values() if r['Type'] == 'AWS::Lambda::Function'],
                         ['tower-port-api'])
        self.assertFalse([n for n, r in resources.items()
                          if r['Type'].startswith('AWS::SQS') or r['Type'] == 'AWS::Lambda::EventSourceMapping'])
        self.assertFalse([n for n in resources if n.startswith(('Webhook', 'Ingress', 'Ack'))])
        self.assertEqual(sorted(port['Outputs']), ['PortUrl'])
        self.assertEqual(port['Outputs']['PortUrl']['Export'], {'Name': 'tower-port-url'})
        self.assertFalse({'AckPath', 'IngressCode', 'WebhookCode', 'ForgeKeys', 'IngressMemory', 'IngressAckLimitS'}
                         & set(port['Parameters']))
        self.assertNotIn('AckBySqs', port.get('Conditions', {}))
        text = json.dumps(port)
        for name in re.findall(r'"(?:Ref|DependsOn)": "(\w+)"', text) + re.findall(r'"Fn::GetAtt": \["(\w+)"', text):
            self.assertIn(name, set(resources) | set(port['Parameters']), name)  # nothing names what left
        self.assertNotIn('port', load('parameters.json'))

    def test_the_runner_stack_is_applied_with_no_runner(self):
        """RUNNER-OFF (14/11): a stack keeps a parameter's previous value when it is not given; the parameters pass
        DesiredCount=0 on every apply and the template defaults to 0."""
        self.assertEqual(load('parameters.json')['runner'], {'DesiredCount': '0'})
        self.assertEqual(load('stacks/50-runner.json')['Parameters']['DesiredCount']['Default'], 0)

    def test_the_data_stack_is_the_class_the_file_names(self):
        self.assertEqual(load('parameters.json')['data'], {'InstanceClass': 'db.t4g.medium'})

    def test_the_service_task_definition_carries_the_datum_its_deploy_saw(self):
        """IMAGE-PREWARM-C: TOWER_CODE_SEEN = LiveSeen, empty by default (test_deploy_sh: not in the stacks' hash)."""
        template = load('stacks/30-service.json')
        self.assertEqual(template['Parameters']['LiveSeen']['Default'], '')
        found = next(c for c in template['Resources']['TaskDefinition']['Properties']['ContainerDefinitions']
                     if c['Name'] == 'service')
        self.assertIn({'Name': 'TOWER_CODE_SEEN', 'Value': {'Ref': 'LiveSeen'}}, found['Environment'])

    def test_the_templates_name_the_image_they_read_so_its_change_is_in_their_hash(self):
        for template in sorted((AWS / 'stacks').glob('*.json')):
            resources = json.loads(template.read_text()).get('Resources', {}).values()
            images = [c.get('Image') for r in resources if r.get('Type') == 'AWS::ECS::TaskDefinition'
                      for c in r['Properties']['ContainerDefinitions']]
            if images:
                self.assertIn('/tower/deploy/image/', template.read_text(), template.name)

    def test_the_real_templates_that_carry_an_ecs_service_are_the_service_alone(self):
        # what deploy.sh's grep finds: the stacks whose rollout is not waited; GATE-SHUTDOWN (D-314): the runner's ECS
        # service is gone, so its stack (the outputs bucket alone) is applied and waited like any other
        found = sorted(path.stem.split('-', 1)[1] for path in (AWS / 'stacks').glob('*.json')
                       if '"AWS::ECS::Service"' in path.read_text())
        self.assertEqual(found, ['service'])


if __name__ == '__main__':
    unittest.main()
