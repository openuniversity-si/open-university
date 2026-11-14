"""Preflight: toolchain stamp, both credential modes, and a cache that stores no secrets."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import credentials
import hermetic
import preflight
import toolchain_manifest as manifest

# Open University's providers (Neon, Vercel) left the engine (D-105, D-111); preflight never asks for them.
OPEN_UNIVERSITY_NAMES = ('NEON_API_KEY', 'VERCEL_TOKEN', 'TOWER_NEON_PROJECT_ID', 'TOWER_NEON_PRODUCTION_BRANCH',
                         'VERCEL_PROJECT_ID', 'VERCEL_ORG_ID')
SENTINEL = 'sentinel-neon-secret'


def stamp_tools(root):
    bindir = root / 'bin'
    bindir.mkdir(parents=True)
    for tool in manifest.TOOLS:
        (bindir / manifest.binary_name(tool)).write_text('')
    (root / 'install.stamp').write_text(manifest.install_id() + '\n')


def origin_credential_names():
    """The Origin forge's credential names (origin-client.auth_token_env, origin-client.credential_env), never values."""
    import config
    return (config.get('origin-client.auth_token_env'), config.get('origin-client.credential_env'))


def pinned_probe(tool, _root):
    """The version probe of a healthy container: every binary reports its pin (GX-28: the stamp alone never answers)."""
    return manifest.load()[tool]['version']


class ManifestTests(unittest.TestCase):
    def test_every_tool_has_a_checksum_and_the_url_uses_the_manifest_version(self):
        data = manifest.load()
        self.assertEqual(set(data), set(manifest.TOOLS))
        for name, spec in ((name, data[name]) for name in manifest.TOOLS):
            self.assertEqual(set(spec['sha256']), {'x86_64', 'aarch64'})
            for digest in spec['sha256'].values():
                self.assertEqual(len(digest), 64)
                int(digest, 16)
            self.assertIn(spec['version'], manifest.artifact(name, data)['url'])

    def test_version_parser_reads_vendor_banners(self):
        self.assertEqual(manifest.version_of('node', 'v22.23.3\n'), '22.23.3')
        self.assertEqual(manifest.version_of('python', '3.12.15\n'), '3.12.15')
        self.assertEqual(manifest.version_of('postgres', 'psql (PostgreSQL) 18.6\n'), '18.6')


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(OU_TOOLCHAIN_DIR=str(self.root), **hermetic.store_env())

    def test_env_mode_names_every_gap_and_does_not_probe_or_print_a_secret(self):
        self.enterContext(self.selected('origin'))  # D-293: the one forge's gaps and identity probe
        names = origin_credential_names()
        env = {**hermetic.store_env(), 'OU_TOOLCHAIN_DIR': str(self.root), 'NEON_API_KEY': SENTINEL}
        with patch.dict(os.environ, env, clear=True), \
                self.origin_forge(identity=AssertionError('identity probed')) as client:
            found = preflight.problems()
        client.identity.assert_not_called()
        text = '\n'.join(found)
        self.assertIn(f'missing {" or ".join(names)}', text)
        for name in OPEN_UNIVERSITY_NAMES:
            self.assertNotIn(name, text)
        self.assertIn('missing toolchain: python', text)
        self.assertNotIn(SENTINEL, text)
        self.assertNotIn('missing NEON_API_KEY', text)

    def test_invalid_mode_is_named_without_its_value(self):
        env = dict(self.env, OU_CREDENTIALS='not-a-mode-sentinel')
        with patch.dict(os.environ, env, clear=True):
            found = preflight.problems()
        self.assertIn('invalid OU_CREDENTIALS', found)
        self.assertNotIn('not-a-mode-sentinel', '\n'.join(found))

    def test_network_probe_is_cached_and_the_stamp_has_no_secret(self):
        self.enterContext(self.selected('origin'))  # D-293: the one forge's gaps and identity probe
        env = dict(self.env, OU_CREDENTIALS='network', **{origin_credential_names()[-1]: SENTINEL})
        with patch.dict(os.environ, env, clear=True), \
                self.origin_forge(identity='origin-bot') as client:
            self.assertEqual([line for line in preflight.problems() if not line.startswith('missing toolchain:')], [])
            self.assertEqual(client.identity.call_count, 1)
            again = preflight.problems()
        self.assertEqual(client.identity.call_count, 1)
        self.assertTrue(all(line.startswith('missing toolchain:') for line in again))
        stamp = (self.root / 'preflight.stamp').read_text()
        self.assertNotIn(SENTINEL, stamp)
        self.assertNotIn('Bearer', stamp)
        self.assertNotIn('fixture-project', stamp)
        self.assertNotIn('console.neon', stamp)
        json.loads(stamp)

    def test_no_open_university_credential_is_asked_or_probed(self):
        # Only the forge's credential is a gap: with the forge ready, no Neon or Vercel name appears, and the
        # credentials module has no provider probe left to ask (OU-DECOUPLE F4, D-111; D-293)
        import forge_events
        source = Path(credentials.__file__).read_text()
        for name in ('NEON', 'VERCEL', 'probe_json'):
            self.assertNotIn(name, source)
        for selected in ('env', 'network'):
            env = dict(self.env, OU_CREDENTIALS=selected)
            with patch.dict(os.environ, env, clear=True), \
                    patch.object(forge_events, 'forge_gaps', return_value=[]):
                found = preflight.problems()
            text = '\n'.join(found)
            for name in OPEN_UNIVERSITY_NAMES:
                self.assertNotIn(name, text)

    def selected(self, adapter):
        """forge-events.adapter as an operator's switch would set it; every other key keeps its value."""
        import config
        real = config.get
        return patch.object(config, 'get', side_effect=lambda name, *rest: adapter if name == 'forge-events.adapter'
                            else real(name, *rest))

    @contextlib.contextmanager
    def origin_forge(self, identity):
        """The Origin forge on this machine: its CLI, a git remote on a declared Origin host and a client whose identity
        answers `identity` (an exception is raised). The credential is whatever the case's environment holds."""
        import config
        import forge_origin
        import forge_origin_client
        from unittest.mock import MagicMock
        host, repo = 'origin.test', config.get('forge-events.repo')
        refs, client = MagicMock(), MagicMock()
        refs.url.return_value = f'https://{host}/{repo}.git'
        if isinstance(identity, BaseException):
            client.identity.side_effect = identity
        else:
            client.identity.return_value = identity
        real = config.get
        with patch.object(config, 'get', side_effect=lambda name, *rest: [host] if name == 'origin-client.git_hosts'
                          else real(name, *rest)), \
                patch.object(forge_origin, 'GitRefs', return_value=refs), \
                patch.object(forge_origin_client, 'client_from_config', return_value=client), \
                patch.dict(os.environ, {forge_origin_client.settings()['cli_env']: '/fixture/origin'}):
            yield client

    def test_the_forge_gaps_are_the_selected_forges_never_githubs(self):
        # ORIGIN-FINISH R3: with origin selected, no GitHub credential is asked or probed; Origin's own gaps are named
        import forge_origin
        env = dict(self.env, OU_CREDENTIALS='network')
        with patch.dict(os.environ, env, clear=True), self.selected('origin'), \
                patch.object(forge_origin, 'credential_gaps', return_value=['missing origin CLI']) as gaps:
            found = preflight.problems()
        gaps.assert_called_once_with(credentials.cached_probe)
        self.assertIn('missing origin CLI', found)
        self.assertFalse([line for line in found if 'GH_TOKEN' in line or 'GitHub' in line])

    def test_an_unreadable_selector_is_named_and_preflight_goes_on(self):
        import forge_events
        env = dict(self.env, OU_CREDENTIALS='network')
        with patch.dict(os.environ, env, clear=True), \
                patch.object(forge_events, 'forge_gaps', side_effect=RuntimeError('store down\ndetail')):
            found = preflight.problems()
        self.assertIn('forge readiness unknown: RuntimeError: store down', found)

    def test_failed_forge_identity_is_named_even_when_a_credential_is_set(self):
        self.enterContext(self.selected('origin'))  # D-293: the one forge's gaps and identity probe
        import forge_origin_client
        env = dict(self.env, OU_CREDENTIALS='network', **{origin_credential_names()[-1]: 'present-but-unused'})
        with patch.dict(os.environ, env, clear=True), \
                self.origin_forge(identity=forge_origin_client.OriginClientError('refused')):
            found = preflight.problems()
        text = '\n'.join(found)
        self.assertIn('Origin API is not reachable', found)
        self.assertNotIn(f'missing {" or ".join(origin_credential_names())}', found)
        self.assertNotIn('present-but-unused', text)

    def test_down_database_uses_the_connection_line(self):
        bindir = self.root / 'bin'
        bindir.mkdir()
        (bindir / 'psql').write_text('')
        down = 'postgres is not accepting connections on 127.0.0.1:54322'
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(preflight, 'observed_version', return_value='18.6'), \
                patch.object(preflight, '_postgres_status', return_value=down):
            self.assertEqual(preflight.database_problems(), [down])

    def test_f54_no_browser_library_or_font_tool_is_asked(self):
        # The engine launches no browser and nothing reads fc-list: a box without either is ready.
        def which(name):
            return None if name == 'fc-list' else f'/usr/bin/{name}'
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(preflight.shutil, 'which', side_effect=which), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                patch.object(preflight, 'require'):
            self.assertEqual(preflight.host_problems(), [])
            self.assertEqual(preflight.main([]), 0)
        self.assertEqual(out.getvalue(), 'preflight: ok\n')

    def test_missing_host_tool_is_named(self):
        with patch.object(preflight.shutil, 'which', return_value=None):
            self.assertIn('missing host tool: flock', preflight.host_problems())

    def test_unwritable_path_is_named_without_the_os_error(self):
        # Under a regular file no directory can exist, for any uid: chmod alone does not stop root.
        blocker = self.root / 'blocker'
        blocker.write_text('not a directory')
        found = preflight._writable(blocker / 'locked', '.toolchain')
        self.assertEqual(found, ['missing writable path: .toolchain'])
        self.assertNotIn('Permission', '\n'.join(found))

    def test_a_probe_is_not_rerun_while_the_binary_is_unchanged(self):
        stamp_tools(self.root)
        expected = {tool: manifest.load()[tool]['version'] for tool in manifest.TOOLS}
        with patch.dict(os.environ, self.env, clear=True):
            with patch.object(preflight, 'observed_version', side_effect=lambda tool, _root: expected[tool]):
                self.assertEqual(preflight.missing_tools(), [])
            with patch.object(preflight, 'observed_version', side_effect=AssertionError('should not exec')):
                self.assertEqual(preflight.missing_tools(), [])

    def test_gx28_a_matching_stamp_never_answers_for_a_replaced_binary(self):
        stamp_tools(self.root)
        expected = {tool: manifest.load()[tool]['version'] for tool in manifest.TOOLS}
        stale = dict(expected, node='20.0.0')
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(preflight, 'observed_version', side_effect=lambda tool, _root: stale[tool]):
            self.assertEqual(preflight.missing_tools(), ['node'])

    def test_vazao_f6_neither_gh_nor_vercel_is_a_toolchain_gap(self):
        # The engine runs neither CLI (github_cli is REST only; Vercel's production left with Open University, D-111).
        self.assertFalse({'gh', 'vercel'} & set(manifest.TOOLS))
        self.assertFalse({'gh', 'vercel'} & set(manifest.load()))
        stamp_tools(self.root)
        self.assertFalse((self.root / 'bin' / 'gh').exists() or (self.root / 'bin' / 'vercel').exists())
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(preflight, 'observed_version', side_effect=pinned_probe):
            self.assertEqual(preflight.missing_tools(), [])


class GatePreflightTests(unittest.TestCase):
    """GX-01: the gate preflight probes the database and the toolchain, never credentials (F54: no browser)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'toolchain'
        self.env = dict(OU_TOOLCHAIN_DIR=str(self.root), **hermetic.store_env())

    def run_gate(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = preflight.main(['gate', *args])
        return rc, out.getvalue()

    def test_the_default_probes_are_the_registered_set(self):
        import config
        root = manifest.ROOT
        self.assertEqual(config.get('env.gate_preflight_probes', root), ['database', 'toolchain'])
        self.assertEqual(set(preflight.GATE_PROBES), set(config.entry('env.gate_preflight_probes', root)['items']['enum']))

    def test_a_healthy_container_passes(self):
        # The CRITICAL false positive: every leaf probe answers as on a healthy box, and the real probe code says ok.
        stamp_tools(self.root)
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(preflight, 'observed_version', side_effect=pinned_probe), \
                patch.object(preflight, '_postgres_status', return_value=None):
            rc, out = self.run_gate()
        self.assertEqual((rc, out), (0, 'gate preflight: ok\n'))
        self.assertNotEqual(preflight.SETUP_EXIT, 0)

    def test_each_gap_is_one_fail_env_line_and_exit_2(self):
        with patch.dict(os.environ, self.env, clear=True):
            rc, out = self.run_gate()
        lines = out.splitlines()
        self.assertEqual(rc, preflight.SETUP_EXIT)
        self.assertTrue(lines and all(line.startswith('FAIL env: ') for line in lines), out)
        self.assertIn('FAIL env: missing toolchain: node', lines)
        self.assertFalse(any('browser' in line for line in lines), out)
        self.assertEqual(len(lines), len(set(lines)))
        self.assertNotIn('GitHub', out)

    def test_down_database_is_a_gap_and_without_skips_a_probe(self):
        stamp_tools(self.root)
        down = 'postgres is not accepting connections'
        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(preflight, 'observed_version', side_effect=pinned_probe), \
                patch.object(preflight, '_postgres_status', return_value=down):
            self.assertEqual(self.run_gate(), (preflight.SETUP_EXIT, f'FAIL env: {down}\n'))
            self.assertEqual(self.run_gate('--without', 'database'), (0, 'gate preflight: ok\n'))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(preflight.main(['gate', '--without', 'nothing']), preflight.SETUP_EXIT)

    def test_cli_names_a_missing_toolchain(self):
        # The time budget is held by gate-local.test.sh on the real driver (env.gate_preflight_budget_s).
        env = dict(os.environ, **self.env)
        done = subprocess.run([sys.executable, str(Path(preflight.__file__)), 'gate', '--without', 'database'],
                              env=env, capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, preflight.SETUP_EXIT, done.stderr)
        self.assertIn('FAIL env: missing toolchain: node', done.stdout.splitlines())
        self.assertNotIn('FAIL env: missing toolchain: pnpm', done.stdout.splitlines())  # vazão F16: pnpm left


if __name__ == '__main__':
    unittest.main()
