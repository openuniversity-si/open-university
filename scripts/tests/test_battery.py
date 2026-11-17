"""The battery role (plan v3 M6): tier 3 on integration.advanced, coalescing, its lock and its verdicts.

A fake forge (the port's memory adapter plus a lock), a fake tier-3 runner and an injected clock: no network, no git,
no real gate. Every value comes from the registry or is an explicit override in the test.
"""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import battery  # noqa: E402
import config  # noqa: E402
import engine_role  # noqa: E402
import forge_events  # noqa: E402

REPO = 'openuniversity-si/open-university'


def tip(number):
    return f'{number:040x}'


class FakeClock:
    def __init__(self, start=datetime(2026, 10, 26, 21, 0, tzinfo=timezone.utc), step=timedelta(seconds=1)):
        self.moment, self.step = start, step

    def now(self):
        current = self.moment
        self.moment += self.step
        return current


class FakeForge(forge_events.MemoryAdapter):
    """The repository log in memory and the forge's leased locks."""

    def __init__(self):
        super().__init__()
        self.locks, self.lock_calls = {}, []

    def lock(self, repo, name, owner, now, expires):
        self.lock_calls.append(owner)
        held = self.locks.get(name)
        if held and held['owner'] != owner and held['expires'] > now:
            return False
        self.locks[name] = {'owner': owner, 'expires': expires}
        return True

    def unlock(self, repo, name, owner, died=None):
        if self.locks.get(name, {}).get('owner') == owner:
            del self.locks[name]
            if died:  # the reason a run that raised leaves on the release record (TRAIN-TEMP-FIX R1)
                self.deaths = getattr(self, 'deaths', []) + [(name, owner, died)]


def tier3_gate(case, body):
    """The real Tier3Gate over a fake tier-3 command (battery.tier3_command) whose script is `body`."""
    directory = Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, directory)
    script = directory / config.get('battery.tier3_command')[0]
    script.parent.mkdir(parents=True)
    script.write_text(body)
    script.chmod(0o755)
    return battery.Tier3Gate(directory)


class FakeTier3:
    """Tier 3: red on every tip in `red` (with the stage the test names); records every tip it judged. `during`
    runs while a tip is judged (an advance that lands meanwhile)."""

    def __init__(self):
        self.runs, self.red, self.during = [], {}, None
        self.tests, self.failing_tests = {}, []  # GX-32: the failing tests each red tip reports

    def run(self, commit):
        self.runs.append(commit)
        self.failing_tests = self.tests.get(commit, [])
        if self.during:
            during, self.during = self.during, None
            during()
        stage = self.red.get(commit)
        return engine_role.GateResult(stage is None, stage, f'FAIL {stage}' if stage else '')


class Fixture(unittest.TestCase):
    def setUp(self):
        # Consumer unit tests inject local doubles; compatibility is exercised by test_forge_events.
        self.enterContext(mock.patch.object(forge_events, '_require_compatibility'))
        self.forge, self.clock, self.tier3 = FakeForge(), FakeClock(), FakeTier3()
        self.battery = battery.Battery(self.forge, self.clock, self.tier3, REPO)
        self.train_port = forge_events.ForgeEvents(self.forge, self.clock, config.get('train.producer'), 'train-1')
        self.lock_ref = config.get('battery.lock_ref')
        self.prs = 0

    def advance(self, number, prs=1):
        """integration.advanced to tip(number), as the train emits it, merging `prs` new PRs."""
        merged = list(range(self.prs + 1, self.prs + prs + 1))
        self.prs += prs
        payload = dict(forge_events.subject(REPO, None, tip(number)), batch_id=f'b-{number:012x}', prs=merged,
                       prs_since_release=self.prs)
        return self.train_port.emit('integration.advanced', payload)

    def events(self, kind=None):
        found = forge_events.ForgeEvents(self.forge, self.clock, 'reader', 'test').read(REPO, None)
        return [event for event in found if kind is None or event['type'] == kind]

    def steps(self):
        return [(e['payload']['step'], e['payload']['sha'], e['payload']['result'])
                for e in self.events('engine.step.measured')]


class Tier3OnAdvance(Fixture):
    def test_nothing_advanced_runs_nothing_and_releases(self):
        self.assertEqual(self.battery.run('lane-a'), 'drained')
        self.assertEqual(self.tier3.runs, [])
        self.assertEqual(self.forge.locks, {})

    def test_green_tip_is_recorded_with_its_duration(self):
        self.advance(1)
        self.assertEqual(self.battery.run('lane-a'), 'drained')
        self.assertEqual(self.tier3.runs, [tip(1)])
        [green] = self.events('battery.green')
        self.assertEqual((green['payload']['sha'], green['payload']['pr'], green['payload']['failing']),
                         (tip(1), None, []))
        self.assertGreater(green['payload']['duration_ms'], 0)
        self.assertEqual(green['producer'], config.get('battery.producer'))
        self.assertEqual(self.events('battery.red'), [])

    def test_coalesces_to_the_newest_tip(self):
        for number in (1, 2, 3):
            self.advance(number)
        self.battery.run('lane-a')
        self.assertEqual(self.tier3.runs, [tip(3)], 'superseded advances are not run')
        self.assertEqual([e['payload']['sha'] for e in self.events('battery.green')], [tip(3)])
        self.assertIsNone(battery.pending_advance(self.events()))

    def test_runs_until_no_newer_tip_is_pending(self):
        self.advance(1)
        self.tier3.during = lambda: (self.advance(2), self.advance(3))
        self.battery.run('lane-a')
        self.assertEqual(self.tier3.runs, [tip(1), tip(3)])
        self.assertNotIn(self.lock_ref, self.forge.locks)

    def test_red_tip_names_the_failing_stage_and_is_not_retried(self):
        self.advance(1)
        self.tier3.red[tip(1)] = 'e2e + a11y'
        with mock.patch('sys.stderr'):
            self.battery.run('lane-a')
        self.assertEqual(self.tier3.runs, [tip(1)], 'D-025: a red run is never retried')
        [red] = self.events('battery.red')
        self.assertEqual((red['payload']['sha'], red['payload']['failing']), (tip(1), ['e2e + a11y']))
        self.assertEqual(self.events('battery.green'), [])
        self.assertFalse(self.battery.pending(), 'a red verdict is a verdict: the tip is not run again')

    def test_every_run_and_step_is_measured_with_the_injected_clock(self):
        self.advance(1)
        self.advance(2)
        self.tier3.red[tip(2)] = 'unit tests'
        with mock.patch('sys.stderr'):
            self.battery.run('lane-a')
        prefix = config.get('battery.step_prefix')
        self.assertEqual(self.steps(), [(prefix + 'tier3', tip(2), 'fail'), (prefix + 'bisect', tip(1), 'ok'),
                                        (prefix + 'bisection', tip(2), 'ok'), (prefix + 'run', tip(2), 'fail')])
        durations = [e['payload']['duration_ms'] for e in self.events('engine.step.measured')]
        self.assertTrue(all(duration > 0 for duration in durations))

    def test_the_log_alone_rebuilds_what_is_pending(self):
        self.advance(1)
        self.battery.run('lane-a')
        self.advance(2)
        again = battery.Battery(self.forge, FakeClock(), self.tier3, REPO)
        self.assertEqual(battery.pending_advance(again.history())['payload']['sha'], tip(2))
        again.run('lane-b')
        self.assertEqual(self.tier3.runs, [tip(1), tip(2)])
        self.assertFalse(again.pending())


class Bisection(Fixture):
    def setUp(self):
        super().setUp()
        self.advance(1)
        self.battery.run('lane-a')  # tip 1 is green
        self.tier3.runs.clear()

    def red_from(self, first, last):
        for number in range(first, last + 1):
            self.tier3.red[tip(number)] = 'unit tests' if number == first else 'e2e + a11y'

    def culprit(self):
        with mock.patch('sys.stderr'):
            self.battery.run('lane-a')
        [culprit] = self.events('battery.culprit')
        return culprit['payload']

    def test_the_first_red_tip_since_the_last_green_names_the_batch(self):
        for number in range(2, 6):
            self.advance(number, prs=2)
        self.red_from(3, 5)
        culprit = self.culprit()
        self.assertEqual((culprit['sha'], culprit['good_sha'], culprit['culprit_sha']), (tip(5), tip(1), tip(3)))
        self.assertEqual((culprit['batch_id'], culprit['prs'], culprit['candidates']),
                         (f'b-{3:012x}', [4, 5], [f'b-{3:012x}']))
        self.assertEqual(culprit['failing'], ['unit tests'], 'the culprit tip\'s own failing stage')
        self.assertEqual(self.tier3.runs[0], tip(5))
        self.assertNotIn(tip(1), self.tier3.runs, 'the green tip is not run again')
        self.assertEqual(culprit['runs'], len(self.tier3.runs) - 1)
        self.assertLessEqual(culprit['runs'], 2)

    def test_a_lone_red_advance_is_the_culprit_without_another_run(self):
        self.advance(2, prs=3)
        self.red_from(2, 2)
        culprit = self.culprit()
        self.assertEqual((culprit['culprit_sha'], culprit['prs'], culprit['runs']), (tip(2), [2, 3, 4], 0))
        self.assertEqual(self.tier3.runs, [tip(2)])

    def test_without_a_green_tip_the_whole_history_is_the_window(self):
        fresh = Fixture('setUp')
        fresh.setUp()
        for number in range(1, 4):
            fresh.advance(number)
        fresh.tier3.red.update({tip(2): 'lint', tip(3): 'lint'})
        with mock.patch('sys.stderr'):
            fresh.battery.run('lane-a')
        [culprit] = fresh.events('battery.culprit')
        self.assertEqual((culprit['payload']['good_sha'], culprit['payload']['culprit_sha']), (None, tip(2)))

    def test_when_the_runs_run_out_the_batches_in_doubt_are_named(self):
        for number in range(2, 7):
            self.advance(number)
        self.red_from(3, 6)
        self.battery.bisection_max_runs = 1  # explicit override: one run cannot settle five tips
        culprit = self.culprit()
        self.assertEqual((culprit['culprit_sha'], culprit['batch_id'], culprit['prs'], culprit['runs']),
                         (None, None, [], 1))
        self.assertEqual(culprit['candidates'], [f'b-{n:012x}' for n in range(2, 5)])
        bisection = [e for e in self.events('engine.step.measured') if e['payload']['step'].endswith('bisection')]
        self.assertEqual(bisection[-1]['payload']['result'], 'blocked')

    def test_the_battery_only_names_it(self):
        self.advance(2)
        self.red_from(2, 2)
        self.culprit()
        kinds = {event['type'] for event in self.events()}
        self.assertEqual(kinds, {'integration.advanced', 'battery.green', 'battery.red', 'battery.culprit',
                                 'engine.step.measured'})
        self.assertEqual(self.forge.locks, {})


class Release(Fixture):
    def setUp(self):
        super().setUp()
        self.battery.release_threshold = 3  # explicit override of release.merged_prs_per_release

    def releases(self):
        return [(e['payload']['sha'], e['payload']['prs'], e['payload']['prs_since_release'])
                for e in self.events('release.ready')]

    def test_the_criterion_is_the_registry_entry(self):
        fresh = battery.Battery(self.forge, self.clock, self.tier3, REPO)
        self.assertEqual(fresh.release_threshold, config.get('release.merged_prs_per_release'))

    def test_green_with_enough_prs_records_release_ready(self):
        self.advance(1, prs=2)
        self.advance(2, prs=2)
        self.battery.run('lane-a')
        self.assertEqual(self.releases(), [(tip(2), [1, 2, 3, 4], 4)])

    def test_below_the_criterion_nothing_is_recorded(self):
        self.advance(1, prs=2)
        self.battery.run('lane-a')
        self.assertEqual(self.releases(), [])

    def test_the_count_restarts_after_each_release(self):
        self.advance(1, prs=3)
        self.battery.run('lane-a')
        self.advance(2, prs=2)
        self.battery.run('lane-a')
        self.assertEqual(self.releases(), [(tip(1), [1, 2, 3], 3)], 'two PRs since the release are not enough')
        self.advance(3, prs=1)
        self.battery.run('lane-a')
        self.assertEqual(self.releases()[-1], (tip(3), [4, 5, 6], 3))

    def test_an_advance_that_landed_before_the_release_does_not_count_it_twice(self):
        self.advance(1, prs=3)
        self.tier3.during = lambda: self.advance(2, prs=1)  # carries prs_since_release 4, stale once tip 1 releases
        self.battery.run('lane-a')
        self.assertEqual(self.releases(), [(tip(1), [1, 2, 3], 3)])
        self.assertEqual(self.tier3.runs, [tip(1), tip(2)])

    def test_a_red_tip_is_never_released(self):
        self.advance(1, prs=5)
        self.tier3.red[tip(1)] = 'lint'
        with mock.patch('sys.stderr'):
            self.battery.run('lane-a')
        self.assertEqual(self.releases(), [])

    def test_release_ready_only_records(self):
        self.advance(1, prs=3)
        self.battery.run('lane-a')
        kinds = {event['type'] for event in self.events()}
        self.assertEqual(kinds, {'integration.advanced', 'battery.green', 'release.ready', 'engine.step.measured'})


class Lock(Fixture):
    def test_a_held_lock_leaves_the_work_to_its_holder(self):
        self.advance(1)
        self.forge.locks[self.lock_ref] = {'owner': 'lane-b', 'expires': '2999-01-01T00:00:00.000Z'}
        self.assertEqual(self.battery.run('lane-a'), 'busy')
        self.assertEqual(self.tier3.runs, [])
        self.assertEqual(self.forge.locks[self.lock_ref]['owner'], 'lane-b')

    def test_an_expired_lock_is_taken_over(self):
        self.advance(1)
        self.forge.locks[self.lock_ref] = {'owner': 'lane-b', 'expires': '2000-01-01T00:00:00.000Z'}
        self.assertEqual(self.battery.run('lane-a'), 'drained')
        self.assertEqual(self.tier3.runs, [tip(1)])

    def test_its_lock_is_not_the_trains(self):
        self.assertNotEqual(self.lock_ref, config.get('train.lock_ref'))
        self.forge.locks[config.get('train.lock_ref')] = {'owner': 'train', 'expires': '2999-01-01T00:00:00.000Z'}
        self.advance(1)
        self.assertEqual(self.battery.run('lane-a'), 'drained')

    def test_a_lost_lock_halts_before_judging_and_the_lock_is_released(self):
        self.advance(1)
        real_lock = self.forge.lock

        def stolen(repo, name, owner, now, expires):
            if len(self.forge.lock_calls) >= 1:
                self.forge.lock_calls.append(owner)
                return False
            return real_lock(repo, name, owner, now, expires)

        self.forge.lock = stolen
        with self.assertRaises(battery.BatteryHalt):
            self.battery.run('lane-a')
        self.assertEqual(self.tier3.runs, [])
        self.assertNotIn(self.lock_ref, self.forge.locks)
        self.assertEqual(self.events('battery.green') + self.events('battery.red'), [])

    def test_the_lease_must_outlast_one_tier3_run(self):
        timeout = config.get('battery.tier3_timeout_s')
        self.assertGreater(config.get('battery.lock_lease_s'), timeout)
        real = config.get
        with mock.patch.object(battery.config, 'get',
                               lambda name: timeout if name == 'battery.lock_lease_s' else real(name)):
            with self.assertRaisesRegex(battery.BatteryError, 'battery.tier3_timeout_s'):
                battery.Battery(self.forge, self.clock, self.tier3, REPO)


class Command(unittest.TestCase):
    def test_the_command_does_nothing_while_the_flag_is_off(self):
        """The flag is pinned off here: the shared store may hold it on (GATE-TRAIN-SERVICES: this test read the live
        store and failed outside the gate's file store)."""
        real = config.get
        off = mock.patch.object(battery.config, 'get',
                                lambda name, *rest: False if name == 'battery.enabled' else real(name, *rest))
        with off, mock.patch.object(battery, 'from_config', lambda: self.fail('a disabled battery must not build its role')):
            with mock.patch('sys.stdout'):
                self.assertEqual(battery.main(['run']), 0)

    def test_the_flag_is_a_registry_flag(self):
        item = config.files()['battery'][1]['properties']['battery.enabled']
        self.assertEqual((item['type'], item['default'], item.get('x-flag')), ('boolean', False, True))

    def test_the_real_tier3_runs_the_registry_command_with_a_fresh_cache(self):
        command = config.get('battery.tier3_command')
        self.assertIn('--tier3', command, 'V7: the tier-3 gate mode, never the WebKit or per-PR database plan')
        prefix = config.get('gate.class_line_prefix')  # the gate's machine class line names the stage (GX-01, GX-02)
        gate = tier3_gate(self, '#!/usr/bin/env bash\necho "cache=$GATE_BUILD_CACHE_DIR args=$*"\n'
                                f'[[ "${{@: -1}}" == good ]] || {{ echo "FAIL e2e + a11y"; '
                                f'printf "{prefix} e2e + a11y\\tcode\\n"; exit 1; }}\n')
        ok, bad = gate.run('good'), gate.run('bad')
        self.assertEqual((ok.ok, ok.stage), (True, None))
        self.assertEqual((bad.ok, bad.stage), (False, 'e2e + a11y'))
        self.assertIn(' '.join(command[1:] + ['good']), ok.log)
        self.assertNotIn(os.environ.get('GATE_BUILD_CACHE_DIR', '<unset>'), ok.log.split('args=')[0])


UNIT = {'id': 'scripts/tests/x.test.sh', 'stage': 'script tests', 'signature': 'AssertionError: expected N to be N'}


class BaseSignal(Fixture):
    """GX-32: tier 3 publishes base.red {tests, since, base_sha} and base.green {cleared}, valid against the locked v1
    contracts (the reader validates every event it returns)."""

    def setUp(self):
        super().setUp()
        self.number = 0

    def next_tip(self):
        self.number += 1
        return self.number

    def green_tip(self):
        number = self.next_tip()
        self.advance(number)
        self.battery.run('lane-a')
        return number

    def red_tip(self, tests=(UNIT,)):
        number = self.next_tip()
        self.advance(number)
        self.tier3.red[tip(number)] = 'unit tests'
        self.tier3.tests[tip(number)] = list(tests)
        with mock.patch('sys.stderr'):
            self.battery.run('lane-a')
        return number

    def test_a_red_tip_publishes_base_red_and_the_next_red_keeps_since(self):
        first, second = self.red_tip(), self.red_tip()
        reds = self.events('base.red')
        self.assertEqual([(e['payload']['base_sha'], e['payload']['since'], e['payload']['tests']) for e in reds],
                         [(tip(first), tip(first), [UNIT]), (tip(second), tip(first), [UNIT])])
        self.assertEqual(reds[0]['payload']['pr'], None)
        self.assertEqual(self.forge_reader_rejected(), [])

    def test_the_first_green_tip_after_a_red_publishes_base_green_once(self):
        self.red_tip()
        green = self.green_tip()
        self.green_tip()
        [event] = self.events('base.green')
        self.assertEqual((event['payload']['base_sha'], event['payload']['cleared']), (tip(green), [UNIT['id']]))
        again = self.red_tip()
        self.assertEqual(self.events('base.red')[-1]['payload']['since'], tip(again))

    def test_a_red_tip_with_no_failing_test_or_the_switch_off_publishes_nothing(self):
        first = self.red_tip(tests=())
        self.assertEqual(self.events('base.red'), [])
        real = config.get
        with mock.patch.object(battery.config, 'get', side_effect=lambda name, *a: False if name == 'defects.base_signal_enabled' else real(name, *a)):
            second = self.red_tip()
        self.assertEqual((self.events('base.red'), self.events('base.green')), ([], []))
        self.assertEqual([e['payload']['sha'] for e in self.events('battery.red')], [tip(first), tip(second)],
                         'the battery verdicts are unchanged')

    def forge_reader_rejected(self):
        reader = forge_events.ForgeEvents(self.forge, self.clock, 'reader', 'test')
        reader.read(REPO, None)
        return reader.rejected

    def test_the_real_tier3_reads_the_failing_tests_from_its_own_report_dir(self):
        gate = tier3_gate(self, '#!/usr/bin/env bash\n[[ "${@: -1}" == good ]] && exit 0\n'
                                'printf \'{"stages": [{"name": "script tests", "result": "FAIL"}]}\' > "$GATE_REPORT_DIR/stages.json"\n'
                                'printf \'[{"test": "scripts/tests/x.test.sh", "result": "FAIL", "tail": ["AssertionError: expected 2 to be 3"]}]\' > "$GATE_REPORT_DIR/script-tests.json"\n'
                                'exit 1\n')
        self.assertEqual((gate.run('bad').ok, gate.failing_tests), (False, [UNIT]))
        self.assertEqual((gate.run('good').ok, gate.failing_tests), (True, []))


class Registry(unittest.TestCase):
    def test_every_battery_entry_is_typed_documented_and_read(self):
        document = config.files()['battery'][1]
        self.assertEqual(document['x-owner'], 'battery')
        for name, item in document['properties'].items():
            with self.subTest(name=name):
                self.assertTrue(name.startswith('battery.'))
                self.assertTrue(item['description'].strip() and item['x-unit'] and item['x-readers'])
                self.assertTrue(all((ROOT / reader).is_file() for reader in item['x-readers']))


if __name__ == '__main__':
    unittest.main()
