#!/usr/bin/env python3
"""Run the Python test files of one script test as separate processes, side by side (GATE-FAST, D-076).

A script test that loops over several test files used to run them one after the other, so its wall was their sum and
the gate's critical path ended with the longest such loop. Here each file is its own process and at most `OU_TEST_CPUS`
run at a time: gate_test_cache gives every script test it runs its share of the vCPUs (vCPUs / the tests running at
once, at least 1), so a gate that runs one or two tests lets each spread over the box while a full suite stays one
process per test as before. Without the variable (a hand run) one file runs at a time. GATE-SPEED F1 (D-118): within a
suite the CPUs a finished test frees go to the tests still running through a jobserver (`jobserver`, a FIFO of tokens
as in GNU make's -j), so the long tail of a suite runs on the whole box instead of one CPU each.

Each file's output is printed whole, in the order given, after it ends; the exit is 1 when any file failed.

  parallel_tests.py FILE...
"""
import contextlib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import os
import shutil
import subprocess
import sys
import tempfile
import threading

ENV = 'OU_TEST_CPUS'  # set by gate_test_cache.run for every script test it starts
JOBSERVER = 'OU_TEST_JOBSERVER'  # GATE-SPEED F1 (D-118): the FIFO of CPU tokens the running script tests share
POLL = 'OU_TEST_JOBSERVER_POLL_S'  # how often a test at its share looks for a freed CPU (gate.jobserver_poll_s)
TOKEN = b'+'


def cpus(environ=None):
    """The processes this test may run at once: OU_TEST_CPUS when it is a positive integer, else 1."""
    value = (os.environ if environ is None else environ).get(ENV, '').strip()
    return int(value) if value.isdigit() and int(value) > 0 else 1


def run_one(path):
    done = subprocess.run([sys.executable, path], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'}, check=False)
    return done.returncode, done.stdout


@contextlib.contextmanager
def jobserver(tests, workers, share, cpus, poll_s):
    """The suite's side of the jobserver (GATE-SPEED F1, D-118; GNU make's -j protocol): a FIFO that holds one token
    for every CPU no running test owns. Each running test owns `share` CPUs (ENV); once no test is left to start, a test
    that ends hands its CPUs to the tests still running, so the long tail of a suite runs on the whole box.
    Yields (the environment a test gets, ended(label) to call when a test ends); ({}, None) when there is nothing to share."""
    if tests < 1 or cpus <= share:
        yield {}, None
        return
    folder = tempfile.mkdtemp(prefix='ou-jobserver-')
    path = os.path.join(folder, 'tokens')
    os.mkfifo(path)
    fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
    lock, left = threading.Lock(), [tests]
    os.write(fd, TOKEN * max(0, cpus - min(workers, tests) * share))

    def ended(_label=None):
        with lock:
            left[0] -= 1
            if left[0] < workers:  # the slot this test frees takes no queued test: its CPUs go to the others
                os.write(fd, TOKEN * share)
    try:
        yield {JOBSERVER: path, POLL: str(poll_s)}, ended
    finally:
        os.close(fd)
        shutil.rmtree(folder, ignore_errors=True)


def _tokens(environ=None):
    """(fd, poll seconds) of the suite's jobserver, or None: no variable, or a FIFO this process cannot open."""
    environ = os.environ if environ is None else environ
    path = environ.get(JOBSERVER)
    try:
        return (os.open(path, os.O_RDWR | os.O_NONBLOCK), float(environ.get(POLL, '')) or None) if path else None
    except (OSError, ValueError):
        return None


def _take(fd):
    try:
        return os.read(fd, len(TOKEN)) == TOKEN
    except BlockingIOError:
        return False


def run(paths, workers=None, environ=None):
    """(exit code, [(path, code, output)]) of every file, in the order given: `workers` at once, and one more for each
    token the suite's jobserver hands over while files are still waiting (each token goes back when its file ends)."""
    workers = max(1, min(workers or cpus(environ), len(paths) or 1))
    pool = _tokens(environ) if len(paths) > workers else None
    if pool is None or pool[1] is None:
        with ThreadPoolExecutor(max_workers=workers) as threads:
            finished = list(threads.map(run_one, paths))
    else:
        fd, poll_s = pool
        finished, waiting, running = [None] * len(paths), list(enumerate(paths)), {}
        try:
            with ThreadPoolExecutor(max_workers=len(paths)) as threads:
                while waiting or running:
                    while waiting and (len(running) < workers or _take(fd)):
                        index, path = waiting.pop(0)
                        running[threads.submit(run_one, path)] = (index, len(running) >= workers)
                    done, _ = wait(running, timeout=poll_s if waiting else None, return_when=FIRST_COMPLETED)
                    for future in done:
                        index, borrowed = running.pop(future)
                        finished[index] = future.result()
                        if borrowed:
                            os.write(fd, TOKEN)
        finally:
            os.close(fd)
    results = [(path, code, output) for path, (code, output) in zip(paths, finished)]
    return (1 if any(code for _path, code, _output in results) else 0), results


def main(argv):
    paths = [path for path in argv[1:] if os.path.exists(path)]
    if not argv[1:]:
        print('usage: parallel_tests.py FILE...', file=sys.stderr)
        return os.EX_USAGE
    code, results = run(paths)
    for path, status, output in results:
        sys.stdout.write(output)
        if status:
            print(f'parallel_tests: {path} failed (exit {status})')
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv))
