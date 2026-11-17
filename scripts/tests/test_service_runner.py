"""The Tower runner (GATE-TRAIN-SERVICES R1, R2; D-086, ADR-41, D-290): jobs claimed from the control plane, run once
each, in order, paused, requeued, superseded, the control route as the only route, and a real executor over stub
commands. A local bare remote is the forge's git side (the D-141 head check); a fake queue the control plane. Numbers
come from the registry or from 1 (the literal census of a new unit allows no other)."""
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import time
import subprocess
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_forge_events import FakeClock, REPO  # noqa: E402
from test_forge_git_ref import Remote, git  # noqa: E402
import config  # noqa: E402
import service  # noqa: E402
import service_runner  # noqa: E402
import service_status  # noqa: E402

PR = 1  # fixture PR
OTHER = PR + 1
BASE = config.get('train.base_branch')
HEAD_A, HEAD_B, HEAD_C = (hashlib.sha1(name).hexdigest() for name in (b'a', b'b', b'c'))
HELD = {'OU_RUNNER_TOKEN': 'secret', 'TOWER_EVENTS_TOKEN': 'events', 'GH_TOKEN': 'github'}  # what a runner holds


class Queue:
    """The control plane as the runner sees it: the jobs each poll claims, and every result reported back."""
    label = 'control'

    def __init__(self):
        self.jobs, self.reported = [], []

    def poll(self, state):
        jobs, self.jobs = self.jobs, []
        return sorted(jobs, key=lambda item: service_runner.ORDER.index(item['kind']))

    def report(self, outcome):
        self.reported.append((outcome['job'], outcome['outcome']))


class FakeExecutor:
    def __init__(self, clock):
        self.clock, self.ran = clock, []
        self.runner = {'name': 'test', 'kind': 'other'}

    def run(self, item, claimed=None):
        self.ran.append(item['id'])
        moment = service_runner.forge_events.rfc3339(self.clock.now())
        return {'job': item['id'], 'outcome': 'passed', 'runner': {'name': 'test', 'kind': 'other'},
                'started_at': moment, 'finished_at': moment, 'duration_s': 0.0, 'exit': 0, 'verdict_event': None,
                'reason': 'passed', 'phases': [], 'log_tail': ''}

    def stop(self):
        pass


class Fixture(unittest.TestCase):
    """A local bare remote is the forge's git side; `heads` is the forge's open changes (the D-141 head check reads
    them); Queue is the control plane."""

    def setUp(self):
        self.heads = {}
        forge = mock.Mock(open_pulls=lambda _repo: [{'number': int(number), 'head_sha': sha}
                                                     for number, sha in self.heads.items()])
        self.enterContext(mock.patch.object(service_runner.forge_events, 'adapter_from_config', lambda: forge))
        self.remote = Remote(self)
        self.refs = self.remote.clone('runner')
        self.root = self.refs.root
        git('config', 'user.email', 'runner@example.com', cwd=self.root)
        git('config', 'user.name', 'Runner', cwd=self.root)
        self.clock = FakeClock()
        self.paused = False
        self.queue = Queue()
        self.executor = FakeExecutor(self.clock)
        self.lines = []
        self.refreshed = []
        self.runner = service_runner.Runner(service_runner.State(self.root, 'test', 'other'), self.queue, self.executor,
                                            self.clock, paused=lambda: self.paused, out=self.lines.append,
                                            refresh=lambda root: self.refreshed.append(len(self.executor.ran)))

    def head(self, number, sha):
        """A push to PR `number`: its head on the forge."""
        commit = git('commit-tree', git('write-tree', cwd=self.root), '-m', f'{number} {sha}', cwd=self.root)
        self.heads[str(number)] = commit
        return commit

    def claim(self, kind, number=None, sha=None, attempt=1):
        """The control plane hands the next poll a job of `kind`."""
        item = service_runner.job(kind, REPO, number, sha, 'control', 'claimed', self.runner.now(), attempt=attempt)
        self.queue.jobs.append(item)
        return item['id']


class Jobs(Fixture):
    def test_a_claimed_job_runs_once_even_when_claimed_again(self):
        head = self.head(PR, HEAD_A)
        self.claim(service_runner.GATE, PR, head)
        self.runner.once()
        self.claim(service_runner.GATE, PR, head)  # a lease that lapsed is claimed again
        self.runner.once()
        self.assertEqual(self.executor.ran, [f'gate:{PR}#{head}'])

    def test_the_outer_deadline_interrupts_a_head_check_before_the_executor_starts(self):
        self.claim(service_runner.GATE, PR, HEAD_A)
        self.runner.superseded = lambda _job: time.sleep(5)
        with mock.patch.object(service_runner.service_budget, 'budget_s', return_value=0.4):
            [outcome] = self.runner.once()
        self.assertEqual(outcome['outcome'], 'over_budget')
        self.assertEqual(self.executor.ran, [])
        self.assertLess(outcome['duration_s'], 0.4 + service_runner.service_budget.TERM_RESERVE_S)
        self.assertIsNone(self.runner.state.data['current'])

    def test_a_train_job_runs_before_the_gates_and_the_sweep_last(self):
        head = self.head(PR, HEAD_A)
        self.claim(service_runner.SWEEP)
        self.claim(service_runner.GATE, PR, head)
        self.claim(service_runner.TRAIN, OTHER, HEAD_C)
        self.runner.once()
        self.assertEqual([item.split(':')[0] for item in self.executor.ran], ['train', 'gate', 'sweep'])

    def test_a_requeue_is_the_next_attempt_of_the_head(self):
        head = self.head(PR, HEAD_A)
        first = self.claim(service_runner.GATE, PR, head)
        again = self.claim(service_runner.GATE, PR, head, attempt=2)
        self.runner.once()
        self.assertEqual(self.executor.ran, [first, again])
        self.assertTrue(again.startswith(f'{first}.'))

    def test_a_gate_job_whose_head_was_pushed_over_before_it_starts_is_dropped(self):
        first, second = self.head(PR, HEAD_A), self.head(OTHER, HEAD_B)
        self.claim(service_runner.GATE, PR, first)
        self.claim(service_runner.GATE, OTHER, second)
        newer = []
        run = self.executor.run

        def run_and_push(item, claimed=None):
            result = run(item, claimed)
            if not newer:  # while the first job ran, the second PR was pushed again
                newer.append(self.head(OTHER, HEAD_C))
            return result

        self.executor.run = run_and_push
        self.runner.once()
        self.assertEqual(self.executor.ran, [f'gate:{PR}#{first}'])
        self.assertIn((f'gate:{OTHER}#{second}', 'skipped'), self.queue.reported)
        self.executor.run = run
        self.claim(service_runner.GATE, OTHER, newer[0])
        self.runner.once()
        self.assertEqual(self.executor.ran[-1], f'gate:{OTHER}#{newer[0]}')

    def test_superseded_is_true_only_for_a_gate_job_of_a_replaced_head(self):
        head = self.head(PR, HEAD_A)
        runner = self.runner
        self.assertFalse(runner.superseded(f'gate:{PR}#{head}'))
        self.assertFalse(runner.superseded(f'train:{PR}#{head}'))
        self.assertFalse(runner.superseded(f'gate:{PR}#{head}.{PR}'))  # a requeue is its own head
        self.head(PR, HEAD_B)
        self.assertTrue(runner.superseded(f'gate:{PR}#{head}'))
        self.assertTrue(runner.superseded(f'gate:{PR}#{head}.{PR}'))
        self.assertFalse(runner.superseded(f'train:{PR}#{head}'))

    def test_a_queue_of_old_heads_of_one_pr_runs_only_the_newest_and_reports_the_rest_skipped(self):
        """The control plane queues one gate job per pushed head (the PR #847 case: eight old heads in line)."""
        old = [self.head(PR, name) for name in (HEAD_A, HEAD_B)]
        newest = self.head(PR, HEAD_C)
        for sha in (*old, newest):
            self.claim(service_runner.GATE, PR, sha)
        self.runner.once()
        reported = self.queue.reported
        self.assertEqual(self.executor.ran, [f'gate:{PR}#{newest}'])
        self.assertEqual([outcome for job, outcome in reported if job != f'gate:{PR}#{newest}'], ['skipped', 'skipped'])
        self.assertEqual(reported[-1], (f'gate:{PR}#{newest}', 'passed'))

    def test_paused_claims_nothing_so_no_job_waits_on_its_budget(self):
        """D-291: a claimed job's budget runs from its claim, so a paused runner does not claim at all."""
        self.paused = True
        head = self.head(PR, HEAD_A)
        self.claim(service_runner.GATE, PR, head)
        self.runner.once()
        self.assertEqual((self.executor.ran, self.queue.reported), ([], []))
        self.assertEqual(len(self.queue.jobs), 1)  # still the control plane's, never leased
        self.paused = False
        self.runner.once()
        self.assertEqual(self.executor.ran, [f'gate:{PR}#{head}'])

    def test_the_base_is_refreshed_before_each_claim_never_inside_a_job(self):
        head = self.head(PR, HEAD_A)
        self.claim(service_runner.GATE, PR, head)
        self.runner.once()
        self.assertEqual(self.refreshed, [0, 1])  # before the claim of the job, and before the claim that found none

    def test_a_deploy_is_a_claimed_budgeted_job_and_has_no_between_jobs_route(self):
        self.claim(service_runner.DEPLOY, None, HEAD_A)
        self.runner.once()
        self.assertEqual(len(self.executor.ran), 1)
        self.assertTrue(self.executor.ran[0].startswith('deploy:'))
        self.assertFalse(hasattr(self.runner, 'deploy'))
        command = service_runner.Executor(self.root, self.clock, {'name': 'vm', 'kind': 'vm'}).command(
            {'kind': service_runner.DEPLOY})
        self.assertEqual(command, [sys.executable, '-c', service_runner.RETIRED_DEPLOY])
        done = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('retired (D-323)', done.stdout)

    def test_a_runner_that_starts_with_a_current_job_reports_it_died_before_it_claims(self):
        head = self.head(PR, HEAD_A)
        item = service_runner.job(service_runner.GATE, REPO, PR, head, 'control', 'claimed', self.runner.now())
        self.runner.state.data['current'] = item
        self.runner.state.save(self.runner.now())
        restarted = service_runner.Runner(service_runner.State(self.root, 'test', 'other'), self.queue, self.executor,
                                          self.clock, paused=lambda: False, out=self.lines.append,
                                          refresh=lambda root: None)
        outcome = restarted.recover()
        self.assertEqual(outcome['outcome'], 'died')
        self.assertIn('the runner stopped during this job', outcome['reason'])
        self.assertEqual(self.queue.reported, [(item['id'], 'died')])
        self.assertIsNone(restarted.state.data['current'])
        self.assertIsNone(restarted.recover())  # nothing left to recover

    def test_a_poll_the_control_plane_does_not_answer_fails_and_the_next_poll_retries(self):
        def refused(state):
            raise OSError('the control plane answered the claim with 503')

        self.queue.poll = refused
        self.assertEqual(self.runner.once(), [])
        self.assertTrue(any('poll failed' in line and '503' in line for line in self.lines))
        self.assertIn('"event": "poll-failed"', (self.root / config.get('service.log_path')).read_text())

    def test_results_reach_the_state_the_log_the_control_plane_and_the_status(self):
        head = self.head(PR, HEAD_A)
        self.claim(service_runner.GATE, PR, head)
        self.runner.once()
        state = json.loads((self.root / config.get('service.state_path')).read_text())
        self.assertEqual((state['results'][-1]['outcome'], state['transport']), ('passed', 'control'))
        self.assertEqual(self.queue.reported, [(f'gate:{PR}#{head}', 'passed')])
        log = self.root / config.get('service.log_path')
        self.assertIn('"event": "finished"', log.read_text())
        sources = service_status.Sources(root=self.root, refs=self.refs, clock=self.clock)
        self.assertEqual(sources.runner()['name'], 'test')


    def liveness(self):
        sources = service_status.Sources(root=self.root, refs=self.refs, clock=self.clock)
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            return service.main(['liveness'], sources=sources), out.getvalue()

    def test_liveness_passes_a_runner_that_just_beat_and_fails_a_stale_or_absent_one(self):
        self.assertEqual(self.liveness()[0], 1)  # no runner state on this machine
        self.runner.once()
        self.assertEqual(self.liveness()[0], 0)
        self.clock.moment += timedelta(seconds=config.get('service.heartbeat_stale_s') + 1)
        code, text = self.liveness()
        self.assertEqual(code, 1)
        self.assertIn('last beat', text)


class Route(unittest.TestCase):
    """D-290: the control plane is the only route. Nothing selects git; a missing token is an error naming the variable."""

    RUNNER = {'name': 'test', 'kind': 'other'}

    def test_the_git_route_cannot_be_selected(self):
        for route in ('git', '', None, 'GIT'):
            with self.subTest(route=route), self.assertRaises(service_runner.RouteError) as raised:
                service_runner.transport_for(route, {config.get('service.runner_token_env'): 'token'}, self.RUNNER)
            self.assertIn('service.transport', str(raised.exception))
            self.assertIn('the control plane is the only route', str(raised.exception))

    def test_the_module_has_no_git_transport_and_no_fallback(self):
        self.assertFalse(hasattr(service_runner, 'GitTransport'))
        self.assertNotIn('fallback', service_runner.ControlTransport.__init__.__code__.co_varnames)
        source = Path(service_runner.__file__).read_text()
        for spelled in ('train.wake_ref', 'train.sweep_interval_s', 'GitTransport'):
            self.assertNotIn(spelled, source)

    def test_the_registry_offers_only_the_control_route(self):
        registry = json.loads((Path(service_runner.ROOT) / 'config/registry/service/service.transport.json').read_text())
        self.assertEqual((registry['default'], registry['enum']), ('control', ['control']))

    def test_a_missing_token_is_an_error_that_names_the_variable_not_a_fallback(self):
        variable = config.get('service.runner_token_env')
        self.assertEqual(variable, 'OU_RUNNER_TOKEN')
        for environ in ({}, {variable: ''}):
            with self.subTest(environ=environ), self.assertRaises(service_runner.RouteError) as raised:
                service_runner.transport_for('control', environ, self.RUNNER)
            self.assertIn('$OU_RUNNER_TOKEN', str(raised.exception))

    def test_build_refuses_before_any_state_is_written(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(service_runner.config, 'shared', return_value='control'), \
                self.assertRaises(service_runner.RouteError):
            service_runner.build(root=root, clock=FakeClock(), environ={})
            self.assertFalse((Path(root) / config.get('service.state_path')).exists())

    def test_a_store_still_holding_git_is_a_route_error_not_a_traceback(self):
        refused = service_runner.config.ConfigError(
            "config: the stored value of service.transport no longer satisfies its schema ('git' is not one of ['control'])")
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(service_runner.config, 'shared', side_effect=refused), \
                self.assertRaises(service_runner.RouteError) as raised:
            service_runner.build(root=root, clock=FakeClock(), environ={'OU_RUNNER_TOKEN': 'secret'})
        self.assertIn('service.transport', str(raised.exception))
        self.assertIn('the control plane is the only route', str(raised.exception))

    def test_build_with_the_token_takes_the_control_plane(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(service_runner.config, 'shared', return_value='control'):
            built = service_runner.build(root=root, clock=FakeClock(), environ=HELD)
        self.assertIsInstance(built.transport, service_runner.ControlTransport)
        self.assertEqual(built.transport.url, config.get('service.control_url').rstrip('/'))

    def test_a_runner_without_a_secret_of_the_inventory_refuses_to_start_naming_it(self):
        """D-291 (5), audit F17: a secret the inventory lists for this kind stops the runner by name, before a poll."""
        for variable in ('TOWER_EVENTS_TOKEN', 'GH_TOKEN'):
            environ = {key: value for key, value in HELD.items() if key != variable}
            with self.subTest(variable=variable), tempfile.TemporaryDirectory() as root, \
                    mock.patch.object(service_runner.config, 'shared', return_value='control'), \
                    self.assertRaises(service_runner.RouteError) as raised:
                service_runner.build(root=root, clock=FakeClock(), environ=environ)
            self.assertIn(f'{variable}', str(raised.exception))
            self.assertIn('service.token_holders', str(raised.exception))

    def test_a_proxied_github_token_does_not_block_the_start(self):
        environ = {key: value for key, value in HELD.items() if key != 'GH_TOKEN'}
        self.assertEqual(service_runner.absent(dict(environ, OU_CREDENTIALS='network'), 'vm'), [])
        self.assertEqual(service_runner.absent(HELD, 'vm'), [])

    def test_a_refused_token_names_the_secret_it_must_equal_and_its_holder(self):
        sentence = service_runner.refused(401)
        self.assertIn(config.get('service.runner_token_env'), sentence)
        self.assertIn('RUNNER_TOKEN', sentence)
        self.assertIn('runner.env', sentence)

    def test_the_command_prints_the_route_error_and_exits_2(self):
        with mock.patch.object(service_runner.config, 'shared', return_value='git'), \
                mock.patch('sys.stderr', new_callable=io.StringIO) as err:
            self.assertEqual(service.main(['runner', '--once']), 2)
        self.assertIn('service.transport is \'git\'', err.getvalue())

class RealExecutor(unittest.TestCase):
    """The executor over stub commands: the verdict event id, the outcome, the log tail, a timeout."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / 'scripts').mkdir()
        self.clock = FakeClock()

    def stub(self, relative, body):
        path = self.root / relative
        path.write_text('#!/usr/bin/env bash\n' + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)

    def run_job(self, kind):
        item = service_runner.job(kind, REPO, PR, HEAD_A, 'control', 'test', service_runner.forge_events.rfc3339(
            self.clock.now()))
        return service_runner.Executor(self.root, self.clock, {'name': 'test', 'kind': 'other'}).run(item)

    def test_a_gate_reports_its_verdict_event_and_outcome(self):
        gate = config.get('service.gate_command')[0]
        self.stub(gate, 'echo "gate evidence: gate.passed abc123 on PR #$2"\n')
        result = self.run_job('gate')
        self.assertEqual((result['outcome'], result['verdict_event'], result['exit']), ('passed', 'abc123', 0))
        self.stub(gate, 'echo "gate evidence: gate.failed def456 on PR #$2"; exit 1\n')
        self.assertEqual(self.run_job('gate')['outcome'], 'failed')

    def test_the_job_gets_its_deadline_and_lock_owner_and_reports_its_phases(self):
        self.stub('scripts/train', 'echo "phase: lock @$(date +%s.%N | cut -c1-14)"; echo "deadline=$TOWER_JOB_DEADLINE owner=$TOWER_JOB_OWNER"; '
                                   'echo "train: drained"\n')
        claimed = self.clock.now().timestamp()
        item = service_runner.job('train', REPO, PR, HEAD_A, 'control', 'test', service_runner.forge_events.rfc3339(self.clock.now()))
        with mock.patch.object(service_runner.time, 'time', return_value=claimed):
            result = service_runner.Executor(self.root, self.clock, {'name': 'vm1', 'kind': 'vm'}).run(item, claimed)
        budget = config.get('service.job_budget_s')
        self.assertIn(f'deadline={claimed + budget - min(service_runner.service_budget.REPORT_RESERVE_S, budget / 5):.3f}', result['log_tail'])
        self.assertIn(f'owner=vm1/{item["id"]}', result['log_tail'])
        self.assertEqual([found['name'] for found in result['phases']], ['lock'])
        self.assertGreaterEqual(result['phases'][0]['at_s'], 0)
        self.assertEqual((result['outcome'], result['reason']), ('passed', 'train passed (exit 0): train: drained'))

    def test_a_job_past_its_budget_is_stopped_and_answers_over_budget_with_its_phase(self):
        self.stub('scripts/train', 'echo "phase: merge @$(date +%s)"; trap "" TERM; sleep 30\n')
        item = service_runner.job('train', REPO, PR, HEAD_A, 'control', 'test', service_runner.forge_events.rfc3339(self.clock.now()))
        budget = 1  # seconds: the registry's 10 would make the test slow; the rule is the same
        with mock.patch.object(service_runner.service_budget, 'budget_s', return_value=budget), \
                mock.patch.object(service_runner.service_budget, 'TERM_RESERVE_S', 0.5):
            result = service_runner.Executor(self.root, self.clock, {'name': 'vm1', 'kind': 'vm'}).run(item)
        self.assertLess(result['duration_s'], budget + 1)  # actual executor duration, even when the job ignores TERM
        self.assertEqual((result['outcome'], result['exit']), ('over_budget', None))
        self.assertIn(f'over the {budget} s budget during phase merge', result['reason'])

    def test_a_halted_train_is_halted_not_failed(self):
        self.stub('scripts/train', 'echo "train: halted: the tip moved"; exit 1\n')
        result = self.run_job('train')
        self.assertEqual(result['outcome'], 'halted')
        self.assertIn('train: halted', result['log_tail'])

    def test_a_claim_that_spent_the_budget_never_starts_a_child(self):
        item = service_runner.job('train', REPO, PR, HEAD_A, 'control', 'test', self.clock.now().isoformat())
        with mock.patch.object(service_runner.subprocess, 'Popen') as spawn, \
                mock.patch.object(service_runner.time, 'time', return_value=config.get('service.job_budget_s')):
            outcome = service_runner.Executor(self.root, self.clock, {'name': 'vm', 'kind': 'vm'}).run(
                item, 0)
        spawn.assert_not_called()
        self.assertEqual(outcome['outcome'], 'over_budget')

    def test_descendants_are_killed_even_after_the_job_leader_exits_successfully(self):
        self.stub('scripts/train', 'sleep 30 &\necho $! > child.pid\nexit 0\n')
        self.assertEqual(self.run_job('train')['outcome'], 'passed')
        pid = int((self.root / 'child.pid').read_text())
        for _ in range(1000):
            try:
                state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
            except FileNotFoundError:
                break
            if state == 'Z':  # init may not have reaped the dead orphan yet
                break
            time.sleep(0.001)
        else:
            self.fail('the descendant survived cleanup')

    def test_restart_cleanup_kills_only_the_recorded_process_generation(self):
        child = subprocess.Popen(['sleep', '30'], start_new_session=True)
        self.addCleanup(lambda: child.poll() is None and child.kill())
        held = service_runner.process_identity(child.pid)
        service_runner.kill_recovered(dict(held, start='different generation'))
        self.assertIsNone(child.poll())
        service_runner.kill_recovered(held)
        self.assertEqual(child.wait(timeout=1), -service_runner.signal.SIGKILL)


class Commands(Fixture):
    def test_requeue_and_cancel_refuse_and_name_the_control_plane_admin_call(self):
        before = git('for-each-ref', cwd=self.root)
        for action in ('requeue', 'cancel'):
            with self.subTest(action=action), mock.patch('sys.stderr', new_callable=io.StringIO) as err:
                self.assertEqual(service.main([action, '--pr', str(PR), '--reason', 'retry']), 2)
            self.assertIn('/v1/admin', err.getvalue())
            self.assertIn(f'"action": "{action}"', err.getvalue())
        self.assertEqual(git('for-each-ref', cwd=self.root), before)  # nothing written to git

    def test_a_dry_run_names_the_route_and_claims_nothing(self):
        # every secret of its own kind, so neither the machine's GH_TOKEN nor its OU_CREDENTIALS=network decides it
        held = {**HELD, service_runner.setting('service.runner_kind_env'): 'box'}
        with mock.patch.object(service_runner.config, 'shared', return_value='control'), \
                mock.patch.dict('os.environ', held), \
                mock.patch.object(service_runner.ControlTransport, 'call', side_effect=AssertionError('claimed')), \
                mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            self.assertEqual(service.main(['runner', '--dry-run']), 0)
        self.assertIn('nothing claimed', out.getvalue())

    def test_pause_and_resume_go_through_the_shared_store(self):
        with mock.patch.object(service, 'config_set', return_value=0) as setter, mock.patch('sys.stdout'):
            service.main(['pause', '--reason', 'maintenance'])
            service.main(['resume', '--reason', 'done'])
        self.assertEqual([(call.args[0], call.args[1]) for call in setter.call_args_list],
                         [('service.paused', 'true'), ('service.paused', 'false')])

    def test_the_unit_keeps_the_runner_up(self):
        text = service_runner.unit_text(self.root)
        self.assertIn(f'ExecStart={self.root}/scripts/service runner', text)
        self.assertIn('Restart=always', text)

    def test_the_unit_survives_a_reboot_a_late_network_and_a_crash_loop_and_finds_its_tools_and_credentials(self):
        text = service_runner.unit_text(self.root, kind='vm')
        for line in ('Environment=OU_RUNNER_KIND=vm', 'Wants=network-online.target', 'After=network-online.target',
                     'StartLimitIntervalSec=0', 'RestartSec=', 'WantedBy=default.target',
                     f'Environment=PATH={self.root}/.toolchain/bin:'):
            self.assertIn(line, text)
        self.assertIn('EnvironmentFile=%h/.config/tower/runner.env\n', text)  # required: a missing secrets file stops the unit (F18)
        self.assertNotIn('{', text)  # every placeholder is filled

    def test_the_liveness_watch_restarts_the_runner_only_when_its_probe_fails(self):
        service_text = service_runner.unit_text(self.root, name='tower-runner-watch.service')
        self.assertIn(f"{self.root}/scripts/service liveness ||", service_text)
        self.assertIn('systemctl --user restart tower-runner.service', service_text)
        self.assertIn('Type=oneshot', service_text)
        timer = service_runner.unit_text(self.root, name='tower-runner-watch.timer')
        self.assertIn('OnUnitActiveSec=', timer)
        self.assertIn('WantedBy=timers.target', timer)

    def test_a_name_that_is_not_a_unit_is_refused_with_the_list(self):
        with self.assertRaises(KeyError) as raised:
            service_runner.unit_text(self.root, name='nope')
        self.assertIn('tower-runner-watch.timer', raised.exception.args[0])
        with mock.patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit):
            service.main(['runner', '--print-unit', 'nope'])

    def test_print_unit_takes_the_runner_kind(self):
        with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
            service.main(['runner', '--print-unit', '--kind', 'vm'])
        self.assertIn('OU_RUNNER_KIND=vm', out.getvalue())



class SelfUpdate(Fixture):
    """GATE-SPEED R6 (D-092): a runner whose checkout's scripts/ moved re-executes itself between jobs, never mid-job."""

    def commit_scripts(self, text):
        (self.root / 'scripts').mkdir(exist_ok=True)
        (self.root / 'scripts' / 'marker.txt').write_text(text)
        git('add', 'scripts/marker.txt', cwd=self.root)
        git('commit', '--quiet', '-m', text, cwd=self.root)

    def serve(self, change=None, enabled=True):
        """serve() until it re-executes or one poll passes; `change` runs during that poll (a refresh landing)."""
        stop, calls = mock.Mock(), []
        stop.is_set.side_effect = [False, True]
        stop.wait.return_value = False
        once = self.runner.once

        def poll():
            if change:
                change()
            return once()
        with mock.patch.object(self.runner, 'once', side_effect=poll), \
                mock.patch.object(self.runner, 'heartbeat'), \
                mock.patch.object(service_runner, 'setting', side_effect=lambda name: enabled if name == 'service.self_update'
                                  else config.get(name)):
            self.runner.serve(stop=stop, reexec=lambda: calls.append('re-executed'))
        return calls

    def test_a_refresh_that_moves_scripts_re_executes_the_runner(self):
        self.commit_scripts('one')
        self.assertEqual(self.serve(lambda: self.commit_scripts('two')), ['re-executed'])
        self.assertTrue(any('re-executing' in line for line in self.lines))

    def test_an_unchanged_checkout_or_the_switch_off_keeps_the_process(self):
        self.commit_scripts('one')
        self.assertEqual(self.serve(), [])
        self.assertEqual(self.serve(lambda: self.commit_scripts('three'), enabled=False), [])


if __name__ == '__main__':
    unittest.main()
