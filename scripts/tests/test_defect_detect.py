"""Detection of base defects in the gate (KD1). A fake runner stands for the base re-run; real git for the worktree test."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import forge_events  # noqa: E402
import gate_report  # noqa: E402
import defect_adapters  # noqa: E402
import defect_detect  # noqa: E402
import defects  # noqa: E402

BASE = 'c' * 40
HEAD = 'a' * 40
OTHER = 'd' * 40
SIG = 'AssertionError: boom N'


def setUpModule():
    """GX-32: no test reads the real forge for the base signal; a test that needs one passes its own reader."""
    patcher = mock.patch.object(defect_detect, '_repository_signal', return_value=[])
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def failure(test='scripts/tests/a.test.sh', stage='script tests', signature=SIG):
    return {'id': test, 'stage': stage, 'signature': signature}


class Runner:
    def __init__(self, **results):
        self.results, self.calls = results, []

    def __call__(self, test, base, root):
        self.calls.append(test)
        return self.results.get(test, {'result': 'pass', 'signature': ''})


class Adjudication(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def judge(self, failures, runner, base=BASE):
        return defect_detect.adjudicate(failures, base, ROOT, self.tmp, runner, now=1000)

    def test_a_failure_with_the_same_signature_on_the_base_is_known_and_not_the_prs(self):
        runner = Runner(**{'scripts/tests/a.test.sh': {'result': 'fail', 'signature': SIG}})
        judged = self.judge([failure()], runner)
        self.assertEqual([item['id'] for item in judged['known']], ['scripts/tests/a.test.sh'])
        self.assertEqual((judged['own'], judged['known'][0]['base_sha']), ([], BASE))
        self.assertEqual(judged['known'][0]['defect'], defects.defect_id('scripts/tests/a.test.sh', SIG))

    def test_a_failure_that_passes_on_the_base_is_the_prs_own(self):
        judged = self.judge([failure()], Runner())
        self.assertEqual((judged['known'], len(judged['own'])), ([], 1))

    def test_another_signature_on_the_base_is_the_prs_own(self):
        runner = Runner(**{'scripts/tests/a.test.sh': {'result': 'fail', 'signature': 'KeyError: x'}})
        self.assertEqual(len(self.judge([failure()], runner)['own']), 1)

    def test_a_rerun_that_errors_proves_nothing_and_is_not_cached(self):
        runner = Runner(**{'scripts/tests/a.test.sh': {'result': 'error', 'signature': ''}})
        self.assertEqual(len(self.judge([failure()], runner)['own']), 1)
        self.judge([failure()], runner)
        self.assertEqual(len(runner.calls), 2)

    def test_a_stage_outside_the_registered_stages_and_an_unresolved_base_are_never_excused(self):
        runner = Runner(**{'src/a.test.ts': {'result': 'fail', 'signature': SIG}})
        self.assertEqual(len(self.judge([failure('src/a.test.ts', 'unit')], runner)['own']), 1)
        self.assertEqual(runner.calls, [])
        self.assertEqual(len(self.judge([failure()], runner, base=None)['own']), 1)

    def test_the_outcome_is_cached_per_base_sha_and_test(self):
        runner = Runner(**{'scripts/tests/a.test.sh': {'result': 'fail', 'signature': SIG}})
        self.judge([failure()], runner)
        self.judge([failure()], runner)
        self.assertEqual(runner.calls, ['scripts/tests/a.test.sh'])
        self.assertEqual(self.judge([failure()], runner, base=OTHER)['known'][0]['base_sha'], OTHER)
        self.assertEqual(len(runner.calls), 2)

    def test_a_cached_outcome_older_than_the_ttl_is_a_miss(self):
        runner = Runner()
        defect_detect.outcome('t', BASE, ROOT, self.tmp, runner, now=0)
        defect_detect.outcome('t', BASE, ROOT, self.tmp, runner, now=config.get('defects.cache_ttl_s') + 1)
        self.assertEqual(len(runner.calls), 2)


class Report(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = self.tmp / 'logs'
        self.logs.mkdir()

    def report(self, stages):
        return {'sha': HEAD, 'result': 'FAIL', 'stages': [{'name': n, 'result': r, 'seconds': 1} for n, r in stages]}

    def records(self, *tests):
        (self.logs / 'script-tests.json').write_text(json.dumps(
            [{'test': t, 'result': 'FAIL', 'cached': False, 'key': '', 'source': 'x', 'tail': [f'AssertionError: boom {n}']}
             for n, t in enumerate(tests)]))

    def apply(self, report, runner):
        return defect_detect.apply_to_report(report, self.logs, BASE, ROOT, self.tmp / 'cache', runner, now=5, reader=list)

    def test_all_failures_known_makes_the_run_pass_and_lists_them(self):
        self.records('scripts/tests/a.test.sh', 'scripts/tests/b.test.sh')
        runner = Runner(**{t: {'result': 'fail', 'signature': 'AssertionError: boom N'} for t in ('scripts/tests/a.test.sh', 'scripts/tests/b.test.sh')})
        report = self.report([('lint', 'PASS'), ('script tests', 'FAIL')])
        known = self.apply(report, runner)
        self.assertEqual((report['result'], len(known)), ('PASS', 2))
        self.assertEqual([s['result'] for s in report['stages']], ['PASS', 'PASS'])
        self.assertEqual(report['stages'][1]['raw_result'], 'FAIL')

    def test_one_own_failure_keeps_the_run_red_and_still_lists_the_known_one(self):
        self.records('scripts/tests/a.test.sh', 'scripts/tests/b.test.sh')
        runner = Runner(**{'scripts/tests/a.test.sh': {'result': 'fail', 'signature': 'AssertionError: boom N'}})
        report = self.report([('script tests', 'FAIL')])
        self.apply(report, runner)
        self.assertEqual((report['result'], [k['id'] for k in report['known_defects']]), ('FAIL', ['scripts/tests/a.test.sh']))

    def test_another_failed_stage_keeps_the_run_red(self):
        self.records('scripts/tests/a.test.sh')
        runner = Runner(**{'scripts/tests/a.test.sh': {'result': 'fail', 'signature': 'AssertionError: boom N'}})
        report = self.report([('typecheck', 'FAIL'), ('script tests', 'FAIL')])
        self.apply(report, runner)
        self.assertEqual(report['result'], 'FAIL')


class Verdict(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        clock = type('Clock', (), {'now': lambda self: __import__('datetime').datetime(2026, 10, 27, tzinfo=__import__('datetime').timezone.utc)})()
        self.port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), clock, 'gate', 'test')

    def report(self, result):
        known = {'id': 'scripts/tests/a.test.sh', 'stage': 'script tests', 'signature': SIG, 'base_sha': BASE, 'owner': 'engine-lane',
                 'defect': defects.defect_id('scripts/tests/a.test.sh', SIG)}
        return {'sha': HEAD, 'result': result, 'base_sha': BASE, 'known_defects': [known],
                'stages': [{'name': 'script tests', 'result': 'PASS' if result == 'PASS' else 'FAIL', 'seconds': 1}],
                'defect_decisions': [{'defect': 'KD-00000001', 'result': 'verified', 'signature': '', 'test': 'scripts/tests/b.test.sh',
                                      'owner': 'engine-lane', 'recorded_signature': SIG}]}

    def test_the_verdict_lists_the_known_defects_and_emits_defect_events_before_it(self):
        events = gate_report.gate_events(self.report('PASS'), 'dev', 7, self.tmp, self.port, [])
        self.assertEqual([e['type'] for e in events if e['type'].startswith('defect.')], ['defect.detected', 'defect.verified'])
        self.assertEqual(events[-1]['type'], 'gate.passed')
        self.assertEqual(events[-1]['payload']['known_defects'][0]['id'], 'scripts/tests/a.test.sh')
        self.assertEqual(events[-1]['version'], config.get('gate-contracts.gate_passed_version'))

    def test_a_red_run_lists_them_too(self):
        events = gate_report.gate_events(self.report('FAIL'), 'dev', 7, self.tmp, self.port, [])
        self.assertEqual(events[-1]['type'], 'gate.failed')
        self.assertEqual(len(events[-1]['payload']['known_defects']), 1)

    def test_other_gate_modes_emit_no_defect_events(self):
        events = gate_report.gate_events(self.report('PASS'), 'noite', 7, self.tmp, self.port, [])
        self.assertEqual([e['type'] for e in events if e['type'].startswith('defect.')], [])

    def test_resolved_defects_are_verified_or_reopened_by_what_the_base_says(self):
        records = {'KD-1': {'status': 'resolved', 'test': 't1', 'stage': 'script tests'},
                   'KD-2': {'status': 'resolved', 'test': 't2', 'stage': 'script tests'},
                   'KD-3': {'status': 'open', 'test': 't3', 'stage': 'script tests'},
                   'KD-4': {'status': 'resolved', 'test': 't4', 'stage': 'unit'}}
        runner = Runner(t2={'result': 'fail', 'signature': 'KeyError: x'})
        decided = defect_detect.verification(records, BASE, ROOT, self.tmp, runner, now=1)
        self.assertEqual([(d['defect'], d['result']) for d in decided], [('KD-1', 'verified'), ('KD-2', 'reopened'), ('KD-3', 'verified')])
        self.assertEqual(defect_detect.verification(records, None), [])
        still = Runner(t3={'result': 'fail', 'signature': SIG})
        self.assertNotIn('KD-3', [d['defect'] for d in defect_detect.verification(records, OTHER, ROOT, self.tmp, still, now=1)])
        real = defect_detect.setting
        with mock.patch.object(defect_detect, 'setting', side_effect=lambda name: False if name == 'verify_open' else real(name)):
            off = defect_detect.verification(records, BASE, ROOT, self.tmp, runner, now=1)
        self.assertEqual([(d['defect'], d['result']) for d in off], [('KD-1', 'verified'), ('KD-2', 'reopened')])


class Worktree(unittest.TestCase):
    def test_rerun_runs_the_test_in_a_throwaway_worktree_of_the_base(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        env = ['-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-C', str(tmp)]
        subprocess.run(['git', 'init', '-q', str(tmp)], check=True)
        (tmp / 't.test.sh').write_text('#!/usr/bin/env bash\necho "AssertionError: base 42"; exit 1\n')
        subprocess.run(['git', *env, 'add', '-A'], check=True)
        subprocess.run(['git', *env, 'commit', '-qm', 'base'], check=True)
        sha = subprocess.run(['git', *env, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        found = defect_detect.rerun('t.test.sh', sha, tmp)
        self.assertEqual(found, {'result': 'fail', 'signature': 'AssertionError: base N'})
        self.assertEqual(subprocess.run(['git', *env, 'worktree', 'list'], capture_output=True, text=True).stdout.count('\n'), 1)
        self.assertEqual(defect_detect.rerun('t.test.sh', 'f' * 40, tmp)['result'], 'error')
        self.assertEqual(defect_detect.resolve_base(tmp, 'no-such-ref'), None)
        self.assertEqual(defect_detect.resolve_base(tmp, 'HEAD'), sha)


class RecordedBase(unittest.TestCase):
    """GX-13: the base is the one the proof records (OU_GATE_BASE_SHA), fetched when missing, never a local ref."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin, self.local = self.tmp / 'origin', self.tmp / 'local'
        self.git(self.tmp, 'init', '-q', str(self.origin))
        (self.origin / 'f').write_text('1')
        self.first = self.commit(self.origin)
        self.git(self.tmp, 'clone', '-q', str(self.origin), str(self.local))
        (self.origin / 'f').write_text('2')
        self.second = self.commit(self.origin)  # not in the local clone
        self.name = config.get('defects.base_env')

    def git(self, where, *args):
        flags = ['-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-C', str(where)]
        return subprocess.run(['git', *flags, *args], capture_output=True, text=True, check=True).stdout.strip()

    def commit(self, where):
        self.git(where, 'add', '-A')
        self.git(where, 'commit', '-qm', 'c')
        return self.git(where, 'rev-parse', 'HEAD')

    def test_the_recorded_base_wins_over_any_local_ref(self):
        self.assertEqual(defect_detect.recorded_base(self.local, {self.name: self.first}), self.first)
        other = self.tmp / 'other'
        self.git(self.tmp, 'clone', '-q', str(self.origin), str(other))  # another session, another local ref
        self.assertEqual(defect_detect.recorded_base(other, {self.name: self.first}), self.first)

    def test_a_missing_base_is_fetched(self):
        self.assertFalse(defect_detect.present(self.local, self.second))
        self.assertEqual(defect_detect.recorded_base(self.local, {self.name: self.second}), self.second)
        self.assertTrue(defect_detect.present(self.local, self.second))

    def test_no_recorded_base_or_an_unfetchable_one_excuses_nothing(self):
        self.assertIsNone(defect_detect.recorded_base(self.local, {self.name: ''}))
        self.assertIsNone(defect_detect.recorded_base(self.local, {self.name: BASE}, fetcher=lambda root, sha: False))

    def test_unset_falls_back_to_the_local_ref_outside_gate_local(self):
        with mock.patch.object(defect_detect, 'resolve_base', return_value=BASE) as resolved:
            self.assertEqual(defect_detect.recorded_base(self.local, {}), BASE)
        resolved.assert_called_once_with(self.local)

    def test_adjudication_uses_the_recorded_base(self):
        report, real = {'result': 'PASS', 'stages': []}, defect_detect.recorded_base
        with mock.patch.dict(os.environ, {self.name: self.first}), \
             mock.patch.object(defect_detect, 'recorded_base', side_effect=lambda: real(self.local)), \
             mock.patch.object(defect_detect, 'resolve_base', side_effect=AssertionError('local ref read')), \
             mock.patch.object(defect_detect, 'verification', return_value=[]):
            import gate_adjudicate
            gate_adjudicate.adjudicate(report, self.tmp / 'logs', 'dev', ['dev'])
        self.assertEqual(report['base_sha'], self.first)


class BaseInstall(unittest.TestCase):
    """GX-13: the base re-run installs nothing and never links the tool root's node_modules (vazão F16: no package)."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.flags = ['-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-C', str(self.tmp)]
        subprocess.run(['git', 'init', '-q', str(self.tmp)], check=True)
        (self.tmp / '.gitignore').write_text('node_modules\n')
        (self.tmp / 't.test.sh').write_text('! test -e node_modules || { echo "AssertionError: linked install"; exit 1; }\n')
        subprocess.run(['git', *self.flags, 'add', '-A'], check=True)
        subprocess.run(['git', *self.flags, 'commit', '-qm', 'base'], check=True)
        self.sha = subprocess.run(['git', *self.flags, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        (self.tmp / 'node_modules').mkdir()  # the tool root's own install: must not be linked

    def test_the_base_runs_without_an_install(self):
        self.assertEqual(defect_detect.rerun('t.test.sh', self.sha, self.tmp), {'result': 'pass', 'signature': ''})
        self.assertFalse(hasattr(defect_detect, 'install'))


class Touched(unittest.TestCase):
    """GX-13: a failing test whose own file or declared covers the PR changed is never excused (the #662 case)."""
    TEST = 'scripts/tests/a.test.sh'
    MAP = {'tests': [{'script': TEST, 'covers': ('scripts/lib/a*.py',)}]}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.runner = Runner(**{self.TEST: {'result': 'fail', 'signature': SIG}})

    def judge(self, changed):
        return defect_detect.adjudicate([failure()], BASE, ROOT, self.tmp, self.runner, now=1, changed=changed, mapping=self.MAP)

    def test_the_662_case_a_failing_test_whose_own_file_the_pr_changed_stays_red(self):
        judged = self.judge([self.TEST])
        self.assertEqual((judged['known'], [item['touched'] for item in judged['own']]), ([], [True]))
        self.assertEqual(self.runner.calls, [])

    def test_a_change_to_its_declared_covers_or_its_manifest_is_touching_it(self):
        manifest = defect_detect.script_covers.manifest_path(self.TEST, ROOT).relative_to(ROOT).as_posix()
        for changed in (['scripts/lib/ab.py'], [manifest], None):
            self.assertEqual(len(self.judge(changed)['own']), 1, changed)
        self.assertEqual(self.runner.calls, [])

    def test_an_unrelated_change_is_still_adjudicated_on_the_base(self):
        self.assertEqual([item['id'] for item in self.judge(['docs/x.md'])['known']], [self.TEST])

    def test_the_switch_off_restores_the_kd1_excuse(self):
        real = defect_detect.setting
        with mock.patch.object(defect_detect, 'setting', side_effect=lambda name: False if name == 'never_excuse_touched' else real(name)):
            self.assertEqual(len(self.judge([self.TEST])['known']), 1)

    def test_changed_files_are_the_prs_diff_and_an_undiffable_pair_is_unknown(self):
        flags = ['-c', 'user.name=t', '-c', 'user.email=t@example.invalid', '-C', str(self.tmp)]
        git = lambda *args: subprocess.run(['git', *flags, *args], capture_output=True, text=True, check=True).stdout.strip()
        git('init', '-q')
        (self.tmp / 'a').write_text('1')
        git('add', '-A'); git('commit', '-qm', 'base')
        base = git('rev-parse', 'HEAD')
        (self.tmp / 'b').write_text('1')
        git('add', '-A'); git('commit', '-qm', 'head')
        self.assertEqual(defect_detect.changed_files(base, git('rev-parse', 'HEAD'), self.tmp), ['b'])
        self.assertIsNone(defect_detect.changed_files(base, 'working-tree', self.tmp))
        self.assertIsNone(defect_detect.changed_files(None, base, self.tmp))

    def test_an_excused_stage_keeps_raw_fail_and_its_defect_ids(self):
        logs = self.tmp / 'logs'
        logs.mkdir()
        (logs / 'script-tests.json').write_text(json.dumps(
            [{'test': self.TEST, 'result': 'FAIL', 'cached': False, 'key': '', 'source': 'x', 'tail': ['AssertionError: boom 1']}]))
        report = {'sha': HEAD, 'result': 'FAIL', 'stages': [{'name': 'script tests', 'result': 'FAIL', 'seconds': 1}]}
        defect_detect.apply_to_report(report, logs, BASE, ROOT, self.tmp / 'cache', self.runner, now=1, changed=['docs/x.md'], mapping=self.MAP)
        self.assertEqual(report['stages'][0], {'name': 'script tests', 'result': 'PASS', 'raw_result': 'FAIL', 'seconds': 1,
                                               'defects': [defects.defect_id(self.TEST, SIG)]})
        red = {'sha': HEAD, 'result': 'FAIL', 'stages': [{'name': 'script tests', 'result': 'FAIL', 'seconds': 1}]}
        defect_detect.apply_to_report(red, logs, BASE, ROOT, self.tmp / 'cache', self.runner, now=1, changed=[self.TEST], mapping=self.MAP)
        self.assertEqual((red['result'], red['stages'][0]['result'], red['known_defects']), ('FAIL', 'FAIL', []))


class Adapters(unittest.TestCase):
    """GX-32 (harvested from BD1 #667): the failing tests of every failed stage; the script shape is the only one (F46)."""

    def setUp(self):
        self.logs = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.logs, True)

    def test_the_script_stage_is_read_and_every_other_failed_stage_is_unattributed(self):
        (self.logs / 'script-tests.json').write_text(json.dumps(
            [{'test': 'scripts/tests/a.test.sh', 'result': 'FAIL', 'tail': ['AssertionError: boom 1']}]))
        # A vitest line in a failed stage's log was a per-test failure while Open University's suites ran; it is not now.
        (self.logs / 'structure_check.log').write_text(' FAIL  |unit| src/x.test.ts > suite > works\nAssertionError: x\n')
        report = {'stages': [{'name': n, 'result': 'FAIL'} for n in ('script tests', 'structure check', 'shellcheck')]
                  + [{'name': 'secret scan (tree)', 'result': 'PASS'}]}
        found, unattributed = defect_adapters.failures(report, self.logs)
        self.assertEqual([(item['stage'], item['id'], item['signature']) for item in found],
                         [('script tests', 'scripts/tests/a.test.sh', SIG)])
        self.assertEqual(unattributed, ['structure check', 'shellcheck'])

    def test_only_the_script_shape_is_rerun_on_the_base(self):
        self.assertEqual([defect_adapters.rerunnable(s) for s in ('script tests', 'structure check', 'shellcheck')],
                         [True, False, False])

    def test_every_adjudicated_stage_is_one_the_gate_runs(self):
        """F46: defects.stages named four stages that left with Open University; it names only the gate's own."""
        import gate_policy
        self.assertEqual(set(defect_detect.setting('stages')) - set(gate_policy.FULL_STAGES), set())


class BaseSignal(unittest.TestCase):
    """GX-32: a test that the base.red for the proof's base sha lists is a known base defect, with no base re-run,
    unless the PR touched its file or covers (GX-13); defects.base_signal_enabled=false restores GX-13."""

    TEST = 'scripts/tests/a.test.sh'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), forge_events.clock_from_config(), 'battery', 'test')
        self.repo = config.get('forge-events.repo')
        self.events = []

    def red(self, base=BASE, tests=None):
        tests = tests or [{'id': self.TEST, 'stage': 'script tests', 'signature': SIG}]
        self.events.append(self.port.build('base.red', dict(forge_events.subject(self.repo, None, base), base_sha=base, since=base, tests=tests)))

    def green(self, base=BASE):
        self.events.append(self.port.build('base.green', dict(forge_events.subject(self.repo, None, base), base_sha=base, cleared=[self.TEST])))

    def pr_run(self, n, signature='AssertionError: boom 2'):
        logs = self.tmp / f'pr{n}'
        logs.mkdir()
        (logs / 'script-tests.json').write_text(json.dumps([{'test': self.TEST, 'result': 'FAIL', 'tail': [signature]}]))
        return logs, {'sha': HEAD, 'result': 'FAIL', 'stages': [{'name': 'shellcheck', 'result': 'PASS'},
                                                                {'name': 'script tests', 'result': 'FAIL'}]}

    def apply(self, logs, report, runner, changed=('scripts/lib/other.py',), base=BASE):
        return defect_detect.apply_to_report(report, logs, base, ROOT, self.tmp / 'cache', runner, now=1, changed=list(changed),
                                             mapping={'tests': [{'script': self.TEST, 'covers': ['scripts/lib/defect_*.py']}]},
                                             reader=lambda: list(self.events))

    def test_a_listed_defect_makes_n_prs_mergeable_with_zero_base_reruns(self):
        self.red()
        runner = Runner()
        for n in ('pr-a', 'pr-b', 'pr-c', 'pr-d', 'pr-e'):
            logs, report = self.pr_run(n)
            known = self.apply(logs, report, runner)
            self.assertEqual((report['result'], report['stages'][1]['raw_result']), ('PASS', 'FAIL'))
            self.assertEqual([(k['id'], k['source'], k['base_sha']) for k in known], [(self.TEST, 'base.red', BASE)])
        self.assertEqual(runner.calls, [])

    def test_a_pr_that_touched_the_test_file_or_its_covers_is_not_excused(self):
        for changed in ([self.TEST], ['scripts/lib/defect_detect.py']):
            with self.subTest(changed=changed):
                self.events = []
                self.red()
                logs, report = self.pr_run('touched-' + str(len(changed[0])))
                self.apply(logs, report, Runner(), changed=changed)
                self.assertEqual((report['result'], report['known_defects']), ('FAIL', []))

    def test_another_signature_another_base_sha_or_a_green_base_is_not_excused(self):
        self.red()
        logs, report = self.pr_run('sig', signature='TypeError: x is undefined')
        self.apply(logs, report, Runner(**{self.TEST: {'result': 'pass', 'signature': ''}}))
        self.assertEqual(report['result'], 'FAIL')
        logs, report = self.pr_run('other')
        self.apply(logs, report, Runner(), base=OTHER)
        self.assertEqual(report['result'], 'FAIL')
        self.green()
        logs, report = self.pr_run('green')
        self.apply(logs, report, Runner())
        self.assertEqual(report['result'], 'FAIL')
        self.assertFalse(defect_detect.base_red(BASE, lambda: list(self.events)))
        self.red()
        self.assertTrue(defect_detect.base_red(BASE, lambda: list(self.events)))

    def test_a_listed_script_test_is_known_without_a_rerun_and_an_unreadable_signal_excuses_nothing(self):
        self.red()
        runner = Runner()
        judged = defect_detect.adjudicate([failure()], BASE, ROOT, self.tmp, runner, now=1, changed=[], mapping={'tests': []},
                                          signal=defect_detect.base_signal(BASE, lambda: list(self.events)))
        self.assertEqual(([k['source'] for k in judged['known']], runner.calls), (['base.red'], []))
        self.assertIsNone(defect_detect.base_signal(BASE, lambda: (_ for _ in ()).throw(OSError('forge down'))))

    def test_the_switch_off_restores_the_gx13_behaviour(self):
        self.red()
        real = defect_detect.setting
        reads = []
        runner = Runner()
        with mock.patch.object(defect_detect, 'setting', side_effect=lambda name: False if name == 'base_signal_enabled' else real(name)):
            logs, report = self.pr_run('off')
            defect_detect.apply_to_report(report, logs, BASE, ROOT, self.tmp / 'cache', runner, now=1, changed=[],
                                          mapping={'tests': []}, reader=lambda: reads.append(1) or list(self.events))
            self.assertEqual(defect_detect.stages(), ['script tests'])
        # With the signal off the base is asked by a re-run (it passes there), never by reading the forge.
        self.assertEqual((report['result'], report['known_defects'], reads, runner.calls), ('FAIL', [], [], [self.TEST]))


if __name__ == '__main__':
    unittest.main()
