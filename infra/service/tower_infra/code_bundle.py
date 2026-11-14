"""IMAGE-PREWARM-B1 (docs/operations/aws.md 22.9): the service and the runner boot from a code bundle named by its digest.

Nearly every change touches only the Python of tower_infra; the image's heavy layers (apt, the CLIs, the pip dependencies
of requirements.txt) rarely change. So a standby task for a new head runs the image already built and loads the head's code
at its start, instead of an image built per push. The bundle is scripts/lib/lambda_package.py's build_code: the whole
tower_infra package, infra/db/migrations and infra/service/requirements.txt, deterministic, kept by its sha256 at
artifacts/lambda/tower-code/<sha256>.zip in the outputs bucket. The task is started with

  TOWER_CODE_KEY      the bundle's key in TOWER_ARTIFACT_BUCKET (both task roles may s3:GetObject artifacts/lambda/*)
  TOWER_CODE_SHA256   its sha256 (hex); it is also the task's TOWER_IMAGE_DIGEST (set to it when absent): the pointer
                      deploy.live_image_<role> names code versions

boot(), the very first step of `serve` and `run-container`, downloads the bundle, checks its sha256, checks that its
requirements.txt is the image's (the libraries are the image's: a head that changes them, or the Dockerfile, keeps the slow
path of a new image), unpacks it into a fresh directory and execs the same command with that directory first on PYTHONPATH
(PYTHONSAFEPATH=1: `-m` would otherwise put the image's WORKDIR /app, with the baked package, ahead of it), TOWER_MIGRATIONS
on the bundle's migrations, and TOWER_CODE_LOADED naming the directory, which the child checks against where tower_infra
really runs from, so it neither loops nor lies. TOWER_IMAGE (DBOS's application_version) gets the digest appended: DBOS
recovers at launch the pending workflows of its own version, and a standby with the live image's tag would recover the live
service's workflows under other code.

Fail-safe: a process that cannot load its bundle exits with FAILED before it touches the database, so ECS shows the task
stopped and the caller of RunTask sees it never turned healthy. Going on with the baked code would let a standby claim, by
TOWER_IMAGE_DIGEST, a digest it does not run; clearing the digest would make it a process that works whatever the pointer
says. With neither variable set boot() does nothing at all (today's path); init (the owner's one step) and healthy (the
health check, run every 30 s with the container's environment) never boot.

IMAGE-SWAP-RELOAD (tower_infra.live_image.Reload): an ECS task standing by under a swapped bundle loads it in place. stage()
is boot()'s fetch, checks and unpacking done while the task stands by, so a bundle that cannot be loaded costs nothing
and is never tried again; reload() is boot()'s exec of the same command on the staged directory, the bundle as
TOWER_CODE_KEY, TOWER_CODE_SHA256 and TOWER_IMAGE_DIGEST, with TOWER_CODE_RELOADED (JSON) telling the child what the
reload said, which reloaded() reads there. A child that cannot run the bundle exits FAILED as any boot does; ECS then
starts the task again on its task definition's code, and the reload's record keeps that task from trying the digest again.

SLOW-PATH-NO-ROLLOUT-WAIT (docs/operations/aws.md 22.10): the live code as a durable datum, read at boot. A reload replaces
only a process: a task ECS starts later (a crash, Spot, a rollout for another reason) boots the code of its task
definition, and once the pointer was handed over nothing made it load the swapped bundle; that is why every code-only
landing was still followed by two ECS rollouts with LiveCode. deploy.live_code ('<bundle sha256>@<merge sha>', written by
the live service after a swap) is that code. boot() of a task of an ECS service (never a prewarm standby, TOWER_STANDBY,
which runs exactly its own bundle; never the child of an exec) reads it first, on a connection of its own with short
timeouts (live()), and loads that bundle instead of its definition's when the datum is not the value the deployer saw
when it deployed this task definition (TOWER_CODE_SEEN, the stacks' LiveSeen: a datum the definition has seen is older
than, or the same as, the code deploy.sh gave it; `unknown`: the deployer could not read it, so this definition never
follows the datum) and is not the bundle the definition already names. Fail-safe, toward the task definition's code and
the gate's normal rules: a datum that cannot be read, is empty or malformed, names a bundle a reload failed on, or whose
bundle cannot be loaded (not in the store, another sha256, other requirements) changes nothing.
The directories of bundles loaded earlier (each reload leaves the one it replaced) are removed once this process runs its own.

RELOAD-WITHOUT-STANDBY (tower_infra.live_image.Order): a task that loaded a landed bundle in place with no standby to fall back
on, and whose judge says the bundle does not work, goes back in place: afresh() execs the same command as ECS started the
task with, the names an exec onto a bundle changes put back to what the task definition gave them (BASE, kept by the first
exec of the task), so boot() decides again as at a task's start: deploy.live_code when the definition follows it and no
reload onto it failed, else the definition's own code. That is what a task ECS restarts would run, in seconds and on the
task's warm disk.
"""
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

LOG = logging.getLogger('tower_infra.code_bundle')
COMMANDS = ('serve', 'run-container')
PACKAGE, REQUIREMENTS, MIGRATIONS = 'tower_infra', 'requirements.txt', 'migrations'
LOADED = 'TOWER_CODE_LOADED'
# BOOT-PARTS: how old this process was (seconds since its start: an exec keeps it) when the image's interpreter reached
# main (ENTRY), and when the bundle's did after boot() fetched the bundle and exec'ed it (CODE): where a successor's boot
# goes, in the record of a swap whose process was started after the pointer named it (live_image.Gate.refresh, late)
BOOT_ENTRY, BOOT_CODE = 'TOWER_BOOT_ENTRY_S', 'TOWER_BOOT_CODE_S'
# RESERVE-NO-DB: how old a reserve was when its supervisor told it to go (tower_infra.reserve): its boot, for the swap's
# record, is what came after; what came before was paid while nobody waited
WENT = 'TOWER_RESERVE_WENT_S'
CPU_AT = 'TOWER_CPU_AT_GO'  # SWAP-CPU: the container's cpu.stat at the reserve's word (JSON, with the monotonic time)
RELOADED = 'TOWER_CODE_RELOADED'  # IMAGE-SWAP-RELOAD: what the process that reloaded itself onto this bundle said (JSON)
# RELOAD-WITHOUT-STANDBY: what the task definition gave the names an exec onto a bundle changes (JSON, null: unset), set by
# the task's first exec and carried by every later one: the environment afresh() goes back to
BASE = 'TOWER_CODE_BASE'
BASED = ('TOWER_CODE_KEY', 'TOWER_CODE_SHA256', 'TOWER_IMAGE_DIGEST', 'TOWER_IMAGE', 'TOWER_MIGRATIONS')
FAILED = 3
# SLOW-PATH-NO-ROLLOUT-WAIT: the stamp of the task definition (what deploy.live_code was when the deployer deployed it), the
# word for "the deployer could not read it", the prewarm's standby mark (live_image.STANDBY), the datum's shape, and its read:
# the value, and whether a reload onto that bundle failed (platform.deploy.image_reload, IMAGE-SWAP-RELOAD's guard)
SEEN, UNKNOWN, STANDBY = 'TOWER_CODE_SEEN', 'unknown', 'TOWER_STANDBY'
DATUM = re.compile(r'([0-9a-f]{64})@([0-9a-f]{7,64})')
LIVE_TIMEOUT_S = 5
LIVE = ("select v.value #>> '{}', exists (select 1 from log.event e where e.type = 'platform.deploy.image_reload' "
        "and e.tenant_id is null and e.occurred_at > now() - interval '7 days' and e.payload->>'state' = 'failed' "
        "and e.payload->>'digest' = split_part(v.value #>> '{}', '@', 1)) "
        "from work.config_value v join work.tenant t on t.id = v.tenant_id "
        "where t.name = %(tenant)s and v.key = 'deploy.live_code'")
HERE = Path(__file__).resolve().parent  # the tower_infra this process runs: /app/tower_infra in the image


class BundleError(Exception):
    pass


class S3Store:
    """The storage port's get(key) on the outputs bucket; boto3 is the image's (the image has no scripts/lib)."""

    def __init__(self, bucket, s3=None):
        self.bucket, self.s3 = bucket, s3

    def get(self, key):
        if self.s3 is None:
            import boto3
            self.s3 = boto3.client('s3', region_name=os.environ.get('AWS_REGION'))
        return self.s3.get_object(Bucket=self.bucket, Key=key)['Body'].read()


def live(environ):
    """SLOW-PATH-NO-ROLLOUT-WAIT: deploy.live_code as the database has it, and whether a reload onto its bundle failed:
    (value, failed), ('', False) with no row. On a connection of its own, before anything of the process is wired, with
    short timeouts; it raises when the database cannot be reached (the caller keeps the task definition's code)."""
    from . import config_data, database, dbinit
    where = database.settings(environ)
    user, password = environ.get('TOWER_DB_USER', dbinit.SERVICE_ROLE), environ.get('TOWER_DB_PASSWORD')
    options = {'connect_timeout': LIVE_TIMEOUT_S, 'options': f'-c statement_timeout={LIVE_TIMEOUT_S * 1000}'}
    connection = (database.password_connection(where, user, password, **options) if password
                  else database.iam_connection(where, user, **options))
    try:
        found = database.Database(connection).rows(LIVE, {'tenant': environ.get('TOWER_CONFIG_TENANT', config_data.TENANT)})
    finally:
        connection.close()
    return (str(found[0][0] or ''), found[0][1] in (True, 't', 'true')) if found else ('', False)


def newer(environ, sha, read):
    """SLOW-PATH-NO-ROLLOUT-WAIT: (key, sha256) of the live code when this task must boot it instead of its definition's
    (the module's docstring), else None. Never raises."""
    seen = environ.get(SEEN, '').strip()
    if environ.get(STANDBY) or environ.get(LOADED) or seen == UNKNOWN:
        return None
    try:
        datum, failed = read(environ)
    except Exception as error:  # noqa: BLE001 - the fail-safe: the task definition's code
        LOG.warning('code bundle: deploy.live_code could not be read (%s): the code of the task definition', error)
        return None
    found = DATUM.fullmatch(datum.strip())
    if not found or datum.strip() == seen or found.group(1) == sha:
        return None
    if failed:
        LOG.warning('code bundle: a reload onto the live code %s failed: the code of the task definition', found.group(1))
        return None
    return f'artifacts/lambda/tower-code/{found.group(1)}.zip', found.group(1)


def sweep(directory):
    """SLOW-PATH-NO-ROLLOUT-WAIT: the bundle directories beside this process's own are removed: each exec onto a bundle
    (a boot, a reload in place) left the one before it, 1 to 2 MB each, and with no rollout a task lives through many."""
    for other in Path(directory).parent.glob('tower-code-*'):
        if other.is_dir() and other.resolve() != Path(directory).resolve():
            shutil.rmtree(other, ignore_errors=True)


def boot(command, args, environ=None, store=None, execve=os.execve, here=HERE, read=None):
    """None: go on in this process (no bundle asked, or this process already runs it). FAILED: the bundle could not be loaded
    and nothing was done. Otherwise execve replaces the process and this never returns."""
    environ = os.environ if environ is None else environ
    key, sha = environ.get('TOWER_CODE_KEY', '').strip(), environ.get('TOWER_CODE_SHA256', '').strip().lower()
    datum = newer(environ, sha, read or live) if command in COMMANDS else None
    if datum:  # SLOW-PATH-NO-ROLLOUT-WAIT: the live code is newer than this task definition: boot it; if it cannot be, go on
        try:
            directory = unpack(fetch(store, environ, *datum), Path(here), datum[1], environ.get('TOWER_CODE_ROOT'))
            LOG.info('code bundle: the live code %s, not the task definition\'s, loaded into %s; exec %s', datum[0], directory, command)
            execve(sys.executable, [sys.executable, '-m', PACKAGE, *args], child_environ(
                {**based(environ), 'TOWER_CODE_KEY': datum[0], 'TOWER_CODE_SHA256': datum[1]}, directory, datum[1]))
            raise BundleError('execve returned')
        except Exception as error:  # noqa: BLE001 - the fail-safe: the task definition's code and the gate's normal rules
            LOG.warning('code bundle: the live code %s cannot be loaded (%s): the code of the task definition', datum[0], error)
    if command not in COMMANDS or not (key or sha):
        return None
    try:
        if not key or not sha:
            raise BundleError('TOWER_CODE_KEY and TOWER_CODE_SHA256 go together')
        digest = environ.get('TOWER_IMAGE_DIGEST', '').strip()
        if digest and digest != sha:
            raise BundleError(f'TOWER_IMAGE_DIGEST {digest} is not the bundle {sha}')
        if environ.get(LOADED):
            if Path(here).resolve() != Path(environ[LOADED]).resolve() / PACKAGE:
                raise BundleError(f'{LOADED} is {environ[LOADED]} but tower_infra runs from {here}')
            LOG.info('code bundle: %s runs bundle %s from %s', command, sha, environ[LOADED])
            restore(environ)
            sweep(environ[LOADED])
            return None
        directory = unpack(fetch(store, environ, key, sha), Path(here), sha, environ.get('TOWER_CODE_ROOT'))
        LOG.info('code bundle: %s loaded into %s; exec %s', key, directory, command)
        execve(sys.executable, [sys.executable, '-m', PACKAGE, *args], child_environ(based(environ), directory, sha))
        raise BundleError('execve returned')
    except Exception as error:  # noqa: BLE001 - the fail-safe: never take work under a digest this process does not run
        LOG.error('code bundle: cannot load %s (%s): exiting before any work', key or sha, error)
        return FAILED


def fetch(store, environ, key, sha):
    if store is None:
        bucket = environ.get('TOWER_ARTIFACT_BUCKET', '').strip()
        if not bucket:
            raise BundleError('no TOWER_ARTIFACT_BUCKET to read the bundle from')
        store = S3Store(bucket)
    data = store.get(key)
    if data is None:
        raise BundleError(f'{key} is not in the store')
    found = hashlib.sha256(data).hexdigest()
    if found != sha:
        raise BundleError(f'{key} has sha256 {found}, not {sha}')
    return data


def unpack(data, here, sha, root=None):
    """The bundle in a fresh directory, once it is known to run on this image's libraries."""
    baked = here.parent / REQUIREMENTS  # /app/requirements.txt, what the image's pip layer installed
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        if f'{PACKAGE}/__main__.py' not in names:
            raise BundleError(f'the bundle has no {PACKAGE}/__main__.py')
        if REQUIREMENTS not in names or not baked.is_file() or archive.read(REQUIREMENTS) != baked.read_bytes():
            raise BundleError(f'the bundle\'s {REQUIREMENTS} is not the image\'s: its code needs a new image')
        directory = Path(tempfile.mkdtemp(prefix=f'tower-code-{sha[:12]}-', dir=root or None))
        archive.extractall(directory)
    return directory


def stage(key, sha, environ=None, store=None, here=HERE):
    """IMAGE-SWAP-RELOAD: the bundle fetched, checked (its sha256; its requirements.txt against the code this process runs,
    which is the image's) and unpacked while this process goes on; answers its directory. Raises when the bundle cannot
    be loaded: nothing was done, and the caller does not reload."""
    environ = os.environ if environ is None else environ
    return unpack(fetch(store, environ, key, sha), Path(here), sha, environ.get('TOWER_CODE_ROOT'))


def reload(command, key, sha, directory, said, environ=None, execve=os.execve):
    """IMAGE-SWAP-RELOAD: this process replaced in place by the same command on the staged bundle: boot()'s exec, with the
    bundle as TOWER_CODE_KEY, TOWER_CODE_SHA256 and TOWER_IMAGE_DIGEST, TOWER_IMAGE back to the image's (a bundle this
    process booted from appended its own digest) and `said` for the child (RELOADED). It does not return."""
    environ = holder(based(os.environ if environ is None else environ))
    environ.update({'TOWER_CODE_KEY': key, 'TOWER_CODE_SHA256': sha, RELOADED: json.dumps(said),
                    'TOWER_IMAGE': environ.get('TOWER_IMAGE', 'local').split('+code.')[0]})
    execve(sys.executable, [sys.executable, '-m', PACKAGE, command], child_environ(environ, Path(directory), sha))
    raise BundleError('execve returned')


def holder(environ):
    """ADOPTED-EXEC-IS-MAIN: the environment of a process that replaces itself in place, without the in-task successor's
    mark. Only the process that holds its task's role execs itself (a standby is strict and follows no reload and no
    order), and one that was a successor and adopted the role still carried TOWER_STANDBY=intask: the process it became
    stood by as a strict successor of a bundle no pointer named, and the role had no process (live 11/11: no dispatch
    for 7.7 min). A Spot standby's mark is the prewarm's and stays."""
    if environ.get(STANDBY) == INTASK:
        environ = {name: value for name, value in environ.items() if name != STANDBY}
    return environ


def based(environ):
    """RELOAD-WITHOUT-STANDBY: a copy of the environment with BASE: what the names an exec onto a bundle changes are now,
    kept from the first exec of the task on (a process with no BASE has what the task definition gave it; one that a
    process older than this unit exec'd has its own bundle, and TOWER_IMAGE loses the digest that exec appended)."""
    base = {name: environ.get(name) for name in BASED}
    base['TOWER_IMAGE'] = base['TOWER_IMAGE'] and base['TOWER_IMAGE'].split('+code.')[0]
    return {**environ, BASE: environ.get(BASE) or json.dumps(base)}


def afresh(command, said, environ=None, execve=os.execve):
    """RELOAD-WITHOUT-STANDBY: this process replaced in place by the same command as ECS started the task with: BASE's
    names put back and no bundle marked loaded, so boot() decides again as at a task's start (the module's docstring).
    `said` (RELOADED) tells the child it is no new task: it says no task_up and warms nothing again. It does not return;
    it raises with no BASE (a process no exec onto a bundle started has nothing to go back to)."""
    environ = holder(dict(os.environ if environ is None else environ))  # ADOPTED-EXEC-IS-MAIN
    if not environ.get(BASE):
        raise BundleError(f'no {BASE}: this process was not started by an exec onto a bundle')
    for name, value in json.loads(environ.pop(BASE)).items():
        if value is None:
            environ.pop(name, None)
        else:
            environ[name] = value
    environ.pop(LOADED, None)
    environ[RELOADED] = json.dumps(said)
    execve(sys.executable, [sys.executable, '-m', PACKAGE, command], environ)
    raise BundleError('execve returned')


INTASK = 'intask'  # IN-TASK-STANDBY: TOWER_STANDBY's value for a successor inside the ECS task of its role


def successor(environ, key, sha, root):
    """IN-TASK-STANDBY: the environment of a successor process of this task (tower_infra.supervisor) for the bundle
    (key, sha): what ECS gave the task (BASE's names and the Python path put back, no bundle marked loaded, no reload
    said) with the standby's names the prewarm gave a Spot task: the bundle as TOWER_CODE_KEY, TOWER_CODE_SHA256 and
    TOWER_IMAGE_DIGEST, and TOWER_STANDBY (INTASK). boot() then loads the bundle as any standby's, into `root`, a
    directory of the successor's own: the processes of one task never sweep each other's code."""
    found = dict(environ)
    for name, value in json.loads(found.pop(BASE, None) or '{}').items():
        found.pop(name, None) if value is None else found.update({name: value})
    restore(found)
    for name in (LOADED, RELOADED):
        found.pop(name, None)
    found.update({'TOWER_CODE_KEY': key, 'TOWER_CODE_SHA256': sha, 'TOWER_IMAGE_DIGEST': sha, STANDBY: INTASK,
                  'TOWER_CODE_ROOT': str(root)})
    return found


def reloaded(environ=None):
    """IMAGE-SWAP-RELOAD: what the reload that started this process said ({digest, from, turn, wrote_at, at, ...}); None
    for a process started any other way, or one that no longer runs that digest."""
    environ = os.environ if environ is None else environ
    try:
        said = json.loads(environ.get(RELOADED) or 'null')
    except ValueError:
        return None
    return said if isinstance(said, dict) and said.get('digest') == environ.get('TOWER_IMAGE_DIGEST') else None


PRIOR = 'TOWER_CODE_PRIOR_'  # BUNDLE-ENV-LEAK: the values PYTHONPATH and PYTHONSAFEPATH had before the exec ('-' = unset)
RESTORED = ('PYTHONPATH', 'PYTHONSAFEPATH')


def restore(environ):
    """BUNDLE-ENV-LEAK: once this process runs the bundle (its sys.path is set at start), put PYTHONPATH and PYTHONSAFEPATH
    back as they were before the exec, so what it runs (setup, the head's checks and tests) is not on the bundle's path."""
    for name in RESTORED:
        prior = environ.pop(PRIOR + name, None)
        if prior is None:
            continue
        if prior == '-':
            environ.pop(name, None)
        else:
            environ[name] = prior


def child_environ(environ, directory, sha):
    found, path = dict(environ), [str(directory)] + ([environ['PYTHONPATH']] if environ.get('PYTHONPATH') else [])
    found.update({PRIOR + name: environ.get(name, '-') for name in RESTORED})
    found.update({'PYTHONPATH': os.pathsep.join(path), 'PYTHONSAFEPATH': '1', 'TOWER_MIGRATIONS': str(directory / MIGRATIONS), 'TOWER_IMAGE_DIGEST': sha,
                  'TOWER_IMAGE': f"{environ.get('TOWER_IMAGE', 'local')}+code.{sha[:16]}", LOADED: str(directory)})
    return found


def age_s(stat='/proc/self/stat', uptime='/proc/uptime', ticks=None):
    """BOOT-PARTS: the seconds since this process started (the kernel's start time of the pid, which an exec keeps), or
    None where the kernel does not say (no /proc). Never raises."""
    try:
        with open(stat, encoding='utf-8') as found:
            started = int(found.read().rsplit(')', 1)[1].split()[19])  # starttime, in clock ticks since the boot
        with open(uptime, encoding='utf-8') as found:
            up = float(found.read().split()[0])
        return round(up - started / (ticks or os.sysconf('SC_CLK_TCK')), 3)
    except Exception:  # noqa: BLE001 - a part that cannot be measured is left out
        return None


def entered(environ=None, age=age_s):
    """BOOT-PARTS: main() says how old the process is as it enters: ENTRY in the image's interpreter, CODE in the
    bundle's (LOADED is set). Kept in the environment, which the exec passes on."""
    environ = os.environ if environ is None else environ
    found = age()
    if found is not None:
        environ[BOOT_CODE if environ.get(LOADED) else BOOT_ENTRY] = str(found)
    return found
