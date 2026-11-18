"""The cloud machine setup (engine-cloud, U4). Hermetic: no network, no server started, no download; every expected
value is read from the registry (config.get) or compared with the registry's declared readers.
"""
import json
import os
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(ROOT / 'scripts' / 'cloud'))
import config  # noqa: E402
import config_check  # noqa: E402
import postgres  # noqa: E402
import toolchain  # noqa: E402

REGISTRY = json.loads((ROOT / 'config/registry/cloud.json').read_text())['properties']


class RegistryTests(unittest.TestCase):
    def test_every_declared_reader_spells_the_name(self):
        for name, item in REGISTRY.items():
            for reader in item['x-readers']:
                self.assertIn(name, (ROOT / reader).read_text(), f'{reader} does not read {name}')

    def test_every_read_in_the_unit_is_registered(self):
        import re
        for path in sorted(p for p in (ROOT / 'scripts/cloud').iterdir() if p.suffix in ('.py', '.sh')):
            for name in re.findall(r"\bcloud\.(?!json\b)([a-z_]+)\b", path.read_text()):
                self.assertIn(f'cloud.{name}', REGISTRY, f'{path.name} reads unregistered cloud.{name}')

    def test_no_registered_value_is_a_literal_in_the_unit(self):
        params = config._load()
        names = config_check.Names(params)
        for path in sorted(p for p in (ROOT / 'scripts/cloud').iterdir() if p.is_file()):
            relative = path.relative_to(ROOT).as_posix()
            text = path.read_text()
            if path.suffix == '.py':
                found = config_check.python_findings(relative, text, names, params)
            elif path.suffix == '.sh' or path.name == 'preflight':
                found = config_check.text_findings(relative, text, names, shell=True)
            else:
                continue
            self.assertEqual(found, [], relative)


def run_bash(script, cwd, **extra):
    """`bash -c script` in cwd, with this environment minus what env.sh derives or branches on, plus `extra`."""
    env = {key: value for key, value in os.environ.items()
           if key not in ('TEST_DATABASE_URL', 'APP_DATABASE_URL_CONTAINER_UNPOOLED', 'OU_POSTGRES_PORT', 'NODE_USE_ENV_PROXY',
                          'NODE_OPTIONS', 'NO_PROXY', 'no_proxy', 'HTTPS_PROXY', 'https_proxy', 'GATE_CHECKOUT_ROOT')}
    env.update(extra)
    return subprocess.run(['bash', '-c', script], cwd=cwd, env=env, capture_output=True, text=True, timeout=60, check=False)


class EnvShellTests(unittest.TestCase):
    def source(self, **extra):
        script = 'source scripts/cloud/env.sh; printf "%s\\n%s\\n%s\\n" "$TEST_DATABASE_URL" "$NODE_OPTIONS" "$NO_PROXY"'
        done = run_bash(script, ROOT, **extra)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.splitlines()

    def test_database_url_follows_the_registry_and_the_port_override(self):
        host, port = config.get('cloud.postgres_host'), config.get('cloud.postgres_port')
        self.assertTrue(self.source()[0].startswith(f'postgresql://postgres@{host}:{port}/'))
        self.assertTrue(self.source(OU_POSTGRES_PORT='6543')[0].startswith(f'postgresql://postgres@{host}:6543/'))

    def test_proxy_defaults_come_from_the_registry_and_are_applied_once(self):
        url, options, no_proxy = self.source(HTTPS_PROXY='http://proxy.invalid:1')
        self.assertIn('--disable-warning=' + config.get('cloud.proxy_silenced_warning'), options)
        for host in config.get('cloud.proxy_direct_hosts'):
            self.assertIn(host, no_proxy.split(','))
        _, again, _ = self.source(HTTPS_PROXY='http://proxy.invalid:1', NODE_USE_ENV_PROXY='1', NODE_OPTIONS=options)
        self.assertEqual(again, options)

    def test_an_origin_cli_off_path_is_appended_from_the_registry_dirs(self):
        # F81: a fresh lane shell without ~/.local/bin on PATH; env.sh appends the first listed dir holding the CLI.
        with tempfile.TemporaryDirectory() as home:
            folder = Path(config.get('origin-client.cli_dirs')[0].replace('~', home, 1))
            folder.mkdir(parents=True)
            (folder / config.get('origin-client.cli')).write_text('#!/bin/sh\n')
            (folder / config.get('origin-client.cli')).chmod(0o755)
            bare = os.pathsep.join(p for p in os.environ['PATH'].split(os.pathsep)
                                   if not (Path(p) / config.get('origin-client.cli')).exists())
            script = 'source scripts/cloud/env.sh; command -v ' + config.get('origin-client.cli')
            done = run_bash(script, ROOT, HOME=home, PATH=bare, OU_ROOT_SESSION='1', TEST_DATABASE_URL='given',
                            GATE_CHECKOUT_ROOT='given')
            self.assertEqual((done.returncode, done.stdout.strip()), (0, str(folder / config.get('origin-client.cli'))),
                             done.stderr)


# NANO-UNBLOCK (D-070): config.py's one reason line (exit 1) while GitHub rate-limits the shared change store.
REASON = ('config: the change store cannot be read (gh: exit 429 (rate-limited); GitHub write budget or limit asks to '
          'wait 976 s, more than github-client.max_wait_s (120 s))')
# The stub config.py: run, it fails with REASON; imported (setup.sh's Python check), it answers from VALUES.
STUB = '''import sys

VALUES = {values!r}


def get(name):
    return VALUES[name]


if __name__ == "__main__":
    sys.exit({reason!r})
'''


class FailedRegistryReadTests(unittest.TestCase):
    """A registry read that fails stops env.sh and setup.sh with one classified FAIL env: line that carries config.py's
    reason: no traceback, no unbound variable. Copies of the scripts run in temporary trees against the stub."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        name = 'cloud.bootstrap_python_minimum'  # setup.sh's Python check imports config and reads it
        stub = STUB.format(values={name: config.entry(name)['default']}, reason=REASON)
        cls.env_tree, cls.setup_tree = Path(tmp.name, 'env'), Path(tmp.name, 'setup')
        for tree, copies in ((cls.env_tree, ('scripts/cloud/env.sh', 'scripts/cloud/root-session.sh',
                                             'scripts/cloud/test-db.sh')),
                             (cls.setup_tree, ('scripts/cloud/setup.sh', 'scripts/cloud/root-session.sh'))):
            for folder in ('scripts/cloud', 'scripts/lib'):
                (tree / folder).mkdir(parents=True)
            for relative in copies:
                shutil.copy2(ROOT / relative, tree / relative)
            (tree / 'scripts/lib/config.py').write_text(stub)
        # setup.sh finds its root with git. The env.sh tree is no repository, so env.sh installs no push guard there.
        subprocess.run(['git', 'init', '-q', str(cls.setup_tree)], check=True)

    def source(self, **extra):
        # A nounset shell prints the status the source returned; one killed by an unbound variable prints nothing.
        # OU_ROOT_SESSION skips root-session.sh's identity probe.
        return run_bash('set -u; source scripts/cloud/env.sh; echo "source: $?"', self.env_tree, OU_ROOT_SESSION='1',
                        **extra)

    def assertOneFailLine(self, done, script, *names):
        self.assertNotIn('unbound variable', done.stderr)
        self.assertNotIn('Traceback', done.stderr)
        lines = done.stderr.splitlines()
        self.assertEqual(len(lines), 1, done.stderr)
        self.assertTrue(lines[0].startswith(f'FAIL env: {script} '), lines[0])
        for expected in (*names, REASON):
            self.assertIn(expected, lines[0])

    def test_env_sh_stops_on_the_database_settings(self):
        done = self.source()
        self.assertOneFailLine(done, 'scripts/cloud/env.sh', 'cloud.postgres_host', 'cloud.postgres_port')
        self.assertEqual(done.stdout, 'source: 1\n')

    def test_env_sh_behind_a_proxy_stops_on_the_proxy_settings(self):
        done = self.source(HTTPS_PROXY='proxy.invalid')  # any value takes the branch; the stub fails before it is used
        self.assertOneFailLine(done, 'scripts/cloud/env.sh', 'cloud.proxy_direct_hosts', 'cloud.proxy_silenced_warning')
        self.assertEqual(done.stdout, 'source: 1\n')

    def test_env_sh_reads_the_root_checkout_root_only_as_root(self):
        done = self.source(TEST_DATABASE_URL='given')  # the database branch reads nothing
        if os.geteuid() == 0:
            self.assertOneFailLine(done, 'scripts/cloud/env.sh', 'cloud.root_gate_checkout_root')
            self.assertEqual(done.stdout, 'source: 1\n')
        else:
            self.assertEqual((done.stdout, done.stderr), ('source: 0\n', ''))

    def test_setup_sh_takes_the_hosts_own_python_before_paths(self):
        # The runner's image on AWS (04/11) has its Python only at /usr/local/bin; a PATH python3 can be a shim
        text = (ROOT / 'scripts/cloud/setup.sh').read_text(encoding='utf-8')
        order = [text.index(needle) for needle in ('for candidate in /usr/bin/python3 /usr/local/bin/python3; do',
                                                   'command -v python3 >/dev/null 2>&1 && python_ok python3')]
        self.assertEqual(order, sorted(order))

    def test_setup_sh_refuses_like_a_missing_host_tool(self):
        done = run_bash('bash scripts/cloud/setup.sh; echo "setup.sh: $?"', self.setup_tree, OU_ROOT_SESSION='1')
        self.assertOneFailLine(done, 'scripts/cloud/setup.sh', 'cloud.setup_lock_path', 'cloud.setup_log_path',
                               'cloud.setup_log_tail_lines', 'cloud.postgres_host', 'cloud.postgres_port')
        self.assertEqual(done.stdout, 'setup.sh: 2\n')  # exit 2, the status of its other environment refusals


class PostgresTests(unittest.TestCase):
    def test_port_follows_the_environment_then_the_registry(self):
        with mock.patch.dict(os.environ, {'OU_POSTGRES_PORT': '6543'}):
            self.assertEqual(postgres._port(), 6543)
        for bad in ('', 'x', '0', '70000'):
            with mock.patch.dict(os.environ, {'OU_POSTGRES_PORT': bad}):
                self.assertEqual(postgres._port(), config.get('cloud.postgres_port'))

    def test_down_message_names_the_registered_address(self):
        with mock.patch.dict(os.environ, {'OU_POSTGRES_PORT': ''}):
            self.assertEqual(postgres._down(), 'postgres is not accepting connections on '
                             f"{config.get('cloud.postgres_host')}:{config.get('cloud.postgres_port')}")

    def test_cluster_configuration_uses_registered_values(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(postgres.identity, 'running_as_root', return_value=False):
            data = Path(tmp)
            (data / 'postgresql.conf').write_text('')
            postgres._configure(data)
            body = (data / 'open-university.conf').read_text()
        self.assertIn(f"listen_addresses = '{config.get('cloud.postgres_host')}'", body)
        self.assertIn(f"port = {postgres._port()}", body)

    def test_tail_is_cut_at_the_registered_length(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'log'
            log.write_text('x' * (config.get('cloud.postgres_log_tail_chars') + 50) + '\n')
            self.assertEqual(len(postgres._tail(log)), config.get('cloud.postgres_log_tail_chars'))

    def test_probe_uses_the_registered_timeout_and_role(self):
        seen = {}

        def fake(argv, **kwargs):
            seen.update(kwargs, argv=argv)
            return mock.Mock(returncode=0, stdout='1\n')

        with mock.patch.object(postgres.subprocess, 'run', fake), mock.patch.object(postgres, '_bin', lambda name: name):
            self.assertEqual(postgres._psql('postgres', 'select 1'), '1')
        self.assertEqual(seen['timeout'], config.get('cloud.postgres_query_timeout_s'))
        self.assertIn(config.get('cloud.postgres_role'), seen['argv'])
        self.assertEqual(seen['env']['PGCLIENTENCODING'], config.get('cloud.postgres_encoding'))

    def test_a_cluster_whose_server_started_before_this_boot_is_discarded_and_made_again(self):
        """CACHE-PGDATA: tower/gate's actions/cache restored a running cluster of another runner (run 43606632818):
        its pid file predates this boot, so it is a copy or a crash's, never a live server's, and setup starts afresh."""
        boot = postgres._boot_time()
        self.assertIsNotNone(boot)  # Linux: /proc/stat names the boot
        for started, kept in ((boot - 3600, False), (boot + 5, True)):
            with self.subTest(kept=kept), tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.dict(os.environ, {'OU_TOOLCHAIN_DIR': tmp}):
                root = Path(tmp)
                (root / 'bin').mkdir()
                (root / 'bin' / 'psql').write_text('')
                data = root / 'pgdata'
                data.mkdir()
                (data / 'PG_VERSION').write_text('18\n')
                (data / 'postmaster.pid').write_text(f'2305\n{data}\n{started}\n54322\n')
                (root / 'postgres.log').write_text('07:54:48 UTC [2305] LOG:  checkpoint complete\n')
                (root / 'pgsocket').mkdir()
                (root / 'pgsocket' / '.s.PGSQL.54322.lock').write_text('2305\n')
                made = []

                def initdb(args, log=None, **kwargs):
                    made.append(args[0])
                    (data / 'PG_VERSION').write_text('18\n')
                    return mock.Mock(returncode=0)

                with mock.patch.object(postgres, '_database_up', return_value=False), \
                        mock.patch.object(postgres, '_psql', return_value=None), \
                        mock.patch.object(postgres.identity, 'share_toolchain'), \
                        mock.patch.object(postgres, '_service', return_value=None), \
                        mock.patch.object(postgres, '_bin', lambda name: name), \
                        mock.patch.object(postgres, '_run', initdb), \
                        mock.patch.object(postgres, '_configure'), \
                        mock.patch.object(postgres, '_start'), mock.patch.object(postgres, '_ensure_database'):
                    postgres._ensure()
                self.assertEqual((data / 'postmaster.pid').exists(), kept)
                self.assertEqual((root / 'pgsocket' / '.s.PGSQL.54322.lock').exists(), kept)
                self.assertEqual('07:54:48' in (root / 'postgres.log').read_text(), kept)
                self.assertEqual(made, [] if kept else ['initdb'])

    def test_an_unreadable_pid_file_or_boot_is_not_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            self.assertFalse(postgres._stale(data, boot=10 ** 12))  # no pid file: a clean shutdown
            (data / 'postmaster.pid').write_text('2305\n')
            self.assertFalse(postgres._stale(data, boot=10 ** 12))
            (data / 'postmaster.pid').write_text(f'2305\n{data}\n100\n')
            self.assertTrue(postgres._stale(data, boot=200))
            self.assertIsNone(postgres._boot_time(data / 'missing'))
            with mock.patch.object(postgres, '_boot_time', return_value=None):
                self.assertFalse(postgres._stale(data))

    def test_a_missing_lock_directory_is_named(self):
        with mock.patch.object(postgres.identity, 'open_lock', side_effect=OSError):
            self.assertEqual(postgres.status(),
                             f"missing writable path: {Path(config.get('cloud.postgres_lock_path')).parent}")


class SharedSetupTests(unittest.TestCase):
    """CHECK-USER-SHARED: setup.sh run by the runner's uid 0 and by the check user (tower-check) on one task: the /tmp log
    root made is not the check user's to truncate (0644; and O_CREAT on another user's file in sticky /tmp is refused under
    fs.protected_regular, root included). The full run as tower-check of 13/11 16:17 UTC: `setup.sh: line 101:
    /tmp/open-university-cloud-setup.log: Permission denied` in claude-session and runner-env."""

    def test_a_log_another_uid_made_leaves_this_uid_its_own(self):
        if os.geteuid() != 0:
            self.skipTest('two uids need a root test, as the runner is')
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        shared, tree = tmp / 'tmp', tmp / 'tree'
        shared.mkdir()
        shared.chmod(0o1777)  # a /tmp of its own: world-writable and sticky
        for folder in ('scripts/cloud', 'scripts/lib'):
            (tree / folder).mkdir(parents=True)
        for relative in ('scripts/cloud/setup.sh', 'scripts/cloud/root-session.sh'):
            shutil.copy2(ROOT / relative, tree / relative)
        names = ('cloud.bootstrap_python_minimum', 'cloud.setup_lock_path', 'cloud.setup_log_path',
                 'cloud.setup_log_tail_lines', 'cloud.postgres_host', 'cloud.postgres_port')
        values = {name: config.entry(name)['default'] for name in names}
        values.update({'cloud.setup_lock_path': str(shared / 'setup.lock'), 'cloud.setup_log_path': str(shared / 'setup.log')})
        (tree / 'scripts/lib/config.py').write_text(
            f'import json, sys\nVALUES = {values!r}\n\n\ndef get(name):\n    return VALUES[name]\n\n\n'
            'if __name__ == "__main__":\n    print(json.dumps({name: VALUES[name] for name in sys.argv[2:]}))\n')
        subprocess.run(['git', 'init', '-q', str(tree)], check=True)
        os.chmod(tmp, 0o755)
        subprocess.run(['chown', '-R', f'{_uid("nobody")}:{_group("nogroup") or _group("nobody")}', str(tree)], check=True)  # hand_over
        (shared / 'setup.log').write_text('root was here\n')  # root's, 0644, as a root run of setup.sh leaves it
        trusted = dict(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='safe.directory', GIT_CONFIG_VALUE_0='*')
        done = subprocess.run(['bash', str(tree / 'scripts/cloud/setup.sh')], cwd=tree, capture_output=True, text=True,
                              timeout=60, check=False, user='nobody', group='nogroup' if _group('nogroup') else 'nobody',
                              extra_groups=[], env={'PATH': os.environ['PATH'], 'HOME': str(tmp), **trusted})
        self.assertNotIn('Permission denied', done.stderr)
        self.assertIn('toolchain.py', done.stderr)  # it went on to the next step, the tree's missing installer
        own = shared / f'setup.{_uid("nobody")}.log'
        self.assertTrue(own.is_file() and os.stat(own).st_uid == _uid('nobody'), sorted(p.name for p in shared.iterdir()))
        self.assertEqual((shared / 'setup.log').read_text(), 'root was here\n')  # root's log untouched


def _uid(name):
    import pwd
    return pwd.getpwnam(name).pw_uid


def _group(name):
    import grp
    try:
        return grp.getgrnam(name).gr_gid
    except KeyError:
        return None


class ToolchainTests(unittest.TestCase):
    def test_download_streams_in_registered_chunks_with_the_registered_agent(self):
        sizes, seen = [], {}

        class Response:
            data = [b'ab', b'']

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, size):
                sizes.append(size)
                return self.data.pop(0)

        def fake(request, timeout):
            seen.update(agent=request.get_header('User-agent'), timeout=timeout)
            return Response()

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(toolchain, 'urlopen', fake):
            dest = Path(tmp) / 'out'
            toolchain._download('https://example.invalid/x', dest)
            self.assertEqual(dest.read_bytes(), b'ab')
        self.assertEqual(sizes, [config.get('cloud.download_chunk_bytes')] * 2)
        self.assertEqual(seen, {'agent': config.get('cloud.download_user_agent'), 'timeout': config.get('cloud.download_timeout_s')})

    def test_checksum_reads_in_registered_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'blob'
            path.write_bytes(b'x' * (config.get('cloud.download_chunk_bytes') + 1))
            import hashlib
            self.assertEqual(toolchain._sha256(path), hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
