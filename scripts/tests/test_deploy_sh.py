"""The session's deploy (DEP1), the tests that run infra/aws/deploy.sh: against a stubbed aws/docker on the PATH and a git
repo made here (DeployShTests, SlowPathShTests). Hermetic: no AWS call, no network beyond 127.0.0.1.

DEPLOY-SH-OWN-MODULE: apart from test_deploy.py, which imports the engine (http_port, gate_infra, scripts/lib/deploy.py)
for its status, CLI and smoke tests: these read no module of the engine, so their three checks (deploy-slow-{a,b,c})
are selected by the deploy's own files only. #630's gate ran them for a change of scripts/lib/gate_infra.py (301, 285
and 205 s of its 318 s), which they never import.
"""
import contextlib
import hashlib
import io
import json
import time
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent

TOKEN = 'doorbell-token-of-the-test-0123456789'
# two stacks that go side by side: each one's apply ends when the other's has started (the stub's STUB_UNTIL)
SIDE_BY_SIDE = 'tower-app-service:tower-app-runner,tower-app-runner:tower-app-service'
AWS_STUB = r'''#!/usr/bin/env bash
echo "aws $*" >> "$STUB_DIR/calls"
case "$1 $2" in
  "ssm get-parameter")
    while [ $# -gt 0 ]; do case "$1" in --name) n="$2";; esac; shift; done
    if [ "$n" = /tower/deploy/cloudflare-api-token ]; then [ -n "${STUB_CF_TOKEN:-}" ] && { echo "$STUB_CF_TOKEN"; exit 0; } || exit 255; fi
    if [ "$n" = /tower/deploy/last-build ]; then [ -n "${STUB_LAST_BUILD:-}" ] && { echo "$STUB_LAST_BUILD"; exit 0; } || exit 255; fi
    if [ "$n" = /tower/deploy/ack-path ]; then [ -n "${STUB_ACK_PATH:-}" ] && { echo "$STUB_ACK_PATH"; exit 0; } || exit 255; fi
    [ -f "$STUB_DIR/param$(echo "$n" | tr / _)" ] && { cat "$STUB_DIR/param$(echo "$n" | tr / _)"; exit 0; }
    [ -n "${STUB_LAST:-}" ] && { echo "$STUB_LAST"; exit 0; } || exit 255 ;;
  "cloudformation describe-stacks")
    [ -n "${STUB_SLOW_READS:-}" ] && sleep "$STUB_SLOW_READS"  # a busy runner: every read of a stack takes this long
    case "$*" in *"--output json"*) json=1 ;; *) json= ;; esac
    while [ $# -gt 0 ]; do case "$1" in --stack-name) s="$2";; esac; shift; done
    [ -n "$json" ] && [ -f "$STUB_DIR/stack_$s.json" ] && { cat "$STUB_DIR/stack_$s.json"; exit 0; }
    # SLOW-PATH-NO-ROLLOUT-WAIT: status_<stack>: one "STATUS<tab>TAG" line per call, the last one kept (a rollout that ends)
    if [ -z "$json" ] && [ -f "$STUB_DIR/status_$s" ]; then
      head -n 1 "$STUB_DIR/status_$s"; [ "$(wc -l < "$STUB_DIR/status_$s")" -gt 1 ] && sed -i 1d "$STUB_DIR/status_$s"; exit 0
    fi
    case " ${STUB_TAGGED:-} " in *" $s "*) printf 'UPDATE_COMPLETE\t%s\n' "${STUB_TAG_VALUE:-}"; exit 0 ;; esac
    exit 255 ;;
  "ssm put-parameter")
    while [ $# -gt 0 ]; do case "$1" in --name) n="$2";; --value) v="$2";; esac; shift; done
    if [ "${STUB_FAIL_PUT:-}" = "$n" ]; then echo "AccessDeniedException on $n" >&2; exit 254; fi
    # SSM Standard refuses a value over 4096; STUB_FAIL_FULL refuses a full record (the minimal one has no "hashes")
    if [ "${#v}" -gt 4096 ] || { [ -n "${STUB_FAIL_FULL:-}" ] && [ "$n" = /tower/deploy/last-build ] && case "$v" in *'"hashes"'*) true ;; *) false ;; esac; }; then
      echo "ValidationException: value too long or refused" >&2; exit 254; fi
    [ "$n" = /tower/deploy/last-build ] && printf '%s\n' "$v" >> "$STUB_DIR/last-build.history"
    printf '%s' "$v" > "$STUB_DIR/ssm$(echo "$n" | tr / _)" ;;
  "cloudformation describe-stack-events")
    case "$*" in *"--max-items 1"*) [ -n "${STUB_LAST_EVENT:-}" ] && { echo "$STUB_LAST_EVENT"; exit 0; } || exit 255 ;; esac
    case "$*" in *"--output json"*) [ -n "${STUB_EVENTS_JSON:-}" ] && { echo "$STUB_EVENTS_JSON"; exit 0; } || exit 255 ;; esac  # SLOW-PATH-STACK-PARTS
    printf '2020-01-01T04:03:00.000000+00:00\tAckIntegration\tCREATE_FAILED\tOLD PORT7 failure\n'
    printf '%s\tNewResource\tUPDATE_FAILED\tTHIS build failure\n' "$(date -u +%Y-%m-%dT%H:%M:%S.000000+00:00)" ;;
  "cloudformation get-template") [ -f "$STUB_DIR/bootstrap.json" ] && { cat "$STUB_DIR/bootstrap.json"; exit 0; } || exit 255 ;;  # BOOTSTRAP-DRIFT
  "ecr describe-repositories") exit 0 ;;
  "ecr describe-images") exit 255 ;;
  "ecr get-login-password") echo "ecr-password-0123456789abcdef0123456789abcdef" ;;
  "cloudformation execute-change-set")
    while [ $# -gt 0 ]; do case "$1" in --change-set-name) a="$2";; esac; shift; done
    s="${a##*changeSet/awscli-}"; s="${s%%/*}"
    if [ "${STUB_FAIL_EXECUTE:-}" = "$s" ]; then echo "An error occurred (InvalidChangeSetStatus) when calling the ExecuteChangeSet operation" >&2; exit 254; fi
    echo "execute $s $(date +%s.%N)" >> "$STUB_DIR/events" ;;
  "cloudformation deploy")
    while [ $# -gt 0 ]; do case "$1" in --stack-name) s="$2";; --no-execute-changeset) noexec=1;; esac; shift; done
    if [ "${STUB_FAIL_STACK:-}" = "$s" ]; then
      [ -n "${STUB_CLI_ERROR:-}" ] && echo "An error occurred (ValidationError) when calling the CreateChangeSet operation: Template format error" >&2
      echo "Failed to create/update $s: Authorization: Bearer abcdefghijklmnop12345 token=$TOWER_DEPLOY_DOORBELL_TOKEN" >&2
      exit 255
    fi
    [ -n "${STUB_FAIL_ROLLBACK:-}" ] && case "$*" in *rollback-*) echo "rollback deploy of $s failed" >&2; exit 255 ;; esac
    echo "start $s $(date +%s.%N)" >> "$STUB_DIR/events"
    if [ -n "${noexec:-}" ]; then  # SLOW-PATH-NO-ROLLOUT-WAIT: the change set is created; nothing is executed, nothing is waited
      case " ${STUB_NOCHANGE:-} " in *" $s "*) echo "No changes to deploy. Stack $s is up to date"; exit 0 ;; esac
      echo "Changeset created successfully. Run the following command to review changes:"
      [ -n "${STUB_NO_ARN:-}" ] || echo "aws cloudformation describe-change-set --change-set-name arn:aws-partition:cloudformation:us-east-1:1:changeSet/awscli-$s/1"
      exit 0
    fi
    for pair in $(echo "${STUB_SLEEP:-}" | tr ',' ' '); do [ "${pair%%:*}" = "$s" ] && sleep "${pair#*:}"; done
    # STUB_UNTIL=a:b,...: the apply of stack a ends when stack b's has started (30 s at most): two stacks that go side by
    # side overlap by this event, not by a sleep the scheduler must beat (the gate's red of #592, 12/11: on a runner task
    # just rolled out the suite took 563 s and the runner's apply started 15 ms after the service's 1 s sleep ended)
    for pair in $(echo "${STUB_UNTIL:-}" | tr ',' ' '); do
      if [ "${pair%%:*}" = "$s" ]; then
        n=0; until grep -q "^start ${pair#*:} " "$STUB_DIR/events" 2>/dev/null || [ "$n" -ge 600 ]; do sleep 0.05; n=$((n + 1)); done
      fi
    done
    echo "end $s $(date +%s.%N)" >> "$STUB_DIR/events"
    case " ${STUB_NOCHANGE:-} " in *" $s "*) echo "No changes to deploy. Stack $s is up to date"; exit 0 ;; esac
    echo "Successfully created/updated stack - $s" ;;
esac
exit 0
'''
DOCKER_STUB = r'''#!/usr/bin/env bash
echo "docker $*" >> "$STUB_DIR/calls"
[ "$1" = login ] && cat > /dev/null
[ "$1" = build ] && [ -n "${STUB_FAIL_IMAGE:-}" ] && { echo "docker build failed for $STUB_FAIL_IMAGE" >&2; exit 1; }
exit 0
'''


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


LAMBDA_KEYS = json.dumps({'tower-port-api': 'artifacts/lambda/tower-port-api/aa.zip', 'tower-port-ack-ingress': 'artifacts/lambda/tower-port-ack-ingress/bb.zip',
                          'tower-port-webhook-consumer': 'artifacts/lambda/tower-port-webhook-consumer/cc.zip', 'deps': 'artifacts/lambda/deps/dd.zip'})



class DeployShTests(unittest.TestCase):
    def setUp(self):
        # deploy.sh writes its record with jq (the deploy build has it). A runner image without it made every test here fail on
        # 08/11 with an unreadable 'JSON None'; say the missing tool instead (the service image installs it).
        if shutil.which('jq') is None:
            self.fail('missing host tool: jq (deploy.sh needs it; infra/service/Dockerfile installs it)')
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        repo = self.tmp / 'repo'
        for path in ('infra/service/Dockerfile', 'infra/db/0001.sql', 'infra/ingress/Dockerfile',
                     'infra/aws/stacks/10-network.json', 'infra/aws/stacks/40-port.json'):
            (repo / path).parent.mkdir(parents=True, exist_ok=True)
            (repo / path).write_text('x\n')
        git(repo, 'init', '-q')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base')
        self.head = git(repo, 'rev-parse', 'HEAD')
        self.stubs = self.tmp / 'bin'
        self.stubs.mkdir()
        for name, text in (('aws', AWS_STUB), ('docker', DOCKER_STUB)):
            (self.stubs / name).write_text(text)
            (self.stubs / name).chmod(0o755)
        self.state = self.tmp / 'state'
        self.state.mkdir()

    def five_stacks(self):
        repo = self.tmp / 'repo'
        for name in ('20-data', '30-service', '50-runner'):
            (repo / f'infra/aws/stacks/{name}.json').write_text('x\n')
        (repo / 'infra/aws/order.json').write_text((ROOT / 'infra/aws/order.json').read_text())
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'five')
        self.head = git(repo, 'rev-parse', 'HEAD')

    def events(self):
        out = {}
        for line in (self.state / 'events').read_text().splitlines():
            kind, stack, at = line.split()
            out[(kind, stack.replace('tower-app-', ''))] = float(at)
        return out

    def run_deploy(self, **extra):
        env = {**os.environ, 'PATH': f'{self.stubs}:{os.environ["PATH"]}', 'STUB_DIR': str(self.state),
               'DEPLOY_REPO': str(self.tmp / 'repo'), 'IMAGE_REGISTRY': 'registry.test', 'CFN_EXEC_ROLE_ARN': 'arn:role',
               'CODEBUILD_BUILD_ID': 'tower-infra-deploy:b1', 'TOWER_DEPLOY_DOORBELL_TOKEN': TOKEN, 'DEPLOY_LAMBDA_PACKAGE_CMD': "echo noise; echo '" + LAMBDA_KEYS + "'", **extra}
        done = subprocess.run(['bash', str(ROOT / 'infra/aws/deploy.sh')], env=env, capture_output=True, text=True,
                              timeout=60, check=False)
        return done

    def recorded(self, name):
        path = self.state / ('ssm' + name.replace('/', '_'))
        return path.read_text() if path.exists() else None

    def build(self):
        return json.loads(self.recorded('/tower/deploy/last-build'))

    # --- DEP-WATCHDOG: last-build is written at the start, at each step, always small, and on ANY exit -----------------------
    def history(self):
        return [json.loads(line) for line in (self.state / 'last-build.history').read_text().splitlines()]

    def test_a_record_of_the_build_is_one_jq_call_not_one_per_part(self):
        # RECORD-ONE-JQ: each record was ~33 jq calls, 3.2 of a tested deploy's 3.9 s and the CPU the deploy's tests share
        shim, calls = self.tmp / 'jq-shim', self.tmp / 'jq-calls'
        shim.mkdir()
        real = shutil.which('jq')
        (shim / 'jq').write_text(f'#!/usr/bin/env bash\necho >>{calls}\nexec {real} "$@"\n')
        (shim / 'jq').chmod(0o755)
        done = self.run_deploy(STUB_LAST='old', PATH=f'{shim}:{self.stubs}:{os.environ["PATH"]}')
        self.assertEqual(done.returncode, 0, done.stderr)
        records = len(self.history())
        self.assertLess(len(calls.read_text().splitlines()) / records, 12)  # with what the build itself asks of jq

    def test_last_build_is_in_progress_from_the_start_and_lists_the_steps(self):
        done = self.run_deploy(STUB_LAST='old')
        self.assertEqual(done.returncode, 0, done.stderr)
        records = self.history()
        first = records[0]
        self.assertEqual((first['status'], first['ended'], first['build_id'], first['base_head']),
                         ('in_progress', 0, 'tower-infra-deploy:b1', self.head))
        self.assertTrue(any(each['status'] == 'in_progress' and each['step'].startswith('stack:') for each in records))
        names = {each['n']: each['s'] for each in records[-1]['steps']}
        self.assertEqual(names['classify'], 'ok')
        self.assertEqual(names['lambda-package'], 'ok')
        self.assertEqual(names['stack:network'], 'ok')
        self.assertEqual(records[-1]['status'], 'succeeded')
        # PROGRESS-AT-START: an in_progress record is a step's start (the first, before any step): none at a step's ok end
        self.assertEqual([each['updated'] for each in records[1:] if each['status'] == 'in_progress' and not each['step']], [])
        self.assertGreater(records[-1]['ended'], 0)

    def test_the_bootstrap_stack_is_read_back_and_compared_with_its_mirror_in_the_record(self):
        # BOOTSTRAP-DRIFT (BOOTSTRAP-MIRROR, req-667-reach 13/11): the stack only the Torre applies, read back by get-template
        # and compared in the canonical form with infra/aws/bootstrap.json: last-build.bootstrap, never a failed build
        repo = self.tmp / 'repo'
        (repo / 'infra/aws/bootstrap.json').write_text('{"Resources": {"Topic": {"Type": "AWS::SNS::Topic"}}, "Outputs": {}}\n')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'mirror')
        self.head = git(repo, 'rev-parse', 'HEAD')
        for applied, verdict in (('{ "Outputs": {}, "Resources": { "Topic": { "Type": "AWS::SNS::Topic" } } }', 'same'),
                                 ('{"Resources": {"Topic": {"Type": "AWS::SQS::Queue"}}, "Outputs": {}}', 'drift'),
                                 (None, 'unread')):
            (self.state / 'bootstrap.json').unlink(missing_ok=True)
            if applied is not None:
                (self.state / 'bootstrap.json').write_text(applied)
            done = self.run_deploy(STUB_LAST='old')
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual((self.build()['bootstrap'], self.build()['status']), (verdict, 'succeeded'))

    def test_a_record_over_4000_bytes_is_shrunk_in_order_and_still_written(self):
        prev = json.dumps({'hashes': {f'stack{i}': 'h' * 20 for i in range(60)}, 'stacks': {f'tower-app-s{i}': 100 + i for i in range(80)}})
        smoke = ("python3 -c \"import json;print(json.dumps({'ok': True, 'variants': "
                 "{f'v{i}': {'ms': 500 + i, 'body': 'x' * 40} for i in range(22)}}))\"")
        done = self.run_deploy(STUB_LAST='old', STUB_LAST_BUILD=prev, DEPLOY_ACK_SMOKE_CMD=smoke, DEPLOY_TAIL_CHARS='3000')
        self.assertEqual(done.returncode, 0, done.stderr)
        text = self.recorded('/tower/deploy/last-build')
        self.assertLessEqual(len(text.encode()), 4000)
        build = json.loads(text)
        self.assertEqual((build['status'], build['build_id']), ('succeeded', 'tower-infra-deploy:b1'))
        self.assertGreater(build['ended'], 0)

    def test_a_refused_full_record_falls_back_to_the_minimal_one(self):
        done = self.run_deploy(STUB_LAST='old', STUB_FAIL_FULL='1')
        self.assertEqual(done.returncode, 0, done.stderr)
        build = self.build()
        self.assertEqual(set(build), {'build_id', 'base_head', 'status', 'started', 'ended', 'failed_step', 'error'})
        self.assertEqual((build['status'], build['base_head']), ('succeeded', self.head))
        self.assertIn('record too large or refused', build['error'])
        self.assertGreater(build['ended'], 0)

    def test_a_waited_stack_s_real_change_says_where_its_seconds_went(self):
        # SLOW-PATH-STACK-PARTS: the port stack took 222 s for one property (live 11/11) and nothing said in what: the stack's
        # own events give the four slowest resources (up to the cleanup) and the cleanup the CLI's deploy also waits for
        # the operation's events are an hour ahead of the test's clock and the earlier operation's an hour behind it: the
        # script keeps the events from the instant it took the stack, and on a slow runner it took the stack 5 s after
        # these were written, so events 3 s ahead were already behind it (the gate's red of #527, 11/11: the suite at 560 s)
        def at(seconds, ahead=3600):
            return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(time.time() + ahead + seconds)) + '.250000+00:00'
        events = [[at(100), 'tower-app-port', 'UPDATE_COMPLETE'], [at(98), 'OldVersion', 'DELETE_COMPLETE'],
                  [at(60), 'OldVersion', 'DELETE_IN_PROGRESS'], [at(60), 'tower-app-port', 'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS'],
                  [at(58), 'PortAlias', 'UPDATE_COMPLETE'], [at(50), 'PortAlias', 'UPDATE_IN_PROGRESS'],
                  [at(50), 'PortFunction', 'UPDATE_COMPLETE'], [at(5), 'PortFunction', 'UPDATE_IN_PROGRESS'],
                  [at(4), 'PortIntegration', 'UPDATE_COMPLETE'], [at(3), 'PortIntegration', 'UPDATE_IN_PROGRESS'],
                  [at(3), 'A', 'UPDATE_COMPLETE'], [at(3), 'A', 'UPDATE_IN_PROGRESS'], [at(3), 'B', 'UPDATE_COMPLETE'],
                  [at(2), 'tower-app-port', 'UPDATE_IN_PROGRESS'], [at(-500, -3600), 'PortFunction', 'UPDATE_COMPLETE'],
                  [at(-900, -3600), 'PortFunction', 'UPDATE_IN_PROGRESS']]  # the last two: an earlier operation, not this one
        before = json.dumps({'parts': {'tower-app-network': {'Vpc': 60}, 'tower-app-gone': {'Queue': 9}},
                             'stacks': {'tower-app-network': 66, 'tower-app-gone': 12}})
        done = self.run_deploy(STUB_LAST='old', STUB_LAST_BUILD=before, STUB_EVENTS_JSON=json.dumps(events),
                               STUB_NOCHANGE='tower-app-network')
        self.assertEqual(done.returncode, 0, done.stderr)
        parts = self.build()['parts']
        self.assertEqual(parts['tower-app-port'], {'PortFunction': 45, 'PortAlias': 8, 'PortIntegration': 1, 'A': 0, 'cleanup': 40})
        self.assertEqual(parts['tower-app-network'], {'Vpc': 60})  # a stack this build did not change keeps its earlier figure
        self.assertNotIn('tower-app-gone', parts)  # ACK-CANARY-GONE: a stack with no template in the tree keeps none
        self.assertNotIn('tower-app-gone', self.build()['stacks'])
        self.assertNotIn('tower-app-service', parts)  # a rollout that is not waited has no end here to measure to
        self.assertIn('[port] parts: {"PortFunction":45', done.stdout)

    def test_a_stack_whose_events_cannot_be_read_records_no_parts_and_the_build_goes_on(self):
        done = self.run_deploy(STUB_LAST='old')  # the stub answers the events' read with an error
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.build()['parts'], {})

    def test_the_hard_deadline_records_a_failed_build_with_the_step_that_hung(self):
        # the deadline is counted from the build's start: 3 s was less than the steps before the first stack take on a busy
        # runner (the gate's red of #510, 11/11: failed_step 'before-first-step'); 20 s leaves them room, the hung stack 300
        started = time.time()
        done = self.run_deploy(STUB_LAST='old', STUB_SLEEP='tower-app-network:300', DEPLOY_HARD_S='20')
        self.assertLess(time.time() - started, 120)
        self.assertNotEqual(done.returncode, 0)
        build = self.build()
        self.assertEqual(build['status'], 'failed')
        self.assertEqual(build['failed_step'], 'stack:network')
        self.assertIn('hard deadline 20s', build['tail'])
        self.assertGreater(build['ended'], 0)
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))

    def test_a_term_signal_records_a_failed_build(self):
        env = {**os.environ, 'PATH': f'{self.stubs}:{os.environ["PATH"]}', 'STUB_DIR': str(self.state), 'STUB_LAST': 'old',
               'STUB_SLEEP': 'tower-app-network:40', 'DEPLOY_REPO': str(self.tmp / 'repo'), 'IMAGE_REGISTRY': 'registry.test',
               'CFN_EXEC_ROLE_ARN': 'arn:role', 'CODEBUILD_BUILD_ID': 'tower-infra-deploy:b1', 'DEPLOY_LAMBDA_PACKAGE_CMD': 'true'}
        proc = subprocess.Popen(['bash', str(ROOT / 'infra/aws/deploy.sh')], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for _ in range(100):
            time.sleep(0.2)
            if (self.state / 'events').exists():
                break
        proc.terminate()
        proc.communicate(timeout=30)
        build = self.build()
        self.assertEqual((build['status'], build['failed_step']), ('failed', 'stack:network'))
        self.assertIn('terminated by SIGTERM', build['tail'])

    def test_lambda_packages_fail_fast_on_access_denied_and_no_stack_starts(self):
        done = self.run_deploy(STUB_LAST='old', DEPLOY_LAMBDA_PACKAGE_CMD='echo "AccessDenied: s3:PutObject" >&2; exit 1')
        self.assertEqual(done.returncode, 1)
        build = self.build()
        self.assertEqual((build['status'], build['failed_step']), ('failed', 'lambda-package'))
        self.assertIn('lambda-package', build['failed'])
        self.assertIn('PEDIDO A TORRE', build['tail'])
        step = [each for each in build['steps'] if each['n'] == 'lambda-package'][0]
        self.assertEqual(step['s'], 'failed')
        self.assertIn('AccessDenied: s3:PutObject', step['e'])  # the step's own output, so the status says WHY
        self.assertLessEqual(len(self.recorded('/tower/deploy/last-build').encode()), 4000)
        self.assertNotIn('cloudformation deploy', (self.state / 'calls').read_text())
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))

    def test_a_failed_stack_prints_only_this_operations_events_and_the_cli_error(self):
        self.five_stacks()
        done = self.run_deploy(STUB_LAST='old', STUB_FAIL_STACK='tower-app-port', STUB_CLI_ERROR='1')
        self.assertEqual(done.returncode, 1)
        log = done.stdout
        self.assertIn('THIS build failure', log)
        self.assertNotIn('OLD PORT7 failure', log)
        self.assertIn('[port] cli: An error occurred (ValidationError) when calling the CreateChangeSet operation', log)
        build = self.build()
        self.assertIn('An error occurred (ValidationError)', build['tail'])

    def test_success_writes_last_sha_and_a_succeeded_record(self):
        done = self.run_deploy(STUB_LAST='old')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), self.head)
        calls = (self.state / 'calls').read_text()
        self.assertEqual(calls.count('docker build'), 2)
        self.assertEqual(calls.count('cloudformation deploy'), 2)
        self.assertIn('--stack-name tower-app-network', calls)
        self.assertIn('--stack-name tower-app-port', calls)
        self.assertEqual(self.recorded('/tower/deploy/image/service'),
                         f'registry.test/tower-service:{self.recorded("/tower/deploy/image/service").rsplit(":", 1)[1]}')
        build = self.build()
        self.assertEqual((build['status'], build['failed'], build['base_head'], build['build_id']),
                         ('succeeded', [], self.head, 'tower-infra-deploy:b1'))
        self.assertLessEqual(build['started'], build['ended'])
        self.assertIn('start tower-app-port', build['tail'])

    def test_an_image_failure_fails_the_build_and_keeps_last_sha(self):
        done = self.run_deploy(STUB_LAST='old', STUB_FAIL_IMAGE='1')
        self.assertEqual(done.returncode, 1)
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))
        build = self.build()
        self.assertEqual(build['status'], 'failed')
        self.assertEqual(build['failed'], ['image:ingress', 'image:service'])
        self.assertIn('docker build failed', build['tail'])
        self.assertIsNone(self.recorded('/tower/deploy/image/service'))

    def test_a_stack_failure_lists_it_and_leaves_last_sha_alone(self):
        done = self.run_deploy(STUB_LAST='old', STUB_FAIL_STACK='tower-app-port')
        self.assertEqual(done.returncode, 1)
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))
        build = self.build()
        self.assertEqual((build['status'], build['failed']), ('failed', ['tower-app-port']))
        self.assertIn('stays old', build['tail'])
        self.assertIn('start tower-app-network', build['tail'])  # the stacks after and before it still ran

    def test_a_last_sha_that_cannot_be_written_fails_the_build_and_says_so(self):
        done = self.run_deploy(STUB_LAST='old', STUB_FAIL_PUT='/tower/deploy/last-sha')
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.build()['failed'], ['record:last-sha'])

    def control_plane_repo(self, change=True):
        repo = self.tmp / 'repo'
        (repo / 'services/control-plane').mkdir(parents=True)
        (repo / 'services/control-plane/wrangler.toml').write_text('name = "forge-test"\n')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'plane')
        self.base = git(repo, 'rev-parse', 'HEAD')
        if not change:
            (repo / 'other.txt').write_text('y\n')
            git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
            git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'other')

    def plane_cmd(self, code=0):
        return f'echo "token_seen=${{CLOUDFLARE_API_TOKEN:+yes}} cwd=$(basename "$PWD")" >> "{self.state}/plane"; exit {code}'

    def test_a_changed_control_plane_is_deployed_with_the_token_and_never_prints_it(self):
        self.control_plane_repo()
        done = self.run_deploy(STUB_LAST='old', STUB_CF_TOKEN='cf-token-0123456789', CONTROL_PLANE_DEPLOY_CMD=self.plane_cmd())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.state / 'plane').read_text().strip(), 'token_seen=yes cwd=repo')
        self.assertNotIn('cf-token-0123456789', done.stdout + done.stderr + self.recorded('/tower/deploy/last-build'))
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), git(self.tmp / 'repo', 'rev-parse', 'HEAD'))

    def test_an_unchanged_control_plane_is_not_deployed(self):
        self.control_plane_repo(change=False)
        done = self.run_deploy(STUB_LAST=self.base, STUB_CF_TOKEN='cf-token-0123456789',
                               CONTROL_PLANE_DEPLOY_CMD=self.plane_cmd())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((self.state / 'plane').exists())
        self.assertIn('unchanged since', done.stdout)

    def test_no_token_skips_the_control_plane_and_does_not_fail_the_build(self):
        self.control_plane_repo()
        done = self.run_deploy(STUB_LAST='old', CONTROL_PLANE_DEPLOY_CMD=self.plane_cmd())
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse((self.state / 'plane').exists())
        self.assertIn('cloudflare-api-token is not readable: skipped', done.stdout)

    def test_a_failed_control_plane_deploy_keeps_last_sha_for_the_next_ring(self):
        self.control_plane_repo()
        done = self.run_deploy(STUB_LAST='old', STUB_CF_TOKEN='cf-token-0123456789', CONTROL_PLANE_DEPLOY_CMD=self.plane_cmd(1))
        self.assertEqual(done.returncode, 1)
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))
        self.assertEqual(self.build()['failed'], ['control-plane'])

    def test_nothing_new_succeeds_and_records_it(self):
        done = self.run_deploy(STUB_LAST=self.head)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(self.build()['status'], 'nothing_new')
        self.assertNotIn('docker build', (self.state / 'calls').read_text())
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))

    def test_secrets_never_reach_the_record_or_the_output_of_the_record(self):
        done = self.run_deploy(STUB_LAST='old', STUB_FAIL_STACK='tower-app-port')
        written = self.recorded('/tower/deploy/last-build')
        for secret in (TOKEN, 'abcdefghij' + 'klmnop12345', 'ecr-pass' + 'word-0123456789abcdef'):
            self.assertNotIn(secret, written)
        self.assertIn('[redacted]', written)
        self.assertNotIn('TOWER_DEPLOY_DOORBELL_TOKEN', json.dumps(list(self.build())))
        self.assertIn('Failed to create/update tower-app-port', self.build()['tail'])
        self.assertEqual(done.returncode, 1)

    def test_the_record_stays_under_three_kilobytes_whatever_the_output(self):
        (self.stubs / 'docker').write_text(DOCKER_STUB.replace('exit 0', 'for i in $(seq 1 400); do echo "line $i \\\\ \\"quoted\\" tab\there"; done; exit 0'))
        done = self.run_deploy(STUB_LAST='old')
        self.assertEqual(done.returncode, 0, done.stderr)
        raw = self.recorded('/tower/deploy/last-build')
        self.assertLessEqual(len(raw.encode()), 3000)
        self.assertEqual(json.loads(raw)['status'], 'succeeded')

    def test_independent_stacks_run_in_parallel_after_their_needs(self):
        self.five_stacks()
        done = self.run_deploy(STUB_LAST='old', STUB_SLEEP='tower-app-network:0.3,tower-app-data:0.3', DEPLOY_PARALLEL='3',
                               STUB_UNTIL='tower-app-service:tower-app-port,tower-app-port:tower-app-service')
        self.assertEqual(done.returncode, 0, done.stderr)
        e = self.events()
        self.assertLess(e[('end', 'network')], e[('start', 'data')])
        self.assertLess(e[('end', 'data')], e[('start', 'service')])
        self.assertLess(e[('end', 'data')], e[('start', 'port')])
        self.assertLess(e[('start', 'port')], e[('end', 'service')])  # port and service overlap
        self.assertLess(e[('start', 'service')], e[('end', 'port')])
        self.assertLess(e[('end', 'service')], e[('start', 'runner')])  # the runner needs the service's cluster
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), self.head)
        self.assertRegex(done.stdout, r'\d\d:\d\d:\d\d start tower-app-port')
        self.assertRegex(done.stdout, r'\d\d:\d\d:\d\d end   tower-app-runner ok in \d+s')

    def test_the_parallelism_is_bounded(self):
        self.five_stacks()
        done = self.run_deploy(STUB_LAST='old', STUB_SLEEP='tower-app-service:1,tower-app-port:1', DEPLOY_PARALLEL='1')
        self.assertEqual(done.returncode, 0, done.stderr)
        e = self.events()
        self.assertTrue(e[('end', 'service')] <= e[('start', 'port')] or e[('end', 'port')] <= e[('start', 'service')])

    def test_a_failed_stack_blocks_what_needs_it_and_not_the_rest(self):
        self.five_stacks()
        done = self.run_deploy(STUB_LAST='old', STUB_FAIL_STACK='tower-app-service')
        self.assertEqual(done.returncode, 1)
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))
        build = self.build()
        self.assertEqual((build['status'], build['failed']), ('failed', ['tower-app-service']))
        self.assertEqual(build['left'], ['tower-app-runner'])
        self.assertIn('tower-app-port', build['done'])
        self.assertNotIn('deploy --stack-name tower-app-runner', (self.state / 'calls').read_text())

    def test_per_stack_seconds_are_recorded_and_a_no_change_keeps_the_old_figure(self):
        self.five_stacks()
        before = json.dumps({'stacks': {'tower-app-runner': 480, 'tower-app-port': 180}})
        done = self.run_deploy(STUB_LAST='old', STUB_LAST_BUILD=before, STUB_SLEEP='tower-app-service:1',
                               STUB_NOCHANGE='tower-app-runner')
        self.assertEqual(done.returncode, 0, done.stderr)
        stacks = self.build()['stacks']
        self.assertGreaterEqual(stacks['tower-app-service'], 1)
        self.assertEqual(stacks['tower-app-runner'], 480)  # no change: seconds of the real deploy kept
        self.assertIn('tower-app-network', stacks)

    def test_the_deadline_guard_stops_before_a_stack_that_no_longer_fits(self):
        self.five_stacks()
        now = 1_700_000_000  # the clock is pinned (D-069 item 5): the guard reads DEPLOY_NOW, never the wall clock
        last = json.dumps({'stacks': {'tower-app-service': 300, 'tower-app-port': 190, 'tower-app-network': 5}})
        done = self.run_deploy(STUB_LAST='old', STUB_LAST_BUILD=last, DEPLOY_BUDGET_S='1080', DEPLOY_NOW=str(now),
                               CODEBUILD_START_TIME=str((now - 800) * 1000))  # 280 s remain
        self.assertEqual(done.returncode, 1)
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))
        build = self.build()
        self.assertEqual(build['status'], 'incomplete')
        self.assertEqual(build['done'], ['tower-app-network', 'tower-app-data', 'tower-app-port'])
        self.assertEqual(build['left'], ['tower-app-service', 'tower-app-runner'])
        self.assertEqual(build['failed'], [])
        self.assertIn('the next ring resumes', build['tail'])
        self.assertIn('tower-app-service', build['stacks'])  # the figures survive for the resume

    def test_no_stack_is_tagged_with_the_commit(self):
        # STACK-COMMIT-OFF-TAGS: a stack tag is copied to every resource that takes tags, and commit=<head> changed at every
        # apply: the port stack spent 122 of its 183 s on its two queues, one after the other, 18 s on its roles and 19 s
        # on the queue's mapping, for a change of one property elsewhere (the Torre's reading of the stack's events, 11/11)
        self.five_stacks()
        done = self.run_deploy(STUB_LAST='old')
        self.assertEqual(done.returncode, 0, done.stderr)
        deploys = [line for line in (self.state / 'calls').read_text().splitlines() if 'cloudformation deploy' in line]
        self.assertEqual(len(deploys), 5)
        for line in deploys:
            self.assertTrue(line.endswith('--tags project=tower'), line)
            self.assertNotIn('commit=', line)

    def test_a_resume_skips_the_stacks_whose_recorded_hash_is_the_head_s(self):
        # (the stack's commit tag said so before; the hash of what was applied, kept in last-build, says it without a tag)
        self.five_stacks()
        first = self.run_deploy(STUB_LAST='old')
        self.assertEqual(first.returncode, 0, first.stderr)
        hashes = self.build()['hashes']
        (self.state / 'calls').write_text('')
        (self.state / 'ssm_tower_deploy_last-sha').unlink()  # the build was incomplete: last-sha did not move
        kept = {name: hashes[name] for name in ('network', 'data')}  # and it had applied these two
        done = self.run_deploy(STUB_LAST='old', STUB_LAST_BUILD=json.dumps({'hashes': kept}),
                               STUB_TAGGED='tower-app-network tower-app-data', STUB_TAG_VALUE='')
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = (self.state / 'calls').read_text()
        self.assertNotIn('deploy --stack-name tower-app-network', calls)
        self.assertNotIn('deploy --stack-name tower-app-data', calls)
        self.assertIn('deploy --stack-name tower-app-runner', calls)
        self.assertIn('skip  tower-app-data: template and images unchanged', done.stdout)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), self.head)
        self.assertIn('tower-app-data', self.build()['done'])

    def test_a_stack_whose_tag_names_the_head_but_whose_hash_is_not_recorded_is_deployed(self):
        # a tag an older deployer left says nothing any more: only the recorded hash skips a stack
        self.five_stacks()
        self.run_deploy(STUB_LAST='old', STUB_TAGGED='tower-app-network', STUB_TAG_VALUE=self.head)
        self.assertIn('deploy --stack-name tower-app-network', (self.state / 'calls').read_text())

    def commit(self, message, **files):
        repo = self.tmp / 'repo'
        for path, text in files.items():
            rel = path.replace('__', '/')
            rel = rel[:-3] + '.py' if rel.endswith('_py') else rel
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text)
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', message)
        return git(repo, 'rev-parse', 'HEAD')

    # PORT7-ACKPATH-EXPLICIT: AckPath is always passed to the port stack, from one place, and a red smoke sticks.
    SMOKE = 'echo ran >> "$STUB_DIR/smoke"; exit ${SMOKE_EXIT:-0}'

    def port_calls(self):
        return [c for c in (self.state / 'calls').read_text().splitlines()
                if 'cloudformation deploy' in c and 'tower-app-port' in c]

    def smoke_runs(self):
        path = self.state / 'smoke'
        return path.read_text().count('ran') if path.exists() else 0

    def test_the_port_stack_gets_the_lambda_keys_as_overrides_and_nothing_goes_to_ssm(self):
        # LAMBDA-PACKAGE-FIX: the deployer role may not PutParameter under /tower/deploy/lambda/
        self.run_deploy(STUB_LAST='old')
        call = self.port_calls()[0]
        for pair in ('PortCode=artifacts/lambda/tower-port-api/aa.zip', 'IngressCode=artifacts/lambda/tower-port-ack-ingress/bb.zip',
                     'WebhookCode=artifacts/lambda/tower-port-webhook-consumer/cc.zip', 'DepsKey=artifacts/lambda/deps/dd.zip'):
            self.assertIn(pair, call)
        self.assertNotIn('/tower/deploy/lambda/', (self.state / 'calls').read_text())

    def test_the_port_stack_always_gets_an_explicit_ackpath_default_lambda(self):
        (self.tmp / 'repo/infra/aws/parameters.json').unlink(missing_ok=True)
        done = self.run_deploy(STUB_LAST='old', DEPLOY_ACK_SMOKE_CMD=self.SMOKE)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(len(self.port_calls()), 1)
        self.assertIn('--parameter-overrides AckPath=lambda', self.port_calls()[0])
        for call in (self.state / 'calls').read_text().splitlines():  # only the port stack takes the parameter
            if 'cloudformation deploy' in call and 'tower-app-port' not in call:
                self.assertNotIn('AckPath', call)
        self.assertEqual(self.smoke_runs(), 0)  # ACK-CANARY-RETIRE: on lambda there is nothing to prove and no canary to run it on
        self.assertIn('ack-smoke: production AckPath=lambda: nothing to prove, not run', done.stdout)
        build = self.build()
        self.assertEqual(build['ack'], {'path': 'lambda', 'source': 'default'})
        self.assertNotIn('ack_failed', build)

    def test_the_file_sets_the_value_and_the_smoke_runs_only_on_the_path_it_proves(self):
        repo = self.tmp / 'repo'
        for value, runs in (('lambda', 0), ('sqs', 1)):  # ACK-CANARY-RETIRE: the smoke is production's, on sqs; no canary
            (repo / 'infra/aws/parameters.json').write_text('{"port": {"AckPath": "%s"}}\n' % value)
            (self.state / 'calls').unlink(missing_ok=True)
            (self.state / 'smoke').unlink(missing_ok=True)
            done = self.run_deploy(STUB_LAST='old', DEPLOY_ACK_SMOKE_CMD=self.SMOKE)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn(f'--parameter-overrides AckPath={value}', self.port_calls()[0])
            self.assertEqual(self.smoke_runs(), runs)
            self.assertNotIn('canary', ' '.join(line for line in done.stdout.splitlines() if line.startswith('ack-smoke')))
            self.assertEqual(self.build()['ack'], {'path': value, 'source': 'file'})

    def test_ssm_wins_over_the_file_and_an_invalid_value_is_ignored(self):
        repo = self.tmp / 'repo'
        (repo / 'infra/aws/parameters.json').write_text('{"port": {"AckPath": "sqs"}}\n')
        self.run_deploy(STUB_LAST='old', STUB_ACK_PATH='lambda', DEPLOY_ACK_SMOKE_CMD=self.SMOKE)
        self.assertIn('--parameter-overrides AckPath=lambda', self.port_calls()[0])
        self.assertEqual(self.build()['ack'], {'path': 'lambda', 'source': 'ssm'})
        (self.state / 'calls').unlink()
        done = self.run_deploy(STUB_LAST='old', STUB_ACK_PATH='bogus', DEPLOY_ACK_SMOKE_CMD=self.SMOKE)
        self.assertIn('ignoring invalid', done.stdout)
        self.assertIn('--parameter-overrides AckPath=sqs', self.port_calls()[0])
        self.assertEqual(self.build()['ack'], {'path': 'sqs', 'source': 'file'})

    def test_the_data_stack_is_deployed_with_the_class_the_file_names(self):
        # DB-MEDIUM (Daniel 13/11 14:39 BRT): a stack keeps a parameter's previous value when it is not given, so the class
        # reaches the database only as an override, from infra/aws/parameters.json's data object
        self.five_stacks()
        repo = self.tmp / 'repo'
        (repo / 'infra/aws/parameters.json').write_text('{"port": {"AckPath": "sqs"}, "data": {"InstanceClass": "db.t4g.medium"}}\n')
        done = self.run_deploy(STUB_LAST='old', DEPLOY_ACK_SMOKE_CMD=self.SMOKE)
        self.assertEqual(done.returncode, 0, done.stderr)
        data = [c for c in (self.state / 'calls').read_text().splitlines() if 'cloudformation deploy' in c and 'tower-app-data' in c]
        self.assertTrue(data, done.stdout[-2000:])
        self.assertIn('--parameter-overrides InstanceClass=db.t4g.medium', data[0])
        self.assertEqual(json.loads((ROOT / 'infra/aws/parameters.json').read_text())['data'], {'InstanceClass': 'db.t4g.medium'})

    def test_a_stacks_values_in_the_file_go_beside_its_own_overrides(self):
        # SERVICE-MEMORY: the service's memory from infra/aws/parameters.json, beside LiveCode and LiveSeen
        self.five_stacks()
        repo = self.tmp / 'repo'
        (repo / 'infra/aws/parameters.json').write_text('{"port": {"AckPath": "sqs"}, "service": {"Memory": "1024"}}\n')
        done = self.run_deploy(STUB_LAST='old', DEPLOY_ACK_SMOKE_CMD=self.SMOKE)
        self.assertEqual(done.returncode, 0, done.stderr)
        service = [c for c in (self.state / 'calls').read_text().splitlines() if 'cloudformation deploy' in c and 'tower-app-service' in c]
        self.assertTrue(service, done.stdout[-2000:])
        self.assertRegex(service[0], r'--parameter-overrides LiveCode=\S* LiveSeen=\S+ Memory=1024')
        port = [c for c in (self.state / 'calls').read_text().splitlines() if 'cloudformation deploy' in c and 'tower-app-port' in c]
        self.assertNotIn('Memory=', port[0])

    def test_the_runner_stack_is_applied_with_no_runner(self):
        """RUNNER-OFF (the migration to GitHub, 14/11): the gate left AWS. A stack keeps a parameter's previous value when it
        is not given, and the runner stack's default was 1: the first deploy from GitHub brought tower-runner back to 1/1
        (8 GiB) after the Torre had set it to 0. infra/aws/parameters.json passes DesiredCount=0 on every apply."""
        self.assertEqual(json.loads((ROOT / 'infra/aws/parameters.json').read_text())['runner'], {'DesiredCount': '0'})
        runner = json.loads((ROOT / 'infra/aws/stacks/50-runner.json').read_text())
        self.assertEqual(runner['Parameters']['DesiredCount']['Default'], 0)
        self.five_stacks()
        repo = self.tmp / 'repo'
        (repo / 'infra/aws/parameters.json').write_text((ROOT / 'infra/aws/parameters.json').read_text())
        done = self.run_deploy(STUB_LAST='old', DEPLOY_ACK_SMOKE_CMD=self.SMOKE)
        self.assertEqual(done.returncode, 0, done.stderr)
        calls = [c for c in (self.state / 'calls').read_text().splitlines() if 'cloudformation deploy' in c and 'tower-app-runner' in c]
        self.assertTrue(calls, done.stdout[-2000:])
        self.assertIn('DesiredCount=0', calls[0])

    def test_the_repo_parameters_make_production_sqs_and_the_template_default_stays_the_fallback(self):
        self.assertEqual(json.loads((ROOT / 'infra/aws/parameters.json').read_text())['port']['AckPath'], 'sqs')  # PORT7-PROD
        port = json.loads((ROOT / 'infra/aws/stacks/40-port.json').read_text())
        self.assertEqual(port['Parameters']['AckPath']['Default'], 'lambda')

    def test_a_red_production_smoke_sticks_lambda_without_failing_or_bisecting_and_a_green_clears_it(self):
        repo = self.tmp / 'repo'
        (repo / 'infra/aws/parameters.json').write_text('{"port": {"AckPath": "sqs"}}\n')
        done = self.run_deploy(STUB_LAST='old', DEPLOY_ACK_SMOKE_CMD=self.SMOKE, SMOKE_EXIT='1')
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn('running against PRODUCTION', done.stdout)
        build = self.build()
        self.assertEqual((build['status'], build['failed'], build['bisect'], build['rolled_back']), ('succeeded', [], None, []))
        self.assertEqual(build['ack_failed'], {'sha': self.head})  # persisted in last-build like #389
        self.assertNotIn('port', build['hashes'])  # the rolled back port stack is redeployed next time
        (self.state / 'calls').unlink()
        last = json.dumps(build)
        done = self.run_deploy(STUB_LAST='old', STUB_LAST_BUILD=last, DEPLOY_ACK_SMOKE_CMD=self.SMOKE)
        self.assertIn('sqs REFUSED', done.stdout)
        self.assertIn('--parameter-overrides AckPath=lambda', self.port_calls()[0])
        self.assertEqual(self.build()['ack'], {'path': 'lambda', 'source': 'guard'})
        self.assertEqual(self.build()['ack_failed'], {'sha': self.head})  # carried over until an ACK file changes
        (repo / 'scripts/lib').mkdir(parents=True, exist_ok=True)  # a change to an ACK file lifts the guard; a green smoke clears it
        (repo / 'infra/service/tower_infra').mkdir(parents=True, exist_ok=True)
        (repo / 'infra/service/tower_infra/webhook_consumer.py').write_text('# changed\n')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'ack file')
        (self.state / 'calls').unlink()
        self.run_deploy(STUB_LAST='old', STUB_LAST_BUILD=last, DEPLOY_ACK_SMOKE_CMD=self.SMOKE)
        self.assertIn('--parameter-overrides AckPath=sqs', self.port_calls()[0])
        self.assertNotIn('ack_failed', self.build())

    def sqs(self):
        """ACK-CANARY-RETIRE: the smoke runs only where there is something to prove, production on sqs."""
        (self.tmp / 'repo/infra/aws/parameters.json').write_text('{"port": {"AckPath": "sqs"}}\n')

    def test_an_ack_smoke_with_no_verdict_never_fails_marks_or_bisects_the_build(self):
        self.sqs()
        for rc in ('2', '7'):  # 1 is a red: the smoke rolled production back to lambda (the tests above)
            (self.state / 'calls').unlink(missing_ok=True)
            done = self.run_deploy(STUB_LAST='old', DEPLOY_ACK_SMOKE_CMD=self.SMOKE, SMOKE_EXIT=rc)
            self.assertEqual(done.returncode, 0, done.stdout)
            self.assertEqual(self.recorded('/tower/deploy/last-sha'), self.head)  # the deploy advanced
            build = self.build()
            self.assertEqual((build['status'], build['failed'], build['bisect'], build['rolled_back']), ('succeeded', [], None, []))
            self.assertNotIn('ack_failed', build)
            self.assertEqual(build['ack_smoke']['exit'], int(rc))
            self.assertIn('port', build['hashes'])  # no forced redeploy of the port stack
            self.assertEqual(len(self.port_calls()), 1)  # and no rollback deploy

    def test_the_smoke_result_and_the_tail_of_a_red_are_recorded(self):
        smoke = ('echo "line one"; echo \'{"ok":false,"http_status":400,"ms":25,"body":"x","headers":{"x-amzn-errortype":"BadRequestException"},"drop":"skipped","reason":"r"}\'; '
                 'exit ${SMOKE_EXIT:-0}')
        self.sqs()
        done = self.run_deploy(STUB_LAST='old', DEPLOY_ACK_SMOKE_CMD=smoke, SMOKE_EXIT='1')
        build = self.build()
        self.assertEqual((build['ack_smoke']['http_status'], build['ack_smoke']['exit']), (400, 1))
        self.assertEqual(build['ack_smoke']['headers']['x-amzn-errortype'], 'BadRequestException')
        self.assertIn('line one', build['ack_smoke']['fail_tail'])
        self.assertIn('ack-smoke: running', done.stdout)
        green = self.run_deploy(STUB_LAST='old', DEPLOY_ACK_SMOKE_CMD='echo \'{"ok":true,"http_status":202,"ms":40}\'')
        self.assertEqual(green.returncode, 0)
        self.assertNotIn('fail_tail', self.build()['ack_smoke'])

    def test_a_change_to_an_ack_file_alone_runs_the_smoke_and_an_unrelated_one_does_not(self):
        self.five_stacks()
        self.sqs()
        repo = self.tmp / 'repo'
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'production on sqs')
        base = git(repo, 'rev-parse', 'HEAD')
        (repo / 'scripts/lib').mkdir(parents=True)
        (repo / 'README').write_text('x\n')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'unrelated')
        self.run_deploy(STUB_LAST=base, STUB_TAGGED='tower-app-port', STUB_TAG_VALUE=git(repo, 'rev-parse', 'HEAD'),
                        DEPLOY_ACK_SMOKE_CMD=self.SMOKE, DEPLOY_TARGETS='none')
        self.assertEqual(self.smoke_runs(), 0)
        (repo / 'scripts/lib/ack_smoke.py').write_text('y\n')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'ack file')
        self.run_deploy(STUB_LAST=base, STUB_TAGGED='tower-app-port', STUB_TAG_VALUE=git(repo, 'rev-parse', 'HEAD'),
                        DEPLOY_ACK_SMOKE_CMD=self.SMOKE, DEPLOY_TARGETS='none')
        self.assertEqual(self.smoke_runs(), 1)

    # IMAGE-PREWARM-C: the service and runner stacks get LiveCode, the bundle a landing swapped to, while it is the head's code
    def stack_calls(self, stack):
        return [c for c in (self.state / 'calls').read_text().splitlines()
                if 'cloudformation deploy' in c and f'--stack-name tower-app-{stack} ' in c]

    def test_the_service_and_runner_stacks_get_the_swapped_bundle_while_it_is_the_heads_code(self):
        self.five_stacks()
        repo, digest = self.tmp / 'repo', 'd' * 64
        swapped = self.head  # the merge the landing promoted
        seen = f'{digest}@{swapped}'  # SLOW-PATH-NO-ROLLOUT-WAIT: deploy.live_code as the status has it: the stacks' LiveSeen
        (self.state / 'status.json').write_text(json.dumps({'live_code': seen, 'image_swap': [
            {'head': 'e' * 40, 'swapped': False, 'why': 'x'}, {'head': swapped, 'digest': digest, 'swapped': True}]}))
        (repo / 'docs').mkdir()
        (repo / 'docs/x.md').write_text('a docs landing on top\n')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'docs')
        status = {'DEPLOY_FAST_STATUS_CMD': f'cat {self.state}/status.json', 'DEPLOY_TARGETS': 'service,runner'}
        done = self.run_deploy(STUB_LAST='old', **status)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn('live code: LiveCode=dddddddddddd', done.stdout)
        for stack in ('service', 'runner'):
            self.assertIn(f'--parameter-overrides LiveCode={digest} LiveSeen={seen} --tags', self.stack_calls(stack)[0])
        self.assertNotIn('LiveCode', ' '.join(self.port_calls()))  # only the two stacks take it
        hashes = self.build()['hashes']
        (self.state / 'calls').unlink()
        complete = {'STUB_TAGGED': 'tower-app-service tower-app-runner', 'STUB_TAG_VALUE': 'f' * 40}
        self.run_deploy(STUB_LAST='old', STUB_LAST_BUILD=json.dumps({'hashes': hashes}), **complete, **status)
        self.assertEqual(self.stack_calls('service'), [])  # the same LiveCode: unchanged, skipped
        (repo / 'infra/service/tower_infra').mkdir(parents=True)
        (repo / 'infra/service/tower_infra/x.py').write_text('new code\n')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'code')
        done = self.run_deploy(STUB_LAST='old', STUB_LAST_BUILD=json.dumps({'hashes': hashes}), **complete, **status)
        self.assertIn('is not the code of this head', done.stdout)
        for stack in ('service', 'runner'):  # the image's own code; a LiveCode that changed is redeployed
            self.assertIn(f'--parameter-overrides LiveCode= LiveSeen={seen} --tags', self.stack_calls(stack)[0])
        (self.state / 'calls').unlink()
        done = self.run_deploy(STUB_LAST='old', DEPLOY_FAST_STATUS_CMD='exit 1', DEPLOY_TARGETS='service,runner')
        self.assertIn('live code: none', done.stdout)
        self.assertIn('--parameter-overrides LiveCode= LiveSeen=unknown --tags', self.stack_calls('runner')[0])  # unreadable
        (self.state / 'calls').unlink()  # a status that does not carry the datum (an older port): unknown too; none yet: empty
        for said, want in (({'image_swap': []}, 'unknown'), ({'image_swap': [], 'live_code': ''}, ''), ({'live_code': 'bogus'}, 'unknown')):
            (self.state / 'status.json').write_text(json.dumps(said))
            self.run_deploy(STUB_LAST='old', DEPLOY_TARGETS='runner', DEPLOY_FAST_STATUS_CMD=f'cat {self.state}/status.json')
            self.assertIn(f'--parameter-overrides LiveCode= LiveSeen={want} --tags', self.stack_calls('runner')[-1])

    def test_the_task_definitions_carry_the_datum_their_deploy_saw_and_it_is_not_in_the_stacks_hash(self):
        for path, container in (('30-service.json', 'service'), ('50-runner.json', 'runner')):
            template = json.loads((ROOT / 'infra/aws/stacks' / path).read_text())
            self.assertEqual(template['Parameters']['LiveSeen']['Default'], '')
            found = next(c for c in template['Resources']['TaskDefinition']['Properties']['ContainerDefinitions'] if c['Name'] == container)
            self.assertIn({'Name': 'TOWER_CODE_SEEN', 'Value': {'Ref': 'LiveSeen'}}, found['Environment'])
        # (the standby's definition is the service's without its init container, so it carries the stamp too; a prewarm
        # standby never follows the datum: its RunTask sets TOWER_STANDBY, test_infra_code_bundle.LiveCode)
        text = (ROOT / 'infra/aws/deploy.sh').read_text()
        hashed = text[text.index('stack_hash() {'):text.index('# DEP7-PORT-FAST-OWNED: port_fast_owned')]
        self.assertNotIn('liveseen', hashed)  # a landing changes the datum: it must not dirty the two stacks


class SlowPathShTests(DeployShTests):
    """DEP7: selective targets, hash skip, smoke with rollback, bisection, cycle measures. Same rig as DeployShTests."""

    def commit(self, message, **files):
        repo = self.tmp / 'repo'
        for path, text in files.items():
            (repo / path.replace('__', '/')).parent.mkdir(parents=True, exist_ok=True)
            (repo / path.replace('__', '/')).write_text(text)
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'add', '.')
        git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', message)
        return git(repo, 'rev-parse', 'HEAD')

    def run_deploy(self, **extra):
        branch = getattr(self, 'branch', None)  # a real build starts from a fresh clone: undo the last bisection checkout
        if branch:
            git(self.tmp / 'repo', 'checkout', '-q', branch)
        return super().run_deploy(**extra)

    def with_classifier(self):
        self.branch = git(self.tmp / 'repo', 'rev-parse', '--abbrev-ref', 'HEAD')
        self.five_stacks()
        (self.tmp / 'repo/scripts/lib').mkdir(parents=True)
        shutil.copy(ROOT / 'scripts/lib/deploy_classify.py', self.tmp / 'repo/scripts/lib/deploy_classify.py')
        self.base = self.commit('classifier')
        (self.state / 'param_tower_deploy_last-sha').write_text(self.base)  # the deployed sha, for the stub's get-parameter

    def stacks_deployed(self):
        calls = (self.state / 'calls').read_text()
        return sorted(set(re.findall(r'--stack-name tower-app-(\w+)', ' '.join(
            line for line in calls.splitlines() if 'cloudformation deploy' in line))))

    def test_a_port_only_change_deploys_port_and_no_image(self):
        self.with_classifier()
        self.commit('port stack', **{'infra__aws__stacks__40-port.json': 'changed\n'})
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='none')
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertEqual(self.stacks_deployed(), ['port'])
        self.assertNotIn('docker build', (self.state / 'calls').read_text())
        build = self.build()
        self.assertEqual((build['status'], build['targets'], build['batch']), ('succeeded', ['port'], 1))
        self.assertIn('not a target of this batch', build['tail'] + done.stdout)

    def test_a_network_change_deploys_every_stack_that_needs_it(self):
        self.with_classifier()
        self.commit('network', **{'infra__aws__stacks__10-network.json': 'changed\n'})
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='none')
        self.assertEqual(self.stacks_deployed(), ['data', 'network', 'port', 'runner', 'service'])

    def test_an_image_change_builds_the_image_and_redeploys_the_stacks_that_read_it(self):
        self.with_classifier()
        self.commit('image', infra__service__Dockerfile='y\n')
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='none')
        self.assertEqual(self.stacks_deployed(), ['port', 'runner', 'service'])
        self.assertIn('docker build', (self.state / 'calls').read_text())
        self.assertIn('--cache-from', (self.state / 'calls').read_text())

    def test_a_batch_with_no_slow_target_deploys_nothing_and_still_advances_last_sha(self):
        self.with_classifier()
        head = self.commit('docs', docs__a_md='x\n')
        done = self.run_deploy(STUB_LAST=self.base)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertEqual(self.stacks_deployed(), [])
        self.assertNotIn('docker build', (self.state / 'calls').read_text())
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), head)
        self.assertEqual(self.build()['targets'], [])

    def test_a_dirty_stack_is_redeployed_whatever_the_diff_and_last_sha_waits_for_it(self):
        # live 09/11: the canary's apply failed, the fix was a docs-only diff for the classifier, last-sha moved, nothing re-applied
        self.with_classifier()
        (self.state / 'param_tower_deploy_last-sha').unlink()
        for image in ('service', 'ingress', 'runner'):  # the same images in both builds, whatever the stub answers
            (self.state / f'param_tower_deploy_image_{image}').write_text(f'registry.test/tower-{image}:fixed')
        for package in ('tower-port-api', 'tower-port-ack-ingress', 'tower-port-webhook-consumer', 'deps'):  # DEP8: the packages too
            (self.state / f'param_tower_deploy_lambda_{package}').write_text(f's3://fixed/{package}')
        first = self.run_deploy(STUB_LAST='old', DEPLOY_TARGETS='all', DEPLOY_SMOKE_CMD='none')
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        hashes = self.build()['hashes']
        self.assertEqual(self.build()['dirty'], [])
        head = self.commit('docs only', docs__a_md='x\n')
        (self.state / 'calls').write_text('')
        stale = {k: v for k, v in hashes.items() if k != 'port'}  # port's last apply failed: no hash recorded
        done = self.run_deploy(STUB_LAST=self.base, STUB_LAST_BUILD=json.dumps({'hashes': stale, 'status': 'failed'}),
                               DEPLOY_SMOKE_CMD='none')
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertEqual(self.stacks_deployed(), ['port'])  # a docs-only batch, yet the dirty stack is applied
        self.assertIn('dirty: tower-app-port', done.stdout)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), head)
        self.assertEqual(self.build()['dirty'], [])

    def test_last_sha_at_the_head_with_a_failed_last_build_still_applies_the_dirty_stack(self):
        self.with_classifier()
        (self.state / 'param_tower_deploy_last-sha').unlink()
        for image in ('service', 'ingress', 'runner'):  # the same images in both builds, whatever the stub answers
            (self.state / f'param_tower_deploy_image_{image}').write_text(f'registry.test/tower-{image}:fixed')
        for package in ('tower-port-api', 'tower-port-ack-ingress', 'tower-port-webhook-consumer', 'deps'):  # DEP8: the packages too
            (self.state / f'param_tower_deploy_lambda_{package}').write_text(f's3://fixed/{package}')
        self.run_deploy(STUB_LAST='old', DEPLOY_TARGETS='all', DEPLOY_SMOKE_CMD='none')
        hashes = self.build()['hashes']
        (self.state / 'calls').write_text('')
        stale = {k: v for k, v in hashes.items() if k != 'port'}
        done = self.run_deploy(STUB_LAST=self.base, STUB_LAST_BUILD=json.dumps({'hashes': stale, 'status': 'failed'}),
                               DEPLOY_SMOKE_CMD='none')
        self.assertNotIn('nothing new', done.stdout)
        self.assertEqual(self.stacks_deployed(), ['port'])

    def test_a_stack_already_applied_with_the_same_template_and_images_is_skipped(self):
        self.five_stacks()
        first = self.run_deploy(STUB_LAST='old', DEPLOY_SMOKE_CMD='none')
        hashes = self.build()['hashes']
        self.assertEqual(sorted(hashes), ['data', 'network', 'port', 'runner', 'service'])
        # the second build: the same tree under a new sha-less deploy (DEPLOY_TARGETS=all), stacks COMPLETE with those hashes
        again = self.run_deploy(STUB_LAST='old', STUB_LAST_BUILD=json.dumps({'hashes': hashes}),
                                STUB_TAGGED='tower-app-network tower-app-data tower-app-service tower-app-port tower-app-runner',
                                STUB_TAG_VALUE='older', DEPLOY_SMOKE_CMD='none')
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn('template and images unchanged', again.stdout)

    # --- ACK-CANARY-GONE: a head that takes a stack's template and its line of the order away -------------------------------
    def test_a_stack_whose_template_left_the_tree_is_not_applied_not_dirty_and_leaves_the_record(self):
        # the canary's stack (12/11): emptied by an update, deleted by the account's owner, then its file and its line of
        # order.json left in one commit. The record of the build before still carries its hash; nothing may wait for it
        self.with_classifier()
        order = json.loads((self.tmp / 'repo/infra/aws/order.json').read_text())
        self.base = self.commit('a sixth stack', **{'infra__aws__stacks__45-ack-canary.json': 'x\n',
                                                    'infra__aws__order.json': json.dumps({**order, 'ack-canary': []})})
        first = self.run_deploy(STUB_LAST='old', DEPLOY_TARGETS='all', DEPLOY_SMOKE_CMD='none')
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        hashes = self.build()['hashes']
        self.assertIn('ack-canary', hashes)
        self.assertIn('tower-app-ack-canary', self.build()['stacks'])
        record = json.dumps({'hashes': hashes, 'stacks': self.build()['stacks']})
        (self.state / 'param_tower_deploy_last-sha').write_text(self.base)
        git(self.tmp / 'repo', 'rm', '-q', 'infra/aws/stacks/45-ack-canary.json')
        head = self.commit('the stack is gone', **{'infra__aws__order.json': json.dumps(order)})
        (self.state / 'calls').write_text('')
        done = self.run_deploy(STUB_LAST=self.base, STUB_LAST_BUILD=record, DEPLOY_SMOKE_CMD='none')
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertNotIn('tower-app-ack-canary', (self.state / 'calls').read_text())  # not applied, not described, not deleted
        self.assertNotIn('ack-canary', done.stdout.replace('45-ack-canary.json', ''))
        build = self.build()
        self.assertEqual((build['status'], build['dirty'], build['failed']), ('succeeded', [], []))
        self.assertEqual(sorted(build['hashes']), ['data', 'network', 'port', 'runner', 'service'])  # its hash left the record
        self.assertEqual([name for name in build['stacks'] if 'canary' in name], [])  # and its seconds
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), head)

    # --- DEP7-CRITICAL-PATH: a new image dirties only the stacks that read it; service and runner roll out side by side ------
    def image_stacks(self):
        """service and runner name the image they read, as the real templates do; last-sha is that commit, the images fixed."""
        self.with_classifier()
        image = '{"Parameters": {"Image": {"Default": "/tower/deploy/image/service"}}}\n'
        self.base = self.commit('the image stacks', **{'infra__aws__stacks__30-service.json': image,
                                                       'infra__aws__stacks__50-runner.json': image})
        (self.state / 'param_tower_deploy_last-sha').write_text(self.base)
        for name in ('service', 'ingress'):
            (self.state / f'param_tower_deploy_image_{name}').write_text(f'registry.test/tower-{name}:one')

    def test_a_new_service_image_redeploys_only_the_stacks_that_read_it_and_dirties_nothing_else(self):
        self.image_stacks()
        (self.state / 'param_tower_deploy_last-sha').unlink()  # the first build applies every stack and records its hash
        first = self.run_deploy(STUB_LAST='old', DEPLOY_TARGETS='all', DEPLOY_SMOKE_CMD='none')
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        hashes = self.build()['hashes']
        self.assertEqual(sorted(hashes), ['data', 'network', 'port', 'runner', 'service'])
        (self.state / 'param_tower_deploy_last-sha').write_text(self.base)
        self.commit('image', infra__service__Dockerfile='y\n')
        (self.state / 'param_tower_deploy_image_service').write_text('registry.test/tower-service:two')  # the push
        (self.state / 'calls').write_text('')
        done = self.run_deploy(STUB_LAST=self.base, STUB_LAST_BUILD=json.dumps({'hashes': hashes}), DEPLOY_SMOKE_CMD='none')
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertEqual(self.stacks_deployed(), ['port', 'runner', 'service'])  # network and data: not a target, not dirty
        self.assertNotIn('dirty: tower-app-network', done.stdout)
        self.assertNotIn('dirty: tower-app-data', done.stdout)
        self.assertEqual(self.build()['dirty'], [])
        after = self.build()['hashes']
        self.assertEqual((after['network'], after['data']), (hashes['network'], hashes['data']))
        self.assertNotEqual(after['service'], hashes['service'])  # the image is in the hash of the stacks that read it

    def test_service_and_runner_overlap_when_the_service_exists_and_its_template_and_the_schema_are_unchanged(self):
        self.image_stacks()
        self.commit('image', infra__service__Dockerfile='y\n')
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='none', STUB_UNTIL=SIDE_BY_SIDE,
                               STUB_TAGGED='tower-app-service tower-app-port tower-app-runner', STUB_TAG_VALUE='older')
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        e = self.events()
        self.assertLess(e[('start', 'runner')], e[('end', 'service')])
        self.assertLess(e[('start', 'service')], e[('end', 'runner')])
        self.assertIn('order: tower-app-service exists', done.stdout)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), git(self.tmp / 'repo', 'rev-parse', 'HEAD'))

    def test_two_stacks_side_by_side_overlap_however_slow_the_runner_of_the_test_is(self):
        # the gate's red of #592 (12/11): these tests gave each apply a 1 s sleep and asked the scheduler to start the
        # other stack inside it; on a runner task just rolled out (the suite at 563 s) it started 15 ms after. Here every
        # read of a stack takes 0.7 s (more than a second between the two starts) and the overlap still holds: an apply
        # ends when the other's has started (STUB_UNTIL), so what is judged is the order of events, not a speed
        self.image_stacks()
        self.commit('image', infra__service__Dockerfile='y\n')
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='none', STUB_UNTIL=SIDE_BY_SIDE, STUB_SLOW_READS='0.7',
                               STUB_TAGGED='tower-app-service tower-app-port tower-app-runner', STUB_TAG_VALUE='older')
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        e = self.events()
        self.assertGreater(abs(e[('start', 'runner')] - e[('start', 'service')]), 0.6)  # a slow scheduler between the two
        self.assertLess(e[('start', 'runner')], e[('end', 'service')])
        self.assertLess(e[('start', 'service')], e[('end', 'runner')])

    def test_a_service_template_that_exports_the_same_does_not_hold_the_runner(self):
        # SLOW-PATH-NO-ROLLOUT-WAIT: a task definition or IAM change in 30-service.json adds no export the runner could need
        self.image_stacks()
        self.commit('task definition', **{'infra__aws__stacks__30-service.json':
                                          '{"Parameters": {"Image": {"Default": "/tower/deploy/image/service"}}, "v": 2}\n'})
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='none', STUB_UNTIL=SIDE_BY_SIDE,
                               STUB_TAGGED='tower-app-service tower-app-port tower-app-runner', STUB_TAG_VALUE='older',
                               DEPLOY_TARGETS='service,runner')
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        e = self.events()
        self.assertLess(e[('start', 'runner')], e[('end', 'service')])
        self.assertIn('order: tower-app-service exists (UPDATE_COMPLETE), its exports are unchanged since', done.stdout)

    def test_the_runner_still_waits_for_the_service_on_a_migration_a_new_export_or_a_new_service(self):
        for label, files, tagged in (
                ('migration', {'infra__db__0002.sql': 'alter\n'}, 'tower-app-service tower-app-port tower-app-runner'),
                ('export', {'infra__aws__stacks__30-service.json': '{"Image": "/tower/deploy/image/service", "Outputs": {"New": {}}}\n',
                            'infra__service__Dockerfile': 'y\n'}, 'tower-app-service tower-app-port tower-app-runner'),
                ('not json', {'infra__aws__stacks__30-service.json': 'x /tower/deploy/image/service\n',
                              'infra__service__Dockerfile': 'y\n'}, 'tower-app-service tower-app-port tower-app-runner'),
                ('no stack yet', {'infra__service__Dockerfile': 'y\n'}, 'tower-app-port tower-app-runner')):
            with self.subTest(label):
                self.setUp()
                self.image_stacks()
                self.commit(label, **files)
                done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='none', STUB_SLEEP='tower-app-service:0.5',
                                       STUB_TAGGED=tagged, STUB_TAG_VALUE='older')
                self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
                e = self.events()
                self.assertLess(e[('end', 'service')], e[('start', 'runner')])
                self.assertNotIn('order: tower-app-service exists', done.stdout)

    # --- SLOW-PATH-NO-ROLLOUT-WAIT: the live service applies the head's migrations, so the runner does not wait for the service
    BUNDLE = {'key': f'artifacts/lambda/tower-code/{"c" * 64}.zip', 'sha256': 'c' * 64, 'bytes': 1, 'uploaded': True}

    def migration(self, sql='alter table work.job add column more int;\n', applied='0002_more', **extra):
        """A head whose batch adds migration 0002_more, deployed over stacks that exist; the port answers `applied` as the
        newest migration of the database."""
        self.image_stacks()
        self.commit('migration', **{'infra__db__migrations__0001_base.sql': 'create schema work;\n',
                                    'infra__db__migrations__0002_more.sql': sql})
        return self.run_deploy(**{
            'STUB_LAST': self.base, 'DEPLOY_SMOKE_CMD': 'none', 'STUB_SLEEP': 'tower-app-service:1,tower-app-runner:1',
            'STUB_TAGGED': 'tower-app-service tower-app-port tower-app-runner', 'STUB_TAG_VALUE': 'older',
            'DEPLOY_CODE_BUNDLE_CMD': "echo publishing; echo '" + json.dumps(self.BUNDLE) + "'",
            'DEPLOY_MIGRATED_CMD': f'echo {applied}', 'DEPLOY_MIGRATE_WAIT_S': '1', 'DEPLOY_MIGRATE_POLL_S': '0.2', **extra})

    def test_a_migration_is_asked_of_the_live_service_before_the_stacks_and_the_runner_does_not_wait_for_the_service(self):
        done = self.migration(STUB_SLEEP='', STUB_UNTIL=SIDE_BY_SIDE)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        e = self.events()
        self.assertLess(e[('start', 'runner')], e[('end', 'service')])  # side by side: on 10/11 the runner started 312 s later
        self.assertLess(e[('start', 'service')], e[('end', 'runner')])
        self.assertIn('migrate: the live service applied the migrations (the database is at 0002_more)', done.stdout)
        ask = {'key': self.BUNDLE['key'], 'sha256': 'c' * 64, 'want': '0002_more'}
        self.assertEqual(self.build()['migrate'], ask)
        asked = [each for each in self.history() if each.get('migrate')]
        self.assertEqual((asked[0]['status'], asked[0]['migrate']), ('in_progress', ask))  # the service reads it from last-build
        self.assertFalse(any(step['n'].startswith(('image:', 'stack:')) for step in asked[0]['steps']))  # before the image is built
        steps = {step['n']: step['s'] for step in self.build()['steps']}
        self.assertEqual((steps['migrate-ask'], steps['migrate']), ('ok', 'ok'))

    def test_a_migration_the_live_service_does_not_apply_keeps_the_old_order(self):
        cases = (('an older service: the database stays behind', {'applied': '0001_base'}, 'is not applied after 1s'),
                 ('no port to ask', {'DEPLOY_MIGRATED_CMD': 'exit 1'}, 'is not applied after 1s (the database is at unknown)'),
                 ('the bundle was not published', {'DEPLOY_CODE_BUNDLE_CMD': 'echo AccessDenied; exit 1'}, 'bundle was not published'),
                 ('marked not additive', {'sql': '-- deploy: not-additive\nalter table work.job drop column old;\n'},
                  'is marked not-additive'))
        for label, how, line in cases:
            with self.subTest(label):
                self.setUp()
                done = self.migration(**how)
                self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
                e = self.events()
                self.assertLess(e[('end', 'service')], e[('start', 'runner')])  # the new service migrates at its boot, then the runner
                self.assertIn(line, done.stdout)
                self.assertNotIn('order: tower-app-service exists', done.stdout)

    def test_a_batch_without_a_migration_asks_nothing(self):
        self.image_stacks()
        self.commit('image', infra__service__Dockerfile='y\n')
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='none', DEPLOY_CODE_BUNDLE_CMD='exit 9', DEPLOY_MIGRATED_CMD='exit 9')
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertNotIn('migrate', self.build())
        self.assertNotIn('migrate', ' '.join(step['n'] for step in self.build()['steps']))

    def test_the_templates_name_the_image_they_read_so_its_change_is_in_their_hash(self):
        for template in sorted((ROOT / 'infra/aws/stacks').glob('*.json')):
            resources = json.loads(template.read_text()).get('Resources', {}).values()
            images = [c.get('Image') for r in resources if r.get('Type') == 'AWS::ECS::TaskDefinition'
                      for c in r['Properties']['ContainerDefinitions']]
            if images:
                self.assertIn('/tower/deploy/image/', template.read_text(), template.name)

    # --- DEP7-PORT-FAST-OWNED: the port stack is not redeployed for code the fast path already put live ---------------------
    D = {name: hashlib.sha256(name.encode()).hexdigest() for name in ('api0', 'api1', 'ing0', 'web0', 'web1', 'deps0', 'deps1')}

    def keys(self, api='api1', web='web0', deps='deps0'):
        return {'tower-port-api': f'artifacts/lambda/tower-port-api/{self.D[api]}.zip',
                'tower-port-ack-ingress': f'artifacts/lambda/tower-port-ack-ingress/{self.D["ing0"]}.zip',
                'tower-port-webhook-consumer': f'artifacts/lambda/tower-port-webhook-consumer/{self.D[web]}.zip',
                'deps': f'artifacts/lambda/deps/{self.D[deps]}.zip'}

    def port_rig(self, tag=None, applied=None, fast=(), status='UPDATE_COMPLETE'):
        """The port stack as CloudFormation holds it (status, commit tag, the keys of its last apply), the end of its last
        operation (1000 s ago) and the service's swaps in GET /v1/deploy/status."""
        applied = applied or self.keys(api='api0')
        params = {'AckPath': 'lambda', 'PortCode': applied['tower-port-api'], 'IngressCode': applied['tower-port-ack-ingress'],
                  'WebhookCode': applied['tower-port-webhook-consumer'], 'DepsKey': applied['deps']}
        (self.state / 'stack_tower-app-port.json').write_text(json.dumps({
            'StackStatus': status, 'Tags': [{'Key': 'project', 'Value': 'tower'}, {'Key': 'commit', 'Value': tag or self.base}],
            'Parameters': [{'ParameterKey': k, 'ParameterValue': v} for k, v in params.items()],
            'Outputs': [{'OutputKey': 'PortUrl', 'OutputValue': 'https://port.test'}]}))
        (self.state / 'status.json').write_text(json.dumps({'fast': list(fast)}))
        self.event_at = int(time.time()) - 1000
        return time.strftime('%Y-%m-%dT%H:%M:%S.000000+00:00', time.gmtime(self.event_at))

    def swap(self, function='tower-port-api', digest='api1', ago=10, **extra):
        return {'function': function, 'sha': 'h' * 40, 'digest': self.D[digest], 'version': '12', 'to_version': '12',
                'ok': True, 'rolled_back': False, 'at': int(time.time()) - ago, **extra}

    def run_port(self, keys, last_event, prev=None, **extra):
        return self.run_deploy(**{'STUB_LAST': self.base, 'DEPLOY_SMOKE_CMD': 'none', 'STUB_LAST_EVENT': last_event,
                                  'STUB_LAST_BUILD': json.dumps(prev if prev is not None else {'hashes': {'port': 'old'}}),
                                  'DEPLOY_FAST_STATUS_CMD': f'cat {self.state}/status.json',
                                  'DEPLOY_LAMBDA_PACKAGE_CMD': "echo '" + json.dumps(keys) + "'", **extra})

    def test_the_port_template_as_last_applied_is_the_record_s_not_the_stack_s_tag(self):
        # STACK-COMMIT-OFF-TAGS: the stack carries no commit tag any more; last-build.port_tpl is the template's hash at the
        # last apply, and a Lambda's code the fast path put live leaves the stack alone only while the head's template is it
        self.with_classifier()
        self.commit('api code', **{'infra__service__tower_infra__http_port.py': 'v1\n'})
        event = self.port_rig(fast=[self.swap()])
        stack = json.loads((self.state / 'stack_tower-app-port.json').read_text())
        stack['Tags'] = [{'Key': 'project', 'Value': 'tower'}]  # as the new deployer leaves it
        (self.state / 'stack_tower-app-port.json').write_text(json.dumps(stack))
        template = hashlib.sha256((self.tmp / 'repo/infra/aws/stacks/40-port.json').read_bytes()).hexdigest()[:20]
        done = self.run_port(self.keys(), event, prev={'hashes': {'port': 'old'}, 'port_tpl': template})
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertNotIn('port', self.stacks_deployed())
        self.assertIn('port: code live by the fast path', done.stdout)
        self.assertEqual(self.build()['port_tpl'], template)  # carried: this build applied nothing
        other = self.run_port(self.keys(), event, prev={'hashes': {'port': 'old'}, 'port_tpl': 'f' * 20})
        self.assertIn('port: redeployed: its template is not the one last applied', other.stdout)
        self.assertIn('port', self.stacks_deployed())
        self.assertEqual(self.build()['port_tpl'], template)  # the apply recorded the head's template
        (self.state / 'calls').write_text('')
        (self.state / 'events').write_text('')
        untagged = self.run_port(self.keys(), event, prev={'hashes': {'port': 'old'}})  # no record and no tag: applied
        self.assertIn('its template is not the one applied at an unknown commit', untagged.stdout)
        self.assertIn('port', self.stacks_deployed())

    def test_a_code_change_the_fast_path_put_live_does_not_redeploy_the_port_stack_and_is_carried(self):
        self.with_classifier()
        self.commit('api code', **{'infra__service__tower_infra__http_port.py': 'v1\n'})
        event = self.port_rig(fast=[self.swap(), self.swap(digest='api0', ago=900, version='11', to_version='11')])
        done = self.run_port(self.keys(), event)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertNotIn('port', self.stacks_deployed())
        self.assertIn('port: code live by the fast path (tower-port-api v12), stack not redeployed', done.stdout)
        build = self.build()
        owned = build['fast_owned']['tower-port-api']
        self.assertEqual((list(build['fast_owned']), owned['d'], owned['v']), (['tower-port-api'], self.D['api1'], '12'))
        self.assertGreater(owned['at'], self.event_at)
        self.assertEqual(build['dirty'], [])
        self.assertNotEqual(build['hashes']['port'], 'old')  # the head's: what runs
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), git(self.tmp / 'repo', 'rev-parse', 'HEAD'))
        # the next build: the webhook consumer swapped too, the service restarted (the status forgot the api swap): the record carries it
        self.base = git(self.tmp / 'repo', 'rev-parse', 'HEAD')
        self.commit('web code', **{'infra__service__tower_infra__webhook_consumer.py': 'v1\n'})
        (self.state / 'status.json').write_text(json.dumps({'fast': [self.swap('tower-port-webhook-consumer', 'web1', version='7', to_version='7')]}))
        (self.state / 'calls').write_text('')
        again = self.run_port(self.keys(web='web1'), event, prev=build)
        self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
        self.assertNotIn('port', self.stacks_deployed())
        self.assertIn('code live by the fast path (tower-port-api v12, tower-port-webhook-consumer v7)', again.stdout)
        self.assertEqual(sorted(self.build()['fast_owned']), ['tower-port-api', 'tower-port-webhook-consumer'])
        # unchanged keys since: the recorded hash is the head's, the stack is skipped without asking the fast path
        self.base = git(self.tmp / 'repo', 'rev-parse', 'HEAD')
        self.commit('api again', **{'infra__service__tower_infra__http_port.py': 'v1 doc\n'})
        (self.state / 'status.json').write_text(json.dumps({'fast': []}))
        (self.state / 'calls').write_text('')
        third = self.run_port(self.keys(web='web1'), event, prev=self.build(), STUB_TAGGED='tower-app-port', STUB_TAG_VALUE='older')
        self.assertEqual(third.returncode, 0, third.stderr + third.stdout)
        self.assertNotIn('port', self.stacks_deployed())
        # (SLOW-PATH-STACK-PARTS reads the events of the stacks this build changed and waited: never the port's here)
        self.assertNotIn('describe-stack-events --stack-name tower-app-port', (self.state / 'calls').read_text())
        self.assertIn('skip  tower-app-port: template and images unchanged', third.stdout)

    def test_the_port_stack_is_deployed_when_the_fast_path_is_not_proven_to_run_that_code_1(self):
        self._test_the_port_stack_is_deployed_when_the_fast_path_is_not_proven_to_run_that_code(0)

    def test_the_port_stack_is_deployed_when_the_fast_path_is_not_proven_to_run_that_code_2(self):
        self._test_the_port_stack_is_deployed_when_the_fast_path_is_not_proven_to_run_that_code(1)

    def test_the_port_stack_is_deployed_when_the_fast_path_is_not_proven_to_run_that_code_3(self):
        self._test_the_port_stack_is_deployed_when_the_fast_path_is_not_proven_to_run_that_code(2)

    def _test_the_port_stack_is_deployed_when_the_fast_path_is_not_proven_to_run_that_code(self, part):
        cases = (
            ('no swap known', {}, lambda: []),
            ('rolled back', {}, lambda: [self.swap(ok=False, rolled_back=True)]),
            ('failed', {}, lambda: [self.swap(ok=False)]),
            ('other code', {}, lambda: [self.swap(digest='api0')]),
            ('a later failed swap', {}, lambda: [self.swap(ago=20), self.swap(ago=5, ok=False)]),
            ('swap before the last stack operation', {}, lambda: [self.swap(ago=2000)]),
            ('the layer changed', {'deps': 'deps1'}, lambda: [self.swap()]),
            ('the template changed', {'template': True}, lambda: [self.swap()]),
            ('the stack is not complete', {'status': 'UPDATE_ROLLBACK_COMPLETE'}, lambda: [self.swap()]),
            ('no status', {'nostatus': True}, lambda: [self.swap()]))
        for label, how, fast in cases[part::3]:  # DEPLOY-SHARDS-BY-SECONDS: one part of 3
            with self.subTest(label):
                self.setUp()
                self.with_classifier()
                files = {'infra__service__tower_infra__http_port.py': 'v1\n'}
                if how.get('template'):
                    files['infra__aws__stacks__40-port.json'] = 'changed\n'
                self.commit(label, **files)
                event = self.port_rig(fast=fast(), status=how.get('status', 'UPDATE_COMPLETE'))
                extra = {'DEPLOY_FAST_STATUS_CMD': 'exit 1'} if how.get('nostatus') else {}
                done = self.run_port(self.keys(deps=how.get('deps', 'deps0')), event,
                                     prev={'hashes': {'port': 'old'}, 'fast_owned': {'tower-port-api': {'d': self.D['api1'], 'v': '12', 'at': self.event_at - 5}}},
                                     **extra)
                self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
                self.assertIn('port', self.stacks_deployed())
                self.assertIn('port: redeployed: ', done.stdout)
                self.assertNotIn('code live by the fast path', done.stdout)
                self.assertNotIn('fast_owned', self.build())  # a real apply passed every current key: nothing stands in

    def test_the_status_token_never_reaches_argv_or_the_log(self):
        text = (ROOT / 'infra/aws/deploy.sh').read_text()
        body = text[text.index('fast_status() {'):text.index('deploy_stacks() {')]
        self.assertIn('-K -', body)
        self.assertNotRegex(body, r'-H "Authorization')
        self.assertNotRegex(body, r'echo[^\n]*\$token')

    def test_a_red_smoke_rolls_back_the_changed_stacks_to_the_previous_templates_and_images(self):
        self.with_classifier()
        (self.state / 'param_tower_deploy_image_service').write_text('registry.test/tower-service:previous')
        self.commit('port stack', **{'infra__aws__stacks__40-port.json': 'broken\n'})
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='echo boom; false')
        self.assertNotEqual(done.returncode, 0)
        build = self.build()
        self.assertEqual((build['status'], build['failed'], build['rolled_back']), ('failed', ['smoke'], ['tower-app-port']))
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), None)  # last-sha never advanced
        calls = (self.state / 'calls').read_text()
        self.assertEqual(sum('cloudformation deploy' in line and '--stack-name tower-app-port' in line for line in calls.splitlines()), 2)  # deployed, then restored
        self.assertNotIn('commit=', calls)  # STACK-COMMIT-OFF-TAGS: the restore carries no commit tag either
        self.assertNotIn('port', build['hashes'])
        self.assertNotIn('port_tpl', build)  # and the template as last applied is unknown again: the next build applies it

    def test_a_red_smoke_gives_the_runner_stack_back_the_live_code_it_had_before_the_deploy(self):
        # LIVECODE-NOT-REFUSED: `aws cloudformation deploy` keeps a parameter it is not given: the rollback, with no
        # overrides, left the stack with the LiveCode of the deploy it undid and the tasks came up again on that bundle
        self.with_classifier()
        before, seen = 'b' * 64, f"{'b' * 64}@{self.base}"
        (self.state / 'stack_tower-app-runner.json').write_text(json.dumps({'StackStatus': 'UPDATE_COMPLETE', 'Parameters': [
            {'ParameterKey': 'LiveCode', 'ParameterValue': before}, {'ParameterKey': 'LiveSeen', 'ParameterValue': seen}]}))
        self.commit('runner stack', **{'infra__aws__stacks__50-runner.json': 'broken\n'})
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='echo boom; false')
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.build()['rolled_back'], ['tower-app-runner'])
        deployed, restored = [line for line in (self.state / 'calls').read_text().splitlines()
                              if 'cloudformation deploy' in line and '--stack-name tower-app-runner ' in line]
        self.assertIn('--parameter-overrides LiveCode= LiveSeen=', deployed)  # the head's deploy: no swapped bundle
        self.assertIn(f'--parameter-overrides LiveCode={before} LiveSeen={seen} --tags', restored)  # before: no overrides
        self.assertIn(f'rollback: tower-app-runner to {self.base} (LiveCode={before[:12]})', done.stdout)

    def test_a_bundle_the_engine_refused_is_not_given_to_the_stacks(self):
        # LIVECODE-NOT-REFUSED: the swap's canary was red (or a reload onto the bundle failed): the pointers went back, and
        # the slow path, which deploys the same head, must not hand the tasks the bundle the canary judged broken
        self.five_stacks()
        digest = 'd' * 64
        swap = {'head': self.head, 'digest': digest, 'swapped': True}
        common = {'DEPLOY_FAST_STATUS_CMD': f'cat {self.state}/status.json', 'DEPLOY_TARGETS': 'runner', 'STUB_LAST': 'old'}
        for refusal in ({'image_retired': [{'by': 'canary', 'role': 'service', 'digest': digest}]},
                        {'image_reload': [{'state': 'failed', 'role': 'runner', 'digest': digest}]}):
            (self.state / 'status.json').write_text(json.dumps({'live_code': '', 'image_swap': [swap], **refusal}))
            done = self.run_deploy(**common)
            self.assertIn('live code: the bundle dddddddddddd swapped at', done.stdout)
            self.assertIn('was refused by the engine', done.stdout)
            self.assertIn('--parameter-overrides LiveCode= LiveSeen= --tags', self.stack_calls('runner')[-1])
        (self.state / 'status.json').write_text(json.dumps({'live_code': '', 'image_swap': [swap], 'image_retired': [
            {'by': 'handover', 'role': 'service', 'digest': digest}]}))  # the swap held: the bundle is the head's code
        self.assertIn('live code: LiveCode=dddddddddddd', self.run_deploy(**common).stdout)

    def test_a_green_smoke_keeps_the_deploy(self):
        self.with_classifier()
        self.commit('port stack', **{'infra__aws__stacks__40-port.json': 'ok\n'})
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='echo fine')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('[smoke] fine', done.stdout)
        self.assertEqual(self.build()['rolled_back'], [])

    def test_a_failed_batch_bisects_to_the_culprit_and_keeps_the_rest_deployed(self):
        self.with_classifier()
        commits = [self.commit(f'c{i}', **{f'infra__aws__stacks__40-port.json': f'v{i}\n'}) for i in range(4)]
        common = dict(DEPLOY_SMOKE_CMD='none')
        # the culprit is commit 3 (index 2): the port stack of that tree fails
        def stub_fail(sha):
            tree = git(self.tmp / 'repo', 'show', f'{sha}:infra/aws/stacks/40-port.json')
            return tree
        # 1: the whole batch fails -> bisect state
        failed = self.run_deploy(STUB_LAST=self.base, STUB_FAIL_STACK='tower-app-port', **common)
        self.assertNotEqual(failed.returncode, 0)
        record = self.build()
        self.assertEqual(record['bisect']['good'], self.base)
        self.assertEqual(record['bisect']['bad'], commits[3])
        self.assertEqual(record['bisect']['n'], 4)
        # 2: the next build deploys the first half (commit index 1), green: last-sha moves there, the rest is the new batch
        (self.state / 'param_tower_deploy_last-build').write_text(json.dumps(record))
        green = self.run_deploy(STUB_LAST=self.base, STUB_LAST_BUILD=json.dumps(record), **common)
        self.assertEqual(green.returncode, 0, green.stdout + green.stderr)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), commits[1])
        record = self.build()
        self.assertEqual((record['base_head'], record['bisect']['good'], record['bisect']['bad']), (commits[1], commits[1], commits[3]))
        # 3: the second half is (c1, c3] = c2, c3: its middle is c2; it fails -> the batch is (c1, c2], one commit: the culprit
        (self.state / 'param_tower_deploy_last-sha').write_text(commits[1])
        bad = self.run_deploy(STUB_LAST=commits[1], STUB_LAST_BUILD=json.dumps(record), STUB_FAIL_STACK='tower-app-port', **common)
        self.assertNotEqual(bad.returncode, 0, bad.stdout)
        record = self.build()
        self.assertEqual(record['bisect']['culprit'], commits[2])
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), commits[1])
        self.assertEqual(record['base_head'], commits[2])

    def test_a_single_slow_commit_that_fails_is_the_culprit_at_once(self):
        self.with_classifier()
        culprit = self.commit('port stack', **{'infra__aws__stacks__40-port.json': 'bad\n'})
        self.commit('docs', docs__a_md='x\n')
        done = self.run_deploy(STUB_LAST=self.base, STUB_FAIL_STACK='tower-app-port', DEPLOY_SMOKE_CMD='none')
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.build()['bisect']['culprit'], culprit)

    # DEP7-BISECT-FIX: a bisection never blocks for ever
    def epoch_record(self, base_head, bisect, **more):
        if isinstance(bisect, dict):
            bisect = {'head_tried_sha': base_head, **bisect}  # the record's head is the one tried; a moved head goes first
        return {'build_id': 'x', 'base_head': base_head, 'status': 'succeeded', 'bisect': bisect, 'bisect_epoch': 2, **more}

    def deploy_with(self, record, last, **extra):
        (self.state / 'param_tower_deploy_last-sha').write_text(last)
        return self.run_deploy(STUB_LAST=last, STUB_LAST_BUILD=json.dumps(record), DEPLOY_SMOKE_CMD='none', **extra)

    def two_slow(self):
        self.with_classifier()
        return [self.commit(f'c{i}', **{'infra__aws__stacks__40-port.json': f'v{i}\n'}) for i in range(2)]

    def test_good_and_bad_adjacent_resolve_at_once_and_never_redeploy_the_same_commit(self):
        a, b = self.two_slow()
        record = self.epoch_record(b, {'good': self.base, 'bad': a, 'builds': 0})
        done = self.deploy_with(record, self.base)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual((self.recorded('/tower/deploy/last-sha'), self.build()['bisect']), (a, None))  # moved off base
        red = self.deploy_with(record, self.base, STUB_FAIL_STACK='tower-app-port')
        self.assertNotEqual(red.returncode, 0)
        self.assertEqual(self.build()['bisect']['culprit'], a)  # adjacent and red: culprit = bad, no more rounds

    def test_a_culprit_never_blocks_the_next_build_which_deploys_the_head_and_clears_it(self):
        a, b = self.two_slow()
        record = self.epoch_record(b, {'culprit': a, 'good': self.base, 'bad': a, 'builds': 0}, status='failed')
        done = self.deploy_with(record, self.base)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual((self.recorded('/tower/deploy/last-sha'), self.build()['bisect']), (b, None))
        self.assertIn('does not block', self.build()['bisect_note'])
        red = self.deploy_with(record, self.base, STUB_FAIL_STACK='tower-app-port')  # the head still fails: the batch is bisected again
        self.assertNotEqual(red.returncode, 0)
        self.assertEqual(self.build()['bisect']['good'], self.base)
        self.assertEqual(self.build()['base_head'], b)

    def test_a_green_midpoint_moves_good_and_last_sha_and_only_a_failure_sets_bad(self):
        self.with_classifier()
        c = [self.commit(f'c{i}', **{'infra__aws__stacks__40-port.json': f'v{i}\n'}) for i in range(4)]
        record = self.epoch_record(c[3], {'good': self.base, 'bad': c[3], 'n': 4, 'builds': 0})
        done = self.deploy_with(record, self.base)
        self.assertEqual(done.returncode, 0, done.stdout)
        built = self.build()
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), c[1])
        self.assertEqual((built['bisect']['good'], built['bisect']['bad'], built['bisect']['builds']), (c[1], c[3], 1))
        red = self.deploy_with(record, self.base, STUB_FAIL_STACK='tower-app-port')
        built = self.build()
        self.assertEqual((built['bisect']['good'], built['bisect']['bad']), (self.base, c[1]))  # bad moved, good did not
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), c[1])  # untouched by the red (from the green above)

    def test_a_bisection_older_than_n_builds_or_with_a_bad_sha_outside_the_history_is_discarded(self):
        a, b = self.two_slow()
        old = self.epoch_record(b, {'good': self.base, 'bad': a, 'builds': 8})
        self.assertEqual(self.deploy_with(old, self.base).returncode, 0)
        self.assertEqual((self.recorded('/tower/deploy/last-sha'), self.build()['bisect']), (b, None))
        self.assertIn('8 builds', self.build()['bisect_note'])
        young = self.epoch_record(b, {'good': self.base, 'bad': a, 'builds': 7})
        self.assertEqual(self.deploy_with(young, self.base).returncode, 0)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), a)  # 7 < 8: still steering
        self.assertEqual(self.deploy_with(young, self.base, DEPLOY_BISECT_MAX_BUILDS='7').returncode, 0)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), b)  # configurable
        gone = self.epoch_record(b, {'good': self.base, 'bad': 'f' * 40, 'builds': 0})
        self.assertEqual(self.deploy_with(gone, self.base).returncode, 0)
        self.assertEqual((self.recorded('/tower/deploy/last-sha'), self.build()['bisect']), (b, None))
        self.assertIn('not in the history', self.build()['bisect_note'])
        side = git(self.tmp / 'repo', 'rev-parse', 'HEAD')
        git(self.tmp / 'repo', 'checkout', '-q', '--detach', self.base)
        other = self.commit('side', **{'infra__aws__stacks__40-port.json': 'side\n'})
        git(self.tmp / 'repo', 'checkout', '-q', self.branch)
        elsewhere = self.epoch_record(side, {'good': self.base, 'bad': other, 'builds': 0})
        self.assertEqual(self.deploy_with(elsewhere, self.base).returncode, 0)
        self.assertEqual((self.recorded('/tower/deploy/last-sha'), self.build()['bisect']), (side, None))

    def test_the_epoch_resets_the_live_state_once_and_a_green_build_clears_it(self):
        a, b = self.two_slow()
        live = {'build_id': 'x', 'base_head': a, 'status': 'succeeded', 'bisect': {'good': self.base, 'bad': a}}  # no epoch
        self.assertEqual(self.deploy_with(live, self.base).returncode, 0)
        built = self.build()
        self.assertEqual((self.recorded('/tower/deploy/last-sha'), built['bisect'], built['bisect_epoch']), (b, None, 2))
        self.assertIn('epoch 0', built['bisect_note'])
        red = self.deploy_with(live, self.base, STUB_FAIL_STACK='tower-app-port')  # a red build starts a fresh bisection
        self.assertEqual((self.build()['bisect']['good'], self.build()['bisect']['bad']), (self.base, b))
        done = self.deploy_with(live, b)  # nothing new also clears it
        self.assertEqual((done.returncode, self.build()['status'], self.build()['bisect']), (0, 'nothing_new', None))

    # DEP7-HEAD-FIRST: after a failed batch, a head that moved is deployed first; the bisection starts only if it fails too
    def failed_state(self, **more):
        a, b, c = [self.commit(f'c{i}', **{'infra__aws__stacks__40-port.json': f'v{i}\n'}) for i in range(3)]
        return a, b, c, self.epoch_record(b, {'good': self.base, 'bad': b, 'n': 2, 'builds': 2, **more}, status='failed')

    def test_a_moved_head_is_deployed_first_and_green_clears_the_bisection(self):
        self.with_classifier()
        a, b, c, rec = self.failed_state()
        done = self.deploy_with(rec, self.base)
        self.assertEqual(done.returncode, 0, done.stdout)
        built = self.build()
        self.assertEqual((self.recorded('/tower/deploy/last-sha'), built['base_head'], built['bisect'], built['batch']), (c, c, None, 3))
        self.assertIn('head first', built['bisect_note'])

    def test_a_legacy_state_without_head_tried_also_goes_head_first(self):
        self.with_classifier()
        a, b, c, rec = self.failed_state()
        rec['bisect'].pop('head_tried_sha')
        self.assertEqual(self.deploy_with(rec, self.base).returncode, 0)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), c)

    def test_a_red_head_first_build_starts_the_bisection_between_last_sha_and_that_head(self):
        self.with_classifier()
        a, b, c, rec = self.failed_state()
        self.assertNotEqual(self.deploy_with(rec, self.base, STUB_FAIL_STACK='tower-app-port').returncode, 0)
        bis = self.build()['bisect']
        self.assertEqual((bis['good'], bis['bad'], bis['n'], bis['builds'], bis['head_tried_sha']), (self.base, c, 3, 3, c))
        # the head did not move, head_tried: the next build deploys the midpoint (not the head), with the head's scripts
        nxt = self.epoch_record(c, bis, status='failed')
        self.assertEqual(self.deploy_with(nxt, self.base).returncode, 0)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), a)

    # DEP7-NEW-HEAD-FIRST: the head-first rule is keyed to a head sha, not once per state
    def three(self, n=3):
        return [self.commit(f'c{i}', **{'infra__aws__stacks__40-port.json': f'v{i}\n'}) for i in range(n)]

    def test_a_state_from_red_h1_and_a_new_head_h2_deploys_h2_next(self):
        self.with_classifier()
        h1, h2 = self.three(2)  # H1 failed as the whole batch; H2 landed since
        rec = self.epoch_record(h1, {'good': self.base, 'bad': h1, 'n': 2, 'builds': 0}, status='failed')
        self.assertEqual(self.deploy_with(rec, self.base).returncode, 0)
        built = self.build()
        self.assertEqual((self.recorded('/tower/deploy/last-sha'), built['base_head'], built['bisect']), (h2, h2, None))
        self.assertIn('head first', built['bisect_note'])

    def test_a_red_h2_bisects_between_last_sha_and_h2_and_the_next_build_is_a_midpoint(self):
        self.with_classifier()
        a, h1, h2 = self.three()
        rec = self.epoch_record(h1, {'good': self.base, 'bad': h1, 'n': 2, 'builds': 0}, status='failed')
        self.assertNotEqual(self.deploy_with(rec, self.base, STUB_FAIL_STACK='tower-app-port').returncode, 0)
        bis = self.build()['bisect']
        self.assertEqual((bis['good'], bis['bad'], bis['head_tried_sha']), (self.base, h2, h2))
        self.assertEqual(self.deploy_with(self.epoch_record(h2, bis, status='failed'), self.base).returncode, 0)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), a)  # H2 is tried and unmoved: now the midpoint

    def test_h3_landing_during_the_bisection_is_deployed_before_any_midpoint(self):
        self.with_classifier()
        a, h2, h3 = self.three()
        # bisecting (base, h2] on midpoints: a failed, so bad moved to a, but the tried head is still h2; h3 landed since
        rec = self.epoch_record(h2, {'good': self.base, 'bad': a, 'n': 1, 'builds': 2, 'head_tried_sha': h2}, status='failed')
        red = self.deploy_with(rec, self.base, STUB_FAIL_STACK='tower-app-port')
        self.assertNotEqual(red.returncode, 0)
        built = self.build()
        self.assertEqual(built['base_head'], h3)  # not the midpoint a
        self.assertEqual((built['bisect']['good'], built['bisect']['bad'], built['bisect']['head_tried_sha']), (self.base, h3, h3))
        self.assertEqual(self.deploy_with(rec, self.base).returncode, 0)
        self.assertEqual((self.recorded('/tower/deploy/last-sha'), self.build()['bisect']), (h3, None))

    def test_an_unmoved_head_bisects_at_once(self):
        self.with_classifier()
        a, b, c, rec = self.failed_state()
        rec = self.epoch_record(c, {'good': self.base, 'bad': c, 'n': 3, 'builds': 0}, status='failed')  # head == bad
        self.assertEqual(self.deploy_with(rec, self.base).returncode, 0)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), a)
        self.assertNotIn('head first', self.build().get('bisect_note') or '')

    def test_head_first_still_respects_the_build_cap(self):
        self.with_classifier()
        a, b, c, rec = self.failed_state(builds=8)
        self.assertEqual(self.deploy_with(rec, self.base).returncode, 0)
        self.assertIn('8 builds', self.build()['bisect_note'])

    def test_the_bisection_builds_run_the_scripts_of_the_head_not_the_midpoint(self):
        self.with_classifier()
        repo = self.tmp / 'repo'
        shas = []
        for i, marker in enumerate(['OLD', 'OLD', 'NEW']):
            (repo / 'scripts').mkdir(exist_ok=True)
            smoke = repo / 'scripts/deploy-smoke'
            smoke.write_text(f'#!/usr/bin/env bash\necho {marker} >> "$STUB_DIR/smokes"\n')
            smoke.chmod(0o755)
            shas.append(self.commit(f'c{i}', **{'infra__aws__stacks__40-port.json': f'v{i}\n'}))
        a, b, c = shas
        rec = self.epoch_record(c, {'good': self.base, 'bad': c, 'n': 3, 'builds': 1}, status='failed')  # head_tried: the midpoint steers
        (self.state / 'param_tower_deploy_last-sha').write_text(self.base)
        done = self.run_deploy(STUB_LAST=self.base, STUB_LAST_BUILD=json.dumps(rec))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), a)  # the midpoint was deployed ...
        self.assertEqual((self.state / 'smokes').read_text().split(), ['NEW'])  # ... with the smoke of the head
        self.assertEqual(git(repo, 'rev-parse', 'HEAD'), a)  # templates come from the midpoint's tree

    def test_the_cycle_is_measured_in_seconds_and_dollars(self):
        done = self.run_deploy(STUB_LAST='old', DEPLOY_SMOKE_CMD='none', DEPLOY_PRICE_PER_MINUTE='0.006')
        build = self.build()
        self.assertEqual(build['seconds'], build['ended'] - build['started'])
        self.assertAlmostEqual(build['usd'], round(build['seconds'] / 60 * 0.006, 6), places=6)
        self.assertEqual(build['rolled_back'], [])

    # --- SLOW-PATH-NO-ROLLOUT-WAIT: the ECS rollout is off the build's clock. A build starts the update of the stacks that carry
    # an ECS service and ends `rolling`; the next build verifies them, runs the smoke and moves last-sha --------------------------
    ECS = '{"Parameters": {"Image": {"Default": "/tower/deploy/image/service"}}, "Resources": {"Service": {"Type": "AWS::ECS::Service"}}}\n'
    ALL = 'tower-app-service tower-app-port tower-app-runner'

    def ecs_stacks(self):
        """service and runner carry an ECS service and read the image, as the real templates do; the three stacks exist."""
        self.with_classifier()
        self.base = self.commit('the ecs stacks', **{'infra__aws__stacks__30-service.json': self.ECS,
                                                     'infra__aws__stacks__50-runner.json': self.ECS})
        (self.state / 'param_tower_deploy_last-sha').write_text(self.base)
        for name in ('service', 'ingress'):
            (self.state / f'param_tower_deploy_image_{name}').write_text(f'registry.test/tower-{name}:one')

    def start(self, **extra):
        """A new image lands: the build that starts the rollouts. Answers (the run, the head, its record)."""
        self.ecs_stacks()
        head = self.commit('image', infra__service__Dockerfile='y\n')
        done = self.run_deploy(**{'STUB_LAST': self.base, 'DEPLOY_SMOKE_CMD': 'echo smoked', 'STUB_TAGGED': self.ALL,
                                  'STUB_TAG_VALUE': 'older', 'STUB_SLEEP': 'tower-app-service:30,tower-app-runner:30', **extra})
        return done, head, self.build()

    def verify(self, record, at=None, **extra):
        """The next build, with the stacks as `at` says ({stack: 'STATUS<tab>TAG' lines})."""
        (self.state / 'calls').write_text('')
        (self.state / 'events').write_text('')
        for stack, lines in (at or {}).items():
            (self.state / f'status_tower-app-{stack}').write_text(lines + '\n')
        plain = hashlib.sha256(b'x\n').hexdigest()[:20]  # network and data: applied long ago, their hash recorded
        record = {**record, 'hashes': {'network': plain, 'data': plain, **record['hashes']}}
        return self.run_deploy(**{'STUB_LAST': self.base, 'STUB_LAST_BUILD': json.dumps(record), 'DEPLOY_SMOKE_CMD': 'echo smoked',
                                  'DEPLOY_ROLL_POLL_S': '0.2', **extra})

    def rolled(self, head, status='UPDATE_COMPLETE'):
        return {stack: f'{status}\t{head}' for stack in ('service', 'port', 'runner')}

    def test_the_build_starts_the_ecs_rollouts_and_ends_rolling_without_waiting_for_them(self):
        began = time.time()
        done, head, build = self.start()
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertLess(time.time() - began, 25)  # each rollout would cost 30 s if it were waited
        e = self.events()
        self.assertEqual(sorted(stack for kind, stack in e if kind == 'execute'), ['runner', 'service'])
        self.assertNotIn(('end', 'service'), e)
        for stack in ('service', 'runner'):
            self.assertIn('--no-execute-changeset', self.stack_calls(stack)[0])
        self.assertNotIn('--no-execute-changeset', self.stack_calls('port')[0])  # no ECS service in it: applied and waited
        self.assertEqual(build['status'], 'rolling')
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))  # not deployed until the next build verifies
        self.assertNotIn('smoked', done.stdout)
        roll = build['rolling']
        self.assertEqual((roll['head'], sorted(roll['stacks']), roll['changed']), (head, ['runner', 'service'], ['port', 'runner', 'service']))
        self.assertEqual(roll['prev'], {'ingress': 'registry.test/tower-ingress:one', 'service': 'registry.test/tower-service:one'})
        # no rollout measured yet: DEPLOY_ROLLOUT_EXPECT_S after the last stack's start, plus the margin; never from the build's end
        self.assertEqual(roll['until'], max(each['t0'] for each in roll['stacks'].values()) + 600 + 60)
        self.assertGreaterEqual(roll['stacks']['runner']['t0'], int(began))
        self.assertEqual((build['dirty'], build['failed'], sorted(build['hashes'])), ([], [], ['port']))
        self.assertIn('rolling: tower-app-runner tower-app-service started and not waited', done.stdout)
        steps = {step['n']: step['s'] for step in build['steps']}
        self.assertEqual((steps['stack:service'], steps['stack:runner']), ('ok', 'ok'))

    def test_the_next_build_verifies_the_rollouts_runs_the_smoke_and_moves_last_sha(self):
        _, head, record = self.start()
        t0 = min(each['t0'] for each in record['rolling']['stacks'].values())
        end = time.strftime('%Y-%m-%dT%H:%M:%S.000000+00:00', time.gmtime(t0 + 400))
        record['rollout'] = {'tower-app-data': 9}  # an older figure of another stack is kept
        done = self.verify(record, self.rolled(head), STUB_LAST_EVENT=end)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertEqual(self.stacks_deployed(), [])  # nothing is applied again
        self.assertIn('done  tower-app-runner: rolled out at', done.stdout)
        self.assertIn('[smoke] smoked', done.stdout)
        build = self.build()
        self.assertEqual((build['status'], self.recorded('/tower/deploy/last-sha')), ('succeeded', head))
        self.assertNotIn('rolling', build)
        for stack in ('tower-app-service', 'tower-app-runner'):
            self.assertAlmostEqual(build['rollout'][stack], 400, delta=3)  # from the stack's start to its end: off the clock
        self.assertEqual(build['rollout']['tower-app-data'], 9)
        self.assertAlmostEqual(build['rollout_wait_s'], t0 + 400 - record['ended'], delta=1)
        self.assertEqual(sorted(build['hashes']), ['data', 'network', 'port', 'runner', 'service'])
        self.assertEqual(build['hashes']['runner'], record['rolling']['stacks']['runner']['hash'])
        self.assertEqual(build['dirty'], [])
        # the build after it starts from that figure: the safety comes at the last rollout's seconds, not the default
        self.base = head
        (self.state / 'param_tower_deploy_last-sha').write_text(head)
        self.commit('image again', infra__service__Dockerfile='z\n')
        (self.state / 'param_tower_deploy_image_service').write_text('registry.test/tower-service:two')  # the push
        (self.state / 'status_tower-app-service').unlink()
        (self.state / 'status_tower-app-runner').unlink()
        third = self.run_deploy(STUB_LAST=head, STUB_LAST_BUILD=json.dumps(build), DEPLOY_SMOKE_CMD='none', STUB_TAGGED=self.ALL,
                                STUB_TAG_VALUE=head)
        self.assertEqual(third.returncode, 0, third.stderr + third.stdout)
        roll, took = self.build()['rolling'], build['rollout']
        self.assertEqual(roll['until'], max(each['t0'] + took[f'tower-app-{stack}'] for stack, each in roll['stacks'].items()) + 60)

    def test_a_rollout_cloudformation_rolled_back_fails_the_build_and_is_not_applied_again(self):
        _, head, record = self.start()
        at = {**self.rolled(head), 'runner': 'UPDATE_ROLLBACK_COMPLETE\tolder'}
        done = self.verify(record, at)
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.stacks_deployed(), [])  # this head was tried: never deployed again by this build
        build = self.build()
        self.assertEqual((build['status'], build['failed'], build['failed_step']), ('failed', ['tower-app-runner'], 'stack:runner'))
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))
        self.assertEqual(build['bisect']['culprit'], head)  # one slow commit: the failed batch is named, as for any failed stack
        self.assertIn('the rollout started at', done.stdout)
        self.assertIn('failed events of tower-app-runner', done.stdout)
        self.assertNotIn('smoked', done.stdout)
        self.assertNotIn('rolling', build)

    def test_a_build_that_comes_before_the_end_waits_for_the_stack_and_then_verifies_it(self):
        _, head, record = self.start()
        # (the empty line: a describe-stacks that answered nothing, e.g. throttled: not an end, the wait goes on)
        at = {**self.rolled(head), 'runner': f'UPDATE_IN_PROGRESS\t{head}\n\nUPDATE_IN_PROGRESS\t{head}\nUPDATE_COMPLETE\t{head}'}
        done = self.verify(record, at)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn('wait  tower-app-runner: UPDATE_IN_PROGRESS', done.stdout)
        self.assertEqual((self.state / 'status_tower-app-runner').read_text(), f'UPDATE_COMPLETE\t{head}\n')  # every line was read
        self.assertEqual(self.stacks_deployed(), [])
        build = self.build()
        self.assertEqual((build['status'], self.recorded('/tower/deploy/last-sha')), ('succeeded', head))
        self.assertEqual({step['n']: step['s'] for step in build['steps']}['wait:runner'], 'ok')
        # the readings of a rolling stack answer nothing (the order's, then the stack's own): it is waited and verified, never
        # applied on a guess
        done = self.verify(record, {**self.rolled(head), 'service': f'\n\nUPDATE_COMPLETE\t{head}'})
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn('wait  tower-app-service: status unreadable', done.stdout)
        self.assertEqual(self.stacks_deployed(), [])

    # --- VERIFY-AT-UP: a rolled stack whose new task said it is up on the rollout's image is settled, not waited ----------------
    def ups(self, record, image=None, at=None):
        """The port's status as the verifying build reads it (DEPLOY_FAST_STATUS_CMD): each rolled stack's new task up."""
        image = image or record['rolling']['stacks']['service']['image']
        status = self.state / 'deploy_status.json'
        status.write_text(json.dumps({'task_up': [
            {'type': 'platform.deploy.task_up', 'stack': f'tower-app-{name}', 'role': name, 'image': image,
             'at': at if at is not None else each['t0'] + 95.5} for name, each in record['rolling']['stacks'].items()]}))
        return {'DEPLOY_FAST_STATUS_CMD': f'cat {status}'}

    def test_the_rolling_build_names_the_image_each_rolled_stack_runs(self):
        _, head, record = self.start()
        # what the stacks read (the stub answers get-parameter from param_*, apart from the puts: live, the push just made)
        image = (self.state / 'param_tower_deploy_image_service').read_text()
        self.assertEqual({name: each['image'] for name, each in record['rolling']['stacks'].items()},
                         {'service': image, 'runner': image})

    def test_a_rollout_whose_new_task_is_up_is_settled_before_its_stacks_end_and_the_next_build_sees_the_end(self):
        _, head, record = self.start()
        at = {**self.rolled(head), 'service': f'UPDATE_IN_PROGRESS\t{head}', 'runner': f'UPDATE_IN_PROGRESS\t{head}'}
        began = time.time()
        done = self.verify(record, at, **self.ups(record))
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertLess(time.time() - began, 30)  # the stacks never ended: nothing waited for them
        self.assertEqual(self.stacks_deployed(), [])
        self.assertRegex(done.stdout, r'done  tower-app-runner: up at \w+, its new task said so 9[56]s after the update started')
        self.assertIn('[smoke] smoked', done.stdout)
        build = self.build()
        self.assertEqual((build['status'], self.recorded('/tower/deploy/last-sha')), ('succeeded', head))
        self.assertEqual(build['dirty'], [])
        self.assertEqual(build['hashes']['runner'], record['rolling']['stacks']['runner']['hash'])
        roll = build['rolling']  # their end is the next build's to verify
        self.assertEqual((roll['head'], roll['settling'], sorted(roll['stacks'])), (head, True, ['runner', 'service']))
        self.assertIn(roll['stacks']['runner']['up'], (95, 96))
        self.assertEqual(roll['stacks']['runner']['t0'], record['rolling']['stacks']['runner']['t0'])
        # the build after it: the stacks ended complete: done, their seconds measured, nothing applied, no smoke of its own
        (self.state / 'deploy_status.json').unlink()
        t0 = min(each['t0'] for each in roll['stacks'].values())
        end = time.strftime('%Y-%m-%dT%H:%M:%S.000000+00:00', time.gmtime(t0 + 210))
        later = self.verify(build, self.rolled(head), STUB_LAST_EVENT=end)
        self.assertEqual(later.returncode, 0, later.stderr + later.stdout)
        self.assertEqual(self.stacks_deployed(), [])
        self.assertIn('done  tower-app-runner: rolled out at', later.stdout)
        after = self.build()
        self.assertEqual(after['status'], 'succeeded')
        self.assertNotIn('rolling', after)
        self.assertAlmostEqual(after['rollout']['tower-app-runner'], 210, delta=3)
        # ... or CloudFormation rolled one back after its task was up (the same head): that build fails, as a failed rollout
        failed = self.verify(build, {**self.rolled(head), 'runner': 'UPDATE_ROLLBACK_COMPLETE\tolder'})
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.build()['failed'], ['tower-app-runner'])

    def test_a_red_smoke_after_a_settle_waits_for_the_stacks_end_then_rolls_back(self):
        _, head, record = self.start()
        going = '\n'.join([f'UPDATE_IN_PROGRESS\t{head}'] * 6 + [f'UPDATE_COMPLETE\t{head}'])
        done = self.verify(record, {**self.rolled(head), 'service': going, 'runner': going}, DEPLOY_SMOKE_CMD='echo boom; false',
                           **self.ups(record))
        self.assertNotEqual(done.returncode, 0)
        self.assertIn('done  tower-app-runner: up at', done.stdout)
        for name in ('service', 'runner'):  # CloudFormation takes no update while the stack is in its operation: its end first
            self.assertEqual((self.state / f'status_tower-app-{name}').read_text(), f'UPDATE_COMPLETE\t{head}\n')
        build = self.build()
        self.assertEqual((build['status'], build['failed']), ('failed', ['smoke']))
        self.assertEqual(sorted(build['rolled_back']), ['tower-app-port', 'tower-app-runner', 'tower-app-service'])
        self.assertNotIn('rolling', build)
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))

    def test_a_task_up_on_another_image_or_before_the_rollout_settles_nothing(self):
        _, head, record = self.start()
        at = {**self.rolled(head), 'runner': f'UPDATE_IN_PROGRESS\t{head}\nUPDATE_IN_PROGRESS\t{head}\nUPDATE_COMPLETE\t{head}'}
        for status in (self.ups(record, image='registry.test/tower-service:one'),
                       self.ups(record, at=record['rolling']['stacks']['runner']['t0'] - 300)):
            done = self.verify(record, at, **status)
            self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
            self.assertIn('wait  tower-app-runner: UPDATE_IN_PROGRESS', done.stdout)
            self.assertIn('done  tower-app-runner: rolled out at', done.stdout)  # waited for its end, as before
            self.assertNotIn('settling', self.build().get('rolling') or {})

    def test_a_red_smoke_at_the_verification_rolls_back_what_both_builds_changed(self):
        _, head, record = self.start()
        done = self.verify(record, self.rolled(head), DEPLOY_SMOKE_CMD='echo boom; false')
        self.assertNotEqual(done.returncode, 0)
        build = self.build()
        self.assertEqual((build['status'], build['failed']), ('failed', ['smoke']))
        self.assertEqual(sorted(build['rolled_back']), ['tower-app-port', 'tower-app-runner', 'tower-app-service'])
        self.assertEqual(self.recorded('/tower/deploy/image/service'), 'registry.test/tower-service:one')  # the image before the FIRST build
        self.assertEqual(self.stacks_deployed(), ['port', 'runner', 'service'])  # the rollback's applies, waited
        self.assertNotIn('--no-execute-changeset', (self.state / 'calls').read_text())
        self.assertIsNone(self.recorded('/tower/deploy/last-sha'))

    def test_a_head_that_moved_while_rolling_is_deployed_by_the_verifying_build(self):
        _, head, record = self.start()
        moved = self.commit('runner template', **{'infra__aws__stacks__50-runner.json': self.ECS.replace('}}}', '}}, "v": 2}')})
        done = self.verify(record, {**self.rolled(head), 'runner': f'UPDATE_ROLLBACK_COMPLETE\t{self.base}'})
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)  # the failed rollout of the older head does not fail this one
        self.assertEqual(self.stacks_deployed(), ['runner'])  # the service rolled out and its inputs are the same: not applied again
        build = self.build()
        self.assertEqual((build['status'], build['rolling']['head'], sorted(build['rolling']['stacks'])), ('rolling', moved, ['runner']))
        self.assertEqual(build['rolling']['changed'], ['port', 'runner', 'service'])  # what a red smoke would roll back: both builds'
        self.assertEqual(build['rolling']['prev']['service'], 'registry.test/tower-service:one')
        self.assertEqual(build['hashes']['service'], record['rolling']['stacks']['service']['hash'])

    def test_a_build_of_a_github_repository_waits_its_rollouts_and_moves_last_sha_itself(self):
        """DEPLOY-FROM-GITHUB: no service rings the build that would verify a rolling one, so it is never left rolling."""
        done, head, build = self.start(ORIGIN_REPO_URL='https://github.com/openuniversity-si/open-university.git', STUB_SLEEP='')
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertEqual((build['status'], self.recorded('/tower/deploy/last-sha')), ('succeeded', head))
        self.assertNotIn('--no-execute-changeset', (self.state / 'calls').read_text())
        self.assertIn('rollouts: waited inside the build', done.stdout)
        self.setUp()  # an explicit DEPLOY_ROLLOUT_WAIT=0 still leaves them rolling, and Origin's URL is as before
        for env in ({'ORIGIN_REPO_URL': 'https://github.com/openuniversity-si/open-university.git', 'DEPLOY_ROLLOUT_WAIT': '0'},
                    {'ORIGIN_REPO_URL': 'https://origin.example/owner/repo.git'}):
            self.setUp()
            done, head, build = self.start(**env)
            self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
            self.assertEqual(build['status'], 'rolling', env)
            self.assertIsNone(self.recorded('/tower/deploy/last-sha'))
            self.assertNotIn('rollouts: waited inside the build', done.stdout)

    def test_a_hard_edge_a_new_stack_a_bisection_or_the_switch_wait_inside_the_build(self):
        done, head, build = self.start(DEPLOY_ROLLOUT_WAIT='1', STUB_SLEEP='')
        self.assertEqual((build['status'], self.recorded('/tower/deploy/last-sha')), ('succeeded', head))
        self.assertNotIn('--no-execute-changeset', (self.state / 'calls').read_text())
        self.setUp()  # the runner must have the service complete (a new export): the service is waited, the runner is not
        self.ecs_stacks()
        self.commit('export', **{'infra__aws__stacks__30-service.json': self.ECS.replace('}}}', '}}, "Outputs": {"New": {}}}')})
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='none', STUB_TAGGED=self.ALL, STUB_TAG_VALUE='older')
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertNotIn('--no-execute-changeset', self.stack_calls('service')[0])
        self.assertIn('--no-execute-changeset', self.stack_calls('runner')[0])
        self.assertLess(self.events()[('end', 'service')], self.events()[('start', 'runner')])
        self.assertEqual(sorted(self.build()['rolling']['stacks']), ['runner'])
        self.setUp()  # a stack that does not exist yet is created and waited
        self.ecs_stacks()
        self.commit('image', infra__service__Dockerfile='y\n')
        done = self.run_deploy(STUB_LAST=self.base, DEPLOY_SMOKE_CMD='none', STUB_TAGGED='tower-app-port', STUB_TAG_VALUE='older')
        self.assertEqual((done.returncode, self.build()['status']), (0, 'succeeded'), done.stdout)
        self.assertNotIn('--no-execute-changeset', (self.state / 'calls').read_text())
        self.setUp()  # a bisection deploys an older commit on purpose: it waits, as before
        self.ecs_stacks()
        first = self.commit('image 1', infra__service__Dockerfile='y\n')
        second = self.commit('image 2', infra__service__Dockerfile='z\n')
        state = {'bisect': {'good': self.base, 'bad': second, 'n': 2, 'builds': 0, 'head_tried_sha': second}, 'bisect_epoch': 2, 'status': 'failed'}
        done = self.run_deploy(STUB_LAST=self.base, STUB_LAST_BUILD=json.dumps(state), DEPLOY_SMOKE_CMD='none', STUB_TAGGED=self.ALL,
                               STUB_TAG_VALUE='older')
        self.assertEqual((done.returncode, self.recorded('/tower/deploy/last-sha')), (0, first), done.stdout)
        self.assertNotIn('--no-execute-changeset', (self.state / 'calls').read_text())

    def test_a_change_set_that_cannot_be_executed_fails_the_stack(self):
        for label, how in (('refused', {'STUB_FAIL_EXECUTE': 'tower-app-runner'}), ('no arn', {'STUB_NO_ARN': '1'})):
            with self.subTest(label):
                self.setUp()
                done, head, build = self.start(**how)
                self.assertNotEqual(done.returncode, 0)
                self.assertEqual(build['status'], 'failed')
                self.assertIn('tower-app-runner', build['failed'])
                self.assertNotIn('rolling', build)

    # --- SLOW-PATH-NO-ROLLOUT-WAIT: a code-only landing whose code is live and durable deploys nothing of the image or the ECS stacks
    LIVE = 'c0de' * 16  # the sha256 of the head's code bundle

    def code_only(self, status=None, service=None, runner=None, files=None, port=False, **extra):
        """A code-only landing over stacks a first build applied (their hashes recorded). The status says the landing's
        bundle is deploy.live_code and both ECS tasks reloaded it; the two stacks' parameters are as given. port: the port
        stack as CloudFormation holds it, on its older Lambda keys (port_rig). Answers (the run of the landing's build,
        its head, the recorded hashes)."""
        self.ecs_stacks()
        if port:
            extra = {'STUB_LAST_EVENT': self.port_rig(), **extra}
        (self.state / 'param_tower_deploy_last-sha').unlink()
        first = self.run_deploy(STUB_LAST='old', DEPLOY_TARGETS='all', DEPLOY_SMOKE_CMD='none')
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        hashes = self.build()['hashes']
        (self.state / 'param_tower_deploy_last-sha').write_text(self.base)
        head = self.commit('code', **(files or {'infra__service__tower_infra__runner.py': 'new code\n'}))
        said = {'live_code': f'{self.LIVE}@{head}', 'image_reload': [
            {'role': role, 'digest': self.LIVE, 'state': 'reloaded', 'task': f'ecs-{role}'} for role in ('service', 'runner')]}
        (self.state / 'status.json').write_text(json.dumps({**said, **(status or {})}))
        for stack, given in (('service', service), ('runner', runner)):
            given = {'status': 'UPDATE_COMPLETE', 'LiveCode': '', 'LiveSeen': '', **(given or {})}
            given = {key: said['live_code'] if value == 'DATUM' else value for key, value in given.items()}
            (self.state / f'stack_tower-app-{stack}.json').write_text(json.dumps({
                'StackStatus': given.pop('status'),
                'Parameters': [{'ParameterKey': key, 'ParameterValue': value} for key, value in given.items() if value is not None]}))
        (self.state / 'calls').write_text('')
        done = self.run_deploy(**{
            'STUB_LAST': self.base, 'STUB_LAST_BUILD': json.dumps({'hashes': hashes}), 'DEPLOY_SMOKE_CMD': 'echo smoked',
            'STUB_TAGGED': 'tower-app-network tower-app-data ' + self.ALL, 'STUB_TAG_VALUE': 'older', 'DEPLOY_ROLLOUT_WAIT': '1',
            'DEPLOY_FAST_STATUS_CMD': f'cat {self.state}/status.json',
            'DEPLOY_CODE_DIGEST_CMD': "echo '" + json.dumps({'sha256': self.LIVE, 'uploaded': False}) + "'", **extra})
        return done, head, hashes

    def test_a_code_only_landing_whose_code_is_live_builds_no_image_and_deploys_no_ecs_stack(self):
        done, head, hashes = self.code_only()
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn(f'code live: yes: the head\'s code is the bundle {self.LIVE[:12]} of deploy.live_code', done.stdout)
        self.assertNotIn('docker build', (self.state / 'calls').read_text())  # 82 s of image that were for nothing
        self.assertEqual(self.stacks_deployed(), [])  # no ECS rollout at all (port keeps its own rule: unchanged here, skipped)
        build = self.build()
        self.assertEqual((build['status'], build['code_live'], build['targets'], build['dirty']), ('succeeded', self.LIVE, ['port'], []))
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), head)
        self.assertEqual([step['n'] for step in build['steps']], ['classify', 'code-live', 'lambda-package'])  # the whole cycle
        self.assertNotIn('smoked', done.stdout)  # nothing changed: nothing to smoke
        self.assertEqual((build['hashes']['service'], build['hashes']['runner']), (hashes['service'], hashes['runner']))
        self.assertNotIn('rolling', build)

    def test_a_change_of_the_owner_s_step_builds_the_image_though_the_bundle_is_live(self):
        # OWNER-STEP-NEEDS-ROLLOUT: dbinit.py runs from the image in the init container: only a new image and a rollout run it
        done, head, hashes = self.code_only(files={'infra__service__tower_infra__dbinit.py': 'a new owner step\n'})
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertNotIn('code live: yes', done.stdout)
        self.assertIn('docker build', (self.state / 'calls').read_text())

    def test_a_change_of_the_task_s_supervisor_builds_the_image_though_the_bundle_is_live(self):
        # SUPERVISOR-NEEDS-ROLLOUT: supervisor.py is the container's first process, on the image's code for the task's
        # whole life: a bundle puts none of it to work (SUCCESSOR-LOST changed it, and its children would have talked
        # to a supervisor that never heard of the signal)
        done, head, hashes = self.code_only(files={'infra__service__tower_infra__supervisor.py': 'a new supervisor\n'})
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertNotIn('code live: yes', done.stdout)
        self.assertIn('docker build', (self.state / 'calls').read_text())

    def test_code_live_beside_a_port_stack_change_builds_no_image_and_applies_the_port_stack_alone(self):
        # CODE-BESIDE-PORT: #509 changed one property of the port stack with the code: an image build, two ECS rollouts and a
        # verification build, 8 min; the code is live by the swap or in place, and only the port stack is this build's
        done, head, hashes = self.code_only(files={'infra__service__tower_infra__runner.py': 'new code\n',
                                                   'infra__aws__stacks__40-port.json': 'changed\n'})
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn('code live: yes', done.stdout)
        self.assertNotIn('docker build', (self.state / 'calls').read_text())
        self.assertEqual(self.stacks_deployed(), ['port'])
        build = self.build()
        self.assertEqual((build['status'], build['code_live'], set(build['targets'])), ('succeeded', self.LIVE, {'port'}))
        self.assertEqual(self.recorded('/tower/deploy/last-sha'), head)
        self.assertNotIn('rolling', build)  # no rollout started: no verification build after this one
        self.assertEqual((build['hashes']['service'], build['hashes']['runner']), (hashes['service'], hashes['runner']))
        self.assertNotEqual(build['hashes']['port'], hashes['port'])

    def test_a_code_only_landing_of_a_module_the_lambdas_hold_too_deploys_no_stack_at_all(self):
        """The port's and the consumer's packages hold live_image.py: the landing swapped both aliases (the classifier names
        every Lambda whose package holds a changed module), so the port stack is left alone too (DEP7-PORT-FAST-OWNED) and
        the slow cycle of the landing is its three short steps."""
        swaps = [self.swap(), self.swap('tower-port-webhook-consumer', 'web1', version='7', to_version='7')]
        done, head, _ = self.code_only(status={'fast': swaps}, files={'infra__service__tower_infra__live_image.py': 'new code\n'},
                                       port=True, DEPLOY_LAMBDA_PACKAGE_CMD="echo '" + json.dumps(self.keys(web='web1')) + "'")
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertIn('code live by the fast path (tower-port-api v12, tower-port-webhook-consumer v7)', done.stdout)
        self.assertEqual(self.stacks_deployed(), [])
        build = self.build()
        self.assertEqual([step['n'] for step in build['steps']], ['classify', 'code-live', 'lambda-package'])
        self.assertEqual((build['status'], build['dirty'], self.recorded('/tower/deploy/last-sha')), ('succeeded', [], head))
    def test_a_code_only_landing_that_is_not_proven_live_and_durable_is_deployed_as_before_1(self):
        self._test_a_code_only_landing_that_is_not_proven_live_and_durable_is_deployed_as_before(0)

    def test_a_code_only_landing_that_is_not_proven_live_and_durable_is_deployed_as_before_2(self):
        self._test_a_code_only_landing_that_is_not_proven_live_and_durable_is_deployed_as_before(1)

    def test_a_code_only_landing_that_is_not_proven_live_and_durable_is_deployed_as_before_3(self):
        self._test_a_code_only_landing_that_is_not_proven_live_and_durable_is_deployed_as_before(2)

    def test_a_code_only_landing_that_is_not_proven_live_and_durable_is_deployed_as_before_4(self):
        self._test_a_code_only_landing_that_is_not_proven_live_and_durable_is_deployed_as_before(3)

    def _test_a_code_only_landing_that_is_not_proven_live_and_durable_is_deployed_as_before(self, part):
        other = f"{'0' * 64}@{'1' * 40}"
        cases = (
            ('another bundle is the live code', {'status': {'live_code': other}}, 'deploy.live_code is'),
            ('no live code written', {'status': {'live_code': ''}}, 'deploy.live_code is not readable'),
            ('the status cannot be read', {'DEPLOY_FAST_STATUS_CMD': 'exit 1'}, 'deploy.live_code is not readable'),
            ('the runner did not reload it', {'status': {'image_reload': [{'role': 'service', 'digest': self.LIVE, 'state': 'reloaded'},
                                                                         {'role': 'runner', 'digest': self.LIVE, 'state': 'started'}]}},
             'was not reloaded in place by the ECS task of both roles (reloaded: service)'),
            ('a reload of another bundle', {'status': {'image_reload': [{'role': role, 'digest': '0' * 64, 'state': 'reloaded'}
                                                                       for role in ('service', 'runner')]}}, 'reloaded: none'),
            ('the runner\'s definition saw the datum: a new task boots its own code', {'runner': {'LiveSeen': 'DATUM'}}, 'tower-app-runner would not boot'),
            ('stamped unknown', {'service': {'LiveSeen': 'unknown'}}, 'tower-app-service would not boot'),
            ('a stack from before the stamp', {'service': {'LiveSeen': None}}, 'tower-app-service would not boot'),
            ('a stack that is not complete', {'runner': {'status': 'UPDATE_ROLLBACK_COMPLETE'}}, 'tower-app-runner would not boot'),
            ('the two stacks carry different code', {'service': {'LiveCode': '0' * 64}}, 'different LiveCode'),
            ('the digest of the head is unknown', {'DEPLOY_CODE_DIGEST_CMD': 'exit 1'}, 'digest of the head\'s code bundle is unknown'),
            ('not code-only: the image itself changes', {'files': {'infra__service__tower_infra__runner.py': 'new\n',
                                                                    'infra__service__Dockerfile': 'z\n'}}, 'targets:'))
        for label, how, line in cases[part::4]:  # DEPLOY-SHARDS-BY-SECONDS: one part of 4
            with self.subTest(label):
                self.setUp()
                done, head, _ = self.code_only(**how)
                self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
                self.assertIn(line, done.stdout)
                self.assertNotIn('code live: yes', done.stdout)
                self.assertIn('docker build', (self.state / 'calls').read_text())
                self.assertNotIn('code_live', self.build())
                if line != 'targets:':  # CODE-LIVE-RELATIVE-ROOT: the reason is in the record, which the status serves whole
                    self.assertIn(line, self.build()['code_live_why'])
                self.assertEqual(self.build()['targets'], ['service', 'port', 'runner'])  # the two stacks are the batch's again

    def test_the_default_digest_command_works_from_inside_a_relative_repo(self):
        # CODE-LIVE-RELATIVE-ROOT: the real build's $repo is the relative `repo` and code_live runs inside it; `--root $repo`
        # looked for repo/repo, the digest was always unknown and no code-only landing was ever skipped live (#496, 11/11)
        script = (ROOT / 'infra/aws/deploy.sh').read_text()
        self.assertIn('repo="${DEPLOY_REPO:-repo}"', script)
        self.assertIn('cd "$repo" && TOWER_ARTIFACT_BUCKET= bash -c "${DEPLOY_CODE_DIGEST_CMD:-python3 '
                      '$ctl/scripts/lib/lambda_package.py code --root .}"', script)
        with tempfile.TemporaryDirectory() as folder:
            os.symlink(ROOT, Path(folder) / 'repo')
            done = subprocess.run(['bash', '-c', f'cd repo && TOWER_ARTIFACT_BUCKET= python3 {ROOT}/scripts/lib/lambda_package.py '
                                   'code --root .'], cwd=folder, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertRegex(json.loads(done.stdout.strip().splitlines()[-1])['sha256'], '^[0-9a-f]{64}$')

    def test_the_real_templates_that_carry_an_ecs_service_are_the_service_and_the_runner(self):
        found = sorted(path.stem.split('-', 1)[1] for path in (ROOT / 'infra/aws/stacks').glob('*.json')
                       if '"AWS::ECS::Service"' in path.read_text())
        self.assertEqual(found, ['runner', 'service'])  # what deploy.sh's grep finds: the stacks whose rollout is not waited


for _name in dir(DeployShTests):  # the rig is inherited; the tests of DeployShTests are not run twice
    if _name.startswith('test_') and _name not in SlowPathShTests.__dict__:
        setattr(SlowPathShTests, _name, None)



# DEPLOY-TEST-SHARDS: this module in three checks, each on a slot of its own (DEPLOY_TEST_SHARD); without the variable (a
# local run, a class or a test by name) nothing is left out
SHARD = 'DEPLOY_TEST_SHARD'
SHARDS = ('slow-a', 'slow-b', 'slow-c')
# DEPLOY-SHARDS-BY-SECONDS: each test's seconds (a local run, 13/11), so the parts are filled longest first, each into the
# lightest: every third by name gave #639's parts 190.5, 169.5 and 125.1 s on the runner. Three, not four (RECORD-ONE-JQ):
# the tests are CPU-bound on the runner's two vCPUs, and four parts took ~200 s each in #640, with every other check
# waiting for a slot until 201 s
SECONDS = ROOT / 'scripts' / 'tests' / 'deploy_sh_seconds.json'

SLOW = (DeployShTests, SlowPathShTests)


def seconds():
    try:
        return json.loads(SECONDS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def assignment():
    """{test: part}: longest first into the lightest part; a test with no seconds yet counts as the median one."""
    names = sorted(f'{kind.__name__}.{name}' for kind in SLOW for name in unittest.TestLoader().getTestCaseNames(kind))
    known = seconds()
    measured = sorted(known.values())
    default = measured[len(measured) // 2] if measured else 1.0
    loads, parts = dict.fromkeys(SHARDS, 0.0), {}
    for name in sorted(names, key=lambda each: (-known.get(each, default), each)):
        part = min(SHARDS, key=lambda shard: (loads[shard], SHARDS.index(shard)))
        parts[name], loads[part] = part, loads[part] + known.get(name, default)
    return parts


ASSIGNED = []


def shard_of(case):
    """The part a test runs in (DEPLOY-SHARDS-BY-SECONDS), across both classes."""
    if not ASSIGNED:
        ASSIGNED.append(assignment())
    return ASSIGNED[0][f'{type(case).__name__}.{case._testMethodName}']


def cases(suite):
    for each in suite:
        if isinstance(each, unittest.TestSuite):
            yield from cases(each)
        else:
            yield each


def load_tests(loader, tests, pattern):
    shard = os.environ.get(SHARD, '')
    if not shard:
        return tests
    if shard not in SHARDS:
        raise ValueError(f'{SHARD} is {shard!r}, not one of {SHARDS}')
    return unittest.TestSuite(case for case in cases(tests) if not isinstance(case, SLOW) or shard_of(case) == shard)


class ShardTests(unittest.TestCase):
    def test_every_test_runs_in_exactly_one_part_and_the_wrappers_name_the_three(self):
        with mock.patch.dict(os.environ, {SHARD: ''}):
            every = [case for case in cases(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__], pattern=None))
                     if isinstance(case, SLOW)]
        parts = {}
        for shard in SHARDS:
            with mock.patch.dict(os.environ, {SHARD: shard}):
                parts[shard] = [case.id() for case in cases(load_tests(None, unittest.TestSuite(every), None))]
        self.assertEqual(sorted(sum(parts.values(), [])), sorted(case.id() for case in every))  # none twice, none left out
        # DEPLOY-SHARDS-BY-SECONDS: the heaviest part is over the lightest by less than the longest test
        known = seconds()
        load = {shard: sum(known.get(name.split('.', 1)[1], 0) for name in names) for shard, names in parts.items()}
        self.assertLess(max(load.values()) - min(load.values()), max(known.values()))
        self.assertEqual(set(known), {case.id().split('.', 1)[1] for case in every})  # every test has its seconds
        with mock.patch.dict(os.environ, {SHARD: 'half'}), self.assertRaises(ValueError):
            load_tests(None, unittest.TestSuite(), None)
        named = {}
        for script in sorted((ROOT / 'scripts/tests').glob('deploy-slow-*.test.sh')):
            text = script.read_text(encoding='utf-8')
            self.assertIn('test_deploy_sh.py', text)
            named[script.name] = re.search(SHARD + r'=([a-z-]+)', text).group(1)
        self.assertEqual(named, {f'deploy-{shard}.test.sh': shard for shard in SHARDS})
        for script in named:  # selected by the deploy's files, never by a module of the engine
            covers = json.loads((ROOT / 'scripts/tests/covers' / script.replace('.test.sh', '.json')).read_text(encoding='utf-8'))
            self.assertIn('infra/aws/deploy.sh', covers['covers'])
            self.assertIn('scripts/tests/test_deploy_sh.py', covers['covers'])
            self.assertFalse([path for path in covers['covers'] if path.startswith('infra/service/')], script)


if __name__ == '__main__':
    unittest.main()
