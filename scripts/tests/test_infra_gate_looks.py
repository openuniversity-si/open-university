"""GATE-SHUTDOWN follow-up (14/11/2026, D-314): the gate is GitHub's (tower/gate, the merge queue) and PR #17 stopped the
AWS gate, so the infrastructure service no longer does the gate's work. serve() starts the gate's looks (GATE_LOOKS),
warms the forge's key and refreshes the forge's webhook keys only when service.gate_looks is true (default false); the
looks of the deploy, the drills and the prune (KEPT_LOOKS) start either way. Read from serve()'s own source (its
syntax tree), as the other wiring tests do: serve() needs a database, DBOS and AWS to run. Hermetic.
"""
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


def serve_node():
    return next(node for node in ast.parse(SOURCE).body if isinstance(node, ast.FunctionDef) and node.name == 'serve')


def guarded(test):
    """True when an if's test asks gate_looks (alone or in an and)."""
    return any(isinstance(node, ast.Name) and node.id == 'gate_looks' for node in ast.walk(test))


def walk(node, under=False):
    """(node, under an `if` that asks gate_looks) for every node of serve(), its body only (never the if's else)."""
    yield node, under
    if isinstance(node, ast.If):
        for child in node.body:
            yield from walk(child, under or guarded(node.test))
        for child in node.orelse:
            yield from walk(child, under)
        yield from walk(node.test, under)
        return
    for child in ast.iter_child_nodes(node):
        yield from walk(child, under)


def aliases(serve):
    """{local name: module} of the `from . import` statements of serve()."""
    return {each.asname or each.name: each.name for node in ast.walk(serve) if isinstance(node, ast.ImportFrom)
            and node.level == 1 and node.module is None for each in node.names}


def started(serve):
    """{module: under gate_looks} for every `<module>.start(...)` serve() calls."""
    names, found = aliases(serve), {}
    for node, under in walk(serve):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'start'
                and isinstance(node.func.value, ast.Name) and node.func.value.id in names):
            found.setdefault(names[node.func.value.id], set()).add(under)
    return found


class TheServicesLooks(unittest.TestCase):
    def test_the_gates_looks_start_only_under_service_gate_looks_and_the_kept_ones_always(self):
        found = started(serve_node())
        self.assertEqual(set(found), set(main.GATE_LOOKS) | set(main.KEPT_LOOKS))  # every look is classified
        self.assertFalse(set(main.GATE_LOOKS) & set(main.KEPT_LOOKS))
        for name in main.GATE_LOOKS:
            self.assertEqual(found[name], {True}, name)
        for name in main.KEPT_LOOKS:
            self.assertEqual(found[name], {False}, name)
        self.assertIn('autodeploy', main.KEPT_LOOKS)  # GET /v1/deploy/status: the deploy's look stays

    def test_the_forges_warm_up_and_its_webhook_keys_refresh_run_only_under_service_gate_looks(self):
        warmed, refreshed = [], []
        for node, under in walk(serve_node()):
            if isinstance(node, ast.Attribute) and node.attr == 'warm' and isinstance(node.value, ast.Name) \
                    and node.value.id == 'origin_forge':
                warmed.append(under)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'refresh_keys':
                refreshed.append(under)
        self.assertEqual(len(warmed), 3)  # the reloaded task's, the standby's beat and the live pass's
        self.assertEqual(len(refreshed), 2)  # the reloaded task's and the loop's interval
        self.assertTrue(all(warmed + refreshed))

    def test_the_flag_is_read_once_from_the_settings_before_any_look_starts(self):
        serve = serve_node()
        assigned = [node for node in ast.walk(serve) if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == 'gate_looks' for target in node.targets)]
        self.assertEqual(len(assigned), 1)
        self.assertIn("settings.get('service.gate_looks')", ast.unparse(assigned[0].value))
        first = min(node.lineno for node, under in walk(serve) if under and hasattr(node, 'lineno'))
        self.assertLess(assigned[0].lineno, first)
        refreshed = [node.lineno for node in ast.walk(serve) if isinstance(node, ast.Call)
                     and ast.unparse(node.func) == 'settings.refresh']
        self.assertLess(min(refreshed), assigned[0].lineno)  # the table read (or the spool handed) comes first

    def test_the_key_is_off_by_default_in_the_compiled_defaults_and_the_registry(self):
        self.assertEqual(config_data.SPEC['service.gate_looks'], (bool, False))
        item = json.loads((ROOT / 'config/registry/service/service.gate_looks.json').read_text(encoding='utf-8'))
        self.assertEqual((item['type'], item['default']), ('boolean', False))
        self.assertIn('infra/service/tower_infra/__main__.py', item['x-readers'])
        self.assertIs(config_data.Config(None).get('service.gate_looks'), False)  # no row: the default
        self.assertIs(config_data.validate('service.gate_looks', True), True)  # the Torre may turn them back on


class TheAwsGateIsGone(unittest.TestCase):
    """GATE-LOOKS-GONE (D-316, Daniel through the Torre, 15/11/2026): the AWS gate's own looks left the tree, their tests,
    their registry key and the port's routes that only they served; the Origin-era code stays, dormant on purpose."""

    GONE = ('prewarm', 'ondemand', 'merge_ready', 'pregate', 'fullrun')

    def test_the_five_looks_their_tests_and_their_key_are_gone(self):
        for name in self.GONE:
            self.assertFalse((SERVICE / 'tower_infra' / f'{name}.py').exists(), name)
            self.assertNotIn(name, main.GATE_LOOKS + main.KEPT_LOOKS)
            self.assertNotIn(f'{name}.start(', SOURCE)
        for name in ('prewarm', 'ondemand', 'pregate', 'fullrun'):
            self.assertFalse((ROOT / 'scripts' / 'tests' / f'test_infra_{name}.py').exists(), name)
        self.assertNotIn('deploy.prewarm_max_tasks', config_data.SPEC)
        self.assertFalse((ROOT / 'config/registry/deploy/deploy.prewarm_max_tasks.json').exists())
        from tower_infra import drills, http_port
        self.assertEqual(drills.KINDS, ('lambda-rollback',))  # the runner-placement drill provoked the on-demand look
        self.assertNotIn('/v1/deploy/measure', {pattern for _, pattern, _ in http_port.ROUTES})  # the prewarm's round

    def test_the_origin_era_code_stays_in_the_tree(self):
        for path in ('scripts/lib/forge_origin.py', 'scripts/deliver', 'scripts/train', 'scripts/service',
                     'services/runner', 'services/control-plane'):
            self.assertTrue((ROOT / path).exists(), path)


class TheServicesStack(unittest.TestCase):
    """The forge's webhook keys were published to /tower/port/forge-keys for the webhook ingress, which PR #17 deleted:
    no task of the service is told the parameter, and the task role may no longer write it."""

    def setUp(self):
        self.resources = json.loads(STACK.read_text(encoding='utf-8'))['Resources']

    def test_no_task_definition_names_the_forge_keys_parameter(self):
        definitions = {name: item for name, item in self.resources.items() if item['Type'] == 'AWS::ECS::TaskDefinition'}
        self.assertEqual(set(definitions), {'TaskDefinition', 'StandbyTaskDefinition'})
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
