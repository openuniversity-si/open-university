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


if __name__ == '__main__':
    unittest.main()
