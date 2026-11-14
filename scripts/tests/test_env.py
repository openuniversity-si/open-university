"""env-check's pinned toolchain and early stop (D-027, F13). Fixture binaries; no network."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import env_manifest  # noqa: E402
import gate_classify  # noqa: E402
import toolchain_manifest as manifest  # noqa: E402

SHELL = shutil.which('sh')


def fixture(root, changed=None):
    """Each installed tool answers its registered pin; a fixture needs no package or update policy."""
    binaries = root / '.toolchain/bin'
    binaries.mkdir(parents=True)
    for tool, version in {**manifest.versions(), **(changed or {})}.items():
        prefix = 'v' if tool == 'node' else 'psql (PostgreSQL) ' if tool == 'postgres' else ''
        binary = binaries / manifest.binary_name(tool)
        binary.write_text(f'#!{SHELL}\necho "{prefix}{version}"\n')
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)


class EnvCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def run_check(self):
        return subprocess.run(['bash', str(ROOT / 'scripts/env-check'), '--root', str(self.root)],
                              capture_output=True, text=True)

    def test_a_matching_toolchain_needs_no_package_or_environment_policy(self):
        fixture(self.root)
        self.assertEqual(env_manifest.check(self.root), ([], []))
        done = self.run_check()
        self.assertEqual((done.returncode, done.stdout), (0, 'env-check: environment matches the manifest\n'))

    def test_the_repository_manifest_contains_only_toolchain_checksums(self):
        self.assertEqual(set(json.loads(manifest.MANIFEST.read_text())), set(manifest.TOOLS))

    def test_toolchain_drift_names_the_tool_actual_version_pin_and_setup(self):
        fixture(self.root, {'node': '0.0.0'})
        errors, warnings = env_manifest.check(self.root)
        self.assertEqual(warnings, [])
        self.assertEqual(errors, [f'env: toolchain node is 0.0.0, registry {manifest.versions()["node"]}; '
                                  'run bash scripts/cloud/setup.sh'])
        done = self.run_check()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertIn('FAIL ' + errors[0], done.stdout)
        self.assertIn('update the registry versions and their checksums in an env PR', done.stdout)
        self.assertNotIn('env-update', done.stdout)

    def test_every_missing_binary_is_reported(self):
        fixture(self.root)
        for tool in manifest.TOOLS:
            (self.root / '.toolchain/bin' / manifest.binary_name(tool)).unlink()
        errors, warnings = env_manifest.check(self.root)
        self.assertEqual(warnings, [])
        self.assertEqual(errors, [f'env: toolchain {tool} is missing, registry {manifest.versions()[tool]}; '
                                  'run bash scripts/cloud/setup.sh' for tool in manifest.TOOLS])

    def test_a_broken_binary_is_reported_as_missing(self):
        fixture(self.root)
        (self.root / '.toolchain/bin/node').write_text(f'#!{SHELL}\nexit 1\n')
        errors, _ = env_manifest.check(self.root)
        self.assertEqual(len(errors), 1)
        self.assertIn('toolchain node is missing', errors[0])

    def test_an_uninstalled_toolchain_keeps_the_setup_warning(self):
        done = self.run_check()
        self.assertEqual((done.returncode, done.stdout),
                         (0, f'WARN env: no toolchain in {self.root / ".toolchain"}; '
                          'run bash scripts/cloud/setup.sh\nenv-check: environment matches the manifest\n'))

    def test_the_repository_probe_honors_the_toolchain_directory_override(self):
        fixture(self.root)
        with mock.patch.dict('os.environ', {'OU_TOOLCHAIN_DIR': str(self.root / '.toolchain')}):
            self.assertEqual(env_manifest.check(), ([], []))

    def test_an_unreadable_toolchain_pin_is_an_actionable_failure(self):
        out = io.StringIO()
        with mock.patch.object(env_manifest, 'check', side_effect=RuntimeError('toolchain: missing checksum')):
            with redirect_stdout(out):
                self.assertEqual(env_manifest.main([]), 1)
        self.assertIn('FAIL env: toolchain: missing checksum', out.getvalue())
        self.assertIn('bash scripts/cloud/setup.sh', out.getvalue())

    def test_idea_to_prod_stops_on_toolchain_drift_before_reading_prs(self):
        fixture(self.root, {'node': '0.0.0'})
        done = subprocess.run(['bash', str(ROOT / 'scripts/idea-to-prod'), '--root', str(self.root),
                               '--prs', str(self.root / 'not-read.json')], capture_output=True, text=True)
        self.assertEqual(done.returncode, 3, done.stdout + done.stderr)
        self.assertIn('FAIL env: toolchain node is 0.0.0', done.stdout)
        self.assertIn('stopped before the PR starts; do the env-fix PR first (D-027)', done.stderr)

    def test_env_gate_guidance_names_the_existing_setup_and_toolchain_pr(self):
        line = gate_classify.line('gate preflight', 'FAIL env: missing toolchain: node')
        self.assertIn('class: env', line)
        self.assertIn('bash scripts/cloud/setup.sh', line)
        self.assertIn('env patch PR', line)
        self.assertIn('toolchain pins', line)
        self.assertNotIn('env-update', line)

    def test_a_sixty_second_fixed_cost_parses(self):
        import idea_to_prod
        goal = idea_to_prod.target('\n## Target\nfixed-cost: ≤60s\nmarginal: <1h\n')
        self.assertEqual(goal['fixed-cost'].total_seconds(), 60)
        self.assertEqual(goal['marginal'].total_seconds(), 3600)


if __name__ == '__main__':
    unittest.main(verbosity=1)
