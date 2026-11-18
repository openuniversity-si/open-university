"""The session's deploy (DEP1). Hermetic: no AWS call, no network beyond 127.0.0.1.

infra/aws/deploy.sh runs against a stubbed aws/docker on the PATH and a git repo made here; GET /v1/deploy/status runs
in process; scripts/lib/deploy.py (ring, status, follow) runs against a fake doorbell and a fake port; and the
bootstrap's buildspec is checked for the clone and the delegation to deploy.sh.
"""
import contextlib
import hashlib
import io
import json
import time
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
import deploy  # noqa: E402
import gate_infra  # noqa: E402
from tower_infra import http_port  # noqa: E402

from test_deploy_sh import AWS_STUB, DOCKER_STUB, LAMBDA_KEYS, SIDE_BY_SIDE, TOKEN, git  # noqa: E402,F401 DEPLOY-SH-OWN-MODULE


class EpochTests(unittest.TestCase):
    def test_the_epoch_constant_is_the_services(self):
        epoch = re.search(r'^BISECT_EPOCH=(\d+)$', (ROOT / 'infra/aws/deploy.sh').read_text(), re.M).group(1)
        service = (ROOT / 'infra/service/tower_infra/autodeploy.py').read_text()
        self.assertIn(f'BISECT_EPOCH = {epoch} ', service)


class SmokeTests(unittest.TestCase):
    """DEP7: scripts/deploy-smoke against a fake port on 127.0.0.1."""

    GREEN = {'ok': True, 'stage': 'ended', 'line': 'canary job dispatched in 0.4 s, taken in 0.1 s, ended in 0.7 s'}

    def serve(self, health=200, status=200, source='registry', canary=(GREEN,), created=200, held=None):
        """canary (DEPLOY-CANARY): what each GET /v1/deploy/canary/<id> answers, in order (the last one repeats); created:
        the status of POST /v1/deploy/canary (404: a port older than the route). held (PORT-HEALTH-WAIT): the health
        answers of a port that holds GET /v1/health?wait_s, in order (the last one repeats): (seconds held, status);
        None: a port older than the wait, which ignores the query."""
        outer, readings, holds = self, list(canary), list(held or [])

        class Handler(BaseHTTPRequestHandler):
            def say(self, code, body):
                self.send_response(code)
                self.end_headers()
                self.wfile.write(json.dumps(body).encode())

            def do_GET(self):
                outer.seen.append((self.path, self.headers.get('Authorization')))
                if self.path.startswith('/v1/deploy/canary/'):
                    return self.say(200, {'id': 'job-1', **(readings.pop(0) if len(readings) > 1 else readings[0])})
                path, _, query = self.path.partition('?')
                if path == '/v1/health' and holds and 'wait_s=' in query:
                    seconds, code = holds.pop(0) if len(holds) > 1 else holds[0]
                    time.sleep(seconds)
                    return self.say(code, {'ok': code == 200, 'long_poll': {'waited_s': seconds, 'ready': code == 200}})
                self.say(*{'/v1/health': (health, {'ok': health == 200}),
                           '/v1/deploy/status': (status, {'source': source})}.get(path, (404, {})))

            def do_POST(self):
                sent = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
                outer.seen.append((self.path, self.headers.get('Authorization'), sent))
                self.say(created, {'id': 'job-1', 'key': sent.get('key'), 'created': True, 'limit_s': 120.0}
                         if created == 200 else {'error': f'no route POST {self.path}'})

            def log_message(self, *_):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_address[1]}'

    def run_smoke(self, url, aws='exit 255', **env):
        """aws: the body of the fake aws CLI (SMOKE-WITHOUT-RUNNER: what ECS answers for the runner); the default fails,
        as with no credential."""
        bin_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bin_dir, True)
        (bin_dir / 'aws').write_text(f'#!/usr/bin/env bash\n{aws}\n')
        (bin_dir / 'aws').chmod(0o755)
        environ = {**os.environ, 'PATH': f'{bin_dir}:{os.environ["PATH"]}', 'DEPLOY_SMOKE_URL': url, 'DEPLOY_SMOKE_TRIES': '2',
                   'DEPLOY_SMOKE_SLEEP': '0', **env}
        return subprocess.run(['bash', str(ROOT / 'scripts/deploy-smoke')], env=environ, capture_output=True, text=True,
                              timeout=60, check=False)

    def setUp(self):
        self.seen = []

    def test_green_with_a_token_reads_health_and_the_registry_status(self):
        done = self.run_smoke(self.serve(), DEPLOY_SMOKE_TOKEN='smoke-token-0123456789')
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn(('/v1/deploy/status', 'Bearer smoke-token-0123456789'), self.seen)
        self.assertNotIn('smoke-token', done.stdout)

    def test_a_red_health_is_red(self):
        done = self.run_smoke(self.serve(health=500), DEPLOY_SMOKE_TOKEN='t' * 12)
        self.assertEqual(done.returncode, 1)
        self.assertIn('smoke RED: GET /v1/health', done.stdout)
        self.assertIn(('/v1/health?wait_s=0', None), self.seen)  # PORT-HEALTH-WAIT: asked, and ignored by an old port

    def test_a_port_that_holds_the_health_is_asked_again_at_once_within_the_window(self):
        # PORT-HEALTH-WAIT: held 1 s and not ready, then ready: green with no pause between (a 600 s pause would run
        # past run_smoke's 60 s timeout)
        done = self.run_smoke(self.serve(held=[(1.1, 503), (0, 200)], status=401), DEPLOY_SMOKE_SLEEP='600')
        self.assertEqual(done.returncode, 0, done.stdout)
        asked = [path for path, *_ in self.seen if path.startswith('/v1/health')]
        self.assertEqual(len(asked), 2)
        self.assertTrue(asked[0].startswith('/v1/health?wait_s=600'), asked)

    def test_a_held_health_that_never_gets_ready_is_red_when_the_window_ends(self):
        done = self.run_smoke(self.serve(held=[(1.1, 503)], status=401), DEPLOY_SMOKE_SLEEP='2')
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("smoke RED: GET /v1/health answered '503'", done.stdout)
        # never before the window ((tries - 1) x pause, 2 s): held 1.1 s each, so asked at least twice
        self.assertGreaterEqual(len([path for path, *_ in self.seen if path.startswith('/v1/health')]), 2)

    def test_a_status_that_does_not_come_from_the_registry_is_red(self):
        done = self.run_smoke(self.serve(source='ssm'), DEPLOY_SMOKE_TOKEN='t' * 12)
        self.assertEqual(done.returncode, 1)

    def test_without_a_token_the_route_must_refuse_and_the_skip_is_said(self):
        done = self.run_smoke(self.serve(status=401))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn('authenticated registry read was skipped', done.stdout)
        self.assertEqual(self.run_smoke(self.serve(status=200)).returncode, 1)  # an open status route is not a smoke pass

    def test_green_runs_the_canary_job_by_the_builds_id_and_says_its_seconds(self):
        done = self.run_smoke(self.serve(), DEPLOY_SMOKE_TOKEN='smoke-token-0123456789', CODEBUILD_BUILD_ID='tower-infra-deploy:b-1')
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn('smoke ok: canary job dispatched in 0.4 s, taken in 0.1 s, ended in 0.7 s', done.stdout)
        self.assertIn(('/v1/deploy/canary', 'Bearer smoke-token-0123456789', {'key': 'tower-infra-deploy:b-1'}), self.seen)
        self.assertIn(('/v1/deploy/canary/job-1?wait_s=20', 'Bearer smoke-token-0123456789'), self.seen)  # the long poll
        self.assertNotIn('smoke-token', done.stdout)

    def test_the_canary_is_asked_again_until_the_port_gives_its_verdict(self):
        waiting = {'ok': None, 'stage': 'take', 'line': 'canary job waiting for its take (1.0 s of 120 s)'}
        done = self.run_smoke(self.serve(canary=(waiting, waiting, self.GREEN)), DEPLOY_SMOKE_TOKEN='t' * 12)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(len([each for each in self.seen if each[0].startswith('/v1/deploy/canary/')]), 3)

    def test_a_red_canary_is_red_with_the_stage_that_never_happened(self):
        for stage, line in (('dispatch', 'canary job not dispatched in 120 s: the service (no run.started)'),
                            ('take', 'canary job dispatched in 0.4 s and not taken in 120 s: the runner (no run.running)'),
                            ('run', 'canary job taken in 0.1 s and ended failed (exit_1): the run')):
            done = self.run_smoke(self.serve(canary=({'ok': False, 'stage': stage, 'line': line},)), DEPLOY_SMOKE_TOKEN='t' * 12,
                                  ALERTS_TOPIC_ARN='arn:aws-partition:sns:us-east-1:1:tower-platform-events')
            self.assertEqual(done.returncode, 1, done.stdout)
            self.assertIn(f'smoke RED: {line}', done.stdout)
            self.assertIn('smoke ok: registry read', done.stdout)  # the port's Lambda answered: only the canary saw it

    def test_a_canary_the_port_could_not_create_is_red_and_a_port_without_the_route_skips_it(self):
        done = self.run_smoke(self.serve(created=409), DEPLOY_SMOKE_TOKEN='t' * 12)
        self.assertEqual(done.returncode, 1)
        self.assertIn("smoke RED: canary job not created: POST /v1/deploy/canary answered '409'", done.stdout)
        done = self.run_smoke(self.serve(created=404), DEPLOY_SMOKE_TOKEN='t' * 12)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn('the canary job was skipped', done.stdout)

    @staticmethod
    def ecs(desired, log=None):
        """A fake aws CLI whose ecs describe-services prints `desired` (what the --query selects) and records its arguments
        in `log`; any other call fails."""
        record = f'echo "$*" >> {shlex.quote(str(log))}; ' if log else ''
        return (f'{record}if [[ "$1 $2" = "ecs describe-services" ]]; then echo {shlex.quote(desired)}; exit 0; fi; exit 255')

    @staticmethod
    def stack(answer, log=None):
        """SMOKE-RUNNER-FROM-STACK: a fake aws CLI that refuses ECS (the deployer's role is not granted it) and answers the
        runner stack's DesiredCount with `answer`; 'missing' says the stack does not exist, 'fail' any other error."""
        record = f'echo "$*" >> {shlex.quote(str(log))}; ' if log else ''
        reply = {'missing': 'echo "An error occurred (ValidationError): Stack with id tower-app-runner does not exist" >&2; exit 254',
                 'fail': 'echo "An error occurred (Throttling)" >&2; exit 254'}.get(answer, f'echo {shlex.quote(answer)}; exit 0')
        return (f'{record}if [[ "$1 $2" = "ecs describe-services" ]]; then echo "AccessDeniedException" >&2; exit 254; fi; '
                f'if [[ "$1 $2" = "cloudformation describe-stacks" ]]; then {reply}; fi; exit 255')

    def test_when_ecs_is_refused_the_runner_stacks_desired_count_decides(self):
        """tower-infra-deploy:e70ed637 (14/11): the deployer may not call ECS, so the canary ran with the runner at 0."""
        for answer, said in (('0', 'the runner stack (tower-app-runner) has DesiredCount 0'),
                             ('missing', 'the runner stack (tower-app-runner) does not exist')):
            self.seen = []
            log = Path(tempfile.mkdtemp()) / 'aws.log'
            self.addCleanup(shutil.rmtree, log.parent, True)
            done = self.run_smoke(self.serve(), aws=self.stack(answer, log), DEPLOY_SMOKE_TOKEN='t' * 12)
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertIn(f'smoke: {said}', done.stdout)
            self.assertEqual(self.canaries(), [])
            self.assertIn('smoke ok: registry read', done.stdout)
            self.assertIn('cloudformation describe-stacks --stack-name tower-app-runner', log.read_text())
        red = ({'ok': False, 'stage': 'take', 'line': 'canary job dispatched in 0.4 s and not taken in 120 s: the runner'},)
        for answer in ('1', 'fail'):  # a runner the stack starts, or neither answer: the canary runs, and red is red
            self.seen = []
            done = self.run_smoke(self.serve(canary=red), aws=self.stack(answer), DEPLOY_SMOKE_TOKEN='t' * 12)
            self.assertEqual(done.returncode, 1, (answer, done.stdout))
            self.assertTrue(self.canaries())

    def canaries(self):
        return [each for each in self.seen if 'canary' in each[0]]

    def test_with_the_runner_stopped_or_gone_the_canary_is_skipped_and_said_and_the_rest_still_runs(self):
        """SMOKE-WITHOUT-RUNNER: the gate left AWS; tower-runner at desired count 0, or deleted, takes no canary job."""
        for desired, said in (('0', 'has a desired count of 0'), ('None', 'is missing or inactive'), ('', 'is missing or inactive')):
            self.seen = []
            log = Path(tempfile.mkdtemp()) / 'aws.log'
            self.addCleanup(shutil.rmtree, log.parent, True)
            done = self.run_smoke(self.serve(), aws=self.ecs(desired, log), DEPLOY_SMOKE_TOKEN='t' * 12)
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertIn(f'smoke: the runner (tower-runner in tower) {said}', done.stdout)
            self.assertIn('the canary job was skipped', done.stdout)
            self.assertEqual(self.canaries(), [])
            self.assertIn('smoke ok: GET /v1/health', done.stdout)
            self.assertIn('smoke ok: registry read', done.stdout)
            self.assertIn('ecs describe-services --cluster tower --services tower-runner', log.read_text())

    def test_with_the_runner_stopped_the_other_checks_are_as_strict_as_before(self):
        stopped = self.ecs('0')
        done = self.run_smoke(self.serve(health=500), aws=stopped, DEPLOY_SMOKE_TOKEN='t' * 12)
        self.assertEqual(done.returncode, 1)
        self.assertIn('smoke RED: GET /v1/health', done.stdout)
        done = self.run_smoke(self.serve(source='ssm'), aws=stopped, DEPLOY_SMOKE_TOKEN='t' * 12)
        self.assertEqual(done.returncode, 1)
        self.assertIn('smoke RED: registry read', done.stdout)

    def test_a_runner_that_runs_or_an_ecs_that_did_not_answer_runs_the_canary(self):
        red = ({'ok': False, 'stage': 'take', 'line': 'canary job dispatched in 0.4 s and not taken in 120 s: the runner'},)
        for aws in (self.ecs('1'), self.ecs('2'), 'exit 255', self.ecs('surprise')):
            self.seen = []
            done = self.run_smoke(self.serve(canary=red), aws=aws, DEPLOY_SMOKE_TOKEN='t' * 12)
            self.assertEqual(done.returncode, 1, (aws, done.stdout))
            self.assertIn('smoke RED: canary job dispatched in 0.4 s and not taken in 120 s', done.stdout)
            self.assertTrue(self.canaries())

    def test_deploy_smoke_canary_on_and_off_override_what_ecs_says(self):
        done = self.run_smoke(self.serve(), aws=self.ecs('0'), DEPLOY_SMOKE_TOKEN='t' * 12, DEPLOY_SMOKE_CANARY='on')
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn('smoke ok: canary job', done.stdout)
        self.seen = []
        done = self.run_smoke(self.serve(), aws=self.ecs('1'), DEPLOY_SMOKE_TOKEN='t' * 12, DEPLOY_SMOKE_CANARY='off')
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn('smoke: DEPLOY_SMOKE_CANARY=off: the canary job was skipped', done.stdout)
        self.assertEqual(self.canaries(), [])
        done = self.run_smoke(self.serve(), aws=self.ecs('0'), DEPLOY_SMOKE_TOKEN='t' * 12, DEPLOY_SMOKE_CANARY='maybe')
        self.assertIn("DEPLOY_SMOKE_CANARY='maybe' is not auto, on or off: the canary runs", done.stdout)
        self.assertIn('smoke ok: canary job', done.stdout)

    def test_without_a_token_no_canary_is_asked_and_the_skip_is_said(self):
        done = self.run_smoke(self.serve(status=401))
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn('and the canary job with it', done.stdout)
        self.assertEqual([each for each in self.seen if 'canary' in each[0]], [])

    def test_the_health_route_needs_no_token_and_reads_the_database(self):
        class Db:
            def rows(self, sql, params=None):
                return [(1,)]
        answered = http_port.handle({'requestContext': {'http': {'method': 'GET'}}, 'rawPath': '/v1/health'}, Db(), 'x')
        self.assertEqual((answered['statusCode'], json.loads(answered['body'])['ok']), (200, True))
        self.assertNotIn('migration', json.loads(answered['body']))  # SLOW-PATH-NO-ROLLOUT-WAIT: only when deploy.sh asks


class StackOrderTests(unittest.TestCase):
    """infra/aws/order.json is the graph deploy.sh runs; it cannot drift from what the templates really import."""

    @staticmethod
    def imports(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == 'Fn::ImportValue' and isinstance(value, str):
                    yield value
                else:
                    yield from StackOrderTests.imports(value)
        elif isinstance(node, list):
            for value in node:
                yield from StackOrderTests.imports(value)

    def test_the_declared_graph_is_the_imported_graph(self):
        stacks = {re.sub(r'^\d+-', '', p.stem): json.loads(p.read_text())
                  for p in sorted((ROOT / 'infra/aws/stacks').glob('*.json'))}
        exports = {}
        for name, template in stacks.items():
            for output in template.get('Outputs', {}).values():
                if 'Export' in output:
                    exports[output['Export']['Name']] = name
        derived = {}
        for name, template in stacks.items():
            needs = set()
            for imported in self.imports(template):
                self.assertIn(imported, exports, f'{name} imports {imported}, which no stack exports')
                needs.add(exports[imported])
            derived[name] = needs
        declared = json.loads((ROOT / 'infra/aws/order.json').read_text())
        self.assertEqual(set(declared), set(stacks))
        self.assertEqual({k: set(v) for k, v in declared.items()}, derived)

    def test_the_declared_graph_has_no_cycle_and_follows_the_file_numbers(self):
        declared = json.loads((ROOT / 'infra/aws/order.json').read_text())
        names = [re.sub(r'^\d+-', '', p.stem) for p in sorted((ROOT / 'infra/aws/stacks').glob('*.json'))]
        for name, needs in declared.items():
            for need in needs:
                self.assertLess(names.index(need), names.index(name), f'{name} needs {need}, which comes later')

    def test_the_runner_stack_keeps_only_the_outputs_bucket_and_never_deletes_it(self):
        """GATE-SHUTDOWN (D-314): the gate's runner (its ECS service, task definition, roles and logs) is gone; the stack keeps
        the outputs bucket, which the deployer writes and the service and the port read (artifacts/lambda/*), retained."""
        runner = json.loads((ROOT / 'infra/aws/stacks/50-runner.json').read_text())
        self.assertEqual({name: each['Type'] for name, each in runner['Resources'].items()},
                         {'Outputs': 'AWS::S3::Bucket', 'OutputsOnlyOverTls': 'AWS::S3::BucketPolicy'})
        for each in runner['Resources'].values():
            self.assertEqual((each['DeletionPolicy'], each['UpdateReplacePolicy']), ('Retain', 'Retain'))
        self.assertEqual(runner['Resources']['Outputs']['Properties']['BucketName'],
                         {'Fn::Sub': 'tower-outputs-${AWS::AccountId}-${AWS::Region}'})
        # the parameters the deployer still passes stay: an unknown parameter would fail its apply
        self.assertTrue({'Image', 'LiveCode', 'LiveSeen', 'DesiredCount'} <= set(runner['Parameters']))

    def test_the_project_timeout_and_the_guard_budget_agree(self):
        project = json.loads((ROOT / 'infra/aws/bootstrap.json').read_text())['Resources']['DeployProject']['Properties']
        self.assertEqual(project['TimeoutInMinutes'], 45)
        budget = [v['Value'] for v in project['Environment']['EnvironmentVariables'] if v['Name'] == 'DEPLOY_BUDGET_S']
        self.assertEqual(budget, ['2400'])
        self.assertLess(int(budget[0]), 45 * 60)


class FakeDb:
    """Answers the token lookup and the observation query; the events are (tenant, occurred_at, payload)."""

    def __init__(self, events=()):
        self.events = list(events)

    def rows(self, sql, params=None):
        if sql.startswith('select id::text'):
            return [('tenant-1',)] if params.get('digest') == hashlib.sha256(b'tenant-token').hexdigest() else []
        if "type = 'platform.config.observed'" in sql:  # DEP9 step 2: no key observed yet
            return []
        if "type = 'platform.runner.warm'" in sql:  # RUNNER-WARM-STATUS: the installation's warm-ups, never a tenant's
            assert 'tenant_id is null' in sql
            return []
        if "type = 'platform.deploy.image_live'" in sql:  # IMAGE-PREWARM-A: the installation's image swaps
            assert 'tenant_id is null' in sql
            return []
        if "type = 'platform.deploy.successor'" in sql:  # IN-TASK-STANDBY: the installation's wants and successors
            assert 'tenant_id is null' in sql
            return []
        if "type = 'platform.deploy.ended'" in sql:  # ROLLOUT-PARTS: the app stacks' ends
            assert 'tenant_id is null' in sql
            return []
        if "type = 'platform.deploy.image_swap'" in sql or "type = 'platform.deploy.image_retired'" in sql:  # IMAGE-PREWARM-C
            assert 'tenant_id is null' in sql
            return []
        if "type = 'platform.deploy.image_reload'" in sql:  # IMAGE-SWAP-RELOAD: the installation's reloads in place
            assert 'tenant_id is null' in sql
            return []
        if "v.key = 'deploy.live_code'" in sql:  # SLOW-PATH-NO-ROLLOUT-WAIT: the live code datum; none written yet
            assert params == {'tenant': 'torre'}  # the installation's configuration, whoever asks
            return []
        if "type = 'platform.deploy.prune'" in sql:  # LAMBDA-PRUNE-STATUS: the prune look's passes
            assert 'tenant_id is null' in sql
            return []
        if "type = 'platform.deploy.canary'" in sql:  # DEPLOY-CANARY: the installation's canaries
            assert 'tenant_id is null' in sql
            return []
        if "type = 'platform.deploy.task_up'" in sql:  # SPOT-KEEP: the runner tasks' lives
            assert "payload->>'role' in ('runner', 'service')" in sql and "payload->>'mode' = 'task'" in sql
            return []
        if "'platform.ecs.task_stopped'" in sql:  # ECS-STOPS-READ: the installation's stopped tasks and service actions
            assert 'tenant_id is null' in sql and "'platform.ecs.service_action'" in sql
            return []
        assert "type = 'platform.deploy.observed'" in sql and 'order by occurred_at desc limit 1' in sql
        mine = [e for e in self.events if e[0] in (None, params['tenant'])]
        return [(json.dumps(max(mine, key=lambda e: e[1])[2]),)] if mine else []


class BuildStateTests(unittest.TestCase):
    """DEP-EVENTS: EventBridge pushes the deployer's CodeBuild Build State Change to tower-port-api:live; a terminal one is
    platform.deploy.ended (it NOTIFYs the autodeploy), once per build, under an id of its own."""

    class Recorder:
        def __init__(self):
            self.writes = []

        def rows(self, sql, params=None):
            self.writes.append((sql, params))
            return []

    def change(self, status, project='tower-infra-deploy', **extra):
        return {'version': '0', 'source': 'aws.codebuild', 'detail-type': 'CodeBuild Build State Change',
                'detail': {'project-name': project, 'build-status': status,
                           'build-id': 'arn:aws-partition:codebuild:us-east-1:123456789012:build/tower-infra-deploy:db4150e4-a2ea'},
                **extra}

    def test_a_terminal_build_is_one_ended_event_named_like_last_build(self):
        db = self.Recorder()
        said = http_port.handle(self.change('SUCCEEDED'), db, StatusEndpointTests.INSTALLATION)
        self.assertEqual(said, {'event_id': 'platform.deploy.ended:tower-infra-deploy:db4150e4-a2ea:codebuild'})
        (sql, params), = db.writes
        self.assertIn("'platform.deploy.ended'", sql)
        self.assertIn('where not exists', sql)  # at least once from EventBridge, once in the log
        self.assertEqual(json.loads(params['payload']),
                         {'build': 'tower-infra-deploy:db4150e4-a2ea', 'status': 'succeeded', 'source': 'codebuild'})
        for status in ('FAILED', 'FAULT', 'STOPPED', 'TIMED_OUT'):
            self.assertIn('event_id', http_port.handle(self.change(status), self.Recorder(), StatusEndpointTests.INSTALLATION))

    def test_a_builds_start_is_one_started_event_that_wakes_the_look_and_never_an_end(self):
        # FAST-PATH-RELOAD: the look then watches that build's record while it may still ask for a reload in place
        db = self.Recorder()
        said = http_port.handle(self.change('IN_PROGRESS'), db, StatusEndpointTests.INSTALLATION)
        self.assertEqual(said, {'event_id': 'platform.deploy.started:tower-infra-deploy:db4150e4-a2ea'})
        (sql, params), = db.writes
        self.assertIn("'platform.deploy.started'", sql)
        self.assertNotIn("'platform.deploy.ended'", sql)
        self.assertIn("pg_notify('tower_deploy', type)", sql)
        self.assertEqual(json.loads(params['payload']), {'build': 'tower-infra-deploy:db4150e4-a2ea', 'source': 'codebuild'})

    def test_a_running_build_another_project_or_an_http_call_writes_nothing(self):
        for event in (self.change('QUEUED'), self.change('IN_PROGRESS', project='other'), self.change('SUCCEEDED', project='other')):
            db = self.Recorder()
            self.assertEqual(http_port.handle(event, db, StatusEndpointTests.INSTALLATION), {'ignored': True})
            self.assertEqual(db.writes, [])
        forged = self.change('SUCCEEDED', requestContext={'http': {'method': 'GET'}}, rawPath='/nowhere')
        db = self.Recorder()
        self.assertEqual(http_port.handle(forged, db, StatusEndpointTests.INSTALLATION)['statusCode'], 404)
        self.assertFalse(any("platform.deploy.ended" in sql for sql, _ in db.writes))


class StatusEndpointTests(unittest.TestCase):
    INSTALLATION = hashlib.sha256(b'installation-token').hexdigest()

    def get(self, token, events=()):
        event = {'requestContext': {'http': {'method': 'GET'}}, 'rawPath': '/v1/deploy/status',
                 'headers': {'Authorization': f'Bearer {token}'} if token else {}}
        return http_port.handle(event, FakeDb(events), self.INSTALLATION)

    def test_the_route_no_longer_touches_parameter_store(self):
        self.assertFalse(hasattr(http_port, 'deploy_reader'))
        self.assertFalse(hasattr(http_port, 'parameter_reader'))

    def test_a_tenant_and_the_installation_read_the_newest_observation(self):
        record = {'status': 'failed', 'failed': ['tower-app-port'], 'tail': 'why'}
        ring = {'action': 'ring', 'reason': 'started', 'at': 5}
        events = [(None, 1, {'last_sha': 'old', 'last_build': None, 'observed_at': 1, 'ring': None}),
                  (None, 2, {'last_sha': 'a0bd4d1', 'last_build': record, 'observed_at': 2, 'ring': ring})]
        for token in ('tenant-token', 'installation-token'):
            answered = self.get(token, events)
            self.assertEqual(answered['statusCode'], 200)
            self.assertEqual(json.loads(answered['body']), {'last_sha': 'a0bd4d1', 'last_build': record, 'observed_at': 2,
                                                            'ring': ring, 'head': None, 'pending': None,
                                                            'source': 'registry', 'cycle': None, 'cycles': [], 'config_version': {},
                                                            'cost': None, 'fast': [], 'runner_warm': [], 'image_live': [], 'successor': [], 'stacks': [], 'image_swap': [], 'image_retired': [], 'image_reload': [], 'ecs': [], 'runner_life': [], 'task_up': [], 'prune': [], 'live_code': '', 'canary': [], 'bisect': None, 'culprit': None,
                                                            'bisect_note': None, 'in_progress': None, 'lost': None})

    def test_another_tenants_observation_is_never_served(self):
        events = [('tenant-2', 9, {'last_sha': 'theirs', 'last_build': None, 'observed_at': 9, 'ring': None})]
        for token in ('tenant-token', 'installation-token'):
            self.assertIsNone(json.loads(self.get(token, events)['body'])['last_sha'])

    def test_the_status_carries_the_live_code_for_the_deployer(self):
        self.assertEqual(json.loads(self.get('tenant-token')['body'])['live_code'], '')  # SLOW-PATH-NO-ROLLOUT-WAIT: none yet

    def test_no_observation_yet_is_200_with_nulls(self):
        answered = self.get('tenant-token')
        self.assertEqual(answered['statusCode'], 200)
        self.assertEqual(json.loads(answered['body']), {'last_sha': None, 'last_build': None, 'observed_at': None,
                                                        'ring': None, 'head': None, 'pending': None, 'source': 'registry',
                                                        'cycle': None, 'cycles': [], 'config_version': {}, 'cost': None, 'fast': [], 'runner_warm': [], 'image_live': [], 'successor': [], 'stacks': [], 'image_swap': [], 'image_retired': [], 'image_reload': [], 'ecs': [], 'runner_life': [], 'task_up': [], 'prune': [], 'live_code': '', 'canary': [], 'bisect': None,
                                                    'culprit': None, 'bisect_note': None, 'in_progress': None, 'lost': None})

    def test_no_token_or_an_unknown_one_is_refused_before_anything_is_read(self):
        self.assertEqual(self.get(None)['statusCode'], 401)
        self.assertEqual(self.get('stranger')['statusCode'], 401)

    def test_a_broken_record_reads_as_null(self):
        events = [(None, 1, {'last_sha': 'x', 'last_build': 'not json', 'observed_at': 1})]
        self.assertEqual(json.loads(self.get('tenant-token', events)['body'])['last_build'], None)


class Fake(BaseHTTPRequestHandler):
    """The doorbell (any path: POST) and the port (GET /v1/deploy/status), by what the test set on the server."""

    def log_message(self, *args):
        pass

    def reply(self, status, body):
        data = body.encode()
        self.send_response(status)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.server.rung.append(self.headers.get('Authorization'))
        token_ok = self.headers.get('Authorization') == f'Bearer {TOKEN}'
        if not token_ok:
            return self.reply(401, 'unauthorized')
        return self.reply(*self.server.doorbell)

    def do_GET(self):
        self.server.asked.append((self.path, self.headers.get('Authorization')))
        states = self.server.states
        self.reply(200, json.dumps(states.pop(0) if len(states) > 1 else states[0]))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Fake)
        self.server.rung, self.server.asked, self.server.doorbell, self.server.states = [], [], (202, '{"build":"p:b9"}'), [{}]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        url = f'http://127.0.0.1:{self.server.server_port}'
        self.environ = {'TOWER_DEPLOY_DOORBELL_URL': url + '/', 'TOWER_DEPLOY_DOORBELL_TOKEN': TOKEN,
                        'TOWER_PORT_URL': url, 'TOWER_PORT_TOKEN': 'port-token-of-the-test'}

    def run_main(self, *argv, environ=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = deploy.main(list(argv), self.environ if environ is None else environ)
        self.assertNotIn(TOKEN, out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def test_ring_202_prints_the_build_id(self):
        code, out, _ = self.run_main('ring')
        self.assertEqual((code, 'p:b9' in out), (0, True))
        self.assertEqual(self.server.rung, [f'Bearer {TOKEN}'])

    def test_ring_401_is_a_refusal_that_never_prints_the_token(self):
        code, _, err = self.run_main('ring', environ={**self.environ, 'TOWER_DEPLOY_DOORBELL_TOKEN': 'wrong-token-value'})
        self.assertEqual(code, 1)
        self.assertIn('401', err)
        self.assertNotIn('wrong-token-value', err)

    def test_ring_409_says_a_build_runs_and_offers_follow(self):
        self.server.doorbell = (409, '{"error":"ResourceInUseException"}')
        code, out, _ = self.run_main('ring')
        self.assertEqual(code, 2)
        self.assertIn('running', out)
        self.assertIn('follow', out)

    def test_missing_doorbell_variables_are_named_exactly(self):
        code, _, err = self.run_main('ring', environ={})
        self.assertEqual(code, 2)
        self.assertIn('TOWER_DEPLOY_DOORBELL_URL', err)
        self.assertIn('TOWER_DEPLOY_DOORBELL_TOKEN', err)
        self.assertIn('Daniel', err)
        self.assertEqual(self.server.rung, [])

    def test_status_prints_the_sha_and_why_it_failed(self):
        self.server.states = [{'last_sha': 'a0bd4d1', 'doorbell_busy': None, 'last_build': {
            'status': 'failed', 'failed': ['tower-app-port'], 'build_id': 'p:b1', 'base_head': 'cd216bd63',
            'started': 1, 'ended': 2, 'tail': 'Waiter StackUpdateComplete failed'}}]
        code, out, _ = self.run_main('status')
        self.assertEqual(code, 0)
        for text in ('a0bd4d1', 'failed', 'tower-app-port', 'Waiter StackUpdateComplete failed'):
            self.assertIn(text, out)
        self.assertEqual(self.server.asked[0], ('/v1/deploy/status', 'Bearer port-token-of-the-test'))

    def follow(self, states, held=True, **kwargs):
        """follow against a fake port; held (PORT-LONG-POLL, the live port): each answer after the first waited 15 s on
        the test's clock and is marked; not held: an old port, unmarked at once. An Exception in states is raised."""
        sleeps, clock, calls = [], [0.0], []

        def call(method, path):
            calls.append(path)
            state = states.pop(0) if len(states) > 1 else states[0]
            if isinstance(state, Exception):
                raise state
            if not held:
                return state
            clock[0] += 15.0 if len(calls) > 1 else 0.0
            return dict(state, long_poll={'seen': json.dumps(state, sort_keys=True), 'waited_s': 15.0, 'changed': True})
        port = mock.Mock()
        port.call.side_effect = call

        def sleep(seconds):
            sleeps.append(seconds)
            clock[0] += seconds
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.dict(os.environ, {}, clear=False):
            code = deploy.follow(port, sleep=sleep, clock=lambda: clock[0], now=lambda: 1000.0, **kwargs)
        return code, out.getvalue() + err.getvalue(), sleeps

    def test_follow_succeeds_when_last_sha_reaches_the_target(self):
        code, _, sleeps = self.follow([{'last_sha': 'old', 'last_build': None}, {'last_sha': 'new', 'last_build': None}],
                                      target='new')
        self.assertEqual((code, sleeps), (0, []))

    def test_follow_backs_off_and_reports_a_failed_build_newer_than_the_ring(self):
        old = {'last_sha': 'a', 'last_build': {'status': 'failed', 'started': 10, 'failed': ['old'], 'build_id': 'p:old'}}
        new = {'last_sha': 'a', 'last_build': {'status': 'failed', 'started': 990, 'failed': ['tower-app-port'],
                                               'build_id': 'p:new', 'tail': 'the reason'}}
        code, out, sleeps = self.follow([old, old, new], target='b')
        self.assertEqual(code, 1)
        self.assertIn('tower-app-port', out)
        self.assertIn('the reason', out)
        self.assertNotIn('old', out.replace('old_', ''))
        self.assertEqual(sleeps, [])  # LONG-POLL-ONLY: the port held each read; no pause

    def test_follow_tells_no_observation_yet_from_a_failed_build(self):
        none = {'last_sha': None, 'last_build': None, 'observed_at': None, 'ring': None, 'head': None, 'pending': None,
                'source': 'registry'}
        code, out, _ = self.follow([none], target='b')
        self.assertEqual(code, 2)
        self.assertIn('nothing yet', out)
        self.assertNotIn('failed', out.replace('not a failed build', ''))
        seen = {'last_sha': 'a', 'last_build': {'status': 'failed', 'started': 990, 'failed': ['x'], 'build_id': 'p:n'},
                'observed_at': 995, 'ring': {'action': 'skip', 'reason': 'backoff', 'at': 995}}
        self.assertEqual(self.follow([none, seen], target='b')[0], 1)

    def test_follow_says_the_service_is_not_reporting_when_a_ring_has_a_stale_observation(self):
        stale = {'last_sha': 'a', 'last_build': None, 'observed_at': 1000 - 301,
                 'ring': {'action': 'ring', 'reason': 'started', 'at': 699}}
        code, out, sleeps = self.follow([stale], target='b')
        self.assertEqual((code, sleeps), (2, []))
        self.assertIn('not reporting', out)
        fresh = dict(stale, observed_at=1000 - 100)
        self.assertEqual(self.follow([fresh, {'last_sha': 'b', 'last_build': None}], target='b')[0], 0)
        quiet = dict(stale, ring={'action': 'skip', 'reason': 'deployed', 'at': 1})
        self.assertIn('ran out', self.follow([quiet], target='b')[1])

    def test_follow_a_named_build_ignores_the_others(self):
        other = {'last_sha': 'a', 'last_build': {'status': 'failed', 'started': 999, 'failed': ['x'], 'build_id': 'p:other'}}
        mine = {'last_sha': 'a', 'last_build': {'status': 'succeeded', 'started': 999, 'failed': [], 'build_id': 'p:b9'}}
        self.assertEqual(self.follow([other, mine], build_id='p:b9')[0], 0)

    def test_follow_a_build_that_ended_rolling_takes_the_verdict_of_the_build_that_verifies_it(self):
        # SLOW-PATH-NO-ROLLOUT-WAIT: the rung build starts the rollouts and ends; the deploy is decided by the next build
        rolling = {'last_sha': 'a', 'last_build': {'status': 'rolling', 'started': 1000, 'failed': [], 'build_id': 'p:b9',
                                                   'rolling': {'stacks': {'runner': {}, 'service': {}}}}}
        for verdict, code in (('succeeded', 0), ('failed', 1)):
            verified = {'last_sha': 'a', 'last_build': {'status': verdict, 'started': 1500, 'failed': [], 'build_id': 'p:b10'}}
            self.assertEqual(self.follow([rolling, rolling, verified], build_id='p:b9')[0], code)
        out = io.StringIO()
        deploy.describe(rolling, out)
        self.assertIn('rolling: runner service started and not waited', out.getvalue())

    def test_status_says_the_builds_seconds_and_the_reload_in_place(self):
        # FAST-PATH-RELOAD: what a code-only merge's deploy cost, and how long its swap took, from `scripts/deploy status`
        state = {'last_sha': 'a', 'last_build': {
            'status': 'succeeded', 'build_id': 'p:b9', 'base_head': 'b' * 40, 'started': 1000, 'ended': 1031, 'seconds': 31,
            'steps': [{'n': 'classify', 's': 'ok', 't': 0}, {'n': 'reload', 's': 'ok', 't': 24}],
            'reload': {'state': 'live', 's': 23, 'sha256': 'c' * 64, 'head': 'b' * 40,
                       'reloaded': {'reload_s': 6.2, 'boot_s': 4.1}, 'proven': {'ticks': 11, 'window_s': 10.4}}}}
        out = io.StringIO()
        deploy.describe(state, out)
        self.assertIn('build_seconds: 31, classify 0s, reload 24s', out.getvalue())
        self.assertIn('reload: live in 23s (bundle cccccccccccc at bbbbbbbbbbbb); reloaded 6.2s after the order (boot 4.1s); '
                      'proven by 11 good ticks in 10.4s', out.getvalue())
        state['last_build']['reload'] = {'state': 'timeout', 's': 150, 'sha256': 'c' * 64, 'head': 'b' * 40, 'why': 'x'}
        out = io.StringIO()
        deploy.describe(state, out)
        self.assertIn('reload: timeout in 150s (bundle cccccccccccc at bbbbbbbbbbbb): x', out.getvalue())

    def test_follow_times_out_with_2_after_the_bounded_wait(self):
        code, out, sleeps = self.follow([{'last_sha': 'a', 'last_build': None}], target='b')
        self.assertEqual((code, sleeps), (2, []))
        self.assertIn('ran out', out)
        # a port that cannot be read: the pauses of before (a backoff on the failure), within the same bounded wait
        code, out, sleeps = self.follow([gate_infra.Refused(503, 'unavailable')], target='b')
        self.assertEqual(code, 2)
        self.assertLessEqual(sum(sleeps), 2400)
        self.assertGreater(sum(sleeps), 2300)
        self.assertIn('ran out', out)

    def held_follow(self, answers, wait_each_s=15.0, **kwargs):
        """follow against a port with the long poll (PORT-LONG-POLL): each answer after the first is held wait_each_s
        on the test's clock, and marked; a sleep is a failure."""
        clock, paths = [0.0], []

        def call(method, path):
            paths.append(path)
            clock[0] += wait_each_s if len(paths) > 1 else 0.0
            state = answers.pop(0) if len(answers) > 1 else answers[0]
            return dict(state, long_poll={'seen': state['digest'], 'waited_s': wait_each_s, 'changed': True})
        port = mock.Mock()
        port.call.side_effect = call
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = deploy.follow(port, sleep=lambda s: self.fail(f'slept {s} s against a waiting port'),
                                 clock=lambda: clock[0], now=lambda: 1000.0, **kwargs)
        return code, out.getvalue(), paths

    def test_follow_against_a_waiting_port_asks_again_at_once_with_what_it_saw(self):
        old = {'last_sha': 'a', 'last_build': None, 'digest': 'd1'}
        new = {'last_sha': 'b', 'last_build': None, 'digest': 'd2'}
        code, _, paths = self.held_follow([old, old, new], target='b')
        self.assertEqual(code, 0)
        self.assertEqual(paths, ['/v1/deploy/status?wait_s=15', '/v1/deploy/status?wait_s=15&seen=d1',
                                 '/v1/deploy/status?wait_s=15&seen=d1'])

    def test_follow_against_a_waiting_port_keeps_the_deadline_and_its_message(self):
        quiet = {'last_sha': 'a', 'last_build': None, 'digest': 'd1'}
        code, out, paths = self.held_follow([quiet], target='b')
        self.assertEqual(code, 2)
        self.assertIn('ran out', out)
        self.assertEqual(len(paths), 2400 // 15 + 1)  # one read each 15 s at most: never later than the pauses

    def test_follow_against_an_old_port_says_so_and_never_pauses_on_an_interval(self):
        # LONG-POLL-ONLY: an old port ignores the query and answers at once, unmarked: said, exit 2, no pause
        code, out, sleeps = self.follow([{'last_sha': 'a', 'last_build': None}, {'last_sha': 'b', 'last_build': None}],
                                        held=False, target='b')
        self.assertEqual((code, sleeps), (2, []))
        self.assertIn('without holding the read (no long_poll: a port older than PORT-LONG-POLL)', out)
        # its verdict, when the first answer already has it, is still the verdict
        self.assertEqual(self.follow([{'last_sha': 'b', 'last_build': None}], held=False, target='b')[0], 0)

    def test_follow_backs_off_on_a_failed_read_and_starts_over_at_the_next_answer(self):
        refused, quiet = gate_infra.Refused(503, 'unavailable'), {'last_sha': 'a', 'last_build': None}
        code, out, sleeps = self.follow([refused, refused, quiet, refused, {'last_sha': 'b', 'last_build': None}],
                                        target='b')
        self.assertEqual((code, sleeps), (0, [15, 22.5, 15]))
        self.assertIn('the status could not be read', out)

    def test_follow_through_the_real_client_reads_the_fake_port(self):
        self.server.states = [{'last_sha': 'new', 'last_build': None}]
        code, _, _ = self.run_main('follow', '--target', 'new')
        self.assertEqual(code, 0)

    def test_status_without_the_port_variables_says_which(self):
        code, _, err = self.run_main('status', environ={})
        self.assertEqual(code, 2)
        self.assertIn('TOWER_PORT_URL', err)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.bootstrap = json.loads((ROOT / 'infra/aws/bootstrap.json').read_text())
        self.spec = self.bootstrap['Resources']['DeployProject']['Properties']['Source']['BuildSpec']

    def statement(self, template, role, sid):
        policies = template['Resources'][role]['Properties']['Policies']
        return next(s for p in policies for s in p['PolicyDocument']['Statement'] if s['Sid'] == sid)

    def test_the_buildspec_clones_then_delegates_and_fails_loudly_without_the_script(self):
        self.assertIn('git clone --quiet --single-branch --branch "$BASE_BRANCH" "$ORIGIN_REPO_URL" repo', self.spec)
        self.assertNotIn('origin', self.spec.replace('$ORIGIN_REPO_URL', ''))  # BUILD-NO-ORIGIN: a public clone, no Origin CLI
        self.assertIn('aws sns publish --topic-arn "$ALERTS_TOPIC_ARN"', self.spec)
        lines = [line.strip() for line in self.spec.splitlines()]
        self.assertIn('- bash repo/infra/aws/deploy.sh', lines)
        check = next(line for line in lines if line.startswith('- test -f repo/infra/aws/deploy.sh'))
        self.assertTrue(check.endswith('false; }'))
        self.assertLess(lines.index(check), lines.index('- bash repo/infra/aws/deploy.sh'))
        for inline in ('cloudformation deploy', 'docker build', 'put-parameter'):
            self.assertNotIn(inline, self.spec)

    def test_the_deployer_may_write_last_build_and_nothing_wider(self):
        write = self.statement(self.bootstrap, 'DeployerRole', 'RecordTheLastDeploy')
        arns = [r['Fn::Sub'].split('parameter')[1] for r in write['Resource']]
        self.assertEqual((write['Action'], arns), ('ssm:PutParameter', ['/tower/deploy/last-sha', '/tower/deploy/last-build']))

    def test_the_port_role_has_no_ssm_grant_the_service_publishes_the_status_instead(self):
        port = json.loads((ROOT / 'infra/aws/stacks/40-port.json').read_text())
        for policy in port['Resources']['PortRole']['Properties']['Policies']:
            for each in policy['PolicyDocument']['Statement']:
                self.assertNotIn('ssm', json.dumps(each.get('Action')).lower(), each.get('Sid'))
                self.assertNotIn('deploy/last', json.dumps(each.get('Resource')))

    def test_deploy_sh_exists_and_is_executable_bash(self):
        path = ROOT / 'infra/aws/deploy.sh'
        self.assertTrue(path.read_text().startswith('#!/usr/bin/env bash'))
        self.assertTrue(re.search(r'^set -u$', path.read_text(), re.M))


# DEPLOY-TEST-SHARDS: this suite took 560 s alone on the runner, of a check's 900 s; on 11/11 four deliveries shared the
# runner and the check timed out in three of them, with no test red. Its wrappers run it in three parts, each a check of
# its own on a slot of its own: deploy.test.sh the classes but SlowPathShTests, deploy-slow-a/-b.test.sh that class's
# tests, every other one by name. Without the variable (a local run, a class or a test by name) nothing is left out.


if __name__ == '__main__':
    unittest.main()
