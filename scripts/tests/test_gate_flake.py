"""Flake attribution on the PR's own head (TX11, D-070). A fake runner stands for the one re-run; an in-memory forge log
for the quarantine. No network."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import defects  # noqa: E402
import forge_events  # noqa: E402
import defect_detect  # noqa: E402
import gate_adjudicate  # noqa: E402
import gate_classify  # noqa: E402
import gate_flake  # noqa: E402
import gate_report  # noqa: E402
import gate_status  # noqa: E402
import gate_test_cache  # noqa: E402

HEAD = hashlib.sha1(b'head').hexdigest()
EARLIER = hashlib.sha1(b'earlier').hexdigest()
A, B = 'scripts/tests/a.test.sh', 'scripts/tests/b.test.sh'
REPO = 'openuniversity-si/open-university'
PR = 1
WINDOW = timedelta(seconds=config.get('gate-flake.quarantine_window_s'))
NOW = datetime.fromtimestamp(0, timezone.utc) + WINDOW + WINDOW  # a fixed clock, a whole window after the epoch


class Runner:
    """The re-run: each named test's result ('PASS' or 'FAIL'); a test it does not name has no result."""

    def __init__(self, **results):
        self.results, self.calls = results, []

    def __call__(self, tests, root):
        self.calls.append(list(tests))
        return {test: {'test': test, 'result': self.results[test]} for test in tests if test in self.results}


def clock(moment):
    return type('Clock', (), {'now': lambda self: moment})()


class Attribute(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = self.tmp / 'logs'
        self.logs.mkdir()

    def records(self, *tests):
        (self.logs / 'script-tests.json').write_text(json.dumps(
            [{'test': t, 'result': 'FAIL', 'cached': False, 'key': '', 'source': 'x', 'tail': [f'AssertionError: boom {t}']}
             for t in tests]))

    def report(self, *stages):
        return {'sha': HEAD, 'result': 'FAIL', 'stages': [{'name': n, 'result': r, 'seconds': 1} for n, r in stages]}

    def attribute(self, report, runner, **kwargs):
        return gate_flake.attribute(report, self.logs, self.tmp, runner, **kwargs)

    def stage_log(self, name='script tests'):
        return gate_flake.stage_log(self.logs, name).read_text()

    def test_a_test_that_passes_on_the_one_rerun_is_a_flake_and_the_run_passes(self):
        self.records(A)
        report = self.report(('lint', 'PASS'), ('script tests', 'FAIL'))
        flakes = self.attribute(report, Runner(**{A: 'PASS'}))
        stage = report['stages'][1]
        self.assertEqual((report['result'], stage['result'], stage['raw_result'], stage['class']), ('PASS', 'PASS', 'FAIL', 'flake'))
        self.assertEqual([item['id'] for item in flakes], [A])
        self.assertEqual(report['flakes'], flakes)
        item = report['known_defects'][0]
        self.assertEqual((item['id'], item['source'], item['base_sha'], item['defect']),
                         (A, 'flake', HEAD, defects.defect_id(A, item['signature'])))
        self.assertEqual(stage['defects'], [item['defect']])
        self.assertEqual(item['owner'], defects.derive_owner(A, ROOT)[1])
        self.assertIn(f'flake: {A} failed, then passed on one re-run at the same head', self.stage_log())
        self.assertTrue(self.stage_log().rstrip().endswith('\tflake'))

    def test_a_test_that_fails_again_changes_nothing_and_the_class_stays_code(self):
        self.records(A)
        report = self.report(('script tests', 'FAIL'))
        self.assertEqual(self.attribute(report, Runner(**{A: 'FAIL'})), [])
        self.assertEqual((report['result'], report['stages'][0]['result'], report.get('known_defects')), ('FAIL', 'FAIL', None))
        self.assertNotIn('raw_result', report['stages'][0])
        self.assertTrue(self.stage_log().rstrip().endswith('\tcode'))

    def test_a_rerun_with_no_result_or_an_error_proves_nothing(self):
        self.records(A)
        report = self.report(('script tests', 'FAIL'))
        self.assertEqual(self.attribute(report, Runner()), [])
        self.assertEqual(report['result'], 'FAIL')

    def test_exactly_one_rerun_of_only_the_failing_tests(self):
        self.records(A, B)
        runner = Runner(**{A: 'PASS', B: 'PASS'})
        self.attribute(self.report(('script tests', 'FAIL')), runner)
        self.assertEqual(runner.calls, [[A, B]])
        self.assertEqual(config.get('gate-flake.reruns'), 1)

    def test_one_flake_and_one_real_failure_keep_the_stage_red_and_still_list_the_flake(self):
        self.records(A, B)
        report = self.report(('script tests', 'FAIL'))
        self.attribute(report, Runner(**{A: 'PASS', B: 'FAIL'}))
        self.assertEqual((report['result'], report['stages'][0]['result']), ('FAIL', 'FAIL'))
        self.assertEqual([item['id'] for item in report['known_defects']], [A])
        self.assertTrue(self.stage_log().rstrip().endswith('\tcode'))

    def test_a_known_base_defect_and_a_flake_in_one_stage_make_it_pass(self):
        self.records(A, B)
        report = self.report(('script tests', 'FAIL'))
        report['known_defects'] = [{'id': B, 'stage': 'script tests', 'signature': 's', 'defect': 'KD-000001'}]
        runner = Runner(**{A: 'PASS'})
        self.attribute(report, runner)
        self.assertEqual(runner.calls, [[A]])
        self.assertEqual((report['result'], report['stages'][0]['defects']), ('PASS', sorted(['KD-000001', report['flakes'][0]['defect']])))

    def test_another_red_stage_keeps_the_run_red(self):
        self.records(A)
        report = self.report(('typecheck', 'FAIL'), ('script tests', 'FAIL'))
        self.attribute(report, Runner(**{A: 'PASS'}))
        self.assertEqual((report['result'], report['stages'][1]['result']), ('FAIL', 'PASS'))

    def test_a_test_the_pr_changed_is_not_rerun_and_stays_its_own(self):
        self.records(A)
        report = self.report(('script tests', 'FAIL'))
        runner = Runner(**{A: 'PASS'})
        self.attribute(report, runner, changed=[A])
        self.assertEqual((runner.calls, report['result']), ([], 'FAIL'))
        self.assertIn(f"flake: {A} is the PR's own: the PR changed it", self.stage_log())

    def test_an_unknown_change_set_excuses_nothing(self):
        self.records(A)
        runner = Runner(**{A: 'PASS'})
        report = self.report(('script tests', 'FAIL'))
        self.attribute(report, runner, changed=None)
        self.assertEqual((runner.calls, report['result']), ([], 'FAIL'))

    def test_a_stage_outside_the_registered_stages_is_never_rerun(self):
        runner = Runner()
        report = self.report(('typecheck', 'FAIL'))
        (self.logs / 'typecheck.log').write_text('src/a.test.ts > b\nAssertionError: x\n')
        self.attribute(report, runner)
        self.assertEqual((runner.calls, report['result']), ([], 'FAIL'))

    def test_the_switch_off_and_a_passing_run_rerun_nothing(self):
        self.records(A)
        runner = Runner(**{A: 'PASS'})
        with mock.patch.object(gate_flake, 'setting', lambda name: False if name == 'enabled' else config.get(f'gate-flake.{name}')):
            report = self.report(('script tests', 'FAIL'))
            self.attribute(report, runner)
        self.assertEqual((runner.calls, report['result'], report['flakes']), ([], 'FAIL', []))
        passed = {'sha': HEAD, 'result': 'PASS', 'stages': []}
        self.attribute(passed, runner)
        self.assertEqual(runner.calls, [])


class Rerun(unittest.TestCase):
    def test_the_rerun_calls_the_cache_run_once_with_a_throwaway_store_it_deletes(self):
        seen = []

        def fake(scripts, root, location, source, tool_root):
            seen.append((list(scripts), Path(location), source))
            self.assertTrue(Path(location).is_dir())
            return [{'test': script, 'result': 'PASS'} for script in scripts]

        with mock.patch.object(gate_flake.gate_test_cache, 'run', fake):
            found = gate_flake.rerun([A], ROOT)
        [(scripts, store, source)] = seen
        self.assertEqual((scripts, source, found[A]['result']), ([A], config.get('gate-flake.rerun_source'), 'PASS'))
        self.assertFalse(store.exists())
        self.assertNotEqual(store, gate_flake.gate_test_cache.store_location())

    def test_the_subject_root_is_the_checkout_gate_local_exports(self):
        self.assertEqual(gate_flake.subject_root({config.get('gate-flake.subject_env'): '/x'}), Path('/x'))
        self.assertEqual(gate_flake.subject_root({}), ROOT)


class Quarantine(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), clock(NOW), 'gate', 'test')

    def report(self, test=A):
        return {'sha': HEAD, 'flakes': [{'id': test, 'stage': 'script tests', 'signature': 's', 'base_sha': HEAD,
                                         'owner': 'engine-lane', 'unit': None, 'defect': 'KD-000001'}]}

    def earlier(self, moment, sha=EARLIER, kind='test.flaked', test=A, **extra):
        port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), clock(moment), 'gate', 'test')
        extra = extra or {'log': 'x.log'}
        return port.build(kind, dict(forge_events.subject(REPO, None, sha), test=test, **extra))

    def events(self, report, log):
        return gate_flake.events(report, self.tmp, self.port, REPO, reader=lambda: log)

    def test_a_first_flake_emits_test_flaked_only(self):
        report = self.report()
        built = self.events(report, [])
        self.assertEqual([e['type'] for e in built], ['test.flaked'])
        self.assertEqual((built[0]['payload']['test'], built[0]['payload']['pr'], built[0]['payload']['sha']), (A, None, HEAD))
        self.assertEqual((report['flakes'][0]['flaked_in_window'], report['flakes'][0]['quarantined']), (1, False))

    def test_a_second_flake_inside_the_window_is_quarantined_and_still_listed(self):
        report = self.report()
        built = self.events(report, [self.earlier(NOW - timedelta(days=1))])
        self.assertEqual([e['type'] for e in built], ['test.flaked', 'test.quarantined'])
        flaked, quarantined = built
        self.assertEqual((quarantined['payload']['flaked_event'], quarantined['payload']['owner']), (flaked['event_id'], 'engine-lane'))
        self.assertEqual((report['flakes'][0]['flaked_in_window'], report['flakes'][0]['quarantined']),
                         (config.get('gate-flake.quarantine_after'), True))

    def test_an_earlier_flake_outside_the_window_or_of_another_test_does_not_count(self):
        log = [self.earlier(NOW - WINDOW - timedelta(seconds=1)), self.earlier(NOW, test=B)]
        self.assertEqual([e['type'] for e in self.events(self.report(), log)], ['test.flaked'])

    def test_the_same_sighting_replayed_is_not_a_second_one(self):
        first = self.events(self.report(), [])
        self.assertEqual([e['type'] for e in self.events(self.report(), first)], ['test.flaked'])

    def test_an_open_quarantine_is_not_opened_again_but_the_flake_is_still_recorded(self):
        flaked = self.earlier(NOW - timedelta(days=1))
        opened = self.earlier(NOW - timedelta(days=1), kind='test.quarantined', owner='engine-lane', flaked_event=flaked['event_id'])
        report = self.report()
        self.assertEqual([e['type'] for e in self.events(report, [flaked, opened])], ['test.flaked'])
        self.assertTrue(report['flakes'][0]['quarantined'])

    def test_an_unreadable_log_records_the_flake_and_quarantines_nothing(self):
        def broken():
            raise forge_events.ForgeEventsError('down')
        report = self.report()
        built = gate_flake.events(report, self.tmp, self.port, REPO, reader=broken)
        self.assertEqual([e['type'] for e in built], ['test.flaked'])
        self.assertIsNone(report['flakes'][0]['flaked_in_window'])

    def test_no_flake_no_event_and_no_read(self):
        self.assertEqual(gate_flake.events({'flakes': []}, self.tmp, self.port, REPO, reader=lambda: 1 / 0), [])


class CallSite(unittest.TestCase):
    """The one seam: gate_adjudicate.adjudicate attributes flakes after the known-base-defect step, and its events carry
    defect.detected and test.flaked for them."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = self.tmp / 'logs'
        self.logs.mkdir()
        (self.logs / 'script-tests.json').write_text(json.dumps(
            [{'test': A, 'result': 'FAIL', 'cached': False, 'key': '', 'source': 'x', 'tail': ['AssertionError: boom']}]))

    def adjudicate(self, again, mode='dev'):
        report = {'sha': HEAD, 'result': 'FAIL', 'stages': [{'name': 'script tests', 'result': 'FAIL', 'seconds': 1}]}
        runner = Runner(**{A: again})
        with mock.patch.object(defect_detect, 'recorded_base', return_value=EARLIER), \
             mock.patch.object(defect_detect, 'changed_files', return_value=['docs/x.md']), \
             mock.patch.object(defect_detect, 'apply_to_report', side_effect=lambda r, *a, **k: r.setdefault('known_defects', [])), \
             mock.patch.object(defect_detect, 'verification', return_value=[]), \
             mock.patch.object(gate_flake, 'rerun', runner):
            gate_adjudicate.adjudicate(report, self.logs, mode, ['dev'])
        return report, runner

    def test_a_flake_after_the_base_step_makes_the_run_pass_and_its_events_record_it(self):
        report, runner = self.adjudicate('PASS')
        self.assertEqual((report['result'], runner.calls, [item['id'] for item in report['flakes']]), ('PASS', [[A]], [A]))
        port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), clock(NOW), 'gate', 'test')
        built = gate_adjudicate.defect_events(report, 'dev', HEAD, self.logs, port, ['dev'], REPO)
        self.assertEqual([event['type'] for event in built], ['defect.detected', 'test.flaked'])
        self.assertEqual((built[0]['payload']['test'], built[0]['payload']['base_sha']), (A, HEAD))

    def test_a_failure_that_fails_again_stays_red(self):
        report, _ = self.adjudicate('FAIL')
        self.assertEqual((report['result'], report['flakes']), ('FAIL', []))

    def test_a_mode_outside_tier_1_reruns_nothing(self):
        report, runner = self.adjudicate('PASS', mode='noite')
        self.assertEqual((report['result'], runner.calls), ('FAIL', []))


# The fixture test stands at a real owned path, so its owner is the one `scripts/units owner` names; its body is the
# fixture's own, in a throwaway checkout.
FIXTURE = 'scripts/tests/gate-flake.test.sh'
ALWAYS = 'echo "AssertionError: expected [1] got [0]"\nexit 1\n'
ONCE = ('if [ -f .flaked ]; then echo ok; exit 0; fi\ntouch .flaked\n'
        'echo "AssertionError: expected [1] got [0]: a corrupt marker runs the stage again"\nexit 1\n')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=True).stdout


class Fixtures(unittest.TestCase):
    """The two DONE fixtures against the real re-run (gate_test_cache.run in a throwaway git checkout), the class line,
    the defect record through `scripts/defects record`, the status table and the verdict payload."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.logs = self.tmp / 'logs'
        self.logs.mkdir()

    def checkout(self, body):
        root = self.tmp / 'head'
        (root / 'scripts' / 'tests').mkdir(parents=True)
        (root / FIXTURE).write_text('#!/usr/bin/env bash\n' + body)
        git(root, 'init', '-q')
        git(root, 'add', '-A')
        return root

    def gate(self, body):
        """The original run as gate-local does it (script-tests.json, the stage log with the runner's class line), then
        the one re-run; returns (report, root)."""
        root = self.checkout(body)
        store = self.tmp / 'store'
        results = gate_test_cache.run([FIXTURE], str(root), store, HEAD, str(ROOT))
        (self.logs / 'script-tests.json').write_text(json.dumps(results))
        log = gate_flake.stage_log(self.logs, 'script tests')
        log.write_text('\n'.join(results[0]['tail']) + '\n')
        log.write_text(log.read_text() + gate_classify.class_line('script tests', gate_classify.classify('script tests', log.read_text())) + '\n')
        report = {'sha': HEAD, 'result': 'FAIL' if results[0]['result'] == 'FAIL' else 'PASS',
                  'stages': [{'name': 'lint', 'result': 'PASS', 'seconds': 1},
                             {'name': 'script tests', 'result': results[0]['result'], 'seconds': 1}]}
        gate_flake.attribute(report, self.logs, root)
        return report, root

    def machine_class(self):
        prefix = config.get('gate.class_line_prefix') + ' '
        lines = [line for line in gate_flake.stage_log(self.logs, 'script tests').read_text().splitlines() if line.startswith(prefix)]
        return lines[-1].rsplit('\t', 1)[1]

    def test_fixture_1_a_deterministic_failure_fails_again_on_the_one_rerun_and_stays_red_as_code(self):
        report, _ = self.gate(ALWAYS)
        stage = report['stages'][1]
        self.assertEqual((stage['result'], self.machine_class(), report['result']), ('FAIL', 'code', 'FAIL'))
        self.assertEqual((report['flakes'], report.get('known_defects')), ([], None))
        self.assertIn(f"flake: {FIXTURE} is the PR's own: it failed again on the one re-run",
                      gate_flake.stage_log(self.logs, 'script tests').read_text())
        print(f"fixture 1: stage {stage['result']}, class {self.machine_class()}, report {report['result']}", file=sys.stderr)

    def test_fixture_2_a_failure_that_passes_on_the_one_rerun_is_a_flake_recorded_and_listed(self):
        report, root = self.gate(ONCE)
        stage = report['stages'][1]
        self.assertEqual((stage['result'], stage['raw_result'], stage['class'], self.machine_class(), report['result']),
                         ('PASS', 'FAIL', 'flake', 'flake', 'PASS'))
        [flake] = report['flakes']
        self.assertEqual((flake['id'], flake['base_sha'], flake['source']), (FIXTURE, HEAD, 'flake'))
        self.assertTrue((root / '.flaked').is_file())  # the re-run ran in the checkout under test
        owned = subprocess.run([str(ROOT / 'scripts' / 'units'), 'owner', FIXTURE], capture_output=True, text=True, check=True).stdout
        unit, owner, _ = defects.derive_owner(FIXTURE, ROOT)
        self.assertEqual((flake['unit'], flake['owner']), (unit, owner))
        self.assertIn(flake['owner'], owned)
        # the record: scripts/defects record with the flake's test, normalized signature and head, twice (first/last seen)
        records = self.tmp / 'records'
        records.mkdir()
        for part in ('units', 'contracts/defects', 'config/registry', config.get('units.decision_register')):
            (records / part).parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if (ROOT / part).is_dir() else shutil.copy)(ROOT / part, records / part)
        (records / 'scripts' / 'tests').mkdir(parents=True)
        shutil.copy(ROOT / FIXTURE, records / FIXTURE)
        git(records, 'init', '-q')
        git(records, 'add', '-A')
        for run in ('run-first', 'run-last'):
            done = subprocess.run([str(ROOT / 'scripts' / 'defects'), '--root', str(records), 'record', '--test', flake['id'],
                                   '--stage', flake['stage'], '--signature', flake['signature'], '--base-sha', flake['base_sha'],
                                   '--run', run, '--by', 'gate-flake', '--summary', f'flake: {flake["signature"]}', '--no-emit'],
                                  capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
        found, errors = defects.load(records)
        self.assertEqual(errors, [])
        record = found[flake['defect']]
        self.assertEqual((record['test'], record['signature'], record['unit'], record['owner']),
                         (FIXTURE, flake['signature'], flake['unit'], flake['owner']))
        first, last = record['evidence'][0]['at'], record['evidence'][-1]['at']
        self.assertEqual([item['run'] for item in record['evidence']], ['run-first', 'run-last'])
        # the status table and the verdict payload
        state = gate_status.new_state(HEAD, PR, 'dev', ['lint', 'script tests'], {}, 0)
        table = gate_status.render_final(state, report, [], None, [], report['known_defects'], [], 1.0, logs=self.logs)
        row = next(line for line in table.splitlines() if line.startswith(f'| `{FIXTURE}`'))
        self.assertIn(f"yes: {flake['defect']}", row)
        port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), clock(NOW), 'gate', 'test')
        report['base_sha'] = EARLIER
        events = gate_report.gate_events(report, 'dev', PR, self.logs, port, [])
        verdict = events[-1]
        self.assertEqual(verdict['type'], 'gate.passed')
        self.assertEqual([item['id'] for item in verdict['payload']['known_defects']], [FIXTURE])
        print(f"fixture 2: stage {stage['result']} raw_result {stage['raw_result']}, class {stage['class']}, "
              f"report {report['result']}; record {record['id']} test {record['test']} signature {record['signature']!r} "
              f"unit {record['unit']} owner {record['owner']} first seen {first} last seen {last}; table row {row}; "
              f"{verdict['type']} known_defects {verdict['payload']['known_defects']}", file=sys.stderr)


if __name__ == '__main__':
    unittest.main()
