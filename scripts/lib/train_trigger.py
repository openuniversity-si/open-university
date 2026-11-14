"""Transport v0 for the train (D-065 (1), docs/process/EVENTS.md): what the producer of pr.ready does next.

train.trigger_mode emit_only (the default, GX-06): nothing. pr.ready is on the log and the designated train-role
session (docs/operations/train.md) runs the train; start() raises NotStarted, so no process starts in a lane's
container. detached (the rollback, Transport v0 as it was): after pr.ready is on the log, start() launches `scripts/train run` detached in the background and returns at once.
The run itself takes train.lock_ref (a taken lock ends it with 'busy'; the holder looks once more after its release,
so nothing is stranded) and honors train.enabled (off: it exits before it reads a log or takes the lock). The child
does not inherit OU_CONFIG_STORE, which the gate pins to the local store. train.trigger_mode itself is read from the
shared store (config.shared) for the same reason: the hook runs after the verdict, inside the pinned process tree.
Its output goes to train.trigger_log_dir under the checkout, never to the producer's console.
wake (GATE-ON-PUSH R2): the producer starts nothing either; it fast-forwards train.wake_ref over git (forge_git_ref, the
lock's own path: no REST) with a record {pr, sha, event_id} of the pr.ready it emitted, and the train-role session's
`scripts/train serve` runs one admission per wake. A fast-forward refused train.wake_attempts times is a lost wake: the
periodic run catches the PR.
"""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import forge_git_ref  # noqa: E402
from engine_role import ROOT, setting  # noqa: E402,F401 - the checkout this module runs from

DETACHED = 'detached'  # the train.trigger_mode value that starts the run here
WAKE = 'wake'  # the train.trigger_mode value that writes a wake on train.wake_ref


class NotStarted(RuntimeError):
    """train.trigger_mode does not start the train in the producer's process tree."""


def command(root):
    return [str(Path(root) / 'scripts' / 'train'), 'run']


def shared_setting(name):
    """A post-verdict switch: its value in the shared store, never the gate's pinned local one (GATE-ON-PUSH R1)."""
    return config.shared(name, ROOT)


def record(event):
    """The wake record of a pr.ready envelope: the PR, its head and the event that asked for it."""
    payload = event['payload']
    return {'pr': payload['pr'], 'sha': payload['sha'], 'event_id': event['event_id']}


def wake(root, event, refs=None):
    """Append the wake of `event` to train.wake_ref; the sha of the wake commit, or None when the wake was lost."""
    refs = refs or forge_git_ref.GitRefs(root)
    return refs.append(setting('train.wake_ref'), record(event), setting('train.wake_attempts'))


def trigger(root, event, label='run', popen=subprocess.Popen, refs=None):
    """What the producer of the pr.ready `event` does next, as one line for its console: a wake on train.wake_ref
    (wake), a detached run (detached), or NotStarted (emit_only). The switch is read once, from the shared store."""
    mode = shared_setting('train.trigger_mode')
    if mode != WAKE:
        return f'started in the background, output in {start(root, label, popen, mode)}'
    name = setting('train.wake_ref')
    sha = wake(root, event, refs)
    if sha is None:
        return (f'wake lost: {name} moved under {setting("train.wake_attempts")} pushes; the periodic run catches '
                f'#{event["payload"]["pr"]}')
    return f'woken over {name} at {sha}; the train-role session admits #{event["payload"]["pr"]}'


def start(root=ROOT, label='run', popen=subprocess.Popen, mode=None):
    """Launch `scripts/train run` detached; returns the log path. Never waits for it. NotStarted unless
    train.trigger_mode (`mode` when the caller read it) is detached."""
    mode = mode or shared_setting('train.trigger_mode')
    if mode != DETACHED:
        raise NotStarted(f'train.trigger_mode is {mode}: pr.ready is on the log and the train-role session runs the '
                         'train (docs/operations/train.md); no process started here')
    logs = Path(root) / setting('train.trigger_log_dir')
    logs.mkdir(parents=True, exist_ok=True)
    log = logs / f'train-{label}.log'
    env = {key: value for key, value in os.environ.items() if key != 'OU_CONFIG_STORE'}
    with open(log, 'ab') as out:
        popen(command(root), cwd=str(root), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
              start_new_session=True)
    return log
