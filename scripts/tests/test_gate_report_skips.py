"""GK1: the report tells a stage skipped by a failed dependency from a stage absent from the run. Hermetic."""
import contextlib
import datetime
import hashlib
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import config  # noqa: E402
import forge_events  # noqa: E402
import gate_report  # noqa: E402
import gate_skips  # noqa: E402
from gate_policy import PLANS  # noqa: E402


def write_stage(logs, name, result='PASS'):
    (logs / f'{gate_skips.slug(name)}.stage.json').write_text(json.dumps(
        {'name': name, 'result': result, 'exit': 0 if result == 'PASS' else 1, 'seconds': 1}))


def run(logs, mode='full'):
    report = {'sha': 'x', 'result': 'PASS', 'stages': gate_report.stage_results(logs)}
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        gate_report.apply_coverage(report, logs, mode, False, True)
    return report, err.getvalue()


class SkipReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.logs = pathlib.Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.expected = list(PLANS['full'])

    def test_every_stage_present_passes(self):
        for name in self.expected:
            write_stage(self.logs, name)
        report, err = run(self.logs)
        self.assertEqual(report['result'], 'PASS')
        self.assertEqual((report['missingStages'], report['skippedStages'], err), ([], [], ''))

    def test_known_defect_stage_adjudicated_to_pass_keeps_later_stage(self):
        # script tests failed on a known defect (the report would adjudicate it PASS); every later stage still ran.
        for name in self.expected:
            write_stage(self.logs, name)
        write_stage(self.logs, 'script tests', 'FAIL')
        report = {'sha': 'x', 'result': 'PASS', 'stages': [dict(s, result='PASS') for s in gate_report.stage_results(self.logs)]}
        gate_report.apply_coverage(report, self.logs, 'full', False, True)
        self.assertEqual((report['result'], report['missingStages']), ('PASS', []))

    def test_guard_skip_is_named_apart_from_missing(self):
        # OU-DECOUPLE F5 (D-113): engine stages stand in for the browser stages and the factory bench of the full plan.
        for name in self.expected:
            if name not in ('script tests', 'shellcheck'):
                write_stage(self.logs, name)
        gate_skips.record(self.logs, 'script tests', 'structure check')
        report, err = run(self.logs)
        self.assertEqual(report['result'], 'FAIL')
        self.assertEqual(report['missingStages'], ['shellcheck'])
        self.assertEqual([item['name'] for item in report['skippedStages']], ['script tests'])
        self.assertIn('skipped by a failed dependency: script tests (skipped: structure check failed)', err)
        self.assertIn('missing gate stages: shellcheck', err)

    def test_genuine_failure_still_fails(self):
        for name in self.expected:
            write_stage(self.logs, name, 'FAIL' if name == 'script tests' else 'PASS')
        report, err = run(self.logs)
        self.assertEqual(report['missingStages'], ['script tests'])
        self.assertEqual(report['result'], 'FAIL')


class AbortReport(unittest.TestCase):
    """GX-01: a driver abort with a PR publishes one gate.failed: the abort stage classed env, every expected stage of
    the mode missing, no known-defect adjudication. The forge is the in-process fake (forge_events.MemoryAdapter)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = pathlib.Path(self.tmp.name) / 'dev-run' / 'logs'
        self.head = hashlib.sha1(b'head').hexdigest()
        self.adapter = forge_events.MemoryAdapter(
            {(config.get('forge-events.repo'), 1): {'head': self.head, 'base': hashlib.sha1(b'base').hexdigest(),
                                                    'body': 'Premises: P-26'}})
        clock = mock.Mock()
        clock.now.return_value = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
        self.port = forge_events.ForgeEvents(self.adapter, clock, 'gate_report', 'run-1')

    def abort(self, mode='dev', pr='1', stage='gate preflight', message='FAIL env: local postgres did not start'):
        gate_report.main(['abort', str(self.logs), stage, '1', message])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(gate_report, 'adjudicate_known_defects') as adjudicate:
            rc = gate_report.main([str(self.logs), self.head, '1', mode, pr], self.port)
        adjudicate.assert_not_called()
        return rc, out.getvalue()

    def test_abort_with_pr_publishes_one_env_gate_failed_with_every_expected_stage_missing(self):
        rc, out = self.abort()
        self.assertEqual(rc, 1)
        events = [event for log in self.adapter.logs.values() for event in log]
        verdicts = [event for event in events if event['type'] in ('gate.failed', 'gate.passed')]
        self.assertEqual([event['type'] for event in verdicts], ['gate.failed'])
        payload = verdicts[0]['payload']
        self.assertEqual(payload['stages'], [{'name': 'gate preflight', 'result': 'FAIL', 'duration_ms': 0, 'class': 'env'}])
        self.assertEqual(sorted(payload['missing_stages']), sorted(PLANS['dev']))
        self.assertEqual((payload['pr'], payload['sha'], payload['plan']), (1, self.head, 'dev'))
        self.assertIn('gate evidence: gate.failed', out)
        report = json.loads((self.logs / 'stages.json').read_text())
        self.assertEqual((report['result'], report['aborted']['stage']), ('FAIL', 'gate preflight'))

    def test_a_later_driver_abort_is_env_too(self):
        self.abort(stage='local database', message='FAIL could not reset the local test database')
        verdict = [event for log in self.adapter.logs.values() for event in log if event['type'] == 'gate.failed'][0]
        self.assertEqual(verdict['payload']['stages'][0]['class'], 'env')

    def test_abort_without_pr_publishes_nothing(self):
        rc, _ = self.abort(pr='')
        self.assertEqual(rc, 1)
        self.assertEqual(self.adapter.appends, 0)
        self.assertEqual(json.loads((self.logs / 'stages.json').read_text())['missingStages'], sorted(PLANS['dev']))


SEAM_STAGES = (('lint', 'PASS', None), ('typecheck', 'PASS', None), ('unit tests', 'FAIL', 'code'))


def seam_events(sha=hashlib.sha1(b'head').hexdigest()):
    """The events gate_report.gate_events must publish for SEAM_STAGES (a failed dev run, each stage one second, with a
    missing and a skipped stage), built here with the shared forge_events builders from the fixture and the registry.
    GX-39 pinned their sha256 once, taken before the gate_proof / gate_adjudicate split; T2 (TX23) computes it, so a new
    stage in the dev plan moves only the verdict's input_hash, which is derived from the plan below."""
    clock = mock.Mock()
    clock.now.return_value = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
    port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), clock, 'gate_report', 'run-1')
    subject = forge_events.subject(config.get('forge-events.repo'), 1, sha, ['P-26'])
    prefix = config.get('forge-events.gate_step_prefix')
    millis = datetime.timedelta(seconds=1) // datetime.timedelta(milliseconds=1)
    steps = [port.build('engine.step.measured', forge_events.step_payload(
        subject, prefix + name, millis, 'ok' if result == 'PASS' else 'fail')) for name, result, _kind in SEAM_STAGES]
    records = [{'name': name, 'result': result, 'duration_ms': millis, 'class': kind} for name, result, kind in SEAM_STAGES]
    inputs = json.dumps([sha, 'dev', list(PLANS['dev'])], separators=(',', ':')).encode()
    verdict = dict(subject, tier=1, plan='dev', stages=records, missing_stages=['e2e', 'a11y'],
                   input_hash=hashlib.sha256(inputs).hexdigest(), failing_tests=[], failing_tests_total=0)
    return steps + [port.build('gate.failed', verdict)]


def seam_digest():
    return hashlib.sha256((json.dumps(seam_events(), indent=1, sort_keys=True, default=str) + '\n').encode()).hexdigest()


class SeamPayload(unittest.TestCase):
    """GX-39: the gate_proof / gate_adjudicate split leaves the v3 verdict and step events byte-identical on SEAM_STAGES.
    BEFORE_SPLIT is the digest of seam_events(), kept as the name test_gate_report_v4 compares its own runs with."""
    BEFORE_SPLIT = seam_digest()

    def test_gate_events_payload_is_identical_on_a_fixture(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs = pathlib.Path(tmp) / 'dev-run' / 'logs'
            logs.mkdir(parents=True)
            for name, result, _kind in SEAM_STAGES:
                (logs / (name.replace(' ', '_') + '.stage.json')).write_text(json.dumps(
                    {'name': name, 'result': result, 'exit': 0 if result == 'PASS' else 1, 'seconds': 1}))
            (logs / 'unit_tests.log').write_text('boom\n')
            sha = hashlib.sha1(b'head').hexdigest()
            adapter = forge_events.MemoryAdapter({(config.get('forge-events.repo'), 1): {
                'head': sha, 'base': hashlib.sha1(b'base').hexdigest(), 'body': 'Premises: P-26'}})
            clock = mock.Mock()
            clock.now.return_value = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
            port = forge_events.ForgeEvents(adapter, clock, 'gate_report', 'run-1')
            report = {'sha': sha, 'result': 'FAIL', 'stages': gate_report.stage_results(logs), 'failingTests': [],
                      'missingStages': ['e2e'], 'skippedStages': [{'name': 'a11y', 'reason': 'x'}]}
            events = gate_report.gate_events(report, 'dev', 1, logs, port, ['P-26'])
        self.assertEqual([event['type'] for event in events], ['engine.step.measured', 'engine.step.measured', 'engine.step.measured', 'gate.failed'])
        self.assertEqual(events, seam_events(sha))
        text = json.dumps(events, indent=1, sort_keys=True, default=str) + '\n'
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), self.BEFORE_SPLIT)
        self.assertNotIn('input_digest', events[-1]['payload'])


if __name__ == '__main__':
    unittest.main()
