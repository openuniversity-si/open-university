"""The Python hermetic harness (plan v3 H1, D-069 item 5): loopback only, seeded random, injected clock, timeout.

Run with the harness installed (the gate puts scripts/lib/hermetic/ on PYTHONPATH); this file also installs it itself, so a
bare `python3 scripts/tests/test_hermetic.py` is judged the same. No network: the only socket is a loopback listener.
"""
from datetime import timedelta
import json
import random
import shutil
import subprocess
import tempfile
import unittest.mock
import os
from pathlib import Path
import socket
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import hermetic  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

hermetic.install()

OUTSIDE_HOST = '203.0.113.7'
LIMIT_S = timedelta(milliseconds=config.get('tests.script_timeout_ms')).total_seconds()


class NetworkTest(unittest.TestCase):
    def test_an_outside_host_is_refused_by_connect_and_by_name(self):
        self.assertFalse(config.get('tests.network_allowed'))
        client = socket.socket()
        self.addCleanup(client.close)
        with self.assertRaises(hermetic.NetworkDenied):
            client.connect((OUTSIDE_HOST, 80))
        with self.assertRaises(hermetic.NetworkDenied):
            socket.getaddrinfo('example.com', 80)

    def test_the_loopback_still_serves_a_fixture(self):
        server = socket.socket()
        self.addCleanup(server.close)
        server.bind(('127.0.0.1', 0))
        server.listen(1)
        client = socket.create_connection(server.getsockname())
        self.addCleanup(client.close)
        peer, _ = server.accept()
        self.addCleanup(peer.close)
        client.sendall(b'ok')
        self.assertEqual(peer.recv(2), b'ok')

    def test_a_udp_send_outside_the_loopback_is_refused(self):
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sender.close)
        with self.assertRaises(hermetic.NetworkDenied):
            sender.sendto(b'x', ('198.51.100.9', 9))


CODE_UNDER_TEST = """
import json, os, socket, sys
sys.path.insert(0, os.path.join(sys.argv[1], 'scripts', 'lib'))
import config
import hermetic
value = config.get('tests.fixture_only_key')
os.environ.clear()
try:
    socket.create_connection((sys.argv[3], 80), timeout=1)
    denied = False
except OSError as error:
    denied = 'hermetic' in str(error)
print(json.dumps({'config': config.__file__, 'hermetic': hermetic.__file__, 'value': value, 'store': config.store_kind(),
                  'denied': denied, 'tooling_on_path': sys.argv[2] in sys.path}))
"""


class CodeUnderTestTest(unittest.TestCase):
    def test_the_code_under_test_imports_its_own_config_pinned_to_the_tests_store(self):
        fixture = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, fixture, True)
        shutil.copytree(ROOT / 'scripts' / 'lib', fixture / 'scripts' / 'lib', ignore=shutil.ignore_patterns('__pycache__'))
        fixture_copy.registry(fixture)
        shutil.copytree(ROOT / 'contracts' / 'config', fixture / 'contracts' / 'config')
        registry = fixture / 'config' / 'registry' / 'tests.json'
        document = json.loads(registry.read_text())
        document['properties']['tests.fixture_only_key'] = {'type': 'integer', 'default': config.get('tests.random_seed'), 'description': 'fixture'}
        registry.write_text(json.dumps(document))
        tooling = str(ROOT / 'scripts' / 'lib')
        env = {key: value for key, value in os.environ.items() if key != 'OU_CONFIG_STORE'}
        env['PYTHONPATH'] = str(ROOT / 'scripts' / 'lib' / 'hermetic')  # this checkout's sitecustomize, whoever the outer judge is
        done = subprocess.run([sys.executable, '-c', CODE_UNDER_TEST, str(fixture), tooling, OUTSIDE_HOST], cwd=fixture,
                              env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        seen = json.loads(done.stdout)
        self.assertEqual(Path(seen['config']), fixture / 'scripts' / 'lib' / 'config.py')
        self.assertEqual(Path(seen['hermetic']), fixture / 'scripts' / 'lib' / 'hermetic.py')
        self.assertEqual(seen['value'], config.get('tests.random_seed'))
        self.assertEqual(seen['store'], config.entry('tests.config_store')['default'])
        self.assertTrue(seen['denied'])
        self.assertFalse(seen['tooling_on_path'])


class JudgesPinnedTest(unittest.TestCase):
    """D-272: a script test judges every lock as its rule is written. The live registry may hold the exception regime on
    (D-260, granted by Daniel); the hook pins the code under test's own regime to off, and without the hook the registry's
    view holds, so the pin is the hook's doing and not the registry's."""

    PROBE = "import sys; sys.path.insert(0, sys.argv[1]); import regime; print(regime.state()['active'], regime.lifted('structure'))"

    def probe(self, hooked):
        env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
        if hooked:
            env['PYTHONPATH'] = str(ROOT / 'scripts' / 'lib' / 'hermetic')  # this checkout's sitecustomize, as the gate starts it
        done = subprocess.run([sys.executable, '-c', self.PROBE, str(ROOT / 'scripts' / 'lib')], env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.split()

    def test_a_script_test_judges_every_lock_without_the_exception_regime(self):
        self.assertEqual(self.probe(hooked=True), ['False', 'False'])

    def test_without_the_hook_the_registry_view_holds(self):
        self.assertEqual(self.probe(hooked=False)[0], str(config.get('regime.exception_active')))


class DeterminismTest(unittest.TestCase):
    def test_a_scrubbed_process_still_reads_the_local_configuration_log(self):
        kind = config.entry('tests.config_store')['default']
        self.assertEqual(hermetic.store_env(), {'OU_CONFIG_STORE': kind})
        self.assertEqual(config.store_kind(), kind)  # pinned by install(): the environment no longer decides
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.store_kind(), kind)

    def test_the_rng_replays_from_the_registry_seed(self):
        self.assertEqual([hermetic.rng().random() for _ in range(3)][0], hermetic.rng().random())
        random.seed(config.get('tests.random_seed'))
        first = random.random()
        random.seed(config.get('tests.random_seed'))
        self.assertEqual(first, random.random())

    def test_the_clock_starts_at_the_registry_instant_and_moves_only_when_advanced(self):
        clock = hermetic.Clock()
        self.assertEqual(clock.now().isoformat(), '2026-01-01T00:00:00+00:00')
        clock.advance(90)
        self.assertEqual(clock.now().isoformat(), '2026-01-01T00:01:30+00:00')
        self.assertEqual(hermetic.clock().now(), hermetic.clock().now())


class TimeoutTest(unittest.TestCase):
    def slow(self, wrap):
        class Slow(unittest.TestCase):
            def test_slow(self):
                time.sleep(2)

        result = unittest.TestResult()
        wrap(hermetic._state['run'], 0.05)(Slow('test_slow'), result)
        return result

    def test_a_test_past_the_limit_fails_instead_of_hanging(self):
        self.assertGreaterEqual(config.get('tests.script_timeout_ms'), 1)
        result = self.slow(hermetic.bounded)
        self.assertEqual(len(result.failures) + len(result.errors), 1)
        self.assertIn('tests.script_timeout_ms', (result.failures + result.errors)[0][1])

    def test_a_wrapper_around_a_wrapper_never_extends_the_inner_limit(self):
        result = self.slow(lambda run, limit: hermetic.bounded(hermetic.bounded(run, LIMIT_S), limit))
        self.assertEqual(len(result.failures) + len(result.errors), 1)


class LateLookupTest(unittest.TestCase):
    def test_a_lookup_after_the_tooling_left_the_path_is_refused_not_an_import_error(self):
        # sitecustomize has dropped the tooling's modules and path by the time a test resolves a name (GX-29, C1 cold gate).
        code = ('import socket, sys\n'
                'assert "forge_events" not in sys.modules\n'
                'try:\n    socket.getaddrinfo("%s", 80)\n'
                'except OSError as error:\n    print(type(error).__name__)' % 'example.test')
        done = subprocess.run([sys.executable, '-c', code], env=hermetic.shell_env({'PATH': os.environ['PATH']}),
                              capture_output=True, text=True, timeout=LIMIT_S, check=False, cwd=tempfile.gettempdir())
        self.assertEqual(done.stdout.strip(), 'NetworkDenied', done.stderr)


class ShellEnvTest(unittest.TestCase):
    """GX-29: the denial extended to the gate's shell (Node and Python children, proxies dropped)."""

    def env(self):
        base = {'PATH': os.environ['PATH'], 'HTTPS_PROXY': 'http://' + OUTSIDE_HOST, 'NODE_OPTIONS': '--no-warnings'}
        return hermetic.shell_env(base)

    def test_the_environment_carries_the_hooks_and_drops_proxies(self):
        env = self.env()
        self.assertNotIn('HTTPS_PROXY', env)
        self.assertEqual(env['OU_GATE_OFFLINE'], '1')
        self.assertEqual(env['OU_HERMETIC_LOOPBACK'], ','.join(config.get('tests.loopback_hosts')))
        self.assertIn('--no-warnings', env['NODE_OPTIONS'])
        self.assertEqual(env['NODE_OPTIONS'].count('ou-hermetic-'), 1)
        self.assertEqual(hermetic.shell_env(env)['NODE_OPTIONS'], env['NODE_OPTIONS'], 'idempotent')

    def test_a_node_child_refuses_an_outside_host_and_reaches_the_loopback(self):
        node = shutil.which('node')
        if node is None:
            self.skipTest('no node')
        server = socket.socket()
        self.addCleanup(server.close)
        server.bind((config.get('tests.loopback_hosts')[0], 0))
        server.listen(1)
        script = ('const net=require("net");'
                  f'net.connect({server.getsockname()[1]},"{server.getsockname()[0]}",function(){{console.log("loopback");this.destroy()}});'
                  f'net.connect(80,"{OUTSIDE_HOST}").on("error",e=>console.log(e.code));')
        done = subprocess.run([node, '-e', script], env=self.env(), capture_output=True, text=True, timeout=LIMIT_S, check=False)
        self.assertEqual(sorted(done.stdout.split()), ['EHERMETIC', 'loopback'], done.stderr)

    def test_a_python_child_refuses_an_outside_host(self):
        code = ('import socket\n'
                'try:\n    socket.socket().connect(("%s", 80))\n'
                'except OSError as error:\n    print(type(error).__name__)' % OUTSIDE_HOST)
        done = subprocess.run([sys.executable, '-c', code], env=self.env(), capture_output=True, text=True, timeout=LIMIT_S,
                              check=False, cwd=tempfile.gettempdir())
        self.assertEqual(done.stdout.strip(), 'NetworkDenied', done.stderr)


class CoversTraceTest(unittest.TestCase):
    """GX-29 (B-13): a Python script test lists the files it read outside its declared covers, report-only."""

    def run_fake(self, mode=None, tmp=None):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / 'scripts' / 'tests' / 'covers').mkdir(parents=True)
        (root / 'data').mkdir()
        for name in ('declared.txt', 'undeclared.txt', 'written.txt'):
            (root / 'data' / name).write_text('x')
        (root / 'scripts' / 'tests' / 'fake.test.sh').write_text('#!/usr/bin/env bash\n')
        (root / 'scripts' / 'tests' / 'covers' / 'fake.json').write_text(json.dumps({
            'script': 'scripts/tests/fake.test.sh',
            'covers': ['scripts/tests/test_fake.py', 'data/declared.txt']}))
        (root / 'scripts' / 'tests' / 'test_fake.py').write_text(
            'import sys\n'
            'for name in ("declared.txt", "undeclared.txt"):\n    open("%s/data/" + name).read()\n'
            'open("%s/data/written.txt", "w").write("y")\n'
            'sys.exit(%d)\n' % (root, root, os.EX_SOFTWARE))
        env = hermetic.shell_env({'PATH': os.environ['PATH']})
        if mode is not None:
            env['OU_CONFIG_STORE'] = 'local'
        if tmp is not None:
            env['TMPDIR'] = str(tmp)
        done = subprocess.run([sys.executable, str(root / 'scripts' / 'tests' / 'test_fake.py')], env=env, cwd=tempfile.gettempdir(),
                              capture_output=True, text=True, timeout=LIMIT_S, check=False)
        return done

    def test_an_undeclared_read_is_listed_and_the_exit_status_is_untouched(self):
        done = self.run_fake()
        self.assertEqual(done.returncode, os.EX_SOFTWARE, 'report-only: the test\'s own status')
        self.assertIn('covers trace (report-only): scripts/tests/test_fake.py read 1 file(s) outside its declared covers', done.stderr)
        self.assertIn('data/undeclared.txt', done.stderr)
        self.assertNotIn('data/declared.txt', done.stderr)
        self.assertNotIn('data/written.txt', done.stderr)

    def test_the_trace_directory_is_removed(self):
        # The child's own temporary directory: the shared one also holds the traces of script tests running beside this
        # one in the gate (GX-22 incident: a set mismatch from a concurrent ou-covers-* directory, never from this run).
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        self.run_fake(tmp=tmp)
        self.assertEqual(list(tmp.glob('ou-covers-*')), [])

    def test_mode_is_a_registered_report_default(self):
        self.assertEqual(config.get('gate-trace.covers_trace_mode'), 'report')


if __name__ == '__main__':
    unittest.main()
