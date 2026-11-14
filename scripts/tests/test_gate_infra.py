"""The gate over the infrastructure (engine-gate-infra; GATE-INFRA 2, P5 F2).

scripts/gate-check is one check of the gate as the command of a check job: a stage the container judges alone, or one
script test through the gate's hermetic runner; it refuses what it does not know, by name, and `pr metadata`, which
reads the forge with management's credential, is never a check job.

The adapter (scripts/lib/gate_infra.py) is proved end to end in shadow on the real infrastructure in process: its port
(http_port on a throwaway database of the toolchain's PostgreSQL, TI1), its dispatcher, the container runner on a forge
on the disk with a stub gate-check and setup, and the forge executor on a stub of the origin CLI. A head whose checks
pass would land and nothing merges; a red check cancels the landing and names itself; a head that moved is named; a red
pr metadata is red; the same tree on a new head comes from the cache; the same head judged again answers from the jobs
it made; landed for real, the forge makes the merge commit; land cancels a late landing and refuses without a port. A
head that predates gate-check is judged by a later commit's copy on its own tree, and a check the runner could not
prepare stays unprepared when judged again (GATE-INFRA 7). The plan is the gate's own, the jobs are what the rules say,
and with no port nothing is judged. No network.
"""
import base64
import contextlib
from datetime import datetime
import io
from http import HTTPStatus
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
CHECK = ROOT / 'scripts' / 'gate-check'
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from infra_db.psql import migrated  # noqa: E402
import test_db  # noqa: E402
from test_infra_forge import STUB  # noqa: E402  the origin CLI's stub
from runner_world import Forge, git  # noqa: E402  a forge on the disk
from tower_infra import container, forge, http_port, mechanisms, port, runner  # noqa: E402
import config  # noqa: E402
import gate_infra  # noqa: E402
import gate_policy  # noqa: E402

URL = os.environ.get('TEST_DATABASE_URL', '')
KEY = b'the-signing-key-of-the-runner'
QUICK = float('0.05')
STUB_CHECK = """#!/usr/bin/env sh
# the test's gate-check: green, unless the head lists the check in red-checks
echo "checked: $*"
if [ -f red-checks ] && grep -qxF "$2" red-checks; then exit 1; fi
"""
PLAN = {'kind': 'scoped', 'stages': ['pr metadata', 'no GitHub Actions workflows', 'schema compat'],
        'tests': ['scripts/tests/a-check.test.sh'], 'reason': 'the test\'s plan'}
MOVED = '89abcdef0123456789abcdef0123456789abcdef'
PORT_URL = '://'.join(('https', 'port.example.invalid'))  # a port nobody answers: the test's opener does
TODAY = 'the-day-of-the-test'  # the structure check's age rules read the day; the test injects it
SINCE = datetime.fromisoformat('2000-01-01T00:00:00+00:00')  # and the clock the first read of the log starts from
AFTER = datetime.fromisoformat('2100-01-01T00:00:00+00:00')  # a read of the log after every event of the test
# A head before GATE-INFRA 2: selection code of its own, no adapter, a registry with none of today's keys
OLD_SELECTION = {
    'scripts/lib/config.py': 'def get(name, root=None):\n    raise KeyError(name)',
    'scripts/lib/gate_policy.py': "PREREQUISITES = ['pr metadata']\n\n\ndef changed_paths(root, base, head):\n"
                                  "    return ['docs/a.md']\n\n\ndef select_dev_plan(paths, base, head, root=None):\n"
                                  "    return {'kind': 'the head', 'stages': ['pr metadata', 'script tests']}",
    'scripts/lib/gate_script_tests.py': "def select_plan(plan):\n"
                                        "    return ['scripts/tests/only-in-the-head.test.sh'], 'the head chose it'",
    'scripts/lib/gate_test_cache.py': "def key(script, root, hashes=None):\n    return 'the key of the head'"}
# GATE-INFRA 9: a head whose test cache has the box's own selection is planned by it (it leaves out a deleted test)
OWN_SELECTION = {**OLD_SELECTION, 'scripts/lib/gate_test_cache.py': (
    "def key(script, root, hashes=None):\n    return 'the key of the head'\n\n\n"
    "def selection(paths, base, root):\n    return ['scripts/tests/the-boxs-own.test.sh'], 'the box chose it'")}


def gate_check(*args):
    return subprocess.run([str(CHECK), *args], cwd=ROOT, capture_output=True, text=True, check=False)


class GateCheck(unittest.TestCase):
    def test_a_stage_the_container_judges_alone_runs_here(self):
        done = gate_check('stage', 'no GitHub Actions workflows')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def test_a_copy_outside_the_tree_judges_the_tree_gate_check_root_names(self):
        # GATE-INFRA 7: a head that predates scripts/gate-check is judged by a later commit's copy, run from outside it
        environ = {name: value for name, value in os.environ.items() if name != 'GATE_CHECK_ROOT'}
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'gate-check'
            copy.write_bytes(CHECK.read_bytes())
            for root, code in ((str(ROOT), 0), (None, 1)):  # alone, the copy looks for its tree around itself
                done = subprocess.run(['bash', str(copy), 'stage', 'no GitHub Actions workflows'], cwd=ROOT,
                                      env=dict(environ, **({'GATE_CHECK_ROOT': root} if root else {})),
                                      capture_output=True, text=True, check=False)
                self.assertEqual(min(done.returncode, 1), code, done.stdout + done.stderr)

    def test_a_batch_of_tests_runs_in_one_check_and_answers_each_ones_verdict(self):
        # FULL-RUN-BATCH: the base's full run runs its tests in batches, one `gate-check tests` each, and reads each test's
        # PASS or FAIL in the runner's answer file
        with tempfile.TemporaryDirectory() as tmp:
            answer = Path(tmp) / 'answer.json'
            names = 'scripts/tests/checks.test.sh,scripts/tests/infra-prune.test.sh'
            done = subprocess.run(['bash', str(CHECK), 'tests', names], cwd=ROOT, capture_output=True, text=True, check=False,
                                  env=dict(os.environ, TOWER_ANSWER_FILE=str(answer), GATE_TEST_CACHE_OFF='1'))
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr[-2000:])
            self.assertEqual(json.loads(answer.read_text()), {'tests': {name: 'PASS' for name in names.split(',')}})
        refused = subprocess.run(['bash', str(CHECK), 'tests', 'scripts/tests/checks.test.sh,../etc/x.sh'], cwd=ROOT,
                                 capture_output=True, text=True, check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn('no script test ../etc/x.sh', refused.stderr)

    def test_a_batch_killed_between_two_tests_has_answered_the_one_that_ended(self):
        # FULL-RUN-KEEP: a batch taken back for a gate (the runner kills its process group) keeps the verdict of each test
        # that ended: the answer file is rewritten whole as each one ends, not only at the batch's end
        import signal
        with tempfile.TemporaryDirectory() as tmp:
            answer = Path(tmp) / 'answer.json'
            names = 'scripts/tests/checks.test.sh,scripts/tests/infra-prune.test.sh'
            batch = subprocess.Popen(['bash', str(CHECK), 'tests', names], cwd=ROOT, start_new_session=True,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     env=dict(os.environ, TOWER_ANSWER_FILE=str(answer), GATE_TEST_CACHE_OFF='1',
                                              GATE_TEST_WORKERS='1'))
            try:
                while not answer.exists():  # no clock of its own (hermetic): the check's wait is the pause
                    try:
                        batch.wait(timeout=0.05)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                said = json.loads(answer.read_text())
            finally:
                if batch.poll() is None:
                    os.killpg(batch.pid, signal.SIGKILL)
                batch.wait()
            self.assertEqual(len(said['tests']), 1)  # read as the first one ended, the second still running (seconds each)
            self.assertTrue(set(said['tests']) <= set(names.split(',')))
            self.assertEqual(set(said['tests'].values()), {'PASS'})
            self.assertFalse(Path(f'{answer}.part').exists())  # renamed over it, never half written

    def test_a_test_check_loads_none_of_the_stages_functions(self):
        # CHECK-ENVELOPE: gate-runner.sh (its gate-budget.sh reads gate.ceiling_s through Python) only for a stage
        done = subprocess.run(['bash', '-x', str(CHECK), 'test', 'scripts/tests/checks.test.sh'], cwd=ROOT,
                              capture_output=True, text=True, check=False)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr[-2000:])
        self.assertNotIn('gate-runner.sh', done.stderr)
        staged = subprocess.run(['bash', '-x', str(CHECK), 'stage', 'no GitHub Actions workflows'], cwd=ROOT,
                                capture_output=True, text=True, check=False)
        self.assertIn('gate-runner.sh', staged.stderr)

    def test_the_plan_is_answered_to_the_runner_with_the_paths(self):
        # PLAN-ON-RUNNER: the head's own adapter plans base...HEAD in the runner's checkout and answers {plan, paths}
        with tempfile.TemporaryDirectory() as tmp:
            answer = Path(tmp) / 'answer.json'
            done = subprocess.run([str(CHECK), 'plan', 'checks', '--base', 'HEAD~1'], cwd=ROOT, capture_output=True, text=True,
                                  check=False, env={**os.environ, 'TOWER_ANSWER_FILE': str(answer)})
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr[-2000:])
            said = json.loads(answer.read_text())
        self.assertIn('structure check', said['plan']['stages'])
        self.assertEqual(said['paths'], [each for each in subprocess.run(
            ['git', '-C', str(ROOT), 'diff', '--no-renames', '--name-only', 'HEAD~1...HEAD'], capture_output=True,
            text=True, check=True).stdout.split('\n') if each])

    def test_the_pregate_answers_the_very_jobs_the_delivery_makes(self):
        # PRE-GATE: the same input_digest each, so the port's cache answers the delivery with the pre-gate's runs
        base = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD~1'], capture_output=True, text=True, check=True).stdout.strip()
        head = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
        with tempfile.TemporaryDirectory() as tmp:
            answer = Path(tmp) / 'answer.json'
            done = subprocess.run([str(CHECK), 'plan', 'jobs', '--base', base], cwd=ROOT, capture_output=True, text=True,
                                  check=False, env={**os.environ, 'TOWER_ANSWER_FILE': str(answer)})
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr[-2000:])
            said = json.loads(answer.read_text())
        trees = {name: subprocess.run(['git', '-C', str(ROOT), 'rev-parse', f'{sha}^{{tree}}'], capture_output=True,
                                      text=True, check=True).stdout.strip() for name, sha in (('head', head), ('base', base))}
        spec = {'repo': gate_infra.config.get('forge-events.repo'), 'pr': '7', 'head': head, 'base': base, 'ref': 'units/x'}
        delivered = {name: body['input_digest'] for name, body in gate_infra.checks(
            spec, gate_infra.fast_plan(said['plan'], ROOT, base, head), trees,
            gate_infra.datetime.now(gate_infra.timezone.utc).date().isoformat())}  # the day the pre-gate ran
        pregated = {each['name']: each['body']['input_digest'] for each in said['jobs']}
        self.assertEqual(pregated, delivered)
        self.assertTrue(all(each['body']['idempotency_key'].startswith(f'pregate:{head}:') for each in said['jobs']))

    def test_pr_metadata_is_never_a_check_job(self):
        done = gate_check('stage', 'pr metadata')
        self.assertEqual(done.returncode, 1)
        self.assertIn('pr metadata runs beside the adapter', done.stderr)

    def test_what_it_does_not_know_is_refused(self):
        for args in ((), ('stage',), ('stage', 'a stage of nobody'), ('test', 'scripts/lib/config.py'),
                     ('test', 'scripts/tests/nothing-here.test.sh'), ('a-kind', 'x'),
                     ('stage', 'structure check', '--an-option')):
            done = gate_check(*args)
            self.assertEqual(done.returncode, 1, args)
            self.assertRegex(done.stderr, '^(usage|gate-check: no )', args)

    def test_the_stages_are_the_gates_always_stages(self):
        import sys
        sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
        import gate_policy
        text = CHECK.read_text(encoding='utf-8')
        here = [stage for stage in gate_policy.PREREQUISITES if f'"{stage}")' in text]
        self.assertEqual(here, [stage for stage in gate_policy.PREREQUISITES if stage != 'pr metadata'])


class Answer:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Shadow(unittest.TestCase):
    def setUp(self):
        self.name, self.db = migrated(URL)
        self.addCleanup(test_db.destroy, URL, self.name)
        for method, path, token, body in (
                ('POST', '/v1/tenants', 'installation', {'name': 'torre', 'token_sha256': port.sha256('torre')}),
                ('POST', '/v1/executors', 'installation', {'name': 'fargate-runner', 'adapter': 'container'}),
                ('PUT', '/v1/executors/fargate-runner/capacity/spot', 'installation', {'slots': '1'}),
                ('POST', '/v1/executors', 'installation', {'name': 'origin-forge', 'adapter': 'forge'}),
                ('PUT', '/v1/executors/origin-forge/capacity/origin', 'installation', {'slots': '1'}),
                ('PUT', '/v1/queues/checks', 'torre', {'policy': 'fifo'}),
                ('PUT', '/v1/queues/land', 'torre', {'policy': 'fifo'})):
            self.call(method, path, body, token)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.forged = Forge(self.tmp)
        base = self.forged.commit({'scripts/gate-check': STUB_CHECK, 'docs/a.md': 'the base'})
        (self.forged.work / 'scripts' / 'gate-check').chmod(stat.S_IRWXU)
        git('-C', str(self.forged.work), 'commit', '--quiet', '-am', 'the stub is executable')
        git('-C', str(self.forged.work), 'push', '--quiet', '--force', str(self.forged.bare), 'HEAD:refs/heads/base')
        base = git('-C', str(self.forged.work), 'rev-parse', 'HEAD')
        head = self.forged.commit({'docs/a.md': 'the head'}, branch='feature')
        self.spec = {'repo': gate_infra.config.get('forge-events.repo'), 'pr': '7', 'head': head, 'base': base,
                     'ref': 'feature', 'base_ref': 'mod/roadmap-integration'}
        box = container.Container(self.tmp / 'runner', forge_url=self.forged.url(),
                                  environ=dict(os.environ, SETUP_LOG=str(self.tmp / 'setup.log')))
        self.runner = runner.Runner(self.db, box.fetch, box.prepare, box.upload, box.workdir, renew_every_s=QUICK,
                                    checkout_of=box.checkout_of, signing_key=lambda: KEY)
        cli = self.tmp / 'origin'
        cli.write_text(STUB)
        cli.chmod(stat.S_IRWXU)
        self.stub_log = self.tmp / 'calls.jsonl'
        self.environ = {name: value for name, value in os.environ.items()
                        if name not in ('CURSOR_API_KEY', 'CURSOR_AUTH_TOKEN')}
        self.environ.update(STUB_LOG=str(self.stub_log), STUB_HEAD=head, STUB_MERGE=head, STUB_STATUS='open')
        self.origin = forge.OriginForge(cli=str(cli), environ=self.environ, credential=lambda: 'key-of-the-test')
        self.port = gate_infra.Port(None, 'torre', call=lambda method, path, body=None: self.call(method, path, body))

    def call(self, method, path, body=None, token='torre'):
        answer = http_port.handle({'rawPath': path, 'requestContext': {'http': {'method': method}},
                                   'headers': {'Authorization': f'Bearer {token}'}, 'body': json.dumps(body or {})},
                                  self.db, port.sha256('installation'))
        if answer['statusCode'] >= HTTPStatus.BAD_REQUEST:
            raise gate_infra.Refused(answer['statusCode'], answer['body'])
        return json.loads(answer['body'])

    def step(self, _seconds=None):
        """What the service and the runner do between two reads of the log: dispatch, land, run the checks."""
        for run in mechanisms.dispatch(self.db):
            if run.get('adapter') == 'forge':
                ended = self.origin.start(run)
                mechanisms.end(self.db, run['run'], run['fence'], ended['outcome'], ended.get('error'),
                               ended.get('result'))
        while self.runner.once() is not None:
            pass

    def judge(self, spec=None, metadata=None, progress=None):
        spec = spec or self.spec
        trees = {name: git('-C', str(self.forged.work), 'rev-parse', f'{spec[name]}^{{tree}}')
                 for name in ('head', 'base')}
        return gate_infra.judge(self.port, spec, PLAN, trees, TODAY, shadow=True, now=SINCE,
                                metadata=metadata or (lambda: (True, 'pr metadata: green')), sleep=self.step,
                                progress=progress)

    def calls(self):
        return [json.loads(line) for line in self.stub_log.read_text().splitlines()] if self.stub_log.exists() else []

    def test_a_head_whose_checks_pass_would_land_in_shadow_and_nothing_merges(self):
        reads = []  # TRAIN-LEASE-IN-JUDGMENT: the judgment says it goes on each time it reads the log, until it decides
        verdict = self.judge(progress=lambda: reads.append(1))
        self.assertGreaterEqual(len(reads), 1)
        self.assertEqual((verdict['verdict'], verdict['red'], verdict['checks']),
                         ('green', [], len(PLAN['stages']) - 1 + len(PLAN['tests'])))  # pr metadata is no job
        self.assertEqual(verdict['unprepared'], [])
        phases = verdict['phases']  # where the wall time went, kept with every verdict (AWS2)
        self.assertLessEqual(phases['created_s'], phases['first_check_s'])
        self.assertLessEqual(phases['first_check_s'], phases['checks_s'])
        self.assertLessEqual(phases['checks_s'], verdict['seconds'])
        self.assertEqual(verdict['box_cached'], [])
        landed = verdict['landing']
        self.assertEqual((landed['state'], landed['result']['would_merge']), ('succeeded', True))
        self.assertGreaterEqual(verdict['ready_to_landed_s'], 0)
        self.assertEqual([[verb, what] for verb, what, *_ in self.calls()], [['pr', 'view']])  # a dry run

    def test_the_plan_comes_from_the_runner_first_and_the_lane_plans_without_its_answer(self):
        # PLAN-ON-RUNNER: a job first in the checks' queue answers the plan; the lane plans when there is no answer
        class PlanPort:
            def __init__(self, states):
                self.states, self.made = list(states), []

            def call(self, method, path, body=None):
                if method == 'POST':
                    self.made.append(body)
                    return {'id': 'plan-job'}
                return self.states.pop(0)
        plan = {'stages': ['structure check'], 'tests': ['scripts/tests/a.test.sh'], 'artifacts': []}
        lambda_path = 'infra/service/tower_infra/http_port.py'
        port = PlanPort([{'state': 'running'}, {'state': 'succeeded', 'result': {'answer': {'plan': dict(plan), 'paths': [lambda_path]}}}])
        got, seconds = gate_infra.planned(port, self.spec, sleep=lambda _: None)
        self.assertEqual((got['tests'], got['artifacts'], seconds >= 0), (plan['tests'], ['lambda'], True))
        made = port.made[0]
        self.assertEqual(made['rank'], gate_infra.RANK_PER_CHECK * gate_infra.RANK_CAP)  # before any check of any head
        command = json.loads(base64.b64decode(made['input_uri'].split(',', 1)[1]))['command']
        self.assertEqual(command[-4:], ['plan', 'checks', '--base', self.spec['base']])
        for states, why in (([{'state': 'failed', 'result': {}}], 'ended failed'),
                            ([{'state': 'succeeded', 'result': {'answer': {'refused': 'too large'}}}], 'too large'),
                            ([{'state': 'succeeded', 'result': {}}], 'ended succeeded')):
            got, said = gate_infra.planned(PlanPort(states), self.spec, sleep=lambda _: None)
            self.assertIsNone(got)
            self.assertIn(why, said)
        self.assertEqual(gate_infra.planned(object(), self.spec)[0], None)  # no port to ask: the lane plans

    def test_the_heads_checks_are_made_in_one_call_and_a_port_without_the_route_makes_them_one_by_one(self):
        # JOBS-BATCH: made four at a time, the checks reached the port's Lambda on cold instances (#636: 9.9 s for 39)
        real, asked = self.call, []

        def call(method, path, body=None, token='torre'):
            asked.append((method, path))
            return real(method, path, body, token)
        self.call = call
        verdict = self.judge()
        checks = len(PLAN['stages']) - 1 + len(PLAN['tests'])
        self.assertEqual((verdict['verdict'], verdict['checks']), ('green', checks))
        self.assertEqual(asked.count(('POST', '/v1/jobs/batch')), 1)
        self.assertEqual(asked.count(('POST', '/v1/jobs')), 1)  # the landing alone

        def older(method, path, body=None, token='torre'):
            if path == '/v1/jobs/batch':
                raise gate_infra.Refused(HTTPStatus.NOT_FOUND, '{"error": "no route POST /v1/jobs/batch"}')
            asked.append((method, path))
            return real(method, path, body, token)
        self.call, asked[:] = older, []
        again = self.judge(spec=dict(self.spec, round='older-port'))
        self.assertEqual(again['verdict'], 'green')
        self.assertEqual(asked.count(('POST', '/v1/jobs')), checks + 1)
        for body in ({}, {'jobs': []}, {'jobs': 'x'}, {'jobs': [{}] * 201}):
            with self.assertRaises(gate_infra.Refused) as refused:
                real('POST', '/v1/jobs/batch', body)
            self.assertEqual(refused.exception.status, HTTPStatus.BAD_REQUEST)

    def test_the_wait_polls_fast_only_when_the_verdict_is_seconds_away(self):
        pauses = []
        real_step = self.step

        def watched(seconds=None):
            pauses.append(seconds)
            real_step(seconds)
        trees = {name: git('-C', str(self.forged.work), 'rev-parse', f'{self.spec[name]}^{{tree}}')
                 for name in ('head', 'base')}
        gate_infra.judge(self.port, self.spec, PLAN, trees, TODAY, shadow=True, now=SINCE, sleep=watched,
                         metadata=lambda: (True, ''))
        slow, fast = gate_infra.config.get('gate-infra.poll_s'), gate_infra.config.get('gate-infra.poll_last_s')
        self.assertLess(fast, slow)
        # GATE-POLL (criterion 3): the checks of #688 to #705, all from the cache, ended by 0.5 to 1.0 s and their verdict
        # was read at ~3.0 s, the rest the 2 s between two reads
        self.assertLessEqual((slow, fast), (0.5, 0.25))
        self.assertTrue(pauses and set(pauses) <= {slow, fast}, pauses)
        self.assertEqual(pauses[-1], fast)  # the last wait, on the landing, is the short one

    def test_landed_for_real_the_forge_makes_the_merge_commit(self):
        trees = {name: git('-C', str(self.forged.work), 'rev-parse', f'{self.spec[name]}^{{tree}}')
                 for name in ('head', 'base')}
        verdict = gate_infra.judge(self.port, self.spec, PLAN, trees, TODAY, shadow=False, now=SINCE,
                                   metadata=lambda: (True, ''), sleep=self.step)
        self.assertEqual((verdict['verdict'], verdict['landing']['result']['merge_sha']), ('green', self.spec['head']))
        self.assertIn(['pr', 'merge'], [[verb, what] for verb, what, *_ in self.calls()])

    def test_land_keeps_the_verdict_it_judged_beside_the_shadows(self):
        # GATE-INFRA 10: after the switch no shadow runs, so the real verdict is what medir reads ready to merged from
        judged = {'pr': self.spec['pr'], 'head': self.spec['head'], 'verdict': 'green', 'shadow': False,
                  'ready_to_landed_s': float('1.25'), 'landing': {'id': 'the-landing'}}
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, {'XDG_CACHE_HOME': cache}), \
                mock.patch.object(gate_infra, 'judge', return_value=judged) as judging, \
                mock.patch.object(gate_infra, 'plan_of', return_value=PLAN), \
                mock.patch.object(gate_infra, 'planned', return_value=(None, 'the test plans on the lane')):
            answer = gate_infra.land(self.spec['pr'], self.spec['head'], self.spec['base'], self.spec['ref'],
                                     self.spec['base_ref'], root=self.forged.work, port=self.port,
                                     publisher=mock.Mock())  # hermetic: tower/gate (D-313) never reaches the live forge
            kept = json.loads((Path(cache) / 'the-tower' / 'gate-infra'
                               / f"pr-{self.spec['pr']}-{self.spec['head']}.json").read_text())
        self.assertEqual((answer, kept, judging.call_args.kwargs['shadow']), ((judged, None), judged, False))

    def test_land_holds_the_status_trails_until_the_forge_merged(self):
        # TRAIL-AFTER-LANDING: the trail's push beside the forge's merge made it 7 s (#630, #631)
        import forge_events
        held = []
        judged = {'pr': self.spec['pr'], 'head': self.spec['head'], 'verdict': 'green', 'landing': {'id': 'the-landing'}}
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, {'XDG_CACHE_HOME': cache}), \
                mock.patch.object(gate_infra, 'judge', side_effect=lambda *a, **k: held.append(forge_events.HELD) or judged), \
                mock.patch.object(gate_infra, 'plan_of', return_value=PLAN), \
                mock.patch.object(gate_infra, 'planned', return_value=(None, 'the test plans on the lane')):
            gate_infra.land(self.spec['pr'], self.spec['head'], self.spec['base'], self.spec['ref'], self.spec['base_ref'],
                            root=self.forged.work, port=self.port, publisher=mock.Mock())
        self.assertEqual(held, [[]])
        self.assertIsNone(forge_events.HELD)

    def test_land_cancels_a_late_landing_and_refuses_without_a_port(self):
        asked = []
        port = gate_infra.Port(None, 'torre', call=lambda method, path, body=None: asked.append((method, path)) or {})
        late = {'verdict': 'late', 'landing': {'id': 'the-landing'}}
        self.assertEqual(gate_infra.land('7', 'h', 'b', 'feature', 'base', port=port, judged=late), (late, {}))
        self.assertEqual(asked, [('POST', '/v1/jobs/the-landing/cancel')])
        bare = {name: value for name, value in os.environ.items() if not name.startswith('TOWER_PORT_')}
        with mock.patch.dict(os.environ, bare, clear=True), self.assertRaisesRegex(RuntimeError, 'not configured'):
            gate_infra.land('7', 'h', 'b', 'feature', 'base')

    def test_a_pr_the_box_merged_before_the_dry_run_is_the_shadows_green(self):
        # #301 (04/11): its 35 checks queued behind the backfill, the box merged it first, and the dry run found it
        # merged; that is the race of a slow shadow with the box, not a disagreement on the gate
        self.environ['STUB_STATUS'] = 'merged'
        verdict = self.judge()
        self.assertEqual((verdict['verdict'], verdict['red'], verdict['landing']['landed_by']), ('green', [], 'box'))
        self.assertEqual(verdict['landing']['error'], 'merged')
        self.assertEqual([[verb, what] for verb, what, *_ in self.calls()], [['pr', 'view']])  # once: never retried
        self.assertTrue(gate_infra.merged_already('refused', {'detail': 'the pull request is merged'}))  # the old forge
        self.assertFalse(gate_infra.merged_already('refused', {'detail': 'the pull request is closed'}))

    def test_a_red_check_cancels_the_landing_and_names_itself(self):
        red = self.forged.commit({'red-checks': 'schema compat'}, branch='feature')
        verdict = self.judge(dict(self.spec, head=red))
        self.assertEqual((verdict['verdict'], verdict['red'], verdict['landing']['state']),
                         ('red', ['stage:schema compat'], 'cancelled'))
        self.assertEqual(self.calls(), [])

    def test_a_check_the_runner_could_not_prepare_is_named_unprepared(self):
        # 04/11: every check of the AWS shadow ended not_started (no forge key); the verdict says it was the runner's
        box = container.Container(self.tmp / 'lost', forge_url='://'.join(('file', '/nowhere-of-the-test')),
                                  environ=dict(os.environ, SETUP_LOG=str(self.tmp / 'setup.log')))
        self.runner = runner.Runner(self.db, box.fetch, box.prepare, box.upload, box.workdir, renew_every_s=QUICK,
                                    checkout_of=box.checkout_of, signing_key=lambda: KEY)
        verdict = self.judge()
        self.assertEqual(verdict['verdict'], 'red')
        self.assertTrue(verdict['unprepared'])
        self.assertLessEqual(set(verdict['unprepared']), set(verdict['red']))

    def judge_landing(self, retry=True):
        """The landing path of `land`: the landing held until before_landing has seen the verdict (a fake one: no
        publisher reaches the forge)."""
        trees = {name: git('-C', str(self.forged.work), 'rev-parse', f"{self.spec[name]}^{{tree}}")
                 for name in ('head', 'base')}
        told = mock.Mock()
        verdict = gate_infra.judge(self.port, self.spec, PLAN, trees, TODAY, shadow=False, now=SINCE,
                                   metadata=lambda: (True, ''), sleep=self.step, before_landing=told, retry=retry)
        return verdict, told

    def cold_runner(self, failing):
        """A runner whose first `failing` setups fail as the 09/11 cold task did (not_started on every check)."""
        real, left = self.runner.prepare, [failing]

        def prepare(checkout):
            if left[0]:
                left[0] -= 1
                raise container.Unprepared('setup: toolchain: download failed for python')
            real(checkout)
        self.runner.prepare = prepare  # not retryable here: the runner says not_started at once, the judge retries

    def test_checks_the_runner_could_not_prepare_are_made_again_once_before_the_verdict(self):
        # 09/11 05:49Z: every check of #389 ended not_started within a second and the infrastructure said red on a green head
        self.cold_runner(len(PLAN['tests']) + len(PLAN['stages']) - 1)
        verdict, told = self.judge_landing()
        self.assertEqual((verdict['verdict'], verdict['red'], verdict['unprepared']), ('green', [], []))
        self.assertTrue(verdict['retried'])
        told.assert_called_once()
        self.assertEqual(told.call_args.args[:2], (True, []))  # tower/gate never saw the first, unprepared, try
        self.assertIn(['pr', 'merge'], [[verb, what] for verb, what, *_ in self.calls()])

    def test_the_success_the_hook_hands_back_rides_the_landing_and_is_posted_right_before_the_merge(self):
        # CHECK-IN-LANDING (F4 criterion 3): the publish of tower/gate (a POST to the port, the service's post, the client's
        # 0.5 s poll for its word) was 1.0 to 2.4 s of each delivery on 13/11; the landing job now carries the body and the
        # live service posts it before Origin's merge. The train's front and the publish are measured apart
        posted = []
        self.origin.post_check = lambda check: posted.append((check['headSha'], len(self.calls()))) or {'outcome': 'created'}
        body = {'headSha': self.spec['head'], 'checkSuite': {'key': 'tower'},
                'checkRun': {'key': 'tower/gate', 'status': 'completed', 'conclusion': 'success'}}
        trees = {name: git('-C', str(self.forged.work), 'rev-parse', f"{self.spec[name]}^{{tree}}")
                 for name in ('head', 'base')}
        told = mock.Mock(return_value={'body': body, 'parts': {'front_s': 0.1, 'publish_s': 0.0, 'check_in_landing': True}})
        verdict = gate_infra.judge(self.port, self.spec, PLAN, trees, TODAY, shadow=False, now=SINCE,
                                   metadata=lambda: (True, ''), sleep=self.step, before_landing=told, retry=True)
        self.assertEqual(verdict['verdict'], 'green')
        self.assertEqual(posted, [(self.spec['head'], 0)])  # posted, and before Origin's merge was called
        self.assertIn(['pr', 'merge'], [[verb, what] for verb, what, *_ in self.calls()])
        self.assertEqual((verdict['phases']['front_s'], verdict['phases']['check_in_landing']), (0.1, True))
        (action,) = [forge.decode(uri) for uri, in self.db.rows("select input_uri from work.job where idempotency_key like 'land:%'")]
        self.assertEqual(action['check_run'], body)

    def test_checks_still_unprepared_after_the_second_try_are_red_and_named(self):
        self.cold_runner(len(PLAN['tests']) * 2 + len(PLAN['stages']) * 2)
        verdict, told = self.judge_landing()
        self.assertEqual(verdict['verdict'], 'red')
        self.assertTrue(verdict['retried'] and verdict['unprepared'])
        self.assertEqual(self.calls(), [])  # nothing merged
        told.assert_called_once()

    def test_a_check_that_ran_and_failed_is_red_at_once_and_never_made_again(self):
        red = self.forged.commit({'red-checks': 'schema compat'}, branch='feature')
        self.spec = dict(self.spec, head=red)
        verdict, told = self.judge_landing()
        self.assertEqual((verdict['verdict'], verdict['red'], 'retried' in verdict), ('red', ['stage:schema compat'], False))

    def test_a_merged_head_judged_again_is_decided_by_its_checks_alone(self):
        # GATE-INFRA 5 (P5 F3): a head that merged already has no landing to try; its checks decide the verdict
        trees = {name: git('-C', str(self.forged.work), 'rev-parse', f'{self.spec[name]}^{{tree}}')
                 for name in ('head', 'base')}
        verdict = gate_infra.judge(self.port, dict(self.spec, round='backfill'), PLAN, trees, TODAY, shadow=True,
                                   now=SINCE, sleep=self.step, landing_too=False)
        self.assertEqual((verdict['verdict'], verdict['red'], verdict['landing']['id']), ('green', [], None))
        self.assertEqual(self.calls(), [])  # no landing, not even a dry run
        jobs = self.db.rows("select idempotency_key from work.job where idempotency_key like 'check:%'")
        self.assertTrue(jobs and all(key.endswith(':backfill') for key, in jobs))  # its own round, not the old jobs

    def test_a_head_that_predates_gate_check_is_judged_by_a_later_copy_on_its_own_tree(self):
        # GATE-INFRA 7: with no scripts/gate-check of its own, each check ends not_started, and judged again later (its
        # log events then older than the wait) it still says so; with the base's copy, the head's own tree decides
        (self.forged.work / 'scripts' / 'gate-check').unlink()
        old = self.forged.commit({'red-checks': 'schema compat'}, branch='old')
        spec = dict(self.spec, head=old, ref='old', round='backfill')
        trees = {name: git('-C', str(self.forged.work), 'rev-parse', f'{spec[name]}^{{tree}}') for name in ('head', 'base')}
        every = sorted([f'stage:{stage}' for stage in PLAN['stages'] if stage != 'pr metadata']
                       + [f'test:{test}' for test in PLAN['tests']])
        verdict = gate_infra.judge(self.port, spec, PLAN, trees, TODAY, now=SINCE, sleep=self.step, landing_too=False)
        # red at the first it sees; the jobs are made at once (AWS2), so which one the runner took first is not fixed
        self.assertEqual(verdict['verdict'], 'red')
        self.assertTrue(verdict['unprepared'] and set(verdict['unprepared']) <= set(every))
        for _ in every:
            self.step()  # the others end not_started too
        again = gate_infra.judge(self.port, spec, PLAN, trees, TODAY, now=AFTER, sleep=self.fail, landing_too=False)
        self.assertEqual((again['verdict'], again['unprepared']), ('red', every))
        tooled = gate_infra.judge(self.port, dict(spec, tools=spec['base']), PLAN, trees, TODAY, now=SINCE,
                                  sleep=self.step, landing_too=False)
        self.assertEqual((tooled['verdict'], tooled['red'], tooled['unprepared']), ('red', ['stage:schema compat'], []))

    def test_a_head_that_moved_is_named(self):
        self.environ['STUB_HEAD'] = MOVED
        verdict = self.judge()
        self.assertEqual((verdict['verdict'], verdict['landing']['error']), ('moved', 'head_moved'))

    def test_a_red_pr_metadata_is_red_with_no_job_failing(self):
        verdict = self.judge(metadata=lambda: (False, 'pr metadata: the body has no commit plan'))
        self.assertEqual((verdict['verdict'], verdict['red']), ('red', ['pr metadata']))
        self.assertIn('no commit plan', verdict['metadata'])

    def test_the_same_tree_on_a_new_head_comes_from_the_cache(self):
        self.assertEqual(self.judge()['verdict'], 'green')
        git('-C', str(self.forged.work), 'commit', '--quiet', '--amend', '-m', 'the same tree, another commit')
        git('-C', str(self.forged.work), 'push', '--quiet', '--force', str(self.forged.bare), 'HEAD:refs/heads/feature')
        again = git('-C', str(self.forged.work), 'rev-parse', 'HEAD')
        self.environ['STUB_HEAD'] = again
        verdict = self.judge(dict(self.spec, head=again))
        self.assertEqual((verdict['verdict'], verdict['from_cache']), ('green', verdict['checks']))

    def test_the_same_head_judged_again_answers_from_the_jobs_it_made(self):
        first = self.judge()
        second = gate_infra.judge(self.port, self.spec, PLAN, {'head': 'unused', 'base': 'unused'}, TODAY,
                                  metadata=lambda: (True, ''), sleep=self.fail, now=SINCE)
        self.assertEqual((second['verdict'], second['landing']['id']), ('green', first['landing']['id']))


class Backfill(unittest.TestCase):
    """GATE-INFRA 5 (P5 F3): the last merged heads judged again, beside the box's green verdict on them."""

    def setUp(self):
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        self.enterContext(mock.patch.dict(os.environ, {'XDG_CACHE_HOME': cache.name}))
        self.where = Path(cache.name) / 'the-tower' / 'gate-infra'

    def test_the_merges_of_the_base_give_each_prs_base_and_head(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            git('-C', folder, 'init', '--quiet', '--initial-branch', 'base')
            for name, value in (('user.email', 'test@example.invalid'), ('user.name', 'test')):
                git('-C', folder, 'config', name, value)
            (work / 'a').write_text('base')
            git('-C', folder, 'add', '-A')
            git('-C', folder, 'commit', '--quiet', '-m', 'the base')
            heads = []
            for number in ('7', '8'):
                git('-C', folder, 'checkout', '--quiet', '-b', f'feature-{number}')
                (work / 'a').write_text(number)
                git('-C', folder, 'commit', '--quiet', '-am', f'work of {number}')
                heads.append((number, git('-C', folder, 'rev-parse', 'base'), git('-C', folder, 'rev-parse', 'HEAD')))
                git('-C', folder, 'checkout', '--quiet', 'base')
                git('-C', folder, 'merge', '--quiet', '--no-ff', '-m', f'the change of {number} (#{number})',
                    f'feature-{number}')
            git('-C', folder, 'update-ref', 'refs/remotes/origin/base', 'base')
            self.assertEqual(gate_infra.merged(work, 'base', int('5')), list(reversed(heads)))

    def test_each_head_is_judged_with_checks_only_beside_the_boxs_green_and_a_backfill_resumes(self):
        judged = []

        def judging(port, spec, plan, trees, today, shadow, landing_too):
            judged.append((spec['pr'], spec['round'], spec['ref'], landing_too))
            return {'pr': spec['pr'], 'head': spec['head'], 'verdict': 'green', 'red': [], 'checks': 1,
                    'from_cache': 0, 'seconds': float('1'), 'unprepared': []}
        args = mock.Mock(ref='base', last=int('5'), round='backfill')
        heads = [('8', 'base-8', 'head-8'), ('7', 'base-7', 'head-7')]
        self.where.mkdir(parents=True)
        (self.where / 'pr-7-head-7.json').write_text(json.dumps({'verdict': 'red', 'red': ['stage:lint']}))  # 04/11
        with mock.patch('builtins.print'):
            for _ in ('first', 'again'):
                gate_infra.backfill(args, port=object(), judging=judging, heads=heads, today=TODAY,
                                    planned=lambda base, head: (PLAN, {'head': 'tree', 'base': 'tree'}),
                                    tool_of=lambda head: None)
        self.assertEqual(judged, [('8', 'backfill', 'base', False), ('7', 'backfill', 'base', False)])  # once each
        box = json.loads((self.where / 'box-7-head-7.json').read_text())
        self.assertEqual((box['verdict'], box['source']), ('green', 'merge'))
        self.assertEqual(json.loads((self.where / 'pr-7-head-7.json').read_text())['round'], 'backfill')

    def test_a_head_with_no_gate_check_is_judged_with_the_tips_and_a_round_it_could_not_prepare_again(self):
        # GATE-INFRA 7: #243..#280 predate scripts/gate-check; on 04/11 their checks ended not_started
        judged = []

        def judging(port, spec, plan, trees, today, shadow, landing_too):
            judged.append((spec['pr'], spec.get('tools')))
            return {'pr': spec['pr'], 'head': spec['head'], 'verdict': 'green', 'red': [], 'checks': 1,
                    'from_cache': 0, 'seconds': float('1'), 'unprepared': []}
        args = mock.Mock(ref='base', last=int('5'), round='backfill')
        heads = [('8', 'base-8', 'head-8'), ('7', 'base-7', 'head-7')]
        self.where.mkdir(parents=True)
        for pr, unprepared in (('8', []), ('7', ['stage:lint'])):
            (self.where / f'pr-{pr}-head-{pr}.json').write_text(json.dumps({'verdict': 'red', 'round': 'backfill',
                                                                            'unprepared': unprepared}))
        with mock.patch('builtins.print'):
            gate_infra.backfill(args, port=object(), judging=judging, heads=heads, today=TODAY,
                                planned=lambda base, head: (PLAN, {'head': 'tree', 'base': 'tree'}),
                                tool_of=lambda head: 'the-tip' if head == 'head-7' else None)
        self.assertEqual(judged, [('7', 'the-tip')])  # #8 was judged in its round; #7 could not be
        self.assertEqual(json.loads((self.where / 'pr-7-head-7.json').read_text())['tools'], 'the-tip')

    def test_a_live_verdict_that_judged_its_head_is_kept_and_one_that_could_not_is_judged_again(self):
        self.assertTrue(gate_infra.judged_already({'verdict': 'green', 'unprepared': []}, 'backfill'))
        self.assertFalse(gate_infra.judged_already({'verdict': 'red', 'unprepared': ['stage:lint']}, 'backfill'))
        self.assertFalse(gate_infra.judged_already({'verdict': 'red', 'red': ['stage:lint']}, 'backfill'))  # 04/11
        self.assertFalse(gate_infra.judged_already({'verdict': 'green', 'round': 'backfill'}, 'again'))
        self.assertTrue(gate_infra.judged_already({'verdict': 'red', 'round': 'backfill', 'unprepared': []}, 'backfill'))
        self.assertFalse(gate_infra.judged_already({'verdict': 'red', 'round': 'backfill',
                                                    'unprepared': ['stage:lint']}, 'backfill'))  # GATE-INFRA 7
        self.assertFalse(gate_infra.judged_already(None, 'backfill'))


class Plan(unittest.TestCase):
    def test_a_test_the_boxs_cache_vouches_for_is_no_job_and_a_broken_cache_is_no_shortcut(self):
        # AWS2: the box skips a test whose key its test cache holds; the infrastructure did not, and paid for it
        class Cache:
            def __init__(self, store):
                self.store = store

            def store_location(self):
                if self.store is None:
                    raise OSError('no store')
                return self.store

            def lookup(self, location, key):
                return {'marker': key} if key in location else None
        keys = {'scripts/tests/a.test.sh': 'ka', 'scripts/tests/b.test.sh': 'kb', 'scripts/tests/c.test.sh': ''}
        self.assertEqual(set(gate_infra.box_cached(Cache({'ka'}), keys)), {'scripts/tests/a.test.sh'})
        self.assertEqual(gate_infra.box_cached(Cache(None), keys), {})
        self.assertEqual(gate_infra.box_cached(object(), keys), {})  # a head whose cache has no lookup
        with mock.patch.object(gate_infra.config, 'get', side_effect=lambda name: name != 'gate-infra.box_cache'):
            self.assertEqual(gate_infra.box_cached(Cache({'ka'}), keys), {})
        with mock.patch.object(gate_infra.config, 'get', side_effect=KeyError('gate-infra.box_cache')):
            self.assertEqual(gate_infra.box_cached(Cache({'ka'}), keys), {})  # a head older than the key

    def test_the_longest_test_is_made_first_so_a_slot_takes_it_at_once(self):
        spec = {'repo': 'org/name', 'pr': '7', 'head': 'h', 'base': 'b', 'ref': 'feature'}
        plan = {'stages': ['pr metadata', 'schema compat'], 'tests': ['t/a', 't/b', 't/c'],
                'costs': {'t/b': float('40'), 't/c': float('3')}}
        names = [name for name, _ in gate_infra.checks(spec, plan, {'head': 'th', 'base': 'tb'}, TODAY)]
        # STAGE-RANK-BY-COST; UNMEASURED-MIDDLE: t/a, with no hint, as a test of gate_infra.UNMEASURED_S
        self.assertEqual(names, ['test:t/b', 'test:t/a', 'stage:schema compat', 'test:t/c'])

    def test_a_test_that_needs_uid_0_runs_as_root_from_the_bases_code_not_the_heads(self):
        # UID0-FROM-BASE (the Torre, 13/11 ~14:15 BRT): the uid 0 probe asks for root at the base's commit; every other check
        # is the head's, asking nothing
        spec = {'repo': 'org/name', 'pr': '7', 'head': 'h' * 40, 'base': 'b' * 40, 'ref': 'refs/heads/feature',
                'base_ref': 'mod/roadmap-integration'}
        probe = 'scripts/tests/uid0-probe.test.sh'
        self.assertIn(probe, gate_infra.config.get('gate-infra.root_from_base_tests'))
        plan = {'stages': [], 'tests': [probe, 'scripts/tests/other.test.sh']}
        made = {name: forge.decode(body['input_uri']) for name, body in gate_infra.checks(spec, plan, {'head': 'th', 'base': 'tb'}, TODAY)}
        self.assertEqual({key: made[f'test:{probe}'][key] for key in ('commit', 'ref', 'user')},
                         {'commit': 'b' * 40, 'ref': 'refs/heads/mod/roadmap-integration', 'user': 'root'})
        other = made['test:scripts/tests/other.test.sh']
        self.assertEqual((other['commit'], other['ref'], 'user' in other), ('h' * 40, 'refs/heads/feature', False))

    def test_the_plan_is_the_gates_own_computed_on_the_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            forged = Forge(Path(tmp))
            base = git('-C', str(forged.work), 'rev-parse', 'HEAD')
            head = forged.commit({'docs/a-page.md': 'a page'})
            plan = gate_infra.plan_of(forged.work, base, head)
        self.assertEqual(plan['stages'], gate_policy.PREREQUISITES)
        self.assertEqual(plan['tests'], [])

    def test_a_lambda_only_change_always_plans_the_artifact_job_even_for_a_head_without_the_classifier(self):
        # FAST-ARTIFACT-FIX: #425 changed only http_port.py and got no artifact:lambda job
        with tempfile.TemporaryDirectory() as tmp:
            forged = Forge(Path(tmp))
            base = git('-C', str(forged.work), 'rev-parse', 'HEAD')
            head = forged.commit({**OLD_SELECTION, 'infra/service/tower_infra/http_port.py': 'x = 1'})
            plan = gate_infra.plan_of(forged.work, base, head)
        self.assertEqual(plan['artifacts'], ['lambda'])
        spec = {'repo': 'org/name', 'pr': '7', 'head': 'h', 'base': 'b', 'ref': 'feature'}
        names = [name for name, _ in gate_infra.checks(spec, plan, {'head': 'th', 'base': 'tb'}, TODAY)]
        self.assertIn('artifact:lambda', names)

    def test_the_artifact_job_is_never_memoized_even_when_every_test_is_served_from_the_box_cache(self):
        # FAST-ARTIFACT-NOCACHE: a full cache hit (no test job left) on a fast Lambda target still makes the artifact job
        with tempfile.TemporaryDirectory() as tmp:
            forged = Forge(Path(tmp))
            base = git('-C', str(forged.work), 'rev-parse', 'HEAD')
            head = forged.commit({**OLD_SELECTION, 'infra/service/tower_infra/http_port.py': 'x = 1'})
            plan = dict(gate_infra.plan_of(forged.work, base, head), tests=[], box_cached=['scripts/tests/a.test.sh'])
        spec = {'repo': 'org/name', 'pr': '7', 'head': 'h', 'base': 'b', 'ref': 'feature'}
        made = dict(gate_infra.checks(spec, plan, {'head': 'th', 'base': 'tb'}, TODAY))
        self.assertIn('artifact:lambda', made)
        self.assertFalse(made['artifact:lambda']['memoize'])
        self.assertTrue(all(body['memoize'] for name, body in made.items() if not name.startswith('artifact:')))
        docs = dict(plan, artifacts=[])
        self.assertNotIn('artifact:lambda', dict(gate_infra.checks(spec, docs, {'head': 'th', 'base': 'tb'}, TODAY)))

    def test_a_docs_change_plans_no_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            forged = Forge(Path(tmp))
            base = git('-C', str(forged.work), 'rev-parse', 'HEAD')
            head = forged.commit({'docs/a-page.md': 'a page'})
            self.assertEqual(gate_infra.plan_of(forged.work, base, head)['artifacts'], [])

    def test_a_missing_classifier_is_a_loud_error_not_a_silent_no_artifact(self):
        with mock.patch.dict(sys.modules, {'deploy_classify': None}):
            with self.assertRaises(ImportError):
                gate_infra.fast_lambda(['infra/service/tower_infra/http_port.py'])

    def test_a_head_with_its_own_selection_and_no_adapter_is_planned_by_its_own_selection(self):
        # GATE-INFRA 8: before GATE-INFRA 2 a head has no gate_infra.py; run from here, the adapter chose with today's
        # covers (#280 got gate-infra.test.sh, born after it); copied into the head, the head's own modules choose
        with tempfile.TemporaryDirectory() as tmp:
            forged = Forge(Path(tmp))
            base = git('-C', str(forged.work), 'rev-parse', 'HEAD')
            head = forged.commit(OLD_SELECTION)
            plan = gate_infra.plan_of(forged.work, base, head)
            self.assertFalse((forged.work / 'scripts' / 'lib' / 'gate_infra.py').exists())  # only in its worktree
        self.assertEqual((plan['kind'], plan['tests'], plan['reason'], plan['keys']),
                         ('the head', ['scripts/tests/only-in-the-head.test.sh'], 'the head chose it',
                          {'scripts/tests/only-in-the-head.test.sh': 'the key of the head'}))
        self.assertEqual(plan['stages'], ['pr metadata'])

    def test_a_head_is_planned_by_the_boxs_own_selection_when_its_test_cache_has_it(self):
        # GATE-INFRA 9: the box's selection, gate_test_cache.selection, also leaves out a test the change deletes
        with tempfile.TemporaryDirectory() as tmp:
            forged = Forge(Path(tmp))
            base = git('-C', str(forged.work), 'rev-parse', 'HEAD')
            plan = gate_infra.plan_of(forged.work, base, forged.commit(OWN_SELECTION))
        self.assertEqual((plan['tests'], plan['reason']), (['scripts/tests/the-boxs-own.test.sh'], 'the box chose it'))

    def test_a_rank_queue_takes_the_smaller_head_first_and_the_stages_and_longest_tests_first_within_it(self):
        # AWS8: fifo ignores rank; a queue of policy rank orders by it (higher first)
        spec = {'repo': 'org/name', 'pr': '7', 'head': 'h' * len(MOVED), 'base': 'b' * len(MOVED), 'ref': 'feature'}
        trees = {'head': 'th', 'base': 'tb'}
        small = dict(PLAN, stages=['structure check'], tests=['a.test.sh', 'b.test.sh'],
                     costs={'a.test.sh': 2, 'b.test.sh': 9})
        big = dict(small, tests=[f'{n}.test.sh' for n in 'abcde'], costs={'a.test.sh': 2, 'b.test.sh': 9})
        ranks = {name: body['rank'] for name, body in gate_infra.checks(spec, small, trees, TODAY)}
        large = {name: body['rank'] for name, body in gate_infra.checks(spec, big, trees, TODAY)}
        self.assertGreater(ranks['stage:structure check'], ranks['test:b.test.sh'])
        self.assertGreater(ranks['test:b.test.sh'], ranks['test:a.test.sh'])
        self.assertGreater(min(ranks.values()), max(large.values()))  # every check of the smaller head goes first
        # STAGE-RANK-BY-COST: a stage takes its place among the tests by its seconds, and the jobs are made in that order
        long = dict(small, stages=['structure check', 'schema compat'], tests=['a.test.sh', 'b.test.sh', 'c.test.sh'],
                    costs={'a.test.sh': 2, 'b.test.sh': 9, 'c.test.sh': 40})
        made = gate_infra.checks(spec, long, trees, TODAY)
        self.assertEqual([name for name, _ in made], ['test:c.test.sh', 'stage:structure check', 'test:b.test.sh',
                                                      'stage:schema compat', 'test:a.test.sh'])
        self.assertEqual([body['rank'] for _, body in made], sorted((body['rank'] for _, body in made), reverse=True))

    def test_the_jobs_are_what_the_rules_say(self):
        spec = {'repo': 'org/name', 'pr': '7', 'head': 'h' * len(MOVED), 'base': 'b' * len(MOVED), 'ref': 'feature',
                'base_ref': 'mod/roadmap-integration'}
        plan = dict(PLAN, stages=gate_policy.PREREQUISITES)
        made = dict(gate_infra.checks(spec, plan, {'head': 'tree-of-the-head', 'base': 'tree-of-the-base'}, 'today'))
        self.assertNotIn('stage:pr metadata', made)
        self.assertEqual(len(made), len(gate_policy.PREREQUISITES) - 1 + len(PLAN['tests']))
        for name, body in made.items():
            self.assertEqual((body['memoize'], body['selector'], body['queue']), (True, {'adapter': 'container'},
                                                                                  'checks'), name)
            self.assertEqual(body['idempotency_key'], f"check:7:{spec['head']}:{name}")
        history, structure = made['stage:secret scan (history)'], made['stage:structure check']
        self.assertEqual(history['input_digest'], gate_infra.digest('gate-check', 'secret scan (history)',
                                                                    'tree-of-the-head', spec['base'], spec['head']))
        self.assertEqual(structure['input_digest'], gate_infra.digest('gate-check', 'structure check',
                                                                      'tree-of-the-head', 'tree-of-the-base', 'today'))
        self.assertEqual(forge.decode(structure['input_uri'])['command'],
                         ['scripts/gate-check', 'stage', 'structure check', '--base', spec['base']])
        tools = 't' * len(MOVED)  # GATE-INFRA 7: a head with no gate-check of its own, judged by this commit's copy
        tooled = dict(gate_infra.checks(dict(spec, tools=tools), plan, {'head': 'tree-of-the-head',
                                                                        'base': 'tree-of-the-base'}, 'today'))
        self.assertEqual(forge.decode(tooled['stage:structure check']['input_uri'])['command'],
                         ['bash', '-c', gate_infra.TOOL_OF, 'gate-check', tools, 'stage', 'structure check', '--base',
                          spec['base']])
        for name, body in tooled.items():  # its own jobs, the same memo
            self.assertEqual(body['idempotency_key'], f"check:7:{spec['head']}:{name}:tools-{tools}")
            self.assertEqual(body['input_digest'], made[name]['input_digest'])
        land = gate_infra.landing(spec, ['job-a', 'job-b'], shadow=True)
        action = forge.decode(land['input_uri'])
        self.assertEqual((action['action'], action['method'], action['dry_run'], action['head']),
                         ('land', 'merge', True, spec['head']))
        self.assertEqual((land['exclusive_key'], land['non_retryable'], land['depends_on'], land['queue']),
                         ('origin:org/name:mod/roadmap-integration', ['head_moved', 'merged'], ['job-a', 'job-b'],
                          'land'))  # a moved head and a merged PR are never tried again
        self.assertFalse(forge.decode(gate_infra.landing(spec, [], shadow=False)['input_uri'])['dry_run'])

    def test_a_tests_check_is_keyed_by_the_gates_own_test_key_so_it_crosses_heads(self):
        spec = {'repo': 'org/name', 'pr': '7', 'head': 'h' * len(MOVED), 'base': 'b' * len(MOVED), 'ref': 'feature',
                'base_ref': 'mod/roadmap-integration'}
        test = PLAN['tests'][0]
        keyed = dict(PLAN, stages=[], keys={test: 'the-key-of-its-covers'})
        first = dict(gate_infra.checks(spec, keyed, {'head': 'one-tree', 'base': 'b'}, TODAY))[f'test:{test}']
        again = dict(gate_infra.checks(dict(spec, head='g' * len(MOVED)), keyed, {'head': 'another-tree', 'base': 'b'},
                                       TODAY))[f'test:{test}']
        self.assertEqual(first['input_digest'], again['input_digest'])  # the covers did not change: the cache answers
        unkeyed = dict(gate_infra.checks(spec, dict(keyed, keys={}), {'head': 'one-tree', 'base': 'b'}, TODAY))
        self.assertEqual(unkeyed[f'test:{test}']['input_digest'], gate_infra.digest('gate-check', test, 'one-tree'))

    def test_the_plan_names_each_tests_own_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            forged = Forge(Path(tmp))
            base = git('-C', str(forged.work), 'rev-parse', 'HEAD')
            head = forged.commit({'scripts/lib/gate_infra_note.md': 'a note'})
            plan = gate_infra.plan_of(forged.work, base, head)
        self.assertEqual(set(plan['keys']), set(plan['tests']))

    def test_the_calls_a_cold_port_answered_are_kept_with_their_route_and_seconds(self):
        # GATE-COLD-PARTS (criterion 3): #674, #678 and #682 spent 6.2 to 6.9 s in the metadata stage, ~1 s by hand: the
        # port's calls that started a Lambda environment are named, with the port's own cold mark (PORT-COLD-START)
        answers = iter([('{"id": "a"}', 'handler;dur=12.0, cold;dur=1834.5, connect;dur=950.0'), ('{"id": "b"}', 'handler;dur=8.0'),
                        ('{"state": "observed"}', None)])

        def opener(request, timeout):
            body, timing = next(answers)
            answer = Answer(body)
            answer.headers = {'Server-Timing': timing} if timing else {}
            return answer
        port = gate_infra.Port(PORT_URL, 'torre', opener=opener)
        port.call('POST', '/v1/jobs', {})
        port.call('GET', '/v1/jobs/01a1d5ce-2c21-7dc5-8eec-8640d92863d7')
        port.call('GET', '/v1/pr-observation/7')
        self.assertEqual([(route, cold) for route, _, cold in port.colds], [('POST /v1/jobs', 1834.5)])

    def test_a_transient_answer_of_the_port_is_tried_again_and_any_other_is_not(self):
        import urllib.error

        def flaky(*answers):
            asked = []

            def opener(request, timeout):
                asked.append(request.full_url)
                answer = answers[len(asked) - 1]
                if isinstance(answer, BaseException):
                    raise answer
                return Answer(answer)
            return asked, opener

        def refusal(status):
            return urllib.error.HTTPError('port', status, 'refused', {}, io.BytesIO(b'{"message": "refused"}'))
        paused = []
        asked, opener = flaky(refusal(HTTPStatus.SERVICE_UNAVAILABLE), urllib.error.URLError('reset'), '{"id": "a"}')
        port = gate_infra.Port(PORT_URL, 'torre', opener=opener, sleep=paused.append, jitter=lambda low, high: high)
        self.assertEqual(port.call('POST', '/v1/jobs', {}), {'id': 'a'})
        self.assertEqual(len(asked), len(('503', 'reset', 'answered')))
        self.assertEqual(len(paused), 2)
        tries = gate_infra.config.get('gate-infra.call_retries') + 1
        asked, opener = flaky(*[refusal(HTTPStatus.SERVICE_UNAVAILABLE)] * tries)
        with self.assertRaises(gate_infra.Refused) as refused:
            gate_infra.Port(PORT_URL, 'torre', opener=opener, sleep=paused.append,
                             jitter=lambda low, high: 0).call('GET', '/v1/x')
        self.assertEqual((refused.exception.status, len(asked)), (HTTPStatus.SERVICE_UNAVAILABLE, tries))
        asked, opener = flaky(refusal(HTTPStatus.BAD_REQUEST))
        with self.assertRaises(gate_infra.Refused):
            gate_infra.Port(PORT_URL, 'torre', opener=opener, sleep=paused.append).call('GET', '/v1/x')
        self.assertEqual(len(asked), 1)

    def test_the_throttle_is_waited_out(self):
        import urllib.error

        def throttled(retry_after=None):
            headers = {'Retry-After': retry_after} if retry_after else {}
            return urllib.error.HTTPError('port', 429, 'Too Many Requests', headers,
                                          io.BytesIO(b'{"message":"Too Many Requests"}'))

        def port_of(*answers, **options):
            asked, paused = [], []

            def opener(request, timeout):
                asked.append(request.full_url)
                answer = answers[len(asked) - 1]
                if isinstance(answer, BaseException):
                    raise answer
                return Answer(answer)
            return asked, paused, gate_infra.Port(PORT_URL, 'torre', opener=opener, sleep=paused.append,
                                                  jitter=lambda low, high: high, **options)
        asked, paused, port = port_of(throttled(), throttled(), '{"id": "a"}')
        with mock.patch('sys.stderr', new_callable=io.StringIO) as err:
            self.assertEqual(port.call('POST', '/v1/jobs', {}), {'id': 'a'})
        base = gate_infra.config.get('gate-infra.call_backoff_s')
        self.assertEqual((len(asked), paused), (3, [base, base * 2]))  # exponential, one line per retry
        self.assertEqual(err.getvalue().count('answered 429; retry'), 2)
        asked, paused, port = port_of(throttled('7'), '{"id": "a"}')
        with mock.patch('sys.stderr', new_callable=io.StringIO):
            port.call('POST', '/v1/jobs', {})
        self.assertEqual(paused, [7.0])  # Retry-After honored
        tries = gate_infra.config.get('gate-infra.call_retries') + 1
        asked, paused, port = port_of(*[throttled('1')] * tries)
        with mock.patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(gate_infra.Refused) as refused:
            port.call('POST', '/v1/jobs', {})
        self.assertEqual((refused.exception.status, len(asked)), (HTTPStatus.TOO_MANY_REQUESTS, tries))
        self.assertIn('gave up after', str(refused.exception))
        too_long = gate_infra.config.get('gate-infra.call_max_wait_s') + 1
        asked, paused, port = port_of(throttled(str(too_long)), '{"id": "a"}')
        with mock.patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(gate_infra.Refused):
            port.call('POST', '/v1/jobs', {})
        self.assertEqual((len(asked), paused), (1, []))  # a wait past the bound fails at once

    def test_with_no_port_nothing_is_judged(self):
        bare = {name: value for name, value in os.environ.items() if not name.startswith('TOWER_PORT_')}
        with mock.patch.dict(os.environ, bare, clear=True), mock.patch('builtins.print') as said:
            self.assertEqual(gate_infra.main(['shadow', '--pr', '7']), 0)
        self.assertIn('nothing judged', said.call_args[0][0])


class TheMetadataOfAForgeThatIsAway(unittest.TestCase):
    """METADATA-FORGE-RETRY (the review's finding 22): on 11/11 03:04 UTC the forge answered 503 for about three minutes
    and a delivery was red at `pr metadata` with nothing wrong in its PR."""

    BLIND = ('FAIL commit-check: PR #7 not readable (origin answered 503: Service Unavailable)\n'
             'structure-check (metadata, PR #7): 1 error(s), 0 warning(s)\n')
    WRONG = ('FAIL plan: the body names no plan step\n'
             'structure-check (metadata, PR #7): 1 error(s), 0 warning(s)\n')
    GREEN = 'structure-check (metadata, PR #7): 0 error(s), 0 warning(s)\n'

    def answers(self, *said):
        left, self.commands, self.pauses = list(said), [], []

        def run(command, **_):
            self.commands.append(command)
            text = left.pop(0) if len(left) > 1 else left[0]
            return mock.Mock(returncode=0 if text == self.GREEN else 1, stdout=text, stderr='')
        with contextlib.redirect_stderr(io.StringIO()) as err:
            found = gate_infra.metadata_of(7, 'base', run=run, sleep=self.pauses.append, jitter=lambda low, high: high)
        return found, err.getvalue()

    def test_the_metadata_stage_says_its_check_seconds(self):
        # GATE-COLD-PARTS: the structure check's seconds apart from the observation's
        (green, _), _ = self.answers(self.GREEN)
        self.assertTrue(green)
        self.assertGreaterEqual(gate_infra.METADATA_PARTS['metadata_check_s'], 0)
        self.assertNotIn('metadata_observe_s', gate_infra.METADATA_PARTS)  # no port: no observation asked

    def test_a_forge_that_does_not_answer_is_tried_again_and_the_pr_is_judged_when_it_does(self):
        (green, said), err = self.answers(self.BLIND, self.BLIND, self.GREEN)
        self.assertEqual((green, len(self.commands), self.pauses), (True, 3, [1, 2]))  # before: red at the first 503
        self.assertIn('0 error(s)', said)
        self.assertEqual(err.count('pr metadata could not read the forge; retry'), 2)
        self.assertIn('--metadata', self.commands[0])

    def test_a_pr_that_is_wrong_is_red_at_once_and_so_is_one_wrong_and_unreadable(self):
        (green, said), _ = self.answers(self.WRONG)
        self.assertEqual((green, len(self.commands), self.pauses), (False, 1, []))
        self.assertIn('names no plan step', said)
        mixed = self.WRONG.splitlines()[0] + '\nFAIL review: PR #7 not readable (timed out)\n'
        (green, _), _ = self.answers(mixed)
        self.assertEqual((green, len(self.commands)), (False, 1))  # a refusal about the PR: no retry makes it right
        self.assertFalse(gate_infra.blind(self.GREEN))

    def test_a_forge_that_stays_away_is_red_by_its_name_within_the_wait_it_is_given(self):
        (green, said), _ = self.answers(self.BLIND)
        limit, retries = config.get('gate-infra.metadata_blind_wait_s'), config.get('gate-infra.call_retries')
        self.assertFalse(green)  # fail closed: a PR that was not read was not judged
        self.assertIn('the forge did not answer the read of PR #7', said)
        self.assertIn('the PR was not judged', said)
        self.assertLessEqual(sum(self.pauses), limit)
        self.assertEqual(len(self.commands), len(self.pauses) + 1)
        self.assertLessEqual(len(self.commands), retries + 1)
        self.assertGreaterEqual(limit, 180)  # the outage of 11/11 lasted about three minutes


if __name__ == '__main__':
    unittest.main()
