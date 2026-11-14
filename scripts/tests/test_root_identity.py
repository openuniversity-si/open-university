"""The delivery tail's uid assumptions. The real uid-0 process runs once, in test_uid0_probe.py (uid0-probe.test.sh)."""
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import traceback
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(ROOT / 'scripts' / 'cloud'))
import config
import gate_classify
import hermetic
import postgres
import preflight
import session_identity as identity
from machine_premise import MachinePremise, premise_failed

SENTINEL = 'fixture-sentinel-not-printed'
UNPRIVILEGED = 65534


def unprivileged_premises(setpriv, env):
    """The dropped uid re-runs this interpreter on this file: both must be readable by it. An interpreter or checkout
    under a 0700 home (uid 0's default slot under /root, HD1) crashes that child in init_fs_encoding instead."""
    completed = subprocess.run(
        [setpriv, f'--reuid={UNPRIVILEGED}', f'--regid={UNPRIVILEGED}', '--clear-groups',
         sys.executable, '-c', 'import sys; open(sys.argv[1]).close()', str(Path(__file__).resolve())],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
        timeout=config.get('env-premises.probe_timeout_s'),
    )
    if completed.returncode != 0:
        said = (completed.stdout + completed.stderr).strip().splitlines() or ['no output']
        raise premise_failed(f'uid {UNPRIVILEGED} cannot run {sys.executable} on {Path(__file__).resolve()} '
                             f'({said[-1]}); on uid 0 set GATE_CHECKOUT_ROOT (scripts/cloud/env.sh)')


def run_unprivileged(test):
    """Run one test of this file as an unprivileged uid and fail with its output.

    A non-root assertion needs a non-root process, and a cloud session is uid 0:
    there the same test body runs in a child that dropped to uid 65534.
    """
    setpriv = identity.find_tool('setpriv')
    if not setpriv:
        raise premise_failed('missing host tool: setpriv (uid 0 runs the non-root assertions as an unprivileged uid)')
    env = {key: value for key, value in os.environ.items() if not key.startswith(('SUDO_', 'GIT_CONFIG_'))}
    env['HOME'] = '/tmp'
    unprivileged_premises(setpriv, env)
    completed = subprocess.run(
        [setpriv, f'--reuid={UNPRIVILEGED}', f'--regid={UNPRIVILEGED}', '--clear-groups',
         sys.executable, str(Path(__file__).resolve()), f'RootAssumptionTests.{test}'],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180, check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f'{test} failed as uid {UNPRIVILEGED}\n' + (completed.stdout + completed.stderr)[-2000:])
LAUNCH_SUFFIXES = {'.mjs', '.js', '.cjs', '.ts', '.tsx'}


def _python_sources():
    for path in (ROOT / 'scripts').rglob('*.py'):
        if 'tests' in path.parts:
            continue
        yield path


def _launch_sources():
    # OU-DECOUPLE F5 (D-113): the engine's own sources, scripts and services; the web build outputs left with Open University.
    roots = [ROOT / 'scripts', ROOT / 'services']
    skipped = {'node_modules'}
    for base in roots:
        for path in base.rglob('*'):
            if path.suffix not in LAUNCH_SUFFIXES or skipped.intersection(path.parts):
                continue
            yield path


class RootAssumptionTests(unittest.TestCase):
    def test_static_guards_cover_the_class(self):
        setup = (ROOT / 'scripts/cloud/setup.sh').read_text()
        for banned in ('apt-get', 'sudo', 'docker', 'pg_ctlcluster'):
            self.assertNotIn(banned, setup)
        self.assertIn('root-session.sh', setup)
        self.assertIn('chmod 666', setup)
        postgres_text = (ROOT / 'scripts/cloud/postgres.py').read_text()
        self.assertIn('as_service=True', postgres_text)
        self.assertIn("identity.open_lock(str(lock_path))", postgres_text)
        self.assertIn("cloud.postgres_lock_path", postgres_text)
        for path in _python_sources():
            text = path.read_text()
            if path.name == 'toolchain.py':
                self.assertEqual(text.count('initdb'), 0, path)
                self.assertIn("config.get('cloud.postgres_binaries')", text)
                self.assertEqual(json.loads((ROOT / 'config/registry/cloud.json').read_text())
                                 ['properties']['cloud.postgres_binaries']['default'].count('initdb'), 1)
            elif path.name != 'postgres.py':
                self.assertNotRegex(text, r"""['"]initdb['"]""", path)
            self.assertNotRegex(text, r"""open\(['"]/tmp/""")
        for relative in ('scripts/gate-local',):  # OU-DECOUPLE F5 (D-113): scripts/lib/gate-fixed.sh left
            text = (ROOT / relative).read_text()
            self.assertNotRegex(text, r'flock /tmp/tower-(e2e|perf).lock', relative)
        # OU-DECOUPLE F4 (D-111): the Playwright config, chromium-args.mjs and the capture scripts left with Open
        # University; a Chromium launch that comes back under scripts/ still has to handle uid 0.
        seen = []
        for path in _launch_sources():
            text = path.read_text()
            if 'chromium.launch' not in text:
                continue
            seen.append(path.relative_to(ROOT).as_posix())
            handled = 'chromiumArgs' in text or ('process.getuid()' in text and '--no-sandbox' in text)
            self.assertTrue(handled, path)

    def test_non_root_does_not_drop_share_or_rewrite_the_environment(self):
        if os.geteuid() == 0:
            run_unprivileged('test_non_root_does_not_drop_share_or_rewrite_the_environment')
            return
        self.assertFalse(identity.running_as_root())
        self.assertEqual(identity.missing_drop_tools(), [])
        self.assertEqual(identity.service_user_problem(), [])
        self.assertEqual(identity.root_environment(), {})
        self.assertEqual(identity.format_exports({}), '')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'bin' / 'tool'
            binary.parent.mkdir()
            binary.write_text('#!/bin/sh\n')
            binary.chmod(0o700)
            identity.share_toolchain(root)
            self.assertEqual(stat.S_IMODE(binary.stat().st_mode), 0o700)
            lock = root / 'lock'
            fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
            os.chmod(lock, 0o600)
            with identity.open_lock(lock):
                pass
            self.assertEqual(stat.S_IMODE(lock.stat().st_mode), 0o600)
            shared = Path('/tmp') / f'ou-lock-share-{os.getpid()}'
            self.addCleanup(lambda: shared.unlink(missing_ok=True))
            descriptor = os.open(shared, os.O_CREAT | os.O_RDWR, 0o644)
            os.close(descriptor)
            os.chmod(shared, 0o644)
            with identity.open_lock(shared):
                pass
            self.assertEqual(stat.S_IMODE(shared.stat().st_mode), 0o666)
            identity.prepare_lock(shared)
            self.assertEqual(stat.S_IMODE(shared.stat().st_mode), 0o666)
            private = root / 'private.lock'
            identity.prepare_lock(private)
            self.assertFalse(private.exists())
            data = root / 'pgdata'
            data.mkdir()
            (data / 'postgresql.conf').write_text('# conf\n')
            previous = os.environ.pop('OU_POSTGRES_PORT', None)
            try:
                postgres._configure(data)
            finally:
                if previous is not None:
                    os.environ['OU_POSTGRES_PORT'] = previous
            extra = (data / 'open-university.conf').read_text()
            self.assertEqual(
                extra,
                f"listen_addresses = '127.0.0.1'\nport = 54322\nunix_socket_directories = '{data}'\n",
            )
            self.assertNotIn('unix_socket_permissions', extra)

    def test_passwd_fallback_is_idempotent_and_not_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            passwd = root / 'passwd'
            group = root / 'group'
            passwd.write_text('root:x:0:0:root:/root:/bin/bash\n')
            group.write_text('root:x:0:\n')
            home = root / 'home'
            # TX12: the id range is a bootstrap registry read, so an empty config cache and no token never decide it.
            unreachable = identity.config.StoreUnavailable('the id range read the change store')
            with patch.object(identity.config, '_overrides', side_effect=unreachable) as store:
                identity.add_system_user('ou-postgres', home, passwd, group)
                identity.add_system_user('ou-postgres', home, passwd, group)
            self.assertEqual(store.call_count, 0)
            lines = [line for line in passwd.read_text().splitlines() if line.startswith('ou-postgres:')]
            self.assertEqual(len(lines), 1)
            uid = int(lines[0].split(':')[2])
            self.assertGreaterEqual(uid, 100)
            self.assertNotEqual(uid, 0)
            self.assertIn(f'ou-postgres:x:{uid}:', group.read_text())
            moved = root / 'moved-home'
            identity.set_passwd_home('ou-postgres', moved, passwd)
            rewritten = [line for line in passwd.read_text().splitlines() if line.startswith('ou-postgres:')]
            self.assertEqual(rewritten[0].split(':')[5], str(moved))
            self.assertEqual(rewritten[0].split(':')[2], str(uid))

    def test_traversable_adds_only_the_search_bit_to_owned_ancestors(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'home'
            tool = home / 'checkout' / '.toolchain' / 'bin' / 'initdb'
            tool.parent.mkdir(parents=True)
            tool.write_text('#!/bin/sh\n')
            home.chmod(0o700)
            identity.traversable(tool)
            self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o701)
            identity.traversable(tool)
            self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o701)

    def test_drop_argv_prefers_runuser_then_su_then_setpriv(self):
        def only(name):
            def find(tool):
                return f'/usr/bin/{name}' if tool == name else None
            return find

        with patch.object(identity, 'find_tool', side_effect=only('runuser')):
            argv, env = identity.command_as('ou-postgres', ['/bin/initdb', '-D', 'data'])
        self.assertEqual(argv, ['/usr/bin/runuser', '-u', 'ou-postgres', '--', '/bin/initdb', '-D', 'data'])
        self.assertIsNone(env)
        with patch.object(identity, 'find_tool', side_effect=only('su')):
            argv, env = identity.command_as('ou-postgres', ['/bin/initdb', '--username', 'postgres'])
        self.assertEqual(argv[:6], ['/usr/bin/su', '-s', '/bin/sh', 'ou-postgres', '-c', 'exec "$0" "$@"'])
        self.assertEqual(argv[6:], ['--', '/bin/initdb', '--username', 'postgres'])
        self.assertIsNone(env)

        class Record:
            pw_gid = 65534
            pw_dir = '/tmp/ou-home'

        with patch.object(identity, 'find_tool', side_effect=only('setpriv')), \
                patch.object(identity.pwd, 'getpwnam', return_value=Record()), \
                patch.object(identity.grp, 'getgrgid') as group:
            group.return_value.gr_name = 'nogroup'
            argv, env = identity.command_as('ou-postgres', ['/bin/initdb'])
        self.assertEqual(argv[0], '/usr/bin/setpriv')
        self.assertIn('--reuid=ou-postgres', argv)
        self.assertIn('--regid=nogroup', argv)
        self.assertEqual(env['HOME'], '/tmp/ou-home')
        self.assertEqual(env['USER'], 'ou-postgres')
        with patch.object(identity, 'find_tool', return_value=None):
            with self.assertRaises(identity.IdentityError) as raised:
                identity.command_as('ou-postgres', ['/bin/initdb'])
        for name in identity.DROP_TOOLS:
            self.assertIn(f'missing host tool: {name}', str(raised.exception))

    def test_root_environment_names_git_npm_and_xdg_without_secrets(self):
        environ = {'HOME': '/tmp', 'SECRET': SENTINEL, 'GIT_CONFIG_COUNT': '0'}
        with patch.object(identity, 'running_as_root', return_value=True), \
                patch.object(identity, '_writable', return_value=True), \
                patch.object(identity, '_owned_by_root', return_value=True), \
                patch.object(identity.os, 'chmod'), \
                patch.object(Path, 'mkdir'):
            values = identity.root_environment(environ)
        text = identity.format_exports(values)
        self.assertEqual(values['npm_config_unsafe_perm'], 'true')
        self.assertEqual(values['npm_config_confirm_modules_purge'], 'false')
        self.assertNotIn('CI', values)
        self.assertEqual(values['GIT_CONFIG_KEY_0'], 'safe.directory')
        self.assertEqual(values['GIT_CONFIG_VALUE_0'], '*')
        self.assertNotIn('HOME', values)
        self.assertIn('XDG_RUNTIME_DIR', values)
        foreign = {'HOME': '/home/not-root'}

        class Foreign:
            st_uid = 1000

        with patch.object(identity, 'running_as_root', return_value=True), \
                patch.object(identity, '_writable', return_value=True), \
                patch.object(Path, 'stat', return_value=Foreign()), \
                patch.object(identity.os, 'chmod'), \
                patch.object(Path, 'mkdir'):
            moved = identity.root_environment(foreign)
        self.assertEqual(moved['HOME'], '/root')
        self.assertEqual(moved['XDG_STATE_HOME'], '/root/.local/state')
        self.assertNotIn(SENTINEL, text)
        self.assertNotIn('SECRET', text)

    def test_root_preflight_lists_every_blocker_in_one_pass(self):
        env = {**hermetic.store_env(), 'OU_TOOLCHAIN_DIR': str(self._empty())}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(identity, 'running_as_root', return_value=True), \
                patch.object(identity, 'find_tool', return_value=None), \
                patch.object(identity.os, 'access', return_value=False), \
                patch.object(identity.pwd, 'getpwnam', side_effect=KeyError), \
                patch.object(preflight.shutil, 'which', return_value=None):
            found = preflight.problems()
        for line in (
            'missing CURSOR_AUTH_TOKEN or CURSOR_API_KEY', 'missing toolchain: python',
            'missing host tool: flock', 'missing host tool: git', 'missing host tool: curl',
            'missing host tool: runuser', 'missing host tool: su', 'missing host tool: setpriv',
            'missing host tool: useradd',
        ):
            self.assertIn(line, found, found)
        self.assertNotIn(SENTINEL, '\n'.join(found))

    def test_a_missing_machine_premise_is_classified_env(self):
        stderr = io.StringIO()
        with patch.object(identity, 'find_tool', return_value=None), patch.object(sys, 'stderr', stderr):
            with self.assertRaises(MachinePremise) as raised:
                run_unprivileged('test_static_guards_cover_the_class')
        self.assertNotIsInstance(raised.exception, AssertionError)
        lines = [line for line in stderr.getvalue().splitlines() if line.startswith('FAIL env: ')]
        self.assertEqual(lines, ['FAIL env: missing host tool: setpriv (uid 0 runs the non-root assertions as an '
                                 'unprivileged uid)'])
        log = stderr.getvalue() + ''.join(traceback.format_exception(raised.exception))
        self.assertEqual(gate_classify.classify('script tests', log), 'env')

    def _empty(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name


if __name__ == '__main__':
    unittest.main()
