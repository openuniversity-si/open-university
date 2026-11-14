"""One cloud session: pinned toolchain, Origin CLI, no legacy delivery providers.

Host python and node are tripwires. The pinned toolchain and the Origin CLI stand-in do the work.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config
import credentials
import forge_origin_client
import hermetic
import test_db

sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'cloud'))
from machine_premise import premise_failed  # noqa: E402 - the one `FAIL env: <premise>` line (TX12)
import toolchain  # noqa: E402 - scripts/cloud

SENTINEL = 'fixture-sentinel-not-printed'


def _script(path, body):
    path.write_text(body)
    path.chmod(0o755)


class ClaudeSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='ou-claude-')
        cls.work = Path(cls.tmp.name)
        cls.shims = cls.work / 'shims'
        cls.guard = cls.work / 'guard'
        cls.shims.mkdir()
        cls.guard.mkdir()
        cls.log = cls.work / 'shim.log'
        # TX12: this class's own preflight stamp; the checkout's shared one is never read, written or deleted.
        cls.stamp = cls.work / 'preflight.stamp'
        cls.shared_stamp = toolchain.manifest.toolchain_dir() / 'preflight.stamp'
        called = cls.work / 'gh-called'
        deny = textwrap.dedent(f'''\
            #!/bin/sh
            printf '%s\\n' "$0 $*" >> {cls.log}
            exit 97
        ''')
        for name in ('docker', 'sudo', 'apt-get', 'python3', 'node'):
            _script(cls.shims / name, deny)
        _script(cls.guard / 'gh', textwrap.dedent(f'''\
            #!/bin/sh
            if [ "$1" = "--version" ]; then echo "gh version 2.102.0"; exit 0; fi
            if [ "$1" = "auth" ] && [ "$2" = "git-credential" ]; then exit 0; fi
            printf '%s\\n' "$*" >> {called}
            exit 97
        '''))
        cls.addClassCleanup(cls._cleanup)
        cls._setup()

    @classmethod
    def _cleanup(cls):
        cls.tmp.cleanup()
        if getattr(cls, 'fresh_db', None):
            # The helper's drop (lock, terminate, FORCE, checked gone); destroy() accepts throwaway names only.
            test_db._drop(cls.fresh_url, cls.fresh_db)

    @staticmethod
    def _stamp_state(path):
        try:
            return path.stat().st_mtime_ns, path.read_bytes()
        except OSError:
            return None

    @classmethod
    def _child_env(cls, *, tokens=True):
        env = os.environ.copy()
        for name in ('NEON_API_KEY', 'VERCEL_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN'):
            env.pop(name, None)
        env['OU_CREDENTIALS'] = 'network'
        env['OU_SHIM_GUARD'] = str(cls.guard)
        env['OU_PREFLIGHT_STAMP'] = str(cls.stamp)
        env['PATH'] = str(cls.shims) + os.pathsep + env.get('PATH', '')
        # the Origin forge through a stand-in CLI and a sentinel key: the probe never reaches the real Origin API
        origin = cls.shims / 'origin-standin'
        _script(origin, '#!/bin/sh\ncase "$*" in *"/namespaces"*) '
                        'echo \'{"namespaces":[{"namespace":{"type":"user","slug":"tester"}}]}\'; exit 0;; esac\nexit 1\n')
        env[config.get('origin-client.cli_env')] = str(origin)
        env.pop(config.get('origin-client.auth_token_env'), None)
        env[config.get('origin-client.credential_env')] = SENTINEL
        if not tokens:
            env.pop(config.get('origin-client.credential_env'), None)
        return env

    @classmethod
    def _setup(cls):
        env = os.environ.copy()
        for name in ('NEON_API_KEY', 'VERCEL_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN'):
            env.pop(name, None)
        env['PATH'] = str(cls.shims) + os.pathsep + env.get('PATH', '')
        env['OU_CREDENTIALS'] = 'network'
        env['OU_PREFLIGHT_STAMP'] = str(cls.stamp)
        # A fresh machine: this checkout's test database does not exist yet, and setup must create it. Its name is
        # the one env.sh gives a checkout (gate-isolation.sh ou_test_db_name), for a checkout path only this class
        # owns. Not a throwaway name (test_db.new_name): setup.sh creates it, so it has no live owner while it sits
        # idle until its assertion, and every gate on this machine ends with gate_db_sweep, which drops idle
        # throwaway databases on the shared cluster. A checkout's database is never swept.
        port = os.environ.get('OU_POSTGRES_PORT', '54322')
        cls.fresh_db = subprocess.run(
            ['bash', '-c', 'source "$1" && ou_test_db_name "$2"', '_', str(ROOT / 'scripts/lib/gate-isolation.sh'),
             str(cls.work / 'checkout')], capture_output=True, text=True, check=True).stdout.strip()
        cls.fresh_url = f'postgresql://postgres@127.0.0.1:{port}/{cls.fresh_db}'
        env['TEST_DATABASE_URL'] = cls.fresh_url
        env['APP_DATABASE_URL_CONTAINER_UNPOOLED'] = env['TEST_DATABASE_URL']
        cls.claude_env = cls.work / 'claude-env.sh'
        env['CLAUDE_ENV_FILE'] = str(cls.claude_env)
        completed = subprocess.run(
            ['bash', str(ROOT / 'scripts/cloud/setup.sh')], cwd=ROOT, env=hermetic.without_harness(env),
            capture_output=True, text=True, timeout=600, check=False,
        )
        cls.setup_out = completed.stdout + completed.stderr
        if completed.returncode != 0:
            raise RuntimeError('setup failed\n' + cls.setup_out[-2000:])
        # The tripwires below only mean something when env.sh puts the guard first (TX12).
        first = cls._first_on_path(cls._child_env())
        if first != str(cls.guard):
            raise premise_failed(f'scripts/cloud/env.sh does not honor OU_SHIM_GUARD={cls.guard} (PATH starts {first!r})')

    @staticmethod
    def _first_on_path(env):
        shown = subprocess.run(['bash', '-c', 'source scripts/cloud/env.sh && printf %s "${PATH%%:*}"'], cwd=ROOT, env=env,
                               capture_output=True, text=True, check=False,
                               timeout=config.get('env-premises.probe_timeout_s'))
        return shown.stdout if shown.returncode == 0 else shown.stderr.strip()

    def _assert_clean(self, text):
        self.assertNotIn(SENTINEL, text)
        self.assertNotIn('Bearer', text)
        self.assertNotIn('sentinel-secret', text)

    def test_setup_uses_the_toolchain_and_not_root_or_docker(self):
        self.assertIn('postgres', self.setup_out)
        self._assert_clean(self.setup_out)
        self.assertFalse(self.log.exists() and self.log.read_text().strip(), self.log.read_text() if self.log.exists() else '')
        for banned in ('apt-get', 'sudo', 'docker', 'pg_ctlcluster'):
            self.assertNotIn(banned, (ROOT / 'scripts/cloud/setup.sh').read_text())

    def test_setup_writes_the_node_proxy_names_only_behind_a_proxy(self):
        text = self.claude_env.read_text()
        proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
        self.assertEqual('NODE_USE_ENV_PROXY=1' in text, bool(proxy), text)
        self.assertNotIn('HTTPS_PROXY', text.upper())
        if proxy:
            self.assertNotIn(proxy, text)

    def test_setup_creates_the_missing_checkout_database(self):
        listed = test_db._psql(self.fresh_url, f"select 1 from pg_database where datname = '{self.fresh_db}'")
        self.assertEqual(listed, '1', self.fresh_db)

    def test_uid0_gate_checkouts_are_traversable(self):
        env = os.environ.copy()
        env.pop('GATE_CHECKOUT_ROOT', None)
        completed = subprocess.run(
            ['bash', '-c', 'source scripts/cloud/env.sh && printf %s "${GATE_CHECKOUT_ROOT:-}"'],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        if os.geteuid() != 0:
            self.assertEqual(completed.stdout, '')
            return
        # uid 0's ~/.cache is under /root (0700); the unprivileged uids of the script tests must reach the slot.
        path = Path(completed.stdout)
        self.assertEqual(path, Path('/var/tmp/open-university/gate-checkouts'))
        for directory in (path, *path.parents):
            self.assertTrue(directory.stat().st_mode & 0o001, directory)

    def test_shim_guard_is_honored_only_in_a_temporary_directory(self):
        # A $TMPDIR outside /tmp: the gitignored toolchain directory stands in for one. A checkout that itself lives
        # under /tmp (the gate's bypass tree) makes that directory a /tmp one, which env.sh honors by design, so the
        # stand-in then moves to /var/tmp (still not /tmp/*).
        base = self.shared_stamp.parent
        if any(str(path).startswith('/tmp/') for path in (base, base.absolute(), base.resolve())):  # a symlinked .toolchain hides /tmp
            base = Path('/var/tmp')
        temporary = tempfile.TemporaryDirectory(dir=base, prefix='ou-guard-')
        self.addCleanup(temporary.cleanup)
        elsewhere = Path(temporary.name)
        guard = elsewhere / 'guard'
        guard.mkdir()
        env = {key: value for key, value in self._child_env().items() if key != 'TMPDIR'}
        self.assertEqual(self._first_on_path({**env, 'TMPDIR': str(elsewhere), 'OU_SHIM_GUARD': str(guard)}), str(guard))
        self.assertEqual(self._first_on_path({**env, 'TMPDIR': str(elsewhere) + '/', 'OU_SHIM_GUARD': str(guard)}),
                         str(guard))
        self.assertNotEqual(self._first_on_path({**env, 'OU_SHIM_GUARD': str(guard)}), str(guard))
        self.assertNotEqual(self._first_on_path({**env, 'TMPDIR': '/', 'OU_SHIM_GUARD': str(guard)}), str(guard))
        # A directory that is neither under /tmp nor under $TMPDIR (ROOT/scripts would be /tmp/* in the bypass tree).
        sibling = tempfile.TemporaryDirectory(dir=base, prefix='ou-checkout-')
        self.addCleanup(sibling.cleanup)
        checkout = Path(sibling.name)
        self.assertNotEqual(self._first_on_path({**env, 'TMPDIR': str(elsewhere), 'OU_SHIM_GUARD': str(checkout)}),
                            str(checkout))

    def test_preflight_and_gate_lists(self):
        self.stamp.unlink(missing_ok=True)  # a fresh credential probe, on this class's own stamp
        env = self._child_env()
        pre = subprocess.run(['bash', str(ROOT / 'scripts/cloud/preflight')], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(pre.returncode, 0, pre.stderr)
        self.assertIn('preflight: ok', pre.stdout)
        self.assertTrue(self.stamp.is_file())
        # The shared stamp is a cache any other preflight in this checkout may write at any moment (a session in
        # network mode caches its GitHub success there), so its mtime and bytes prove nothing about this run. The
        # proof is this run's own: every stamp read and write goes through credentials._cache_path, which resolves
        # to this class's file, and none of the digests this run wrote (bound to this class's loopback origins,
        # so no other process can produce them) is in the shared file.
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(credentials._cache_path(), self.stamp)
        own = json.loads(self.stamp.read_text())
        self.assertEqual(sorted(own), ['origin'], own)
        shared = self._stamp_state(self.shared_stamp)
        for provider, digest in own.items():
            self.assertNotIn(digest.encode(), shared[1] if shared else b'', provider)
        self._assert_clean(pre.stdout + pre.stderr)
        dev = subprocess.run(['bash', str(ROOT / 'scripts/gate-dev'), '--list'], cwd=ROOT, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(dev.returncode, 0, dev.stderr)
        self.assertIn('secret scan (history)', dev.stdout)  # OU-DECOUPLE F5 (D-113): the dev plan is the engine's
        self.assertNotIn('smoke database', dev.stdout)
        which = subprocess.run(
            ['bash', '-c', 'source scripts/cloud/env.sh && command -v python3 && command -v node && pgtools_start'],
            cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        )
        self.assertEqual(which.returncode, 0, which.stderr)
        lines = [line for line in which.stdout.splitlines() if line.strip()]
        python3 = lines[0]
        if env.get('OU_FORK_SERVER') and python3 == os.path.join(env['OU_FORK_SERVER'], 'bin', 'python3'):
            python3 = env['OU_FORK_SERVER_PYTHON']  # GATE-SPEED F4 (D-122): the client of the toolchain's interpreter
        self.assertTrue(python3.endswith('.toolchain/bin/python3'), lines)
        self.assertTrue(lines[1].endswith('.toolchain/bin/node'), lines)
        self._assert_clean(which.stdout + which.stderr)
        self.assertFalse(self.log.exists() and self.log.read_text().strip())

    def test_origin_identity_uses_the_cli_without_the_retired_tail(self):
        # D-293: the session's forge is Origin; the stand-in CLI answers the public identity probe.
        with patch.dict(os.environ, self._child_env(), clear=True):
            self.assertEqual(forge_origin_client.OriginClient().identity(), 'tester')
        called = self.work / 'gh-called'
        self.assertFalse(called.exists() and called.read_text().strip())
        self.assertFalse(self.log.exists() and self.log.read_text().strip())

    def test_entrypoints_do_not_call_graphql_or_gh_pr(self):
        names = [
            'scripts/gate-dev', 'scripts/gate-local',
            'scripts/cloud/setup.sh', 'scripts/cloud/env.sh', 'scripts/cloud/preflight',
        ]
        for name in names:
            text = (ROOT / name).read_text()
            self.assertNotIn('gh pr', text, name)
            self.assertNotIn('api.github.com/graphql', text, name)
        client = (ROOT / 'scripts/lib/forge_origin_client.py').read_text()
        self.assertNotIn('api.github.com/graphql', client)
        self.assertIn("'api', path", client)


PROXY_NAMES = ('HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'NO_PROXY', 'no_proxy',
               'NODE_USE_ENV_PROXY', 'NODE_OPTIONS')
FETCH = textwrap.dedent('''\
    for (const url of process.argv.slice(2)) {
      try { const response = await fetch(url); console.log(url, response.status, await response.text()) }
      catch (error) { console.log(url, 'failed') }
    }
''')


class _Recorder(BaseHTTPRequestHandler):
    """Fake egress proxy and loopback origin: record each request line, refuse or answer it."""
    def _answer(self):
        self.server.lines.append(self.requestline)
        status, body = self.server.reply
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)

    do_CONNECT = do_GET = _answer

    def log_message(self, *args):
        pass


class _Server6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


class NodeEnvProxyTests(unittest.TestCase):
    """env.sh: Node fetch uses a cloud egress proxy without stderr; loopback and proxy-less hosts are untouched."""
    def _serve(self, cls, host, reply):
        server = cls((host, 0), _Recorder)
        server.lines, server.reply = [], reply
        # shutdown() waits for serve_forever's next poll: 10 ms, not the default 0.5 s, per server per test
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def _env(self, **extra):
        env = {key: value for key, value in os.environ.items() if key not in PROXY_NAMES}
        return {**env, **extra}

    def _fetch(self, env, *urls):
        script = Path(self.tmp.name) / 'fetch.mjs'
        script.write_text(FETCH)
        return subprocess.run(['bash', '-c', 'source scripts/cloud/env.sh && exec node "$0" "$@"', str(script), *urls],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ou-proxy-')
        self.addCleanup(self.tmp.cleanup)
        self.proxy = self._serve(ThreadingHTTPServer, '127.0.0.1', (403, b''))
        self.origin = self._serve(ThreadingHTTPServer, '127.0.0.1', (200, b'direct'))

    def test_fetch_goes_through_the_proxy_silently_and_loopback_stays_direct(self):
        proxy = f'http://127.0.0.1:{self.proxy.server_port}'
        urls = ['https://media.example.test/a', 'http://media.example.test/b',
                f'http://127.0.0.1:{self.origin.server_port}/c']
        try:
            origin6 = self._serve(_Server6, '::1', (200, b'direct'))
            urls.append(f'http://[::1]:{origin6.server_port}/d')
        except OSError:
            origin6 = None
        result = self._fetch(self._env(HTTPS_PROXY=proxy, HTTP_PROXY=proxy, no_proxy='corp.example'), *urls)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stderr, '')
        self.assertEqual(self.proxy.lines, ['CONNECT media.example.test:443 HTTP/1.1',
                                            'CONNECT media.example.test:80 HTTP/1.1'])
        out = result.stdout.splitlines()
        self.assertEqual(out[:2], [f'{urls[0]} failed', f'{urls[1]} failed'])
        self.assertEqual(out[2:], [f'{url} 200 direct' for url in urls[2:]])
        self.assertEqual(self.origin.lines, ['GET /c HTTP/1.1'])
        if origin6:
            self.assertEqual(origin6.lines, ['GET /d HTTP/1.1'])

    def test_lowercase_proxy_and_existing_no_proxy_are_kept(self):
        shown = subprocess.run(
            ['bash', '-c', 'source scripts/cloud/env.sh && source scripts/cloud/env.sh && '
                           'printf "%s\\n" "$NODE_USE_ENV_PROXY" "$NODE_OPTIONS" "$no_proxy" "${NO_PROXY-unset}"'],
            cwd=ROOT, env=self._env(https_proxy='http://127.0.0.1:9', no_proxy='corp.example', NODE_OPTIONS='--use-openssl-ca'),
            capture_output=True, text=True, timeout=60)
        self.assertEqual(shown.stdout.splitlines(), [
            '1', '--use-openssl-ca --disable-warning=UNDICI-EHPA', 'corp.example,localhost,127.0.0.1,::1,[::1]', 'unset'])

    def test_claude_env_file_lines_carry_the_names_and_never_the_proxy_url(self):
        exports = 'source scripts/cloud/env.sh && ou_node_env_proxy_exports'
        proxy = 'http://fixture-user:sentinel-secret@127.0.0.1:9'
        shown = subprocess.run(['bash', '-c', exports], cwd=ROOT, env=self._env(HTTPS_PROXY=proxy, NO_PROXY='corp.example'),
                               capture_output=True, text=True, timeout=60)
        self.assertNotIn('sentinel-secret', shown.stdout + shown.stderr)
        replay = subprocess.run(['env', '-i', 'bash', '-c', shown.stdout + 'printf "%s\\n" "$NODE_USE_ENV_PROXY" "$NODE_OPTIONS" "$NO_PROXY"'],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(replay.stdout.splitlines(), [
            '1', '--disable-warning=UNDICI-EHPA', 'corp.example,localhost,127.0.0.1,::1,[::1]'])
        none = subprocess.run(['bash', '-c', exports], cwd=ROOT, env=self._env(), capture_output=True, text=True, timeout=60)
        self.assertEqual((none.returncode, none.stdout, none.stderr), (0, '', ''))

    def test_without_a_proxy_env_sh_sets_nothing(self):
        shown = subprocess.run(
            ['bash', '-c', 'source scripts/cloud/env.sh && printf "%s\\n" "$NODE_OPTIONS" '
                           '"${NODE_USE_ENV_PROXY-unset}" "${NO_PROXY-unset}" "${no_proxy-unset}"'],
            cwd=ROOT, env=self._env(NODE_OPTIONS='--use-openssl-ca'), capture_output=True, text=True, timeout=60)
        self.assertEqual(shown.stdout.splitlines(), ['--use-openssl-ca', 'unset', 'unset', 'unset'])
        result = self._fetch(self._env(), f'http://127.0.0.1:{self.origin.server_port}/e')
        self.assertEqual((result.stdout, result.stderr), (f'http://127.0.0.1:{self.origin.server_port}/e 200 direct\n', ''))
        self.assertEqual(self.proxy.lines, [])


if __name__ == '__main__':
    unittest.main()
