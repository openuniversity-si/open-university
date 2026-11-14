"""The box queue (VAZÃO F36, D-297 (b)): the deliveries waiting for the box's lock, one file each, and what the leader
did with them.

A `deliver` writes `pr-N.json` {pr, branch, head, pid, at} to delivery.box_queue_dir before it asks for the box's lock
(delivery.gate_lock_path) and removes it when it ends. The leader of a batch (`scripts/train run --box`) reads the live
entries, judges a batch of them and writes `pr-N.result.json` {pr, head, sha, outcome, batch_id, merge_sha, detail, at}
for each member it resolved (outcome merged, ejected, conflicted or refused); a member that is still waiting gets no
result. A result is read only for the head it was written for. The folder is process coordination, like the lock
itself: it lives while the processes wait and never holds flow state. The record is the forge's (pr.merged with the
batch id, train.batch.*, pr.ejected), so D-065 (1) holds.

`hold` takes the box's lock for a leader started by hand; a leader started by a `deliver` that already holds it runs
with HELD_ENV set to the lock's path and takes nothing (flock is per open file: a second open would wait for its parent).
"""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import time

import config

HELD_ENV = 'TOWER_BOX_LOCK_HELD'  # the lock path a parent `deliver` holds for the leader it runs
OUTCOMES = ('merged', 'ejected', 'conflicted', 'refused')


def folder(directory=None):
    """The queue folder (delivery.box_queue_dir), created on first use."""
    path = Path(os.path.expanduser(directory or config.get('delivery.box_queue_dir')))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write(path, data):
    """Write a JSON file whole: a reader sees the old file or the new one, never half of it."""
    scratch = path.with_name(f'.{path.name}.{os.getpid()}')
    scratch.write_text(json.dumps(data, sort_keys=True) + '\n')
    os.replace(scratch, path)


def enqueue(pr, branch, head, directory=None, pid=None, at=None):
    """The entry of one waiting delivery; a result left for an older head of the PR is removed."""
    path = folder(directory)
    _write(path / f'pr-{pr}.json', {'pr': pr, 'branch': branch, 'head': head, 'pid': pid or os.getpid(),
                                    'at': time.time() if at is None else at})
    return path / f'pr-{pr}.json'


def leave(pr, directory=None, pid=None):
    """Remove this delivery's entry (only its own: another delivery of the PR may have written a newer one)."""
    path = folder(directory) / f'pr-{pr}.json'
    with contextlib.suppress(OSError, ValueError):
        if json.loads(path.read_text()).get('pid') == (pid or os.getpid()):
            path.unlink()


def alive(pid):
    """True while process `pid` exists (a delivery that died leaves its entry behind: it is not waiting)."""
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except (TypeError, ValueError):
        return False
    return True


def entries(directory=None, live=alive):
    """The waiting deliveries, oldest first: entries whose process is alive. Unreadable files are skipped."""
    rows = []
    for path in folder(directory).glob('pr-*.json'):
        if path.name.endswith('.result.json'):
            continue
        try:
            row = json.loads(path.read_text())
            row['pr'], row['head'], row['branch'], row['pid'], row['at']  # noqa: B018 - a row needs every field
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if live(row['pid']):
            rows.append(row)
    return sorted(rows, key=lambda row: (row['at'], row['pr']))


def position(pr, directory=None, live=alive):
    """(place, total) of PR `pr` among the live waiting deliveries, oldest first (place 1 is next); None when `pr` is
    not queued. A line for whoever reads the log: the wait is a queue, not a hang (F132)."""
    rows = entries(directory, live)
    for place, row in enumerate(rows, 1):
        if row['pr'] == pr:
            return place, len(rows)
    return None


def write_result(pr, head, outcome, directory=None, **fields):
    """What the leader did with one member (outcome one of OUTCOMES), for the delivery that waits on `head`."""
    if outcome not in OUTCOMES:
        raise ValueError(f'box result {outcome!r} is not one of {", ".join(OUTCOMES)}')
    data = dict(fields, pr=pr, head=head, outcome=outcome, at=fields.get('at', time.time()))
    _write(folder(directory) / f'pr-{pr}.result.json', data)
    return data


def result(pr, head, directory=None):
    """The leader's result for PR `pr` at `head`, or None (none yet, or one written for another head)."""
    try:
        data = json.loads((folder(directory) / f'pr-{pr}.result.json').read_text())
    except (OSError, ValueError):
        return None
    return data if data.get('head') == head else None


@contextlib.contextmanager
def hold(path=None, out=print):
    """The box's lock for a leader: taken here, or already held by the parent `deliver` (HELD_ENV names its path)."""
    lock = Path(os.path.expanduser(path or config.get('delivery.gate_lock_path')))
    if os.environ.get(HELD_ENV) == str(lock):
        yield
        return
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, 'a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            out(f'train: another gate holds the box ({lock}); waiting for it')
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
