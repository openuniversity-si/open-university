"""The Tower runner (GATE-TRAIN-SERVICES R1, R2; D-086, ADR-41, D-290, D-291): the gate and the train on any machine, no AI session.

`scripts/service runner [--once] [--http PORT]` runs in a checkout on train.base_branch: the box, a free VM, a hosted
job (a Claude Code session only as the last resort). Each poll (service.poll_s) it:
  1. unless service.paused (the shared store), refreshes the checkout to the base tip (train_serve.refresh, P-46) and
     claims ONE job (contracts/service/job.v2.json) from the control plane (service.control_url,
     contracts/service/api.v1.json): a gate of a pushed PR head, a train run woken by a pr.ready, the safety-net sweep, a
     requeue; it runs it and claims the next at once, until the control plane has none. The control plane is the only
     job channel and the only wake source (D-290). service.transport other than `control`, or no token in the variable
     service.runner_token_env names (OU_RUNNER_TOKEN), is an error raised before the first poll; a control plane that
     does not answer is a failed poll, retried at the next one;
  2. starts the budget before the claim request, includes the head check, and reserves the last two seconds for cleanup
     and reporting. The child gets its execution deadline (TOWER_JOB_DEADLINE) and lock owner (TOWER_JOB_OWNER), TERM
     one second before that deadline and KILL at it. A gate job is
     service.gate_command with the PR (the fast decision only: bypass or attested proof, else a definite no), a train job
     `scripts/train run --pr N`, a sweep `scripts/train run`. A gate job whose head is no longer its PR's head is skipped
     (D-141, one `git ls-remote`: a check, not a channel);
  3. reports each result to the control plane, always with a sentence (reason) and the time of each phase the job
     printed (phases), and writes it (contracts/service/result.v1.json) to its JSONL log (service.log_path) and its state
     file (service.state_path: heartbeat, current job, recent results), which `scripts/service status` reads. A runner
     that starts and finds a current job in its state died during it: it reports that job `died` before it claims.
A job's id is its natural key (kind:pr#sha), so a head is gated once per runner and a requeue is its next attempt.
"""
from http import HTTPStatus
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import forge_events  # noqa: E402
import forge_git_ref  # noqa: E402
import service_budget  # noqa: E402
import service_credentials  # noqa: E402
import train_serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1].parent
VERDICT = re.compile(r'gate evidence: gate\.(?:passed|failed) ([0-9a-f]+)')
HALTED = 'train: halted'
REASON_CHARS = 300  # a result's reason is one line, bounded
GATE, TRAIN, SWEEP, DEPLOY = 'gate', 'train', 'sweep', 'deploy'
ORDER = (DEPLOY, TRAIN, GATE, SWEEP)
# The control plane Worker is retired (D-323): a deploy job, still a kind of job.v2, fails and says why.
RETIRED_DEPLOY = ("import sys; print('deploy: the control plane Worker is retired (D-323); nothing to deploy'); "
                  "sys.exit(1)")


def setting(name):
    return config.get(name, ROOT)


def job(kind, repo, pr, sha, source, reason, now, attempt=1):
    """A contracts/service/job.v2.json document; its id is the natural key (a later attempt adds .<attempt>)."""
    key = (f'{kind}:' + (sha or now.replace(':', '').replace('.', '-').lower())
           if kind in (SWEEP, DEPLOY) else f'{kind}:{pr}#{sha}')
    if attempt > 1:
        key += f'.{attempt}'
    return {'id': key, 'kind': kind, 'repo': repo, 'pr': pr, 'sha': sha, 'source': source, 'reason': reason,
            'requested_at': now, 'attempt': attempt}


class State:
    """The runner's state file (service.state_path), written by an atomic rename after every change."""

    def __init__(self, root, name, kind):
        self.root = Path(root)
        self.path = self.root / setting('service.state_path')
        try:
            self.data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.data = {}
        self.data.update(name=name, kind=kind, transport=ControlTransport.label)
        for key, empty in (('done', []), ('results', [])):
            self.data.setdefault(key, empty)

    def save(self, now):
        self.data['heartbeat'] = now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f'{self.path.name}.{os.getpid()}.tmp')
        temporary.write_text(json.dumps(self.data, sort_keys=True))
        os.replace(temporary, self.path)

    def done(self, key):
        self.data['done'] = (self.data['done'] + [key])[-setting('service.results_kept'):]

    def result(self, outcome):
        self.data['results'] = (self.data['results'] + [outcome])[-setting('service.results_kept'):]


def remote_heads(root):
    """{pr: head sha} of every open change on the selected forge (forge-events.adapter): the forge's own answer, one
    paged list. Never a ref namespace: Origin's refs/pull/* are the ones imported from GitHub (ORIGIN-FINISH R5)."""
    adapter = forge_events.adapter_from_config()
    return {str(pull['number']): pull['head_sha'] for pull in adapter.open_pulls(setting('forge-events.repo'))}


def superseded_job(root, job_id):
    """True when `job_id` is a gate job whose head is no longer its PR's head on the remote: the PR was pushed again,
    so the gate of this head can no longer be the PR's verdict (D-141). Whatever transport claimed the job (the control
    plane queues one job per pushed head), the runner asks the forge before it spends a gate on it. Unreadable heads are not
    superseded: the runner never skips a gate on a guess."""
    kind, _, rest = job_id.partition(':')
    pr, _, attempt = rest.partition('#')
    sha = attempt.partition('.')[0]  # a requeue is `<sha>.<attempt>`
    if kind != GATE or not sha:
        return False
    try:
        current = remote_heads(root).get(pr)
    except Exception:  # noqa: BLE001 - an unreadable forge is never a superseded head
        return False
    return current is not None and current != sha


class RouteError(Exception):
    """The runner cannot take the control route: a setting or a variable it needs is wrong or missing (D-290). It names
    what to set; there is no other route to fall back to."""


class ControlTransport:
    """Jobs claimed from the control plane (service.control_url, contracts/service/api.v1.json): one claim at a time,
    each result reported and each running job's heartbeat sent. A control plane that
    does not answer (network, 5xx, a refused token) is a failed poll: OSError reaches Runner.once, which logs it and
    retries at the next poll. It is the only transport (D-290)."""
    label = 'control'  # what the state file and status name this transport (service.transport's only value)

    def __init__(self, url, token, runner, opener=None):
        if not token:
            raise RouteError(f'the control plane needs a runner token: set ${setting("service.runner_token_env")}')
        self.url, self.token, self.runner = url.rstrip('/'), token, runner
        self.opener = opener or urllib.request.urlopen

    def call(self, path, body, timeout=None):
        """(status, the answer's JSON or None); raises OSError (URLError included) when nothing answered."""
        request = urllib.request.Request(f'{self.url}{path}', data=json.dumps(body).encode(), method='POST', headers={
            'authorization': f'Bearer {self.token}', 'content-type': 'application/json',
            'user-agent': setting('service.user_agent')})  # D-091: the edge refuses urllib's default agent
        try:
            with self.opener(request, timeout=timeout or setting('service.control_timeout_s')) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as error:
            return error.code, None

    def poll(self, state):
        """[the one job claimed now] or [] (D-291: one claim at a time, so a job's budget starts when it is claimed and
        no claimed job waits behind another). The control plane not answering raises OSError (the poll failed); a
        refused token raises it with the sentence that names the rotated secret (service.credentials)."""
        state.data['transport'] = self.label
        code, answer = self.call('/v1/runner/claim', {'runner': self.runner, 'kinds': list(ORDER)})
        if code == HTTPStatus.NO_CONTENT:
            return []
        if code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            raise OSError(refused(code))
        if code != HTTPStatus.OK or not isinstance(answer, dict):
            raise OSError(f'the control plane answered the claim with {code}')
        return [answer]

    def report(self, outcome):
        deadline = getattr(self, 'deadline', None)
        left = service_budget.remaining(deadline) if deadline is not None else setting('service.control_timeout_s')
        if left <= 0:
            raise OSError('the job deadline ended before its result could be reported; the control plane expires it')
        try:
            code, _ = self.call('/v1/runner/result', outcome, timeout=left)
        except OSError as error:
            raise OSError('the result could not reach the control plane; it remains in the runner state') from error
        if code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            raise OSError(refused(code))
        if code not in (HTTPStatus.OK, HTTPStatus.CONFLICT):
            raise OSError(f'the control plane answered the result with {code}')

    def heartbeat(self, job_id):
        """True when the control plane asks the running job to stop (a cancel)."""
        try:
            code, answer = self.call('/v1/runner/heartbeat', {'runner': self.runner['name'], 'job': job_id})
        except OSError:
            return False
        if code in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            raise OSError(refused(code))
        return code == HTTPStatus.OK and bool((answer or {}).get('cancel'))


def refused(code):
    """The sentence of a refused runner token (service.token_holders): which variable, which secret it must equal,
    where its holder is."""
    return service_credentials.refused_sentence(setting('service.runner_token_env'), code)


def absent(environ, kind):
    """The sentences of every secret this runner kind must hold and does not (service.token_holders), checked before
    the first poll so a missing or renamed secret stops the runner by name. A GitHub token is not required where the
    egress proxy injects it (OU_CREDENTIALS=network)."""
    skip = set()
    if environ.get('OU_CREDENTIALS') == 'network':
        skip |= {'GH_TOKEN', 'GITHUB_TOKEN'}
    items = [item for item in service_credentials.entries() if item['variable'] not in skip]
    return service_credentials.missing(environ, kind, items)


def reason(item, outcome, code, text, budget, last):
    """One sentence for every outcome (D-291): what the job answered, or why it has no answer."""
    lines = [line.strip() for line in text.splitlines() if line.strip() and not service_budget.PHASE.match(line.strip())]
    said = lines[-1] if lines else ''
    if outcome == 'over_budget':
        sentence = (f'over the {budget:g} s budget during phase {last or "start"}: stopped at the deadline, nothing '
                    'it held outlives it (D-291)')
    elif outcome == 'error':
        sentence = f'the job could not run: {said or "no output"}'
    else:
        sentence = f'{item["kind"]} {outcome} (exit {code}): {said or "no output"}'
    return sentence[:REASON_CHARS]


class Executor:
    """Runs one job as a process in `root` under its budget (D-291), its output kept in service.jobs_dir; returns a
    result (result.v1) with a reason and the phases the job printed."""

    def __init__(self, root, clock, runner):
        self.root, self.clock, self.runner = Path(root), clock, runner
        self.process = None
        self.on_start = None

    def command(self, item):
        if item['kind'] == DEPLOY:
            return [sys.executable, '-c', RETIRED_DEPLOY]
        if item['kind'] == GATE:
            return [str(self.root / part) if index == 0 else part
                    for index, part in enumerate(setting('service.gate_command'))] + [str(item['pr'])]
        train = [str(self.root / 'scripts' / 'train'), 'run']
        return train + (['--pr', str(item['pr'])] if item['kind'] == TRAIN else [])

    def owner(self, item):
        """The lock owner of this job (`<runner>/<job id>`): the job takes its lock under it (TOWER_JOB_OWNER)."""
        return f'{self.runner["name"]}/{item["id"]}'

    def run(self, item, claimed=None):
        """The job, claimed at `claimed` (epoch s, default now), ended by its deadline whatever it does (D-291)."""
        claimed = time.time() if claimed is None else claimed
        started = datetime.fromtimestamp(claimed, timezone.utc)
        budget = service_budget.budget_s()  # the runner's own registry, like every setting() here
        deadline = claimed + budget - min(service_budget.REPORT_RESERVE_S, budget / 5)
        logs = self.root / setting('service.jobs_dir')
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / f'{item["id"].replace(":", "-").replace("#", "-")}.log'
        env = {key: value for key, value in os.environ.items() if key != 'OU_CONFIG_STORE'}
        env.update({service_budget.DEADLINE_ENV: f'{deadline:.3f}', service_budget.OWNER_ENV: self.owner(item)})
        code, killed = None, False
        with log.open('w') as output:
            try:
                if time.time() >= deadline:
                    killed = True
                    output.write('service runner: no execution time remains after the claim and head check\n')
                    raise subprocess.TimeoutExpired(self.command(item), 0)
                self.process = subprocess.Popen(self.command(item), cwd=str(self.root), env=env, stdout=output,
                                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                                start_new_session=True)
                if self.on_start:
                    self.on_start(self.process.pid)
                code, killed = self.wait(deadline)
            except subprocess.TimeoutExpired:
                killed = True
            except OSError as error:
                output.write(f'service runner: the job could not start ({error})\n')
            finally:
                self.signal(signal.SIGKILL)  # descendants may survive even when their leader has already exited
                self.process = None
        text = log.read_text(errors='replace')
        verdict = VERDICT.findall(text)
        if killed or 'OverBudget:' in text:
            outcome = 'over_budget'
        elif code is None:
            outcome = 'error'
        elif code == 0:
            outcome = 'passed'
        elif item['kind'] != GATE and HALTED in text:
            outcome = 'halted'
        else:
            outcome = 'failed'
        finished = datetime.now(timezone.utc)
        return {'job': item['id'], 'outcome': outcome, 'runner': self.runner, 'started_at': forge_events.rfc3339(started),
                'finished_at': forge_events.rfc3339(finished),
                'duration_s': max(0.0, (finished - started).total_seconds()), 'exit': None if killed else code,
                'verdict_event': verdict[-1] if verdict else None,
                'reason': reason(item, outcome, code, text, budget, service_budget.last_phase(text)),
                'phases': service_budget.phases(text, claimed),
                'log_tail': text[-setting('service.log_tail_chars'):]}

    def wait(self, deadline):
        """(exit code, killed): TERM one second before the deadline (the job's own alarm came earlier and released what
        it held), KILL at the deadline. A job never outlives its budget."""
        process = self.process
        for signal_number, at in ((None, deadline - service_budget.TERM_RESERVE_S), (signal.SIGTERM, deadline)):
            if signal_number is not None:
                self.signal(signal_number)
            try:
                return process.wait(timeout=max(0.0, at - time.time())), signal_number is not None
            except subprocess.TimeoutExpired:
                continue
        self.signal(signal.SIGKILL)
        return process.wait(), True

    def stop(self):
        """Terminate the running job's whole process group (a cancel)."""
        self.signal(signal.SIGTERM)

    def release(self, item, deadline):
        """Owner-checked cleanup, bounded by the same deadline; on an unreachable forge wait for lease expiry."""
        if item['kind'] not in (TRAIN, SWEEP):
            return
        left = service_budget.remaining(deadline) - service_budget.TERM_RESERVE_S
        try:
            if left <= 0:
                raise subprocess.TimeoutExpired('lock cleanup', 0)
            subprocess.run([sys.executable, str(ROOT / 'scripts/lib/service_lock.py'), '--repo', item['repo'],
                            '--owner', self.owner(item)], cwd=self.root, check=True, capture_output=True,
                           timeout=left)
        except (OSError, subprocess.SubprocessError):
            # The child's lock expires at its execution deadline, before the reporting reserve. If release failed
            # early, do not call the job finished until the lease has actually expired.
            execution_end = deadline - min(service_budget.REPORT_RESERVE_S, service_budget.budget_s() / 5)
            threading.Event().wait(max(0, service_budget.remaining(execution_end)))

    def signal(self, number):
        process = self.process
        if process is not None:
            try:
                os.killpg(process.pid, number)
            except (ProcessLookupError, PermissionError):
                pass


class Runner:
    """One poll, then the jobs it found, one at a time. paused() reads service.paused from the shared store."""

    def __init__(self, state, transport, executor, clock, paused=None, out=None, refresh=None):
        self.state, self.transport, self.executor, self.clock = state, transport, executor, clock
        self.paused = paused or (lambda: bool(config.shared('service.paused')))
        self.refresh = refresh or train_serve.refresh
        self.out = out or (lambda line: print(line, flush=True))
        self.lock = threading.Lock()
        self.job_deadline = None
        self.phase_started = None
        self.phase_marks = []

    def mark(self, name):
        self.phase_marks.append({'name': name, 'at_s': round(max(0, time.time() - self.phase_started), 3)})

    def now(self):
        return forge_events.rfc3339(self.clock.now())

    def log(self, event, **fields):
        path = self.state.root / setting('service.log_path')
        line = json.dumps(dict({'runner': self.state.data.get('name')}, at=self.now(), event=event, **fields),
                          sort_keys=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.stat().st_size > setting('service.log_max_bytes'):
            os.replace(path, path.with_name(path.name + '.1'))
        with path.open('a') as handle:
            handle.write(line + '\n')

    def beat(self):
        with self.lock:
            self.state.save(self.now())

    def once(self):
        """One poll: refresh, claim one job, run it, and again until the control plane has none; the results, in order.
        Paused, nothing is claimed (D-291: a claimed job's budget runs from its claim, so a job is never claimed to
        wait)."""
        results = []
        while True:
            if self.paused():
                self.log('paused')
                self.out('service runner: paused (service.paused); nothing is claimed')
                break
            note = self.refresh(self.state.root)  # the base tip before the claim: outside every job's budget (D-150)
            if note:
                self.out(f'service runner: {note}')
            job_budget = service_budget.budget_s()
            claimed = time.time()  # includes the claim's round trip; never start a fresh budget after the response
            claimed_tick = time.monotonic()
            try:
                jobs = self.transport.poll(self.state)
            except (forge_git_ref.GitRefError, forge_events.ForgeEventsError, OSError, subprocess.SubprocessError) as error:
                self.log('poll-failed', error=str(error))
                self.out(f'service runner: poll failed ({error}); the next poll retries')
                break
            if not jobs:
                break
            for item in jobs:
                self.log('queued', job=item)
            for item in sorted(jobs, key=lambda job: ORDER.index(job['kind'])):
                try:
                    with service_budget.supervise(job_budget - (time.monotonic() - claimed_tick)):
                        outcome = self.handle(item, claimed)
                except service_budget.OverBudget as error:
                    self.executor.stop()
                    outcome = self.skipped(item, f'{error} during {self.phase_marks[-1]["name"]}'[:REASON_CHARS])
                    outcome.update(outcome='over_budget', duration_s=max(0, time.time() - claimed),
                                   started_at=forge_events.rfc3339(datetime.fromtimestamp(claimed, timezone.utc)))
                    self.finish(item, outcome)
                if outcome is not None:
                    results.append(outcome)
        self.beat()
        return results

    def handle(self, item, claimed):
        """One claimed job to its result (None: a job this runner already ran)."""
        self.job_deadline = claimed + service_budget.budget_s()
        self.phase_started = claimed
        self.phase_marks = [{'name': 'claim', 'at_s': 0}]
        self.mark('head-check')
        self.transport.deadline = self.job_deadline
        self.state.data['current'] = dict(item, claimed_at=claimed)
        self.beat()
        if item['id'] in self.state.data['done']:
            self.finish(item, self.skipped(item, 'this runner already completed the job'))
            return None
        if item['kind'] == GATE and self.superseded(item['id']):
            self.log('superseded', job=item['id'])
            self.finish(item, self.skipped(item, 'the PR has a newer head (D-141)'))
            return None
        def started(pid):
            self.state.data['current']['process'] = process_identity(pid)
            self.beat()
        self.executor.on_start = started
        self.beat()
        self.out(f'service runner: {item["id"]} ({item["reason"]})')
        outcome = self.executor.run(item, claimed)
        if item['kind'] == GATE and outcome['outcome'] == 'failed' and self.superseded(item['id']):
            outcome['outcome'] = 'cancelled'  # stopped, or failed, on a head the PR has left (D-141)
        self.finish(item, outcome)
        self.out(f'service runner: {item["id"]} {outcome["outcome"]} in {outcome["duration_s"]:.1f} s: '
                 f'{outcome["reason"]}')
        return outcome

    def finish(self, item, outcome):
        self.mark('cleanup')
        outcome['phases'] = self.phase_marks[:-1] + outcome.get('phases', []) + self.phase_marks[-1:]
        cleanup = getattr(self.executor, 'release', None)
        if cleanup:
            cleanup(item, self.job_deadline)
        self.mark('report')
        outcome['phases'].append(self.phase_marks[-1])
        outcome['duration_s'] = max(0, time.time() - self.phase_started)
        self.report(outcome)
        outcome['phases'].append({'name': 'report-ended', 'at_s': max(0, time.time() - self.phase_started)})
        self.transport.deadline = None
        self.state.data['current'] = None
        self.state.done(item['id'])
        self.state.result(outcome)
        self.log('finished', **outcome)
        self.beat()

    def report(self, outcome):
        report = getattr(self.transport, 'report', None)
        if report:
            try:
                report(outcome)
            except OSError as error:
                self.state.data['report_error'] = str(error)
                self.log('report-failed', error=str(error), job=outcome['job'])
                self.out(f'service runner: report failed: {error}')

    def recover(self):
        """A runner that starts with a current job in its state died during it (a restart, a crash, a KILL): that job
        gets its answer, `died`, before anything is claimed. Its lock expired at its deadline (D-291), so nothing it
        held is still held. Returns the result, or None when nothing was running."""
        item = self.state.data.get('current')
        if not item:
            return None
        self.phase_started = time.time()
        self.phase_marks = [{'name': 'recover', 'at_s': 0}]
        kill_recovered(item.get('process'))
        self.job_deadline = time.time() + service_budget.budget_s()
        self.transport.deadline = self.job_deadline
        moment = self.now()
        outcome = {'job': item['id'], 'outcome': 'died', 'runner': self.executor.runner, 'started_at': moment,
                   'finished_at': moment, 'duration_s': 0.0, 'exit': None, 'verdict_event': None,
                   'reason': (f'the runner stopped during this job (its last beat was {self.state.data.get("heartbeat")}) '
                              'and started again; the job ended at its deadline and its lock with it (D-291)'),
                   'phases': [], 'log_tail': ''}
        self.finish(item, outcome)
        self.out(f'service runner: {item["id"]} died: {outcome["reason"]}')
        return outcome

    def superseded(self, job_id):
        return superseded_job(self.state.root, job_id)

    def skipped(self, item, why):
        """The result of a job the runner did not run (result.v1 outcome `skipped`), reported like any other."""
        moment = self.now()
        return {'job': item['id'], 'outcome': 'skipped', 'runner': self.executor.runner, 'started_at': moment,
                'finished_at': moment, 'duration_s': 0.0, 'exit': None, 'verdict_event': None, 'reason': why,
                'phases': [], 'log_tail': why}

    def serve(self, stop=None, reexec=None):
        stop = stop or threading.Event()
        beating = threading.Thread(target=self.heartbeat, args=(stop,), daemon=True)
        beating.start()
        self.recover()
        started = code_tree(self.state.root)
        while not stop.is_set():
            self.once()
            if updated(self.state.root, started):
                self.log('self-update', tree=code_tree(self.state.root), was=started)
                self.out('service runner: its own code changed with the base; re-executing (service.self_update)')
                (reexec or restart)()
                return
            stop.wait(setting('service.poll_s'))

    def heartbeat(self, stop):
        """While a job runs the state still beats, so a long gate is not a dead runner; the beat also renews the job's
        records liveness on the control plane; a cancel (or a newer head of the PR, D-141) stops the job."""
        while not stop.wait(setting('service.poll_s')):
            self.beat()
            current, ask = self.state.data.get('current'), getattr(self.transport, 'heartbeat', None)
            try:
                if current and ((ask and ask(current['id'])) or self.superseded(current['id'])):
                    self.log('cancelled', job=current['id'])
                    self.executor.stop()
            except OSError as error:
                self.log('heartbeat-failed', error=str(error))
                self.out(f'service runner: heartbeat failed: {error}')


def process_identity(pid):
    """Linux process start time plus pid: restart cleanup must never kill a reused pid."""
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': pid, 'start': fields[19]}
    except (OSError, IndexError):
        return None


def kill_recovered(identity):
    if identity and process_identity(identity['pid']) == identity:
        try:
            os.killpg(identity['pid'], signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def code_tree(root):
    """The tree id of the checkout's scripts/ at HEAD: the runner's own code and everything it runs; '' unreadable."""
    done = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD:scripts'], capture_output=True, text=True)
    return done.stdout.strip() if done.returncode == 0 else ''


def updated(root, started):
    """GATE-SPEED R6 (D-092): True when service.self_update is on and a refresh moved scripts/ since the runner started:
    the process still holds the code it started with (train_serve.refresh only updates files), so a fix merged to the
    base, its own included, reached the runner only on a manual restart."""
    if not setting('service.self_update') or not started:
        return False
    now = code_tree(root)
    return bool(now) and now != started


def restart():
    """Re-execute this runner with the same interpreter and arguments: the same process id, the base's new code."""
    os.execv(sys.executable, [sys.executable, *sys.argv])


def identity():
    """(name, kind) of this runner: the first set variable of service.runner_name_env, else the host name."""
    name = next((os.environ[key] for key in setting('service.runner_name_env') if os.environ.get(key)),
                socket.gethostname())
    kind = os.environ.get(setting('service.runner_kind_env')) or 'other'
    return name, kind


def transport_for(route, environ, runner):
    """The control transport, or RouteError naming what is wrong (D-290): `route` is service.transport's value, and
    `environ` holds the token under the variable service.runner_token_env names. Nothing here builds another route."""
    if route != ControlTransport.label:
        raise RouteError(f'service.transport is {route!r}: the control plane is the only route (D-290); '
                         f'set it with `scripts/config set service.transport {ControlTransport.label}`')
    return ControlTransport(setting('service.control_url'), environ.get(setting('service.runner_token_env')), runner)


def build(root=ROOT, clock=None, environ=None):
    """The runner of this machine; RouteError before any poll when the control route cannot be taken."""
    clock = clock or forge_events.clock_from_config()
    name, kind = identity()
    runner = {'name': name, 'kind': kind}
    try:
        route = config.shared('service.transport')
    except config.ConfigError as error:  # the store still holds a route the registry no longer offers (git)
        raise RouteError(f'{error}; the control plane is the only route (D-290)') from error
    environ = os.environ if environ is None else environ
    transport = transport_for(route, environ, runner)
    gaps = absent(environ, kind)
    if gaps:
        raise RouteError('this runner lacks its secrets (service.token_holders): ' + ' '.join(gaps))
    return Runner(State(root, name, kind), transport, Executor(root, clock, runner), clock)


UNIT_DIR = ROOT / 'services' / 'runner'  # the units are data, not code: <name>.tmpl for each unit scripts/service prints
DEFAULT_UNIT = 'tower-runner.service'


def unit_names():
    """Every unit this checkout can print (scripts/service runner --print-unit NAME)."""
    return sorted(path.stem for path in UNIT_DIR.glob('*.tmpl'))


def unit_text(root=ROOT, kind='box', name=None):
    """A systemd user unit: the runner (default) that stays up and comes back after a crash, a reboot or a network that was
    not ready, or the liveness watch (a .service and a .timer) that restarts it when its heartbeat is stale, which
    Restart= cannot see in a hung process. Raises KeyError for a name that is not one of unit_names()."""
    name = name or DEFAULT_UNIT
    if name not in unit_names():
        raise KeyError(f'{name} is not a unit of services/runner: {", ".join(unit_names())}')
    return (UNIT_DIR / f'{name}.tmpl').read_text().format(root=root, kind=kind)
