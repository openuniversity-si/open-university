"""The warm runner of the container executor (engine-infra-service; INFRA-EXE 1, P4 F1).

The world is built through the port on a throwaway database of the toolchain's PostgreSQL (TI1); the service's
dispatcher claims the runs, and the runner takes the ones handed over to container executors, with a local fetch,
prepare and upload in place of the image's git, setup.sh and S3: a check that passes and one that fails, a timeout, a
job stopped while its command runs (the run ends and gives its slot back), a lease lost while it runs (the run is left
to the reaper and the job goes back to the queue), an input it does not understand, two runners that never take the
same run, a memoized check whose second run comes from the cache with the runner's signature (and none with no key),
a Spot interruption (a real SIGTERM) that ends the run as lost and has the job dispatched again, a slow setup that
keeps its lease, a job stopped during its setup whose command never starts, and a command whose environment carries no
credential of the runner's.

The image's side (container.py) runs against a forge on the disk (a bare repository reached by file://) with a stub of
scripts/cloud/setup.sh and a stand-in for S3: the checkout kept between runs and left clean but for the toolchain's
link, a commit its ref no longer reaches, the forge's key only in git's environment, the toolchain cached by its
manifests, a failed fetch or setup named, the log in the bucket; and a check through the port, end to end. The
stack (infra/aws/stacks/50-runner.json) is read as data: the warm runner of the architecture on Fargate Spot ARM, the
service's image as run-container with an init that reaps, a role that reaches only its login, its two keys and the
runs' prefix, and a private bucket that forgets the logs. No network.
"""
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import contextlib
import threading
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
from infra_db.psql import migrated  # noqa: E402
import test_db  # noqa: E402
from tower_infra import container, forge, http_port, mechanisms, port, runner  # noqa: E402

from runner_world import COMMIT, KEY, QUICK, REPO, SETUP, URL, Bucket, Forge, RunnerWorld, git  # noqa: E402,F401

STACKS = ROOT / 'infra/aws/stacks'
TARGET = ROOT / 'docs/arquitetura-referencia/ARQUITETURA-ALVO.md'


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


class Runs(RunnerWorld):
    def test_a_check_that_passes_keeps_its_log_and_relays_its_cpu_seconds(self):
        job = self.job('passes', 'echo checked; exit 0')
        mechanisms.dispatch(self.db)
        ended = self.runner.once()
        self.assertEqual((ended['outcome'], ended['state'], ended['result']['exit']), ('succeeded', 'succeeded', 0))
        self.assertIn('checked', ended['result']['tail'])
        self.assertIn('checked', self.kept[ended['run']])
        self.assertEqual((self.fetched, len(self.prepared)), ([COMMIT], len(self.fetched)))
        # HEAD-ON-PUSH: the run's parts in its result
        self.assertEqual(set(ended['result']['parts']), {'fetch_s', 'prepare_s', 'command_s', 'upload_s'})
        self.assertTrue(all(value >= 0 for value in ended['result']['parts'].values()))
        usage = self.port('POST', '/v1/log/query', 'torre', {'filters': {'type': 'run.usage'},
                                                            'payload': {'job_id': job}})['events']
        self.assertEqual([event['payload']['meter'] for event in usage], ['cpu_s'])

    def test_a_command_answers_a_json_object_in_its_answer_file(self):
        # PLAN-ON-RUNNER: the gate's plan rides the result, not the 2000 characters of a log's tail
        for command, want in (('echo "{\\"plan\\": 1}" > "$TOWER_ANSWER_FILE"', {'plan': 1}),
                              ('echo "[1]" > "$TOWER_ANSWER_FILE"', {'refused': 'the answer is not a JSON object'}),
                              ('head -c 600000 /dev/zero > "$TOWER_ANSWER_FILE"', None),
                              # PLAN-ANSWER: a pre-gate's `plan jobs` of a PR that touches the shared libraries (#671 on
                              # 13/11: 93 job bodies, 88 470 bytes) was refused at 64 KiB, and nothing was made at its push
                              ('python3 -c "import json, os; json.dump({\\"jobs\\": [\\"x\\" * 800] * 120}, '
                               'open(os.environ[\\"TOWER_ANSWER_FILE\\"], \\"w\\"))"', {'jobs': ['x' * 800] * 120}),
                              ('true', 'none')):
            self.job(f'answers-{len(command)}', command)
            mechanisms.dispatch(self.db)
            ended = self.runner.once()
            if want == 'none':
                self.assertNotIn('answer', ended['result'])
            elif want is None:
                self.assertIn('over 524288', ended['result']['answer']['refused'])
            else:
                self.assertEqual(ended['result']['answer'], want)
        self.assertEqual(list(Path(self.workdir).glob('*.answer')), [])  # each answer file removed

    def test_a_check_user_s_command_runs_as_that_user_on_a_checkout_of_its_own_and_cannot_read_the_runner(self):
        # CHECK-NOT-ROOT (revisão da arquitetura, achado 14): a check's command ran as the runner's uid 0 and could read the
        # runner's environment (/proc/<pid>/environ) and files; as the check user it cannot. Here the check user is
        # `nobody` (the image's is tower-check), and the runner of the test is root, as the task's is
        if os.geteuid() != 0:
            self.skipTest('the drop of a user needs a runner that is root, as the task is (User "0")')
        with mock.patch.object(runner, 'CHECK_USER', 'nobody'):
            self.assertEqual(runner.check_user({'user': 'nobody'}, {}, euid=0), 'nobody')
            # UID0-FROM-BASE: a job that asks for root on code not known to have landed runs as the check user
            self.assertEqual(runner.check_user({'user': 'root'}, {}, euid=0), 'nobody')
            self.assertEqual(runner.check_user({}, {runner.CHECK_USER_ENV: 'nobody'}, euid=0), 'nobody')  # the task's
            self.assertIsNone(runner.check_user({'user': 'nobody'}, {}, euid=1000))  # a runner that is no root drops nothing
            self.job('as-nobody', 'printf "{\\"uid\\": %s, \\"env\\": %s}" "$(id -u)" '
                     '"$(cat /proc/1/environ >/dev/null 2>&1 && echo 1 || echo 0)" > "$TOWER_ANSWER_FILE"; touch made-here',
                     user='nobody')
            mechanisms.dispatch(self.db)
            ended = self.runner.once()
        self.assertEqual(ended['outcome'], 'succeeded', ended['result']['tail'])
        self.assertEqual(ended['result'].get('answer'), {'uid': 65534, 'env': 0}, ended['result']['tail'])  # nobody; the runner's environ unread
        # no user asked: as before, on a checkout that is root's again (CHECK-USER-SHARED: #670's gate, 13/11 16:2x UTC: a
        # root job on the slot a full-run job had as tower-check met git's `dubious ownership` with its system config off)
        self.job('as-root', 'printf "{\\"uid\\": %s, \\"owner\\": %s, \\"made\\": %s}" "$(id -u)" "$(stat -c %u .)" '
                 '"$(stat -c %u made-here)" > "$TOWER_ANSWER_FILE"')
        mechanisms.dispatch(self.db)
        self.assertEqual(self.runner.once()['result']['answer'], {'uid': 0, 'owner': 0, 'made': 0})

    def test_a_job_has_root_only_for_a_commit_the_forge_pushed_to_the_base(self):
        # UID0-FROM-BASE (the Torre, 13/11 ~14:15 BRT): the uid 0 probe keeps its coverage by a job of root that runs the
        # base's landed code, never a PR's head; and no job escapes the task's check user by asking for another user
        from tower_infra.pregate import REPO
        owner, name = REPO.split('/')
        landed, head = 'a' * 40, 'b' * 40
        for n, (ref, after) in enumerate(((runner.BASE_REF, landed), ('refs/heads/units/x', head))):
            self.db.rows("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) values "
                         "(%(id)s, null, 'forge.repository.pushed', clock_timestamp(), 'ingress', 'repository', %(payload)s::jsonb)",
                         {'id': f'push-{n}', 'payload': json.dumps({'delivery': {'event': {'payload': {
                             'repository': {'owner': {'slug': owner}, 'name': name},
                             'refUpdates': [{'ref': ref, 'after': after}]}}}})})
        self.assertEqual([self.runner.landed(sha) for sha in (landed, head, 'c' * 40, 'not a sha')], [True, False, False, False])
        check = runner.CHECK_USER
        self.assertIsNone(runner.check_user({'user': 'root', 'commit': landed}, {}, euid=0, landed=self.runner.landed))
        self.assertIsNone(runner.check_user({'user': 'root', 'commit': landed}, {runner.CHECK_USER_ENV: check}, euid=0,
                                            landed=self.runner.landed))  # the task's check user too: the base's code
        self.assertEqual(runner.check_user({'user': 'root', 'commit': head}, {}, euid=0, landed=self.runner.landed), check)
        self.assertEqual(runner.check_user({'user': 'bob'}, {runner.CHECK_USER_ENV: check}, euid=0), check)  # no escape

    def test_the_check_user_owns_its_checkout_and_its_toolchains_directory_not_the_databases_data(self):
        # CHECK-USER-SHARED: the full run as tower-check (13/11 15:51 UTC): `missing writable path: .toolchain` (the setup's
        # probe writes in the toolchain's directory); the PostgreSQL data in it keeps its own owner
        if os.geteuid() != 0:
            self.skipTest('a chown needs a runner that is root, as the task is')
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        tools, checkout = base / 'toolchains' / 'abc', base / 'slot-0'
        (tools / 'pgdata').mkdir(parents=True)
        checkout.mkdir()
        (checkout / 'file').write_text('x')
        (checkout / '.toolchain').symlink_to(tools)
        uid, gid, _ = runner.hand_over(checkout, 'nobody')
        self.assertEqual((os.stat(checkout / 'file').st_uid, os.stat(tools).st_uid, os.stat(tools / 'pgdata').st_uid),
                         (uid, uid, 0))
        # TOOLCHAIN-TAKE-BACK: a slot taken back for a root run leaves the shared toolchain to the check user's other slots
        runner.hand_over(checkout, 'root')
        self.assertEqual((os.stat(checkout / 'file').st_uid, os.stat(tools).st_uid), (0, uid))

    def test_a_check_that_fails_ends_with_its_exit_code(self):
        self.job('fails', 'echo broken >&2; exit 3')
        mechanisms.dispatch(self.db)
        ended = self.runner.once()
        self.assertEqual((ended['outcome'], ended['error'], ended['state']), ('failed', 'exit_3', 'failed'))
        self.assertIn('broken', ended['result']['tail'])

    def test_a_run_whose_job_is_cancelled_stops_at_the_wake_not_at_the_next_renewal(self):
        # CANCEL-WAKES-RUNNER (criterion 3): #684's artifact job waited 82.6 s for a slot a full run's test held after it was
        # taken back (mechanisms.PREEMPT): the runner heard the cancel at its keeper's renewal, every 60 s. job.cancelled now
        # wakes tower_runs (migration 0022), and watch_cancels stops the command at once
        listened = self.db.call(['-A', '-t', '-f', '-'], script=(
            "listen tower_runs;\ninsert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
            "values ('job.cancelled:probe', null, 'job.cancelled', clock_timestamp(), 'test', 'job/x', '{}'::jsonb);\nselect 1;\n"))
        self.assertIn('tower_runs', listened)
        self.runner.renew_every_s = 60.0  # the renewal far away: only the wake can stop it in time
        job = self.job('long', 'sleep 30')
        mechanisms.dispatch(self.db)
        ended, woke, stop = [], threading.Event(), threading.Event()
        self.addCleanup(stop.set)
        runner.watch_cancels([self.runner], lambda s: woke.wait(s) and (woke.clear() or True), lambda: contextlib.nullcontext(self.db), stop)
        thread = threading.Thread(target=lambda: ended.append(self.runner.once()), daemon=True)
        thread.start()
        while not self.running(job):
            time.sleep(0.05)
        while self.runner.current is None:
            time.sleep(0.05)
        self.db.rows("update work.job set state = 'cancelled', version = version + 1 where id = %(id)s::uuid", {'id': job})
        woke.set()  # the notification of job.cancelled
        thread.join(10)  # the command sleeps 30 s and the renewal is 60 s away: an end within the join is the wake's
        self.assertFalse(thread.is_alive())
        self.assertEqual(ended[0]['outcome'], 'cancelled')
        self.assertEqual(self.state(job), 'cancelled')

    def test_a_check_past_its_timeout_is_killed(self):
        self.job('slow', 'sleep 30', timeout_s='0.2')
        mechanisms.dispatch(self.db)
        ended = self.runner.once()
        self.assertEqual((ended['outcome'], ended['error']), ('timed_out', 'timed_out'))

    def unprepared(self, retryable):
        def prepare(checkout):
            error = container.Unprepared('setup: toolchain: download failed for python')
            error.retryable = retryable
            raise error
        self.runner.prepare = prepare

    def test_a_setup_that_failed_for_the_network_ends_lost_and_goes_back_to_the_queue_a_few_times(self):
        # 09/11: 16 gate jobs ended not_started on a cold task's failed toolchain download: a red verdict on a green head
        job = self.job('cold', 'exit 0')
        self.unprepared(True)
        ends = []
        for _ in range(self.runner.lost_limit + 1):
            mechanisms.dispatch(self.db)
            ends.append(self.runner.once())
        self.assertEqual([(each['outcome'], each['error']) for each in ends],
                         [('lost', 'unprepared')] * self.runner.lost_limit + [('failed', 'not_started')])
        self.assertEqual(self.state(job), 'failed')  # bounded: the last run says it, as before
        self.assertIn('download failed', ends[-1]['result']['tail'])

    def test_a_setup_that_failed_for_the_network_then_works_runs_the_check(self):
        job = self.job('cold-then-warm', 'exit 0')
        self.unprepared(True)
        mechanisms.dispatch(self.db)
        self.assertEqual(self.runner.once()['outcome'], 'lost')
        self.runner.prepare = self.prepare
        mechanisms.dispatch(self.db)
        self.assertEqual(self.runner.once()['outcome'], 'succeeded')
        self.assertEqual(self.state(job), 'succeeded')

    def test_a_setup_that_failed_for_another_reason_is_not_started_at_once(self):
        job = self.job('broken', 'exit 0')
        self.unprepared(False)
        mechanisms.dispatch(self.db)
        ended = self.runner.once()
        self.assertEqual((ended['outcome'], ended['error'], self.state(job)), ('failed', 'not_started', 'failed'))

    def test_an_input_it_does_not_understand_is_refused_without_a_fetch(self):
        job = self.port('POST', '/v1/jobs', 'torre', {'executor': 'script-runner', 'input_uri': 'in/a-file',
                                                      'input_digest': 'sha256:file', 'idempotency_key': 'file'})['id']
        mechanisms.dispatch(self.db)
        ended = self.runner.once()
        self.assertEqual((ended['error'], self.state(job), self.fetched), ('not_understood', 'failed', []))

    def test_there_is_nothing_to_take_before_the_dispatch_and_none_of_another_adapter(self):
        self.job('waits', 'exit 0')
        self.assertIsNone(self.runner.once())
        self.job('lands', 'exit 0', executor='origin-forge')
        mechanisms.dispatch(self.db)
        self.assertEqual(self.runner.once()['outcome'], 'succeeded')  # the container job, not the forge's
        self.assertIsNone(self.runner.once())


class TheCommand(RunnerWorld):
    def test_its_environment_carries_the_jobs_env_and_no_credential_of_the_runners(self):
        self.job('environment', 'env', env={'CHECK': 'one'})
        mechanisms.dispatch(self.db)
        with mock.patch.dict(os.environ, {'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI': 'credentials-of-the-test',
                                          'TOWER_DB_PASSWORD': 'password-of-the-test'}):
            ended = self.runner.once()
        self.assertIn('CHECK=one', ended['result']['tail'])
        for leaked in ('credentials-of-the-test', 'password-of-the-test'):
            self.assertNotIn(leaked, ended['result']['tail'])

    def test_an_env_that_is_not_an_object_is_not_understood(self):
        self.job('bad-env', 'exit 0', env=['CHECK=one'])
        mechanisms.dispatch(self.db)
        self.assertEqual((self.runner.once()['error'], self.fetched), ('not_understood', []))


class TheImagesSide(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.forge, self.calls = Forge(self.tmp), []
        self.setup_log = self.tmp / 'setup.log'
        self.box = self.box_with(lambda: 'key-of-the-test')

    def box_with(self, credential, bucket=None, s3=None):
        environ = {name: value for name, value in os.environ.items()
                   if name not in ('CURSOR_API_KEY', 'CURSOR_AUTH_TOKEN')}
        environ['SETUP_LOG'] = str(self.setup_log)

        def run(args, **options):
            verb = next(arg for arg in args[1:] if not arg.startswith('-') and '=' not in arg)
            self.calls.append((args[0], verb, 'CURSOR_API_KEY' in (options.get('env') or {})))
            return subprocess.run(args, **options)
        return container.Container(self.tmp / 'runner', credential=credential, forge_url=self.forge.url(),
                                   bucket=bucket, run=run, environ=environ, s3=s3)

    def spec(self, commit, ref='base'):
        return {'repo': REPO, 'ref': ref, 'commit': commit, 'command': ['sh', 'check.sh']}

    def head(self, checkout):
        return git('-C', str(checkout), 'rev-parse', 'HEAD')

    def test_the_checkout_is_kept_between_runs_and_left_clean_but_for_the_toolchain(self):
        first = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        checkout = self.box.checkout_of(self.spec(first))
        self.box.fetch(self.spec(first), checkout)
        self.assertEqual(self.head(checkout), first)
        (checkout / '.git' / 'kept-by-the-test').write_text('the same clone\n')
        (checkout / 'left-by-a-check').write_text('junk\n')
        (checkout / container.KEEP).symlink_to(self.tmp, target_is_directory=True)
        second = self.forge.commit({'check.sh': 'echo second'})
        self.box.fetch(self.spec(second), checkout)
        self.assertEqual(self.head(checkout), second)
        self.assertTrue((checkout / '.git' / 'kept-by-the-test').exists())
        self.assertFalse((checkout / 'left-by-a-check').exists())
        self.assertTrue((checkout / container.KEEP).is_symlink())
        self.assertEqual((checkout / 'check.sh').read_text(), 'echo second\n')

    def test_a_commit_its_ref_no_longer_reaches_is_fetched_by_itself(self):
        aside = self.forge.commit({'check.sh': 'echo aside'}, branch='aside')
        git('-C', str(self.forge.work), 'reset', '--quiet', '--hard', 'HEAD~1')
        checkout = self.box.checkout_of(self.spec(aside))
        self.box.fetch(self.spec(aside), checkout)
        self.assertEqual(self.head(checkout), aside)

    def test_the_jobs_base_is_fetched_when_its_ref_does_not_reach_it(self):
        base = self.forge.commit({'check.sh': 'echo the base'}, branch='the-base')
        git('-C', str(self.forge.work), 'reset', '--quiet', '--hard', 'HEAD~1')
        head = self.forge.commit({'check.sh': 'echo the head'})
        spec = dict(self.spec(head), base=base)
        checkout = self.box.checkout_of(spec)
        self.box.fetch(spec, checkout)
        self.assertEqual((self.head(checkout), git('-C', str(checkout), 'cat-file', '-t', base)), (head, 'commit'))
        self.assertFalse(runner.understood(dict(spec, base='the-base')))

    def test_a_slot_whose_sibling_holds_a_clone_copies_it_on_the_disk_not_from_the_forge(self):
        # PREWARM-LOCAL-CLONE: a new task's slots cloned the repository from the forge one after the other
        first = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        self.box.fetch(self.spec(first), self.box.checkout_of(self.spec(first)))
        seen = []

        def run(args, **options):
            seen.append(args)
            return subprocess.run(args, **options)
        other = container.Container(self.tmp / 'runner', forge_url=self.forge.url(), slot=2, run=run,
                                    environ=self.box.environ)
        aside = other.checkout_of(self.spec(first))
        other.fetch(self.spec(first), aside)
        [clone] = [args for args in seen if 'clone' in args]
        self.assertIn('--local', clone)
        self.assertNotIn(self.forge.url(), ' '.join(clone))  # no trip to the forge for it
        self.assertEqual(self.head(aside), first)
        self.assertEqual(git('-C', str(aside), 'remote', 'get-url', 'origin'), f'{self.forge.url()}/{self.spec(first)["repo"]}.git')

    def test_a_commit_already_in_the_checkout_costs_no_trip_to_the_forge_and_a_sibling_slot_gives_it(self):
        # AWS8: the checks of one head ask for the same commit; the forge is reached once per task, not once per check
        first = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        checkout = self.box.checkout_of(self.spec(first))
        self.box.fetch(self.spec(first), checkout)
        second = self.forge.commit({'check.sh': 'echo second'})
        self.box.fetch(self.spec(second), checkout)
        before = list(self.calls)
        self.box.fetch(self.spec(second), checkout)
        self.box.fetch(dict(self.spec(second), base=first), checkout)
        news = [verb for tool, verb, _ in self.calls[len(before):] if tool == 'git' and verb in ('clone', 'fetch')]
        self.assertEqual(news, [])  # head and base held: nothing reaches the forge
        seen = []

        def run(args, **options):
            seen.append(args)
            return subprocess.run(args, **options)
        other = container.Container(self.tmp / 'runner', forge_url=self.forge.url(), slot=1, run=run,
                                    environ=self.box.environ)
        aside = other.checkout_of(self.spec(second))
        self.assertNotEqual(aside, checkout)
        other.fetch(dict(self.spec(second), base=first), aside)  # the clone is the one trip to the forge
        third = self.forge.commit({'check.sh': 'echo third'})
        self.box.fetch(self.spec(third), checkout)  # slot 0 reaches the forge for it
        seen.clear()
        other.fetch(self.spec(third), aside)  # slot 1 takes it from slot 0's checkout, on the disk
        self.assertEqual(self.head(aside), third)
        fetched = [args for args in seen if 'fetch' in args]
        self.assertEqual(len(fetched), 1)
        self.assertIn(str(checkout), fetched[0])
        self.assertFalse([args for args in seen if self.forge.url() in ' '.join(args) and 'set-url' not in args])

    def test_a_fetch_says_where_the_head_came_from(self):
        # HEAD-ON-PUSH: the forge, a sibling slot's checkout on the disk, or this checkout already
        first = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        checkout = self.box.checkout_of(self.spec(first))
        self.assertEqual(self.box.fetch(self.spec(first), checkout), 'forge')
        self.assertEqual(self.box.fetch(self.spec(first), checkout), 'here')
        other = container.Container(self.tmp / 'runner', forge_url=self.forge.url(), slot=1, environ=self.box.environ)
        self.assertEqual(other.fetch(self.spec(first), other.checkout_of(self.spec(first))), 'sibling')  # its clone
        second = self.forge.commit({'check.sh': 'echo second'})
        self.assertEqual(self.box.fetch(self.spec(second), checkout), 'forge')
        self.assertEqual(other.fetch(self.spec(second), other.checkout_of(self.spec(second))), 'sibling')

    def test_a_pushed_head_is_kept_beside_the_slots_and_a_slot_takes_it_from_the_disk(self):
        # HEAD-ON-PUSH: a gate's first run in each slot fetched its head from the forge (about 2.4 s, every slot at once)
        first = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        self.box.fetch(self.spec(first), self.box.checkout_of(self.spec(first)))
        pushed = container.Container(self.tmp / 'runner', forge_url=self.forge.url(), slot=container.PUSHED_SLOT,
                                     environ=self.box.environ)
        head = self.forge.commit({'check.sh': 'echo pushed'}, branch='units/x')
        self.assertTrue(pushed.keep_pushed(REPO, 'units/x', head))
        self.assertFalse(pushed.keep_pushed(REPO, 'units/x', head))  # held: no second trip
        kept = pushed.checkout_of({'repo': REPO})
        self.assertFalse((kept / 'check.sh').exists())  # no work tree: no run checks it out
        self.assertEqual(self.box.fetch(self.spec(head, ref='units/x'), self.box.checkout_of(self.spec(head))), 'pushed')
        self.assertEqual(self.head(self.box.checkout_of(self.spec(head))), head)
        seen = []
        fresh = container.Container(self.tmp / 'runner', forge_url=self.forge.url(), slot=3, environ=self.box.environ,
                                    run=lambda args, **options: seen.append(args) or subprocess.run(args, **options))
        self.assertEqual(fresh.fetch(self.spec(head, ref='units/x'), fresh.checkout_of(self.spec(head))), 'sibling')
        self.assertFalse([args for args in seen if self.forge.url() in ' '.join(args) and 'set-url' not in args])
        # PUSHED-ALTERNATES: a slot reads the pushed clone's objects in place, copies nothing, and that clone never collects
        later = self.forge.commit({'check.sh': 'echo later'}, branch='units/x')
        self.assertTrue(pushed.keep_pushed(REPO, 'units/x', later))
        seen.clear()
        # here: cloned from a slot that leans on the pushed clone, it carries the alternates over (git clone --local)
        self.assertIn(fresh.fetch(self.spec(later, ref='units/x'), fresh.checkout_of(self.spec(later))), ('pushed', 'here'))
        self.assertFalse([args for args in seen if 'fetch' in args])
        self.assertEqual(self.head(fresh.checkout_of(self.spec(later))), later)
        self.assertIn(str((kept / '.git' / 'objects').resolve()),
                      (fresh.checkout_of(self.spec(later)) / '.git' / 'objects' / 'info' / 'alternates').read_text())
        self.assertEqual(git('-C', str(kept), 'config', 'gc.auto'), '0')

    def test_a_pushed_head_appears_in_the_pushed_clone_whole_or_not_at_all(self):
        # PUSHED-PACK: slots read the pushed clone in place while a push is fetched into it; a small fetch unpacked loose
        # objects, the commit first, and a slot saw the head without its tree (#654's bundle job, 13/11 13:26 UTC)
        first = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        self.box.fetch(self.spec(first), self.box.checkout_of(self.spec(first)))
        pushed = container.Container(self.tmp / 'runner', forge_url=self.forge.url(), slot=container.PUSHED_SLOT,
                                     environ=self.box.environ)
        kept = pushed.checkout_of({'repo': REPO})
        for n in range(2):
            head = self.forge.commit({'check.sh': f'echo pushed {n}', f'dir{n}/file': f'{n}'}, branch='units/x')
            self.assertTrue(pushed.keep_pushed(REPO, 'units/x', head))
            for name in (head, git('-C', str(kept), 'rev-parse', f'{head}^{{tree}}'),
                         git('-C', str(kept), 'rev-parse', f'{head}:dir{n}')):
                self.assertFalse((kept / '.git' / 'objects' / name[:2] / name[2:]).exists(), name)  # in a pack
            self.assertEqual(git('-C', str(kept), 'cat-file', '-t', f'{head}:dir{n}/file'), 'blob')
        self.assertEqual(git('-C', str(kept), 'config', 'fetch.unpackLimit'), '1')

    def test_the_forges_key_goes_only_into_gits_environment(self):
        commit = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        checkout = self.box.checkout_of(self.spec(commit))
        self.box.fetch(self.spec(commit), checkout)
        self.box.fetch(self.spec(self.forge.commit({'check.sh': 'echo later'})), checkout)  # not here yet: a fetch
        self.box.prepare(checkout)
        reached = {verb: key for tool, verb, key in self.calls if tool == 'git' and verb in ('clone', 'fetch')}
        self.assertEqual(reached, {'clone': True, 'fetch': True})  # what reaches the forge carries the key
        self.assertEqual({key for tool, verb, key in self.calls if tool == 'bash' or verb == 'cat-file'}, {False})
        self.assertIn('"$(origin auth token 2>/dev/null)" exec origin credential-helper', container.helper('origin'))
        self.assertIn("'an origin/origin' auth token", container.helper('an origin/origin'))

    def test_the_toolchain_is_cached_by_its_manifests_and_set_up_once_for_the_same_inputs(self):
        # INFRA-EXE 1c: the checks of one head, or of heads whose setup inputs are the same, pay one setup in a task
        commit = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        checkout = self.box.checkout_of(self.spec(commit))
        for spec in (self.spec(commit), self.spec(commit), self.spec(self.forge.commit({'check.sh': 'echo other'}))):
            self.box.fetch(spec, checkout)
            self.box.prepare(checkout)
        self.assertEqual(len(self.setup_log.read_text().splitlines()), 1)  # what setup reads did not change
        moved = self.forge.commit({'scripts/cloud/toolchain.json': '{"tools": "second"}'})
        self.box.fetch(self.spec(moved), checkout)
        self.box.prepare(checkout)
        first, second = self.setup_log.read_text().splitlines()
        self.assertNotEqual(first, second)
        self.assertEqual(Path(second).parent, self.tmp / 'runner' / 'toolchains')
        self.assertEqual(container.Container(self.tmp / 'another').prepared, None)  # each task sets up once itself

    def test_a_process_that_took_the_role_in_the_task_and_a_library_setup_never_runs_set_up_nothing_again(self):
        # SETUP-PER-HEAD: a landing's swap gives the slots a new process, and most heads change a library of scripts/lib:
        # each slot set up again on its first run (prepare_s 1.2 to 12.8 s in #634 and #635)
        commit = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        checkout = self.box.checkout_of(self.spec(commit))
        self.box.fetch(self.spec(commit), checkout)
        self.box.prepare(checkout)
        successor = self.box_with(lambda: 'key-of-the-test')  # the same task's disk, a new process
        successor.fetch(self.spec(commit), checkout)
        successor.prepare(checkout)
        self.assertEqual(len(self.setup_log.read_text().splitlines()), 1)
        other = self.forge.commit({'scripts/lib/not_read_by_setup.py': 'x = 1\n'})
        successor.fetch(self.spec(other), checkout)
        successor.prepare(checkout)
        self.assertEqual(len(self.setup_log.read_text().splitlines()), 1)
        read = self.forge.commit({'scripts/lib/config.py': 'changed = True\n'})
        successor.fetch(self.spec(read), checkout)
        successor.prepare(checkout)
        self.assertEqual(len(self.setup_log.read_text().splitlines()), 2)  # what setup runs changed: set up again
        (checkout / '.git' / container.PREPARED).unlink()
        self.box_with(lambda: 'key-of-the-test').prepare(checkout)  # no mark (a new task's disk): set up
        self.assertEqual(len(self.setup_log.read_text().splitlines()), 3)

    def test_each_slot_keeps_a_checkout_of_its_own_over_one_toolchain_cache(self):
        # INFRA-EXE 1e: two slots check out two commits at once; slot 0 keeps the checkout a one-slot task had
        commit = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        boxes = [container.Container(self.tmp / 'runner', forge_url=self.forge.url(), slot=n) for n in (0, 1)]
        first, second = (box.checkout_of(self.spec(commit)) for box in boxes)
        self.assertEqual(first, self.box.checkout_of(self.spec(commit)))
        self.assertNotEqual(first, second)
        for box, checkout in zip(boxes, (first, second)):
            box.fetch(self.spec(commit), checkout)
        self.assertEqual(*(box.toolchain_of(checkout) for box, checkout in zip(boxes, (first, second))))

    def test_a_failed_fetch_or_setup_is_named(self):
        missing = self.spec('89abcdef0123456789abcdef0123456789abcdef')
        with self.assertRaisesRegex(container.Unprepared, '^git fetch'):
            self.box.fetch(missing, self.box.checkout_of(missing))
        good = git('-C', str(self.forge.work), 'rev-parse', 'HEAD')
        checkout = self.box.checkout_of(self.spec(good))
        self.box.fetch(self.spec(good), checkout)
        self.box.prepare(checkout)
        broken = self.forge.commit({'scripts/cloud/setup.sh': 'echo the toolchain is missing; exit 3'})
        self.box.fetch(self.spec(broken), checkout)
        for _ in ('first', 'again'):  # a failed setup is never kept (INFRA-EXE 1c): the next run sets up again
            with self.assertRaisesRegex(container.Unprepared, '^setup: the toolchain is missing'):
                self.box.prepare(checkout)
        flaky = self.forge.commit({'scripts/cloud/setup.sh': 'echo toolchain: download failed for python >&2; exit 1'})
        self.box.fetch(self.spec(flaky), checkout)
        with self.assertRaises(container.Unprepared) as caught:
            self.box.prepare(checkout)
        self.assertTrue(caught.exception.retryable)  # the network's word: the runner ends the run lost
        self.assertFalse(container.Unprepared('setup: the toolchain is missing').retryable)
        self.box.fetch(self.spec(good), checkout)
        self.box.prepare(checkout)  # and it drops the one kept before it, whose toolchain it may have touched
        self.assertEqual(len(self.setup_log.read_text().splitlines()), len(('good', 'good again')))  # the failing stubs log nothing

    def test_the_log_goes_to_the_bucket_or_stays_in_the_workdir(self):
        log = self.tmp / 'a.log'
        log.write_text('checked\n')
        bucket = Bucket()
        run = {'run': 'the-run', 'job': 'the-job'}
        scheme, _, where = self.box_with(None, 'outputs', bucket).upload(run, log).partition('://')
        self.assertEqual((scheme, where), ('s3', 'outputs/runs/the-job/the-run.log'))
        self.assertEqual(bucket.kept, {('outputs', 'runs/the-job/the-run.log'): 'checked\n'})
        kept = Path(self.box.upload(run, log))
        self.assertEqual((kept.parent, kept.read_text()), (self.tmp / 'runner' / 'logs', 'checked\n'))


def pushed(repo=REPO, *updates):
    owner, name = repo.split('/')
    return {'delivery': {'event': {'type': 'repository.pushed', 'payload': {
        'repository': {'name': name, 'owner': {'slug': owner}}, 'refUpdates': list(updates)}}}}


def update(ref, after, deleted=False):
    return {'ref': ref, 'after': after, 'before': '0' * 40, 'deleted': deleted}


class ThePushedHeads(unittest.TestCase):
    """HEAD-ON-PUSH: the heads a push made, read from the log and kept beside the slots' checkouts."""

    def test_a_push_says_the_branches_it_created_or_moved_of_the_served_repository(self):
        head = 'a' * 40
        self.assertEqual(container.pushed_heads(pushed(REPO, update('refs/heads/units/x', head)), REPO), [('units/x', head)])
        for payload in (pushed('other/repo', update('refs/heads/units/x', head)),
                        pushed(REPO, update('refs/heads/units/x', head, deleted=True)),
                        pushed(REPO, update('refs/heads/units/x', '0' * 40)),
                        pushed(REPO, update('refs/tags/v1', head)),
                        pushed(REPO, update('refs/heads/units/x', 'short')), {}, None):
            self.assertEqual(container.pushed_heads(payload, REPO), [], payload)

    class Db:
        def __init__(self, rows):
            self.rows_, self.asked = list(rows), []

        def rows(self, sql, params=None):
            self.asked.append(params)
            if sql == container.NOW:
                return [('2026-11-13 07:00:00+00',)]
            assert sql == container.PUSHED, sql
            found, self.rows_ = self.rows_, []
            return found

    class Box:
        def __init__(self, held=()):
            self.kept, self.held = [], set(held)

        def keep_pushed(self, repo, ref, commit):
            self.kept.append((repo, ref, commit))
            if commit == 'b' * 40:
                raise container.Unprepared('git fetch: refused')
            return commit not in self.held

    def test_its_look_fetches_each_head_once_from_its_first_look_on(self):
        box, logged = self.Box(held={'c' * 40}), []
        db = self.Db([('2026-11-13 07:00:01+00', json.dumps(pushed(REPO, update('refs/heads/units/x', 'a' * 40),
                                                                     update('refs/heads/units/y', 'b' * 40)))),
                      ('2026-11-13 07:00:02+00', json.dumps(pushed(REPO, update('refs/heads/units/z', 'c' * 40))))])
        look = container.Pushed(box, REPO, log=lambda *args: logged.append(args))
        self.assertEqual(look.step(db), 0)  # the first look only says from when
        self.assertEqual(look.step(db), 1)  # x fetched; y refused (said); z held already
        self.assertEqual([ref for _, ref, _ in box.kept], ['units/x', 'units/y', 'units/z'])
        self.assertEqual(db.asked[-1], {'since': '2026-11-13 07:00:00+00'})
        self.assertEqual(look.since, '2026-11-13 07:00:02+00')
        self.assertTrue(any('not fetched' in args[0] for args in logged))

    def test_the_runners_main_listens_for_the_pushes(self):
        source = (ROOT / 'infra' / 'service' / 'tower_infra' / '__main__.py').read_text()
        self.assertIn('(wake.RUNS, wake.CONFIG, wake.DEPLOY))  # HEAD-ON-PUSH', source)
        self.assertIn('container.Pushed(', source)


class Prewarm(unittest.TestCase):
    """F1: a starting task warms before its slots take a run; injected clock and boxes, no network."""

    class Box:
        def __init__(self, clock, steps=(), cost=5.0):
            self.clock, self.steps, self.cost, self.calls = clock, list(steps), cost, []
            self.environ = {}

        def seconds(self, name, default):
            return float(self.environ.get(name, default))

        def head_of(self, repo, ref):
            self.calls.append(('head', repo, ref))
            return 'a' * 40

        def checkout_of(self, spec):
            return Path('/work/checkouts/x')

        def fetch(self, spec, checkout):
            self.calls.append(('fetch', spec['commit']))
            self.clock.now += self.cost

        def prepare(self, checkout):
            self.calls.append(('prepare', self.environ.get('TOWER_SETUP_TIMEOUT_S')))
            if self.steps:
                step = self.steps.pop(0)
                if step:
                    raise step

    class Clock:
        now = 100.0

        def __call__(self):
            return self.now

    def test_it_fetches_the_base_head_and_sets_up_each_slot_and_records_the_event(self):
        clock, events, logs = self.Clock(), [], []
        boxes = [self.Box(clock), self.Box(clock)]
        ok, seconds = container.prewarm(boxes, 'o/r', 'base', clock=clock, record=events.append, name='task-1',
                                        log=logs.append)
        self.assertEqual((ok, seconds), (True, 10.0))
        # PREWARM-PARTS: and where each slot's seconds went
        self.assertEqual(events, [{'task': 'task-1', 'seconds': 10.0, 'ok': True, 'head_s': 0.0,
                                   'slots': [{'fetch_s': 5.0, 'setup_s': 0.0}, {'fetch_s': 5.0, 'setup_s': 0.0}]}])
        self.assertEqual([call[0] for call in boxes[1].calls], ['fetch', 'prepare'])
        self.assertEqual(boxes[0].calls[:2], [('head', 'o/r', 'base'), ('fetch', 'a' * 40)])

    def test_it_beats_while_it_warms(self):
        clock, beats = self.Clock(), []
        box = self.Box(clock)
        box.fetch = lambda spec, checkout: time.sleep(0.15)
        container.prewarm([box], 'o/r', 'base', clock=clock, heartbeat=lambda: beats.append(1), beat_s=0.02)
        self.assertGreaterEqual(len(beats), 2)

    def test_a_failed_download_is_tried_again_and_a_failed_warm_up_is_logged_not_raised(self):
        clock, events, logs = self.Clock(), [], []
        flaky = container.Unprepared('setup: download failed')
        flaky.retryable = True
        retried = self.Box(clock, steps=[flaky])
        self.assertTrue(container.prewarm([retried], 'o/r', 'b', clock=clock, tries=2, log=logs.append)[0])
        self.assertEqual([call[0] for call in retried.calls].count('prepare'), 2)
        broken = self.Box(clock, steps=[container.Unprepared('setup: syntax error')])
        ok, _ = container.prewarm([broken], 'o/r', 'b', clock=clock, record=events.append, name='t', log=logs.append)
        self.assertFalse(ok)
        self.assertFalse(events[-1]['ok'])
        self.assertTrue(any('going on cold' in line for line in logs))

    def test_a_forge_that_cannot_say_the_head_or_a_budget_spent_fails_cold_and_the_setup_gets_what_is_left(self):
        clock = self.Clock()
        box = self.Box(clock, cost=500.0)
        box.head_of = mock.Mock(side_effect=container.Unprepared('ls-remote: no ref'))
        self.assertFalse(container.prewarm([box], 'o/r', 'b', clock=clock)[0])
        slow = [self.Box(clock, cost=300.0), self.Box(clock, cost=200.0), self.Box(clock)]
        self.assertFalse(container.prewarm(slow, 'o/r', 'b', clock=clock, timeout_s=420)[0])
        self.assertEqual(slow[1].calls[-1], ('prepare', '120.0'))  # the setup's timeout is the budget left
        self.assertEqual([call for call in slow[2].calls if call[0] != 'head'], [])  # the third slot never started

    def test_a_recording_that_fails_does_not_fail_the_warm_up(self):
        clock = self.Clock()

        def broken(_):
            raise RuntimeError('db down')
        self.assertTrue(container.prewarm([self.Box(clock)], 'o/r', 'b', clock=clock, record=broken)[0])

    def test_head_of_reads_the_forge_ref_and_the_main_warms_before_the_slots_and_beats_a_warming_file(self):
        box = container.Container('/tmp/none', environ={}, run=mock.Mock(return_value=mock.Mock(
            returncode=0, stdout='b' * 40 + '\trefs/heads/base\n', stderr='')))
        self.assertEqual(box.head_of('o/r', 'base'), 'b' * 40)
        body = (ROOT / 'infra' / 'service' / 'tower_infra' / '__main__.py').read_text()
        run_container = body[body.index('def run_container'):body.index('def healthy')]
        self.assertLess(run_container.index('prewarm(container'), run_container.index('runner.serve_all'))
        self.assertIn('.warming', body)  # the health file stays untouched while warming: the old task serves meanwhile
        self.assertIn('prewarm_s=', run_container)
        # GATE-SHUTDOWN (D-314): the runner's task definition (its health check and warm-up timeout) left 50-runner.json


class ColdStart(unittest.TestCase):
    def test_the_seconds_since_the_tasks_image_pull_started_come_from_the_task_metadata(self):
        asked = []

        def opener(url, timeout):
            asked.append(url)
            return Answer(json.dumps({'PullStartedAt': '2026-11-04T19:29:01.250000999Z'}))
        now = datetime.fromisoformat('2026-11-04T19:29:31.25+00:00')
        seconds = container.cold_start(now, {'ECS_CONTAINER_METADATA_URI_V4': 'metadata-of-the-test'}, opener)
        self.assertEqual((seconds, asked), (float('30'), ['metadata-of-the-test/task']))

    def test_outside_ecs_or_with_metadata_it_cannot_read_there_is_no_number(self):
        def broken(url, timeout):
            return Answer('{"PullStartedAt": "not a time"}')
        self.assertIsNone(container.cold_start(environ={}))
        self.assertIsNone(container.cold_start(environ={'ECS_CONTAINER_METADATA_URI_V4': 'metadata'}, opener=broken))


class Answer:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ThroughThePort(RunnerWorld):
    def test_a_check_through_the_port_runs_on_its_commit_and_keeps_its_log_in_the_bucket(self):
        forged = Forge(Path(self.workdir) / 'forged')
        commit = git('-C', str(forged.work), 'rev-parse', 'HEAD')
        bucket = Bucket()
        environ = dict(os.environ, SETUP_LOG=str(Path(self.workdir) / 'setup.log'))
        box = container.Container(Path(self.workdir) / 'runner', forge_url=forged.url(), bucket='outputs', s3=bucket,
                                  environ=environ)
        worker = runner.Runner(self.db, box.fetch, box.prepare, box.upload, box.workdir, renew_every_s=QUICK,
                               checkout_of=box.checkout_of, signing_key=lambda: KEY)
        job = self.check('end-to-end', commit, ['sh', 'check.sh'])
        mechanisms.dispatch(self.db)
        ended = worker.once()
        scheme, _, where = ended['result']['log_uri'].partition('://')
        self.assertEqual((ended['state'], scheme, where), ('succeeded', 's3', f"outputs/runs/{job}/{ended['run']}.log"))
        self.assertEqual(list(bucket.kept.values()), ['checked\n'])
        self.assertEqual(self.port('GET', f'/v1/jobs/{job}', 'torre')['state'], 'succeeded')


class TheCache(RunnerWorld):
    def test_a_memoized_check_that_passed_comes_from_the_cache_the_second_time(self):
        self.job('memo-first', 'echo once', digest='same', memoize=True)
        mechanisms.dispatch(self.db)
        self.assertEqual(self.runner.once()['state'], 'succeeded')
        (hexed, cached), = self.db.rows("select encode(signature, 'hex'), result::text from work.result_cache "
                                        "where input_digest = 'sha256:same'")
        self.assertTrue(runner.verified(KEY, 'script-runner', 'sha256:same', json.loads(cached), bytes.fromhex(hexed)))
        self.assertFalse(runner.verified(b'another-key', 'script-runner', 'sha256:same', json.loads(cached),
                                         bytes.fromhex(hexed)))
        second = self.job('memo-second', 'echo once', digest='same', memoize=True)
        mechanisms.dispatch(self.db)
        self.assertEqual((self.state(second), self.runner.once(), self.fetched), ('succeeded', None, [COMMIT]))

    def test_a_memoized_job_whose_twin_runs_waits_for_it_and_is_answered_by_its_success(self):
        # PRE-GATE: the delivery's gate makes the jobs the pre-gate is still running at the push: each runs once
        first = self.job('twin-first', 'echo once', digest='twin', memoize=True)
        second = self.job('twin-second', 'echo once', digest='twin', memoize=True)
        mechanisms.dispatch(self.db)
        self.assertEqual((self.state(first), self.state(second)), ('running', 'queued'))  # two slots, one run
        self.assertEqual(self.runner.once()['state'], 'succeeded')
        mechanisms.dispatch(self.db)
        self.assertEqual((self.state(second), self.runner.once()), ('succeeded', None))  # from the cache
        failing = self.job('twin-fails', 'exit 1', digest='twin-red', memoize=True)
        after = self.job('twin-after', 'exit 1', digest='twin-red', memoize=True)
        mechanisms.dispatch(self.db)
        self.assertEqual(self.runner.once()['state'], 'failed')
        mechanisms.dispatch(self.db)
        self.assertEqual((self.state(failing), self.state(after)), ('failed', 'running'))  # no answer: it runs

    def test_with_no_key_a_success_enters_no_cache(self):
        keyless = self.runner_with(lambda: None)
        self.job('unsigned-first', 'exit 0', digest='unsigned', memoize=True)
        mechanisms.dispatch(self.db)
        self.assertEqual(keyless.once()['state'], 'succeeded')
        self.assertEqual(self.db.rows('select count(*) from work.result_cache'), [('0',)])
        self.job('unsigned-second', 'exit 0', digest='unsigned', memoize=True)
        mechanisms.dispatch(self.db)
        self.assertEqual(keyless.once()['state'], 'succeeded')  # it ran again
        self.assertEqual(self.fetched, [COMMIT, COMMIT])


class Interruptions(RunnerWorld):
    def test_a_job_stopped_while_it_runs_ends_and_gives_its_slot_back(self):
        job = self.job('stopped', 'sleep 30')
        thread, ended = self.started(job)
        while self.state(job) != 'running' or not self.running(job):
            pass
        self.db.rows("update work.job set state = 'stopped' where id = %(id)s::uuid returning id", {'id': job})
        thread.join()
        self.assertEqual((ended['outcome'], self.state(job)), ('stopped', 'stopped'))
        self.assertEqual(self.db.rows("select in_use from work.capacity where executor = 'script-runner'"), [('0',)])

    def test_a_slow_setup_keeps_its_lease(self):
        reaped = []

        def slow(checkout):
            time.sleep(float('1.5'))  # past the second the lease lasts: only the renewals keep it
            reaped.extend(mechanisms.reap(self.db))
        worker = runner.Runner(self.db, self.fetch, slow, self.upload, self.workdir, lease='1 second',
                               renew_every_s=QUICK, signing_key=lambda: KEY)
        self.job('slow-setup', 'exit 0')
        mechanisms.dispatch(self.db, '1 second')
        self.assertEqual((worker.once()['state'], reaped), ('succeeded', []))

    def test_a_job_stopped_while_its_checkout_is_prepared_never_starts_its_command(self):
        job = self.job('stopped-early', 'echo started')

        def prepare(checkout):
            self.db.rows("update work.job set state = 'stopped' where id = %(id)s::uuid returning id", {'id': job})
            time.sleep(float('0.5'))  # renewals every 0.05 s: the keeper sees the stop
        worker = runner.Runner(self.db, self.fetch, prepare, self.upload, self.workdir, renew_every_s=QUICK)
        mechanisms.dispatch(self.db)
        ended = worker.once()
        self.assertEqual((ended['outcome'], ended['result']['tail'], self.state(job)),
                         ('stopped', 'the command did not start: the job is stopped\n', 'stopped'))
        self.assertEqual(self.db.rows("select in_use from work.capacity where executor = 'script-runner'"), [('0',)])

    def test_a_lease_lost_while_it_runs_leaves_the_run_to_the_reaper(self):
        job = self.job('lost', 'sleep 30')
        thread, ended = self.started(job)
        while not self.running(job):
            pass
        # The runner renews every QUICK seconds: under load a renewal can land between the expiry below and the reap, which then
        # finds a live lease ([] != [job], red on the infrastructure runner on 08/11). Expire again until the reap sees it.
        reaped = []
        for _ in range(200):
            self.db.rows("update work.job set lease_expires_at = now() - interval '1 second' where id = %(id)s::uuid "
                         "returning id", {'id': job})
            reaped = mechanisms.reap(self.db)
            if reaped:
                break
        self.assertEqual(reaped, [job])
        thread.join()
        self.assertEqual((ended['outcome'], self.state(job)), ('lost', 'queued'))

    def test_the_warning_s_time_is_set_before_the_slot_is_said_interrupted(self):
        """TERM-GRACE-RACE: interrupt() said `interrupted` and only then stamped when the warning came; the thread that
        waits on the run in flight asks overdue() between its slices, and one that asked between the two saw a warning
        with no time, which reads as a grace that is over: the run was killed at the warning, the loss the grace
        exists to prevent (the gate's red of 12/11 05:10 UTC on a loaded box). Here the clock itself asks, at the
        instant the warning's time is taken: not overdue, then and after."""
        seen = []
        self.runner.grace_s = 30.0
        self.runner.clock = lambda: (seen or seen.append(self.runner.overdue()), 100.0)[1]  # asks once, at the first reading
        self.runner.interrupt()
        self.assertEqual(seen[0], False)  # asked while the warning was being recorded
        self.assertEqual((self.runner.interrupted, self.runner.termed_at, self.runner.overdue()), (True, 100.0, False))

    def test_a_run_that_ends_in_the_grace_of_an_interruption_is_not_lost_and_the_slot_takes_no_more(self):
        # RUNNER-TERM-GRACE: live 12/11 01:20 UTC: Spot interrupted the runner and its four runs were killed at once, to
        # be run again by the task that came up three minutes later. The task has its StopTimeout (120 s) to leave
        # the warning comes once the command itself has started (its first line leaves a file): a run is `running` from
        # its claim, before its checkout is prepared, and a warning in between means a command that never starts, which is
        # lost by design. Waiting on `running` alone made this test red on a loaded runner (the gate, 12/11 07:05 UTC)
        started = Path(tempfile.mkdtemp(prefix='tower-test-grace-')) / 'started'
        self.addCleanup(shutil.rmtree, started.parent, True)
        job, later = self.job('ends-in-the-grace', f'touch {started}; sleep 1; echo done'), self.job('after-the-warning', 'true')
        mechanisms.dispatch(self.db)

        def interrupt():
            while not started.exists():
                time.sleep(0.01)
            os.kill(os.getpid(), signal.SIGTERM)  # Spot's warning, into the run
        threading.Thread(target=interrupt).start()
        self.runner.grace_s = 30.0
        self.runner.serve(threading.Event(), poll_s=QUICK)
        runs = self.db.rows('select outcome, error_type from work.run where job_id = %(id)s::uuid', {'id': job})
        self.assertEqual((runs, self.state(job)), ([('succeeded', None)], 'succeeded'))  # before: lost, interrupted
        self.assertTrue(self.runner.interrupted)
        # no run is taken after the warning: the one handed over stays for the next task (its lease gives it back)
        self.assertEqual(self.db.rows('select state from work.run where job_id = %(id)s::uuid', {'id': later}), [('starting',)])
        # (GATE-SHUTDOWN: the runner's task definition and its StopTimeout left 50-runner.json)

    def test_a_spot_interruption_ends_the_run_as_lost_and_the_job_is_dispatched_again(self):
        job = self.job('interrupted', 'sleep 30')
        mechanisms.dispatch(self.db)
        self.runner.grace_s = 0.5  # RUNNER-TERM-GRACE: a run that does not end in the grace is lost, as it always was

        def interrupt():
            while not self.running(job):
                pass
            os.kill(os.getpid(), signal.SIGTERM)  # what Fargate sends a Spot task before it stops
        threading.Thread(target=interrupt).start()
        self.runner.serve(threading.Event(), poll_s=QUICK)  # in the main thread, where SIGTERM is handled
        runs = self.db.rows('select outcome, error_type from work.run where job_id = %(id)s::uuid', {'id': job})
        attempts = self.db.rows('select attempts from work.job where id = %(id)s::uuid', {'id': job})
        self.assertEqual((runs, attempts, self.state(job)), ([('lost', 'interrupted')], [('0',)], 'queued'))
        self.assertEqual(self.db.rows("select in_use from work.capacity where executor = 'script-runner'"), [('0',)])
        self.assertEqual([run['job'] for run in mechanisms.dispatch(self.db)], [job])

    def test_an_idle_runner_waits_on_its_wake_and_a_run_handed_over_is_taken_at_once(self):
        # INFRA-SVC 5: the idle poll waits on the wake of tower_runs (migration 0006), not on a fixed poll
        stop, waited = threading.Event(), []
        job = self.job('woken', 'echo woken')

        def wake(timeout_s):
            waited.append(timeout_s)
            if len(waited) == 1:
                mechanisms.dispatch(self.db)  # a run handed over while the runner waits: the wake returns
            else:
                stop.set()
        self.runner.wait = wake
        self.runner.serve(stop, poll_s=QUICK)
        self.assertEqual((waited, self.state(job)), ([QUICK, QUICK], 'succeeded'))

    def slots(self):
        """Two slots of one task (INFRA-EXE 1e): the same fetch and prepare, a checkout each."""
        return [runner.Runner(self.db, self.fetch, self.prepare, self.upload, self.workdir, name=f'runner-of-the-test/{n}',
                              renew_every_s=QUICK, signing_key=lambda: KEY,
                              checkout_of=lambda spec, n=n: Path(self.workdir) / f'checkout-{n}')
                for n in range(len(('first', 'second')))]

    def test_two_slots_run_two_checks_at_once(self):
        # each check waits for the other to start, so they end only if the two slots run them side by side
        marks = Path(self.workdir) / 'marks'
        marks.mkdir()
        jobs = [self.job(name, f'touch {marks}/{name}; until [ -f {marks}/{other} ]; do sleep 0.01; done',
                         timeout_s=int('10'))
                for name, other in (('left', 'right'), ('right', 'left'))]
        stop, slots = threading.Event(), self.slots()

        def watch():
            while not all(self.state(job) in ('succeeded', 'failed') for job in jobs):
                mechanisms.dispatch(self.db)
                stop.wait(QUICK)
            stop.set()
        threading.Thread(target=watch, daemon=True).start()
        runner.serve_all(slots, stop, poll_s=QUICK)
        self.assertEqual([self.state(job) for job in jobs], ['succeeded', 'succeeded'])
        self.assertEqual(self.db.rows("select in_use from work.capacity where executor = 'script-runner'"), [('0',)])

    def test_one_interruption_stops_every_slot_and_their_runs_go_back_to_the_queue(self):
        jobs = [self.job(name, 'sleep 30') for name in ('one', 'two')]
        mechanisms.dispatch(self.db)

        def interrupt():
            while not all(self.running(job) for job in jobs):
                time.sleep(QUICK)
            os.kill(os.getpid(), signal.SIGTERM)  # what Fargate sends a Spot task: the main thread receives it
        threading.Thread(target=interrupt, daemon=True).start()
        slots = self.slots()
        for each in slots:
            each.grace_s = 0.5  # RUNNER-TERM-GRACE: past it
        runner.serve_all(slots, threading.Event(), poll_s=QUICK)
        self.assertTrue(all(each.interrupted for each in slots))
        self.assertEqual([self.state(job) for job in jobs], ['queued', 'queued'])
        self.assertEqual(self.db.rows("select in_use from work.capacity where executor = 'script-runner'"), [('0',)])

    def test_two_runners_never_take_the_same_run(self):
        self.job('once', 'exit 0')
        mechanisms.dispatch(self.db)
        first = runner.take(self.db, 'container', 'first')
        self.assertIsNotNone(first)
        self.assertIsNone(runner.take(self.db, 'container', 'second'))


class RunnerStackTests(unittest.TestCase):
    """infra/aws/stacks/50-runner.json since GATE-SHUTDOWN (D-314): the outputs bucket alone; the gate's runner is gone."""

    def setUp(self):
        self.template = load(STACKS / '50-runner.json')
        self.resources = self.template['Resources']

    def test_the_stack_is_the_outputs_bucket_and_its_tls_policy_both_retained(self):
        self.assertEqual(sorted(self.resources), ['Outputs', 'OutputsOnlyOverTls'])
        self.assertNotIn('AWS::ECS::Service', json.dumps(self.template))
        self.assertEqual({name: each['DeletionPolicy'] for name, each in self.resources.items()},
                         {'Outputs': 'Retain', 'OutputsOnlyOverTls': 'Retain'})
        self.assertEqual(self.template['Outputs']['OutputsBucket']['Export']['Name'], 'tower-runner-outputs-bucket')

    def test_the_bucket_is_private_encrypted_reached_over_tls_and_forgets_the_logs(self):
        bucket = self.resources['Outputs']['Properties']
        self.assertEqual(set(bucket['PublicAccessBlockConfiguration'].values()), {True})
        self.assertEqual(bucket['OwnershipControls'], {'Rules': [{'ObjectOwnership': 'BucketOwnerEnforced'}]})
        rule, = bucket['LifecycleConfiguration']['Rules']
        self.assertEqual((rule['Prefix'], rule['ExpirationInDays']), ('runs/', {'Ref': 'LogDays'}))
        deny, = self.resources['OutputsOnlyOverTls']['Properties']['PolicyDocument']['Statement']
        self.assertEqual((deny['Effect'], deny['Condition']), ('Deny', {'Bool': {'aws:SecureTransport': 'false'}}))


class ArtifactEnvTests(unittest.TestCase):
    """DEP8: only the gate's artifact job gets the bucket and the task role's credential pointer."""
    ENV = {'PATH': '/bin', 'HOME': '/root', 'TOWER_ARTIFACT_BUCKET': 'b', 'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI': '/v2/x',
           'AWS_REGION': 'us-east-1', 'TOWER_DB_URL': 'never'}

    def test_the_artifact_job_gets_the_bucket_and_the_credential_pointer(self):
        from tower_infra import runner
        env = runner.passed_env(['scripts/gate-check', 'artifact', 'lambda', '--base', 'abc'], self.ENV)
        self.assertEqual(env['TOWER_ARTIFACT_BUCKET'], 'b')
        self.assertEqual(env['AWS_CONTAINER_CREDENTIALS_RELATIVE_URI'], '/v2/x')
        self.assertNotIn('TOWER_DB_URL', env)

    def test_the_older_head_form_is_an_artifact_job_too(self):
        from tower_infra import runner
        env = runner.passed_env(['bash', '-c', 'x', 'gate-check', 'f' * 40, 'artifact', 'lambda'], self.ENV)
        self.assertIn('TOWER_ARTIFACT_BUCKET', env)

    def test_a_test_job_never_sees_them(self):
        from tower_infra import runner
        env = runner.passed_env(['scripts/gate-check', 'test', 'scripts/tests/x.test.sh'], self.ENV)
        self.assertEqual(set(env), {'PATH', 'HOME'})



if __name__ == '__main__':
    unittest.main()
