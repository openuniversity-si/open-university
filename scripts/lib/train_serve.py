"""`scripts/train serve` (GATE-ON-PUSH R2, plan commit 5): the train-role session's consumer of the wake.

With train.trigger_mode wake the producer of pr.ready fast-forwards train.wake_ref (train_trigger.py) and starts nothing.
This process, started in the background of the designated train-role session only (docs/operations/train.md, P-18),
waits on that ref:

wait    one `git ls-remote` of train.wake_ref every train.wake_poll_s: a read of git, never of the REST budget, so an idle
        wait costs no forge call.
wake    when the tip moved, the records after the last one served (the ref's own history is the wake log) give the PRs;
        each distinct PR gets one `scripts/train run --pr <n>`, oldest wake first.
sweep   `scripts/train run` (the full replay, the safety net) once at start, which covers every wake before it, and
        every train.sweep_interval_s after that.
exit    after train.serve_max_s, below the session's background-process limit, so its exit event wakes the session to
        start serve again; the starting sweep of the next serve covers anything in between.

Before each run the checkout, when it is on train.base_branch, is fast-forwarded to the remote tip, so the run and its
tier 2 use the base tip's code (P-46). Each run is its own process: it takes train.lock_ref, honors train.enabled and
refuses a machine-local override (train.py); serve itself writes nothing to the forge.
"""
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import forge_git_ref  # noqa: E402
from engine_role import ROOT, setting  # noqa: E402


def say(line):
    print(line, flush=True)  # serve runs in the background: each line reaches the session's output file at once


class Serve:
    """The wait loop over injected refs (tip, log), run(pr or None), clock and sleep."""

    def __init__(self, refs, run, name, poll_s, sweep_s, max_s, clock=time.monotonic, sleep=time.sleep, out=say):
        self.refs, self.run, self.name = refs, run, name
        self.poll_s, self.sweep_s, self.max_s = poll_s, sweep_s, max_s
        self.clock, self.sleep, self.out = clock, sleep, out
        self.wakes = self.sweeps = 0

    def tip(self):
        try:
            return self.refs.tip(self.name)
        except forge_git_ref.GitRefError as error:  # a failed wait is retried on the next poll; the sweep still runs
            self.out(f'train serve: {self.name} not read ({error})')
            return None

    def pending(self, last):
        """(PRs woken after `last`, oldest first and each once, the sha of the newest wake read)."""
        prs = []
        records = self.refs.log(self.name, last)
        for _, record in records:
            if record.get('pr') not in prs:
                prs.append(record.get('pr'))
        return [pr for pr in prs if isinstance(pr, int)], (records[-1][0] if records else last)

    def sweep(self):
        self.sweeps += 1
        self.run(None)

    def serve(self):
        start = self.clock()
        end = start + self.max_s
        last = self.tip()  # every wake before it: the starting sweep covers them
        self.sweep()
        due = self.clock() + self.sweep_s
        while self.clock() < end:
            tip = self.tip()
            if tip and tip != last:
                try:
                    prs, last = self.pending(last)
                except forge_git_ref.GitRefError as error:
                    self.out(f'train serve: {self.name} log not read ({error})')
                    prs = []
                for pr in prs:
                    self.wakes += 1
                    self.run(pr)
            if self.clock() >= due:
                self.sweep()
                due = self.clock() + self.sweep_s
            self.sleep(max(0, min(self.poll_s, end - self.clock())))
        return (f'served {self.wakes} wake(s) and {self.sweeps} sweep(s) in {round(self.clock() - start)}s; '
                f'train.serve_max_s reached: start `scripts/train serve` again')


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True,
                          timeout=setting('train.git_timeout_s'))


def refresh(root):
    """Fast-forward the checkout to the remote tip of train.base_branch when it is on that branch; a line saying what
    happened (a failure is printed, never fatal: the run reads the tip from the remote itself)."""
    base, remote = setting('train.base_branch'), setting('train.git_remote')
    branch = git(root, 'symbolic-ref', '--quiet', '--short', 'HEAD').stdout.strip()
    if branch != base:
        return f'checkout on {branch or "a detached HEAD"}, not {base}: not refreshed'
    for args in (('fetch', '--quiet', '--no-tags', remote, base), ('merge', '--ff-only', '--quiet', 'FETCH_HEAD')):
        done = git(root, *args)
        if done.returncode != 0:
            return f'{base} not refreshed (git {args[0]}: {forge_git_ref._last_line(done.stderr)})'
    return None


def runner(root, out=say):
    """run(pr): `scripts/train run [--pr <n>]` in its own process from the refreshed checkout, output inherited."""
    def run(pr):
        note = refresh(root)
        if note:
            out(f'train serve: {note}')
        command = [str(Path(root) / 'scripts' / 'train'), 'run'] + (['--pr', str(pr)] if pr is not None else [])
        out(f'train serve: {"wake #" + str(pr) if pr is not None else "sweep"}: {" ".join(command[1:])}')
        env = {key: value for key, value in os.environ.items() if key != 'OU_CONFIG_STORE'}
        done = subprocess.run(command, cwd=str(root), env=env, stdin=subprocess.DEVNULL)
        if done.returncode != 0:
            out(f'train serve: run exited {done.returncode}')
    return run


def main(root=ROOT):
    serve = Serve(forge_git_ref.GitRefs(root), runner(root), setting('train.wake_ref'), setting('train.wake_poll_s'),
                  setting('train.sweep_interval_s'), setting('train.serve_max_s'))
    say(f'train serve: {serve.serve()}')
    return 0
