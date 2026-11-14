"""Keep the train serving: refresh the checkout, run `scripts/train serve`, start again after any exit (D-156).

`train serve` exits by design (train.serve_max_s, a lost lock, a halted batch) and the documented answer is that the
session starts it again; this is that session's loop for a container that has no other. It never edits the checkout
beyond a fast-forward of the base branch, never merges by itself (the train does) and never polls the forge: the wait
between starts is a sleep, the train's own wake is a `git ls-remote`.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402


def refresh(checkout):
    """Fast-forward the checkout to the remote tip of the base branch; the exit code (non-zero is only reported)."""
    remote, base = config.get('train.git_remote'), config.get('train.base_branch')
    fetched = subprocess.run(['git', '-C', str(checkout), 'fetch', '--quiet', remote, base], capture_output=True)
    if fetched.returncode:
        return fetched.returncode
    return subprocess.run(['git', '-C', str(checkout), 'merge', '--quiet', '--ff-only', 'FETCH_HEAD'], capture_output=True).returncode


def tip(checkout):
    """The checkout's HEAD commit, or None."""
    done = subprocess.run(['git', '-C', str(checkout), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    return done.stdout.strip() or None


def shadow(checkout):
    """Start the real gate on the checkout's tip for measurement only (scripts/gate-shadow run), detached: the loop never
    waits for it and its result lands in .gate/shadow, where lane-status reads it (D-151)."""
    subprocess.Popen([str(Path(checkout) / 'scripts' / 'gate-shadow'), 'run', 'HEAD'], cwd=str(checkout), stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def watcher(checkout, watch, interval, stop, out=print, last=None, refresh_checkout=None):
    """Thread body: while `train serve` runs (it blocks for train.serve_max_s), look at the base tip every `interval` seconds
    and call `watch` when it moved, so the real gate follows the base and not the loop's restarts (D-157)."""
    refresh_checkout = refresh_checkout or refresh
    while not stop.wait(interval):
        refresh_checkout(checkout)
        now = tip(checkout)
        if now and now != last:
            watch(checkout)
            out(f'train-loop: the base moved to {now}; the real gate runs on it for measurement')
            last = now


def loop(checkout, pause, iterations=None, serve=None, sleep=time.sleep, out=print, watch=None, last=None):
    """Start the train again after every exit; `iterations` None is forever (a test passes a count). `watch` is called
    with the checkout whenever its tip moved since the last start (the shadow gate); `last` is the tip it saw."""
    serve = serve or (lambda: subprocess.run([str(Path(checkout) / 'scripts' / 'train'), 'serve'], cwd=str(checkout)).returncode)
    started = 0
    stop = threading.Event()
    if watch and iterations is None:
        threading.Thread(target=watcher, args=(checkout, watch, pause, stop, out, last), daemon=True).start()
    while iterations is None or started < iterations:
        if refresh(checkout):
            out('train-loop: the checkout was not refreshed; serving what it holds')
        now = tip(checkout)
        if watch and now and now != last:
            watch(checkout)
            out(f'train-loop: the base moved to {now}; the real gate runs on it for measurement')
            last = now
        code = serve()
        started += 1
        out(f'train-loop: train serve exited {code}; starting again in {pause} s')
        if iterations is None or started < iterations:
            sleep(pause)
    stop.set()
    return started


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/train-loop', description=__doc__.splitlines()[0])
    parser.add_argument('--checkout', default='.', help='a clean checkout of the base branch (not a private directory: the unprivileged uid must traverse it)')
    parser.add_argument('--shadow', action='store_true', help='run the real gate (scripts/gate-shadow) on every new base tip, detached')
    parser.add_argument('--pause', type=int, default=len('twenty seconds'))
    args = parser.parse_args(argv)
    loop(args.checkout, args.pause, watch=shadow if args.shadow else None)
    return 0


if __name__ == '__main__':
    sys.exit(main())
