"""forge_events port (D-065, M2): gate evidence (TX24: one file per feature; fixtures in scripts/tests/test_forge_events.py)."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_forge_events import HEAD, NEXT, REPO, ROOT, port  # noqa: E402,F401
import config  # noqa: E402
import config  # noqa: E402
import forge_events  # noqa: E402
import gate_report  # noqa: E402


class GateEvidence(unittest.TestCase):
    """gate_report emits gate.passed/gate.failed and one engine.step.measured per stage (D-065, D-069 item 6)."""

    def logs(self, failing=None):
        logs = Path(tempfile.mkdtemp()) / 'logs'
        logs.mkdir()
        self.addCleanup(shutil.rmtree, logs.parent)
        for name, seconds in (('secret scan (tree)', 0.25), ('unit tests', 3.5)):
            result = 'FAIL' if name == failing else 'PASS'
            safe = ''.join(c if c.isalnum() else '_' for c in name)
            (logs / f'{safe}.stage.json').write_text(json.dumps({'name': name, 'result': result, 'exit': int(result == 'FAIL'),
                                                                 'seconds': seconds}))
            (logs / f'{safe}.log').write_text('AssertionError: expected 2 to be 3' if result == 'FAIL' else 'ok')
        (logs / 'plan.json').write_text(json.dumps({'kind': 'scoped', 'stages': ['secret scan (tree)', 'unit tests']}))
        return logs

    def report(self, logs, rc=0):
        report = {'sha': HEAD, 'result': 'PASS' if rc == 0 else 'FAIL', 'stages': gate_report.stage_results(logs)}
        return report

    def adapter(self):
        return forge_events.MemoryAdapter({(REPO, 7): {'head': HEAD, 'base': NEXT, 'body': 'Premises: P-02, P-34'}})

    def test_pass_is_the_evidence_and_rerun_is_a_no_op(self):
        adapter, logs = self.adapter(), self.logs()
        verdict = gate_report.emit_evidence(self.report(logs), 'dev', 7, logs, port(adapter))
        self.assertEqual(verdict['type'], 'gate.passed')
        self.assertEqual((verdict['payload']['tier'], verdict['payload']['plan'], verdict['payload']['premises']),
                         (1, 'dev', ['P-02', 'P-34']))
        self.assertEqual([s['duration_ms'] for s in verdict['payload']['stages']], [250, 3500])
        log = adapter.logs[(REPO, 7)]
        self.assertEqual([e['type'] for e in log], ['engine.step.measured'] * 2 + ['gate.passed'])
        self.assertEqual([e['payload']['step'] for e in log[:2]], ['gate:secret scan (tree)', 'gate:unit tests'])
        self.assertEqual(adapter.appends, 1, 'one forge write per gate run')
        gate_report.emit_evidence(self.report(logs), 'dev', 7, logs, port(adapter))
        self.assertEqual(adapter.appends, 1, 'the same run re-reported adds nothing')
        state = forge_events.replay(port(adapter).read(REPO, 7))
        self.assertEqual(forge_events.gate_evidence(state, 7, HEAD, 'dev'), verdict['event_id'])

    def test_failure_carries_the_stage_class_and_is_no_evidence(self):
        adapter, logs = self.adapter(), self.logs(failing='unit tests')
        verdict = gate_report.emit_evidence(self.report(logs, rc=1), 'dev', 7, logs, port(adapter))
        self.assertEqual(verdict['type'], 'gate.failed')
        self.assertEqual([s['class'] for s in verdict['payload']['stages']], [None, 'code'])
        self.assertEqual([e['payload']['result'] for e in adapter.logs[(REPO, 7)][:2]], ['ok', 'fail'])
        state = forge_events.replay(port(adapter).read(REPO, 7))
        self.assertIsNone(forge_events.gate_evidence(state, 7, HEAD, 'dev'))

    def test_other_plans_are_not_tier_one(self):
        logs = self.logs()
        verdict = gate_report.emit_evidence(self.report(logs), 'db', 7, logs, port(self.adapter()))
        self.assertEqual((verdict['payload']['tier'], verdict['payload']['plan']), (None, 'db'))

    def test_unrecordable_evidence_fails_the_gate(self):
        logs = self.logs()
        # no forge credential of either adapter: with the Origin key left in, the evidence reached the real repo
        unset = ('GH_TOKEN', 'GITHUB_TOKEN', 'OU_CREDENTIALS', 'OU_GITHUB_API',
                 config.get('origin-client.auth_token_env'), config.get('origin-client.credential_env'))
        env = {key: value for key, value in os.environ.items() if key not in unset}
        run = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'lib' / 'gate_report.py'), str(logs), HEAD, '0',
                              'dev', '7'], env=env, capture_output=True, text=True)
        self.assertEqual(run.returncode, 1)
        self.assertIn('FAIL gate evidence', run.stderr)
        self.assertEqual(json.loads((logs / 'stages.json').read_text())['result'], 'PASS')

    def test_working_tree_gate_records_no_evidence(self):
        logs = self.logs()
        run = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'lib' / 'gate_report.py'), str(logs),
                              'working-tree', '0', 'dev', ''], env=dict(os.environ), capture_output=True, text=True)
        self.assertEqual((run.returncode, run.stdout), (0, ''))


if __name__ == '__main__':
    unittest.main()
