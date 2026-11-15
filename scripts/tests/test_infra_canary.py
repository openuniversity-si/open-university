"""DEPLOY-CANARY (docs/operations/aws.md 22.3): the deploy's smoke proves the engine works end to end.

The smoke read two routes of the port's Lambda, so a merged change that broke the service's dispatch or the runner's take
passed it green and no gate was left to land the fix. A canary is one job through the path a check takes: created by the
port (POST /v1/deploy/canary, the installation's token), dispatched by the service, taken and run by the runner; its
verdict (GET /v1/deploy/canary/<id>, a long poll its end wakes) is green when it ended well within
deploy.canary_limit_s and red with the stage that never happened: dispatch (the service), take (the runner), run.

After an image swap and after a reload in place (aws.md 22.9) the same canary runs with no build: the service that took
the role fires it after its first good tick (canary.Live) and its autodeploy when it sees the swap; the ECS task standing
by on the previous code judges it in the statement of its standby pass (live_image.WATCH) and, red, empties both pointers
(image_retired, by: canary); and it reloads onto the swapped bundle only once that canary ended succeeded.

Hermetic: the verdict's table, the long poll on a stand-in wake, the routes' wiring, the measures; the live service's
firing, the standby's judgement on IMAGE-SWAP-FAILOVER's table, the reload's trigger, the autodeploy's look. OnPostgres
runs the real statements on the migrated tables (TEST_DATABASE_URL), with the service's real dispatch tick and the
runner's real TAKE; the smoke script itself is in test_deploy.py (SmokeTests).
"""
import contextlib
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import (autodeploy, canary, code_bundle, config_data, engine, forge, http_port, live_image, mechanisms, port,  # noqa: E402
                         runner, wake)
import config  # noqa: E402
import gate_infra  # noqa: E402
import medir  # noqa: E402
import test_infra_image_swap as image_swap  # noqa: E402
import test_infra_swap_failover as failover  # noqa: E402
import test_infra_swap_reload as reload  # noqa: E402
from test_infra_swap_ready import workflows_with  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
COMMIT = '0123456789abcdef0123456789abcdef01234567'
S, ECS = failover.S, failover.ECS  # the promoted bundle; the ECS tasks' own image
BOTH = sorted(live_image.KEYS.values())


class TheVerdict(unittest.TestCase):
    def test_green_is_a_job_that_ended_succeeded_within_the_limit_with_the_seconds_of_each_stage(self):
        self.assertEqual(canary.verdict('succeeded', 2.0, 120.0, 0.4, 0.5, 1.2), (
            True, 'ended', 'canary job dispatched in 0.4 s, taken in 0.1 s, ended in 0.7 s'))

    def test_it_has_no_verdict_while_it_may_still_end_well_in_time(self):
        for seen, stage in (((None, None, None), 'dispatch'), ((0.4, None, None), 'take'), ((0.4, 0.5, None), 'run')):
            state = 'queued' if seen[0] is None else 'running'
            ok, at, line = canary.verdict(state, 2.0, 120.0, *seen)
            self.assertEqual((ok, at), (None, stage))
            self.assertIn(f'waiting for its {stage}', line)

    def test_red_names_the_stage_that_never_happened_and_whose_it_is(self):
        cases = ((('queued', 121.0, 120.0, None, None, None), 'dispatch', 'not dispatched in 120 s: the service'),
                 (('running', 121.0, 120.0, 0.4, None, None), 'take', 'dispatched in 0.4 s and not taken in 120 s: the runner'),
                 (('running', 121.0, 120.0, 0.4, 0.5, None), 'run', 'taken in 0.1 s and not ended in 120 s: the run'),
                 (('failed', 3.0, 120.0, 0.4, 0.5, 2.0, 'exit_1'), 'run', 'taken in 0.1 s and ended failed (exit_1): the run'),
                 (('failed', 3.0, 120.0, 0.4, 0.5, 2.0, 'not_started'), 'run', 'ended failed (not_started): the run'),
                 (('cancelled', 3.0, 120.0, None, None, None), 'dispatch', 'ended cancelled: the service'))
        for seen, stage, said in cases:
            ok, at, line = canary.verdict(*seen)
            self.assertEqual((ok, at), (False, stage), seen)
            self.assertIn(said, line)

    def test_a_job_that_ended_well_after_the_limit_is_red_at_the_stage_that_was_late(self):
        self.assertEqual(canary.verdict('succeeded', 130.0, 120.0, 0.4, 0.5, 125.0)[:2], (False, 'run'))
        self.assertEqual(canary.verdict('succeeded', 130.0, 120.0, 0.4, 121.0, 125.0)[:2], (False, 'take'))
        self.assertEqual(canary.verdict('succeeded', 130.0, 120.0, 121.0, 122.0, 125.0)[:2], (False, 'dispatch'))

    def test_a_full_runner_is_not_the_services_fault_the_dispatch_may_wait_for_a_slot(self):
        # CANARY-WAITS-FOR-CAPACITY: live 11/11 (#537): the four slots were in long checks at the swap; the canary was
        # dispatched 58 s later, when one ended. Past 120 s it would have been red "not dispatched: the service", the swap
        # undone and the head deployed the slow way, with nothing wrong in the new code
        full = canary.FULL_MAX_S
        ok, stage, line = canary.verdict('queued', 300.0, 120.0, None, None, None, full=True)
        self.assertEqual((ok, stage), (None, 'dispatch'))
        self.assertIn('waiting for a free slot of a full runner (300.0 s', line)
        self.assertEqual(canary.verdict('queued', full + 1, 120.0, None, None, None, full=True)[:2], (False, 'dispatch'))
        # once dispatched, the runner and the run have the limit from the dispatch on
        self.assertEqual(canary.verdict('running', 310.0, 120.0, 300.0, None, None, full=True)[:2], (None, 'take'))
        self.assertEqual(canary.verdict('running', 421.0, 120.0, 300.0, None, None, full=True)[:2], (False, 'take'))
        self.assertEqual(canary.verdict('succeeded', 310.0, 120.0, 300.0, 301.5, 309.0, full=True), (
            True, 'ended', 'canary job dispatched in 300.0 s, taken in 1.5 s, ended in 7.5 s'))
        self.assertEqual(canary.verdict('succeeded', 500.0, 120.0, 300.0, 301.5, 430.0, full=True)[:2], (False, 'run'))
        # without the evidence of a full runner nothing changes: the service has the limit to dispatch
        self.assertEqual(canary.verdict('queued', 121.0, 120.0, None, None, None)[:2], (False, 'dispatch'))
        self.assertEqual(canary.verdict('succeeded', 310.0, 120.0, 300.0, 301.5, 309.0)[:2], (False, 'dispatch'))

    def test_the_look_keeps_the_evidence_of_a_full_runner_and_judges_with_it(self):
        waiting = (*reading('queued', 130.0), True, None)  # READ's two more columns: no free slot now; no evidence kept yet
        db = Reads(waiting)
        said, fresh = canary.look(db, 'torre', 'job-1')
        self.assertEqual((said['ok'], said['stage'], fresh, db.settled), (None, 'dispatch', False, []))
        self.assertEqual(db.sent.count(canary.FULL), 1)  # said once in the log: the dispatch found the runner full
        late = (*reading('succeeded', 310.0, 300.0, 301.5, 309.0), False, 1)  # dispatched at 300 s; the evidence is there
        said, fresh = canary.look(Reads(late), 'torre', 'job-1')
        self.assertEqual((said['ok'], said['line']), (True, 'canary job dispatched in 300.0 s, taken in 1.5 s, ended in 7.5 s'))
        free = (*reading('queued', 130.0), False, None)  # a free slot and no dispatch: the service's, as before
        said, _ = canary.look(Reads(free), 'torre', 'job-1')
        self.assertEqual((said['ok'], said['stage']), (False, 'dispatch'))
        old = reading('queued', 130.0)  # a row as READ gave it before this unit (a stand-in of another suite): as before
        self.assertEqual(canary.look(Reads(old), 'torre', 'job-1')[0]['ok'], False)

    def test_the_limit_is_the_registry_key_and_an_invalid_row_is_its_default(self):
        self.assertEqual(config_data.SPEC[canary.LIMIT], (float, 120.0))
        self.assertEqual([canary.limit_of(stored) for stored in (None, '45', '2.5', '"soon"', '0')], [120.0, 45.0, 2.5, 120.0, 120.0])
        entry = json.loads((ROOT / 'config/registry/deploy/deploy.canary_limit_s.json').read_text())
        self.assertEqual((entry['default'], entry['x-readers']), (120.0, ['infra/service/tower_infra/canary.py']))


class TheJob(unittest.TestCase):
    def test_it_is_a_check_of_the_gate_with_the_command_true_ahead_of_every_check(self):
        self.assertEqual(canary.QUEUE, config.get('gate-infra.check_queue'))
        self.assertEqual(canary.REPO, engine.DEFAULT)
        self.assertGreater(canary.RANK, gate_infra.RANK_PER_CHECK * gate_infra.RANK_CAP - 1)  # the best rank a check has
        self.assertEqual(canary.COMMAND, ['true'])
        self.assertEqual(canary.RESERVED, mechanisms.RESERVED)  # CANARY-OWN-SLOT: the account the dispatch reserves

    def test_the_long_poll_stays_under_the_apis_thirty_seconds(self):
        self.assertLess(canary.WAIT_MAX_S, 30)
        self.assertEqual(canary.WAIT_MAX_S, port.TRAIN_WAIT_MAX_S)


class Reads:
    """READ and TENANT answered from a list of readings (each a job's row as READ gives it); SETTLE kept."""

    def __init__(self, *readings):
        self.readings, self.settled, self.sent = list(readings), [], []

    def rows(self, sql, params=None):
        self.sent.append(sql)
        if sql == canary.TENANT:
            return [('t-1',)]
        if sql == canary.SETTLE:
            self.settled.append(json.loads(params['payload']))
            return [(1,)]
        if sql == canary.READ:
            return [self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]]
        if sql == getattr(canary, 'FULL', None):  # CANARY-WAITS-FOR-CAPACITY: the evidence of a full runner
            return [(1,)]
        if sql.startswith('with cancelled as') or 'work.job' in sql:  # port.cancel_job of a red canary still open
            return []
        raise AssertionError(sql)


def reading(state='queued', age=1.0, started=None, running=None, ended=None, error=None, stored=None, recorded=None):
    return ('job-1', 't-1', 'canary:build-1', state, 1000.0, age, started, running, ended, error,
            json.dumps({'job_id': 'job-1', 'canary': 'build-1'}), stored, recorded)


class Wake:
    def __init__(self, woken=True):
        self.woken, self.waits, self.listened, self.closed = woken, [], 0, 0

    def listening(self):
        self.listened += 1

    def wait(self, timeout_s):
        self.waits.append(timeout_s)
        return self.woken

    def close(self):
        self.closed += 1


class TheLongPoll(unittest.TestCase):
    WHO = ('installation', None)

    def test_it_listens_before_its_first_read_and_answers_when_the_jobs_end_wakes_it(self):
        db, woken = Reads(reading('running', 1.0, 0.4, 0.5), reading('succeeded', 1.4, 0.4, 0.5, 1.2)), Wake()
        said = canary.read(db, self.WHO, 'job-1', '20', woken)
        self.assertEqual((said['ok'], said['stage'], said['seconds'], said['dispatched_s'], said['taken_s'], said['ran_s']),
                         (True, 'ended', 1.2, 0.4, 0.1, 0.7))
        self.assertEqual((woken.listened, len(woken.waits), woken.closed), (1, 1, 1))
        self.assertEqual(db.sent.count(canary.READ), 2)  # one read per wake, no loop on a clock
        self.assertEqual([each['ok'] for each in db.settled], [True])

    def test_the_wait_is_bounded_by_the_port_and_by_the_canarys_own_limit(self):
        db, woken = Reads(reading('queued', 1.0)), Wake(woken=False)
        clock = mock.Mock(side_effect=[0.0, 0.0, 0.0, 99.0])  # the deadline, whether it waits, the time left, the time left after the wait
        said = canary.read(db, self.WHO, 'job-1', '500', woken, clock=clock)
        self.assertEqual((said['ok'], said['stage'], woken.waits), (None, 'dispatch', [canary.WAIT_MAX_S]))
        db, woken = Reads(reading('queued', 1.0, stored='3')), Wake(woken=False)
        canary.read(db, self.WHO, 'job-1', '20', woken, clock=mock.Mock(side_effect=[0.0, 0.0, 0.0, 99.0]))
        self.assertEqual(woken.waits, [2.05])  # its limit passing ends the wait: the red verdict is not a poll away

    def test_without_a_wake_or_a_wait_the_state_is_answered_now(self):
        for wait_s, woken in ((None, Wake()), ('20', None)):
            db = Reads(reading('running', 1.0, 0.4))
            said = canary.read(db, self.WHO, 'job-1', wait_s, woken)
            self.assertEqual((said['ok'], said['stage'], said['age_s'], db.sent.count(canary.READ)), (None, 'take', 1.0, 1))
            self.assertEqual(db.settled, [])  # no verdict yet: nothing recorded
            if woken is not None:
                self.assertEqual((woken.listened, woken.waits), (0, []))

    def test_a_recorded_verdict_is_answered_as_recorded(self):
        kept = {'id': 'job-1', 'ok': False, 'stage': 'take', 'line': 'kept'}
        db = Reads(reading('cancelled', 500.0, 0.4, recorded=json.dumps(kept)))
        self.assertEqual(canary.read(db, self.WHO, 'job-1'), kept)
        self.assertEqual(db.settled, [])

    def test_a_wait_that_is_not_a_number_is_refused(self):
        with self.assertRaises(port.PortError) as refused:
            canary.read(Reads(reading()), self.WHO, 'job-1', 'soon')
        self.assertEqual(refused.exception.status, 400)

    def test_the_route_reads_wait_s_from_the_query_and_waits_on_tower_work(self):
        seen = {}

        def read(db, who, job, wait_s, woken):
            seen.update(job=job, wait_s=wait_s, channels=woken.channels)
            return {'ok': None}
        db = mock.Mock(rows=lambda sql, params=None: [], connect=lambda: None)
        job = '01a1be27-1c2d-7af4-b1e5-e2087696832c'
        with mock.patch.object(canary, 'read', read):
            answer = http_port.handle({'rawPath': f'/v1/deploy/canary/{job}', 'requestContext': {'http': {'method': 'GET'}},
                                       'headers': {'Authorization': 'Bearer installation'}, 'rawQueryString': 'wait_s=20',
                                       'queryStringParameters': {'wait_s': '20'}}, db, port.sha256('installation'))
        self.assertEqual((answer['statusCode'], seen), (200, {'job': job, 'wait_s': '20', 'channels': (wake.WORK,)}))


class TheMeasures(unittest.TestCase):
    def test_medir_leaves_a_canarys_runs_out_of_the_checks_measures(self):
        def events(job, runner, canary_key=None):
            at = lambda second: f'2026-11-10T12:00:{second:02d}+00:00'  # noqa: E731
            return [{'type': 'job.created', 'occurred_at': at(0), 'payload': {'job_id': job, **({'canary': canary_key} if canary_key else {})}},
                    {'type': 'run.started', 'occurred_at': at(1), 'payload': {'job_id': job, 'run_id': f'r-{job}', 'executor': 'fargate-runner'}},
                    {'type': 'run.running', 'occurred_at': at(2), 'payload': {'job_id': job, 'run_id': f'r-{job}', 'executor': 'fargate-runner', 'runner': runner}},
                    {'type': 'run.usage', 'occurred_at': at(3), 'payload': {'job_id': job, 'run_id': f'r-{job}', 'meter': 'cpu_s', 'quantity': 0.5}},
                    {'type': 'run.ended', 'occurred_at': at(9), 'payload': {'job_id': job, 'run_id': f'r-{job}', 'executor': 'fargate-runner'}}]
        check, with_canary = events('check', 'task-a/1'), events('check', 'task-a/1') + events('canary', 'task-b', 'build-1')
        self.assertEqual(medir.from_log(with_canary), medir.from_log(check))
        self.assertEqual(medir.from_log(check)['first_check_s'], [9.0])
        self.assertEqual(len(medir.from_log(events('canary', 'task-b'))['first_check_s']), 1)  # untagged, it would count

    def test_deploy_canary_s_is_the_seconds_of_the_green_canaries_of_the_status(self):
        status = {'canary': [{'ok': True, 'seconds': 1.2}, {'ok': False, 'stage': 'take', 'seconds': None},
                             {'ok': True, 'seconds': 8.5}, {'ok': True, 'seconds': True}, 'x']}
        self.assertEqual(medir.from_deploy_status(status), {'deploy_canary_s': [1.2, 8.5]})
        self.assertEqual(medir.from_deploy_status({}), {})

    def test_a_cover_is_measured_by_what_it_said_when_it_ended(self):
        # SUCCESSOR-LOST: platform.deploy.successor {state: covered, covered_s, end}, in the status's successor rows
        status = {'successor': [{'state': 'covered', 'role': 'runner', 'covered_s': 6.4, 'end': 'live'}, {'state': 'warm'},
                                {'state': 'covered', 'role': 'service', 'covered_s': 11.2, 'end': 'failover'},
                                {'state': 'covered', 'covered_s': True}, 'x']}
        self.assertEqual(medir.from_deploy_status(status), {'image_swap_covered_s': [6.4, 11.2]})

    def test_the_first_job_after_a_swap_is_measured_by_the_swap_s_canary(self):
        # FIRST-JOB-REHEARSED: its creation to its dispatch and its dispatch to its take, the swaps' canaries only
        status = {'canary': [{'ok': True, 'by': 'swap', 'at': 200.0, 'seconds': 4.7, 'dispatched_s': 1.333, 'taken_s': 0.436},
                             {'ok': True, 'by': 'reload', 'at': 190.0, 'seconds': 1.7, 'dispatched_s': 0.31, 'taken_s': 0.059},
                             {'ok': True, 'at': 180.0, 'seconds': 0.6, 'dispatched_s': 0.074, 'taken_s': 0.018},
                             {'ok': False, 'by': 'swap', 'at': 170.0, 'stage': 'take', 'dispatched_s': 0.9, 'taken_s': None},
                             {'ok': True, 'by': 'swap', 'at': 100.0, 'seconds': 4.0, 'dispatched_s': 0.398, 'taken_s': 1.021}]}
        found = medir.from_deploy_status(status)
        self.assertEqual((found['swap_first_job_dispatched_s'], found['swap_first_job_taken_s']),
                         ([1.333, 0.9, 0.398], [0.436, 1.021]))
        since = medir.from_deploy_status(status, since=150.0)  # MEDIR-LANDINGS-SINCE: only what happened from that point
        self.assertEqual((since['swap_first_job_dispatched_s'], since['swap_first_job_taken_s']), ([1.333, 0.9], [0.436]))
        self.assertNotIn('swap_first_job_dispatched_s', medir.from_deploy_status({'canary': [status['canary'][1]]}))


def gate_of(strict=True, pointed=True, reloaded=None, version=7, task='task-1'):
    """What canary.Live reads of the service's gate."""
    return mock.Mock(digest=S, version=version, task=task, tenant='torre', role='service', strict=strict, reloaded=reloaded,
                     pointed=lambda: pointed)


class Asked:
    """canary.settle's stand-in: what it was asked, answering the verdicts in order (the last one repeats)."""

    def __init__(self, *verdicts):
        self.verdicts, self.calls = list(verdicts), []

    def __call__(self, db, tenant, key, said=None, fire=False, publish=None, **_):
        self.calls.append((tenant, key, said, fire))
        found = self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]
        if isinstance(found, Exception):
            raise found
        return found


class TheLiveService(unittest.TestCase):
    """canary.Live: the service that took the role fires its canary after a good tick and reads it until the verdict."""

    def live(self, gate, *verdicts, head='h' * 40):
        db = mock.Mock(rows=mock.Mock(return_value=[(head,)] if head else []))
        asked = Asked(*verdicts)
        patch = mock.patch.object(canary, 'settle', asked)
        patch.start()
        self.addCleanup(patch.stop)
        return canary.Live(gate, lambda: contextlib.nullcontext(db)), asked, db

    def test_a_promoted_standby_fires_the_swaps_canary_once_and_reads_it_until_its_verdict(self):
        live, asked, db = self.live(gate_of(), {'ok': None}, {'ok': None}, {'ok': True})
        for _ in range(6):  # six good ticks
            live.step()
        said = {'digest': S, 'head': 'h' * 40, 'by': 'swap'}
        self.assertEqual(asked.calls, [('torre', f'swap:{S}:7', said, True)] * 3)  # made, read, read: then nothing
        db.rows.assert_called_once_with(canary.HEAD, {'digest': S})  # the swap's head, once

    def test_a_pointer_written_again_is_a_new_swap_and_a_new_canary(self):
        gate = gate_of()
        live, asked, _ = self.live(gate, {'ok': True})
        live.step()
        gate.version = 9
        live.step()
        live.step()
        self.assertEqual([call[1] for call in asked.calls], [f'swap:{S}:7', f'swap:{S}:9'])

    def test_a_service_that_did_not_take_its_role_by_a_pointer_fires_nothing(self):
        for gate in (gate_of(strict=False, pointed=False),  # an ECS task under no pointer: today's path
                     gate_of(strict=False, pointed=True),  # the reconciled ECS task while sharing: the slow path's smoke is its canary
                     gate_of(strict=True, pointed=False)):  # a standby the pointer does not name
            live, asked, db = self.live(gate, {'ok': True})
            live.step()
            self.assertEqual((asked.calls, db.rows.call_count), ([], 0))

    def test_a_reloaded_ecs_service_fires_a_canary_of_its_own_once(self):
        gate = gate_of(strict=False, pointed=False, reloaded={'turn': 0, 'from': ECS}, task='ecs-1')
        live, asked, _ = self.live(gate, {'ok': None}, {'ok': True}, head=None)
        for _ in range(4):
            live.step()
        self.assertEqual(asked.calls, [('torre', f'reload:{S}:0:ecs-1', {'digest': S, 'head': None, 'by': 'reload'}, True)] * 2)
        self.assertTrue(canary.KEY.match(f'reload:{S}:0:ip-10-40-7-34.example.internal'))  # a task's name fits a key

    def test_a_read_that_fails_is_tried_again_and_a_canary_the_port_refuses_is_said_once(self):
        live, asked, _ = self.live(gate_of(), RuntimeError('db down'), {'ok': True})
        with self.assertLogs('tower_infra.canary', 'ERROR'):
            live.step()
        live.step()
        live.step()
        self.assertEqual(len(asked.calls), 2)  # the failed one, then the one that answered
        live, asked, _ = self.live(gate_of(), port.PortError(409, 'the log has no head'))
        with self.assertLogs('tower_infra.canary', 'WARNING') as logged:
            live.step()
        live.step()
        self.assertEqual((len(asked.calls), len(logged.records)), (1, 1))

    def test_the_services_loop_steps_it_after_a_good_tick_and_the_handover(self):
        serve = failover.SERVE
        self.assertIn('proving = None if gate is None else canary.Live(gate, loop.scope)', serve)  # FIRST-JOB-AT-ONCE
        self.assertLess(serve.index('gate.back()  # IMAGE-SWAP-RELOAD'), serve.index('if proving.step():'))
        self.assertLess(serve.index('started = workflows.tick('), serve.index('if proving.step():'))

    def test_the_canary_a_step_just_made_is_dispatched_in_the_same_pass_on_the_loop_s_connection(self):
        # FIRST-JOB-AT-ONCE: live 12/11, ten swaps: the swap's canary waited 0.40 to 1.54 s for its run.started (p50
        # 0.93 s; 1.51 s with the path's statements rehearsed, #592): it was made after the pass's tick, on a pooled
        # connection, and dispatched by the next pass, behind this one's housekeeping and beside every look the swap woke
        serve = failover.SERVE
        made = serve.index('if proving.step():')
        again = serve.index('started += workflows.tick(lease, scope=loop.scope)')
        self.assertEqual(serve[made:again].count('\n'), 1)  # the very next statement: nothing of the pass between them
        for later in ('followed.follow(db)', 'deliver(engine, sinks)'):
            self.assertLess(again, serve.index(later))
        live, asked, _ = self.live(gate_of(), {'ok': None}, {'ok': True})
        self.assertIs(live.step(), True)  # made now: the loop dispatches it at once
        self.assertIs(live.step(), False)  # read until its verdict: no tick of its own
        self.assertIs(live.step(), False)  # and nothing more once it is recorded
        refused, _, _ = self.live(gate_of(), port.PortError(409, 'the log has no head'))
        with self.assertLogs('tower_infra.canary', 'WARNING'):
            self.assertIs(refused.step(), False)  # no canary was made: nothing to dispatch
        away, _, _ = self.live(gate_of(), RuntimeError('the database is away'))
        with self.assertLogs('tower_infra.canary', 'ERROR'):
            self.assertIs(away.step(), False)
        self.assertIs(canary.Live(gate_of(strict=False), None).step(), False)  # an ECS task that took no role by a pointer


class TheSettling(unittest.TestCase):
    """canary.settle: the service's reading of a canary by its key; a red verdict it recorded is published once."""

    class Db(Reads):
        def __init__(self, *readings, job='job-1'):
            super().__init__(*readings)
            self.job = job

        def rows(self, sql, params=None):
            if sql == canary.JOB:
                self.sent.append(sql)
                return [(self.job,)] if self.job else []
            return super().rows(sql, params)

    def test_a_red_verdict_is_recorded_and_published_once(self):
        red = reading('queued', 121.0)
        db, published = self.Db(red), []
        with self.assertLogs('tower_infra.canary', 'WARNING'), mock.patch.object(port, 'cancel_job') as cancelled:
            said = canary.settle(db, 'torre', 'build-1', publish=published.append)
        self.assertEqual((said['ok'], said['stage'], published, len(db.settled)), (False, 'dispatch', [said], 1))
        cancelled.assert_called_once()  # the job left open by the red verdict
        db = self.Db(reading('cancelled', 300.0, recorded=json.dumps(said)))
        self.assertEqual((canary.settle(db, 'torre', 'build-1', publish=published.append), len(published)), (said, 1))

    def test_a_green_or_a_pending_one_publishes_nothing_and_a_missing_one_is_made_only_when_asked(self):
        published = []
        for found, ok in ((reading('succeeded', 2.0, 0.4, 0.5, 1.2), True), (reading('running', 2.0, 0.4), None)):
            self.assertEqual(canary.settle(self.Db(found), 'torre', 'build-1', publish=published.append)['ok'], ok)
        self.assertEqual(published, [])
        db = self.Db(reading('queued', 0.1), job=None)
        self.assertIsNone(canary.settle(db, 'torre', 'build-1'))
        with mock.patch.object(canary, 'start', return_value={'id': 'job-9'}) as start:
            canary.settle(db, 'torre', 'swap:s:1', {'digest': 's'}, fire=True)
        start.assert_called_once_with(db, ('installation', None), {'key': 'swap:s:1'}, {'digest': 's'})

    def test_the_alert_goes_to_the_platforms_topic_and_never_raises(self):
        clients = {}

        def client(name, region_name=None):
            clients[name] = mock.Mock(get_caller_identity=lambda: {'Account': '123456789012', 'Arn': 'arn:aws-partition:iam::123456789012:role/x'})
            return clients[name]
        said = {'key': 'swap:s:1', 'ok': False, 'stage': 'dispatch'}
        with mock.patch.dict(sys.modules, {'boto3': mock.Mock(client=client)}):
            canary.alert(said, {'AWS_REGION': 'us-east-1'})
            sent = clients['sns'].publish.call_args.kwargs
            self.assertEqual((sent['TopicArn'], sent['Subject'], json.loads(sent['Message'])),
                             ('arn:aws-partition:sns:us-east-1:123456789012:tower-platform-events', 'tower deploy canary RED', said))
            canary.alert(said, {'AWS_REGION': 'us-east-1', 'TOWER_ALERTS_TOPIC_ARN': 'arn:aws-partition:sns:us-east-1:1:tower-other'})
            self.assertEqual(clients['sns'].publish.call_args.kwargs['TopicArn'], 'arn:aws-partition:sns:us-east-1:1:tower-other')
        with mock.patch.dict(sys.modules, {'boto3': mock.Mock(client=mock.Mock(side_effect=RuntimeError('no network')))}):
            with self.assertLogs('tower_infra.canary', 'ERROR'):
                canary.alert(said, {'AWS_REGION': 'us-east-1'})


class Watched(failover.Table):
    """IMAGE-SWAP-FAILOVER's table whose WATCH also answers the swap's canary job, as live_image.SWAP_CANARY reads it."""

    def __init__(self, value='', clock=None):
        super().__init__(value, clock)
        self.canary = None  # {id, state, age_s, limit}; None: no such canary
        self.refused = []  # platform.deploy.image_reload {state: failed}: the bundles that must not be loaded again

    def rows(self, sql, params=None):
        if sql == live_image.RELOAD_SAY:
            self.refused.append({**json.loads(params['payload']), 'id': params['id']})
            return []
        found = super().rows(sql, params)
        if sql == live_image.WATCH:
            return [(*found[0], None if self.canary is None else json.dumps(self.canary))]
        if sql == live_image.EMPTY and found:
            self.emptied = params['keys'].split(',')
        return found


class TheJudge(unittest.TestCase):
    """The ECS task standing by judges the swap's canary in the statement of its standby pass."""

    def pair(self, role='service', seen=None):
        """The promoted standby of S, live and beating, and the role's ECS task standing by, on one table."""
        table = Watched(S)
        promoted, ecs = failover.gate_on(table, role, S, strict=True, task='promoted'), failover.gate_on(table, role, ECS, task='ecs')
        self.assertEqual((promoted.refresh(), ecs.refresh()), (True, False))
        table.canary = seen
        return table, promoted, ecs

    def passes(self, table, promoted, ecs, count=3):
        for _ in range(count):  # the promoted service beats: its loop turns
            table.clock.now += 1
            promoted.live_beat()
            ecs.beat()

    def test_a_role_that_beats_while_its_canary_is_green_pending_or_missing_is_left_alone(self):
        for seen in (None, {'id': 'j', 'state': 'succeeded', 'age_s': 500.0, 'limit': None},
                     {'id': 'j', 'state': 'queued', 'age_s': 119.0, 'limit': None},
                     {'id': 'j', 'state': 'running', 'age_s': 4.0, 'limit': 5}):
            table, promoted, ecs = self.pair(seen=seen)
            self.passes(table, promoted, ecs)
            self.assertEqual((ecs.active(), table.events, table.value, table.refused), (False, [], S, []), seen)
            self.assertEqual(set(table.sent[-3:]), {live_image.WATCH, live_image.LIVE_BEAT})  # still one statement a pass

    def test_a_role_that_beats_but_whose_canary_is_red_is_failed_over_and_both_pointers_are_emptied(self):
        cases = (({'id': 'j-1', 'state': 'queued', 'age_s': 120.5, 'limit': None}, 'not dispatched in time'),
                 ({'id': 'j-1', 'state': 'running', 'age_s': 5.5, 'limit': 5}, 'the limit as stored'),
                 ({'id': 'j-1', 'state': 'failed', 'age_s': 2.0, 'limit': None}, 'ended failed: at once'),
                 ({'id': 'j-1', 'state': 'cancelled', 'age_s': 2.0, 'limit': None}, 'cancelled by a red verdict'))
        for role in ('service', 'runner'):  # either ECS task that sees it first
            for seen, why in cases:
                table, promoted, ecs = self.pair(role, seen)
                with self.assertLogs('tower_infra.live_image', 'WARNING'):
                    self.passes(table, promoted, ecs, count=1)
                self.assertEqual(table.sent[-3:], [live_image.WATCH, live_image.EMPTY, live_image.READ], why)  # live in that pass
                [refused] = table.refused  # and the bundle is not loaded again: no reload, no boot from deploy.live_code
                self.assertEqual((refused['state'], refused['digest'], refused['role'], refused['id']),
                                 ('failed', S, role, f'platform.deploy.image_reload:{role}:{S}:failed:canary'), why)
                self.assertIn(f"the canary of its swap is {seen['state']}", refused['why'])
                self.assertEqual((ecs.active(), table.value, sorted(table.emptied)), (True, '', BOTH), why)
                [event] = table.events
                self.assertEqual((event['by'], event['role'], event['digest'], event['task'], event['canary'], event['state'],
                                  event['age_s']), ('canary', role, S, 'ecs', 'j-1', seen['state'], seen['age_s']), why)
                self.assertEqual(event['id'], f'platform.deploy.image_retired:{role}:{S}:canary:1')
                self.assertEqual((promoted.refresh(), promoted.retired), (False, True))  # the promoted standby stands by

    def test_a_dead_role_is_still_the_watchdogs_and_a_promoted_standby_never_judges(self):
        table, promoted, ecs = self.pair(seen={'id': 'j', 'state': 'failed', 'age_s': 2.0, 'limit': None})
        table.clock.now += 11  # no live beat for longer than deploy.live_stale_s
        with self.assertLogs('tower_infra.live_image', 'WARNING'):
            ecs.beat()
        self.assertEqual([event['by'] for event in table.events], ['failover'])
        table, promoted, ecs = self.pair(seen={'id': 'j', 'state': 'failed', 'age_s': 2.0, 'limit': None})
        other = failover.gate_on(table, 'service', 'b' * 64, strict=True, task='standby')
        other.refresh()
        other.beat()
        self.assertEqual((table.sent[-1], table.events), (live_image.BEAT, []))  # a prewarm standby only beats

    def test_the_watch_reads_the_canary_by_the_service_pointer_in_the_same_statement(self):
        self.assertIn(live_image.SWAP_CANARY, live_image.WATCH)
        self.assertIn("j.idempotency_key = 'canary:swap:' || (p.value #>> '{}') || ':' || p.version", live_image.SWAP_CANARY)
        self.assertIn("p.key = 'deploy.live_image_service' and p.value = v.value", live_image.SWAP_CANARY)
        self.assertEqual(live_image.WATCH.count(';'), 0)  # one statement
        self.assertEqual(canary.swap_key(S, 7), f'swap:{S}:7')
        self.assertEqual([canary.failed(*each) for each in (('queued', 121, 120), ('running', 119, 120), ('succeeded', 500, 120),
                                                             ('failed', 1, 120), ('cancelled', 1, 120))],
                         [True, False, False, True, True])


class TheReload(unittest.TestCase):
    """IMAGE-SWAP-RELOAD's trigger also wants the swap's canary ended succeeded: nothing reloads onto an unproven bundle."""

    def pair(self, state):
        pair = reload.Pair()
        pair.table.canary = state
        pair.passes(1, seconds=0.0)  # the pass that sees the swap
        pair.worked()  # the promoted standby's image_live
        return pair

    def test_it_waits_while_the_canary_is_missing_or_open_and_reloads_once_it_ended_succeeded(self):
        for state in (None, 'queued', 'running'):
            pair = self.pair(state)
            pair.passes(5)
            self.assertEqual((pair.bundle.staged, pair.bundle.execed), ([], []), state)
            self.assertEqual(set(pair.table.new()), {live_image.RELOAD_OF}, state)  # a look a pass, nothing else
            pair.table.canary = 'succeeded'
            with self.assertRaises(reload.Replaced):
                pair.passes(1)
            self.assertEqual(len(pair.bundle.execed), 1, state)

    def test_a_red_canary_is_never_reloaded_onto(self):
        for state in ('failed', 'cancelled', 'stopped'):
            pair = self.pair(state)
            pair.passes(5)
            self.assertEqual((pair.bundle.staged, pair.bundle.execed), ([], []), state)

    def test_with_no_canary_in_the_limit_the_task_stays_and_looks_no_more(self):
        pair = self.pair(None)
        with self.assertLogs('tower_infra.live_image', 'INFO') as logged:
            pair.passes(125)
        self.assertIn('no canary of this swap in 120 s: the promoted pair keeps the role', logged.output[-1])
        looks = len(pair.table.new())
        pair.table.canary = 'succeeded'
        pair.passes(5)
        self.assertEqual((len(pair.table.new()), pair.bundle.execed), (looks, []))  # no more looks at this swap


class TheLook(image_swap.World):
    """The autodeploy's look: it fires the newest swap's canary while the service's pointer still names it, records its
    verdict, and a red one empties the pointers that still name the swap (by: canary)."""

    def swapped(self, versions=True):
        self.db.pointer = {key: S for key in live_image.KEYS.values()}
        self.db.events.append((autodeploy.SWAP, {'digest': S, 'head': image_swap.MERGE, 'swapped': True, **(
            {'versions': {key: 1 for key in live_image.KEYS.values()}} if versions else {})}))  # the fake's READ says version 1
        self.db.live = {'runner', 'service'}
        self.watcher.alert = self.published = mock.Mock()

    def look(self, *verdicts):
        asked, rows, self.refused = Asked(*verdicts), self.db.rows, getattr(self, 'refused', [])

        def with_refusals(sql, params=None):  # platform.deploy.image_reload {state: failed}, kept apart from the fake's events
            if sql == live_image.RELOAD_SAY:
                self.refused.append({**json.loads(params['payload']), 'id': params['id']})
                return []
            return rows(sql, params)
        with mock.patch.object(canary, 'settle', asked), mock.patch.object(self.db, 'rows', with_refusals):
            self.watcher.settle_image(self.db, self.heads)
        return asked.calls

    def retired(self):
        return [each for kind, each in self.db.events if kind == 'platform.deploy.image_retired']

    def test_it_fires_the_swaps_canary_while_the_pointer_names_it_and_asks_no_more_once_it_is_green(self):
        self.swapped()
        said = {'digest': S, 'head': image_swap.MERGE, 'by': 'swap'}
        self.assertEqual(self.look({'ok': None}), [('torre', f'swap:{S}:1', said, True)])
        self.assertEqual(self.look({'ok': True, 'line': 'fine'}), [('torre', f'swap:{S}:1', said, True)])
        self.assertEqual((self.look({'ok': True}), self.retired(), self.db.pointer), ([], [], {key: S for key in BOTH}))
        self.assertEqual(self.refused, [])  # a green bundle is refused by nobody

    def test_a_red_canary_empties_the_pointers_that_still_name_the_swap(self):
        self.swapped()
        line = 'canary job not dispatched in 120 s: the service (no run.started)'
        self.look({'ok': False, 'line': line})
        [event] = self.retired()
        self.assertEqual((event['by'], event['why'], sorted(event['keys']), event['digest'], event['head']),
                         ('canary', line, BOTH, S, image_swap.MERGE))
        self.assertEqual(self.db.pointer, {key: '' for key in BOTH})
        self.assertEqual(self.look({'ok': False, 'line': line}), [])  # its verdict is known: nothing asked again
        [refused] = self.refused  # the bundle is not loaded again, said once
        self.assertEqual((refused['state'], refused['digest'], refused['id'], refused['why']),
                         ('failed', S, f'platform.deploy.image_reload:service:{S}:failed:canary',
                          f'the canary of its swap is red: {line}'))

    def test_once_the_pointer_moved_it_only_records_the_verdict_and_fires_nothing(self):
        self.swapped()
        self.db.pointer = {key: '' for key in BOTH}  # failed over by the ECS task already
        self.assertEqual(self.look(None), [('torre', f'swap:{S}:1', {'digest': S, 'head': image_swap.MERGE, 'by': 'swap'}, False)])
        self.assertEqual(self.retired(), [])

    def test_a_swap_with_no_versions_or_an_old_one_is_not_asked_and_a_failure_never_stops_the_way_back(self):
        self.swapped(versions=False)
        self.assertEqual(self.look({'ok': True}), [])
        self.setUp()
        self.swapped()
        self.now[0] += autodeploy.CANARY_LOOK_S + 200  # NEWEST_SWAP's fake puts the swap at 100.0
        self.assertEqual(self.look({'ok': True}), [])
        self.setUp()
        self.swapped()
        self.db.live = set()  # no image_live in 60 s: the revert
        self.now[0] = 100.0 + autodeploy.SWAP_LIMIT_S + 1
        with self.assertLogs('tower_infra.autodeploy', 'ERROR'):
            self.look(RuntimeError('db down'))
        self.assertEqual([event['by'] for event in self.retired()], ['revert'])


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class OnPostgres(unittest.TestCase):
    """The real statements: the canary created by the port, the service's dispatch tick, the runner's TAKE and run."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db, self.port = self.world.db, self.world.port
        self.port('PUT', '/v1/queues/checks', 'torre', {'policy': 'rank'})
        # the shared slots, as before CANARY-OWN-SLOT (DEFAULTS-AS-LIVE made its own slot the default; the tests that
        # want it say so)
        self.port('PUT', f'/v1/config/{canary.SLOT}', 'torre', {'value': 0, 'reason': 'test'})
        self.workflows = workflows_with([])

    def tick(self):
        """The service's dispatch tick (workflows.tick: reap, dispatch, the claimed runs' workflows) on the test's database."""
        @contextlib.contextmanager
        def connected():
            yield self.db
        with mock.patch.object(self.workflows, 'connected', connected):
            return self.workflows.tick('5 minutes')

    def start(self, key='build-1', token='installation', **more):
        return self.port('POST', '/v1/deploy/canary', token, {'key': key, 'commit': COMMIT, **more})

    def read(self, ident, token='installation'):
        return self.port('GET', f'/v1/deploy/canary/{ident}', token)

    def limit(self, seconds):
        self.port('PUT', f'/v1/config/{canary.LIMIT}', 'torre', {'value': seconds, 'reason': 'test'})

    def late(self, ident):
        """The canary's reading once its limit has passed. The limit is set just past the age it has now, so what already
        happened was in time whatever the machine's speed, and what did not is what the verdict names."""
        self.limit(round(self.read(ident)['age_s'] + 0.3, 3))
        time.sleep(0.5)
        return self.read(ident)

    def test_a_drill_is_one_event_that_names_a_bundle_and_a_role_and_arms_only_a_successor_born_before_it(self):
        # SWAP-DRILL: the standby lost at the instant of the swap, induced by an event; the real route and statement
        said = self.port('POST', '/v1/deploy/drill', 'installation', {'digest': S, 'role': 'runner'})
        self.assertEqual({name: said[name] for name in ('digest', 'role', 'kind')},
                         {'digest': S, 'role': 'runner', 'kind': 'lost-at-swap'})
        events = self.db.rows("select tenant_id, producer, payload->>'role' from log.event where type = %(type)s",
                              {'type': live_image.DRILL_EVENT})
        self.assertEqual(events, [(None, port.PRODUCER, 'runner')])
        self.port('POST', '/v1/deploy/drill', 'torre', {'digest': S, 'role': 'service'})  # the configuration tenant may
        for body in ({}, {'digest': 'short', 'role': 'runner'}, {'digest': S, 'role': 'port'}, {'digest': S}):
            with self.assertRaises(port.PortError) as refused:
                canary.drill(self.db, ('installation', None), body)
            self.assertEqual(refused.exception.status, 400)
        born = float(self.db.rows('select extract(epoch from clock_timestamp())::float8')[0][0])
        asked = {'role': 'runner', 'digest': S}
        self.assertEqual(self.db.rows(live_image.DRILL, {**asked, 'born': str(born - 60)}), [('1',)])  # born before it
        self.assertEqual(self.db.rows(live_image.DRILL, {**asked, 'born': str(born + 1)}), [])  # started again after it
        self.assertEqual(self.db.rows(live_image.DRILL, {**asked, 'digest': 'f' * 64, 'born': str(born - 60)}), [])

    def test_a_canary_made_while_every_slot_is_taken_waits_for_one_past_its_limit_and_ends_green(self):
        # CANARY-WAITS-FOR-CAPACITY on the real tables: no free slot of a container executor, so the tick dispatches
        # nothing. The forge's executor has its slot free, as the forge's and the sessions' have in the installation:
        # that is no slot of the canary's (read as one, the runner was never found full: #544 as it landed)
        self.db.rows("update work.capacity set in_use = slots where executor = 'script-runner'")
        self.assertEqual(self.db.rows("select count(*) from work.capacity where in_use < slots"), [('1',)])
        made = self.start()
        self.assertEqual(self.tick(), [])
        self.limit(0.2)
        time.sleep(0.4)  # past the limit: red "not dispatched: the service" before this unit
        waiting = self.read(made['id'])
        self.assertEqual((waiting['ok'], waiting['stage']), (None, 'dispatch'))
        self.assertIn('waiting for a free slot of a full runner', waiting['line'])
        self.assertEqual(self.db.rows(f"select count(*) from log.event where type = '{canary.WAITED}'"), [('1',)])
        self.read(made['id'])
        self.assertEqual(self.db.rows(f"select count(*) from log.event where type = '{canary.WAITED}'"), [('1',)])  # once
        self.port('PUT', '/v1/executors/script-runner/capacity/canary', 'installation', {'slots': '1'})
        self.assertIn('waiting for a free slot', self.read(made['id'])['line'])  # the reserved slot is of who names it
        self.db.rows('update work.capacity set in_use = 0')  # a run ended: the slot is the canary's
        self.limit(120)
        self.assertEqual(len(self.tick()), 1)
        self.world.runner.once()
        said = self.read(made['id'])
        self.assertEqual((said['ok'], said['stage']), (True, 'ended'))
        self.assertGreater(said['dispatched_s'], 0.4)

    def test_with_a_slot_of_its_own_a_canary_made_while_every_slot_is_in_a_check_is_dispatched_at_once(self):
        # CANARY-OWN-SLOT on the real tables: every slot of the checks in use, as with four checks of minutes in flight
        self.port('PUT', f'/v1/config/{canary.SLOT}', 'torre', {'value': 1, 'reason': 'test'})
        self.db.rows('update work.capacity set in_use = slots')
        spec = forge.encode({'repo': canary.REPO, 'ref': 'base', 'commit': COMMIT, 'command': ['true']})
        check = self.port('POST', '/v1/jobs', 'torre', {
            'queue': 'checks', 'rank': 999999, 'selector': {'adapter': 'container'}, 'input_uri': spec,
            'input_digest': 'sha256:check', 'idempotency_key': 'check'})['id']  # a check that waits for a slot
        made = self.start()
        self.assertEqual(self.db.rows('select selector::text from work.job where id = %(id)s::uuid', {'id': made['id']}),
                         [('{"account": "canary", "adapter": "container"}',)])
        capacity = "select account, slots, in_use from work.capacity where executor = 'script-runner' order by account"
        self.assertEqual(self.db.rows(capacity), [('canary', '1', '0'), ('fargate', '2', '2')])  # made by the canary
        self.assertEqual(len(self.tick()), 1)  # the canary alone, at once: before this unit it waited for a check to end
        self.assertEqual((self.world.state(made['id']), self.world.state(check)), ('running', 'queued'))
        self.assertEqual(self.db.rows(capacity), [('canary', '1', '1'), ('fargate', '2', '2')])
        self.world.runner.once()
        said = self.read(made['id'])
        self.assertEqual((said['ok'], said['stage']), (True, 'ended'))
        self.assertEqual(self.db.rows(f"select count(*) from log.event where type = '{canary.WAITED}'"), [('0',)])
        self.assertEqual(self.tick(), [])  # its slot is free again and the check that waits never takes it
        self.assertEqual((self.world.state(check), self.db.rows(capacity)[0]), ('queued', ('canary', '1', '0')))
        self.port('PUT', '/v1/executors/script-runner/capacity/canary', 'installation', {'slots': '0'})
        self.start('build-2')  # the slot taken away by its capacity stays as set: the canary asks, it is not made again
        self.assertEqual((self.tick(), self.db.rows(capacity)[0]), ([], ('canary', '0', '0')))

    def test_the_canary_goes_through_the_services_dispatch_and_the_runners_take_and_ends_green(self):
        made = self.start()
        self.assertEqual((made['key'], made['created'], made['limit_s']), ('build-1', True, 120.0))
        waiting = self.read(made['id'])
        self.assertEqual((waiting['ok'], waiting['stage'], waiting['state']), (None, 'dispatch', 'queued'))
        self.assertEqual(len(self.tick()), 1)  # the service: run.started
        self.assertEqual((self.read(made['id'])['ok'], self.read(made['id'])['stage']), (None, 'take'))
        ended = self.world.runner.once()  # the runner: TAKE (run.running), fetch, prepare, the command, run.ended
        self.assertEqual((ended['outcome'], ended['state'], ended['result']['exit']), ('succeeded', 'succeeded', 0))
        self.assertEqual((self.world.fetched, len(self.world.prepared)), ([COMMIT], 1))  # a checkout of the commit, as a check has
        said = self.read(made['id'])
        self.assertEqual((said['ok'], said['stage'], said['state'], said['key'], said['id']),
                         (True, 'ended', 'succeeded', 'build-1', made['id']))
        self.assertAlmostEqual(said['dispatched_s'] + said['taken_s'] + said['ran_s'], said['seconds'], places=2)
        self.assertRegex(said['line'], r'^canary job dispatched in [0-9.]+ s, taken in [0-9.]+ s, ended in [0-9.]+ s$')
        self.assertEqual(self.read(made['id']), said)  # recorded once, answered as recorded
        events = self.db.rows("select tenant_id, payload::text from log.event where type = 'platform.deploy.canary'")
        self.assertEqual([(tenant, json.loads(payload)) for tenant, payload in events], [(None, said)])
        for token in ('installation', 'torre'):  # the status shows it to whoever the port knows
            self.assertEqual(self.port('GET', '/v1/deploy/status', token)['canary'], [said])
        self.assertEqual(medir.from_deploy_status({'canary': [said]}), {'deploy_canary_s': [said['seconds']]})

    def test_its_job_is_a_check_of_the_queue_tagged_in_the_log_and_made_once_per_key(self):
        made = self.start()
        again = self.start()
        self.assertEqual((again['id'], again['created']), (made['id'], False))
        self.assertNotEqual(self.start('build-2')['id'], made['id'])
        job = self.db.rows("select queue, rank::int, selector::text, memoize, idempotency_key, input_uri from work.job "
                           "where id = %(id)s::uuid", {'id': made['id']})[0]
        self.assertEqual(job[:5], ('checks', str(canary.RANK), '{"adapter": "container"}', 'f', 'canary:build-1'))
        self.assertEqual(forge.decode(job[5]), {'repo': canary.REPO, 'ref': 'refs/heads/mod/roadmap-integration',
                                                'commit': COMMIT, 'command': ['true'], 'timeout_s': canary.TIMEOUT_S})
        created = self.port('POST', '/v1/log/query', 'torre', {'filters': {'type': 'job.created'},
                                                              'payload': {'job_id': made['id']}})['events']
        self.assertEqual([event['payload'] for event in created], [{'job_id': made['id'], 'canary': 'build-1'}])
        check = self.world.job('a-check', 'true')  # any other job says nothing more than before
        plain = self.port('POST', '/v1/log/query', 'torre', {'filters': {'type': 'job.created'}, 'payload': {'job_id': check}})
        self.assertEqual([event['payload'] for event in plain['events']], [{'job_id': check}])

    def test_it_takes_the_slot_ahead_of_the_checks_that_were_already_waiting(self):
        self.world.port('PUT', '/v1/executors/script-runner/capacity/fargate', 'installation', {'slots': '1'})
        spec = forge.encode({'repo': canary.REPO, 'ref': 'base', 'commit': COMMIT, 'command': ['true']})
        check = self.port('POST', '/v1/jobs', 'torre', {
            'queue': 'checks', 'rank': 999999, 'selector': {'adapter': 'container'}, 'input_uri': spec,
            'input_digest': 'sha256:check', 'idempotency_key': 'check'})['id']  # the best rank a check of the gate has
        made = self.start()
        self.tick()
        self.assertEqual((self.world.state(made['id']), self.world.state(check)), ('running', 'queued'))

    def test_a_service_that_dispatches_nothing_is_red_not_dispatched_and_the_job_is_cancelled(self):
        made = self.start()
        said = self.late(made['id'])  # no tick: the service is dead
        self.assertEqual((said['ok'], said['stage'], said['dispatched_s'], said['seconds']), (False, 'dispatch', None, None))
        self.assertRegex(said['line'], r'^canary job not dispatched in [0-9.]+ s: the service \(no run\.started\)$')
        self.assertEqual(self.world.state(made['id']), 'cancelled')  # it never runs later
        self.assertEqual(self.tick(), [])
        self.assertEqual(self.read(made['id']), said)
        self.assertEqual(self.port('GET', '/v1/deploy/status', 'installation')['canary'], [said])
        self.assertEqual(medir.from_deploy_status({'canary': [said]}), {})

    def test_a_runner_that_takes_nothing_is_red_not_taken(self):
        made = self.start()
        self.tick()  # dispatched; no runner takes it
        said = self.late(made['id'])
        self.assertEqual((said['ok'], said['stage'], said['taken_s']), (False, 'take', None))
        self.assertRegex(said['line'], r'^canary job dispatched in [0-9.]+ s and not taken in [0-9.]+ s: the runner \(no run\.running\)$')
        self.assertEqual(self.world.state(made['id']), 'cancelled')
        self.world.runner.once()  # a runner that comes back takes the run it was handed: nothing changes
        self.assertEqual((self.world.state(made['id']), self.read(made['id'])), ('cancelled', said))

    def test_a_run_that_fails_is_red_at_the_run_with_its_error(self):
        made = self.start()
        self.tick()
        with mock.patch.object(self.world.runner, 'fetch', mock.Mock(side_effect=RuntimeError('the forge is down'))):
            self.world.runner.once()
        said = self.read(made['id'])  # within the limit: red at once, not at the limit
        self.assertEqual((said['ok'], said['stage'], said['state']), (False, 'run', 'failed'))
        self.assertRegex(said['line'], r'^canary job taken in [0-9.]+ s and ended failed \(not_started\): the run$')

    def test_a_run_still_going_at_the_limit_is_red_at_the_run(self):
        made = self.start()
        self.tick()
        self.assertTrue(mechanisms.relay(self.db, *self.db.rows(
            "select r.id::text, j.fencing_token from work.run r join work.job j on j.id = r.job_id where j.id = %(id)s::uuid",
            {'id': made['id']})[0], 'run.running', {'runner': 'a-runner-that-hangs'}))
        said = self.late(made['id'])
        self.assertEqual((said['ok'], said['stage']), (False, 'run'))
        self.assertRegex(said['line'], r'^canary job taken in [0-9.]+ s and not ended in [0-9.]+ s: the run$')

    def test_only_the_installation_and_the_configuration_tenant_may_ask(self):
        self.port('POST', '/v1/tenants', 'installation', {'name': 'other', 'token_sha256': port.sha256('other')})
        made = self.start(token='torre')  # the configuration tenant itself: a session measuring live
        self.assertTrue(made['created'])
        self.assertEqual(self.start('build-9', token='other'), {'error': 'only the installation or the configuration tenant may do this'})
        self.assertEqual(self.read(made['id'], token='other'), {'error': 'only the installation or the configuration tenant may do this'})
        self.assertEqual(self.start('build-9', token='nobody'), {'error': 'unknown token'})
        self.assertIn('a canary needs a key', self.start('')['error'])
        self.assertIn('a canary needs a key', self.start('a key with spaces')['error'])
        check = self.world.job('a-check', 'true')
        self.assertEqual(self.read(check), {'error': f'no canary {check}'})  # a job that is not a canary is no canary

    def test_the_commit_is_the_bases_head_as_the_log_knows_it(self):
        refused = self.port('POST', '/v1/deploy/canary', 'installation', {'key': 'build-1'})
        self.assertEqual(refused, {'error': 'the log has no head of refs/heads/mod/roadmap-integration in 7 days: name a commit'})
        head = 'f' * 40
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                     "('push-1', null, 'forge.repository.pushed', clock_timestamp(), 'ingress', 'repository', %(payload)s::jsonb)",
                     {'payload': json.dumps({'delivery': {'event': {'payload': {'refUpdates': [
                         {'ref': 'refs/heads/mod/roadmap-integration', 'after': head}]}}}})})
        made = self.port('POST', '/v1/deploy/canary', 'installation', {'key': 'build-1'})
        spec = forge.decode(self.db.rows("select input_uri from work.job where id = %(id)s::uuid", {'id': made['id']})[0][0])
        self.assertEqual(spec['commit'], head)


@unittest.skipUnless(URL, 'needs TEST_DATABASE_URL (Postgres; local port 54322)')
class SwapOnPostgres(unittest.TestCase):
    """The real statements after an image swap: the canary the promoted service fires, the ECS tasks' watch over it, the
    failover by canary, the reload's trigger and the autodeploy's look."""

    def setUp(self):
        from runner_world import RunnerWorld
        self.world = type('World', (RunnerWorld,), {'runTest': lambda self: None})()
        self.world.setUp()
        self.addCleanup(self.world.doCleanups)
        self.db, self.port = self.world.db, self.world.port
        self.port('PUT', '/v1/queues/checks', 'torre', {'policy': 'rank'})
        self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                     "('push-1', null, 'forge.repository.pushed', clock_timestamp(), 'ingress', 'repository', %(payload)s::jsonb)",
                     {'payload': json.dumps({'delivery': {'event': {'payload': {'refUpdates': [
                         {'ref': 'refs/heads/mod/roadmap-integration', 'after': image_swap.MERGE}]}}}})})
        self.workflows, self.published = workflows_with([]), []
        patch = mock.patch.object(live_image, 'LIVE_BEAT_S', 0.1)
        patch.start()
        self.addCleanup(patch.stop)
        # the landing's swap of both pointers to S, with its record (digest, head, the pointers' versions)
        self.swap = json.loads(self.db.rows(autodeploy.SWAP_WRITE, {
            'tenant': 'torre', 'digest': S, 'keys': ','.join(BOTH), 'reason': 'test', 'id': f'{autodeploy.SWAP}:{image_swap.MERGE}',
            'landed_at': time.time(), 'payload': json.dumps({'digest': S, 'key': 'k', 'head': image_swap.MERGE})})[0][0])
        self.key = canary.swap_key(S, self.swap['versions'][live_image.KEYS['service']])
        self.promoted, self.ecs = self.gate('service', S, strict=True, task='promoted'), self.gate('service', ECS, task='ecs')
        self.ecs_runner = self.gate('runner', ECS, task='ecs-runner')
        self.assertEqual((self.promoted.active(), self.ecs.active(), self.ecs_runner.active()), (True, False, False))
        self.live = canary.Live(self.promoted, live_image.kept(self.db), publish=self.published.append)

    def gate(self, role, digest, strict=False, task=None):
        return live_image.gate(role, digest, live_image.kept(self.db), task=task, strict=strict)

    def tick(self):
        @contextlib.contextmanager
        def connected():
            yield self.db
        with mock.patch.object(self.workflows, 'connected', connected):
            return self.workflows.tick('5 minutes')

    def job(self):
        return self.db.rows(canary.JOB, {'tenant': 'torre', 'key': canary.PREFIX + self.key})[0][0]

    def test_the_step_that_makes_the_swap_s_canary_says_so_and_a_tick_right_after_dispatches_it(self):
        # FIRST-JOB-AT-ONCE on the real tables: the loop's `if proving.step(): workflows.tick(...)`, one pass
        self.assertEqual(self.tick(), [])  # the pass's own tick: nothing queued yet
        self.assertIs(self.live.step(), True)  # the canary is made now
        [run] = self.tick()  # the tick of the same pass: it is claimed (run.started) without waiting for the next pass
        self.assertEqual(self.db.rows("select j.id::text, j.state from work.run r join work.job j on j.id = r.job_id "
                                      "where r.id = %(run)s::uuid", {'run': run}), [(self.job(), 'running')])
        self.assertIs(self.live.step(), False)  # read from then on: no tick of its own

    def pointers(self):
        return [json.loads(row[0]) for row in self.db.rows(
            "select value::text from work.config_value where key = any(string_to_array(%(keys)s, ',')) order by key",
            {'keys': ','.join(BOTH)})]

    def events(self, kind):
        return [json.loads(row[0]) for row in self.db.rows(
            "select payload::text from log.event where type = %(type)s order by occurred_at", {'type': kind})]

    def proven(self, role):
        """What the reload's trigger reads of the swap's canary (RELOAD_OF's fifth column)."""
        return self.db.rows(live_image.RELOAD_OF, {'role': role, 'digest': S, 'tenant': 'torre', 'live': 'none'})[0][4]

    def look(self):
        """The autodeploy's look of whichever service is live: the swap's way back, with its canary."""
        watcher = autodeploy.AutoDeploy(live_image.kept(self.db), {}.get, lambda _: {}, clock=time.time)
        watcher.alert = self.published.append
        watcher.settle_image(self.db, [image_swap.MERGE])

    def test_a_promoted_service_that_beats_but_never_dispatches_is_failed_over_by_the_ecs_task_by_canary(self):
        self.promoted.live_beat()
        self.live.step()  # its first "good" tick dispatched nothing; the canary of the role it took is fired
        job, work = self.job(), self.world.job('queued', 'true')  # and work waits for a service that dispatches nothing
        self.assertEqual(self.proven('service'), 'queued')  # nothing reloads onto a bundle that has not proven itself
        for _ in range(3):  # it beats: the watchdog of IMAGE-SWAP-FAILOVER sees a live role
            self.promoted.live_beat()
            self.ecs.beat()
            self.ecs_runner.beat()
        self.assertEqual((self.pointers(), self.ecs.active(), self.events('platform.deploy.image_retired')), ([S, S], False, []))
        age = float(self.db.rows("select extract(epoch from clock_timestamp() - uuid_extract_timestamp(%(id)s::uuid))::float8",
                                 {'id': job})[0][0])
        self.port('PUT', f'/v1/config/{canary.LIMIT}', 'torre', {'value': round(age + 0.3, 3), 'reason': 'test'})
        until = time.monotonic() + 30
        with self.assertLogs('tower_infra.live_image', 'WARNING'):
            while not self.ecs.active() and time.monotonic() < until:  # the promoted service goes on beating
                self.promoted.live_beat()
                self.ecs.beat()  # the ECS service's standby pass: its beat, the pointer, the live beat and the canary
                time.sleep(0.05)
        [event] = self.events('platform.deploy.image_retired')
        self.assertEqual((event['by'], event['role'], event['task'], event['digest'], event['keys'], event['canary'], event['state']),
                         ('canary', 'service', 'ecs', S, BOTH, job, 'queued'))
        self.assertEqual((self.pointers(), self.ecs.active()), (['', ''], True))  # both roles go back, in one statement
        [refused] = self.events('platform.deploy.image_reload')  # and the bundle is not loaded again
        self.assertEqual((refused['state'], refused['digest'], refused['role'], refused['task']), ('failed', S, 'service', 'ecs'))
        autodeploy.AutoDeploy(live_image.kept(self.db), {}.get, lambda _: {}).live_code(self.db, image_swap.MERGE)  # the look's datum
        self.assertEqual(self.db.rows(code_bundle.LIVE, {'tenant': 'torre'}), [(f'{S}@{image_swap.MERGE}', 't')])
        seen = {'TOWER_CODE_SEEN': 'f' * 64 + '@' + 'e' * 40}  # a task ECS starts later, its definition older than the datum
        with self.assertLogs('tower_infra.code_bundle', 'WARNING'):
            self.assertIsNone(code_bundle.newer(seen, '', lambda environ: (f'{S}@{image_swap.MERGE}', True)))  # its own code
        self.ecs_runner.beat()  # the ECS runner's pass finds its pointer emptied: it works
        self.assertEqual((self.ecs_runner.active(), self.promoted.refresh(), self.promoted.retired), (True, False, True))
        self.assertEqual(len(self.tick()), 2)  # the ECS service, on the previous code, dispatches what waited
        slot = runner.Runner(self.db, self.world.fetch, self.world.prepare, self.world.upload, self.world.workdir,
                             name='ecs-runner', gate=self.ecs_runner)
        self.assertEqual([slot.once()['outcome'], slot.once()['outcome'], self.world.state(work)], ['succeeded'] * 3)
        self.look()  # the ECS service's autodeploy: the verdict is recorded and published, once
        self.look()
        [said] = self.events('platform.deploy.canary')
        self.assertEqual((said['ok'], said['stage'], said['digest'], said['head'], said['by'], said['key']),
                         (False, 'dispatch', S, image_swap.MERGE, 'swap', self.key))
        self.assertEqual(self.published, [said])
        status = self.port('GET', '/v1/deploy/status', 'torre')
        self.assertIsInstance(status['image_retired'][0].pop('at'), float)  # STATUS-EVENTS-AT: when it was emptied
        self.assertEqual((status['canary'], status['image_retired']), ([said], [event]))

    def test_a_swap_that_works_has_a_green_canary_and_only_then_may_the_ecs_tasks_reload(self):
        promoted_runner = self.gate('runner', S, strict=True, task='promoted-runner')
        slot = runner.Runner(self.db, self.world.fetch, self.world.prepare, self.world.upload, self.world.workdir,
                             name='promoted-runner', gate=promoted_runner)
        self.assertEqual(self.tick(), [])  # the promoted service's first tick
        self.promoted.live_beat()
        self.live.step()
        self.assertEqual((self.proven('service'), self.proven('runner')), ('queued', 'queued'))
        self.assertEqual(len(self.tick()), 1)  # the promoted service dispatches the canary
        self.assertEqual(slot.once()['outcome'], 'succeeded')  # the promoted runner takes and runs it
        self.live.step()  # the tick the run's end woke: the verdict
        [said] = self.events('platform.deploy.canary')
        self.assertEqual((said['ok'], said['stage'], said['digest'], said['head'], said['by'], said['key']),
                         (True, 'ended', S, image_swap.MERGE, 'swap', self.key))
        self.assertGreater(said['seconds'], 0)
        for _ in range(2):  # the ECS tasks' passes: a green canary is left alone
            self.promoted.live_beat()
            promoted_runner.live_beat()
            self.ecs.beat()
            self.ecs_runner.beat()
        self.assertEqual((self.pointers(), self.ecs.active(), self.events('platform.deploy.image_retired')), ([S, S], False, []))
        self.assertEqual((self.proven('service'), self.proven('runner')), ('succeeded', 'succeeded'))  # now they may reload
        self.promoted.working()  # the promoted standby's image_live: the swap is not reverted for want of it
        promoted_runner.working()
        self.look()
        self.assertEqual((self.pointers(), self.published, len(self.events('platform.deploy.canary'))), ([S, S], [], 1))
        self.assertEqual(medir.from_deploy_status(self.port('GET', '/v1/deploy/status', 'torre'))['deploy_canary_s'],
                         [said['seconds']])

    def test_the_autodeploy_fires_the_canary_when_the_service_did_not(self):
        self.look()  # the look the landing woke: no canary of the swap yet, and the service's pointer names it
        self.assertEqual(self.world.state(self.job()), 'queued')
        self.live.step()  # the service's own firing answers the same job
        self.assertEqual(len(self.db.rows("select 1 from work.job where starts_with(idempotency_key, 'canary:')")), 1)
        created = self.port('POST', '/v1/log/query', 'torre', {'filters': {'type': 'job.created'}})['events']
        self.assertEqual([event['payload'] for event in created],
                         [{'job_id': self.job(), 'canary': self.key, 'digest': S, 'head': image_swap.MERGE, 'by': 'swap'}])


if __name__ == '__main__':
    unittest.main()
