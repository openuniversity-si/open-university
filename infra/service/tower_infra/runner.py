"""The warm runner of the container executor (P4 F1; ARQUITETURA-ALVO §6): it runs a command on a checkout, for
scripts and checks, and relays what it used and how it ended.

The service's dispatcher claims a run for an executor whose adapter is container and leaves it handed over (no adapter
in the service: P3 F3). A runner takes one at a time: one statement locks a handed-over run whose lease is current and
relays run.running under its fencing token, so two runners never take the same run. A task runs several, its slots
(serve_all, INFRA-EXE 1e), each with its own checkout, connection and wake. The job's input is a data: URI of
JSON: {"repo": "org/name", "ref": "<branch>", "commit": "<full sha>", "base": "<full sha, optional>", "command":
["scripts/run", "test", "x"], "timeout_s": 900, "env": {}}. While a keeper renews the lease for the whole run (work.renew_lease, 0004; a cold setup
takes minutes), the runner checks the commit out (fetch), prepares the pinned toolchain (prepare, cached by manifest),
runs the command with its timeout, relays the CPU seconds it used (the meter cpu_s) and ends the run: succeeded on exit
0, failed with exit_<code>, timed_out or not_started otherwise, with the log kept by upload and its tail in the result.
A success is signed for the cache (ARQUITETURA-ALVO §8: the output that enters it is signed by the executor): an
HMAC-SHA256 of the executor, the input's digest and the result, with the key signing_key answers when the run ends; with
no key the run still succeeds and nothing enters the cache. A job stopped or cancelled while it runs kills the command
and ends the run with that outcome, giving the slot back; a lease that is gone (the reaper gave the job to another run)
kills it and leaves the run alone. A setup that failed only for the environment (an Unprepared with retryable: the toolchain's download) ends the run
as lost as well, while the job has had fewer than lost_limit runs, so a cold task's network trouble is not a verdict on the code;
the last run says not_started. A Spot interruption (SIGTERM, about two minutes before the task stops) kills the
command and ends the run as lost, so the job goes back to its queue at once without spending an attempt, and serve stops
taking runs. fetch (the commit checked out, clean, at a checkout the runner keeps between runs), prepare and upload are
the caller's (the image's git, setup.sh and S3 in container.py; the gate's test gives local ones). The command's
environment carries only the runner's PASSED variables and the job's env, never a credential of the runner's. The
database is any object with rows(sql, params). Standard library only.
"""
import fcntl
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import resource
import signal
import subprocess
import threading
import time

from . import forge, live_image, mechanisms

# RUNNER-OWN-LOGIN: the TAKE is the owner's function (migration 0019, where its statement is): it locks the run it
# picks, which a login that owns nothing may not do by itself. The next handed-over run of the adapter's executors, now
# running under this runner (run.running relayed, fenced); no row when there is none
TAKE = 'select * from work.take_run(%(adapter)s, %(runner)s)'
RENEW = 'select work.renew_lease(%(run)s::uuid, %(fence)s::bigint, %(lease)s::interval)'
# CANCEL-WAKES-RUNNER: of the runs in flight in this process, the ones whose job is no longer open (cancelled, stopped)
ENDED_JOBS = ("select lease_run_id::text, state from work.job where lease_run_id = any(string_to_array(%(runs)s, ',')::uuid[]) "
              "and state in ('cancelled', 'stopped')")
SHA = re.compile(r'^[0-9a-f]{40}$')
TAIL_CHARS = 2000
# PLAN-ON-RUNNER: a run's command may answer a JSON object in the file this names (the gate's plan): it comes back as the
# result's `answer`, beside the tail a log is cut to; ANSWER_MAX bytes at most. PLAN-ANSWER: 512 KiB, not 64: the
# pre-gate's `plan jobs` carries every check job's body (~0.8 KB each), and a PR touching the shared libraries (#671 on
# 13/11: 93 jobs, 88 470 bytes) was refused at its push, so its delivery found nothing made (0 of 97 from the cache,
# 176.9 s); the whole battery's plan is ~170 KB
ANSWER_ENV, ANSWER_MAX = 'TOWER_ANSWER_FILE', 524288
# CHECK-NOT-ROOT (revisão da arquitetura, achado 14; the Torre's item 2 of 13/11 12:10 BRT): a check's command runs as
# CHECK_USER, not as the runner's uid 0, when the task says so (TOWER_CHECK_USER) or the job asks for it (a job may only
# drop to it: no job makes a command run as root). The runner's own environment, the forge's key and the signing key are
# then out of the command's reach (/proc/<pid>/environ of a root process is not readable by another uid)
CHECK_USER, CHECK_USER_ENV = 'tower-check', 'TOWER_CHECK_USER'
OPEN = ('running', 'waiting')
PASSED = ('PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ', 'TMPDIR', 'USER', 'LOGNAME', 'SHELL')
# DEP8: only the gate's artifact job (scripts/gate-check artifact ...) uploads the Lambda packages, so only it gets the
# bucket and the task role's credential pointer; a PR's tests never see them in their environment.
ARTIFACT_PASSED = ('TOWER_ARTIFACT_BUCKET', 'AWS_CONTAINER_CREDENTIALS_RELATIVE_URI', 'AWS_CONTAINER_CREDENTIALS_FULL_URI',
                   'AWS_CONTAINER_AUTHORIZATION_TOKEN', 'AWS_REGION', 'AWS_DEFAULT_REGION')


def answered(path):
    """PLAN-ON-RUNNER: the JSON object a run's command wrote to its answer file (removed after), or None for none; one
    too large or not an object is said as a refusal, never as an answer."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size == 0:  # CHECK-NOT-ROOT: the file made ready for a check user's command, which wrote nothing in it
        path.unlink(missing_ok=True)
        return None
    try:
        if size > ANSWER_MAX:
            return {'refused': f'the answer is {size} bytes, over {ANSWER_MAX}'}
        said = json.loads(path.read_text(errors='replace'))
        return said if isinstance(said, dict) else {'refused': 'the answer is not a JSON object'}
    except ValueError:
        return {'refused': 'the answer is not JSON'}
    finally:
        path.unlink(missing_ok=True)


# UID0-FROM-BASE (the Torre, 13/11 ~14:15 BRT): a job may ask for root (the uid 0 probe: postgres, git and npm by a real uid 0
# process) only to run code that landed: a commit the forge pushed to the base branch (forge.repository.pushed, the merge a
# gate passed), never a PR's head. Any other ask of root runs as the check user.
BASE_REF = 'refs/heads/mod/roadmap-integration'
LANDED = ("select exists (select 1 from log.event where type = 'forge.repository.pushed' "
          "and (payload #> '{delivery,event,payload,refUpdates}') @> jsonb_build_array(jsonb_build_object("
          "'ref', %(ref)s::text, 'after', %(sha)s::text)) "
          "and payload #>> '{delivery,event,payload,repository,owner,slug}' || '/' "
          "|| (payload #>> '{delivery,event,payload,repository,name}') = %(repo)s)")


def check_user(spec, environ=None, euid=None, landed=None):
    """CHECK-NOT-ROOT: the user a run's command runs as (the check user, when the task or the job asks and the runner is
    root), or None for the runner's own. UID0-FROM-BASE: a job that asks for root has it only for a commit landed(sha)
    says landed, else the check user; a job that asks for any other user than the check user gets the task's choice."""
    environ = os.environ if environ is None else environ
    euid = os.geteuid() if euid is None else euid
    if euid != 0:
        return None  # a runner that is no root drops nothing
    asked = str(spec.get('user') or '').strip()
    if asked == 'root':
        return None if landed is not None and landed(str(spec.get('commit') or '')) else CHECK_USER
    if asked == CHECK_USER:
        return CHECK_USER
    return CHECK_USER if str(environ.get(CHECK_USER_ENV) or '').strip() == CHECK_USER else None


def hand_over(checkout, user, run=subprocess.run):
    """CHECK-NOT-ROOT: the checkout made the check user's for its run (what the command writes, git's index included);
    answers the user's (uid, gid, home)."""
    import pwd
    found = pwd.getpwnam(user)
    run(['chown', '-R', f'{found.pw_uid}:{found.pw_gid}', str(checkout)], check=True, capture_output=True)
    # CHECK-USER-SHARED: the toolchain the checkout links (.toolchain -> the task's cache by the manifests' digest) is the
    # check user's directory too, not its tree: the project's PostgreSQL keeps its data there (pgdata, owned by its own
    # account), and the setup's probe writes in the directory itself (`missing writable path: .toolchain` as tower-check)
    # TOOLCHAIN-TAKE-BACK: never back to root: the directory is every slot's, root writes in it whoever owns it, and a slot
    # taken back for a root run (the uid-0 probe of the full run) took it from the check user's tests running in the other
    # slots at that instant (`missing writable path: .toolchain` in test_claude_session, the full runs of 13/11 22:20 and
    # 22:31 UTC; a probe job as tower-check found it its own and writable at 22:40)
    shared = os.path.join(str(checkout), '.toolchain')
    if found.pw_uid != 0 and os.path.islink(shared) and os.path.isdir(shared):
        os.chown(os.path.realpath(shared), found.pw_uid, found.pw_gid)
    return found.pw_uid, found.pw_gid, found.pw_dir


def passed_env(command, environ=None):
    """The environment a run's command gets: the plain PASSED names, plus ARTIFACT_PASSED for the gate's artifact job."""
    environ = os.environ if environ is None else environ
    names = PASSED
    argv = [str(each) for each in command] if isinstance(command, (list, tuple)) else str(command).split()
    # ['scripts/gate-check', 'artifact', ...] or the older-head form ['bash', '-c', TOOL_OF, 'gate-check', <sha>, 'artifact', ...]
    tool = next((index for index, each in enumerate(argv) if each.endswith('gate-check')), None)
    if tool is not None and 'artifact' in argv[tool + 1:tool + 3]:
        names = PASSED + ARTIFACT_PASSED
    return {name: environ[name] for name in names if name in environ}
LOG = logging.getLogger('tower_infra.runner')
# RUNNER-TERM-GRACE: how long a run in flight may go on after the task was asked to stop (SIGTERM: Spot's two-minute
# warning, a rollout's stop), under the task's StopTimeout (120 s, 50-runner.json): what ends by then ended, the rest is
# lost as before. And how often the command's wait looks at it
TERM_GRACE_S, WAIT_SLICE_S = 100.0, 2.0
# SPOT-KEEP: at Spot's warning the task's process keeps taking runs until the task ECS starts in its place says it is
# up, KEEP_S at most (TOWER_SPOT_KEEP_S); it asks every KEEP_TICK_S. REPLACED: a runner task other than this one said
# platform.deploy.task_up after this one did (a rollout's new task is up before the old one is stopped: at once)
KEEP_S, KEEP_TICK_S = 'TOWER_SPOT_KEEP_S', 2.0
REPLACED = ("select exists (select 1 from log.event e where e.type = 'platform.deploy.task_up' and e.tenant_id is null "
            "and e.payload->>'role' = 'runner' and e.payload->>'task' <> %(task)s and e.occurred_at > coalesce("
            "(select max(m.occurred_at) from log.event m where m.type = 'platform.deploy.task_up' and m.tenant_id is null "
            "and m.payload->>'role' = 'runner' and m.payload->>'task' = %(task)s), now() - interval '1 hour'))")


def watch_cancels(runners, wait, db_of, stop, check_s=60.0):
    """CANCEL-WAKES-RUNNER (criterion 3): a job cancelled while it runs (a full run's test taken back for a gate's job,
    mechanisms.PREEMPT) is heard at once: job.cancelled notifies tower_runs (migration 0022), this thread wakes, reads which
    of the process's runs in flight have a job no longer open, and kills those commands as the keeper does at its renewal
    (verdict cancelled or stopped), so the slot is free for the gate's job in a second, not at the next renewal (60 s:
    #684's artifact job waited 82.6 s). A daemon thread; the keepers' renewals stay the backstop."""
    import threading

    def loop():
        while not stop.is_set():
            wait(check_s)
            flying = {each.current[0]['run']: each for each in runners if getattr(each, 'current', None)}
            if not flying:
                continue
            try:
                with db_of() as db:
                    ended = db.rows(ENDED_JOBS, {'runs': ','.join(flying)})
            except Exception:  # noqa: BLE001 - the next wake reads again; the renewal is the backstop
                LOG.exception('runner: the cancelled runs were not read')
                continue
            for ident, state in ended:
                each = flying.get(ident)
                current = getattr(each, 'current', None)
                if current and current[0]['run'] == ident:
                    current[1]['state'] = state
                    each.kill()
                    LOG.info('runner: %s %s: its command stopped at once', ident, state)
    thread = threading.Thread(target=loop, name='cancels', daemon=True)
    thread.start()
    return thread


def take(db, adapter, runner):
    """The next handed-over run of the adapter's executors, now running under this runner; None when there is none."""
    found = db.rows(TAKE, {'adapter': adapter, 'runner': runner})
    if not found or found[0][-1] not in (True, 't'):
        return None
    run, job, fence, uri, digest, executor, n, _ = found[0]
    return {'run': run, 'job': job, 'fence': int(fence), 'input_uri': uri, 'input_digest': digest,
            'executor': executor, 'n': int(n)}


def renew(db, run, lease):
    """The job's state after renewing its lease, or None when the lease is no longer this run's."""
    return db.rows(RENEW, {'run': run['run'], 'fence': run['fence'], 'lease': lease})[0][0]


def signature(key, executor, digest, result):
    """The HMAC-SHA256 of an output for the cache, over its executor, its input's digest and the result in canonical
    JSON; None with no key."""
    if not key:
        return None
    body = json.dumps({'executor': executor, 'input_digest': digest, 'result': result}, sort_keys=True,
                      separators=(',', ':'))
    return hmac.new(key if isinstance(key, bytes) else key.encode('utf-8'), body.encode('utf-8'),
                    hashlib.sha256).digest()


def verified(key, executor, digest, result, signed):
    """Whether a cached output carries the signature of the key's holder."""
    expected = signature(key, executor, digest, result)
    return bool(expected and signed) and hmac.compare_digest(expected, bytes(signed))


def understood(spec):
    command = spec.get('command') if isinstance(spec, dict) else None
    return bool(isinstance(command, list) and command and all(isinstance(part, str) for part in command)
                and SHA.match(str(spec.get('commit'))) and forge.REPO.match(str(spec.get('repo')))
                and (spec.get('base') is None or SHA.match(str(spec['base'])))
                and isinstance(spec.get('env') or {}, dict))


class Runner:
    def __init__(self, db, fetch, prepare, upload, workdir, name='runner', adapter='container', lease='5 minutes',
                 renew_every_s=60.0, signing_key=None, checkout_of=None, beat=None, wait=None, lost_limit=3, gate=None,
                 reload=None, order=None, held=None, grace_s=TERM_GRACE_S, clock=time.monotonic):
        self.db, self.fetch, self.prepare, self.upload = db, fetch, prepare, upload
        self.workdir, self.name, self.adapter = Path(workdir), name, adapter
        self.lease, self.renew_every_s, self.signing_key = lease, renew_every_s, signing_key
        self.current = None  # CANCEL-WAKES-RUNNER: (run, verdict) while a run is in flight
        self.checkout_of = checkout_of or (lambda spec: self.workdir / 'checkout')
        self.beat = beat or (lambda: None)  # the health check's heartbeat: every idle poll and every renewal
        self.wait = wait  # an idle poll's wait: a wake on the runs that start (tower_infra.wake), else the stop event's
        self.interrupted, self.child, self.lost_limit = False, None, lost_limit
        # RUNNER-TERM-GRACE: when the stop was asked, and whether it killed the command (a run that ended by itself in
        # the grace is not lost)
        self.grace_s, self.clock, self.termed_at, self.killed = grace_s, clock, None, False
        self.passed = None  # SUCCESSOR-BACK-FASTER: called once after this slot's first good pass
        self.gate = gate  # IMAGE-PREWARM-A: live_image.Gate, None (no TOWER_IMAGE_DIGEST) takes runs as always
        self.reload = reload  # IMAGE-SWAP-RELOAD: live_image.Reload, the task's (its slots share it); None never reloads
        self.order = order  # RELOAD-WITHOUT-STANDBY: live_image.Order, the task's (shared too); None follows no order
        self.held = held  # IN-TASK-STANDBY: Held, this slot's checkout among the task's processes; None: the only process
        if order is not None:  # and no beat from a reload by order until its judge says proven: what does not prove itself
            self.beat = lambda beat=self.beat: order.trusted() and beat()  # and does not go back, ECS replaces

    def interrupt(self, *_):
        """The task was asked to stop (the SIGTERM handler: Spot's warning, a rollout): this slot takes no more runs.
        RUNNER-TERM-GRACE: the command in flight goes on for grace_s (the task has its StopTimeout to leave): on 12/11
        01:20 UTC Spot interrupted the runner and its four runs were killed at once and lost, to be run again by the task
        that came up three minutes later; most checks end in under a minute. The command's own wait kills what is left
        when the grace is over (command()); a second signal, or no grace, kills it now. Plain flags and a kill,
        nothing that takes a lock the interrupted thread may hold."""
        again = self.interrupted
        if not again and self.grace_s > 0:
            # TERM-GRACE-RACE: the warning's time before the flag: the thread that waits on the run asks overdue()
            # between its slices, and a warning with no time yet read as a grace that was over (the run killed at the
            # warning, the loss the grace exists to prevent). SPOT-KEEP: the grace counts from the warning, not from
            # the end of the keeping: ECS's SIGKILL comes StopTimeout (120 s) after the warning, whatever came between
            self.termed_at = self.clock() if self.termed_at is None else self.termed_at
        self.interrupted = True
        if again or self.grace_s <= 0:
            return self.kill(interrupted=True)

    def overdue(self):
        """RUNNER-TERM-GRACE: the stop was asked and its grace is over."""
        return self.interrupted and (self.termed_at is None or self.clock() - self.termed_at >= self.grace_s)

    def kill(self, interrupted=False):
        child = self.child
        if child is not None and child.returncode is None:
            self.killed = self.killed or interrupted
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def keep(self, run, stop, verdict):
        """Renew the lease for as long as the run lasts, fetch and setup included (a cold setup takes minutes), and
        beat; a job no longer open (stopped, cancelled) or a lease that is gone kills the command, or keeps it from
        starting. IMAGE-SWAP-FAILOVER: while the pointer names this image the keeper wakes sooner (Gate.pace) for the
        live beat, so a runner whose slots are all busy with long runs never looks dead; the renewals keep their pace."""
        waited = 0.0
        while True:
            pace = self.renew_every_s if self.gate is None else self.gate.pace(self.renew_every_s)
            if stop.wait(pace):
                return
            if self.gate is not None:
                self.gate.live_beat(self.db)
            waited += pace
            if waited < self.renew_every_s:
                continue
            waited = 0.0
            try:
                state = renew(self.db, run, self.lease)
            except Exception:  # noqa: BLE001 - one failed renewal is retried at the next; the lease is the backstop
                LOG.exception('runner: the lease of %s was not renewed', run['run'])
                continue
            if state not in OPEN:
                verdict['state'] = state or 'lost'
                self.kill()
                return
            self.beat()

    def once(self):
        """Take and run one handed-over run; answers how it ended, or None when there was nothing to take."""
        gate = self.gate
        if gate is None:
            run = take(self.db, self.adapter, self.name)
        else:
            began = gate.clock()
            getattr(self.db, 'ready', lambda: None)()  # IMAGE-SWAP-TICK: the slot's kept connection (container.Reconnecting)
            ready = gate.clock()
            run = take(self.db, self.adapter, self.name)
            # IMAGE-SWAP-TIGHTEN: the first TAKE after a swap is when this image works (image_live). IMAGE-SWAP-TICK: its
            # parts: the slot's wake, connect_s (a usable connection: 0 on the kept one) and take_s (the TAKE's round trip)
            # SWAP-RECORD-WARM: recorded on this slot's connection, which rehearsed the record while it stood by
            gate.working(began=began, db=self.db, connect_s=ready - began, take_s=gate.clock() - ready)
            gate.live_beat(self.db)  # IMAGE-SWAP-FAILOVER: a good TAKE is the live beat while the pointer names it
            gate.back(self.db)  # IMAGE-SWAP-RELOAD: a reloaded task's first TAKE is recorded and it takes the role over
            gate.cover(self.db)  # SUCCESSOR-LOST: a process that covers for a successor that ended looks when to stop
        return None if run is None else self.execute(run)

    def execute(self, run):
        spec = forge.decode(run['input_uri'])
        if not understood(spec):
            return self.end(run, 'failed', 'not_understood', {'detail': 'a container job needs repo, commit, command'})
        checkout, log = self.checkout_of(spec), self.workdir / f"{run['run']}.log"
        code, outcome, environmental = None, 'failed', False
        stop, verdict = threading.Event(), {}
        self.current = (run, verdict)  # CANCEL-WAKES-RUNNER: watch_cancels reads it
        keeper = threading.Thread(target=self.keep, args=(run, stop, verdict), daemon=True)
        keeper.start()
        parts, mark = {}, self.clock()  # HEAD-ON-PUSH: the run's parts, said in its result
        answer = self.workdir / f"{run['run']}.answer"  # PLAN-ON-RUNNER
        answer.unlink(missing_ok=True)
        spec = dict(spec, env={**(spec.get('env') or {}), ANSWER_ENV: str(answer)})

        def part(name):
            nonlocal mark
            now = self.clock()
            parts[name] = round(now - mark, 3)
            mark = now
        try:
            if not self.interrupted:
                how = self.fetch(spec, checkout)
                part('fetch_s')
                if isinstance(how, str):
                    parts['head'] = how  # here, sibling or forge
                self.prepare(checkout)
                part('prepare_s')
            if not (self.interrupted or verdict):
                code, outcome = self.command(run, spec, checkout, log)
                part('command_s')
        except Exception as error:  # noqa: BLE001 - a run that cannot start is a failed run, named
            log.write_text(f'{type(error).__name__}: {error}\n')
            environmental = bool(getattr(error, 'retryable', False))
        finally:
            self.current = None
            stop.set()
            keeper.join()
        # RUNNER-TERM-GRACE: interrupted is a command the stop killed, or one that never started; a command that ended
        # by itself in the grace ended as it did
        cut = self.killed or (self.interrupted and code is None)
        outcome = 'interrupted' if cut else verdict.get('state', outcome)
        if outcome in ('lost', 'interrupted'):
            log.unlink(missing_ok=True)
            if outcome == 'interrupted':
                return self.end(run, 'lost', 'interrupted', None)
            return {'outcome': 'lost', 'run': run['run']}
        if environmental and outcome == 'failed' and run['n'] <= self.lost_limit:
            LOG.warning('runner: run %s of %s could not be prepared (%s): lost, the job goes back to its queue',
                        run['run'], run['job'], log.read_text(errors='replace')[-200:].strip())
            log.unlink(missing_ok=True)
            return self.end(run, 'lost', 'unprepared', None)
        if not log.exists():  # stopped or cancelled before its command started
            log.write_text(f'the command did not start: the job is {outcome}\n')
        tail = log.read_text(errors='replace')[-TAIL_CHARS:]
        result = {'exit': code, 'log_uri': self.upload(run, log), 'tail': tail}
        part('upload_s')
        result['parts'] = parts
        said = answered(answer)
        if said is not None:
            result['answer'] = said
        log.unlink(missing_ok=True)
        error = {'succeeded': None, 'timed_out': 'timed_out', 'stopped': 'stopped', 'cancelled': 'cancelled'}.get(
            outcome, f'exit_{code}' if code is not None else 'not_started')
        return self.end(run, outcome, error, result)

    def landed(self, sha):
        """UID0-FROM-BASE: whether the forge pushed `sha` to the base branch of this repository (the log's
        forge.repository.pushed: what a gate passed and the forge merged)."""
        if not SHA.match(sha):
            return False
        from .pregate import REPO
        return self.db.rows(LANDED, {'ref': BASE_REF, 'sha': sha, 'repo': REPO})[0][0] in (True, 't')

    def command(self, run, spec, checkout, log):
        """Run the command in its own process group with its timeout; (exit code, outcome), with the CPU seconds it
        used relayed (fenced: a run whose lease is gone relays nothing)."""
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        env = passed_env(spec['command'])
        env.update({str(name): str(value) for name, value in (spec.get('env') or {}).items()})
        drop = {}
        user = check_user(spec, landed=self.landed)
        if not user and os.geteuid() == 0 and os.stat(checkout).st_uid != 0:
            # CHECK-USER-SHARED: a slot a check user's run had (a full run's job, as tower-check) is root's again for a
            # run as root: git refuses a repository another uid owns (`dubious ownership`) when its system config, the
            # image's safe.directory, is off (a test's hermetic git: #670's gate, 13/11). Only then: no chown otherwise
            hand_over(checkout, 'root')
        if user:  # CHECK-NOT-ROOT
            uid, gid, home = hand_over(checkout, user)
            answer = env.get(ANSWER_ENV)
            if answer:  # the runner's directory is not the check user's: the answer is written in one of its own, moved after
                import tempfile
                own = tempfile.mkdtemp(prefix='tower-answer-', dir='/tmp')  # not TMPDIR: a runner's may be private to it
                os.chown(own, uid, gid)
                env[ANSWER_ENV] = os.path.join(own, 'answer')
                drop['answered'] = (env[ANSWER_ENV], answer)
            env.update({'HOME': home, 'USER': user, 'LOGNAME': user})
            drop.update({'user': uid, 'group': gid, 'extra_groups': [], 'umask': 0o022})
        moved = drop.pop('answered', None)
        try:
            return self.wait_command(run, spec, checkout, log, env, drop, before)
        finally:
            if moved:  # CHECK-NOT-ROOT: the check user's answer, where the runner reads it
                import shutil
                if os.path.exists(moved[0]):  # another file system than the runner's, maybe: moved, not renamed
                    shutil.move(moved[0], moved[1])
                shutil.rmtree(os.path.dirname(moved[0]), ignore_errors=True)

    def wait_command(self, run, spec, checkout, log, env, drop, before):
        with open(log, 'w') as out:
            process = subprocess.Popen(spec['command'], cwd=checkout, stdout=out, stderr=subprocess.STDOUT,
                                       start_new_session=True, env=env, **drop)
            self.child = process
            limit, began = float(spec.get('timeout_s') or 900), self.clock()
            try:
                while True:  # RUNNER-TERM-GRACE: the wait in slices, so a stop's grace that is over is seen
                    if self.overdue():  # (also the signal that came before the child was known, with no grace)
                        self.kill(interrupted=True)
                    left = limit - (self.clock() - began)
                    if left <= 0:
                        raise subprocess.TimeoutExpired(spec['command'], limit)
                    try:
                        code = process.wait(timeout=min(left, WAIT_SLICE_S))
                        break
                    except subprocess.TimeoutExpired:
                        continue
                outcome = 'succeeded' if code == 0 else 'failed'
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                code, outcome = process.wait(), 'timed_out'
            finally:
                self.child = None
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        used = round((after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime), 3)
        mechanisms.relay(self.db, run['run'], run['fence'], 'run.usage', {'meter': 'cpu_s', 'quantity': used})
        return code, outcome

    def end(self, run, outcome, error, result):
        key = self.signing_key() if self.signing_key and outcome == 'succeeded' else None
        signed = signature(key, run['executor'], run['input_digest'], result)
        state = mechanisms.end(self.db, run['run'], run['fence'], outcome, error, result, signed)
        return {'outcome': outcome, 'error': error, 'state': state, 'run': run['run'], 'result': result}

    def serve(self, stop, poll_s=1.0):
        """Take runs until stop is set or the Spot interruption comes (SIGTERM, handled here: serve runs in the main
        thread)."""
        serve_all([self], stop, poll_s)

    def loop(self, stop, poll_s=1.0):
        """One slot's work: take runs until stop is set or this runner is interrupted."""
        while not stop.is_set() and not self.interrupted:
            if self.gate is not None and not self.gate.active():  # IMAGE-PREWARM-A: not the live image
                # the pointer left this promoted standby: the run in flight is done, the slot ends. IMAGE-SWAP-FAILOVER:
                # an ECS task (not strict) the pointer leaves stays, standing by: it is who takes the role back
                if self.gate.retired and self.gate.strict:
                    LOG.info('runner: %s is no longer the live image; the slot ends', self.name)
                    return
                if getattr(self.gate, 'gone', False):  # IN-TASK-STANDBY: the role was given to the task's successor:
                    return  # the run in flight is done, the slot ends, and the process with its last slot
                self.standby(stop, poll_s)
                continue
            try:
                # IMAGE-SWAP-RELOAD: the pass, its run included, is work in flight; none starts once a reload holds the gate
                with live_image.engaged(self.gate, self.name) as free:
                    # IN-TASK-STANDBY: not while another process of the task still runs in this slot's checkout
                    if free and self.held is not None and not self.held.take():
                        free = False
                        # PROMOTED-RUNNER-WAITS-ALIVE: the process holds the role and waits for this checkout, which
                        # a run of the process before it still uses: alive, so its live beat goes on (with every slot
                        # waiting no TAKE sent one, and the ECS task's watchdog took the swap back at 58 s: live 11/11)
                        if self.gate is not None:
                            self.gate.live_beat(self.db)
                    try:
                        took = self.once() if free else None
                    finally:
                        if free and self.held is not None:
                            self.held.give()
                self.beat()  # a good pass, idle or not, keeps the health check fresh; a failing one does not
                passed, self.passed = self.passed, None  # SUCCESSOR-BACK-FASTER: its first pass is said once (serve_all)
                if passed is not None:
                    passed()
                if self.order is not None:  # RELOAD-WITHOUT-STANDBY: the look at an order to load a landed bundle in
                    self.order.step(self.db)  # place: no statement unless one is owed; the exec does not return
            except Exception:  # noqa: BLE001 - a run left half-way is fenced by its lease; the reaper takes it
                LOG.exception('runner: a run failed on the way')
                took = None
            if took is None and not self.interrupted:
                (self.wait or stop.wait)(poll_s)

    def standby(self, stop, poll_s):
        """IMAGE-PREWARM-A: one pass of a standby slot: no run is claimed, the database answers and the health check
        stays fresh (the pointer may name this image only while it is healthy); then wait until the image turns live.
        IMAGE-SWAP-TIGHTEN: the pass's round trip is the beat in work.standby_beat, the landing's evidence of health.
        IMAGE-SWAP-FAILOVER: an ECS task's beat also watches the live image and fails the role over (Gate.beat).
        IMAGE-SWAP-RELOAD: then the reload's look (live_image.Reload): under a swapped bundle, once no slot of the task
        has a run in flight, the task execs that bundle in place (no return) and takes the role over."""
        try:
            self.gate.beat(self.db)
            warm = getattr(self.gate, 'warm', None)  # SWAP-TAIL-CUT: the slot's first TAKE, rolled back, on its connection
            if warm is not None:
                warm.step(self.db)
            self.beat()
            if self.wait is not None:  # IMAGE-SWAP-TICK: the slot's wake listens while it stands by, drained every pass:
                self.wait(0)  # its first idle wait after the swap is no login and sees a run handed over meanwhile
            if self.reload is not None and not self.interrupted and not stop.is_set():
                self.reload.step(self.db)
        except Exception:  # noqa: BLE001 - a standby that cannot reach the database is not healthy: no beat
            LOG.exception('runner: a standby pass failed')
        if not stop.is_set():
            self.gate.wait(poll_s)


class Held:
    """IN-TASK-STANDBY: the checkout of a slot belongs to one process of the task at a time. A successor's slots use
    the checkouts its task keeps (warm: no clone, no setup again); the process it replaces may still have a run in one
    when the successor takes the role, so each pass holds its slot's lock (flock: a dead process holds nothing) from
    before its TAKE to the end of its run. A slot whose lock another process holds takes nothing on that pass: the
    other slots take the new runs, and this one joins when that run ends."""

    def __init__(self, workdir, slot):
        self.path, self.fd, self.failed = Path(workdir) / 'checkouts' / f'.slot-{slot}.lock', None, False

    def take(self):
        try:
            if self.fd is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        except OSError:  # a disk that cannot lock never stops the runner: it works as the task's only process did
            if not self.failed:
                LOG.exception('runner: %s cannot be locked; the slot works without it', self.path)
            self.failed = True
        return True

    def give(self):
        if self.fd is not None and not self.failed:
            fcntl.flock(self.fd, fcntl.LOCK_UN)


STAGGER_S = 1.0  # SUCCESSOR-BACK-FASTER: the longest the other slots wait for the first slot's first pass


def keep(runners, interrupt, replaced, keep_s, clock=time.monotonic, tick_s=KEEP_TICK_S, start=None, said=None,
         wait=time.sleep):
    """SPOT-KEEP: the SIGTERM handler of the task's process of the runner (Spot's warning, a rollout's stop). Spot warns
    two minutes ahead (StopTimeout 120 s) and ECS starts the task that takes this one's place at the warning; the
    process left within seconds, and the role had no runner until that task was up (12/11: 144 s at 17:28 UTC, ~110 s
    at 19:27 UTC). Now the slots go on taking runs until replaced() (the new task said it is up: at once in a
    rollout, whose new task is up first) or keep_s passed, and then are interrupted as before. The grace of a run in
    flight counts from the warning (Runner.interrupt), so what is taken meanwhile ends before ECS's SIGKILL or is
    lost and run again, as at the warning before. A second signal interrupts at once. said(kept_s, replaced) when it
    ends. The handler only sets an event; a thread started here, before any signal, does the rest."""
    warned, now = threading.Event(), []

    def watch():
        warned.wait()
        found = False
        while clock() - now[0] < keep_s:
            try:
                found = bool(replaced())
            except Exception:  # noqa: BLE001 - not known: keep until the limit, as a task that is not replaced yet
                LOG.exception('runner: could not read whether the task that replaces this one is up')
            if found:
                break
            wait(tick_s)
        LOG.warning('runner: warned %.1f s ago; %s: the slots take no more runs', clock() - now[0],
                    'the task in its place is up' if found else 'no task in its place yet')
        if said is not None:
            said(round(clock() - now[0], 3), found)
        interrupt()
    (start or (lambda target: threading.Thread(target=target, name='spot-keep', daemon=True).start()))(watch)

    def handler(*_):
        if warned.is_set():  # a second signal: now
            return interrupt()
        now.append(clock())
        for each in runners:  # the grace of what runs counts from now
            if each.termed_at is None:
                each.termed_at = now[0]
        LOG.warning('runner: warned of its stop: it takes runs until the task in its place is up (%.0f s at most)', keep_s)
        warned.set()
    return handler


def serve_all(runners, stop, poll_s=1.0, term=None, staggered=False):
    """Each runner is one slot of the task (INFRA-EXE 1e): the first takes runs in the main thread, the others each in a
    thread of its own, and the Spot interruption (SIGTERM, which only the main thread receives) interrupts every one.
    IMAGE-SWAP-FAILOVER: term(interrupt) gives the SIGTERM handler (live_image.on_term: a promoted standby hands its
    pointer back before its slots are interrupted); with none it is the interruption itself, as before."""
    def interrupt(*_):
        for each in runners:
            each.interrupt()
    previous = signal.signal(signal.SIGTERM, interrupt if term is None else term(interrupt))
    try:
        # SUCCESSOR-BACK-FASTER: staggered (a successor the role is waiting for): the other slots start once the first
        # one passed (its login alone, its first TAKE), STAGGER_S at most: four logins at once on the db.t4g.micro take
        # 0.4 to 1.2 s each, one alone 0.06 to 0.17 s
        opened = threading.Event()
        if staggered:
            runners[0].passed = opened.set
        else:
            opened.set()

        def later(each):
            opened.wait(STAGGER_S)
            each.loop(stop, poll_s)
        others = [threading.Thread(target=later, args=(each,), name=f'slot-{n}', daemon=True)
                  for n, each in enumerate(runners[1:], start=1)]
        for thread in others:
            thread.start()
        runners[0].loop(stop, poll_s)
        for thread in others:
            thread.join()
    finally:
        signal.signal(signal.SIGTERM, previous)
