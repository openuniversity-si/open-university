"""What the engine's locked roles share (D-065 (1); plan v3 M3 the train, M6 the battery): one mechanism, not two.

LockedRole   the lock-holder loop of Transport v0 (docs/process/EVENTS.md): take the role's lock through the
             forge_events port (leased, renewed before every judged run), drain until nothing is pending, release,
             and look once more, so an event whose producer found the lock taken is never stranded. A drain that
             ends with another outcome (the train's 'flaked') stops the loop until the next event. A role that
             loses its lock halts before it judges or acts on anything.
judge        one measured run of the role's gate on a commit (engine.step.measured with the injected clock), handed
             to the role's record() (the train keeps it as flake evidence for the quarantine, M7); last_verdict is
             that measurement's event_id, the run's verdict on the log. The role's
             gate_env(commit) is the extra environment of that run (the train's batch members, GX-30).
first_red    prefix bisection over commits that already exist: the newest is known red, the first red one names
             the culprit; bounded by a run limit, after which the range still in doubt is returned, and stopped
             (None) when the caller proves a red probe is a flake.
CommandGate  a gate command run on one commit with a fresh build cache (never a cached result, D-065 (5)): its first
             failed stage and that stage's class (code, env or contract), both read from the gate's machine class line
             `<gate.class_line_prefix> <stage>\t<class>` (GX-01, D-070), the test files its output names failing (the
             quarantine's test ids) and its output tail (the log excerpt only, never the evidence of a class).

Each role keeps its own registry entries (lock ref, lease, producer, step prefix, command, timeout); this module
reads none of them (only the gate's own gate.class_line_prefix), so the same mechanism never gets a second
name for a value. setting(name) reads the registry of this checkout by its root: a base-tip gate (D-A3) runs these
modules' tests with its own config module already imported, whose registry lacks the keys a head adds (GX-02).

The lock owner is the session id when the role's environment names one (default_owner), so two sessions on one host
never share an owner; a role that dies frees the lock when its lease ends. A drain that raises releases the lock with
`died` on the release record (death(): the exception type and the first line of its message), so the reason is on
the forge over git even when the event log is the thing that failed (TRAIN-TEMP-FIX R1).

A role with a `deadline` (epoch s; the train, D-291) holds its lock exactly until it: the lease is the time left, and
renew() only checks the deadline, since nobody can take an unexpired lock and the role ends before it expires. The
deadline's OverBudget (service_budget.guard: the alarm, or TERM) is a BaseException, so it releases like any death.

"""
from collections import namedtuple
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile

import config
import forge_events
import gate_classify
import service_budget

ROOT = Path(__file__).resolve().parents[2]
FAILED_LINE = re.compile(r'^.*(?:\bFAIL\b|[×✗✘]).*$', re.M)
TIMEOUT_CLASS = 'env'  # a run past its timeout registry entry is red on the machine (train.tier2_timeout_s)
TEST_FILE = re.compile(r'[\w@./-]+\.(?:test|spec)\.[cm]?[jt]sx?')
GateResult = namedtuple('GateResult', 'ok stage log tests kind', defaults=((), None))
Bisection = namedtuple('Bisection', 'low high failing runs')


class RoleHalt(RuntimeError):
    """The role must stop for a person (it lost its lock, or the forge is not what it tested)."""


def failing_test_files(output):
    """Test files the gate output reports failing (vitest `FAIL  <file> > ...`, playwright `✘ ... <file>:<line>`), in
    order of first mention: the test ids of the quarantine (M7)."""
    found = []
    for line in FAILED_LINE.findall(output):
        found += [name for name in TEST_FILE.findall(line) if name not in found]
    return tuple(found)


def setting(name):
    """A registry value of this checkout (read by root, never through another checkout's imported config module)."""
    return config.get(name, ROOT)


def failed_stage(output):
    """(stage, class) of the first red stage the gate's machine class line names, or None when the output has none."""
    prefix = re.escape(setting('gate.class_line_prefix'))
    classes = '|'.join(map(re.escape, gate_classify.ACTIONS))
    found = re.search(rf'^{prefix} (.+)\t({classes})\s*$', output, re.M)
    return found.groups() if found else None


def default_owner(producer, session_env=()):
    """A lock owner name that tells which session holds a role: producer@<session id> from the first variable of
    `session_env` that is set (unique per session), else producer@host:pid."""
    session = next((os.environ[name] for name in session_env if os.environ.get(name)), None)
    return f'{producer}@{session}' if session else f'{producer}@{socket.gethostname()}:{os.getpid()}'


def elapsed_ms(start, end):
    return int((end - start).total_seconds() * 1000)


class Recording:
    """A port that keeps the envelopes emitted through it (the judged run's engine.step.measured: its verdict)."""

    def __init__(self, port):
        self.port, self.envelopes = port, []

    def emit(self, kind, payload, version=None):
        envelope = self.port.emit(kind, payload, version)
        self.envelopes.append(envelope)
        return envelope

    def __getattr__(self, name):
        return getattr(self.port, name)


class LockedRole:
    """Base of a role run by whoever holds its lock. A subclass sets adapter, clock, repo, producer, step_prefix,
    lock_ref, lock_lease_s and gate, and implements pending() and drain(port)."""

    Halt = RoleHalt
    owner = None
    deadline = None  # epoch s: the lock is held until it and never renewed past it (D-291)
    last_run_ms = 0
    last_verdict = None  # event_id of the latest judged run's engine.step.measured

    def port(self, correlation_id):
        return forge_events.ForgeEvents(self.adapter, self.clock, self.producer, correlation_id)

    def pending(self):
        raise NotImplementedError

    def drain(self, port):
        """Work until nothing is pending; return None (or 'drained'), or another outcome that ends the run."""
        raise NotImplementedError

    def record(self, step, commit, result):
        """What the role keeps of each judged run (nothing by default)."""

    def gate_env(self, commit):
        """Extra environment for the gate run on `commit` (none by default)."""
        return {}

    def step(self, port, name, sha):
        """engine.step.measured for this role's step `name` on an integration commit (pr null)."""
        return forge_events.measured(port, self.step_prefix + name, forge_events.subject(self.repo, None, sha))

    def lease_s(self):
        """The lease of a take: the time left to the deadline (D-291), else the role's own lock_lease_s."""
        if self.deadline is None:
            return self.lock_lease_s
        left = service_budget.remaining(self.deadline)
        if left <= 0:
            raise service_budget.OverBudget(f'{self.lock_ref}: the job budget ended before the lock was taken (D-291)')
        return left

    def renew(self, port):
        """Extend the lease while the role runs; losing the lock stops the role before it judges or acts. With a
        deadline the lock is already held until it: only the deadline is checked, nothing is pushed."""
        if self.deadline is not None:
            self.lease_s()
            return
        if self.owner and not port.lock(self.repo, self.lock_ref, self.owner, self.lock_lease_s):
            raise self.Halt(f'{self.owner} lost {self.lock_ref}')

    def judge(self, port, step, commit):
        """One gate run on a commit, measured as `step`; the lease is renewed first."""
        self.renew(port)
        recording = Recording(port)
        with self.step(recording, step, commit) as measurement:
            start = self.clock.now()
            env = self.gate_env(commit)
            result = self.gate.run(commit, env=env) if env else self.gate.run(commit)
            self.last_run_ms = elapsed_ms(start, self.clock.now())
            if not result.ok:
                measurement.result = 'fail'
        self.last_verdict = recording.envelopes[-1]['event_id'] if recording.envelopes else None
        self.record(step, commit, result)
        return result

    def run(self, owner, correlation_id):
        """The role: 'busy' (another owner holds the lock), 'drained' (nothing is pending) or the outcome another
        drain ended with."""
        port, outcome = self.port(correlation_id), 'busy'
        service_budget.phase('lock')
        while port.lock(self.repo, self.lock_ref, owner, self.lease_s()):
            self.owner, died = owner, None
            try:
                outcome = self.drain(port) or 'drained'
            except BaseException as error:
                died = death(error)  # the release record keeps why this run ended (TRAIN-TEMP-FIX R1)
                raise
            finally:
                self.owner = None
                service_budget.phase('release')
                if died:
                    port.unlock(self.repo, self.lock_ref, owner, died=died)
                else:
                    port.unlock(self.repo, self.lock_ref, owner)
            if outcome != 'drained' or not self.pending():
                break
        return outcome


DEATH_CHARS = 300  # the reason a dead run leaves on its lock's release record: one line, bounded


def death(error):
    """`<ExceptionType>: <first line of its message>`, at most DEATH_CHARS: the reason a run that raised leaves on the
    release record of its lock (TRAIN-TEMP-FIX R1), which goes over git and so survives a log that cannot be read."""
    lines = str(error).strip().splitlines()
    text = f'{type(error).__name__}: {lines[0]}' if lines else type(error).__name__
    return text[:DEATH_CHARS]


def first_red(count, probe, failing, max_runs, flake=None):
    """Prefix bisection over `count` ordered commits whose last is known red with `failing`.

    probe(i) judges commit i and returns a result with .ok. Returns Bisection(low, high, failing, runs): low == high
    names the first red commit and failing is its result; low < high when max_runs ran out first, and [low, high]
    is the range still in doubt. None when flake() proves a red probe a flake: the bisection stops and blames
    nobody. A run is never retried (D-025)."""
    low, high, runs = 0, count - 1, 0
    while low < high and runs < max_runs:
        middle = (low + high) // 2
        runs += 1
        result = probe(middle)
        if result.ok:
            low = middle + 1
        elif flake and flake():
            return None
        else:
            high, failing = middle, result
    return Bisection(low, high, failing, runs)


class CommandGate:
    """Runs a gate command on one commit (the commit appended to `command`, relative to `root`) with a fresh build
    cache and a fresh per-test cache (GATE_TEST_CACHE_DIR, so no marker of another run is reused: P-02 strict, D-065
    (5)), or, with `cache` 'box', with the caches the command finds on this machine (the box content cache of gate-dev,
    F19; D-076 (a) allows it, D-297 (c)), and reports (ok, first failed stage, output tail, failing test files, class). `timeout_name` is the registry
    entry of `timeout`; a timeout is class env (the machine, never a member). A red run without a class line (a timeout, a gate older than GX-01) is classified once over its
    whole output with gate_classify, never over the tail, and its stage is the command."""

    CACHES = ('fresh', 'box')

    def __init__(self, root, command, timeout, log_chars, label, timeout_name, cache='fresh'):
        self.root = Path(root or ROOT)
        self.command, self.timeout, self.log_chars = command, timeout, log_chars
        self.label, self.timeout_name = label, timeout_name
        if cache not in self.CACHES:
            raise ValueError(f'{label}: cache {cache!r} is not one of {", ".join(self.CACHES)}')
        self.cache = cache

    def caches(self, folder):
        """The cache variables of one run: a fresh folder, or none under 'box' (the command's own defaults)."""
        if self.cache == 'box':
            return {}
        return dict(GATE_BUILD_CACHE_DIR=folder, GATE_TEST_CACHE_DIR=os.path.join(folder, 'test-cache'))

    def run(self, commit, env=None):
        """`env` adds variables for the command (the train's GATE_BATCH_BASE and GATE_BATCH_MEMBERS); a command that
        does not read them (the rollback `gate-dev --sha`) runs as before."""
        with tempfile.TemporaryDirectory(prefix=f'{self.label.replace(" ", "")}-') as cache:
            try:
                done = subprocess.run([str(self.root / self.command[0]), *self.command[1:], commit], cwd=self.root,
                                      capture_output=True, text=True, timeout=self.timeout,
                                      env=dict(os.environ, **(env or {}), **self.caches(cache)))
            except subprocess.TimeoutExpired:
                message = f'{self.label} exceeded {self.timeout_name} on {commit}'
                return GateResult(False, 'timeout', message, (), TIMEOUT_CLASS)
        output = done.stdout + done.stderr
        tail = output[-self.log_chars:] if self.log_chars else ''
        if done.returncode == 0:
            return GateResult(True, None, tail)
        stage, kind = failed_stage(output) or (self.command[0], gate_classify.classify(self.command[0], output))
        return GateResult(False, stage, tail, failing_test_files(output), kind)
