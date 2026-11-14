"""The measures of the phase-1 path (engine-medir; MEDIR 1, P6 F1).

The nearest-rank quantiles; the measures the infrastructure's log carries (the forge's seconds by action, each run's
seconds by executor, the checks' CPU seconds), read page by page from a port; the cost of each run, its usage priced
by the tenant's meter rates as the log keeps them (MEDIR 2); the merges scripts/deliver measured, from its logs; the
shadow's agreement with the box, head by head (GATE-INFRA 4, P5 F3); and with no port only the deliveries are read. No
network.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import medir  # noqa: E402


def event(name, kind, at, **payload):
    return {'event_id': name, 'type': kind, 'occurred_at': at, 'payload': payload}


LOG = [event('started', 'run.started', '2026-11-04T20:00:00+00:00', run_id='r', executor='fargate-runner'),
       event('usage', 'run.usage', '2026-11-04T20:00:01+00:00', meter='cpu_s', quantity=float('1.5')),
       event('ended', 'run.ended', '2026-11-04T20:00:02.5+00:00', run_id='r', executor='fargate-runner'),
       event('merged', 'run.usage', '2026-11-04T20:00:03+00:00', meter='forge_merge_s', quantity=float('0.4')),
       event('viewed', 'run.usage', '2026-11-04T20:00:04+00:00', meter='forge_view_s', quantity=float('0.2')),
       event('alone', 'run.ended', '2026-11-04T20:00:05+00:00', run_id='never-started', executor='origin-forge'),
       event('hook', 'forge.pull_request.created', '2026-11-04T20:00:06.25+00:00',
             delivery={'event': {'id': 'evt_1', 'eventTime': '2026-11-04T20:00:06Z'}})]


class Pages:
    """A port whose log answers in pages of the registry's size, from the point asked."""

    def __init__(self, found):
        self.found, self.asked = found, []

    def call(self, method, path, body):
        self.asked.append(body['since'])
        after = [item for item in self.found if body['since'] is None or item['occurred_at'] >= body['since']]
        return {'events': after[:body['limit']]}


class Measures(unittest.TestCase):
    def test_the_quantiles_are_the_nearest_rank(self):
        values = [float(value) for value in range(1, int('101'))]
        self.assertEqual((medir.quantile(values, float('0.5')), medir.quantile(values, float('0.99'))),
                         (float('50'), float('99')))
        self.assertEqual(medir.quantile([float('7')], float('0.99')), float('7'))
        self.assertIsNone(medir.quantile([], float('0.5')))

    def test_the_log_carries_the_forge_the_runs_and_the_checks(self):
        measures = medir.from_log(LOG)
        self.assertEqual(measures, {'cpu_s': [float('1.5')], 'run_s:fargate-runner': [float('2.5')],
                                    'forge_merge_s': [float('0.4')], 'forge_view_s': [float('0.2')],
                                    'webhook_s': [float('0.25')]})  # the forge's eventTime to the log

    def test_a_forge_runs_orchestration_is_its_seconds_less_its_call_to_origin(self):
        log = [event('s', 'run.started', '2026-11-08T17:48:12.2+00:00', run_id='r', job_id='j', executor='origin-forge'),
               event('u', 'run.usage', '2026-11-08T17:48:13.3+00:00', run_id='r', meter='forge_view_s', quantity=1.0),
               event('e', 'run.ended', '2026-11-08T17:48:13.4+00:00', run_id='r', job_id='j', executor='origin-forge'),
               event('s2', 'run.started', '2026-11-08T17:48:14+00:00', run_id='c', job_id='k', executor='fargate-runner'),
               event('e2', 'run.ended', '2026-11-08T17:48:15+00:00', run_id='c', job_id='k', executor='fargate-runner')]
        measures = medir.from_log(log)
        self.assertEqual([round(each, 3) for each in measures['orchestration_s:origin-forge']], [0.2])
        self.assertNotIn('orchestration_s:fargate-runner', measures)  # only the runs that called Origin

    def test_first_check_s_is_the_first_run_of_each_new_runner_task(self):
        def run(name, job, task, running, end):
            return [event(f'{name}-s', 'run.started', running, run_id=name, job_id=job, executor='fargate-runner'),
                    event(f'{name}-r', 'run.running', running, run_id=name, job_id=job, runner=task),
                    event(f'{name}-e', 'run.ended', end, run_id=name, job_id=job, executor='fargate-runner')]
        log = [event('ja', 'job.created', '2026-11-04T20:00:00+00:00', job_id='A'),
               event('jb', 'job.created', '2026-11-04T20:01:00+00:00', job_id='B'),
               event('jc', 'job.created', '2026-11-04T20:05:00+00:00', job_id='C'),
               *run('ra', 'A', 'task-1', '2026-11-04T20:00:30+00:00', '2026-11-04T20:01:40+00:00'),
               *run('rb', 'B', 'task-1/1', '2026-11-04T20:01:50+00:00', '2026-11-04T20:02:00+00:00'),  # warm, not first
               *run('rc', 'C', 'task-2', '2026-11-04T20:05:20+00:00', '2026-11-04T20:05:50+00:00')]
        self.assertEqual(medir.from_log(log)['first_check_s'], [100.0, 50.0])
        self.assertNotIn('first_check_s', medir.from_log(LOG))
        self.assertNotIn('first_check_after_loss_s', medir.from_log(log))

    def test_a_job_run_again_after_its_task_was_lost_is_not_a_cold_start(self):
        # FIRST-CHECK-NOT-A-RETRY: live 12/11 08:38 UTC the Spot took the runner's task in the middle of a check; the job
        # was run again from its start on the next task, 85 s later, and its 620 s from the job's creation were read as
        # the worst cold start of the window (the others: 2.7 to 5.9 s)
        def attempt(name, n, task, started, end, outcome):
            return [event(f'{name}-s', 'run.started', started, run_id=name, job_id='J', executor='fargate-runner', n=n),
                    event(f'{name}-r', 'run.running', started, run_id=name, job_id='J', runner=task),
                    event(f'{name}-e', 'run.ended', end, run_id=name, job_id='J', executor='fargate-runner', n=n, outcome=outcome)]
        log = [event('j', 'job.created', '2026-11-12T08:34:00+00:00', job_id='J'),
               event('k', 'job.created', '2026-11-12T08:50:00+00:00', job_id='K'),
               *attempt('r1', 1, 'task-old/2', '2026-11-12T08:34:01+00:00', '2026-11-12T08:38:17+00:00', 'lost'),
               *attempt('r2', 2, 'task-new/1', '2026-11-12T08:39:45+00:00', '2026-11-12T08:44:20+00:00', 'succeeded'),
               event('k-s', 'run.started', '2026-11-12T08:50:01+00:00', run_id='rk', job_id='K', executor='fargate-runner', n=1),
               event('k-r', 'run.running', '2026-11-12T08:50:01+00:00', run_id='rk', job_id='K', runner='task-new/1'),
               event('k-e', 'run.ended', '2026-11-12T08:50:04+00:00', run_id='rk', job_id='K', executor='fargate-runner', n=1)]
        measures = medir.from_log(log)
        self.assertEqual(measures['first_check_s'], [257.0])  # the old task's first run: its own job's first attempt
        self.assertEqual(measures['first_check_after_loss_s'], [620.0])  # the new task's first run: the job run again

    def test_prewarm_s_is_the_seconds_of_each_warm_runner_task_that_succeeded(self):
        # RUNNER-WARM-STATUS: the warm-ups are installation events the tenant's log never returns; the status carries them
        status = {'runner_warm': [{'task': 't1', 'seconds': 30.0, 'ok': True}, {'task': 't2', 'seconds': 90.0, 'ok': True},
                                  {'task': 't3', 'seconds': 5.0, 'ok': False}]}
        self.assertEqual(medir.from_deploy_status(status)['prewarm_s'], [30.0, 90.0])
        self.assertNotIn('prewarm_s', medir.from_log(LOG))

    def test_medir_prints_the_cold_start_line_and_a_note_when_none(self):
        for events, expected in (([], 'n=0 p50=None max=None'), (None, 'n=2 p50=50.0 max=100.0')):
            if events is None:
                events = [event('ja', 'job.created', '2026-11-04T20:00:00+00:00', job_id='A'),
                          event('rs', 'run.running', '2026-11-04T20:00:30+00:00', run_id='ra', job_id='A', runner='t1'),
                          event('re', 'run.ended', '2026-11-04T20:01:40+00:00', run_id='ra', job_id='A',
                                executor='fargate-runner'),
                          event('jc', 'job.created', '2026-11-04T20:05:00+00:00', job_id='C'),
                          event('rs2', 'run.running', '2026-11-04T20:05:20+00:00', run_id='rc', job_id='C', runner='t2'),
                          event('re2', 'run.ended', '2026-11-04T20:05:50+00:00', run_id='rc', job_id='C',
                                executor='fargate-runner')]
                for each in events:
                    if each['type'] == 'run.running':
                        events.append(event(each['event_id'] + 's', 'run.started', each['occurred_at'],
                                            run_id=each['payload']['run_id'], job_id=each['payload']['job_id'],
                                            executor='fargate-runner'))
                        break
            out = io.StringIO()
            with mock.patch.dict(os.environ, {'TOWER_PORT_URL': 'u', 'TOWER_PORT_TOKEN': 't'}), \
                    mock.patch.object(medir, 'events', return_value=events), \
                    mock.patch.object(medir, 'from_deliveries', return_value=[]), \
                    mock.patch.object(medir, 'from_shadows', return_value={'pairs': 0, 'ready_to_landed_s': [],
                                                                           'ready_to_merged_s': []}), \
                    mock.patch.dict(sys.modules, {'gate_infra': mock.Mock()}), contextlib.redirect_stdout(out):
                medir.main([])
            self.assertIn('first_check_s after runner task change: ' + expected, out.getvalue())
            self.assertEqual('no runner task started' in out.getvalue(), expected.startswith('n=0'))

    def test_a_runners_waits_are_its_take_and_the_dispatch_after_a_slot_freed(self):
        # INFRA-SVC 5 and INFRA-EXE 1e cut these: the runner's poll (take_s) and the dispatcher's tick (dispatch_s)
        def run(name, job, start, running, end=None, executor='fargate-runner'):
            found = [event(f'{name}-started', 'run.started', start, run_id=name, job_id=job, executor=executor)]
            found += [event(f'{name}-running', 'run.running', running, run_id=name, job_id=job)] if running else []
            return found + ([event(f'{name}-ended', 'run.ended', end, run_id=name, job_id=job, executor=executor)]
                            if end else [])
        log = [event('job-a', 'job.created', '2026-11-04T20:00:00+00:00', job_id='A'),
               event('job-b', 'job.created', '2026-11-04T20:00:00+00:00', job_id='B'),  # waiting behind A
               *run('ra', 'A', '2026-11-04T20:00:01+00:00', '2026-11-04T20:00:01.5+00:00', '2026-11-04T20:00:04+00:00'),
               *run('rb', 'B', '2026-11-04T20:00:04.25+00:00', '2026-11-04T20:00:04.75+00:00',
                    '2026-11-04T20:00:06+00:00'),
               event('job-c', 'job.created', '2026-11-04T20:00:10+00:00', job_id='C'),  # after the slot freed
               *run('rc', 'C', '2026-11-04T20:00:10.5+00:00', '2026-11-04T20:00:11+00:00'),
               *run('rl', 'A', '2026-11-04T20:00:12+00:00', None, '2026-11-04T20:00:13+00:00', executor='origin-forge')]
        measures = medir.from_log(log)
        self.assertEqual(measures['take_s:fargate-runner'], [float('0.5')] * len('abc'))
        self.assertEqual(measures['dispatch_s:fargate-runner'], [float('0.25')])  # B, from A's end; C waited for nothing
        self.assertFalse([name for name in measures if name.endswith(':origin-forge') and not name.startswith('run_s')])

    def test_each_runs_usage_priced_by_the_tenants_rates_is_its_cost(self):
        model = 'anthropic.claude-haiku-5-5'
        priced = [event('rate-in', 'limit.rate.defined', '2026-11-04T20:00:00+00:00', meter=f'tokens_in:{model}',
                        derived_meter='usd', rate='0.0000001'),
                  event('rate-out', 'limit.rate.defined', '2026-11-04T20:00:00+00:00', meter=f'tokens_out:{model}',
                        derived_meter='usd', rate='0.0000005'),
                  *(event(f'{run}-{meter}', 'run.usage', '2026-11-04T20:01:00+00:00', run_id=run,
                          executor='api-bedrock', meter=f'{meter}:{model}', quantity=quantity)
                    for run, meter, quantity in (('one', 'tokens_in', int('20')), ('one', 'tokens_out', int('4')),
                                                 ('two', 'tokens_in', int('10')), ('two', 'api_s', float('0.5'))))]
        measures = medir.from_log(priced)
        self.assertEqual([round(cost, int('9')) for cost in measures['cost_usd:api-bedrock']],
                         [float('0.000004'), float('0.000001')])
        with mock.patch.object(medir.config, 'get', side_effect=lambda key: {'medir.quantiles': [float('0.5')]}.get(key)):
            self.assertEqual(round(medir.summary(measures['cost_usd:api-bedrock'], total=True)['sum'], int('9')),
                             float('0.000005'))
            self.assertNotIn('sum', medir.summary([float('1')]))

    def test_the_box_and_the_shadow_are_paired_head_by_head_and_a_pr_agrees_when_all_its_heads_do(self):
        def kept(folder, name, **verdict):
            (Path(folder) / name).write_text(json.dumps(verdict))
        with tempfile.TemporaryDirectory() as folder:
            for pr, head, box, shadow in (('7', 'a1', 'green', 'green'), ('7', 'a2', 'red', 'red'),
                                          ('8', 'b1', 'green', 'red'), ('9', 'c1', 'green', 'moved')):
                kept(folder, f'box-{pr}-{head}.json', pr=pr, head=head, verdict=box)
                kept(folder, f'pr-{pr}-{head}.json', pr=int(pr), head=head, verdict=shadow, ready_to_landed_s=None,
                     red=['stage:lint'] if shadow == 'red' and pr == '8' else [],
                     unprepared=['stage:lint'] if pr == '8' else [])
            kept(folder, 'pr-10-d1.json', pr=int('10'), head='d1', verdict='green', ready_to_landed_s=float('1.5'))
            kept(folder, 'pr-12-f1.json', pr=int('12'), head='f1', verdict='green', shadow=False,  # GATE-INFRA 10
                 ready_to_landed_s=float('1.25'))
            (Path(folder) / 'box-11-e1.json').write_text('{not json')
            agreement = medir.from_shadows(folder)
        self.assertEqual({key: agreement[key] for key in ('pairs', 'same', 'unprepared', 'prs', 'prs_same')},
                         {'pairs': int('3'), 'same': len(('a1', 'a2')), 'unprepared': 1, 'prs': len(('7', '8')),
                          'prs_same': 1})
        self.assertEqual(agreement['differ'], [{'pr': '8', 'head': 'b1', 'box': 'green', 'shadow': 'red',
                                                'red': ['stage:lint'], 'unprepared': True}])
        self.assertEqual(agreement['ready_to_landed_s'], [float('1.5')])  # the shadow's dry run
        self.assertEqual(agreement['ready_to_merged_s'], [float('1.25')])  # a real merge, after the switch
        self.assertEqual(agreement['needed'], medir.config.get('medir.shadow_prs'))

    def test_the_seconds_to_land_are_those_kept_since_a_point_and_the_agreement_all_of_them(self):
        # MEDIR 4: a deploy's effect is read from its own samples; the agreement keeps every pair
        with tempfile.TemporaryDirectory() as folder:
            for pr, seconds in (('7', float('2')), ('8', float('1.25'))):
                (Path(folder) / f'box-{pr}-h.json').write_text(json.dumps({'pr': pr, 'head': 'h', 'verdict': 'green'}))
                (Path(folder) / f'pr-{pr}-h.json').write_text(json.dumps({'pr': int(pr), 'head': 'h', 'verdict': 'green',
                                                                          'ready_to_landed_s': seconds}))
            old = Path(folder) / 'pr-7-h.json'
            os.utime(old, (old.stat().st_atime, old.stat().st_mtime - int('3600')))
            agreement = medir.from_shadows(folder, since=old.stat().st_mtime + 1)
        self.assertEqual((agreement['prs_same'], agreement['ready_to_landed_s']), (len('78'), [float('1.25')]))

    def test_the_switch_needs_the_agreement_and_a_landing_within_the_slack_of_the_boxs_merge(self):
        slack = medir.config.get('medir.landing_slack_s')
        agreement = {'prs_same': 1, 'needed': 1, 'ready_to_landed_s': [float('1.4')],
                     'judged_s': {'box': [float('150')], 'shadow': [float('90')]}}
        self.assertTrue(medir.switch(agreement, [float('1.4') - slack])[0])
        ready, why = medir.switch(dict(agreement, prs_same=0), [float('1.4')])
        self.assertEqual((ready, why), (False, 'not yet: 0 of 1 PRs judged the same'))
        ready, why = medir.switch(agreement, [float('1')])
        self.assertFalse(ready)
        self.assertIn('ready to landed p50 1.40 s over the box merge p50 1.00 s', why)
        self.assertEqual(medir.switch(dict(agreement, ready_to_landed_s=[]), [float('1')]),
                         (False, 'not yet: no ready to landed sample yet'))

    def test_the_switch_also_needs_the_infrastructure_to_judge_no_slower_than_the_box(self):
        # MEDIR 5, the lesson of 05/11: the switch went back after 393 s against the box's ~150 s on the same head
        agreement = {'prs_same': 1, 'needed': 1, 'ready_to_landed_s': [float('1.4')],
                     'judged_s': {'box': [float('150')], 'shadow': [float('393')]}}
        ready, why = medir.switch(agreement, [float('1.4')])
        self.assertEqual((ready, why), (False, 'not yet: the infrastructure judges in 393 s against the box gate '
                                               '150 s (p50 of 1 heads both timed; 0 of 1 judged heads have no box time)'))
        ready, why = medir.switch(dict(agreement, judged_s={'box': [], 'shadow': []}), [float('1.4')])
        self.assertEqual((ready, why), (False, 'not yet: no head timed by both the box and the shadow yet'))

    def test_the_heads_both_timed_give_the_seconds_each_judged_them_in(self):
        with tempfile.TemporaryDirectory() as folder:
            for pr, box, shadow in (('7', float('150'), float('90')), ('8', None, float('60'))):
                (Path(folder) / f'box-{pr}-h.json').write_text(json.dumps(
                    {'pr': pr, 'head': 'h', 'verdict': 'green', **({'seconds': box} if box else {})}))
                (Path(folder) / f'pr-{pr}-h.json').write_text(json.dumps(
                    {'pr': int(pr), 'head': 'h', 'verdict': 'green', 'seconds': shadow}))
            self.assertEqual(medir.from_shadows(folder)['judged_s'],
                             {'box': [float('150')], 'shadow': [float('90')], 'judged': len('ab'), 'untimed': 1})

    def test_a_backfilled_head_is_timed_by_the_boxs_lock_log_and_the_untimed_are_counted(self):
        # MEDIR 5: the box's verdict a backfill keeps has no seconds; the lock log says how long its gate held the box
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'gate-lock.jsonl'
            log.write_text('\n'.join(json.dumps(row) for row in (
                {'pr': 7, 'held_s': float('30')}, {'pr': 7, 'held_s': float('50')}, {'pr': None, 'held_s': 9},
                {'pr': 9, 'held_s': float('0')})) + '\nnot json\n')
            for pr in ('7', '8', '9'):
                (Path(folder) / f'box-{pr}-h.json').write_text(json.dumps({'pr': pr, 'head': 'h', 'verdict': 'green'}))
                (Path(folder) / f'pr-{pr}-h.json').write_text(json.dumps(
                    {'pr': int(pr), 'head': 'h', 'verdict': 'green', 'seconds': float('90')}))
            judged = medir.from_shadows(folder, lock_log=log)['judged_s']
            self.assertEqual(medir.held_by_pr(Path(folder) / 'missing.jsonl'), {})
        self.assertEqual((judged['box'], judged['shadow'], judged['judged'], judged['untimed']),
                         ([float('50')], [float('90')], len('abc'), len('ab')))

    def test_the_webhook_ack_fails_on_any_single_delivery_over_the_limit_cold_ones_included(self):
        def line(id, ack_ms, cold, prefix=''):
            return prefix + json.dumps({'ingress': 202, 'cold': cold, 'id': id, 'ack_ms': ack_ms})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'ingress.log'
            path.write_text('\n'.join([line('w1', 120.5, False), line('w2', 1450, True, '2026-11-08T17:00:00Z abc\t'),
                                       line('w3', 1000, False), 'REPORT RequestId: x Duration: 5 ms', 'not json {',
                                       json.dumps({'other': 1})]), encoding='utf-8')
            found = medir.from_ingress([path])
        self.assertEqual((found['limit_s'], found['n']), (1, 3))  # medir.webhook_ack_limit_s; 1000 ms is at the limit
        self.assertEqual(found['over_limit'], [{'id': 'w2', 'seconds': float('1.45'), 'cold': True}])

    def test_the_acceptance_line_lists_each_failure_and_a_clean_sample_says_it_is_only_a_sample(self):
        def run(rows):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'ingress.log'
                path.write_text('\n'.join(json.dumps({'ingress': 202, 'cold': cold, 'id': id, 'ack_ms': ms})
                                          for id, ms, cold in rows), encoding='utf-8')
                with mock.patch.dict(os.environ, {'TOWER_PORT_URL': '', 'TOWER_PORT_TOKEN': ''}), \
                        mock.patch('sys.stdout', new_callable=__import__('io').StringIO) as out:
                    medir.main(['--ingress-log', str(path), '--deliveries', folder, '--shadows', folder])
                return out.getvalue()
        failed = run([('w1', 90, False), ('w2', 2300, True)])
        self.assertIn('webhook ack (limit 1 s): n=2, over limit: 1', failed)
        self.assertIn('over limit: w2 2.3 s cold', failed)
        self.assertIn('ingress_ack_s: n=2', failed)
        self.assertNotIn('no over-limit', failed)
        clean = run([('w1', 90, False), ('w2', 300, True)])
        self.assertIn('webhook ack (limit 1 s): n=2, over limit: 0', clean)
        self.assertIn('no over-limit delivery in 2 samples (a sample, not a guarantee)', clean)

    def test_the_registrys_ingress_timing_lists_each_delivery_whose_pre_send_is_over_the_limit_and_says_it_is_a_lower_bound(self):
        def forge(id, pre_send, cold, **extra):
            return {'event_id': f'forge.ping:{id}', 'type': 'forge.ping', 'occurred_at': '2026-11-08T16:00:00+00:00',
                    'payload': {'webhook': {'id': id}, 'delivery': {}, **extra,
                                **({'ingress': {'cold': cold, 'pre_send_ms': pre_send, 'gateway_to_handler_ms': 1,
                                                'origin_sent_to_handler_s': 0.1}} if pre_send is not None else {})}}
        found = [forge('w1', 40, False), forge('w2', 1730, True), forge('w3', 950, True), forge('old', None, False)]
        result = medir.from_registry_ingress(found, 1)
        self.assertEqual((result['n'], result['cold_n'], result['max_cold_pre_send_s'], result['near_limit_share']),
                         (3, 2, 1.73, float('0.6667')))  # the pre-PORT6 event is not counted
        self.assertEqual(result['over_limit'], [{'id': 'w2', 'seconds': 1.73, 'cold': True}])
        bare = {k: v for k, v in os.environ.items() if k not in ('TOWER_PORT_URL', 'TOWER_PORT_TOKEN')}
        with mock.patch.dict(os.environ, {**bare, 'TOWER_PORT_URL': 'http://x', 'TOWER_PORT_TOKEN': 't'}), \
                mock.patch.dict(sys.modules, {'gate_infra': mock.Mock(Port=mock.Mock())}), \
                mock.patch.object(medir, 'events', return_value=found), \
                tempfile.TemporaryDirectory() as folder, mock.patch('builtins.print') as said:
            medir.main(['--deliveries', folder, '--shadows', folder])
        out = '\n'.join(call[0][0] for call in said.call_args_list)
        self.assertIn('webhook ingress (limit 1 s, from the registry): n=3, cold n=2, deliveries whose pre_send '
                      'already exceeds the limit: 1', out)
        self.assertIn('over limit before the send: w2 1.73 s cold', out)
        self.assertIn('max pre_send among cold deliveries: 1.73 s', out)
        self.assertIn('LOWER BOUND of the ACK and a sample, not a guarantee', out)

    def test_the_log_is_read_page_by_page_each_event_once(self):
        port = Pages(LOG)
        with mock.patch.object(medir.config, 'get', side_effect=lambda key: {'medir.log_page': len(('one', 'two'))}.get(
                key)):
            found = medir.events(port, None)
        self.assertEqual([item['event_id'] for item in found], [item['event_id'] for item in LOG])
        self.assertGreater(len(port.asked), 1)

    def test_the_deliveries_logs_give_the_merges_through_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'pr-7.log').write_text('Merge commit: abc\ndeliver: origin merged #7 in 0.812 s\n')
            (Path(folder) / 'pr-8.log').write_text('deliver: the gate failed on abc; nothing merged\n')
            self.assertEqual(medir.from_deliveries(folder), [float('0.812')])

    def test_with_no_port_only_the_deliveries_are_read(self):
        bare = {name: value for name, value in os.environ.items() if not name.startswith('TOWER_PORT_')}
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, bare, clear=True), \
                mock.patch('builtins.print') as said:
            (Path(folder) / 'pr-7.log').write_text('deliver: origin merged #7 in 0.5 s\n')
            self.assertEqual(medir.main(['--json', '--deliveries', folder, '--shadows', folder]), 0)
        answer = json.loads(said.call_args[0][0])
        self.assertEqual(list(answer), ['deliver_merge_s'])
        self.assertEqual((answer['deliver_merge_s']['n'], answer['deliver_merge_s']['p50']), (1, float('0.5')))


class DeployCycleTests(unittest.TestCase):
    def test_the_cycles_of_the_status_become_seconds_and_usd(self):
        status = {'cycles': [{'seconds': 150, 'usd': 0.0125}, {'seconds': 210, 'usd': 0.0175}, {'seconds': None}]}
        found = medir.from_deploy_status(status)
        self.assertEqual(found, {'deploy_cycle_s': [150, 210], 'deploy_cycle_usd': [0.0125, 0.0175]})
        self.assertEqual(medir.summary(found['deploy_cycle_s'])['n'], 2)
        self.assertEqual(medir.from_deploy_status({}), {})

    def test_the_wait_for_the_rollouts_is_a_measure_of_its_own_off_the_cycles_clock(self):
        # SLOW-PATH-NO-ROLLOUT-WAIT: a build starts the ECS rollouts and ends (rolling); the next one verifies them
        status = {'cycles': [{'seconds': 160, 'usd': 0.0133, 'status': 'rolling'},
                             {'seconds': 25, 'usd': 0.0021, 'status': 'succeeded', 'rollout_wait_s': 410,
                              'rollout': {'tower-app-service': 264, 'tower-app-runner': 433}},
                             {'seconds': 30, 'usd': 0.0025, 'status': 'succeeded', 'rollout_wait_s': True}]}
        found = medir.from_deploy_status(status)
        self.assertEqual((found['deploy_cycle_s'], found['deploy_rollout_wait_s']), ([160, 25, 30], [410]))

    def test_the_runner_warm_ups_of_the_status_become_prewarm_s(self):
        # RUNNER-WARM-STATUS: the warm-up is an installation event (tenant_id null), so it comes from the status, not the log
        status = {'runner_warm': [{'task': 'a', 'seconds': 41.5, 'ok': True}, {'task': 'b', 'seconds': 300, 'ok': False},
                                  {'task': 'c', 'seconds': None, 'ok': True}, 'junk']}
        self.assertEqual(medir.from_deploy_status(status), {'prewarm_s': [41.5]})
        self.assertEqual(medir.from_log([{'type': 'platform.runner.warm', 'occurred_at': '2026-11-09T01:00:00+00:00',
                                          'payload': {'ok': True, 'seconds': 9}}]).get('prewarm_s'), None)

    def test_a_port_that_does_not_answer_the_status_costs_nothing(self):
        class Down:
            def call(self, *_):
                raise OSError('down')
        self.assertEqual(medir.deploy_status_of(Down()), {})


if __name__ == '__main__':
    unittest.main()
