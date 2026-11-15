"""RESERVE-NO-DB (docs/operations/aws.md 22.9): a role's process that is loaded and waits, with no connection to the
database, to be the successor the instant the successor of its bundle is lost.

A successor that ended as the swap promoted it left the role's new code with no process until its supervisor's new one
was up: 4.6 to 5.9 s for the runner and 8.9 s for the service at the drills of 12/11 (SWAP-DRILL), of which the boot of
the process (the interpreter, the bundle's fetch, the imports: 2.8 s and 7.0 s) is the most. A second successor would
have been ready, and is refused: it holds connections and backends of a database that has few (db.t4g.micro). The
reserve pays the part that needs no database before it is needed, and nothing else:

    python -m tower_infra reserve serve | run-container     (the supervisor's command for it; tower_infra.supervisor)

It boots the bundle as a successor does (code_bundle.boot, the successor's environment), imports what the role's command
imports, compiles the rest of its code, makes the AWS clients a login and the role's first reads use (their service
models are the cost: no call is made), says it is ready (ready.<n>.json, with what it holds: its memory) and waits for
SIGUSR2. Told to go, it is the role's command from its first line: a successor of its task (TOWER_STANDBY=intask), which
logs in then and not before. A bundle of a code before this one has no such command: its process ends at once (2) and
never runs as a second successor; the supervisor holds no reserve for that bundle.

Until the word comes this process opens no socket to the database, holds no credential of it and reads nothing of it:
`ready` imports and builds, and the only network it touches is none (a client made is a model loaded).

This module runs in the service alone: no port Lambda's package holds it (scripts/lib/deploy_classify.LAMBDA_MODULES),
so a change here is a code-only merge of the service (QUEUE-SWAP: its heir is up before the landing).
"""
import compileall
import json
import importlib
import logging
import os
from pathlib import Path
import signal
import time

from . import code_bundle, supervisor

LOG = logging.getLogger('tower_infra.reserve')
# what the role's command imports before its first statement; `workflows` (and what imports it) is left to the command:
# its workflows are registered against the DBOS the command makes first
# RESERVE-AFTER-GO: and the engine's dialect, which SQLAlchemy imports only when an engine is made (after the word,
# on the service's quarter of a vCPU)
LIBRARIES = {'serve': ('psycopg', 'sqlalchemy', 'sqlalchemy.dialects.postgresql.psycopg', 'boto3', 'dbos'),
             'run-container': ('psycopg', 'boto3')}
MODULES = {'serve': ('canary', 'code_bundle', 'container', 'database', 'live_image', 'stall', 'vitals', 'lifecycle',
                     'config_data', 'wake', 'mechanisms', 'rehearsal', 'autodeploy', 'prewarm', 'migrations',
                     # RESERVE-AFTER-GO: what serve imports between its gate's read and its launch (none imports workflows)
                     'forge', 'forge_webhooks', 'sessions', 'subscriptions', 'api_providers', 'cursor_agents',
                     'cli_sessions'),
           'run-container': ('code_bundle', 'config_data', 'container', 'database', 'lifecycle', 'live_image', 'runner',
                             'wake', 'rehearsal')}
CLIENTS = {'serve': ('rds', 'ssm', 'sns'), 'run-container': ('rds', 'ssm', 's3')}


def ready(command, environ=None, load=importlib.import_module, compile_all=compileall.compile_dir):
    """What needs no database, done ahead: the libraries and the modules of the role's command imported, the rest of
    this package compiled (an import then reads the bytecode), the AWS clients made. A part that fails is left to the
    command, which does it as it always did; answers the parts that failed."""
    environ = os.environ if environ is None else environ
    failed = []
    for name in (*LIBRARIES.get(command, ()), *(f'{code_bundle.PACKAGE}.{each}' for each in MODULES.get(command, ()))):
        try:
            load(name)
        except Exception:  # noqa: BLE001 - the command imports it itself, and says why it cannot
            LOG.exception('reserve: %s could not be imported ahead', name)
            failed.append(name)
    try:
        compile_all(str(Path(__file__).resolve().parent), quiet=2, workers=1)
    except Exception:  # noqa: BLE001
        LOG.exception('reserve: the package could not be compiled ahead')
        failed.append('compile')
    try:
        boto3 = load('boto3')
        database = load(f'{code_bundle.PACKAGE}.database')
        for name in CLIENTS.get(command, ()):
            if name == 'rds':
                database.signer(database.settings(environ)['region'])  # the one a login's token is signed with, kept
            else:
                boto3.client(name, region_name=environ.get('AWS_REGION'))
    except Exception:  # noqa: BLE001
        LOG.exception('reserve: the AWS clients could not be made ahead')
        failed.append('clients')
    return failed


def restorable(before, status='/proc/self/status', limit=None):
    """Whether this process may raise its CPU priority back to `before` once lowered: its limit allows it
    (RLIMIT_NICE) or it holds CAP_SYS_NICE (bit 23 of CapEff). A container has neither by default: False then."""
    try:
        if limit is None:
            import resource
            limit = resource.getrlimit(resource.RLIMIT_NICE)[0]
        if limit >= 20 - before:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        for line in Path(status).read_text().splitlines():
            if line.startswith('CapEff:'):
                return bool(int(line.split()[1], 16) & (1 << 23))
    except (OSError, ValueError, IndexError):
        pass
    return False


def quiet(get=os.getpriority, put=os.setpriority, may=restorable):
    """The lowest CPU priority for this process while it loads (the task's CPU is the role's first: the service has a
    quarter of a vCPU), only where it can be given back: the priority it had, or None where the process may not raise
    its priority again (a container with no CAP_SYS_NICE: nothing is changed, and what keeps its load off a landing
    is when it starts: after its bundle's successor beats)."""
    try:
        before = get(os.PRIO_PROCESS, 0)
        if not may(before):
            return None
        put(os.PRIO_PROCESS, 0, 19)
        return before
    except OSError:
        return None


def loud(before, put=os.setpriority, tasks='/proc/self/task'):
    """The priority given back, to every thread of the process (on Linux a priority is a thread's, and a thread
    started while the process loaded has the low one)."""
    if before is None:
        return
    try:
        threads = [int(each.name) for each in Path(tasks).iterdir() if each.name.isdigit()]
    except OSError:
        threads = []
    for thread in threads or [0]:
        try:
            put(os.PRIO_PROCESS, thread, before)
        except OSError:  # a thread that ended meanwhile
            pass


def hold(command, environ=None, wait=signal.sigwait, tell=supervisor.tell, prepare=ready, age=code_bundle.age_s,
         mask=signal.pthread_sigmask, handle=signal.signal, lower=quiet, raise_=loud):
    """The reserve of `command`: the word to go (SIGUSR2) is held back from now, so one sent early waits; what needs no
    database is done; the supervisor is told this process is ready (only a ready one is ever told to go) with its age
    and its memory; and it waits. On the word the signal is ignored until the role's command sets its own handler
    (SUCCESSOR-LOST uses the same signal for the role's process) and how old the process was is kept (WENT). Answers
    what it told the supervisor."""
    environ = os.environ if environ is None else environ
    mask(signal.SIG_BLOCK, {supervisor.GO})
    for signum in (signal.SIGTERM, signal.SIGINT):  # a reserve holds nothing: the task's stop, or its bundle's want
        handle(signum, signal.SIG_DFL)  # withdrawn, ends it at once, whatever was imported before it
    before = lower()
    failed = prepare(command, environ)
    from . import live_image
    said = {'command': command, 'ready_s': age(), **live_image.rss(), **({'failed': failed} if failed else {})}
    LOG.info('reserve: %s ready and waiting, no connection made: %s', command, said)
    tell(f'{supervisor.READY}{environ.get(supervisor.CHILD)}.json', said, environ)
    wait({supervisor.GO})
    raise_(before)
    handle(supervisor.GO, signal.SIG_IGN)
    mask(signal.SIG_UNBLOCK, {supervisor.GO})
    # a process is born, for what it says and for a drill it obeys (SWAP-DRILL: a drill older than the process does not
    # arm it), when it becomes the successor: the drill that ended the one before it is not this one's
    live_image.BORN = str(int(time.time()))
    # SWAP-CPU: the container's CPU at the word, for the swap's record to say what the quota held back until the first work
    environ[code_bundle.CPU_AT] = json.dumps({**live_image.cpu(), 'at': time.monotonic()})
    went = age()
    if went is not None:
        environ[code_bundle.WENT] = str(went)  # its boot, for the swap's record, is what comes after
    LOG.warning('reserve: told to go: this process is the successor of its bundle now')
    return said
