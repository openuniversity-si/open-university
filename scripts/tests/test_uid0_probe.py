"""The uid-0 tail path, run once as a real uid-0 process (I-986a5daf): postgres, git and npm, not a mock of geteuid.

It lived twice, in root-identity and claude-session, whose covers are wide; here it runs once, under covers that name
only what the probe loads (VAZÃO F51)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config
import hermetic
import session_identity as identity
from machine_premise import premise_failed

SENTINEL = 'fixture-sentinel-not-printed'
PROBE_TIMEOUT_S = 180


def ensure_toolchain():
    """The pinned toolchain is a machine premise. A gate's slot checkout has none yet, so setup.sh installs it; when
    that fails (network, disk) the premise does not hold: env, never this file's code."""
    binary = ROOT / '.toolchain' / 'bin' / 'initdb'
    if binary.is_file():
        return
    completed = subprocess.run(
        ['bash', str(ROOT / 'scripts/cloud/setup.sh')], cwd=ROOT, env=hermetic.without_harness(os.environ),
        capture_output=True, text=True, timeout=600, check=False,
    )
    if completed.returncode != 0 or not binary.is_file():
        said = (completed.stdout + completed.stderr)
        print(said[-2000:], file=sys.stderr)
        last = said.strip().splitlines() or ['no output']
        raise premise_failed(f'missing toolchain: scripts/cloud/setup.sh did not install {binary.relative_to(ROOT)} '
                             f'({last[-1]})')


def ensure_sudo():
    """Not root: the uid 0 probe needs a password-less sudo."""
    sudo = shutil.which('sudo')
    usable = sudo and subprocess.run([sudo, '-n', 'true'], capture_output=True, check=False,
                                     timeout=config.get('env-premises.probe_timeout_s')).returncode == 0
    if not usable:
        raise premise_failed('the uid 0 probe needs root or a password-less sudo -n (none here)')


def run_uid0_probe():
    """Run root_probe.py as uid 0 with a sentinel secret in the parent environment. Returns the probe's printed text
    and its parsed report. Raises AssertionError when the probe fails."""
    ensure_toolchain()
    # Publish the shared lock as the session uid. The probe runs as uid 0, and
    # that uid cannot chmod a 0644 file this session already created.
    with identity.open_lock('/tmp/open-university-postgres.lock'):
        pass
    probe = ROOT / 'scripts/tests/root_probe.py'
    env = {
        'OU_REPO': str(ROOT),
        'OU_REAL_TOOLCHAIN': str(ROOT / '.toolchain'),
        'PATH': os.environ.get('PATH', ''),
        'HOME': '/root',
        **hermetic.store_env(),  # TX12: named on the sudo env line, so the reset environment keeps the local store
    }
    parent = os.environ.copy()
    parent['OU_SENTINEL'] = SENTINEL
    if os.geteuid() == 0:
        command = [sys.executable, str(probe)]
        parent.update(env)
        parent.pop('GIT_CONFIG_COUNT', None)
    else:
        ensure_sudo()
        command = ['sudo', '-n', 'env', *[f'{key}={value}' for key, value in env.items()], sys.executable, str(probe)]
    completed = subprocess.run(command, cwd=ROOT, env=parent, capture_output=True, text=True,
                               timeout=PROBE_TIMEOUT_S, check=False)
    text = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise AssertionError(f'uid 0 probe failed ({completed.returncode})\n' + text[-2000:])
    return text, json.loads(completed.stdout.strip().splitlines()[-1])


class Uid0ProbeTests(unittest.TestCase):
    def test_uid0_probe_runs_postgres_git_and_npm(self):
        text, report = run_uid0_probe()
        for secret in (SENTINEL, 'Bearer', 'sentinel-secret'):
            self.assertNotIn(secret, text, 'the probe printed a secret')
        # The server runs as the dropped uid, never 0; npm's lifecycle script still runs as uid 0.
        self.assertNotEqual(report['uid'], 0, report)
        self.assertEqual(report['server_uid'], report['uid'], report)
        self.assertEqual(report['npm_uid'], '0', report)
        self.assertIn(report['drop'], identity.DROP_TOOLS)
        self.assertEqual(report['git'], 'safe.directory')
        self.assertEqual(report['lock'], '0666')


if __name__ == '__main__':
    unittest.main()
