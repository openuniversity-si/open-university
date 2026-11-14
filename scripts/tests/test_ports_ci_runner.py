"""The CI runner port and its local gate adapter (D-069 items 7 and 12): a fake gate, no network."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
from adapters import ci_local, ci_runner  # noqa: E402


class FakeGate:
    """Writes the stage records gate-runner.sh writes, into the GATE_REPORT_DIR it is given."""

    def __init__(self, stages, returncode):
        self.stages, self.returncode, self.calls = stages, returncode, []

    def __call__(self, argv, cwd, env):
        self.calls.append((argv, cwd, env))
        for name, code, seconds in self.stages:
            record = {'name': name, 'result': 'PASS' if code == 0 else 'FAIL', 'exit': code, 'seconds': seconds}
            (Path(env['GATE_REPORT_DIR']) / f'{name.replace(" ", "_")}.stage.json').write_text(json.dumps(record))
        return subprocess.CompletedProcess(argv, self.returncode)


class Local(unittest.TestCase):
    def test_runs_the_registry_command_and_reads_every_stage(self):
        gate = FakeGate([('lint', 0, 1.25), ('unit tests', 1, 30.0)], 1)
        with tempfile.TemporaryDirectory() as tmp:
            run = ci_local.LocalGateRunner(ROOT, gate).run(506, Path(tmp) / 'reports')
            argv, cwd, env = gate.calls[0]
        self.assertEqual(argv, [str(ROOT / config.get('providers.ci_local_command')), '--pr', '506'])
        self.assertEqual(cwd, ROOT)
        self.assertEqual(run.runner, 'local')
        self.assertEqual(run.exit, 1)
        self.assertEqual(run.stages, [ci_runner.Stage('lint', 0, 1250), ci_runner.Stage('unit tests', 1, 30000)])
        self.assertFalse(ci_runner.passed(run))

    def test_a_green_gate_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = ci_local.LocalGateRunner(ROOT, FakeGate([('lint', 0, 1.0)], 0)).run(1, tmp)
        self.assertTrue(ci_runner.passed(run))


class Port(unittest.TestCase):
    def test_the_registry_selects_the_local_runner_and_nothing_else(self):
        self.assertEqual(ci_runner.runner().name, config.get('providers.ci_runner'))
        self.assertEqual(config.entry('providers.ci_runner')['enum'], ['local'])
        with self.assertRaises(ci_runner.CIRunnerError):
            ci_runner.runner('github-actions')

    def test_the_port_never_touches_the_runner(self):
        source = (ROOT / 'scripts/lib/adapters/ci_runner.py').read_text()
        self.assertNotIn('subprocess', source)
        self.assertNotIn('gate-dev', source)


if __name__ == '__main__':
    unittest.main(verbosity=1)
