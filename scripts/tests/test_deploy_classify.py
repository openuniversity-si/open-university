"""Deploy classifier (DEP6): the real directories of this repository map to the documented targets. Hermetic: no git, no network."""
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import deploy_classify as dc  # noqa: E402


def t(path):
    return dc.classify_path(path)


class ClassifyPath(unittest.TestCase):
    def test_every_stack_is_its_own_slow_target(self):
        for stack in (ROOT / 'infra' / 'aws' / 'stacks').glob('*.json'):
            name = stack.stem.split('-', 1)[1]
            self.assertEqual(t(f'infra/aws/stacks/{stack.name}'), [f'slow:stack-{name}'])

    def test_deployer_and_bootstrap(self):
        self.assertEqual(t('infra/aws/deploy.sh'), ['slow:deployer'])
        self.assertEqual(t('infra/aws/order.json'), ['slow:deployer'])
        self.assertEqual(t('infra/aws/bootstrap.json'), ['manual:bootstrap'])

    def test_service_image(self):
        for path in ('infra/service/Dockerfile', 'infra/service/requirements.txt', 'infra/db/migrations/0001_work_log.sql',
                     'services/runner/tower-runner.service.tmpl'):
            self.assertEqual(t(path), ['slow:service-image'], path)

    def test_the_staged_github_workflows_deploy_nothing(self):
        # STAGED-WORKFLOWS-NONE: the owner installs them as .github/workflows; no image, stack or Lambda carries them
        for path in ('services/runner/github/tower-gate.yml', 'services/runner/github/deploy-doorbell.yml',
                     'services/runner/github/full-suite.yml'):
            self.assertEqual(t(path), ['none'], path)
        self.assertEqual(dc.code_only(['infra/service/tower_infra/runner.py', 'services/runner/github/tower-gate.yml'])[0],
                         True)  # beside code, the code-only fast path still holds

    def test_lambda_modules(self):
        self.assertEqual(t('infra/service/tower_infra/ingress.py'), ['fast:lambda-ingress', 'slow:service-image'])
        self.assertEqual(t('infra/service/tower_infra/webhook_consumer.py'), ['fast:lambda-webhooks', 'slow:service-image'])
        # the consumer's package holds http_port too (it imports it): a change to it swaps both, or the port stack is applied for it
        self.assertEqual(t('infra/service/tower_infra/http_port.py'), ['fast:lambda-port', 'fast:lambda-webhooks', 'slow:service-image'])
        # LANDING-PREWARM-GONE: the port's landing no longer imports live_image: the service's alone, as code_bundle is
        self.assertEqual(t('infra/service/tower_infra/live_image.py'), ['slow:service-image'])
        self.assertEqual(t('infra/service/tower_infra/forge_webhooks.py'), ['fast:lambda-all', 'slow:service-image'])
        self.assertEqual(t('infra/service/tower_infra/autodeploy.py'), ['slow:service-image'])

    def test_the_lambda_table_is_the_import_closure_of_each_package(self):
        """SLOW-PATH-NO-ROLLOUT-WAIT: a module a Lambda's package holds and the table does not name is code the fast path
        never swaps: the slow path then applies the port stack (193 s) for a change of code alone."""
        import lambda_package
        names = {'tower-port-api': dc.PORT, 'tower-port-ack-ingress': dc.INGRESS, 'tower-port-webhook-consumer': dc.WEBHOOKS}
        held = {}
        for function, (_, init) in lambda_package.FUNCTIONS.items():
            modules = lambda_package.closure(ROOT, function) + (['__init__'] if init.parent == lambda_package.SOURCE else [])
            for module in modules:
                held.setdefault(module, set()).add(names[function])
        self.assertEqual({module: set(lambdas) for module, lambdas in dc.LAMBDA_MODULES.items()}, held)

    def test_worker(self):
        self.assertEqual(t('services/control-plane/src/core.js'), ['fast:worker'])
        self.assertEqual(t('services/control-plane/wrangler.toml'), ['fast:worker'])
        self.assertEqual(t('services/control-plane/test/core.test.mjs'), ['none'])

    def test_data_and_none(self):
        self.assertEqual(t('config/registry/deploy/deploy.auto.json'), ['data-only'])
        for path in ('docs/operations/aws.md', 'scripts/deliver', 'scripts/tests/x.py', 'units/a.md', 'README.md'):
            self.assertEqual(t(path), ['none'], path)

    def test_real_tower_infra_modules_all_classified(self):
        for module in (ROOT / 'infra' / 'service' / 'tower_infra').glob('*.py'):
            self.assertIn('slow:service-image', t(f'infra/service/tower_infra/{module.name}'))


class Classify(unittest.TestCase):
    def test_routes(self):
        self.assertEqual(dc.classify(['docs/a.md'])['route'], 'none')
        self.assertEqual(dc.classify(['config/registry/gate.json', 'docs/a.md'])['route'], 'data-only')
        self.assertEqual(dc.classify(['services/control-plane/src/core.js'])['route'], 'fast')
        self.assertEqual(dc.classify(['infra/aws/stacks/50-runner.json'])['route'], 'slow')
        self.assertEqual(dc.classify(['infra/service/tower_infra/ingress.py'])['route'], 'both')

    def test_a_hyphenated_stack_name_targets_its_own_stack(self):
        self.assertEqual(dc.classify_path('infra/aws/stacks/45-ack-canary.json'), ['slow:stack-ack-canary'])

    def test_deterministic_sorted_deduplicated(self):
        a = dc.classify(['infra/aws/stacks/40-port.json', 'docs/a.md', 'infra/aws/stacks/40-port.json'])
        b = dc.classify(['docs/a.md', 'infra/aws/stacks/40-port.json'])
        self.assertEqual(a, b)
        self.assertEqual([r['path'] for r in a['paths']], ['docs/a.md', 'infra/aws/stacks/40-port.json'])
        self.assertEqual(a['targets'], ['slow:stack-port'])
        self.assertEqual(dc.classify([])['targets'], ['none'])

    def test_cli_from_file_list(self):
        out = subprocess.run([str(ROOT / 'scripts' / 'deploy-classify'), '--files', '-'], input='docs/x.md\ninfra/aws/deploy.sh\n',
                             capture_output=True, text=True, check=True).stdout
        self.assertIn('"route": "slow"', out)
        self.assertIn('slow:deployer', out)


class CodeOnly(unittest.TestCase):
    """IMAGE-PREWARM-B2: the heads a code bundle can prewarm (the image already built runs the head's tower_infra); every
    other image change, and every stack, deployer or database change, stays on the slow path."""

    def test_only_tower_infra_files_make_a_code_only_head(self):
        for paths in (['infra/service/tower_infra/autodeploy.py'],
                      ['infra/service/tower_infra/runner.py', 'infra/service/tower_infra/port.py', 'docs/x.md',
                       'scripts/tests/test_x.py', 'config/registry/deploy/deploy.auto.json'],
                      ['infra/service/tower_infra/sub/data.json'],  # the bundle carries the whole package
                      ['infra/service/tower_infra/ingress.py', 'services/control-plane/src/core.js']):  # fast swaps too
            self.assertTrue(dc.code_only(paths)[0], paths)

    def test_the_port_stack_may_change_beside_the_code(self):
        # CODE-BESIDE-PORT: no ECS task runs on the port stack; the code still swaps and the build applies that stack alone
        ok, why = dc.code_only(['infra/service/tower_infra/port.py', 'infra/aws/stacks/40-port.json', 'docs/x.md'])
        self.assertEqual((ok, why), (True, '1 file(s) of infra/service/tower_infra/ only, beside slow:stack-port'))
        self.assertEqual(dc.code_only(['infra/aws/stacks/40-port.json']), (False, 'no service/runner image target'))
        # PORT-COLD-LAYER: the Lambdas' layer is the port stack's: its requirements file builds no image and replaces no
        # task (it was classified as the service image's, which the Dockerfile never copied it into)
        layer = 'infra/service/requirements-lambda.txt'
        self.assertEqual(dc.classify_path(layer), ['slow:stack-port'])
        self.assertEqual(dc.classify([layer])['route'], 'slow')
        self.assertEqual(dc.code_only([layer]), (False, 'no service/runner image target'))
        self.assertEqual(dc.code_only(['infra/service/tower_infra/port.py', layer])[0], True)
        self.assertEqual(dc.classify_path('infra/service/requirements.txt'), ['slow:service-image'])  # the image's own
        self.assertNotIn('requirements-lambda', (ROOT / 'infra/service/Dockerfile').read_text())
        self.assertEqual(dc.code_only(['infra/service/tower_infra/port.py', 'infra/aws/stacks/40-port.json',
                                       'infra/aws/stacks/30-service.json'])[0], False)

    def test_the_image_itself_a_migration_a_stack_or_the_deployer_is_the_slow_path(self):
        code = 'infra/service/tower_infra/runner.py'
        for extra in ('infra/service/Dockerfile', 'infra/service/requirements.txt',
                      'infra/db/migrations/0014_x.sql', 'infra/db/schema.sql', 'infra/ingress/__init__.py',
                      'services/runner/tower-runner.service.tmpl', 'infra/aws/stacks/30-service.json',
                      'infra/aws/stacks/10-network.json', 'infra/aws/stacks/20-data.json', 'infra/aws/deploy.sh',
                      'infra/aws/bootstrap.json'):
            ok, why = dc.code_only([code, extra])
            self.assertFalse(ok, extra)
            self.assertTrue(why, extra)
        self.assertEqual(dc.code_only(['infra/db/migrations/0014_x.sql'])[1],
                         'the image itself changes: infra/db/migrations/0014_x.sql')
        self.assertEqual(dc.code_only([code, 'infra/aws/stacks/20-data.json'])[1], 'also slow:stack-data')

    def test_the_owner_s_step_is_the_image_s_not_the_bundle_s(self):
        """OWNER-STEP-NEEDS-ROLLOUT: tower_infra/dbinit.py runs in the init container, from the image, with the owner's
        password, when a task starts: a code swap changes nothing of it. Live 12/11 a head that changed it would have
        swapped in a second and left the owner's step as it was until some unrelated rollout."""
        self.assertEqual(dc.code_only(['infra/service/tower_infra/dbinit.py']),
                         (False, 'the image itself changes: infra/service/tower_infra/dbinit.py'))
        self.assertFalse(dc.code_only(['infra/service/tower_infra/runner.py', 'infra/service/tower_infra/dbinit.py'])[0])

    def test_the_task_s_supervisor_is_the_image_s_not_the_bundle_s(self):
        """SUPERVISOR-NEEDS-ROLLOUT: tower_infra/supervisor.py is the container's first process and runs on the image's
        code for the task's whole life (its children are what a landing changes): a head that changes it is not
        code-only, or the new supervisor would wait for some unrelated rollout."""
        self.assertEqual(dc.code_only(['infra/service/tower_infra/supervisor.py']),
                         (False, 'the image itself changes: infra/service/tower_infra/supervisor.py'))
        self.assertFalse(dc.code_only(['infra/service/tower_infra/live_image.py', 'infra/service/tower_infra/supervisor.py'])[0])
        self.assertTrue(dc.code_only(['infra/service/tower_infra/live_image.py'])[0])
        # RESTORE-DRILL: and so is the reading of a restored database, the init container's command
        self.assertFalse(dc.code_only(['infra/service/tower_infra/restore_check.py'])[0])
        self.assertFalse(dc.code_only(['infra/service/tower_infra/pooler.py'])[0])  # TASK-POOLER: the supervisor starts it from the image
        self.assertEqual(dc.IMAGE_RUN, tuple(dc.CODE_ONLY + name for name in ('dbinit.py', 'supervisor.py', 'restore_check.py', 'pooler.py')))

    def test_a_head_without_an_image_target_has_nothing_to_prewarm(self):
        for paths in ([], ['docs/x.md'], ['services/control-plane/src/core.js'], ['config/registry/x/y.json']):
            self.assertEqual(dc.code_only(paths), (False, 'no service/runner image target'), paths)

    def test_the_rule_names_what_the_bundle_carries(self):
        import lambda_package
        self.assertEqual(dc.CODE_ONLY, f'{lambda_package.SOURCE.as_posix()}/')


if __name__ == '__main__':
    unittest.main()
