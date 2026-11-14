"""IMAGE-PREWARM-B1 (docs/operations/aws.md 22.9): the service/runner boots from a code bundle named by its digest.

Today's behaviour is pinned first: with no TOWER_CODE_KEY/TOWER_CODE_SHA256 boot() reads nothing, execs nothing and main()
dispatches as before. Then the real bundle (lambda_package.build_code of this checkout) from a fake store: the happy path
execs the same command on a fresh directory, and the child really imports that directory's tower_infra ahead of a baked one
in its working directory; a sha mismatch, other requirements, a missing object, a digest that is not the bundle's, half
the variables and a marker that does not match exit FAILED before any work; the marker of a loaded bundle goes on.
Hermetic: no network, execve stubbed.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import __main__ as entry, code_bundle  # noqa: E402
import lambda_package  # noqa: E402

BAKED = ROOT / 'infra' / 'service' / 'tower_infra'  # its parent holds requirements.txt, as /app does in the image
DATA, SHA, _ = lambda_package.build_code(ROOT)
KEY = lambda_package.code_key(SHA)


class Store:
    def __init__(self, objects=None):
        self.objects, self.reads = dict(objects or {}), []

    def get(self, key):
        self.reads.append(key)
        return self.objects.get(key)


class Execed(BaseException):
    """execve's stand-in: it does not return, and the boot's fail-safe (which catches Exception) does not see it."""


def execve(path, argv, environ):
    raise Execed(path, argv, environ)


# SLOW-PATH-NO-ROLLOUT-WAIT: no database here: deploy.live_code reads as "none" unless a test passes its own read
NO_DATUM = mock.patch.object(code_bundle, 'live', lambda environ: ('', False))


def setUpModule():
    NO_DATUM.start()


def tearDownModule():
    NO_DATUM.stop()


def env(**extra):
    return {'TOWER_CODE_KEY': KEY, 'TOWER_CODE_SHA256': SHA, 'TOWER_ARTIFACT_BUCKET': 'outputs', 'TOWER_IMAGE': 'tag1',
            **extra}


class TodaysBehaviour(unittest.TestCase):
    def test_no_variables_read_nothing_and_exec_nothing(self):
        store = Store({KEY: DATA})
        for command in ('serve', 'run-container', 'init', 'healthy', 'bogus'):
            self.assertIsNone(code_bundle.boot(command, [command], {'TOWER_IMAGE_DIGEST': 'x'}, store, execve, BAKED))
        self.assertEqual(store.reads, [])

    def test_init_and_healthy_never_boot_even_with_the_variables(self):
        store = Store({KEY: DATA})
        for command in ('init', 'healthy'):
            self.assertIsNone(code_bundle.boot(command, [command], env(), store, execve, BAKED))
        self.assertEqual(store.reads, [])

    def test_main_dispatches_as_before_without_the_variables(self):
        clean = {k: v for k, v in os.environ.items() if not k.startswith('TOWER_CODE')}
        with mock.patch.dict(os.environ, clean, clear=True), mock.patch.object(entry, 'serve') as serve, \
                mock.patch.object(entry, 'run_container') as run, mock.patch('logging.basicConfig'):
            self.assertEqual(entry.main(['serve']), 0)
            self.assertEqual(entry.main(['run-container']), 0)
        serve.assert_called_once_with()
        run.assert_called_once_with()


class LiveCode(unittest.TestCase):
    """SLOW-PATH-NO-ROLLOUT-WAIT: a task ECS starts boots deploy.live_code when its task definition has not seen it, so a
    code-only landing needs no rollout to last; anything unknown is the task definition's code."""
    DATUM = f"{SHA}@{'1' * 40}"
    IMAGE = {'TOWER_ARTIFACT_BUCKET': 'outputs', 'TOWER_IMAGE': 'tag1', 'TOWER_IMAGE_DIGEST': 'registry/tower-service:tag1'}

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root, self.asked = Path(self.tmp.name), 0

    def boot(self, environ, datum=DATUM, failed=False, store=None, command='serve', here=BAKED):
        def read(found):
            self.asked += 1
            if isinstance(datum, Exception):
                raise datum
            return datum, failed
        return code_bundle.boot(command, [command], {'TOWER_CODE_ROOT': str(self.root), **environ},
                                Store({KEY: DATA}) if store is None else store, execve, here, read)

    def test_a_task_definition_that_has_not_seen_the_datum_boots_the_live_code(self):
        other = 'b' * 64
        for label, definition in (
                ('the image\'s own code, deployed before any swap', {**self.IMAGE, 'TOWER_CODE_SEEN': ''}),
                ('deployed seeing an older datum', {**self.IMAGE, 'TOWER_CODE_SEEN': f"{other}@{'0' * 40}"}),
                ('a definition older than the stamp', self.IMAGE),
                ('a LiveCode of an older swap', {**self.IMAGE, 'TOWER_CODE_KEY': f'artifacts/lambda/tower-code/{other}.zip',
                                                  'TOWER_CODE_SHA256': other, 'TOWER_IMAGE_DIGEST': other, 'TOWER_CODE_SEEN': ''})):
            with self.subTest(label), self.assertRaises(Execed) as done:
                self.boot(definition)
            path, argv, child = done.exception.args
            self.assertEqual(argv, [sys.executable, '-m', 'tower_infra', 'serve'])
            self.assertEqual((child['TOWER_CODE_KEY'], child['TOWER_CODE_SHA256'], child['TOWER_IMAGE_DIGEST']), (KEY, SHA, SHA))
            self.assertEqual(child['TOWER_IMAGE'], f'tag1+code.{SHA[:16]}')
            loaded, asked = Path(child[code_bundle.LOADED]) / 'tower_infra', self.asked
            self.assertIsNone(self.boot(child, here=loaded))  # the child runs it: no second read, no second exec
            self.assertEqual(self.asked, asked)

    def test_a_datum_the_definition_saw_or_already_names_changes_nothing(self):
        store = Store({KEY: DATA})
        self.assertIsNone(self.boot({**self.IMAGE, 'TOWER_CODE_SEEN': self.DATUM}, store=store))  # deploy.sh saw it: the image is newer or the same
        self.assertEqual(store.reads, [])
        named = {**self.IMAGE, **env(), 'TOWER_IMAGE_DIGEST': SHA, 'TOWER_CODE_SEEN': ''}
        with self.assertRaises(Execed) as done:  # LiveCode is that bundle already: the boot of the definition, as before
            self.boot(named, datum=f"{SHA}@{'2' * 40}", store=store)
        self.assertEqual((done.exception.args[2]['TOWER_CODE_SHA256'], store.reads), (SHA, [KEY]))

    def test_a_definition_stamped_unknown_a_standby_and_the_other_commands_never_read_the_datum(self):
        self.assertIsNone(self.boot({**self.IMAGE, 'TOWER_CODE_SEEN': 'unknown'}))  # the deployer could not read it
        with self.assertRaises(Execed) as done:  # a prewarm standby runs exactly the bundle its RunTask names
            self.boot({**self.IMAGE, **env(), 'TOWER_IMAGE_DIGEST': SHA, 'TOWER_STANDBY': '1'}, datum=f"{'c' * 64}@{'3' * 40}")
        self.assertEqual(done.exception.args[2]['TOWER_CODE_SHA256'], SHA)
        for command in ('init', 'healthy'):  # the health check runs every few seconds: it must never open a connection
            self.assertIsNone(self.boot(self.IMAGE, command=command))
        self.assertEqual(self.asked, 0)

    def test_anything_unknown_is_the_code_of_the_task_definition(self):
        with self.assertLogs('tower_infra.code_bundle', 'WARNING'):
            self.assertIsNone(self.boot(self.IMAGE, datum=RuntimeError('the database is away')))  # unreadable: the image's code
        for datum in ('', 'bogus', SHA, f'{SHA}@zz', f'{SHA}@'):
            self.assertIsNone(self.boot(self.IMAGE, datum=datum), datum)
        with self.assertLogs('tower_infra.code_bundle', 'WARNING'):
            self.assertIsNone(self.boot(self.IMAGE, failed=True))  # a reload onto it failed: never booted from the datum
        with self.assertLogs('tower_infra.code_bundle', 'WARNING'):
            self.assertIsNone(self.boot(self.IMAGE, store=Store()))  # not in the store: no exit, the image's code
        with self.assertLogs('tower_infra.code_bundle', 'WARNING'):
            self.assertIsNone(self.boot(self.IMAGE, store=Store({KEY: DATA + b'x'})))  # another sha256
        other, moved = hashlib.sha256(b'moved').hexdigest(), Store({KEY: DATA})
        with self.assertLogs('tower_infra.code_bundle', 'WARNING'), self.assertRaises(Execed) as done:
            self.boot({**self.IMAGE, **env(), 'TOWER_IMAGE_DIGEST': SHA}, datum=f"{other}@{'4' * 40}", store=moved)
        self.assertEqual(done.exception.args[2]['TOWER_CODE_SHA256'], SHA)  # the datum's bundle is gone: the definition's LiveCode

    def test_the_directories_of_the_bundles_loaded_before_are_removed_once_this_one_runs(self):
        earlier, kept = self.root / 'tower-code-000000000000-old', self.root / 'something-else'
        for directory in (earlier, kept):
            (directory / 'tower_infra').mkdir(parents=True)
        with self.assertRaises(Execed) as done:
            self.boot(self.IMAGE)
        child = done.exception.args[2]
        own = Path(child[code_bundle.LOADED])
        self.assertTrue(earlier.exists())  # nothing is removed before the exec
        self.assertIsNone(self.boot(child, here=own / 'tower_infra'))
        self.assertEqual((earlier.exists(), kept.exists(), (own / 'tower_infra' / '__main__.py').exists()), (False, True, True))


class Boot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def boot(self, environ, store=None, command='run-container', here=BAKED):
        environ = {'TOWER_CODE_ROOT': str(self.root), **environ}
        return code_bundle.boot(command, [command], environ, Store({KEY: DATA}) if store is None else store, execve, here)

    def test_the_happy_path_execs_the_same_command_on_the_unpacked_bundle(self):
        with self.assertRaises(Execed) as done:
            self.boot(env(PYTHONPATH='/elsewhere'))
        path, argv, child = done.exception.args
        self.assertEqual((path, argv), (sys.executable, [sys.executable, '-m', 'tower_infra', 'run-container']))
        directory = Path(child[code_bundle.LOADED])
        self.assertEqual(directory.parent, self.root)
        self.assertEqual(child['PYTHONPATH'], f'{directory}{os.pathsep}/elsewhere')
        self.assertEqual(child['PYTHONSAFEPATH'], '1')
        self.assertEqual(child['TOWER_IMAGE_DIGEST'], SHA)  # the pointer names this code version
        self.assertEqual(child['TOWER_IMAGE'], f'tag1+code.{SHA[:16]}')  # DBOS recovers only its own version's workflows
        self.assertEqual(child['TOWER_MIGRATIONS'], str(directory / 'migrations'))
        self.assertEqual(sorted(p.name for p in (directory / 'migrations').iterdir()),
                         sorted(p.name for p in (ROOT / 'infra' / 'db' / 'migrations').iterdir()))
        for module in BAKED.glob('*.py'):
            self.assertEqual((directory / 'tower_infra' / module.name).read_bytes(), module.read_bytes())

    def test_the_child_imports_the_bundle_not_the_baked_package_in_its_working_directory(self):
        with self.assertRaises(Execed) as done:
            self.boot({**os.environ, **env()})  # the interpreter's own environment, for the real child below
        child = done.exception.args[2]
        probe = [sys.executable, '-c', 'import tower_infra; print(tower_infra.__file__)']
        out = subprocess.run(probe, cwd=BAKED.parent, env=child, capture_output=True, text=True, check=True).stdout
        self.assertEqual(Path(out.strip()).parent, Path(child[code_bundle.LOADED]) / 'tower_infra')
        unsafe = {k: v for k, v in child.items() if k != 'PYTHONSAFEPATH'}  # why PYTHONSAFEPATH: /app would come first
        out = subprocess.run(probe, cwd=BAKED.parent, env=unsafe, capture_output=True, text=True, check=True).stdout
        self.assertEqual(Path(out.strip()).parent, BAKED)

    def test_the_marker_of_the_loaded_bundle_goes_on_without_a_read(self):
        with self.assertRaises(Execed) as done:
            self.boot(env())
        child, store = done.exception.args[2], Store()
        loaded = Path(child[code_bundle.LOADED]) / 'tower_infra'
        self.assertIsNone(self.boot(child, store, here=loaded))
        self.assertEqual(store.reads, [])
        with self.assertLogs('tower_infra.code_bundle', 'ERROR'):  # the marker, but the baked code runs
            self.assertEqual(self.boot(child, store, here=BAKED), code_bundle.FAILED)

    def test_the_loaded_child_gives_its_own_children_the_environment_from_before_the_exec(self):
        # BUNDLE-ENV-LEAK: the runner passed PYTHONSAFEPATH=1 and the bundle's PYTHONPATH to every check it ran
        for prior in ({}, {'PYTHONPATH': '/opt/keep', 'PYTHONSAFEPATH': ''}):
            with self.assertRaises(Execed) as done:
                self.boot(env(**prior))
            child = done.exception.args[2]
            self.assertEqual(child['PYTHONSAFEPATH'], '1')
            loaded = Path(child[code_bundle.LOADED]) / 'tower_infra'
            self.assertIsNone(code_bundle.boot('run-container', ['run-container'], child, Store(), execve, loaded))
            for name in ('PYTHONPATH', 'PYTHONSAFEPATH'):
                self.assertEqual(child.get(name), prior.get(name), name)
                self.assertNotIn(code_bundle.PRIOR + name, child)

    def test_the_heads_scripts_drop_the_bundle_path_before_any_check(self):
        # BUNDLE-ENV-LEAK: scripts/gate-check and scripts/cloud/setup.sh run on a runner that may still leak them
        for script in ('scripts/gate-check', 'scripts/cloud/setup.sh'):
            text = (ROOT / script).read_text(encoding='utf-8')
            block = text[text.index('# BUNDLE-ENV-LEAK'):]
            block = block[:block.index('\nfi\n') + 4]
            probe = block + 'echo "safe=${PYTHONSAFEPATH-unset} path=${PYTHONPATH-unset}"\n'
            leaked = {'PATH': os.environ['PATH'], 'TOWER_CODE_LOADED': '/tmp/b', 'PYTHONSAFEPATH': '1',
                      'PYTHONPATH': '/tmp/b:/opt/keep'}
            out = subprocess.run(['bash', '-c', 'set -euo pipefail\n' + probe], env=leaked, capture_output=True, text=True,
                                 check=True).stdout.strip()
            self.assertEqual(out, 'safe=unset path=/opt/keep', script)
            alone = dict(leaked, PYTHONPATH='/tmp/b')
            out = subprocess.run(['bash', '-c', 'set -euo pipefail\n' + probe], env=alone, capture_output=True, text=True,
                                 check=True).stdout.strip()
            self.assertEqual(out, 'safe=unset path=unset', script)
            clean = {'PATH': os.environ['PATH'], 'PYTHONPATH': '/opt/keep'}  # no bundle: nothing touched
            out = subprocess.run(['bash', '-c', 'set -euo pipefail\n' + probe], env=clean, capture_output=True, text=True,
                                 check=True).stdout.strip()
            self.assertEqual(out, 'safe=unset path=/opt/keep', script)

    def test_a_sha_mismatch_exits_before_any_work(self):
        with self.assertLogs('tower_infra.code_bundle', 'ERROR') as logs:
            self.assertEqual(self.boot(env(), Store({KEY: DATA + b'x'})), code_bundle.FAILED)
            self.assertEqual(self.boot(env(TOWER_CODE_SHA256=hashlib.sha256(b'other').hexdigest()), Store({KEY: DATA})),
                             code_bundle.FAILED)
        self.assertTrue(all('has sha256' in line for line in logs.output))
        self.assertEqual(list(self.root.iterdir()), [])  # nothing unpacked

    def test_every_other_failure_exits_too(self):
        here = self.root / 'image' / 'tower_infra'  # an image whose requirements are not the bundle's
        here.mkdir(parents=True)
        (here.parent / 'requirements.txt').write_text('dbos==0.0.1\n')
        cases = {'other requirements': (env(), None, here),
                 'missing object': (env(), Store(), BAKED),
                 'not the digest': (env(TOWER_IMAGE_DIGEST='sha256:' + '1' * 64), None, BAKED),
                 'half the variables': ({'TOWER_CODE_KEY': KEY}, None, BAKED),
                 'no bucket': ({'TOWER_CODE_KEY': KEY, 'TOWER_CODE_SHA256': SHA}, False, BAKED)}
        for name, (environ, store, where) in cases.items():
            with self.subTest(name), self.assertLogs('tower_infra.code_bundle', 'ERROR'):
                found = code_bundle.boot('serve', ['serve'], {'TOWER_CODE_ROOT': str(self.root / 'x'), **environ},
                                         None if store is False else Store({KEY: DATA}) if store is None else store,
                                         execve, where)
                self.assertEqual(found, code_bundle.FAILED)
        self.assertFalse((self.root / 'x').exists())

    def test_main_exits_non_zero_and_never_serves_when_the_bundle_cannot_load(self):
        with mock.patch.dict(os.environ, {'TOWER_CODE_KEY': KEY, 'TOWER_CODE_SHA256': SHA}), \
                mock.patch.dict(os.environ, {'TOWER_ARTIFACT_BUCKET': ''}), mock.patch.object(entry, 'serve') as serve, \
                mock.patch('logging.basicConfig'), self.assertLogs('tower_infra.code_bundle', 'ERROR'):
            self.assertEqual(entry.main(['serve']), code_bundle.FAILED)
        serve.assert_not_called()


class Bundle(unittest.TestCase):
    def test_the_bundle_is_the_package_the_migrations_and_the_requirements_by_content(self):
        names = set(lambda_package.build_code(ROOT)[2])
        self.assertEqual(lambda_package.build_code(ROOT)[1], SHA)
        self.assertTrue(KEY.startswith('artifacts/lambda/tower-code/') and KEY.endswith(f'{SHA}.zip'))
        self.assertIn('requirements.txt', names)
        self.assertTrue({f'tower_infra/{p.name}' for p in BAKED.glob('*.py')} <= names)
        self.assertTrue({f'migrations/{p.name}' for p in (ROOT / 'infra' / 'db' / 'migrations').iterdir()} <= names)
        self.assertFalse(any('__pycache__' in name for name in names))

    def test_publish_code_uploads_once(self):
        class Kept:
            def __init__(self):
                self.objects = {}

            def exists(self, key):
                return key in self.objects

            def put(self, key, data):
                self.objects[key] = data

        kept = Kept()
        self.assertEqual(lambda_package.publish_code(ROOT, kept), {'key': KEY, 'sha256': SHA, 'bytes': len(DATA),
                                                                  'uploaded': True})
        self.assertFalse(lambda_package.publish_code(ROOT, kept)['uploaded'])
        self.assertEqual(kept.objects, {KEY: DATA})

    def test_both_task_roles_read_the_bundle_prefix_and_both_tasks_know_the_bucket(self):
        for stack, role in (('30-service.json', 'TaskRole'), ('50-runner.json', 'TaskRole')):
            template = json.loads((ROOT / 'infra' / 'aws' / 'stacks' / stack).read_text())
            statements = [s for p in template['Resources'][role]['Properties']['Policies']
                          for s in p['PolicyDocument']['Statement']]
            self.assertTrue(any('s3:GetObject' in json.dumps(s['Action']) and '/artifacts/lambda/*' in json.dumps(s['Resource'])
                                for s in statements), stack)
            task = template['Resources']['TaskDefinition']['Properties']['ContainerDefinitions']
            main = [c for c in task if c.get('Command') in (['serve'], ['run-container'])][0]
            self.assertIn('TOWER_ARTIFACT_BUCKET', [e['Name'] for e in main['Environment']], stack)


if __name__ == '__main__':
    unittest.main()
