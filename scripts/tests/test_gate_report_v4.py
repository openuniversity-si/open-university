"""GX-10 (D-070, GA-P01): the gate produces gate.passed|failed v4 with the proof binding. A verifier recomputes
input_digest from git and the toolchain manifest alone; gate-proof.event_version=3 keeps today's v3 payload byte for byte;
GX-09's readers accept the produced event. Hermetic: a temp git repo and the in-process forge (MemoryAdapter)."""
import contextlib
import datetime
import hashlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))

import config  # noqa: E402
import event_contracts  # noqa: E402
import forge_events  # noqa: E402
import gate_digest  # noqa: E402
import gate_proof  # noqa: E402
import gate_report  # noqa: E402
import pr_ready  # noqa: E402
import slo  # noqa: E402
import toolchain_manifest  # noqa: E402
from test_plan_tick import FIXED  # noqa: E402
import test_gate_report_skips  # noqa: E402 - GX-39's v3 digest of its fixture (a module import: no TestCase rerun here)

PR = 1
REPO = config.get('forge-events.repo')
STARTED = FIXED.timestamp()  # the shared fixed clock
V4 = gate_proof.proof_version()
V3 = config.entry('gate-contracts.gate_passed_version')['default']  # the registry pin: today's v3


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout.strip()


def commit(root, path, text):
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    (root / path).write_text(text)
    git(root, 'add', '-A')
    git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', path)
    return git(root, 'rev-parse', 'HEAD')


def clock():
    moment = mock.Mock()
    moment.now.return_value = datetime.datetime.fromtimestamp(0, datetime.timezone.utc)
    return moment


def stage(logs, name, result='PASS', **extra):
    (logs / (name.replace(' ', '_') + '.stage.json')).write_text(json.dumps(
        dict({'name': name, 'result': result, 'exit': 0 if result == 'PASS' else 1, 'seconds': 1}, **extra)))


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = pathlib.Path(tmp.name) / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q')
        self.base = commit(self.repo, 'scripts/gate', 'v1\n')
        self.head = commit(self.repo, 'products/demo/a.ts', 'x\n')
        self.logs = pathlib.Path(tmp.name) / 'dev-run' / 'logs'
        self.logs.mkdir(parents=True)
        stage(self.logs, 'lint', started_at=STARTED)
        stage(self.logs, 'typecheck', started_at=STARTED + 1, cached=True)
        (self.logs / 'selection.json').write_text(json.dumps({'kind': 'scoped', 'units': ['web-build']}))
        self.adapter = forge_events.MemoryAdapter({(REPO, PR): {'head': self.head, 'base': self.base,
                                                                'body': 'Premises: P-42'}})
        self.port = forge_events.ForgeEvents(self.adapter, clock(), config.get('forge-events.gate_producer'), 'gate:dev:run')

    def binding(self, plan='dev'):
        return gate_proof.bind(self.repo, self.repo, self.head, self.base, plan, pid=os.getpid())

    def events(self, binding, version=V4, result='PASS', report=None):
        report = report or {'sha': self.head, 'result': result, 'stages': gate_report.stage_results(self.logs),
                            'failingTests': []}
        environ = {gate_proof.ENV: json.dumps(binding)} if binding else {}
        with mock.patch.dict(os.environ, environ), mock.patch.object(gate_proof, 'event_version', return_value=version), \
                contextlib.redirect_stderr(io.StringIO()):
            return gate_report.gate_events(report, 'dev', PR, self.logs, self.port, ['P-42'])


class V4Producer(Fixture):
    def test_the_verdict_is_v4_and_validates_against_the_locked_contract(self):
        for result, kind in (('PASS', 'gate.passed'), ('FAIL', 'gate.failed')):
            with self.subTest(kind=kind):
                verdict = self.events(self.binding(), result=result)[-1]
                self.assertEqual((verdict['type'], verdict['version']), (kind, V4))
                event_contracts.validate(verdict, event_contracts.registry())
                payload = verdict['payload']
                self.assertEqual((payload['sha'], payload['base_sha'], payload['tier']), (self.head, self.base, 1))
                self.assertEqual(payload['selection']['kind'], 'scoped')
                self.assertEqual(payload['selection']['units'], ['web-build'])
                lint, typecheck = payload['stages']
                moment = datetime.datetime.fromisoformat(lint['started_at'].replace('Z', '+00:00')).timestamp()
                self.assertAlmostEqual(moment, STARTED, places=len('ms'))
                self.assertEqual((lint['cached'], typecheck['cached']), (False, True))
                self.assertEqual(set(payload['cost']), {'wall_s', 'cpu_s', 'rest_calls', 'queue_wait_s', 'cache_hits',
                                                        'cache_misses'})
                self.assertEqual((payload['cost']['cache_hits'], payload['cost']['cache_misses']), (1, 1))

    def test_a_verifier_recomputes_input_digest_from_git_and_the_toolchain_manifest_alone(self):
        payload = self.events(self.binding())[-1]['payload']
        head_tree = git(self.repo, 'rev-parse', f'{payload["sha"]}^{{tree}}')
        selection = gate_proof.selection_digest(payload['plan'])
        attested = toolchain_manifest.attestation()
        recomputed = gate_digest.input_digest(head_tree, payload['base_sha'], payload['plan'], selection,
                                              attested['toolchain_id'], git(self.repo, 'rev-parse', 'HEAD:scripts'))
        self.assertEqual(recomputed, payload['input_digest'])
        self.assertEqual(payload['toolchain_id'], attested['toolchain_id'])
        self.assertEqual(payload['observed_versions'], attested['observed_versions'])
        self.assertEqual(list(payload['observed_versions']), config.get('toolchain.observed_tools'))
        self.assertEqual(payload['selection']['digest'], selection)
        self.assertEqual(payload['head_tree'], head_tree)
        self.assertEqual(payload['base_tree'], git(self.repo, 'rev-parse', f'{self.base}^{{tree}}'))

    def test_gx28_the_proof_and_the_cache_keys_carry_one_attested_toolchain_id(self):
        import gate_keys
        gate_keys.reset()
        self.addCleanup(gate_keys.reset)
        with mock.patch.dict(os.environ, {gate_keys.ENV: ''}):  # this process attests, not the enclosing gate run (D-082)
            self.assertEqual(self.binding()['toolchain_id'], gate_keys.key_parts()[1])

    def test_gx28_an_unattested_toolchain_is_not_bound(self):
        import gate_keys
        gate_keys.reset()
        self.addCleanup(gate_keys.reset)
        with mock.patch('toolchain_manifest.attestation', side_effect=OSError('no toolchain')):
            with self.assertRaisesRegex(RuntimeError, 'toolchain not attested'):
                self.binding()

    def test_binding_and_export_attest_once_and_share_the_toolchain(self):
        import gate_keys
        gate_keys.reset()
        self.addCleanup(gate_keys.reset)
        keys_file = self.repo / 'key-parts.json'
        output = io.StringIO()
        with mock.patch('toolchain_manifest.attestation', wraps=toolchain_manifest.attestation) as attestation, \
                contextlib.redirect_stdout(output):
            code = gate_proof.main(['bind', '--src-root', str(self.repo), '--tool-root', str(ROOT),
                                    '--sha', self.head, '--base', self.base, '--plan', 'dev',
                                    '--key-parts-file', str(keys_file)])
        self.assertEqual(code, 0)
        self.assertEqual(attestation.call_count, 1)
        binding = json.loads(output.getvalue().splitlines()[0])
        snapshot = json.loads(keys_file.read_text())
        self.assertEqual(snapshot['parts'][1], binding['toolchain_id'])
        self.assertEqual(snapshot['root'], str(ROOT))

    def test_the_pass_record_extras_carry_the_same_binding(self):
        out = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/gate_proof.py'), 'bind', '--src-root', str(self.repo),
                              '--tool-root', str(self.repo), '--sha', self.head, '--base', self.base, '--plan', 'dev'],
                             capture_output=True, text=True, check=True).stdout.splitlines()
        binding = json.loads(out[0])
        extras = dict(line.split('=', 1) for line in out[1:])
        self.assertEqual(list(extras), ['head_tree', 'base_sha', 'gate_version', 'toolchain_id', 'input_digest'])
        self.assertEqual(extras, {key: binding[key] for key in extras})
        self.assertEqual(extras['input_digest'], self.events(binding)[-1]['payload']['input_digest'])

    def test_the_proof_binds_the_wall_clock_start_not_the_monotonic_one(self):
        """GATE-SPEED: gate-local's budget start is monotonic; the proof's cost compares the start with epoch ms, so the
        hook passes gate_started_epoch when the driver has it (wall_s and queue_wait_s were about 1.79e9 s)."""
        script = ('source "$1"; py="$2" tool_root="$3" src_root="$4" sha="$5" base="$6" mode=dev plan_file="" '
                  'gate_started=1 gate_started_epoch=7 OU_GATE_PASS_EXTRA=""; gate_hook_proof; printenv OU_GATE_PROOF')
        hook = ROOT / 'scripts/lib/gate-hooks/proof.sh'
        out = subprocess.run(['bash', '-c', script, 'hook', str(hook), sys.executable, str(ROOT), str(self.repo), self.head,
                              self.base], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out)['started_ms'], int('7'))
        script = ('GATE_CEILING_MS=1; source "$1"; before=$EPOCHREALTIME; actual=$(gate_epoch_ms); '
                  'after=$EPOCHREALTIME; printf "%s %s %s" "$before" "$actual" "$after"')
        before, actual, after = subprocess.run(
            ['bash', '-c', script, 'clock', str(ROOT / 'scripts/lib/gate-budget.sh')],
            capture_output=True, text=True, check=True).stdout.split()
        self.assertGreaterEqual(int(actual), int(float(before) * 1000) - 1)
        self.assertLessEqual(int(actual), int(float(after) * 1000) + 1)

    def test_the_proof_hook_exports_the_binding_and_the_pass_extras(self):
        script = ('source "$1"; py="$2" tool_root="$3" src_root="$4" sha="$5" base="$6" mode=dev plan_file="" '
                  'gate_started=1 OU_GATE_PASS_EXTRA=""; gate_hook_proof; '
                  'printf "%s\\n--\\n%s\\n--\\n%s\\n" "$OU_GATE_VERSION" "$OU_GATE_PASS_EXTRA" "$(printenv OU_GATE_PROOF)"')
        hook = ROOT / 'scripts/lib/gate-hooks/proof.sh'
        out = subprocess.run(['bash', '-c', script, 'hook', str(hook), sys.executable, str(ROOT), str(self.repo), self.head, self.base],
                             capture_output=True, text=True, check=True).stdout.split('--\n')
        version, extras, binding = out
        version, extras, binding = version.strip(), extras.strip(), json.loads(binding)
        self.assertEqual(version, git(ROOT, 'rev-parse', 'HEAD:scripts'))  # the tooling that runs the hook
        self.assertEqual(extras, gate_proof.pass_extra(binding))
        self.assertEqual((binding['sha'], binding['base_sha'], binding['started_ms']), (self.head, self.base, 1))
        unbound = subprocess.run(['bash', '-c', script, 'hook', str(hook), sys.executable, str(ROOT), str(self.repo), self.head, ''],
                                 capture_output=True, text=True, check=True).stdout
        self.assertEqual(unbound, '\n--\n\n--\n\n')

    def test_an_unbindable_run_says_why_and_exits_1(self):
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/lib/gate_proof.py'), 'bind', '--src-root', str(self.repo),
                               '--tool-root', str(self.repo), '--sha', self.head, '--base', '', '--plan', 'dev'],
                              capture_output=True, text=True)
        self.assertEqual((done.returncode, done.stdout), (1, ''))
        self.assertIn('gate proof: not bound', done.stderr)

    def test_gx09_readers_accept_the_produced_event(self):
        events = self.events(self.binding())
        self.port.publish(events)
        session = forge_events.ForgeEvents(self.adapter, clock(), config.get('plan-tick.event_producer'), f'pr-{PR}')
        ready = pr_ready.emit_ready(session, REPO, PR, self.head, ['P-42'], 'dev', None)
        self.assertEqual(ready['payload']['evidence'], events[-1]['event_id'])
        [tier1] = slo.fold(session.read(REPO, PR))['tier1']
        self.assertEqual((tier1['event_id'], tier1['passed']), (events[-1]['event_id'], True))


class V3Unchanged(Fixture):
    """The switch at 3, or a run the proof cannot bind, keeps GX-39's v3 payload byte for byte."""

    def seam_fixture(self):
        logs = self.logs.parent.parent / 'seam' / 'logs'
        logs.mkdir(parents=True)
        for name, result in (('lint', 'PASS'), ('typecheck', 'PASS'), ('unit tests', 'FAIL')):
            stage(logs, name, result)
        (logs / 'unit_tests.log').write_text('boom\n')
        sha = hashlib.sha1(b'head').hexdigest()
        adapter = forge_events.MemoryAdapter({(REPO, 1): {'head': sha, 'base': hashlib.sha1(b'base').hexdigest(),
                                                          'body': 'Premises: P-26'}})
        port = forge_events.ForgeEvents(adapter, clock(), 'gate_report', 'run-1')
        report = {'sha': sha, 'result': 'FAIL', 'stages': gate_report.stage_results(logs), 'failingTests': [],
                  'missingStages': ['e2e'], 'skippedStages': [{'name': 'a11y', 'reason': 'x'}]}
        return sha, logs, port, report

    def digest(self, version, bound):
        sha, logs, port, report = self.seam_fixture()
        binding = dict(self.binding(), sha=sha) if bound else None
        environ = {gate_proof.ENV: json.dumps(binding)} if binding else {gate_proof.ENV: ''}
        with mock.patch.dict(os.environ, environ), mock.patch.object(gate_proof, 'event_version', return_value=version), \
                contextlib.redirect_stderr(io.StringIO()):
            events = gate_report.gate_events(report, 'dev', 1, logs, port, ['P-26'])
        text = json.dumps(events, indent=1, sort_keys=True, default=str) + '\n'
        return hashlib.sha256(text.encode()).hexdigest(), events[-1]

    def test_switch_3_is_byte_identical_to_v3_even_when_bound(self):
        digest, verdict = self.digest(V3, bound=True)
        self.assertEqual(digest, test_gate_report_skips.SeamPayload.BEFORE_SPLIT)
        self.assertNotIn('input_digest', verdict['payload'])

    def test_an_unbound_run_keeps_v3_under_switch_4(self):
        digest, _ = self.digest(V4, bound=False)
        self.assertEqual(digest, test_gate_report_skips.SeamPayload.BEFORE_SPLIT)

    def test_a_binding_of_another_commit_is_not_used(self):
        verdict = self.events(dict(self.binding(), sha=self.base))[-1]
        self.assertEqual(verdict['version'], V3)
        self.assertNotIn('input_digest', verdict['payload'])

    def test_the_registry_default_is_4(self):
        self.assertEqual(config.entry('gate-proof.event_version')['default'], V4)


class MetadataObservation(unittest.TestCase):
    def test_only_this_pr_and_head_can_reuse_the_fresh_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'pr-snapshot.json'
            change = {'head': 'a' * 40, 'base': 'b' * 40, 'body': 'freshly checked plan'}
            path.write_text(json.dumps({'pr': PR, 'sha': change['head'], 'change': change}))
            self.assertEqual(gate_report.observed_change(directory, PR, change['head']), change)
            self.assertIsNone(gate_report.observed_change(directory, PR + 1, change['head']))
            self.assertIsNone(gate_report.observed_change(directory, PR, change['base']))
            path.write_text('{invalid')
            self.assertIsNone(gate_report.observed_change(directory, PR, change['head']))


if __name__ == '__main__':
    unittest.main()
