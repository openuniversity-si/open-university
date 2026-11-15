"""PROCESS-LIFE-IN-LOG (docs/operations/aws-revisao-arquitetura.md, finding 28): a process of the engine says in the
engine's own log when it started, why it stopped and what failed in its loop.

On 10/11 only the Torre could say what the tasks had done: a stop, a crash and a tick that failed were lines of
CloudWatch, in an account no session reads. The service and the runner write them as events of the configuration tenant
(as platform.db.vitals is), read with POST /v1/log/query {filters: {type}}:

  platform.process.started {role, task, mode: task|standby|successor|reloaded, digest, image, supervised}
  platform.process.stopped {role, task, mode, digest, up_s, reason: asked|yielded|retired|error, error}
  platform.process.error   {role, task, where, error, times}

started is written when the process is ready to work (serve before its first tick, run-container when its slots open).
stopped is written by main() when the command returns or raises: asked (a signal: SIGTERM of ECS, of Spot or of the
supervisor), yielded (IN-TASK-STANDBY: the role was given to the successor), retired (no longer the live image), error
(the exception that ended it). A process that replaces itself by exec says nothing here: platform.deploy.image_reload
says it. error is a failure the loop survived (the service's tick): the first of a kind at once, the same kind again
not before ERROR_EVERY_S, with how many times it happened meanwhile.
Never raises: a database that is away never costs the process. LIFE-EVENT-RETRY: nor the event. Live 11/11 17:10 UTC,
with the database at 65 of its 79 connections, the tasks an ECS rollout started wrote no `started`: the moment the
events are for. An event that could not be written is kept (KEEP at most) with the time it happened (`at`) and
written on a later good pass of the process (beat(): the service's tick, a runner slot's pass), RETRY_S apart.

This module runs in the service alone: no port Lambda's package holds it (scripts/lib/deploy_classify.LAMBDA_MODULES),
so a change here is a code-only merge of the service (QUEUE-SWAP: its heir is up before the landing).
"""
import json
import logging
import os
import socket
import threading
import time
import uuid

from . import config_data

LOG = logging.getLogger('tower_infra.lifecycle')
STARTED, STOPPED, ERROR = 'platform.process.started', 'platform.process.stopped', 'platform.process.error'
ERROR_EVERY_S = 600
TEXT = 300  # the most of an error's words an event carries
KEEP, RETRY_S = 20, 30  # LIFE-EVENT-RETRY: the events kept for a later write, and how far apart the writes are tried
RECORD = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
          "select %(id)s, t.id, %(type)s, clock_timestamp(), %(producer)s, %(subject)s, %(payload)s::jsonb "
          "from work.tenant t where t.name = %(tenant)s")


def words(error):
    return f'{type(error).__name__}: {error}'[:TEXT]


def mode_of(environ):
    from . import code_bundle
    standby = (environ.get(code_bundle.STANDBY) or '').strip()
    if standby:
        return 'successor' if standby == code_bundle.INTASK else 'standby'
    return 'reloaded' if environ.get(code_bundle.RELOADED) else 'task'


class Life:
    """One process's record. scope() gives a database for one statement (a new short connection: the process may be
    stopping); gate is its live_image.Gate or None."""

    def __init__(self, role, scope, gate=None, environ=None, clock=time.monotonic, tenant=None):
        environ = os.environ if environ is None else environ
        self.role, self.scope, self.gate, self.clock = role, scope, gate, clock
        self.tenant = tenant or environ.get('TOWER_CONFIG_TENANT', config_data.TENANT)
        self.task = getattr(gate, 'task', None) or environ.get('TOWER_RUNNER_NAME') or socket.gethostname()
        self.about = {'role': role, 'task': self.task, 'mode': mode_of(environ),
                      'digest': environ.get('TOWER_IMAGE_DIGEST') or None}
        from . import supervisor
        self.first = {'image': environ.get('TOWER_IMAGE'), 'supervised': bool(supervisor.supervised(environ))}
        self.since, self.errors, self.ended = clock(), {}, False
        self.unsaid, self.tried = [], None  # LIFE-EVENT-RETRY: the statements' parameters not written yet; the last try

    def write(self, kind, payload):
        said = {'id': f'{kind}:{uuid.uuid4()}', 'type': kind, 'producer': f'tower-{self.role}', 'subject': self.task,
                'tenant': self.tenant, 'payload': json.dumps({**self.about, **payload, 'at': round(time.time(), 3)})}
        if self.send(said):
            return True
        self.unsaid = (self.unsaid + [said])[-KEEP:]
        self.tried = self.clock()
        return False

    def send(self, said):
        try:
            with self.scope() as db:
                db.rows(RECORD, said)
            return True
        except Exception:  # noqa: BLE001 - the event is a courtesy to whoever diagnoses, never the process's health
            LOG.exception('lifecycle: %s not recorded', said['type'])
            return False

    def beat(self):
        """LIFE-EVENT-RETRY: a good pass of the process: the events not written yet are written now, oldest first, until
        one fails; nothing is asked of the database while there is none, nor more often than RETRY_S."""
        if not self.unsaid or self.clock() - self.tried < RETRY_S:
            return 0
        self.tried, wrote = self.clock(), 0
        while self.unsaid and self.send(self.unsaid[0]):
            self.unsaid.pop(0)
            wrote += 1
        return wrote

    def started(self):
        return self.write(STARTED, self.first)

    def error(self, where, error):
        """A failure the loop survived: recorded at once the first time, then once every ERROR_EVERY_S with the count."""
        kind, now = (where, type(error).__name__), self.clock()
        last, times = self.errors.get(kind, (None, 0))
        if last is not None and now - last < ERROR_EVERY_S:
            self.errors[kind] = (last, times + 1)
            return False
        self.errors[kind] = (now, 0)
        return self.write(ERROR, {'where': where, 'error': words(error), 'times': times + 1})

    def stopped(self, error=None):
        if self.ended:
            return False
        self.ended = True
        reason = ('error' if error is not None else 'yielded' if getattr(self.gate, 'gone', False)
                  else 'retired' if getattr(self.gate, 'retired', False) else 'asked')
        return self.write(STOPPED, {'up_s': round(self.clock() - self.since, 1), 'reason': reason,
                                    'error': None if error is None else words(error), **getattr(self, 'notes', {}),
                                    **memory()})


NOW = None  # the Life of this process, once it is ready to work


FIRST_WORK_S = 5  # FIRST-WORK-FIRST: the longest a start said aside waits for the role's first work


def begin(role, scope, gate=None, aside=False):
    """SUCCESSOR-BACK-FASTER: aside says the start in a thread of its own (a process the role is waiting for: its first
    work comes before its word). FIRST-WORK-FIRST: and that thread waits for the role's first work (the gate's own
    event, at most FIRST_WORK_S) before it logs in: at the drill of 12/11 18:07 UTC a dozen logins reached the database
    in the second both roles' new processes started, and each took 0.7 to 1.5 s; this one is no part of the first work."""
    global NOW  # noqa: PLW0603 - one process, one record
    NOW = Life(role, scope, gate)
    if aside:
        def later(life=NOW):
            worked = getattr(gate, 'worked', None)
            if worked is not None:
                worked.wait(FIRST_WORK_S)
            life.started()
        threading.Thread(target=later, name='life-started', daemon=True).start()
    else:
        NOW.started()
    return NOW


def memory():
    """TASK-MEMORY-AT-STOP: the task's memory as its cgroup says it when a process stops: task_mb (in use, less the file
    pages nothing reads) and task_peak_mb (the most since the task started: a rollout's, a Spot warning's, a provoked
    swap's), with the task's limit when the supervisor knows it. The memory was said only by a successor (its reserve's
    word), and a task that no successor stood in had none: none since the rollout of 12/11 18:50 UTC, and none of the
    runner's task Spot took at 19:27 UTC. {} where there is no cgroup. Never raises."""
    try:
        from . import supervisor
        found = supervisor.cgroup()
        said = {'task_mb': found.get('used_mb'), 'task_peak_mb': found.get('peak_mb'),
                'task_limit_mb': supervisor.memory().get('task_limit_mb') or found.get('limit_mb')}
        return {name: value for name, value in said.items() if value is not None}
    except Exception:  # noqa: BLE001 - a measure, never the stop's word
        return {}


def note(**more):
    """SPOT-KEEP: what the process's stop says beside its reason (kept_s, replaced): told before the stop is said."""
    if NOW is not None:
        NOW.notes = {**getattr(NOW, 'notes', {}), **more}


def error(where, failure):
    if NOW is not None:
        NOW.error(where, failure)


def beat():
    if NOW is not None:
        NOW.beat()


def end(failure=None):
    """main()'s word when the command returned or raised. SystemExit(0) and a KeyboardInterrupt are a stop that was
    asked, not an error."""
    if NOW is not None:
        asked = isinstance(failure, KeyboardInterrupt) or (isinstance(failure, SystemExit) and failure.code in (0, None))
        NOW.stopped(None if asked else failure)


def said(work):
    """main()'s run of serve or run-container: its stop is said whatever ended it, and what it raised is raised."""
    try:
        work()
    except BaseException as failure:  # noqa: BLE001 - said in the log, then raised as it was
        end(failure)
        raise
    end()
    return 0
