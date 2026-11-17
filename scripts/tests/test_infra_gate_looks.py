"""GATE-SHUTDOWN follow-up (14/11/2026, D-314) and GATE-LOOKS-GONE (15/11/2026, D-316): the gate is GitHub's (tower/gate,
the merge queue), so the infrastructure service does none of the gate's work. serve() starts the looks of the deploy, the
drills and the prune (KEPT_LOOKS) and nothing else: the AWS gate's own looks left the tree, and the Origin forge's
(checks, observations, branches), its key's warm-up and its webhook keys' refresh stay in the tree, dormant on purpose,
with no start and no flag (the service's flag of the gate's looks left with them). Read from serve()'s own source (its syntax tree), as the
other wiring tests do: serve() needs a database, DBOS and AWS to run. Hermetic.
"""
# Verifies: REQ-origin-dormant
import ast
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE = ROOT / 'infra' / 'service'
sys.path.insert(0, str(SERVICE))
from tower_infra import __main__ as main, config_data  # noqa: E402

SOURCE = (SERVICE / 'tower_infra' / '__main__.py').read_text(encoding='utf-8')
STACK = ROOT / 'infra' / 'aws' / 'stacks' / '30-service.json'
ORIGIN_LOOKS = ('checks', 'observations', 'branches')


def serve_node():
    return next(node for node in ast.parse(SOURCE).body if isinstance(node, ast.FunctionDef) and node.name == 'serve')


def aliases(serve):
    """{local name: module} of the `from . import` statements of serve()."""
    return {each.asname or each.name: each.name for node in ast.walk(serve) if isinstance(node, ast.ImportFrom)
            and node.level == 1 and node.module is None for each in node.names}


def started(serve):
    """The modules whose `<module>.start(...)` serve() calls."""
    names = aliases(serve)
    return {names[node.func.value.id] for node in ast.walk(serve)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'start'
            and isinstance(node.func.value, ast.Name) and node.func.value.id in names}


class TheServicesLooks(unittest.TestCase):
    def test_serve_starts_the_kept_looks_and_no_look_of_the_origin_forge(self):
        self.assertEqual(started(serve_node()), set(main.KEPT_LOOKS))
        self.assertIn('autodeploy', main.KEPT_LOOKS)  # GET /v1/deploy/status: the deploy's look stays
        self.assertFalse(set(ORIGIN_LOOKS) & set(main.KEPT_LOOKS))
        self.assertFalse(hasattr(main, 'GATE_LOOKS'))
        for name in ORIGIN_LOOKS:  # dormant on purpose: in the tree, never started
            self.assertTrue((SERVICE / 'tower_infra' / f'{name}.py').exists(), name)

    def test_the_forges_warm_up_and_its_webhook_keys_refresh_are_never_run(self):
        serve = ast.unparse(serve_node())
        self.assertNotIn('origin_forge.warm', serve)
        self.assertNotIn('refresh_keys', SOURCE)
        self.assertNotIn('gate_looks', SOURCE)

    def test_the_flag_and_the_keys_interval_left_the_registry(self):
        # by their parts: no file spells a removed key's whole name (schema_compat: a reader names it whole)
        for name in ('.'.join(('service', 'gate_looks')), '.'.join(('service', 'forge_keys_every_s'))):
            self.assertNotIn(name, config_data.SPEC)
            self.assertFalse((ROOT / 'config' / 'registry' / 'service' / f'{name}.json').exists(), name)
            with self.assertRaises(ValueError):
                config_data.validate(name, True)


class TheAwsGateIsGone(unittest.TestCase):
    """GATE-LOOKS-GONE (D-316, Daniel through the Torre, 15/11/2026): the AWS gate's own looks left the tree, their tests,
    their registry key and the port's routes that only they served; the Origin-era code stays, dormant on purpose."""

    GONE = ('prewarm', 'ondemand', 'merge_ready', 'pregate', 'fullrun')

    def test_the_five_looks_their_tests_and_their_key_are_gone(self):
        for name in self.GONE:
            self.assertFalse((SERVICE / 'tower_infra' / f'{name}.py').exists(), name)
            self.assertNotIn(name, main.KEPT_LOOKS)
            self.assertNotIn(f'{name}.start(', SOURCE)
        for name in ('prewarm', 'ondemand', 'pregate', 'fullrun'):
            self.assertFalse((ROOT / 'scripts' / 'tests' / f'test_infra_{name}.py').exists(), name)
        # the prewarm's keys, by their prefix: no file spells a removed key's name (schema_compat: a reader names it whole)
        self.assertEqual([name for name in config_data.SPEC if name.startswith('deploy.prewarm_')], [])
        self.assertEqual(list((ROOT / 'config/registry/deploy').glob('deploy.prewarm_*.json')), [])
        from tower_infra import drills, http_port
        self.assertEqual(drills.KINDS, ('lambda-rollback',))  # the runner-placement drill provoked the on-demand look
        self.assertNotIn('/v1/deploy/measure', {pattern for _, pattern, _ in http_port.ROUTES})  # the prewarm's round

    def test_the_origin_era_code_stays_in_the_tree(self):
        for path in ('scripts/lib/forge_origin.py', 'scripts/deliver', 'scripts/train', 'scripts/service',
                     'services/runner'):
            self.assertTrue((ROOT / path).exists(), path)


class TheServicesStack(unittest.TestCase):
    """The forge's webhook keys were published to /tower/port/forge-keys for the webhook ingress, which PR #17 deleted:
    no task of the service is told the parameter, and the task role may no longer write it."""

    def setUp(self):
        self.resources = json.loads(STACK.read_text(encoding='utf-8'))['Resources']

    def test_no_task_definition_names_the_forge_keys_parameter(self):
        definitions = {name: item for name, item in self.resources.items() if item['Type'] == 'AWS::ECS::TaskDefinition'}
        self.assertEqual(set(definitions), {'TaskDefinition'})  # SPOT-STANDBY-GONE: no standby task definition
        for name, item in definitions.items():
            for container in item['Properties']['ContainerDefinitions']:
                given = {each['Name']: each['Value'] for each in container.get('Environment', [])}
                self.assertNotIn('TOWER_FORGE_KEYS_PARAMETER', given, f"{name}/{container['Name']}")
                # ORIGIN-ACCESS-GONE (15/11/2026): nor the forge's own key, nor the Origin app's signing key
                self.assertNotIn('TOWER_FORGE_KEY_PARAMETER', given, f"{name}/{container['Name']}")
                self.assertNotIn('TOWER_ORIGIN_APP_KEY_PARAMETER', given, f"{name}/{container['Name']}")

    def test_the_task_role_may_no_longer_write_the_forge_keys_parameter(self):
        statements = [each for policy in self.resources['TaskRole']['Properties']['Policies']
                      for each in policy['PolicyDocument']['Statement']]
        self.assertNotIn('PublishTheForgeKeysToTheWebhookIngress', [each.get('Sid') for each in statements])
        self.assertNotIn('forge-keys', STACK.read_text(encoding='utf-8'))
        writes = [each for each in statements if 'ssm:PutParameter' in json.dumps(each['Action'])]
        self.assertEqual([each['Sid'] for each in writes], ['WriteBackRenewedCliSessionCredentials'])  # the CLIs' alone


if __name__ == '__main__':
    unittest.main()
