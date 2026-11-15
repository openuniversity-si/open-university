"""ENGINE-REPO (the migration to GitHub, 14/11/2026): the engine's repository on its forge comes from configuration:
TOWER_ENGINE_REPO, else the service's `service.engine_repo` datum (written through PUT /v1/config, seen live), else the public
default. Hermetic: fake settings, no database."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
from tower_infra import config_data, engine, observations  # noqa: E402

OTHER = 'some-owner/some-repo'


class Settings:
    def __init__(self, value):
        self.value = value

    def get(self, name):
        assert name == 'service.engine_repo'
        return self.value


class TheRepository(unittest.TestCase):
    def setUp(self):
        self.addCleanup(engine.use, Settings(None))
        engine.use(Settings(None))

    def test_the_default_is_the_public_repository_and_the_registrys(self):
        self.assertEqual(engine.repo({}), 'openuniversity-si/open-university')
        self.assertEqual(config_data.SPEC['service.engine_repo'][1], engine.DEFAULT)

    def test_the_environment_wins_then_the_settings_then_the_default(self):
        settings = Settings(OTHER)
        engine.use(settings)
        self.assertEqual(engine.repo({}), OTHER)
        self.assertEqual(engine.repo({engine.ENV: 'env-owner/env-repo'}), 'env-owner/env-repo')
        settings.value = 'changed/live'  # a write the service sees on tower_config: no restart
        self.assertEqual(engine.repo({}), 'changed/live')

    def test_a_value_that_is_not_owner_slash_name_is_ignored(self):
        engine.use(Settings('not a repo'))
        self.assertEqual(engine.repo({engine.ENV: ' '}), engine.DEFAULT)
        with self.assertRaises(ValueError):
            config_data.validate('service.engine_repo', 'not a repo')
        self.assertEqual(config_data.validate('service.engine_repo', OTHER), OTHER)

    def test_the_looks_follow_it_unless_one_is_given(self):
        engine.use(Settings(OTHER))
        self.assertEqual(observations.Observer(object()).repo, OTHER)  # GATE-LOOKS-GONE: the gate's own looks left

    def test_no_look_reads_a_hard_coded_repository_any_more(self):
        service = ROOT / 'infra' / 'service' / 'tower_infra'
        for path in sorted(service.glob('*.py')):
            if path.name in ('engine.py', 'config_data.py'):
                continue
            text = path.read_text(encoding='utf-8')
            self.assertFalse(re.findall(r"'openuniversity-si/open-university'", text), path.name)
            self.assertNotIn('repo=REPO', text, path.name)

    def test_the_service_hands_its_settings_over_without_rebinding_the_database_engine(self):
        """ENGINE-REPO: serve() hands its settings to the module, and `engine` in it stays the database's engine."""
        import ast
        main = ast.parse((ROOT / 'infra' / 'service' / 'tower_infra' / '__main__.py').read_text(encoding='utf-8'))
        serve = next(node for node in main.body if isinstance(node, ast.FunctionDef) and node.name == 'serve')
        calls = [node for node in ast.walk(serve) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr == 'use' and isinstance(node.func.value, ast.Name)]
        self.assertEqual([(call.func.value.id, [arg.id for arg in call.args]) for call in calls], [('engine_repo', ['settings'])])
        bound = [node.value.func.attr for node in ast.walk(serve) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == 'engine' for target in node.targets)]
        self.assertEqual(bound, ['iam_engine'])  # the database's engine, the only binding of the name

    def test_no_scope_binds_the_name_engine_to_the_module_and_to_something_else(self):
        """The first deploy from GitHub (14/11) failed on this: in a scope where `engine` is the database's engine (an
        argument or an assignment), an import of the engine module under the same name rebinds it for the whole scope."""
        import ast

        def module_imports(scope):
            return [node for node in ast.walk(scope) if isinstance(node, ast.ImportFrom) and node.level == 1
                    and not node.module and any(alias.name == 'engine' and alias.asname in (None, 'engine')
                                                for alias in node.names)]

        def other_bindings(scope):
            names = [arg.arg for arg in ast.walk(scope.args) if isinstance(arg, ast.arg)] if hasattr(scope, 'args') else []
            names += [target.id for node in ast.walk(scope) if isinstance(node, ast.Assign) for target in node.targets
                      if isinstance(target, ast.Name)]
            return 'engine' in names

        bad = []
        for path in sorted((ROOT / 'infra' / 'service' / 'tower_infra').glob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            scopes = [tree] + [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for scope in scopes:
                if module_imports(scope) and other_bindings(scope):
                    bad.append(f'{path.name}:{getattr(scope, "name", "<module>")}')
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
