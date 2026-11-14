"""One budget per runner job (D-291): service.job_budget_s from the claim to the result, and what is derived from it.

The runner computes the job's deadline D = claim + budget and hands it to the job in TOWER_JOB_DEADLINE (seconds since
the epoch), with the lock owner it must use in TOWER_JOB_OWNER (`<runner>/<job id>`), so the runner and the job agree
on both without a second channel. A job run by hand (no runner) takes D = its own start + the budget.

guard(D)   inside the job: SIGALRM fires `RELEASE_RESERVE_S` before D and SIGTERM (the runner's, systemd's) at any
           time; both raise OverBudget, a BaseException so that no `except Exception` in the job swallows it, and the
           role's `finally` releases what it holds (engine_role.LockedRole.run) with the reason.
phase(n)   inside the job: one line `phase: <name> @<epoch>` on stdout, so the runner can report the time of each phase
           from the claim (phases()), and an over-budget answer names the phase that was running.
"""
import os
from pathlib import Path
import re
import signal
import sys
import time
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEADLINE_ENV = 'TOWER_JOB_DEADLINE'
OWNER_ENV = 'TOWER_JOB_OWNER'
RELEASE_RESERVE_S = 2.0  # the job's own alarm leaves this much of the budget to release its lock (one fetch, one push)
TERM_RESERVE_S = 1.0  # the runner sends TERM this long before D and KILL at D
REPORT_RESERVE_S = RELEASE_RESERVE_S  # cleanup and reporting are part of the job, not extra time after its deadline
PHASE = re.compile(r'^phase: (?P<name>\S+) @(?P<at>[0-9]+(?:\.[0-9]+)?)\s*$', re.M)


class OverBudget(BaseException):
    """The job reached its deadline, or was told to stop (TERM): it must release what it holds and end."""


def budget_s(root=None):
    return float(config.get('service.job_budget_s', root or ROOT))


def deadline(environ=None, now=None, root=None):
    """D for this process: TOWER_JOB_DEADLINE when the runner set it, else now + the budget."""
    environ = os.environ if environ is None else environ
    held = environ.get(DEADLINE_ENV)
    if held:
        return float(held)
    return (time.time() if now is None else now) + budget_s(root)


def owner(environ=None):
    """The lock owner the runner named for this job (`<runner>/<job id>`), or None for a run by hand."""
    environ = os.environ if environ is None else environ
    return environ.get(OWNER_ENV) or None


def remaining(when, now=None):
    return when - (time.time() if now is None else now)


def phase(name, out=None, now=None):
    """Mark the start of a phase of this job: one stdout line the runner parses (phases())."""
    stamp = time.time() if now is None else now
    print(f'phase: {name} @{stamp:.3f}', file=out or sys.stdout, flush=True)


def phases(text, started):
    """[{name, at_s}] of the phase lines in a job's output, at_s counted from `started` (the claim, epoch s)."""
    return [{'name': found.group('name'), 'at_s': round(max(0.0, float(found.group('at')) - started), 3)}
            for found in PHASE.finditer(text)]


def last_phase(text):
    """The name of the last phase a job's output started, or None."""
    found = PHASE.findall(text)
    return found[-1][0] if found else None


def guard(when, now=None):
    """Arm the deadline in this process: SIGALRM RELEASE_RESERVE_S before `when`, and SIGTERM, both raise OverBudget.
    Returns the seconds left before the alarm (0 when it is already due: the alarm fires at once)."""
    def stop(number, _frame):
        what = 'the deadline' if number == signal.SIGALRM else 'TERM'
        raise OverBudget(f'stopped by {what} of the {budget_s():g} s job budget (D-291)')

    signal.signal(signal.SIGALRM, stop)
    signal.signal(signal.SIGTERM, stop)
    left = max(0.0, remaining(when, now) - RELEASE_RESERVE_S)
    signal.setitimer(signal.ITIMER_REAL, left or 0.001)
    return left


def disarm():
    signal.setitimer(signal.ITIMER_REAL, 0)


@contextmanager
def supervise(seconds):
    """The runner's outer deadline covers Python checks and network reporting as well as its child process."""
    previous = signal.getsignal(signal.SIGALRM)
    timer = signal.getitimer(signal.ITIMER_REAL)
    def stop(_number, _frame):
        raise OverBudget('the complete runner job reached its deadline, including checks and reporting')
    signal.signal(signal.SIGALRM, stop)
    signal.setitimer(signal.ITIMER_REAL, max(seconds, 0.001))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *timer)
        signal.signal(signal.SIGALRM, previous)
