"""D-293: what one gate run costs Origin, measured at its client boundary.

The script-tests stage (the durations read and the one record of every timed test) makes no GitHub call at all; a whole
run (panel begin, stage edits, the 80 tests, the verdict append, the final panel and status) stays within
gate.forge_writes_per_run_max writes and gate.forge_reads_per_run_max reads, the same for 1 test as for 80; the journal does not spend forge requests. Every test value lives in
scripts/tests/fixtures/gate-forge-budget.json (LT1)."""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
os.environ.setdefault('OU_CONFIG_STORE', 'file')

import config  # noqa: E402
import forge_events  # noqa: E402
from test_gate_status import FakeOrigin, origin_adapter  # noqa: E402
import gate_status  # noqa: E402
import gate_test_cache  # noqa: E402

F = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'gate-forge-budget.json').read_text())
REPO, SHA, PR = F['repo'], F['sha'], F['pr']




class Fixed:
    def now(self):
        return datetime.fromisoformat(F['verdict_at'])


class Forge(unittest.TestCase):
    """An independent Origin client and this case directory replace the real forge and journal."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        class MeasuredOrigin(FakeOrigin):
            def publish_check_run(self, repo, sha, *args):
                self._call('POST', f'{repo}/checks/{sha}')
                return super().publish_check_run(repo, sha, *args)
        self.forge = MeasuredOrigin()
        real = config.get
        pinned = {'gate.status_enabled': True, 'origin-client.git_hosts': [FakeOrigin.HOST]}
        self.enterContext(mock.patch.object(config, 'get', side_effect=lambda name, *args, **kwargs:
                                           pinned[name] if name in pinned else real(name, *args, **kwargs)))
        adapter = origin_adapter(self.forge, forge_events.FileAdapter(self.dir / 'events'))
        self.enterContext(mock.patch.object(forge_events, 'adapter_from_config', return_value=adapter))
        self.enterContext(mock.patch.dict(forge_events.CLOCKS, {config.get('forge-events.clock'): Fixed}))

    def lines(self, name):
        methods = {'reads': ('GET',), 'content-writes': ('POST', 'PATCH')}
        return [f'{method} {path}' for method, path in self.forge.calls if method in methods.get(name, ())]

    def calls(self):
        return self.lines('reads') + self.lines('content-writes')


class ScriptTestsStage(Forge):
    def test_eighty_timed_tests_make_no_github_call(self):
        timed = [(f'scripts/tests/t{n}.test.sh', F['timed_base_ms'] + n, True) for n in range(F['timed_tests'])]
        self.assertEqual(gate_test_cache.measured_durations(), {})
        gate_test_cache.record_durations(timed, SHA)
        found = gate_test_cache.measured_durations()
        print(f"script-tests stage, {F['timed_tests']} tests: forge calls {self.calls()}", file=sys.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(len(found), F['timed_tests'])

    def test_a_kind_that_lives_on_the_journal_reaches_it_once_and_never_github(self):
        port = forge_events.ForgeEvents(forge_events.adapter_from_config(), Fixed(), 'gate_report', 'run-1')
        fields = forge_events.subject(REPO, PR, SHA, ['P-42'])
        verdict = port.build('gate.passed', dict(fields, tier=1, plan='dev', missing_stages=[], input_hash=F['digest'],
                                                 stages=[{'name': 'lint', 'result': 'PASS',
                                                          'duration_ms': F['stage_ms'], 'class': None}]))
        steps = [port.build('engine.step.measured', forge_events.step_payload(fields, f'gate:{name}', F['stage_ms'], 'ok'))
                 for name in F['stages']]
        port.publish([verdict] + steps)
        # CANALE7: the verdict reaches the journal once, and the journal is not GitHub: no forge write at all
        self.assertEqual(self.lines('content-writes'), [])
        self.assertEqual([event['type'] for event in port.read(REPO, PR)].count('gate.passed'), 1)


class WholeRun(Forge):
    """The run's forge path in order: panel begin, a start and an end edit per stage, the timed script tests, the
    verdict append, the final panel and status."""

    def run_gate(self, tests):
        start = len(self.forge.calls)
        logs = self.dir / f'logs-{tests}'
        logs.mkdir()
        (logs / 'plan.json').write_text(json.dumps({'kind': 'scoped', 'stages': F['stages']}))
        now = F['now']
        gate_status.begin(logs, SHA, PR, 'dev', self.dir, now=now)
        for name in F['stages']:
            gate_status.stage_event(logs, name, False, now=now)
            if name == 'script tests':
                gate_test_cache.measured_durations()
                gate_test_cache.record_durations(
                    [(f'scripts/tests/t{n}.test.sh', F['timed_base_ms'] + n, True) for n in range(tests)], SHA)
            (logs / f'{gate_status.slug(name)}.stage.json').write_text(json.dumps(
                {'name': name, 'result': 'PASS', 'exit': 0, 'seconds': 1.0}))
            gate_status.stage_event(logs, name, True, now=now)
        port = forge_events.ForgeEvents(forge_events.adapter_from_config(), Fixed(), 'gate_report', 'run-1')
        fields = forge_events.subject(REPO, PR, SHA, ['P-42'])
        events = port.publish([port.build('gate.passed', dict(
            fields, tier=1, plan='dev', missing_stages=[], input_hash=F['digest'],
            stages=[{'name': name, 'result': 'PASS', 'duration_ms': F['stage_ms'], 'class': None} for name in F['stages']]))])
        gate_status.final(logs, {'sha': SHA, 'result': 'PASS', 'stages': []}, [], tests, [], [], events, now=now,
                          inline_hooks=True)  # the bound counts the verdict hooks' reads too
        calls = self.forge.calls[start:]
        return {'writes': sum(method in ('POST', 'PATCH') for method, _ in calls),
                'reads': sum(method == 'GET' for method, _ in calls)}

    def test_writes_and_reads_are_bounded_and_do_not_grow_with_the_tests(self):
        many = self.run_gate(F['timed_tests'])
        print(f"gate run over {F['timed_tests']} script tests: forge {many['writes']} writes, {many['reads']} reads "
              f"(bounds {config.get('gate.forge_writes_per_run_max')} / {config.get('gate.forge_reads_per_run_max')})",
              file=sys.stderr)
        self.assertLessEqual(many['writes'], config.get('gate.forge_writes_per_run_max'))
        self.assertLessEqual(many['reads'], config.get('gate.forge_reads_per_run_max'))
        self.assertEqual(len(self.lines('content-writes')), many['writes'], 'the count file sees every write sent')
        one = self.run_gate(F['one_test'])
        self.assertLessEqual(one['writes'], many['writes'])  # the same verdict event is deduplicated, never re-posted
        self.assertLessEqual(one['reads'], many['reads'])
        self.assertTrue(all('/issues/' not in path for _, path in self.forge.calls))

    def test_the_panel_is_one_comment_edited_in_place(self):
        self.run_gate(F['timed_tests'])
        posts = [line for line in self.lines('content-writes') if line.startswith('POST') and '/comments' in line]
        edits = [line for line in self.lines('content-writes') if line.startswith('PATCH')]
        self.assertEqual(len(posts), F['posts_per_run'], 'the panel only: the events append goes to the journal')
        self.assertGreaterEqual(len(edits), 1, 'the final verdict edits the panel in place')




# GX-FIX-forge-rate-3 (D-070): the kinds in forge-events.file_kinds and the gate's stage steps live in the local file
# log, never in issue comments, so no test may look for them in the fake forge's comment store (comments-<n>.json);
# a test reads them through the port (forge_events read), which merges both logs. A negated check (`! grep`,
# assertNotIn) states the contract and is allowed. gate-db.test.sh:92 broke the base when it did (7224e361).
def forge_comment_readers(files):
    needles = [*config.get('forge-events.file_kinds'), config.get('forge-events.gate_step_prefix')]
    found = []
    for path in files:
        for number, line in enumerate(Path(path).read_text(errors='replace').splitlines(), 1):
            if F['comment_store'] not in line or '! grep' in line or 'NotIn' in line:
                continue
            if any(needle in line for needle in needles):
                found.append(f'{Path(path).relative_to(ROOT)}:{number}')
    return found


class FileKindsStayOffComments(unittest.TestCase):
    def test_no_test_reads_a_file_log_kind_from_forge_comments(self):
        tests = sorted((ROOT / 'scripts' / 'tests').glob('*.sh')) + sorted((ROOT / 'scripts' / 'tests').glob('*.py'))
        self.assertEqual(forge_comment_readers(tests), [])

    def test_a_planted_reader_fails_the_guard(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'scripts' / 'tests') as folder:
            planted = Path(folder) / 'planted.test.sh'
            planted.write_text(F['planted_comment_reader'])
            self.assertEqual(forge_comment_readers([planted]), [f'{planted.relative_to(ROOT)}:{F["planted_line"]}'])


if __name__ == '__main__':
    unittest.main()
