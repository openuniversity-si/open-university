"""Local gate adapter of the CI runner port: runs providers.ci_local_command (scripts/gate-dev) and reads its stages.

The gate writes one <stage>.stage.json per stage (scripts/lib/gate-runner.sh) into GATE_REPORT_DIR, which this
adapter sets; it waits for the process to end (no timeout and no polling, AGENTS.md). The runner is injected so tests
need no gate.
"""
import json
import os
from pathlib import Path
import subprocess

import config
from adapters.ci_runner import GateRun, Stage

ROOT = Path(__file__).resolve().parents[3]


class LocalGateRunner:
    name = 'local'

    def __init__(self, root=ROOT, runner=subprocess.run):
        self.root, self.runner = Path(root), runner
        self.command = config.get('providers.ci_local_command')

    def argv(self, pr):
        return [str(self.root / self.command), '--pr', str(pr)]

    def run(self, pr, report_dir):
        report_dir = Path(report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, GATE_REPORT_DIR=str(report_dir))
        done = self.runner(self.argv(pr), cwd=self.root, env=env)
        return GateRun(self.name, done.returncode, stages(report_dir), str(report_dir))


def stages(report_dir):
    found = []
    for path in sorted(Path(report_dir).glob('*.stage.json')):
        record = json.loads(path.read_text(encoding='utf-8'))
        found.append(Stage(record['name'], int(record['exit']), round(float(record['seconds']) * 1000)))
    return found
