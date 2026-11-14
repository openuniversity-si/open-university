"""IN-TASK-STANDBY (docs/operations/aws.md 22.9): the task's first process is a small supervisor of the role's processes.

The standby of a code-only head was a Fargate Spot task (tower_infra.prewarm): Spot took four in four hours on 11/11, a
replacement beats ~95 s later, RunTask is refused at times and one pair serves every branch. The standby becomes a process
inside the ECS task of its role, a successor: it costs no task, Spot cannot take it apart from the task, and the landing
promotes it by the pointer as it promoted the Spot standby. This module is the part that holds the processes; what a
successor is and when it takes the role is live_image's.

`serve` and `run-container`, when they are the container's first process (pid 1; __main__.main, before code_bundle.boot),
become the supervisor: it starts the role's process as a child with the environment it was given (so the child boots
exactly as the task's process did: code_bundle.boot, deploy.live_code or the image's code) and keeps the task's contract:
  - SIGTERM and SIGINT are forwarded to every child, whose own handlers do what they did (the handback, the drain); the
    supervisor exits after its children, with the code of the role's process;
  - the health file the ECS health check reads is the role's process's: every child beats a file of its own and the
    supervisor copies the time of the main child's onto the task's (a successor standing by, or a process finishing its
    work, never keeps a task healthy whose role's process stopped beating);
  - the role's process ending is the task ending, as before: the others are stopped and ECS starts the task again;
  - as pid 1 it reaps every process the container leaves behind.

The children talk to it through a spool directory (TOWER_SUPERVISOR in their environment, the mark of a supervised
process): a file written whole (tell: a temporary name, then renamed) and SIGUSR1 to the supervisor. The supervisor reads no
database and knows no statement: it runs for the task's whole life on the code the task started with, while its children
change code at every landing, so what it understands is two files and one signal:
  want.json          {"successors": [{"key", "sha"}]}  the successors this task should hold now (the whole set, each
                     time): one not running is started, one running and no longer wanted gets SIGTERM. A successor is the
                     same command with code_bundle.successor's environment (the bundle as TOWER_CODE_KEY, TOWER_CODE_SHA256
                     and TOWER_IMAGE_DIGEST, TOWER_STANDBY=intask: the standby the prewarm ran on Spot), a directory of its
                     own for its code and its own health file. One that dies while wanted is started again, RESTARTS times
                     TOWER_SUPERVISOR_RESTART_S apart, then reported (state.json `failed`, and the log) and left.
  yield.<n>.json     {"sha"}  the role's process (the child the supervisor numbered n) gives the role to the successor of that bundle: that successor becomes
                     the main child and gets SIGUSR1 (it adopts the role), the one that yielded finishes what it has in
                     flight and exits, and is reaped like any child.
  state.json         written by the supervisor after every change: its children {n, pid, kind: main|successor|retiring, sha}
                     and the bundles whose successor it gave up on.
  heeds.<n>.json     {}  SUCCESSOR-LOST: the child numbered n wants to be told when a successor of the task ends unasked:
                     the supervisor then sends it SIGUSR2, after state.json says the successor is gone, while it is the
                     main child. A child that never said so is never sent it (a process of a code before this one has no
                     handler, and the signal's default would end it).

RESERVE-NO-DB: beside the successor of a wanted bundle the task holds one RESERVE of it: the same command told `reserve`
first (python -m tower_infra reserve serve), with the successor's environment and a directory of its own. It loads the
bundle and what the role imports, opens no connection to the database, says it is ready (ready.<n>.json) and waits for
SIGUSR2. When the successor of its bundle ends unasked the reserve IS the successor from that instant (told to go: the
boot of a new process, 5 to 9 s live on 12/11, is not on the role's clock) and a new reserve is started behind it. One
reserve a task, never for the bundle the role's process runs, stopped when its bundle is no longer wanted or took the
role. A reserve that ends by itself is the mark of a bundle whose code holds none (a code before this: `reserve` is no
command of it, so it never runs as a second successor): none is tried again for that bundle. It is held only while the
task has room for it, measured (TOWER_RESERVE: 0 never, 1 always, else when the memory the container uses plus
TOWER_RESERVE_ROOM_MB fits in the task's limit, read from the cgroup and the task's metadata; a task whose limit is
unknown holds none). RESERVE-SETTLE: no new reserve is started behind one that was just told to go until
TOWER_RESERVE_SETTLE_S (60) passed: at a swap the role's previous process, the reserve that took over and a new
reserve were up together (the service's task peaked at 424 MB of 512 on 12/11), and seconds later the bundle ran the
role and its new reserve was stopped unused. state.json says the memory when it changes: {limit_mb, used_mb, peak_mb, children: {n: {rss_mb,
pss_mb}}} and `reserve` (held, no room, off, not its code, or waiting: the reserve is started once its bundle's
successor beats its health file, so its boot is never on the warm-up a landing waits for).

TASK-POOLER: the task's connections to its database are the task's, not a process's: the supervisor starts a pool
beside the role's process (python -m tower_infra pooler <command>; tower_infra.pooler, the image's code) and names its
socket's directory to every child (TOWER_DB_POOL), which then connects there with no login of its own; a process that
dies leaves its connections in the pool, logged in, for the one that takes its place. The pool is no process of the
role: it is started again when it ends (POOL_RESTARTS times a minute, then left: the processes log in by themselves,
as before), it is the last to be stopped (a process that hands its pointer back at the task's stop does it through
the pool), and its end is never the task's. TOWER_POOLER=0, or a task with no database named, has none.
Standard library only.
"""
import json
import logging
import os
from pathlib import Path
import re
import select
import shutil
import signal
import sys
import tempfile
import time

from . import code_bundle

LOG = logging.getLogger('tower_infra.supervisor')
DIR = 'TOWER_SUPERVISOR'  # the spool directory, in every child's environment: the mark of a supervised process
PID, CHILD = 'TOWER_SUPERVISOR_PID', 'TOWER_SUPERVISOR_CHILD'  # the supervisor's pid, and the number it gave this child
FORCE = 'TOWER_SUPERVISE'  # '1': supervise though not pid 1 (the gate's tests); '0': never (the task's process as before)
HEALTH = 'TOWER_HEALTH_FILE'
WANT, YIELD, STATE, HEEDS, READY = 'want.json', 'yield.', 'state.json', 'heeds.', 'ready.'
MAIN, SUCCESSOR, RETIRING, RESERVE, POOLER = 'main', 'successor', 'retiring', 'reserve', 'pooler'
POOLS, POOL = 'TOWER_POOLER', 'TOWER_DB_POOL'  # TASK-POOLER: 0 never; the pool's directory in a child's environment
POOL_RESTARTS = 5  # a pool that ends is started again this many times a minute, then left
HOLD = 'reserve'  # RESERVE-NO-DB: the word before the role's command that makes a process a reserve
GO = signal.SIGUSR2  # and the signal that tells a ready one it is the successor now
RESERVES, ROOM_MB = 'TOWER_RESERVE', 'TOWER_RESERVE_ROOM_MB'  # 0 never, 1 always, else by the room; the room (160)
SETTLE_S = 'TOWER_RESERVE_SETTLE_S'  # RESERVE-SETTLE: how long after a reserve went no other is started for its bundle (60)
CGROUP, PROC, METADATA = '/sys/fs/cgroup', '/proc', 'ECS_CONTAINER_METADATA_URI_V4'
MOST = 2  # the successors one task ever holds, whatever a want says (the datum bounds it: deploy.intask_standbys)
RESTARTS = 3  # a wanted successor that dies is started again this many times,
RESTART_S = 'TOWER_SUPERVISOR_RESTART_S'  # this far apart (D-308: an interval is a value of the environment; 5 s)
TICK_S = 'TOWER_SUPERVISOR_TICK_S'  # the health file's relay, and the safety of a lost signal (5 s)
SHA = re.compile(r'^[0-9a-f]{64}$')


def due(command, environ=None, pid=None, parent=None):
    """Whether this process becomes the supervisor: the container's first process of a role's command, not a child of one.
    RUNNER-SUPERVISED: the first process is pid 1, or the child of pid 1 where the container has an init (the runner's
    task: InitProcessEnabled, so the orphans of its checks are reaped). The init stays pid 1 and passes the task's SIGTERM
    on; a process a supervisor started carries DIR whoever its parent is by then."""
    environ = os.environ if environ is None else environ
    if command not in code_bundle.COMMANDS or environ.get(DIR) or environ.get(FORCE) == '0':
        return False
    first = (os.getpid() if pid is None else pid) == 1 or (os.getppid() if parent is None and pid is None else parent) == 1
    return environ.get(FORCE) == '1' or first


def supervised(environ=None):
    """The spool directory of this process's supervisor, or None: a process no supervisor started."""
    return (os.environ if environ is None else environ).get(DIR) or None


def tell(name, said, environ=None, kill=os.kill):
    """A child's word to its supervisor: the file `name` of the spool directory written whole, then SIGUSR1 to the
    supervisor (its pid as it gave it: a child is not always its direct child). Answers False for a process no supervisor
    started (nothing is written)."""
    environ = os.environ if environ is None else environ
    where = supervised(environ)
    if not where:
        return False
    path = Path(where) / name
    draft = path.with_name(f'.{name}.{os.getpid()}')
    draft.write_text(json.dumps(said))
    os.replace(draft, path)
    kill(int(environ[PID]), signal.SIGUSR1)
    return True


def want(successors, environ=None, **how):
    """The successors this task should hold now: [(key, sha256)], the whole set."""
    return tell(WANT, {'successors': [{'key': key, 'sha': sha} for key, sha in successors]}, environ, **how)


def give(sha, environ=None, **how):
    """This process, the role's, gives the role to the successor of the bundle `sha`."""
    return tell(f"{YIELD}{(os.environ if environ is None else environ)[CHILD]}.json", {'sha': sha}, environ, **how)


def heeds(environ=None, **how):
    """SUCCESSOR-LOST: this process wants SIGUSR2 when a successor of its task ends unasked (its handler is set)."""
    return tell(f"{HEEDS}{(os.environ if environ is None else environ)[CHILD]}.json", {}, environ, **how)


def lost(environ=None):
    """SUCCESSOR-LOST: {sha: how many times a successor of that bundle ended unasked in this task} (state.json), for the
    role's process told of one (SIGUSR2): a count that grew is a process that is gone, though the supervisor may have
    started the bundle's successor again already. {} for a process no supervisor started and when the state cannot be
    read: nothing is known."""
    spool = supervised(environ)
    if not spool:
        return {}
    try:
        found = json.loads((Path(spool) / STATE).read_text()).get('lost') or {}
        return {str(sha): int(count) for sha, count in found.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def failed(environ=None):
    """SUCCESSOR-GAVE-UP: the bundles whose successor this process's supervisor gave up on (state.json: one that ended
    more than RESTARTS times), for the role's process to say in the engine's log. [] for a process no supervisor started,
    and when the state is not there or not whole yet: the next look reads it again."""
    spool = supervised(environ)
    if not spool:
        return []
    try:
        return [str(sha) for sha in json.loads((Path(spool) / STATE).read_text()).get('failed') or [] if SHA.match(str(sha))]
    except (OSError, ValueError):
        return []


def reserved(environ=None):
    """RESERVE-NO-DB, for a successor's word in the log: (how its task's reserve stands: held, no room, off, not its
    code, waiting or None; the bundle of the reserve that is ready, or None). (None, None) for a process no supervisor
    started and when the state cannot be read."""
    spool = supervised(environ)
    if not spool:
        return None, None
    try:
        state = json.loads((Path(spool) / STATE).read_text())
        ready = next((child.get('sha') for child in state.get('children') or []
                      if child.get('kind') == RESERVE and child.get('ready')), None)
        return state.get('reserve'), ready
    except (OSError, ValueError, AttributeError):
        return None, None


def megabytes(count):
    return round(count / (1024 * 1024), 1)


def cgroup(root=CGROUP):
    """RESERVE-NO-DB: the memory of this container as its cgroup counts it (v2, then v1): {used_mb: what is in use
    less the file pages nothing reads (reclaimable: the working set), peak_mb, limit_mb}; a part that cannot be read
    is left out ({} with no cgroup). Never raises."""
    def read(name):
        try:
            return (Path(root) / name).read_text().strip()
        except OSError:
            return None

    def line(name, key):
        for each in (read(name) or '').splitlines():
            parts = each.split()
            if len(parts) == 2 and parts[0] == key and parts[1].isdigit():
                return int(parts[1])
        return 0
    for now, peak, limit, stat, idle in (
            ('memory.current', 'memory.peak', 'memory.max', 'memory.stat', 'inactive_file'),
            ('memory/memory.usage_in_bytes', 'memory/memory.max_usage_in_bytes', 'memory/memory.limit_in_bytes',
             'memory/memory.stat', 'total_inactive_file')):
        current = read(now)
        if current is None or not current.isdigit():
            continue
        found = {'used_mb': megabytes(max(0, int(current) - line(stat, idle)))}
        top, most = read(peak), read(limit)
        if top and top.isdigit():
            found['peak_mb'] = megabytes(int(top))
        if most and most.isdigit() and int(most) < 1 << 50:  # v1 says "no limit" as a number near 2^63
            found['limit_mb'] = megabytes(int(most))
        return found
    return {}


def resident(pid, proc=PROC):
    """RESERVE-NO-DB: {rss_mb, pss_mb} of a process as the kernel says it (smaps_rollup: Pss counts a page shared by n
    processes as 1/n of it, so the Pss of a task's processes add up to what they hold); {} for one that is gone or
    cannot be read."""
    try:
        found = {}
        for each in (Path(proc) / str(pid) / 'smaps_rollup').read_text().splitlines():
            parts = each.split()
            if len(parts) >= 2 and parts[0] in ('Rss:', 'Pss:') and parts[1].isdigit():
                found[f'{parts[0][:-1].lower()}_mb'] = round(int(parts[1]) / 1024, 1)
        return found
    except (OSError, ValueError):
        return {}


def task_limit(environ, fetch=None):
    """RESERVE-NO-DB: the memory limit of this ECS task in MiB (the task metadata endpoint's Limits.Memory: what the
    task definition gives the task), or None outside ECS or when the endpoint does not say. Never raises."""
    where = (environ.get(METADATA) or '').strip()
    if not where:
        return None
    try:
        if fetch is None:
            import urllib.request

            def fetch(url):
                with urllib.request.urlopen(url, timeout=2) as said:  # noqa: S310 - the agent's link-local endpoint
                    return said.read()
        found = float(json.loads(fetch(f'{where}/task'))['Limits']['Memory'])
        return found if found > 0 else None
    except Exception:  # noqa: BLE001 - a limit that is not known is no room
        return None


def memory(environ=None, root=CGROUP, proc=PROC):
    """RESERVE-NO-DB, for a child's word in the engine's log: what its supervisor's state says of the task's memory
    and its reserve, with the container's use and the reserve's own size measured now, by this process (the same
    container, the same cgroup): {task_mb, task_peak_mb, task_limit_mb, reserve: held | no room | off | not its code,
    reserve_mb (its Pss), reserve_rss_mb}; a part that is not known is left out. {} for a process no supervisor
    started. Never raises."""
    spool = supervised(environ)
    if not spool:
        return {}
    try:
        state = json.loads((Path(spool) / STATE).read_text())
        said, now = state.get('memory') or {}, cgroup(root)
        found = {'task_mb': now.get('used_mb', said.get('used_mb')), 'task_peak_mb': now.get('peak_mb', said.get('peak_mb')),
                 'task_limit_mb': said.get('limit_mb'), 'reserve': state.get('reserve')}
        for child in state.get('children') or []:
            if child.get('kind') == RESERVE:
                sized = resident(child.get('pid'), proc)
                found.update(reserve_mb=sized.get('pss_mb'), reserve_rss_mb=sized.get('rss_mb'))
            if child.get('kind') == POOLER:  # TASK-POOLER: what the task's pool holds
                found.update(pool_mb=resident(child.get('pid'), proc).get('pss_mb'))
        return {name: value for name, value in found.items() if value is not None}
    except Exception:  # noqa: BLE001 - a measure, never the event's failure
        return {}


class Supervisor:
    def __init__(self, command, args, environ, spawn=None, clock=time.monotonic, pool=None):
        self.command, self.environ, self.clock = command, dict(environ), clock
        self.spawn = spawn or [sys.executable, '-m', code_bundle.PACKAGE, *args]
        self.dir = Path(tempfile.mkdtemp(prefix='tower-supervisor-'))
        self.health = Path(self.environ.get(HEALTH, '/tmp/tower-infra.healthy'))  # the task's: what `healthy` reads
        self.children, self.born = {}, 0  # pid -> {kind, sha, key, n, health, root}
        self.wanted, self.read = [], None  # [(key, sha)] and the want file's time when it was read
        self.tries, self.failed = {}, []  # sha -> (starts, the last one's time); the bundles given up on
        self.stopping, self.code, self.signals = False, None, []
        self.ended, self.lost = {}, False  # SUCCESSOR-LOST: sha -> successors of it that ended unasked; one to tell of
        self.restart_s, self.tick_s = float(self.environ.get(RESTART_S, 5)), float(self.environ.get(TICK_S, 5))
        # RESERVE-NO-DB: the reserve's command (the word before the role's), the bundles whose code holds none, the
        # room a reserve needs, the task's limit (read once, when first asked) and what the state says of the reserve
        cut = len(self.spawn) - len(args) if args and self.spawn[-len(args):] == list(args) else len(self.spawn)
        self.hold = [*self.spawn[:cut], HOLD, *self.spawn[cut:]]
        self.unheld, self.room_mb, self.limit, self.reserve = {}, float(self.environ.get(ROOM_MB, 160)), False, None
        self.went, self.settle_s = {}, float(self.environ.get(SETTLE_S, 60))  # RESERVE-SETTLE: sha -> when its reserve went
        self.memory, self.stale = {}, False  # STATE-BEFORE-MEASURE: the memory as last measured; a state not measured yet
        # TASK-POOLER: whether this task keeps a pool, its command, its socket's directory and its starts ([when])
        self.pooling = (self.environ.get(POOLS, '') != '0' and bool(self.environ.get('TOWER_DB_HOST'))
                        and command in code_bundle.COMMANDS)
        self.pool_spawn = pool or [sys.executable, '-m', code_bundle.PACKAGE, POOLER, command]
        self.pool_dir, self.pool_starts = self.dir / 'pool', []

    # --- the children -------------------------------------------------------------------------------------------------
    def start(self, kind, key=None, sha=None):
        self.born += 1
        health = self.health.with_name(f'{self.health.name}.{self.born}')
        environ = {**self.environ, DIR: str(self.dir), PID: str(os.getpid()), CHILD: str(self.born), HEALTH: str(health),
                   **({POOL: str(self.pool_dir)} if self.pooling else {})}  # TASK-POOLER: where a child connects
        root, command = None, self.hold if kind == RESERVE else self.pool_spawn if kind == POOLER else self.spawn
        if kind == POOLER:
            self.pool_starts.append(self.clock())
        if kind in (SUCCESSOR, RESERVE):
            root = self.dir / f'code-{self.born}'
            root.mkdir()
            environ = code_bundle.successor(environ, key, sha, root)
        pid = os.posix_spawn(command[0], command, environ)
        self.children[pid] = {'kind': kind, 'sha': sha, 'key': key, 'n': self.born, 'health': health, 'root': root}
        LOG.info('supervisor: %s %s started as pid %d%s', self.command, kind, pid, f' on {sha[:12]}' if sha else '')
        return pid

    def send(self, pid, signum):
        try:
            os.kill(pid, signum)
        except ProcessLookupError:  # it ended already: the reap says so
            pass

    def reap(self):
        """Every child that ended (and, as pid 1, every process the container left behind)."""
        while True:
            try:
                pid, status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            if pid == 0:
                return
            child = self.children.pop(pid, None)
            if child is None:
                continue
            code = os.waitstatus_to_exitcode(status)
            code = 128 - code if code < 0 else code
            (LOG.info if code == 0 or child['kind'] != MAIN else LOG.error)(
                'supervisor: the %s process %d ended with %d', child['kind'], pid, code)
            child['health'].unlink(missing_ok=True)
            if child['root'] is not None:
                shutil.rmtree(child['root'], ignore_errors=True)
            # SUCCESSOR-LOST: a successor that ended and was not told to (not withdrawn, not at the task's stop): the
            # role's process is told once the state says so (run), so it takes the role back at once if the pointer
            # names that bundle, not after deploy.live_stale_s (10 s) with no live beat
            if child['kind'] == SUCCESSOR and not child.get('told') and not self.stopping:
                self.ended[child['sha']] = self.ended.get(child['sha'], 0) + 1
                self.lost = True
                self.promote(child['sha'])  # RESERVE-NO-DB: the bundle's reserve, if one is ready, is its successor now
            # RESERVE-NO-DB: a reserve that ends by itself: its bundle's code holds none (`reserve` is no command of a
            # code before this one), or it failed: no other is tried for that bundle
            if child['kind'] == RESERVE and not child.get('told') and not self.stopping:
                self.unheld[child['sha']] = code
                LOG.warning('supervisor: the reserve on %s ended with %d: none is held for that bundle', child['sha'][:12], code)
            if child['kind'] == MAIN:  # the role's process ended: the task ends, as before; ECS starts it again
                self.code = code
                self.stop()
            # TASK-POOLER: the pool ended: started again at once (its clients log in by themselves meanwhile, and
            # connect to the new one from then), unless it keeps ending
            if child['kind'] == POOLER and not self.stopping:
                recent = [at for at in self.pool_starts if self.clock() - at < 60]
                if len(recent) <= POOL_RESTARTS:
                    self.start(POOLER)
                else:
                    self.pooling = False
                    LOG.error('supervisor: the pool ended %d times in a minute: left; the processes log in by themselves',
                              len(recent))

    def promote(self, sha):
        """RESERVE-NO-DB: the successor of `sha` ended unasked: its reserve, when one said it is ready, is the bundle's
        successor from now (told to go: SIGUSR2, which it waits for) and counts as a start of the bundle's successor
        (a bundle whose successors keep ending is given up on, as before). Answers whether one was promoted."""
        heir = next((pid for pid, child in self.children.items() if child['kind'] == RESERVE and child['sha'] == sha
                     and child.get('ready') and not child.get('told')), None)
        starts, _ = self.tries.get(sha, (0, None))
        if heir is None or sha in self.failed or starts > RESTARTS or sha not in [each[1] for each in self.wanted]:
            return False
        self.children[heir]['kind'] = SUCCESSOR
        self.tries[sha] = (starts + 1, self.clock())
        self.went[sha] = self.clock()  # RESERVE-SETTLE
        self.send(heir, GO)
        LOG.warning('supervisor: the reserve %d on %s is its successor now: the one before it ended', heir, sha[:12])
        return True

    def measured(self):
        """RESERVE-NO-DB: the task's memory now: the container's cgroup (used_mb, peak_mb, limit_mb), the limit the
        lower of the cgroup's and the task's own (the metadata endpoint, asked once), and every child's size."""
        if self.limit is False:
            self.limit = task_limit(self.environ)
        found = cgroup(self.environ.get('TOWER_CGROUP', CGROUP))
        limits = [each for each in (found.get('limit_mb'), self.limit) if each]
        sizes = {str(child['n']): resident(pid) for pid, child in self.children.items()}
        if 'used_mb' not in found and any(sizes.values()):  # no cgroup to read: what the role's processes hold
            found['used_mb'] = round(sum(each.get('pss_mb', each.get('rss_mb', 0)) for each in sizes.values()), 1)
        return {**found, **({'limit_mb': min(limits)} if limits else {}), 'children': sizes}

    def room(self):
        """RESERVE-NO-DB: whether the task has room for a reserve, measured: never (0), always (1: the gate's tests), or
        when what the container uses plus the room a reserve is given fits in the task's limit. No limit, no reserve."""
        mode = self.environ.get(RESERVES, '')
        if mode in ('0', '1'):
            return mode == '1'
        found = self.measured()
        return found.get('limit_mb') is not None and found.get('used_mb') is not None and (
            found['used_mb'] + self.room_mb <= found['limit_mb'])

    def stop(self, signum=signal.SIGTERM):
        """The task is stopping: the signal goes to every child, and nothing is started any more."""
        self.stopping = True
        for pid, child in list(self.children.items()):
            if child['kind'] != POOLER:  # TASK-POOLER: the pool is stopped last (run): a handback goes through it
                self.send(pid, signum)

    # --- what the children say ----------------------------------------------------------------------------------------
    def listen(self):
        """The spool: the yields first (a process that yielded may be gone at the next reap), then the want."""
        for path in sorted(self.dir.glob(f'{HEEDS}*.json')):  # SUCCESSOR-LOST: the children that take SIGUSR2
            path.unlink(missing_ok=True)
            for child in self.children.values():
                if str(child['n']) == path.name[len(HEEDS):-len('.json')]:
                    child['heeds'] = True
        for path in sorted(self.dir.glob(f'{READY}*.json')):  # RESERVE-NO-DB: a reserve that waits for its word
            path.unlink(missing_ok=True)
            for child in self.children.values():
                if child['kind'] == RESERVE and str(child['n']) == path.name[len(READY):-len('.json')]:
                    child['ready'] = True
        for path in sorted(self.dir.glob(f'{YIELD}*.json')):
            try:
                n, sha = int(path.name[len(YIELD):-len('.json')]), json.loads(path.read_text()).get('sha')
            except (OSError, ValueError, AttributeError):
                n, sha = None, None
            path.unlink(missing_ok=True)
            self.yielded(next((pid for pid, child in self.children.items() if child['n'] == n), None), sha)
        try:
            at = (self.dir / WANT).stat().st_mtime_ns
            if at != self.read:
                found = json.loads((self.dir / WANT).read_text()).get('successors') or []
                self.wanted = [(str(each['key']), each['sha']) for each in found if SHA.match(str(each.get('sha')))][:MOST]
                self.read, self.tries, self.failed = at, {}, []  # a new want is a new set of tries
                self.went = {}  # RESERVE-SETTLE: and a new reserve, when its successor beats
        except FileNotFoundError:
            pass
        except (OSError, ValueError, AttributeError, KeyError, TypeError):
            LOG.exception('supervisor: the want could not be read; the last one stands')

    def yielded(self, pid, sha):
        """The main child gives the role to the successor of sha: that one is the main child now and is told to adopt."""
        giver = self.children.get(pid)
        heir = next((each for each, child in self.children.items() if child['kind'] == SUCCESSOR and child['sha'] == sha), None)
        if giver is None or giver['kind'] != MAIN or heir is None:
            LOG.error('supervisor: %s yielded to the successor of %s, which is not here: nothing changes', pid, str(sha)[:12])
            return
        giver['kind'], self.children[heir]['kind'] = RETIRING, MAIN
        self.send(heir, signal.SIGUSR1)
        LOG.info('supervisor: %d gave the role to its successor %d on %s and finishes what it has in flight', pid, heir, sha[:12])

    def reconcile(self):
        """The successors held are the successors wanted."""
        held = {child['sha']: pid for pid, child in self.children.items() if child['kind'] == SUCCESSOR}
        runs = {child['sha'] for child in self.children.values() if child['kind'] == MAIN}
        for sha, pid in held.items():
            if sha not in [each[1] for each in self.wanted] and not self.children[pid].get('told'):
                self.children[pid]['told'] = True
                self.send(pid, signal.SIGTERM)
                LOG.info('supervisor: the successor %d on %s is no longer wanted: stopped', pid, sha[:12])
        for key, sha in self.wanted:
            if sha in held or sha in runs or sha in self.failed:
                continue
            starts, last = self.tries.get(sha, (0, None))
            if starts > RESTARTS:
                self.failed.append(sha)
                LOG.error('supervisor: the successor on %s ended %d times: given up until it is wanted anew', sha[:12], starts)
            elif last is None or self.clock() - last >= self.restart_s:
                self.tries[sha] = (starts + 1, self.clock())
                self.start(SUCCESSOR, key, sha)
        self.spare(runs)

    def spare(self, runs):
        """RESERVE-NO-DB: the task's one reserve: of the first wanted bundle that is not the role's own and whose code
        holds one, started once that bundle's successor is here and beats; a reserve of any other bundle is stopped
        (one whose successor is being started again is kept). `reserve` says how it stands."""
        succeeding = {child['sha']: child for child in self.children.values()
                      if child['kind'] == SUCCESSOR and not child.get('told')}
        wanted = [(key, sha) for key, sha in self.wanted if sha not in runs and sha not in self.failed]
        fit = next(((key, sha) for key, sha in wanted if sha not in self.unheld), None)
        held = False
        for pid, child in self.children.items():
            if child['kind'] != RESERVE or child.get('told'):
                continue
            if fit is None or child['sha'] != fit[1]:
                child['told'] = True
                self.send(pid, signal.SIGTERM)
                LOG.info('supervisor: the reserve %d on %s is no longer wanted: stopped', pid, child['sha'][:12])
            else:
                held = True
        if held:
            self.reserve = 'held'
        elif fit is None:
            self.reserve = 'not its code' if wanted else None
        elif self.environ.get(RESERVES) == '0':
            self.reserve = 'off'
        elif fit[1] not in succeeding or not succeeding[fit[1]]['health'].exists():
            self.reserve = 'waiting'  # the successor first: a reserve's boot never slows the warm-up the landing waits for
        elif fit[1] in self.went and self.clock() - self.went[fit[1]] < self.settle_s:
            # RESERVE-SETTLE: its reserve just went: at a swap the bundle runs the role within seconds and needs none;
            # one started now would be a third process at the task's fullest moment, stopped unused
            self.reserve = 'waiting'
        elif self.room():
            self.start(RESERVE, *fit)
            self.reserve = 'held'
        else:
            self.reserve = 'no room'

    def relay(self):
        """The task's health file has the time of the main child's own: only the role's process keeps the task healthy."""
        for child in self.children.values():
            if child['kind'] == MAIN:
                try:
                    beat = child['health'].stat()
                    self.health.touch()
                    os.utime(self.health, ns=(beat.st_atime_ns, beat.st_mtime_ns))
                except OSError:  # no beat yet (or a read-only path): the health check says so
                    pass

    def say(self):
        state = {'children': [{'n': child['n'], 'pid': pid, 'kind': child['kind'], 'sha': child['sha'],
                               **({'ready': bool(child.get('ready'))} if child['kind'] == RESERVE else {})}
                              for pid, child in self.children.items()],
                 'failed': self.failed, 'lost': self.ended, 'reserve': self.reserve}
        if state != getattr(self, 'said', None):
            self.said = state
            # STATE-BEFORE-MEASURE: the state is written at once with the memory as last measured; the measure of this
            # change (a read of the cgroup and of every child's pages) comes after the signals of the pass (measure):
            # it was on the way of the word to the role's process that a successor ended (the cover's start)
            self.write(state)
            self.stale = True

    def write(self, state):
        draft = self.dir / f'.{STATE}'
        draft.write_text(json.dumps({**state, 'memory': self.memory}))
        os.replace(draft, self.dir / STATE)

    def measure(self):
        """RESERVE-NO-DB: the memory as it is when the state changed (a reserve that said it is ready is a change), in
        the state, after everything the pass had to tell."""
        if self.stale:
            self.stale, self.memory = False, self.measured()
            self.write(self.said)

    # --- the loop -----------------------------------------------------------------------------------------------------
    def run(self):
        wake, woken = os.pipe()
        os.set_blocking(wake, False)
        os.set_blocking(woken, False)
        signal.set_wakeup_fd(woken, warn_on_full_buffer=False)
        for signum in (signal.SIGTERM, signal.SIGINT):
            signal.signal(signum, lambda signum, _frame: self.signals.append(signum))
        for signum in (signal.SIGUSR1, signal.SIGCHLD):
            signal.signal(signum, lambda *_: None)  # only the wake
        if self.pooling:  # TASK-POOLER: before the role's process, which boots for seconds before its first login
            self.pool_dir.mkdir(mode=0o700, exist_ok=True)
            self.start(POOLER)
        self.start(MAIN)
        while any(child['kind'] != POOLER for child in self.children.values()):
            due = [self.restart_s - (self.clock() - last) for _, last in self.tries.values() if last is not None]
            select.select([wake], [], [], max(0.01, min([self.tick_s, *[each for each in due if each > 0]])))
            try:
                os.read(wake, 4096)
            except BlockingIOError:
                pass
            while self.signals:
                self.stop(self.signals.pop(0))
            if not self.stopping:
                self.listen()
            self.reap()
            if not self.stopping:
                self.reconcile()
            self.relay()
            self.say()
            if self.lost:  # SUCCESSOR-LOST: after the state says it
                self.lost = False
                for pid, child in list(self.children.items()):
                    if child['kind'] == MAIN and child.get('heeds'):
                        self.send(pid, signal.SIGUSR2)
            self.measure()  # STATE-BEFORE-MEASURE: after the pass's words
        self.stopping = True
        for pid, child in list(self.children.items()):  # TASK-POOLER: the pool, last
            self.send(pid, signal.SIGTERM)
        limit = self.clock() + 5
        while self.children and self.clock() < limit:
            select.select([wake], [], [], 0.05)
            self.reap()
        for pid in list(self.children):
            self.send(pid, signal.SIGKILL)
        shutil.rmtree(self.dir, ignore_errors=True)
        return 0 if self.code is None else self.code


def run(command, args, environ=None, spawn=None):
    """The supervisor of `command`, until its children ended; answers the exit code of the role's process."""
    return Supervisor(command, args, os.environ if environ is None else environ, spawn).run()
