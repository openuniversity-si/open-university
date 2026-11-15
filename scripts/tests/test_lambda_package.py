"""The zip packages of the port's Lambdas (DEP8): deterministic, content-addressed, built by the gate's artifact check, read by
the 40-port stack through the alias live. Hermetic: a fake store, no AWS, no network."""
import contextlib
import hashlib
import json
import os
from unittest import mock
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile
import io

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import lambda_package as lp  # noqa: E402


class FakeStore:
    def __init__(self, fail=False):
        self.objects, self.fail = {}, fail

    def exists(self, key):
        return key in self.objects

    def put(self, key, data):
        if self.fail:
            raise OSError('denied')
        self.objects[key] = data


def names(data):
    return zipfile.ZipFile(io.BytesIO(data)).namelist()


class Packages(unittest.TestCase):
    def test_the_same_files_give_the_same_digest_anywhere(self):
        first = lp.build_all(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            for path in ('infra/service/tower_infra', 'infra/ingress/__init__.py'):
                source = ROOT / path
                target = Path(tmp) / path
                target.parent.mkdir(parents=True, exist_ok=True)
                (shutil.copytree if source.is_dir() else shutil.copy)(source, target)
            second = lp.build_all(tmp)
        for function in lp.FUNCTIONS:
            self.assertEqual(first[function][1], second[function][1], function)
            self.assertEqual(hashlib.sha256(first[function][0]).hexdigest(), first[function][1])

    def test_a_changed_module_changes_only_the_functions_that_import_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(ROOT / 'infra/service/tower_infra', Path(tmp) / 'infra/service/tower_infra')
            (Path(tmp) / 'infra/ingress').mkdir()
            shutil.copy(ROOT / 'infra/ingress/__init__.py', Path(tmp) / 'infra/ingress/__init__.py')
            before = lp.build_all(tmp)
            with open(Path(tmp) / 'infra/service/tower_infra/ingress.py', 'a') as handle:
                handle.write('\n# changed\n')
            after = lp.build_all(tmp)
        changed = {f for f in lp.FUNCTIONS if before[f][1] != after[f][1]}
        self.assertEqual(changed, {'tower-port-ack-ingress'})

    def test_the_closure_follows_the_imports_and_stays_in_the_standard_library(self):
        self.assertEqual(lp.closure(ROOT, 'tower-port-ack-ingress'), ['awsjson', 'ed25519', 'forge_webhooks', 'ingress'])
        port = lp.closure(ROOT, 'tower-port-api')
        self.assertTrue({'http_port', 'port', 'forge_webhooks', 'subscriptions', 'ed25519'} <= set(port))
        self.assertNotIn('autodeploy', port)  # the Fargate service alone
        self.assertIn('http_port', lp.closure(ROOT, 'tower-port-webhook-consumer'))
        data = lp.build(ROOT, 'tower-port-ack-ingress')[0]
        self.assertEqual(names(data), ['tower_infra/__init__.py', 'tower_infra/awsjson.py', 'tower_infra/ed25519.py',
                                       'tower_infra/forge_webhooks.py', 'tower_infra/ingress.py'])
        self.assertEqual(zipfile.ZipFile(io.BytesIO(data)).read('tower_infra/__init__.py'),
                         (ROOT / 'infra/ingress/__init__.py').read_bytes())  # the minimal one, as its Dockerfile ships
        self.assertTrue(all(i.date_time == lp.DATE for i in zipfile.ZipFile(io.BytesIO(data)).infolist()))

    def test_every_handler_exists_in_its_module(self):
        for function, (module, _) in lp.FUNCTIONS.items():
            self.assertIn('def handler(', (ROOT / 'infra/service/tower_infra' / f'{module}.py').read_text(encoding='utf-8'), function)


class Upload(unittest.TestCase):
    def test_upload_is_by_digest_and_idempotent_and_records_the_head(self):
        store, built = FakeStore(), lp.build_all(ROOT)
        first = lp.upload(store, built, 'b' * 40, 'h' * 40)
        self.assertEqual(sorted(first['uploaded']), sorted(lp.FUNCTIONS))
        for function, (_, digest, _) in built.items():
            self.assertIn(f'artifacts/lambda/{function}/{digest}.zip', store.objects)
        recorded = json.loads(store.objects[f'artifacts/lambda/head/{"h" * 40}.json'])
        self.assertEqual(recorded['base'], 'b' * 40)
        self.assertEqual(recorded['functions']['tower-port-api']['key'], lp.key_of('tower-port-api', built['tower-port-api'][1]))
        self.assertEqual(lp.upload(store, built, 'b' * 40, 'h' * 40)['uploaded'], [])  # nothing twice

    def test_the_gate_builds_only_for_a_fast_lambda_diff(self):
        self.assertFalse(lp.gate(ROOT, 'a', 'b', FakeStore(), paths=['docs/x.md', 'scripts/y.py'])['built'])
        self.assertFalse(lp.gate(ROOT, 'a', 'b', FakeStore(), paths=['services/control-plane/src/worker.js'])['built'])
        store = FakeStore()
        done = lp.gate(ROOT, 'a', 'b', store, paths=['infra/service/tower_infra/ingress.py'])
        self.assertTrue(done['built'] and done['published'])
        self.assertIn('artifacts/lambda/head/b.json', store.objects)

    def test_the_gate_uploads_nothing_when_the_head_manifest_is_in_the_store_but_still_says_its_digests(self):
        store = FakeStore()
        store.objects['artifacts/lambda/head/b.json'] = b'{}'
        done = lp.gate(ROOT, 'a', 'b', store, paths=['infra/service/tower_infra/ingress.py'])
        self.assertTrue(done['published'])
        self.assertEqual(list(store.objects), ['artifacts/lambda/head/b.json'])  # nothing uploaded again
        # DIGEST-FROM-GATE-JOB: the manifest may be another check's: what this job built is said, for the fast path to compare
        self.assertEqual(done['digests'], {function: digest for function, (_, digest, _) in lp.build_all(ROOT).items()})

    def test_without_a_bucket_it_digests_and_with_a_broken_store_it_warns_but_stays_green(self):
        paths = ['infra/service/tower_infra/port.py']
        offline = lp.gate(ROOT, 'a', 'b', None, paths=paths)
        self.assertTrue(offline['built'] and not offline['published'])
        broken = lp.gate(ROOT, 'a', 'b', FakeStore(fail=True), paths=paths)
        self.assertFalse(broken['published'])
        self.assertIn('upload failed', broken['why'])


class Deployer(unittest.TestCase):
    def test_a_failed_publish_names_the_operation_the_prefix_and_the_backend(self):
        class Denied:
            bucket = 'b'

            def client(self):
                return False

            def exists(self, key):
                return False

            def put(self, key, data):
                raise PermissionError('AccessDenied s3:PutObject')
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(PermissionError):
            lp.publish(ROOT, Denied(), with_layer=False)
        line = err.getvalue()
        self.assertIn('lambda-package FAILED at put tower-port-api', line)
        self.assertIn('backend=aws-cli', line)
        self.assertIn('prefix=artifacts/lambda/tower-port-api', line)
        self.assertIn('AccessDenied s3:PutObject', line)

    def test_publish_records_each_key_and_builds_the_layer_once_per_requirements_file(self):
        store, calls = FakeStore(), []

        def run(command, check=False, **_):
            calls.append(command)
            target = Path(command[command.index('--target') + 1])
            (target / 'psycopg').mkdir(parents=True)
            (target / 'psycopg' / '__init__.py').write_text('x')

        with mock.patch.object(lp, 'layer_python', lambda: None):  # a builder without the Lambdas' Python: no bytecode
            keys = lp.publish(ROOT, store, run=run)
            self.assertEqual(set(keys), set(lp.PARAMETERS) | {'deps'})
            # GATE-SHUTDOWN: only the port's own package is published; the webhook path left the 40-port stack
            self.assertEqual(set(keys), {'tower-port-api', 'deps'})
            self.assertEqual(set(lp.PARAMETERS), set(lp.PUBLISHED))
            self.assertEqual(set(lp.PARAMETERS.values()) | {lp.LAYER_PARAMETER}, {'PortCode', 'DepsKey'})
            self.assertEqual({key.split('/')[2] for key in store.objects}, {'tower-port-api', 'deps'})  # nothing else uploaded
            digest = hashlib.sha256((ROOT / lp.LAYER_REQUIREMENTS).read_bytes()).hexdigest()
            self.assertEqual(keys['deps'], f'artifacts/lambda/deps/{digest}.zip')
            flags = calls[0]
            self.assertIn('manylinux2014_aarch64', flags)
            self.assertIn('manylinux_2_28_aarch64', flags)  # psycopg-binary 3.3 has aarch64 wheels under this tag only
            self.assertEqual(flags.count('--platform'), 2)
            self.assertIn('--only-binary=:all:', flags)
            lp.publish(ROOT, store, run=run)
        self.assertEqual(len(calls), 1)  # the layer exists: pip does not run again

    def layer_with(self, compiler):
        """The layer built by a builder whose interpreter of the Lambdas' Python is `compiler` (None: it has none): pip's
        install leaves a module, pip's own stale bytecode and, when the layer compiles, the bytecode of the Lambdas' Python."""
        store, calls = FakeStore(), []

        def run(command, check=False, **_):
            calls.append((command, check))
            if '--target' in command:
                package = Path(command[command.index('--target') + 1]) / 'psycopg'
                (package / '__pycache__').mkdir(parents=True)
                (package / '__init__.py').write_text('x = 1\n')
                (package / '__pycache__' / '__init__.cpython-39.pyc').write_bytes(b'the builder\'s own, dated')
            else:
                package = Path(command[-1]) / 'psycopg'
                (package / '__pycache__' / '__init__.cpython-312.pyc').write_bytes(b'compiled')
        key = lp.layer(ROOT, store, run=run, python=lambda: compiler)
        names = zipfile.ZipFile(io.BytesIO(store.objects[key])).namelist()
        return key, calls, names

    def test_the_layer_carries_the_bytecode_of_the_lambdas_python_when_the_builder_has_it(self):
        # PORT-COLD-LAYER: live 12/11 the driver's import was 0.32 to 0.46 s of the port's cold start (0.58 to 0.62 s),
        # compiled from source on every cold start; with its bytecode the same import measured 215 -> 132 ms here
        key, calls, names = self.layer_with('/usr/bin/python3.12')
        (pip, pip_checked), (compile_all, compile_checked) = calls
        self.assertIn('--no-compile', pip)  # pip's bytecode is the builder's Python's
        self.assertTrue(pip_checked)
        self.assertEqual(compile_all[:6], ['/usr/bin/python3.12', '-m', 'compileall', '-q', '--invalidation-mode', 'unchecked-hash'])
        self.assertEqual(Path(compile_all[-1]).name, 'python')  # the whole layer
        self.assertFalse(compile_checked)  # a file that does not compile goes without: never a failed build
        self.assertEqual(names, ['python/psycopg/__init__.py', 'python/psycopg/__pycache__/__init__.cpython-312.pyc'])
        requirements = (ROOT / lp.LAYER_REQUIREMENTS).read_bytes()
        self.assertEqual(key, lp.layer_key(hashlib.sha256(requirements + lp.LAYER_BYTECODE).hexdigest()))

    def test_a_builder_without_that_python_builds_the_layer_without_bytecode_under_another_name(self):
        key, calls, names = self.layer_with(None)
        self.assertEqual(len(calls), 1)  # pip alone
        self.assertEqual(names, ['python/psycopg/__init__.py'])
        self.assertEqual(key, lp.layer_key(hashlib.sha256((ROOT / lp.LAYER_REQUIREMENTS).read_bytes()).hexdigest()))
        self.assertNotEqual(key, self.layer_with('/usr/bin/python3.12')[0])  # the two layers never share a name

    def test_the_compiler_is_this_python_when_it_is_the_lambdas_or_python3_12_on_the_path(self):
        self.assertEqual(lp.layer_python(which=lambda name: None, version=(3, 12)), sys.executable)
        self.assertEqual(lp.layer_python(which={'python3.12': '/opt/py/python3.12'}.get, version=(3, 13)), '/opt/py/python3.12')
        self.assertIsNone(lp.layer_python(which=lambda name: None, version=(3, 9)))
        runtimes = {each['Properties']['Runtime'] for each in json.loads((ROOT / 'infra/aws/stacks/40-port.json').read_text())
                    ['Resources'].values() if each['Type'] == 'AWS::Lambda::Function'}
        self.assertEqual(runtimes, {'python%d.%d' % lp.LAYER_PYTHON})  # the bytecode is of the runtime the stack names

    def test_the_bytecode_is_loaded_as_it_is_whatever_the_files_dates(self):
        # the real compile, by this interpreter: unchecked-hash .pyc (flags 0b01): the zip's dates (1980) do not matter
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            store = FakeStore()

            def run(command, check=False, **_):
                if '--target' in command:
                    package = Path(command[command.index('--target') + 1]) / 'pkg'
                    package.mkdir(parents=True)
                    (package / '__init__.py').write_text('VALUE = 41 + 1\n')
                else:
                    subprocess.run(command, check=check)
            with mock.patch.object(lp, 'LAYER_PYTHON', sys.version_info[:2]):
                key = lp.layer(ROOT, store, run=run, work=tmp, python=lambda: sys.executable)
            archive = zipfile.ZipFile(io.BytesIO(store.objects[key]))
            compiled = [name for name in archive.namelist() if name.endswith('.pyc')]
            self.assertEqual(len(compiled), 1)
            self.assertEqual(int.from_bytes(archive.read(compiled[0])[4:8], 'little'), 1)  # hash-based, never checked
            archive.extractall(Path(tmp) / 'opt')
            source = Path(tmp) / 'opt/python/pkg/__init__.py'
            source.write_text('VALUE = "the source, changed: a checked bytecode would be thrown away"\n')
            said = subprocess.run([sys.executable, '-c', 'import pkg; print(pkg.VALUE)'], capture_output=True, text=True,
                                  env={**os.environ, 'PYTHONPATH': str(source.parent.parent), 'PYTHONDONTWRITEBYTECODE': '1'})
            self.assertEqual(said.stdout.strip(), '42', said.stderr)  # the bytecode ran, not the source

    def test_main_uses_the_s3_adapter_whatever_the_registry_says(self):
        seen = []
        with mock.patch.object(lp.storage, 'open_store', lambda location, name=None: seen.append((location, name)) or FakeStore()), \
                mock.patch.dict(os.environ, {'TOWER_ARTIFACT_BUCKET': 'b'}), mock.patch.object(lp, 'publish', return_value={}), mock.patch.object(lp, 'gate', return_value={}), \
                contextlib.redirect_stdout(io.StringIO()):
            lp.main(['publish', '--root', str(ROOT)])
            lp.main(['gate', '--base', 'a', '--head', 'b', '--root', str(ROOT)])
        self.assertEqual(seen, [('b', 's3'), ('b', 's3')])

    def test_the_layer_pins_the_one_library_the_lambdas_import(self):
        # PORT-COLD-LAYER: SQLAlchemy is the service's pool, in the image; no Lambda's module closure reaches it
        pins = [line for line in (ROOT / lp.LAYER_REQUIREMENTS).read_text().splitlines() if line and not line.startswith('#')]
        self.assertEqual(len(pins), 1)
        self.assertTrue(pins[0].startswith('psycopg[binary]=='))
        self.assertIn(pins[0], (ROOT / 'infra/service/requirements.txt').read_text())  # the image's own pin: one driver
        source = ROOT / lp.SOURCE
        for function in lp.FUNCTIONS:
            for module in lp.closure(ROOT, function):
                text = (source / f'{module}.py').read_text()
                for line in text.splitlines():
                    if 'import sqlalchemy' in line or 'from sqlalchemy' in line:
                        self.assertTrue(line.startswith('    '), f'{module}: {line}')  # inside iam_engine, the service's
        self.assertEqual([name for name in ('database',) if 'sqlalchemy' in (source / f'{name}.py').read_text()], ['database'])


class Stack(unittest.TestCase):
    def setUp(self):
        self.port = json.loads((ROOT / 'infra/aws/stacks/40-port.json').read_text())
        self.res = self.port['Resources']

    def test_each_function_is_a_zip_with_an_alias_live_and_retained_versions(self):
        for function, code, logical in (('PortFunction', 'PortCode', 'Port'),):
            properties = self.res[function]['Properties']
            self.assertNotIn('PackageType', properties)
            self.assertEqual((properties['Runtime'], properties['Architectures']), ('python3.12', ['arm64']))
            self.assertEqual(properties['Code']['S3Key'], {'Ref': code})
            self.assertEqual(self.port['Parameters'][code]['Type'], 'String')  # not SSM: deploy.sh passes the key
            alias = self.res[logical + 'Alias']['Properties']
            self.assertEqual((alias['Name'], alias['FunctionName']), ('live', {'Ref': function}))
            self.assertEqual(alias['FunctionVersion'], {'Fn::GetAtt': [logical + 'Version', 'Version']})
            version = self.res[logical + 'Version']
            self.assertEqual((version['DeletionPolicy'], version['UpdateReplacePolicy']), ('Retain', 'Retain'))  # the rollback targets stay

    def test_everything_that_calls_a_function_calls_the_alias(self):
        self.assertEqual(self.res['PortIntegration']['Properties']['IntegrationUri'], {'Ref': 'PortAlias'})
        self.assertEqual(self.res['InvokeFromTheApi']['Properties']['FunctionName'], {'Ref': 'PortAlias'})

    def test_the_layer_carries_the_libraries_for_the_function_that_opens_the_database(self):
        self.assertEqual(self.res['PortFunction']['Properties']['Layers'], [{'Ref': 'DepsLayer'}])
        self.assertEqual(self.res['DepsLayer']['Properties']['CompatibleArchitectures'], ['arm64'])

    def test_the_stack_has_one_function_and_publish_builds_its_package_only(self):
        # GATE-SHUTDOWN: the webhook path (ingress, queue, consumer) left the port stack; the deployer publishes what remains
        functions = sorted(r['Properties']['FunctionName'] for r in self.res.values() if r['Type'] == 'AWS::Lambda::Function')
        self.assertEqual(functions, sorted(lp.PUBLISHED))
        self.assertEqual({p for p in self.port['Parameters'] if p.endswith('Code')}, set(lp.PARAMETERS.values()))

    def test_a_new_layer_reaches_the_alias_live_a_version_is_of_its_code_and_of_its_layer(self):
        # PORT-COLD-LAYER: the alias runs a published version, and a version was replaced only when the code's key
        # changed: a layer alone changed $LATEST and nothing the alias runs, until the next change of the code
        # PORT-MEMORY-LIVE: and the port's memory, which the version freezes the same way
        self.assertEqual(self.res['PortVersion']['Properties']['Description'],
                         {'Fn::Sub': 'slow deploy of ${PortCode} on ${DepsKey} with 256 MB'})
        longest = 'slow deploy of %s on %s with 3008 MB' % (lp.key_of('tower-port-api', 'a' * 64), lp.layer_key('a' * 64))
        self.assertLessEqual(len(longest), 256)  # a version's description

    def test_the_runner_keeps_the_artifacts_and_knows_the_bucket(self):
        # GATE-SHUTDOWN (D-314): the runner's role and task are gone; the outputs bucket stays, retained, and its artifacts
        # never expire (the deployer writes them, the service and the port read them)
        runner = json.loads((ROOT / 'infra/aws/stacks/50-runner.json').read_text())
        self.assertEqual(runner['Resources']['Outputs']['DeletionPolicy'], 'Retain')
        lifecycle = runner['Resources']['Outputs']['Properties']['LifecycleConfiguration']['Rules']
        self.assertTrue(all(rule['Prefix'] == 'runs/' for rule in lifecycle))  # artifacts do not expire

    def test_the_deployer_publishes_before_the_stacks_and_the_gate_has_the_check(self):
        deploy = (ROOT / 'infra/aws/deploy.sh').read_text()
        self.assertLess(deploy.index('lambda_package.py publish'), deploy.index('  deploy_stacks\n'))
        self.assertIn('artifact)', (ROOT / 'scripts/gate-check').read_text())


class GateCheck(unittest.TestCase):
    def test_a_head_with_a_fast_lambda_diff_gets_an_artifact_check_job(self):
        import gate_infra
        spec = {'repo': 'r', 'pr': '1', 'head': 'h' * 40, 'base': 'b' * 40, 'ref': 'x', 'base_ref': 'y'}
        trees = {'head': 't1', 'base': 't0'}
        plan = {'stages': [], 'tests': [], 'artifacts': ['lambda']}
        jobs = dict(gate_infra.checks(spec, plan, trees, '2026-11-09'))
        self.assertEqual(list(jobs), ['artifact:lambda'])
        self.assertEqual(gate_infra.checks(spec, {'stages': [], 'tests': []}, trees, '2026-11-09'), [])


if __name__ == '__main__':
    unittest.main()
