"""The program coordinator (D-069 CO1): next() over a small graph, every limit from the registry."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import coordinator  # noqa: E402
import forge_events  # noqa: E402
import program  # noqa: E402

real_get = config.get
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
SHA = 'a' * 40


def setUpModule():
    unittest.enterModuleContext(config.use_adapter(forge_events.MemoryAdapter()))


def unit(name, deps=(), wave=1):
    return {'id': name, 'depends_on': list(deps), 'owner': 'lane', 'model': 'm', 'wave': wave, 'done': ['d']}


def plan(*units):
    return {'contract': 'program.v1', 'program': 'p', 'complaint': {'symptom': 's', 'evidence': 'e', 'goal': {
        'metric': 'm', 'comparator': 'gte', 'target': 1, 'unit': 'u'}}, 'units': list(units)}


def event(kind, name, pr=None, at=NOW, **extra):
    payload = {'unit': name.lower(), 'pr': pr, 'sha': extra.pop('sha', None)}
    payload.update(extra)
    return {'type': kind, 'payload': payload, 'occurred_at': at.isoformat(), 'event_id': f'{kind}-{name}-{pr}-{at.timestamp()}-{len(extra)}'}


def state(program, **extra):
    return dict({'program': program, 'now': NOW, 'open_defects': [], 'quota_remaining_percent': None}, **extra)


def room(program):
    """The registered limits with room for every unit of `program`: a test of what launches, and in which order, does not
    depend on the account's cap (coordinator.max_sessions, D-277 and D-281); test_max_sessions sets its own."""
    return dict(coordinator.limits(), max_sessions=len(program['units']))


def acts(program, events=(), limit=None, **extra):
    return coordinator.next(state(program, **extra), list(events), limit or room(program))


def kinds(actions, name):
    return [item for item in actions if item['action'] == name]


class Launch(unittest.TestCase):
    def test_launches_ready_units_only_in_wave_order(self):
        launched = [item['unit'] for item in kinds(acts(plan(unit('A1'), unit('B1', ['A1'], 2))), 'launch')]
        self.assertEqual(launched, ['A1'])

    def test_a_merged_dependency_unblocks(self):
        log = [event('pr.merged', 'A1', 3)]
        self.assertEqual([item['unit'] for item in kinds(acts(plan(unit('A1'), unit('B1', ['A1'], 2)), log), 'launch')], ['B1'])

    def test_running_unit_is_not_launched_again(self):
        self.assertEqual(kinds(acts(plan(unit('A1')), [event('work.assigned', 'A1')]), 'launch'), [])

    def test_max_sessions(self):
        limit = dict(coordinator.limits(), max_sessions=2)
        program = plan(unit('A1'), unit('B1'), unit('C1'))
        self.assertEqual(len(kinds(acts(program, limit=limit), 'launch')), 2)
        self.assertEqual(len(kinds(acts(program, [event('work.assigned', 'A1')], limit=limit), 'launch')), 1)

    def test_a_queued_unit_is_never_launched(self):
        queued = dict(unit('B1'), owner=coordinator.limits()['queue_owner'])
        self.assertEqual([item['unit'] for item in kinds(acts(plan(unit('A1'), queued)), 'launch')], ['A1'])

    def test_the_plan_holds_no_more_live_lanes_than_the_account_runs(self):
        """D-277: the lanes that own units in a program's plan never outnumber coordinator.max_sessions."""
        import re
        limit = coordinator.limits()
        text = (ROOT / 'docs' / 'programs' / 'fluxo-amplo' / 'plan.md').read_text()
        graph = json.loads(re.search(r'```json program\.v1\s*\n(.*?)```', text, re.S).group(1))
        live = {item['owner'] for item in graph['units']} - {limit['queue_owner']}
        self.assertLessEqual(len(live), limit['max_sessions'], sorted(live))

    def test_launch_rate_counts_recent_assignments_only(self):
        limit = dict(coordinator.limits(), launch_rate_max=1, launch_rate_window_s=60, max_sessions=50)
        program = plan(unit('A1'), unit('B1'))
        recent = event('work.assigned', 'Z9', at=NOW - timedelta(seconds=30))
        old = event('work.assigned', 'Z9', at=NOW - timedelta(seconds=300))
        self.assertEqual(kinds(acts(plan(unit('A1'), unit('B1'), unit('Z9', wave=2)), [recent], limit=limit), 'launch'), [])
        self.assertEqual(len(kinds(acts(plan(unit('A1'), unit('B1'), unit('Z9', wave=2)), [old], limit=limit), 'launch')), 1)
        self.assertEqual(len(kinds(acts(program, limit=limit), 'launch')), 1)

    def test_quota_headroom_blocks_launch_but_unknown_quota_does_not(self):
        limit = coordinator.limits()
        low = limit['quota_headroom_percent'] - 1
        self.assertEqual(kinds(acts(plan(unit('A1')), quota_remaining_percent=low), 'launch'), [])
        self.assertEqual(len(kinds(acts(plan(unit('A1')), quota_remaining_percent=limit['quota_headroom_percent']), 'launch')), 1)
        self.assertEqual(len(kinds(acts(plan(unit('A1')), quota_remaining_percent=None), 'launch')), 1)


class Retry(unittest.TestCase):
    def failed(self, count):
        log = []
        for number in range(count):
            log += [event('work.assigned', 'A1', at=NOW + timedelta(seconds=2 * number)), event('session.failed', 'A1', at=NOW + timedelta(seconds=2 * number + 1))]
        return log

    def test_retry_within_budget_relaunches_with_next_attempt(self):
        budget = coordinator.limits()['retry_budget']
        found = kinds(acts(plan(unit('A1')), self.failed(budget)), 'launch')
        self.assertEqual([(item['unit'], item['attempt']) for item in found], [('A1', budget + 1)])

    def test_budget_spent_escalates_and_blocks_dependents(self):
        budget = coordinator.limits()['retry_budget']
        found = acts(plan(unit('A1'), unit('B1', ['A1'], 2)), self.failed(budget + 1))
        self.assertEqual([item['unit'] for item in kinds(found, 'escalate')], ['A1'])
        self.assertEqual(kinds(found, 'launch'), [])
        self.assertEqual(kinds(found, 'mark_blocked'), [{'action': 'mark_blocked', 'unit': 'B1', 'blocked_by': ['A1']}])


class Defects(unittest.TestCase):
    def test_open_defect_opens_a_fix_unit(self):
        self.assertEqual(kinds(acts(plan(unit('A1')), open_defects=['KD-1']), 'open_fix_unit'),
                         [{'action': 'open_fix_unit', 'defect': 'KD-1'}])


class Enqueue(unittest.TestCase):
    def ready_log(self, passed=True, head=SHA):
        log = [event('gate.passed', 'A1', 9, sha=SHA, plan='dev')]
        log[0]['event_id'] = 'gate-1'
        ready = event('pr.ready', 'A1', 9, sha=SHA, evidence='gate-1' if passed else 'missing', premises=[], lane_id='lane')
        return log + [ready]

    def test_ready_pr_resting_on_a_passed_gate_is_enqueued(self):
        found = kinds(acts(plan(unit('A1')), self.ready_log()), 'enqueue')
        self.assertEqual([(item['pr'], item['sha'], item['unit']) for item in found], [(9, SHA, 'A1')])

    def test_ready_without_passed_gate_is_not(self):
        self.assertEqual(kinds(acts(plan(unit('A1')), self.ready_log(passed=False)), 'enqueue'), [])


class Properties(unittest.TestCase):
    def test_pure_and_deterministic(self):
        program, log = plan(unit('A1'), unit('B1', ['A1'], 2)), [event('pr.merged', 'A1', 3)]
        before = repr(log)
        self.assertEqual(acts(program, log), acts(program, log))
        self.assertEqual(repr(log), before)

    def test_every_action_is_in_the_registered_vocabulary(self):
        vocabulary = set(config.get('coordinator.actions'))
        found = acts(plan(unit('A1')), open_defects=['KD-1'])
        self.assertTrue({item['action'] for item in found} <= vocabulary)

    def test_limits_come_from_the_registry(self):
        for name, value in coordinator.limits().items():
            self.assertEqual(value, config.get(f'coordinator.{name}'))


class Run(unittest.TestCase):
    def ports(self):
        calls = {'launch': [], 'route': 0, 'notify': []}
        return calls, {'launch': lambda item, attempt: calls['launch'].append((item['id'], attempt)) or 'session-1',
                       'route': lambda: calls.__setitem__('route', calls['route'] + 1),
                       'notify': calls['notify'].append}

    def test_dry_run_applies_nothing(self):
        calls, ports = self.ports()
        program = plan(unit('A1'))
        done = coordinator.run(program, [], state(program, open_defects=['KD-1']), room(program), ports)
        self.assertTrue(done)
        self.assertEqual((calls['launch'], calls['route'], calls['notify']), ([], 0, []))

    def test_apply_launches_routes_once_and_records_the_assignment(self):
        calls, ports = self.ports()
        emitted = []
        program = plan(unit('A1'))
        coordinator.run(program, [], state(program, open_defects=['KD-1', 'KD-2']), room(program), ports, dry_run=False,
                        emit=lambda kind, payload: emitted.append((kind, payload)))
        self.assertEqual(calls['launch'], [('A1', 1)])
        self.assertEqual(calls['route'], 1)
        self.assertEqual(emitted[0][0], 'work.assigned')
        self.assertEqual(emitted[0][1]['item'], 'p/A1#1')

    def test_cli_briefs_print_every_unit_not_merged(self):
        # B1 (D-204): a unit stays briefed after its start, so every unpushed unit gets its brief, launchable or not.
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(coordinator.main(['run', 'reach-1000-prs-per-day', '--events', '/dev/null', '--briefs']), 0)
        for unit in program.load('reach-1000-prs-per-day')['units']:
            self.assertIn(f"===== brief {unit['id']} =====", out.getvalue())

    def test_apply_refuses_a_stale_launch_flag_before_any_launch(self):
        # L1 (D-206 (d)): the preflight refuses; no unit is assigned and no session starts.
        class Stale:
            name = 'claude'

            def preflight(self):
                raise RuntimeError('launch argv names flags that claude --help does not list: --remote')

            def launch(self, request):
                raise AssertionError('a launch happened after a refused preflight')
        err = io.StringIO()
        with mock.patch('adapters.launcher.adapter', return_value=Stale()), redirect_stderr(err):
            self.assertEqual(coordinator.main(['run', 'reach-1000-prs-per-day', '--events', '/dev/null', '--apply']), 1)
        self.assertIn('--remote', err.getvalue())

    def test_cli_status_and_next_on_an_empty_log(self):
        for command in ('next', 'status'):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(coordinator.main([command, 'reach-1000-prs-per-day', '--events', '/dev/null']), 0)
            self.assertTrue(out.getvalue())

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'live-planning-fold.json').read_text())
AT = {int(version): folded for version, folded in FIXTURE['expected_at'].items()}
MERGED_A1 = [event('pr.merged', 'A1', 1)]


def launched(program, events=(), **extra):
    return [item['unit'] for item in kinds(acts(program, events, **extra), 'launch')]


class LivePlan(unittest.TestCase):
    """Launches read the folded live plan (LP5, D-071); the folds come from the LP2 fixture, not from plan_live."""
    def test_a_held_unit_is_not_launched_and_a_release_launches_it(self):
        self.assertEqual(launched(AT[1], MERGED_A1), ['A2'])
        self.assertEqual(launched(AT[0], MERGED_A1), ['A2', 'A3'])
        self.assertEqual(launched(FIXTURE['expected'], MERGED_A1), ['A0', 'A3'])  # A2 now waits on the prep unit A0

    def test_hold_all_holds_every_launch(self):
        held = dict(AT[0], holds={coordinator.HOLD_ALL: {'reason': 'LAUNCH-HOLD present', 'release_when': 'file removed'}})
        self.assertEqual(launched(held), [])

    def test_launch_hold_file_maps_to_hold_all(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'LAUNCH-HOLD'
            with mock.patch.object(config, 'get', side_effect=lambda key, *a: str(path) if key == 'planner.launch_hold_path' else real_get(key, *a)):
                self.assertFalse(coordinator.launch_hold(folder))
                self.assertEqual(launched(AT[0], **{'launch_hold': coordinator.launch_hold(folder)}), ['A1'])
                path.write_text('')
                self.assertTrue(coordinator.launch_hold(folder))
                self.assertEqual(launched(AT[0], **{'launch_hold': coordinator.launch_hold(folder)}), [])
        self.assertFalse(coordinator.launch_hold(), 'the registry default is no brake')

    def test_priority_orders_launches_inside_a_wave(self):
        ranked = dict(AT[0], priority={'A3': 0, 'A2': 1})
        self.assertEqual(launched(ranked, MERGED_A1), ['A3', 'A2'])
        self.assertEqual(launched(AT[0], MERGED_A1), ['A2', 'A3'])

    def test_launch_carries_the_plan_version(self):
        found = kinds(acts(AT[1], MERGED_A1), 'launch')
        self.assertEqual({item['plan_version'] for item in found}, {1})
        self.assertEqual(kinds(acts(plan(unit('A1'))), 'launch')[0]['plan_version'], 0)

    def test_provider_seam_folds_the_plan_and_defaults_to_the_log(self):
        seen = []
        folded = coordinator.live_plan(FIXTURE['plan'], provider=lambda base: seen.append(base) or AT[1])
        self.assertEqual((folded['version'], seen), (1, [FIXTURE['plan']]))
        self.assertEqual(coordinator.plan_version(coordinator.live_plan(FIXTURE['plan'], provider=lambda base: base)), 0)


class StaleLaunch(unittest.TestCase):
    def apply(self, decided, current, events=MERGED_A1):
        launches, emitted = [], []
        ports = {'launch': lambda entry, attempt: launches.append(entry['id']) or 's', 'route': lambda: 0, 'notify': lambda text: None}
        done = coordinator.run(decided, list(events), state(decided), room(decided), ports, dry_run=False,
                               emit=lambda kind, payload: emitted.append(payload), reread=lambda: current)
        return done, launches

    def test_a_launch_decided_before_a_change_to_that_unit_is_refused(self):
        done, launches = self.apply(AT[0], AT[1])  # v1 holds A3 and adds a brief line to A2
        self.assertEqual(launches, [])
        self.assertEqual([(item['unit'], item['plan_version'], item['current_plan_version']) for item in done if item.get('refused')],
                         [('A2', 0, 1), ('A3', 0, 1)])

    def test_a_version_move_that_does_not_touch_the_unit_does_not_refuse(self):
        done, launches = self.apply(AT[0], dict(AT[0], version=AT[1]['version'], brief_lines={'A2': ['new fact']}))
        self.assertEqual(launches, ['A3'])
        self.assertEqual([item['unit'] for item in done if item.get('refused')], ['A2'])

    def test_a_changed_brief_line_or_priority_refuses(self):
        moved = dict(AT[0], brief_lines={'A2': ['new fact']})
        self.assertEqual(self.apply(AT[0], moved)[1], ['A3'])  # A2 refused, A3 untouched
        self.assertEqual(self.apply(AT[0], dict(AT[0], priority={'A3': 0}))[1], ['A2'])

    def test_hold_all_after_the_decision_refuses_everything(self):
        brake = dict(AT[0], holds={coordinator.HOLD_ALL: {'reason': 'x', 'release_when': 'y'}})
        self.assertEqual(self.apply(AT[0], brake)[1], [])


class BriefLines(unittest.TestCase):
    def test_brief_lines_of_the_folded_plan_reach_the_brief(self):
        import coordinator_launch
        folded = FIXTURE['expected']
        text = coordinator_launch.render_brief(folded, folded['units'][1], 1)
        self.assertIn('## Live plan notes\n- use the root from OU_SUBJECT_ROOT', text)
        self.assertLess(text.index('## Applied lessons'), text.index('## Live plan notes'))
        self.assertLess(text.index('## Live plan notes'), text.index('## Known defects'))
        other = coordinator_launch.render_brief(folded, folded['units'][0], 1)
        self.assertIn('## Live plan notes\nNone.', other)
        self.assertIn('## Live plan notes\nNone.', coordinator_launch.render_brief(plan(unit('A1')) | {'complaint': folded['complaint']}, unit('A1'), 1))


if __name__ == '__main__':
    unittest.main()
