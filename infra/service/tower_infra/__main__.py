"""The infrastructure's service (P3 F1): `python -m tower_infra init | serve | run-container | healthy`.

init     the task's init container: the owner's one step (dbinit), with the owner's password it alone receives.
restore-check  RESTORE-DRILL: one line of JSON with what the database of TOWER_DB_HOST holds, read only, as the owner
         (tower_infra.restore_check): the reading of an instance restored from the backup, and of production beside it.
serve    the service container: connects as the IAM database user, applies the migrations of infra/db, launches DBOS with
         its tables in the schema dbos of the same database, and runs the dispatcher (P3 F3): every tick it reaps the
         expired leases, dispatches what can go and starts one workflow per run (tower_infra.workflows); every heartbeat
         a good tick marks it healthy, and every hour it keeps the next partition of log.event ahead. Every tick
         also delivers the log's subscriptions (P3 F4, tower_infra.subscriptions) to their HTTPS or SNS sinks and
         follows the AI sessions' runs (P4 F3, tower_infra.sessions; no provider is configured until a subscription's
         transport is, so a session job is refused). A tick comes every service.dispatch_s (work.config_value, DEP9; default 1 s), or at once when work frees
         (INFRA-SVC 5, tower_infra.wake: migration 0006 notifies tower_work).
run-container  the warm runner of the container executor (P4 F1, its own task): takes the runs the dispatcher handed
         over to container executors and runs their command on a checkout (tower_infra.runner, tower_infra.container),
         with the forge's key for git and its signing key for the cache read from Parameter Store when used, the logs
         in TOWER_OUTPUTS_BUCKET, and a heartbeat on every good pass and every lease renewal. An idle runner polls
         every TOWER_POLL_S, or at once when a run is handed over (tower_runs). The task runs TOWER_RUNNER_SLOTS
         runners side by side (INFRA-EXE 1e), each with its own checkout, connection and wake.
healthy  the container's health check: exit 0 while the last good heartbeat is fresh.

IMAGE-PREWARM-A (docs/operations/aws.md 22.9, tower_infra.live_image): with TOWER_IMAGE_DIGEST set, a serve or run-container
whose image is not the one deploy.live_image_<role> names stands by (it beats, it takes no work) and turns live on the
pointer's NOTIFY; with no TOWER_IMAGE_DIGEST or no pointer both run exactly as before. IMAGE-SWAP-SERVICE-READY: the
prewarm's service standby launches DBOS while it stands by (schema verified, not migrated; an executor id of its own).
IMAGE-PREWARM-B1 (tower_infra.code_bundle): with TOWER_CODE_KEY and TOWER_CODE_SHA256 set, serve and run-container first load
that code bundle and exec themselves on it (a bundle that cannot be loaded exits non-zero); without them, nothing changes.
IMAGE-SWAP-RELOAD (live_image.Reload): an ECS task standing by under a bundle a landing swapped to loads it in place once
nothing of its own is in flight (the service's DBOS workflows and looks, the runner's runs) and takes the role over.
IMAGE-SWAP-TICK: under TOWER_IMAGE_DIGEST the service's loop keeps one connection of its own for the standby's beat and
the dispatch tick, and it and the runner's kept connections commit each statement by themselves (one round trip).
IN-TASK-STANDBY (tower_infra.supervisor): as the container's first process, serve and run-container are the supervisor of
the role's processes: the child it starts is the process described here, and so is each successor it holds.
RELOAD-WITHOUT-STANDBY (live_image.Order): a live ECS task follows the order to load a landed bundle in place when the
landing found no standby pair: the runner after its runs in flight, then the service between two ticks, each judged by
the other, and neither touches its health file from its reload until its judge says proven.

Every interval is a value of the environment with a default (D-308). TOWER_DB_PASSWORD, for a local run only, makes
the serve connection use a password instead of an IAM token.
"""
import json
import logging
import os
from pathlib import Path
import signal
import socket
import sys
import threading
import time

from . import dbinit, migrations

LOG = logging.getLogger('tower_infra')
PRODUCER = 'infra-service'
WARM_EVENT = ("insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
              "values (%(id)s, null, 'platform.runner.warm', clock_timestamp(), 'runner', 'runner/warm', %(payload)s::jsonb)")
# SLOW-PATH-NO-ROLLOUT-WAIT: a task ECS started is up, and the autodeploy look is woken at once on the channel of migration
# 0009 (its trigger does not name this type): the rollout of the task's stack is seen without waiting for a clock
UP_EVENT = ("with said as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
            "values (%(id)s, null, 'platform.deploy.task_up', clock_timestamp(), %(producer)s, 'deploy/task', %(payload)s::jsonb) "
            "returning type) select pg_notify('tower_deploy', type) from said")
# GATE-SHUTDOWN (14/11/2026, D-314; PR #17 stopped the AWS gate): the looks serve() starts, by module. The gate's own
# (they served the AWS gate on Origin: its standbys, its runner, its check runs, its PR reads, its merges and its full
# runs) start only when service.gate_looks is true; the kept ones serve the deploy, the port and the account's hygiene
GATE_LOOKS = ('prewarm', 'ondemand', 'checks', 'observations', 'merge_ready', 'pregate', 'fullrun', 'branches')
KEPT_LOOKS = ('autodeploy', 'drill_look', 'prune')


def number(name, default):
    return float(os.environ.get(name, default))


def health_file():
    return Path(os.environ.get('TOWER_HEALTH_FILE', '/tmp/tower-infra.healthy'))


def parameter(name, fresh_s=None):
    """A SecureString of Parameter Store, read when asked and kept for a few minutes; None while it does not exist.
    ORIGIN-ACCESS-GONE (15/11/2026): no name (the variable unset) reads nothing and answers None."""
    if not name:
        return lambda: None
    kept = {}

    def read():
        if kept and time.monotonic() - kept['at'] < (number('TOWER_PARAMETER_FRESH_S', 300) if fresh_s is None else fresh_s):
            return kept['value']
        import boto3
        client = boto3.client('ssm', region_name=os.environ.get('AWS_REGION'))
        try:
            value = client.get_parameter(Name=name, WithDecryption=True)['Parameter']['Value']
        except client.exceptions.ParameterNotFound:
            value = None
        kept.update(value=value, at=time.monotonic())
        return value
    return read


def migrations_dir():
    return Path(os.environ.get('TOWER_MIGRATIONS', '/app/migrations'))


def init():
    from . import database
    where = database.settings(role='init')
    connection = database.password_connection(where, os.environ['TOWER_DB_OWNER'], os.environ['TOWER_DB_OWNER_PASSWORD'])
    try:
        dbinit.init(database.Database(connection), where['name'])
    finally:
        connection.close()
    LOG.info('init: %s may log in by IAM and create schemas in %s', dbinit.SERVICE_ROLE, where['name'])


def restore_check(out=print):
    """RESTORE-DRILL (architecture review, finding 25): one line of JSON with what the database holds (restore_check.
    facts), read in a read-only session with the owner's credentials (the init container's: TOWER_DB_OWNER and its
    password), on the host TOWER_DB_HOST names: the instance restored from tower-data's backup, and production for the
    comparison. Run by the account's owner as the init container's command of a task started for it."""
    from . import database, restore_check as reading
    where = database.settings(role='init')
    connection = database.password_connection(where, os.environ['TOWER_DB_OWNER'], os.environ['TOWER_DB_OWNER_PASSWORD'],
                                              purpose='restore-check')
    try:
        out(json.dumps({'restore_check': reading.facts(database.Database(connection)), 'host': where['host']},
                       sort_keys=True))
    finally:
        connection.close()
    return 0


def migrate(engine):
    from . import database
    raw = engine.raw_connection()
    try:
        return migrations.migrate(database.Database(raw.driver_connection), migrations_dir(), PRODUCER)
    finally:
        raw.close()


def deliver(engine, sinks):
    """One pass of the log's subscriptions on a connection of the engine; answers what each sink accepted."""
    from . import database, subscriptions
    raw = engine.raw_connection()
    try:
        return subscriptions.deliver(database.Database(raw.driver_connection), sinks,
                                     limit=int(number('TOWER_SUBSCRIPTION_BATCH', 100)),
                                     settle=os.environ.get('TOWER_SUBSCRIPTION_SETTLE', '5 seconds'))
    finally:
        raw.close()


def refresh_keys(forge_webhooks, workflows):
    """The forge's webhook keys (P4 F2b): the service reaches Origin's JWKS, the port's Lambda does not (D-309), so the
    service records them in the log when they change. Best effort: a failure is logged and the tick goes on."""
    try:
        with workflows.connected() as db:
            if forge_webhooks.refresh(db, url=os.environ.get('TOWER_FORGE_KEYS_URL', forge_webhooks.KEYS_URL)):
                LOG.info("serve: the forge's webhook keys changed")
            parameter = os.environ.get('TOWER_FORGE_KEYS_PARAMETER')
            # PORT3: the webhook ingress verified from this parameter, without a database. GATE-SHUTDOWN: the ingress is
            # gone (PR #17) and no task definition names the parameter any more, so nothing is published
            if parameter:
                import boto3
                ssm = boto3.client('ssm', region_name=os.environ.get('AWS_REGION'))
                forge_webhooks.publish(db, lambda name, value: ssm.put_parameter(
                    Name=name, Value=value, Type='String', Overwrite=True), parameter)
    except Exception as error:  # noqa: BLE001 - the keys only matter to the webhooks; nothing else stops
        LOG.warning("serve: the forge's webhook keys were not refreshed: %s", error)


def pooled(engine):
    """A scope over a pooled connection of the engine (IMAGE-PREWARM-A: the gate reads before workflows.ENGINE is set)."""
    import contextlib
    from . import database

    @contextlib.contextmanager
    def scope():
        raw = engine.raw_connection()
        try:
            yield database.Database(raw.driver_connection)
        finally:
            raw.close()
    return scope


POOL_READY = 4  # POOL-READY: the pooled connections a service standing by keeps open for the swap


def pool_ready(engine, count=POOL_READY):
    """POOL-READY: `count` connections of the pool taken at once and given back, so the pool holds that many, logged in
    (and each one pinged: pool_pre_ping). The pool opens a connection only when every one it has is in use, and a
    service standing by uses one at a time: at the swap its threads asked for several at once and the pool logged in
    then (live 12/11 10:23 UTC: a login of tower-service:pool inside the swap's instant, the pointer read 0.69 s after
    its write, the swap 0.71 s; a login is a fork, TLS and the IAM token's check on a host that pages). The standby
    calls this once, when it first warms (live_image.Warm.primed): the logins are its start's, minutes before a
    landing. Never more than the pool's own size keeps."""
    held = []
    try:
        for _ in range(count):
            held.append(engine.raw_connection())
    finally:
        for raw in held:
            raw.close()
    return len(held)


def ready_ahead(engine):
    """What a service standing by readies besides its warm-up, once, when it first warms (READY-ONCE: never at a
    readiness signal, a second before a landing): POOL-READY, its pool's connections; LOOK-READS-WHAT-IS-NEW: the 7
    days of pushes and landings its first look after the swap would read (the look then reads what is new)."""
    from . import autodeploy
    pool_ready(engine)
    autodeploy.read_ahead(pooled(engine))  # the pool's scope: a standby has no workflows.ENGINE yet


def task_up(role, scope, environ=None):
    """SLOW-PATH-NO-ROLLOUT-WAIT: platform.deploy.task_up {stack, role, task, image, code}, once, when a task of an ECS
    service is up (serve before its first tick, run-container after its warm-up). deploy.sh starts a stack's rollout and
    does not wait for it; the autodeploy rings the build that verifies it when the stack's new task says this, or when
    CloudFormation's event of the stack's end comes, whichever is first (autodeploy.rolling). Not a prewarm standby (it
    is no task of the stack) and not a process that reloaded itself in place (no rollout started it). Never raises:
    without it the verification waits for the stack's event or the safety the build set."""
    from . import code_bundle
    environ = os.environ if environ is None else environ
    if environ.get(code_bundle.STANDBY) or environ.get(code_bundle.RELOADED):
        return False
    task = environ.get('TOWER_RUNNER_NAME') or socket.gethostname()
    try:
        with scope() as db:
            db.rows(UP_EVENT, {'id': f'platform.deploy.task_up:{role}:{task}:{int(time.time())}', 'producer': f'tower-{role}',
                               'payload': json.dumps({'stack': f'tower-app-{role}', 'role': role, 'task': task,
                                                      'image': environ.get('TOWER_IMAGE'),
                                                      'code': environ.get('TOWER_IMAGE_DIGEST')})})
    except Exception:  # noqa: BLE001 - a courtesy to the deploy's clock, never the task's health
        LOG.exception('%s: could not record platform.deploy.task_up', role)
        return False
    return True


def aside(work):
    """IMAGE-SWAP-TICK: work that waits on the network (Parameter Store, the forge's CLI) in a thread of its own: a
    standby's pass never waits for it, so the swap's wake finds the loop free."""
    threading.Thread(target=work, name='aside', daemon=True).start()


def touch_health(engine):
    """The heartbeat: the database answers, then the health file is touched."""
    import sqlalchemy
    with engine.connect() as beat:  # not `connection`: the Wake lambdas of serve resolve that name when they run
        beat.execute(sqlalchemy.text('select 1'))
    health_file().touch()


def serve():
    from . import canary, code_bundle, container, database, live_image, stall, vitals
    intask = live_image.heed()  # IN-TASK-STANDBY: a successor inside the task hears its supervisor from its start
    from dbos import DBOS

    where = database.settings(role='service')  # DB-LISTEN-ONE: its connections are named tower-service:<purpose>
    user, password = os.environ.get('TOWER_DB_USER', dbinit.SERVICE_ROLE), os.environ.get('TOWER_DB_PASSWORD')
    engine = database.iam_engine(where, user, token=(lambda: password) if password else None)
    # IMAGE-PREWARM-A: None without TOWER_IMAGE_DIGEST; a standby applies no migration (its image may not have landed)
    # SWAP-CPU: the loop's connection is made before the gate, and the gate's first read goes through it: one statement
    # on a kept psycopg connection (0.08 s for the runner's gate at the drill of 12/11 21:51 UTC), not the engine's first
    # connection with its dialect's setup and its ping (0.36 s for the service's)
    early = container.Reconnecting(
        lambda: connection(database, where, user, password, purpose='loop', autocommit=True), database.Database)
    gate = live_image.gate('service', os.environ.get('TOWER_IMAGE_DIGEST'), pooled(engine),
                           os.environ.get('TOWER_CONFIG_TENANT', live_image.config_data.TENANT),
                           strict=bool(os.environ.get(live_image.STANDBY)),  # IMAGE-PREWARM-B2: a prewarm standby
                           intask=intask, task=live_image.named(socket.gethostname()),  # IN-TASK-STANDBY: its own name
                           reloaded=code_bundle.reloaded(),  # IMAGE-SWAP-RELOAD: an ECS task that reloaded itself
                           first=early.scope if os.environ.get('TOWER_IMAGE_DIGEST', '').strip() else None)
    # IMAGE-SWAP-TICK: the loop's own connection, kept: a standby's beat goes through it every pass, so the first tick after
    # a swap finds it open and its backend warm (no pool checkout and its ping, never a new login with its IAM token and TLS
    # on the swap's second), and each statement commits by itself: one round trip, not BEGIN, the statement and COMMIT
    loop = None if gate is None else early
    # LATE-NO-MIGRATE: a successor inside its task applies none at its start, whatever its pointer says: the task's own
    # process applied the image's, a bundle the pointer may name carries none of its own (a head with a migration is no
    # code-only landing), and for one started under a pointer that already names it (the role waits for it) the pass
    # (a login, the lock, the partitions) was on the role's clock. LOGIN-AHEAD: and that one's loop logs in from now,
    # beside the launch, not after it
    if gate is not None and gate.strict and intask and gate.live is True:
        loop.ahead()
        LOG.info('serve: a successor under its own pointer: no migration pass, the loop logs in ahead')
    elif gate is None or gate.live is not False:
        LOG.info('serve: migrations applied now: %s', migrate(engine) or 'none')
    else:
        LOG.info('serve: standing by (deploy.live_image_service is %s): no migration applied', gate.pointer)
    # IMAGE-SWAP-SERVICE-READY: the prewarm's standby (strict) launches DBOS while it stands by, so the swap finds it ready.
    # It verifies the system schema and never migrates it (its dbos is the image's, B1; a schema behind it fails the launch:
    # the standby exits, never beats, and the landing takes the slow path); its application version is its own (code_bundle)
    # and so is its executor id, so its recovery at launch finds nothing of another process, even one of the same bundle
    ready = gate is not None and gate.strict
    version = os.environ.get('TOWER_IMAGE', 'local')  # a bundle's carries its digest (code_bundle: +code.<sha16>)
    DBOS(config={'name': 'tower-infra', 'system_database_engine': engine, 'dbos_system_schema': 'dbos',
                 'application_version': version,
                 **({'run_migrations': False, 'executor_id': f'standby-{gate.task}'} if ready else {})})
    import boto3
    from . import forge, forge_webhooks, sessions, subscriptions, workflows  # registered before the launch
    # LATE-SETUP-SAID: the SNS client is made at the first event sent to SNS, not on the way of the swap
    sinks = subscriptions.Sinks(sns_of=lambda: boto3.client('sns', region_name=os.environ.get('AWS_REGION')))
    live_image.mark(gate, 'dbos')  # LATE-SETUP-SAID: DBOS configured, the package's modules imported
    workflows.ENGINE['engine'] = engine
    from . import checks
    poster = checks.from_environ(workflows.connected)  # CHECK-IN-LANDING: the landing posts tower/gate with it too
    import urllib.request  # OBSERVE-HTTP: the PR observation's reads over HTTP with the forge's kept token
    origin_forge = forge.OriginForge(credential=parameter(os.environ.get('TOWER_FORGE_KEY_PARAMETER')), post_check=None if poster is None else poster.post,
        opener=urllib.request.urlopen)
    workflows.register('forge', origin_forge)
    from . import api_providers, cursor_agents  # P4 F3, D-310, D-311: the transports; each key is read when used
    providers = {'cursor': cursor_agents.CursorAgents(parameter(os.environ.get('TOWER_CURSOR_SESSIONS_KEY_PARAMETER',
                                                                               '/tower/sessions/cursor')))}
    from . import cli_sessions  # the subscription CLIs (claude -p, codex exec); a credential is read when a run starts
    readers = {name: parameter(f'/tower/sessions/{name}', fresh_s=0)  # never cached: the Torre shares and renews it
                for name in cli_sessions.NAMES}

    def renew(name, value):  # the task role may lack ssm:PutParameter here: cli_sessions then reports the credential unsaved
        boto3.client('ssm', region_name=os.environ.get('AWS_REGION')).put_parameter(
            Name=name, Value=value, Type='SecureString', Overwrite=True)

    def session(work):
        """IMAGE-SWAP-RELOAD: a CLI session runs in this process (its end saves the credential the CLI renewed): it is
        work in flight, which a reload of this task waits for."""
        def worker():
            with live_image.engaged(gate, 'session'):
                work()
        threading.Thread(target=worker, name='session', daemon=True).start()
    providers.update(cli_sessions.providers(lambda name: readers[name](), renew,
                                            parameter(os.environ.get('TOWER_FORGE_KEY_PARAMETER')), spawn=session))
    models = api_providers.allowed(os.environ.get('TOWER_API_MODELS'))  # no model named, no API provider spends
    providers.update(api_providers.providers(models, lambda name: parameter(f'/tower/sessions/{name}'),
                                             os.environ.get('AWS_REGION'), os.environ))
    LOG.info('serve: API models allowed: %s; not providers: %s', json.dumps(models, sort_keys=True),
             api_providers.unknown(models, providers) or 'none')
    followed = sessions.Sessions(workflows.connected, providers=providers,
                                 lease=os.environ.get('TOWER_SESSION_LEASE', '15 minutes'))
    live_image.mark(gate, 'providers')  # SWAP-SECOND: the providers and the sessions made
    workflows.register('session', followed)
    # IMAGE-PREWARM-B2: an ECS task that starts standing by launches DBOS (its system-schema migrations, the version
    # registration, the recovery of pending workflows) only when it turns live; with no gate, or a prewarm standby
    # (IMAGE-SWAP-SERVICE-READY, above), it launches here
    launch = live_image.OnceLive(lambda: DBOS.launch(), None if ready else gate)
    # LAUNCH-AFTER-CLAIM: a successor the role waits for (started, or a reserve told to go, under a pointer that already
    # names it) launches DBOS after its first pass's claims are committed, before that pass starts their workflows: the
    # role's work (the reap, the claims a runner takes from the database) needs no DBOS, and the launch (its schema's
    # check, the version's registration, the recovery's reads) was 1.28 s of the 2.38 s with no login at the drill of
    # 12/11 23:11 UTC. Any other process launches here, as before
    deferred = gate is not None and bool(gate.boot)
    if deferred:
        LOG.info('serve: the role waits for this process: DBOS is launched after its first claims')
    elif not launch():
        LOG.info('serve: standing by: DBOS is launched when this image turns live')
    if not deferred:
        # LATE-LAUNCH-SAID: the launch said apart in the swap's record (launch_s)
        live_image.launched(gate, launch.seconds)
        live_image.mark(gate, 'launched')  # LATE-SETUP-SAID

    def pending():
        """IMAGE-SWAP-RELOAD: the workflows of this version DBOS has not ended. A reload waits for them: the reloaded
        process is another application version, and DBOS recovers at its launch only the pending workflows of its own."""
        return [each.workflow_id for each in DBOS.list_workflows(
            status=['PENDING', 'ENQUEUED'], app_version=version, load_input=False, load_output=False)] if launch.done else []
    from . import wake  # INFRA-SVC 5: a tick waits until work frees (migration 0006) or the tick, whichever is first
    # DB-LISTEN-ONE: one connection of this process listens, for the five waiters below (each was a connection of its own)
    # POOL-KEEPS: a successor the role waits for listens after its first work: one connection less before it (the
    # pool gives the new process the connections the lost one left; at 12/11 22:21 UTC it took 7 and logged in twice)
    late_listen = gate is not None and gate.strict and intask and gate.live is True
    hub = wake.Hub(lambda: connection(database, where, user, password, purpose='listen', **wake.KEEPALIVE),
                   (wake.WORK, wake.CONFIG, wake.DEPLOY, wake.TRAIN), later=late_listen)  # TRAIN: MERGE-READY's look
    woken = hub.wake(wake.WORK)
    stop = threading.Event()
    # IMAGE-SWAP-FAILOVER: a promoted standby that is stopped (Spot's warning, a StopTask) hands its pointer back first
    halt = live_image.on_term(gate, quick(database, where, user, password), stop.set)
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: halt())
    from . import lifecycle  # PROCESS-LIFE-IN-LOG: its start, its stop and its loop's failures, in the engine's own log
    # SUCCESSOR-BACK-FASTER: a successor started under a pointer that already names it (its supervisor's, after the swap's
    # own ended) is what the role waits for: it says its start beside its first tick, not before it
    late = gate is not None and intask and gate.active() and gate.pointed()
    lifecycle.begin('service', quick(database, where, user, password), gate, aside=late)
    live_image.orphaned(gate)  # SUCCESSOR-LOST: a successor of this task that ends unasked is heard at once
    live_image.mark(gate, 'lifecycle')  # SWAP-SECOND: the hub, the stop's handler, the start said, the loss heard
    # IMAGE-SWAP-RELOAD: an ECS task standing by under a swapped bundle loads it in place, after its workflows and looks
    reload = None if gate is None else live_image.Reload(gate, 'serve', pending=pending, stopping=stop.is_set)
    # RELOAD-WITHOUT-STANDBY: a live ECS task follows the order to load a landed bundle in place (no standby pair)
    order = None if gate is None or gate.strict else live_image.Order(gate, 'serve', pending=pending, stopping=stop.is_set)
    if intask:  # IN-TASK-STANDBY: a successor looks (the orders, the successors its task should hold) once it adopted the role
        order = live_image.Order(gate, 'serve', pending=pending, stopping=stop.is_set)
    from . import autodeploy  # AUTO1: the deploy rings itself, in its own thread: never on a tick, never on the ingress
    from . import config_data  # DEP9: the behaviour keys are rows of work.config_value; a change notifies tower_config
    live_image.mark(gate, 'orders')  # SWAP-SECOND: the reload's and the order's looks made
    # SETTINGS-HANDED: every read leaves its values in the task's spool, for the process the role waits for
    spool = live_image.supervisor.supervised()
    settings = config_data.Config(workflows.connected, os.environ.get('TOWER_CONFIG_TENANT', config_data.TENANT),
                                  keep=os.path.join(spool, 'settings.json') if spool else None)
    # SETTINGS-ON-LOOP: a successor the role waits for reads its settings on its loop's own connection (open since its
    # gate's read), not on a checkout of the engine's pool with its ping: 0.22 s and 1.13 s from the launch to the
    # settings read at the drills of 12/11 21:51 and 22:21 UTC
    # SETTINGS-HANDED: it starts with what the task's other process read (its read was 0.73 s of the 1.18 s at the drill
    # of 12/11 23:53 UTC: one statement on a database busy in the swap's second) and reads the table after its first work
    handed = gate is not None and bool(gate.boot) and settings.kept()
    if not handed:
        settings.refresh(loop.scope if loop is not None and gate.boot else None)
    live_image.mark(gate, 'settings')  # LATE-SETUP-SAID: the behaviour keys read
    # GATE-SHUTDOWN (14/11/2026, D-314): the gate is GitHub's (tower/gate, the merge queue); the AWS gate's looks, the
    # forge's warm-up and its webhook keys' refresh start only when service.gate_looks is true (read once, here)
    gate_looks = bool(settings.get('service.gate_looks'))
    LOG.info("serve: the gate's looks are %s (service.gate_looks): %s", 'on' if gate_looks else 'off', ', '.join(GATE_LOOKS))
    # ENGINE-REPO: the engine's repository from service.engine_repo, live on tower_config. Imported under its own name:
    # `engine` in serve() is the database's engine (deliver, touch_health, ready_ahead), and a bare `from . import
    # engine` here rebound it to the module (the first deploy from GitHub, 14/11: AttributeError raw_connection, the
    # health file never written, the ECS task replaced and rolled back)
    from . import engine as engine_repo
    engine_repo.use(settings)
    config_data.listen(settings, stop, hub.wake(wake.CONFIG).wait)
    if gate is not None:  # IMAGE-PREWARM-A: the pointer's write (tower_config) is seen at once, never on a poll
        config_data.listen(gate, stop, hub.wake(wake.CONFIG).wait)
    live_image.lowly(autodeploy.start(workflows.connected, stop, wait=hub.wake(wake.DEPLOY).wait,
                     config=settings,  # DEP-EVENTS: pushes and deploy ends wake it (IMAGE-SWAP-SERVICE-READY: after the work)
                     gate=gate,  # IMAGE-SWAP-RELOAD: a look in flight is work a reload of this task waits for
                     active=None if gate is None else gate.after_work(gate.active)))  # SWAP-CPU: no work of the role
    # DRILLS: a port Lambda's rollback rehearsed and Spot's placement failure provoked, when the port is asked
    from . import drill_look
    live_image.lowly(drill_look.start(workflows.connected, stop, hub.wake(wake.DEPLOY).wait,
                                  active=None if gate is None else gate.after_work(gate.sole)))
    # LAMBDA-PRUNE: once a day, the port Lambdas' old versions and the unnamed old packages under artifacts/lambda/
    from . import prune
    live_image.lowly(prune.start(workflows.connected, stop, hub.wake(wake.DEPLOY).wait,
                                 active=None if gate is None else gate.after_work(gate.sole)))
    if gate_looks:  # GATE-SHUTDOWN: the AWS gate's looks (GATE_LOOKS), kept whole behind service.gate_looks
        # IMAGE-PREWARM-B2: a unit branch's push and its bundle job's end (tower_work) wake the look; only the live service
        from . import prewarm as standbys  # not `prewarm`: the module's prewarm() of the runner
        # IMAGE-PREWARM-C: not while sharing; IMAGE-SWAP-SERVICE-READY: after the first work; IMAGE-SWAP-RELOAD: gate, as above
        live_image.lowly(standbys.start(workflows.connected, stop, hub.wake((wake.DEPLOY, wake.WORK)).wait, config=settings,
                                        gate=gate, active=None if gate is None else gate.after_work(gate.sole)))  # SWAP-CPU
        # RUNNER-ON-DEMAND: while Spot cannot place the runner (ECS's placement failure), one on Fargate on demand, stopped
        # once Spot's runner is up again; the live service's alone
        from . import ondemand
        live_image.lowly(ondemand.start(workflows.connected, stop, hub.wake(wake.DEPLOY).wait,
                                        active=None if gate is None else gate.after_work(gate.sole)))
        # CHECK-RUN-AWS: the gate's tower/gate check run, asked at the port, posted by the live service with the Origin app's key
        live_image.lowly(checks.start(workflows.connected, stop, hub.wake(wake.DEPLOY).wait,
                                      active=None if gate is None else gate.after_work(gate.sole), poster=poster))
        # PR-OBSERVATION: what `pr metadata` reads of a PR, asked at the port, read by the live service with the forge's key
        from . import observations
        live_image.lowly(observations.start(workflows.connected, stop, hub.wake(wake.DEPLOY).wait, origin_forge,
                                            active=None if gate is None else gate.after_work(gate.sole)))
        # MERGE-READY (criterion 2): the train front's merge started ahead, at its join, and released by its landing. Not
        # lowly: the merge's process takes this thread's priority (a nice raised is never lowered back without privilege)
        from . import merge_ready
        merge_ready.start(workflows.connected, stop, hub.wake(wake.TRAIN).wait, origin_forge,
                          active=None if gate is None else gate.after_work(gate.sole))
        # PRE-GATE: at each push of a unit branch, its gate's plan and checks run on the runner while the PR is authored
        from . import pregate
        live_image.lowly(pregate.start(workflows.connected, stop, hub.wake((wake.DEPLOY, wake.WORK)).wait,
                                       active=None if gate is None else gate.after_work(gate.sole)))
        # FULL-RUN (revisão da arquitetura, achado 29): at each landing the base's whole battery, no cache, below the gates
        from . import fullrun
        live_image.lowly(fullrun.start(workflows.connected, stop, hub.wake((wake.DEPLOY, wake.WORK)).wait,
                                       active=None if gate is None else gate.after_work(gate.sole)))
        # BRANCH-MERGE: the base merged into a unit's branch and pushed by the live service, in a clone of its own, with the key
        from . import branches
        live_image.lowly(branches.start(workflows.connected, stop, hub.wake(wake.DEPLOY).wait, container.Container(
            os.environ.get('TOWER_BRANCHES_WORKDIR', '/tmp/tower-branches'), credential=parameter(os.environ.get('TOWER_FORGE_KEY_PARAMETER')), slot=branches.SLOT, token_auth=True),
            active=None if gate is None else gate.after_work(gate.sole)))
    # DEPLOY-CANARY: a service that took its role by a swap, or reloaded in place, fires a canary job after its first good tick
    # FIRST-JOB-AT-ONCE: on the loop's own connection (the one that dispatches, and where the successor rehearsed the
    # canary's statements), not a pooled one: live 12/11 12:50 UTC the canary was made 0.6 s after the swap's first tick
    proving = None if gate is None else canary.Live(gate, loop.scope)
    def during(window_s):  # STALL-SAYS-WHAT: what the database was doing in the seconds a pass stalled, on a pooled connection
        with workflows.connected() as db:
            return live_image.busy(db, window_s)
    # DB-VITALS: the live service measures the database's size and connections; STALL-SAYS-WHAT: and asks it about a stall
    measured = vitals.Vitals(settings, evidence=during)
    taking = stall.Watch(settings)  # RUNNER-STALL-ALERT: the live service watches the runs it handed over and no one takes
    # DISPATCH-STALL-ALERT: a service process that stands by watches the jobs ready to be dispatched that nobody starts
    idle = stall.Idle(settings, task=None if gate is None else gate.task)
    # SWAP-TAIL-CUT: a standby warms the first pass's statements (reap, the limits' roll, the held jobs' wake, the queues)
    from . import mechanisms
    # FIRST-JOB-REHEARSED: and a job of no one through the whole path (created, dispatched, taken, ended), rolled back
    from . import rehearsal
    warm = None if gate is None else live_image.Warm(gate, [(sql, None) for sql in (
        mechanisms.REAP, mechanisms.ROLL, mechanisms.WAKE, mechanisms.QUEUES)], primed=lambda: ready_ahead(engine),
        job=lambda cursor: rehearsal.job(rehearsal.Rows(cursor), 'service', lease, canary_of=gate.tenant))
    handed = gate is None  # IMAGE-PREWARM-C: the reconciled ECS task hands the role over after its first live beat
    heartbeat = number('TOWER_HEARTBEAT_S', 30)
    partitions, lease = number('TOWER_PARTITIONS_EVERY_S', 3600), os.environ.get('TOWER_LEASE', '5 minutes')
    last_beat = last_partitions = time.monotonic() - heartbeat
    last_keys = None  # P4 F2b: the forge's webhook keys; the interval is service.forge_keys_every_s (DEP9)
    # IMAGE-SWAP-TICK: the first pass after a swap is the dispatcher's: live 11/11 the swap's canary, made right after the
    # first tick, waited 1.3 to 6.5 s for the second (3.3 to 4.3 s on the reloaded task), the time of the pass's cold
    # reads (the forge's key and token, its webhook keys: a Parameter Store client, the CLI, an HTTPS fetch on 0.25 vCPU).
    # A standby keeps the forge's key warm and puts off its refresh of the webhook keys (its pass, below: the live service
    # refreshes them); a task that reloaded itself reads both here, before its first tick, which is when it takes the
    # role over (Gate.back): until then the promoted standby works
    if gate is not None and gate.reloaded is not None and gate.sharing():
        if gate_looks:  # GATE-SHUTDOWN: the forge's key and its webhook keys serve the AWS gate alone
            origin_forge.warm()
            refresh_keys(forge_webhooks, workflows)
        last_keys = time.monotonic()
        woken.wait(0)  # and its wake is drained before that tick, like a standby's (below)
    LOG.info('serve: up')
    live_image.mark(gate, 'loop')  # LATE-SETUP-SAID: the loop's first pass comes next
    task_up('service', quick(database, where, user, password))  # SLOW-PATH-NO-ROLLOUT-WAIT: the rollout's new task is here
    live_image.mark(gate, 'up')  # LOOP-PARTS: a drill of 13/11 02:31 UTC waited 1.58 s from `loop` to its first pass
    first = True
    while not stop.is_set():
        if gate is not None and gate.gone:  # IN-TASK-STANDBY: the role is its successor's: what is in flight ends, then it
            left = live_image.finish(gate, pending, stop.is_set)
            LOG.info('serve: the role was given to the successor; nothing in flight%s', f' but {left}' if left else '')
            stop.set()  # the looks' threads end as at a stop: this process only leaves
            break
        if gate is not None and not gate.active():  # IMAGE-PREWARM-A: a standby beats and takes no dispatcher work
            try:
                gate.beat(loop)  # IMAGE-SWAP-TIGHTEN: every pass (service.dispatch_s), the landing's evidence of health
                warm.step(loop)  # SWAP-TAIL-CUT: the first pass's statements, rolled back, on the loop's connection
                # IMAGE-SWAP-TICK: the loop's wake listens while it stands by, drained every pass: the first wait after the
                # swap's first tick is no login (an IAM token, TLS) and sees the work notified during that pass (the canary).
                # DB-LISTEN-ONE: the hub's thread listens from the process's start; the drain touches no connection
                woken.wait(0)
                if time.monotonic() - last_beat >= heartbeat:
                    touch_health(engine)
                    last_beat = time.monotonic()
                    lifecycle.beat()  # LIFE-EVENT-RETRY: an event the database refused is written on a good beat
                    idle.beat(loop)  # DISPATCH-STALL-ALERT: an alert when no service dispatches what is ready
                    if gate_looks:  # GATE-SHUTDOWN: the forge's key serves the AWS gate's landings alone
                        aside(origin_forge.warm)  # IMAGE-SWAP-TICK: the swap finds the forge's key and token kept,
                last_keys = time.monotonic()  # and the webhook keys' refresh comes an interval after it, not on its first pass
                reload.step()  # IMAGE-SWAP-RELOAD: under a swapped bundle, after the beat; the exec does not return
            except Exception:  # noqa: BLE001 - a standby that cannot reach the database is not healthy
                LOG.exception('serve: standby beat failed')
            gate.wait(settings.get('service.dispatch_s'))  # turning live wakes it at once
            continue
        try:
            launched = launch.done
            if not deferred or launched:
                launch()  # IMAGE-PREWARM-B2: once, when a standby turned live; a no-op after
            if order is not None:  # RELOAD-WITHOUT-STANDBY: before the tick, so the exec (no return) falls between two
                order.step()  # ticks; no statement unless a look is owed
            if first:  # LOOP-PARTS: the first pass's parts before its claims, in the swap's record (after_read)
                live_image.mark(gate, 'order')
                first = False
            began = time.monotonic()  # IMAGE-SWAP-TIGHTEN: the first dispatch after a swap is when this image works;
            # IMAGE-SWAP-SERVICE-READY: recorded once its claims are committed, before the workflows start. IMAGE-SWAP-TICK:
            # on the loop's connection, timed at its first committed claim (Gate.first_work), with the pass in parts
            timed = {} if gate is None else {'scope': loop.scope, 'first': gate.first_work, 'dispatched': lambda parts: gate.working(
                db=loop, began=began, launch_s=None if launched else launch.seconds, **parts)}  # SWAP-RECORD-WARM: on the loop's
            if deferred and not launched:  # LAUNCH-AFTER-CLAIM: once its claims are committed and recorded
                timed['launch'] = launch
                timed['reap_after'] = True  # SWAP-SECOND: and its first pass claims before it reaps
            started = workflows.tick(lease, **timed)
            measured.passed(time.monotonic() - began, len(started))  # DB-STALL-EVIDENCE: an idle pass that took long is a stall
            if order is not None:  # FAST-PATH-RELOAD: a good tick, the proof of a reload by an order of the service alone
                order.ticked()
            if handed:  # SETTINGS-HANDED: its own read, after its first work
                handed = False
                settings.refresh(loop.scope)
            hub.begin()  # POOL-KEEPS: a late successor listens from its first work on (a no-op for any other)
            if gate is not None:
                gate.live_beat()  # IMAGE-SWAP-FAILOVER: a good tick is the live beat while the pointer names this image
                gate.back()  # IMAGE-SWAP-RELOAD: a reloaded task's first good tick is recorded and it takes the role over
                gate.cover(loop)  # SUCCESSOR-LOST: a process that covers for a successor that ended looks when to stop
                # DEPLOY-CANARY: the role's canary is fired once, then read until its verdict is recorded
                # FIRST-JOB-AT-ONCE: and the one this step just made is dispatched now, in this pass. It waited for
                # the loop's next pass, behind this pass's housekeeping (the sessions, the subscriptions, the forge's
                # key) while every look the swap woke was at its own: live 12/11, ten swaps, 0.40 to 1.54 s from its
                # creation to its run.started (p50 0.93 s), and still 1.51 s once the path's statements were
                # rehearsed (#592: 0.05 s a rehearsal), against 0.03 to 0.10 s on an engine that is not swapping
                if proving.step():
                    started += workflows.tick(lease, scope=loop.scope)
            if started:
                LOG.info('serve: started %d run(s)', len(started))
            with workflows.connected() as db:
                moved = followed.follow(db)
            if moved:
                LOG.info('serve: %d session run(s) moved', len(moved))
            delivered = deliver(engine, sinks)
            if delivered:
                LOG.info('serve: delivered %d event(s) to %d subscription(s)', sum(delivered.values()),
                         len(delivered))
            if gate_looks:  # GATE-SHUTDOWN: no landing of the AWS gate comes, so no key is read for one
                origin_forge.warm()  # AWS6: the key is read here, between ticks, never in a landing's seconds
            now = time.monotonic()
            # RELOAD-WITHOUT-STANDBY: not from a reload by order until its judge says proven: what does not prove itself
            # and does not go back goes unhealthy, and ECS replaces the task with one that boots the code before it
            if now - last_beat >= heartbeat and (order is None or order.trusted()):
                touch_health(engine)
                last_beat = now
                lifecycle.beat()  # LIFE-EVENT-RETRY
                handed = handed or gate.handover()
                with workflows.connected() as db:
                    measured.beat(db)  # DB-VITALS: the connections' peak; a task's first beat also records the sizes
                    taking.beat(db)  # RUNNER-STALL-ALERT: an alert when the runner takes nothing
            if now - last_partitions >= partitions:
                migrate(engine)
                last_partitions = now
                with workflows.connected() as db:
                    measured.record(db)  # DB-VITALS: the hour's platform.db.vitals, and its alerts
                    live_image.sweep(db)  # SWAP-TAIL-CUT: the old standby beats, once an hour and not in every beat
            # GATE-SHUTDOWN: the webhook ingress that verified with these keys is gone (PR #17); off with the gate's looks
            if gate_looks and (last_keys is None or now - last_keys >= settings.get('service.forge_keys_every_s')):
                last_keys = now
                refresh_keys(forge_webhooks, workflows)
        except Exception as failure:  # noqa: BLE001 - a failed tick leaves the health file stale; ECS replaces the task
            LOG.exception('serve: tick failed')
            lifecycle.error('tick', failure)  # PROCESS-LIFE-IN-LOG
        woken.wait(settings.get('service.dispatch_s'))  # the safety tick; work freed wakes it at once
    LOG.info('serve: stopping')
    DBOS.destroy()


def connection(database, where, user, password, **options):
    """A new connection as the service's user: by password for a local run (TOWER_DB_PASSWORD), else by IAM token.
    DB-LISTEN-ONE: options carry its purpose, which with the role of `where` names it (database.named)."""
    return (database.password_connection(where, user, password, **options) if password
            else database.iam_connection(where, user, **options))


def quick(database, where, user, password):
    """IMAGE-SWAP-FAILOVER: a scope over a new connection with short timeouts of its own (live_image.HANDBACK_S to
    connect and per statement): the handback's, so a slow database never holds a stopping task's exit."""
    import contextlib
    from . import live_image

    @contextlib.contextmanager
    def scope():
        found = connection(database, where, user, password, purpose='quick', connect_timeout=live_image.HANDBACK_S,
                           options=f'-c statement_timeout={live_image.HANDBACK_S * 1000}')
        try:
            yield database.Database(found)
        finally:
            found.close()
    return scope


def prewarm(container, boxes, connect, name):
    """F1: before any slot takes a run, fetch the base head and run setup once (container.prewarm), the task's health file
    untouched meanwhile (the old task serves until this one is healthy) and a warming file beating. Seconds, or None when
    off (TOWER_PREWARM_REPO empty) or the warm-up failed; a failure never stops the runner."""
    repo = os.environ.get('TOWER_PREWARM_REPO')
    if not repo:
        return None
    if os.environ.get('TOWER_STANDBY') == 'intask':  # IN-TASK-STANDBY: a successor's task is warm: the checkouts it
        # will work in are the ones its task already keeps. CANARY-OWN-SLOT: but for a slot the task does not have yet
        # (the loop more of a successor whose task started with one less): that checkout alone is warmed, which no
        # process uses, so the first canary that lands on it finds the commit and the setup done
        boxes = [box for box in boxes if not (box.checkout_of({'repo': repo}) / '.git').is_dir()]
        if not boxes:
            return None

    def record(payload):
        from . import database
        db = container.Reconnecting(connect, database.Database)
        db.rows(WARM_EVENT, {'id': f"platform.runner.warm:{name}:{int(time.time())}", 'payload': json.dumps(payload)})
    warming = health_file().with_name(health_file().name + '.warming')
    ok, seconds = container.prewarm(
        boxes, repo, os.environ.get('TOWER_PREWARM_REF', 'mod/roadmap-integration'), heartbeat=warming.touch,
        beat_s=number('TOWER_PREWARM_BEAT_S', 15), timeout_s=number('TOWER_PREWARM_TIMEOUT_S', 300),
        record=record, name=name, log=LOG.info)
    return seconds if ok else None


def run_container():
    from . import code_bundle, config_data, container, database, lifecycle, live_image, runner, wake
    where = database.settings(role='runner')  # DB-LISTEN-ONE: its connections are named tower-runner:<purpose>
    user, password = os.environ.get('TOWER_DB_USER', dbinit.SERVICE_ROLE), os.environ.get('TOWER_DB_PASSWORD')

    def connect():
        return connection(database, where, user, password, purpose='warm')  # the warm-up's record

    def login(purpose='slot'):
        """IMAGE-SWAP-TICK: a connection a slot or the gate keeps: under TOWER_IMAGE_DIGEST each statement commits by
        itself, so the TAKE and the standby's beat are one round trip each, not BEGIN, the statement and COMMIT."""
        return connection(database, where, user, password, purpose=purpose,
                          autocommit=bool(os.environ.get('TOWER_IMAGE_DIGEST', '').strip()))
    # LOGIN-AHEAD: a successor inside its task starts the login of its first slot now, beside its gate's (the gate's
    # login and its read of the pointer came first, then the slot's: two logins in a row before the first TAKE of a
    # successor the role waits for); the first slot that asks for its connection takes it
    early = [container.Ahead(login)] if os.environ.get(live_image.STANDBY) == live_image.INTASK else []

    def kept(purpose='slot'):
        try:
            found = early.pop().result() if purpose == 'slot' else None
        except IndexError:
            found = None
        return login(purpose) if found is None else found
    # DB-LISTEN-ONE: one connection of this process listens, for every slot and for the gate (each was a connection)
    hub = wake.Hub(lambda: connection(database, where, user, password, purpose='listen', **wake.KEEPALIVE),
                   (wake.RUNS, wake.CONFIG, wake.DEPLOY))  # HEAD-ON-PUSH: a push notifies tower_deploy
    forge_key = parameter(os.environ.get('TOWER_FORGE_KEY_PARAMETER'))
    signing_key = parameter(os.environ.get('TOWER_SIGNING_KEY_PARAMETER', '/tower/runner/signing-key'))
    intask = live_image.heed()  # IN-TASK-STANDBY: a successor inside the task: its own name, its supervisor's word heard
    name = live_image.named(os.environ.get('TOWER_RUNNER_NAME') or socket.gethostname())
    # IMAGE-PREWARM-A: None without TOWER_IMAGE_DIGEST (every slot takes runs as before); read on one kept connection
    gate = live_image.gate('runner', os.environ.get('TOWER_IMAGE_DIGEST'),
                           live_image.kept(container.Reconnecting(lambda: kept('gate'), database.Database)),
                           os.environ.get('TOWER_CONFIG_TENANT', config_data.TENANT), task=name,
                           strict=bool(os.environ.get(live_image.STANDBY)),  # IMAGE-PREWARM-B2: a prewarm standby
                           intask=intask,  # IN-TASK-STANDBY: a successor inside the task
                           reloaded=code_bundle.reloaded())  # IMAGE-SWAP-RELOAD: an ECS task that reloaded itself
    # SWAP-TAIL-CUT: a standby slot warms its first TAKE, rolled back, on its own connection
    # FIRST-JOB-REHEARSED: and a run of no one through the runner's whole path, undone, on each slot's connection
    # (RUNNER-OWN-LOGIN: by the owner's function: the runner's login inserts no job of its own)
    if gate is not None:
        from . import rehearsal
        live_image.Warm(gate, [(runner.TAKE, {'adapter': 'container', 'runner': 'warm-up'})],
                        job=lambda cursor: rehearsal.run(rehearsal.Rows(cursor)))
    workers = []
    boxes = []
    stop = threading.Event()
    # IMAGE-SWAP-RELOAD: an ECS task standing by under a swapped bundle loads it in place once no slot has a run
    reload = None if gate is None else live_image.Reload(
        gate, 'run-container', stopping=lambda: stop.is_set() or any(each.interrupted for each in workers))
    # RELOAD-WITHOUT-STANDBY: a live ECS task follows the order to load a landed bundle in place; its slots take no run
    # while it drains, and they do not beat from its reload until the service says it is proven (runner.Runner)
    order = None if gate is None or gate.strict else live_image.Order(
        gate, 'run-container', stopping=reload.stopping, hold=True)
    if intask:  # IN-TASK-STANDBY: a successor looks (the orders, the successors its task should hold) once it adopted the role
        order = live_image.Order(gate, 'run-container', stopping=reload.stopping, hold=True)
    from . import supervisor
    # CANARY-OWN-SLOT: and one loop more, with its own checkout: the capacity gives the runs at most TOWER_RUNNER_SLOTS at
    # once and the deploy canary one of its own (mechanisms.RESERVED), so a loop is free for the canary whatever runs
    for slot in range(max(1, int(number('TOWER_RUNNER_SLOTS', 1))) + 1):  # INFRA-EXE 1e: the task's slots
        box = container.Container(os.environ.get('TOWER_WORKDIR', '/work'), credential=forge_key,
                                  bucket=os.environ.get('TOWER_OUTPUTS_BUCKET'), slot=slot, token_auth=True)
        boxes.append(box)
        workers.append(runner.Runner(container.Reconnecting(kept, database.Database), box.fetch, box.prepare,
                                     box.upload, box.workdir, name=name if not slot else f'{name}/{slot}',
                                     lease=os.environ.get('TOWER_LEASE', '5 minutes'),
                                     renew_every_s=number('TOWER_RENEW_S', 60), signing_key=signing_key,
                                     checkout_of=box.checkout_of,
                                     beat=lambda: health_file().touch() or lifecycle.beat(),  # LIFE-EVENT-RETRY: and a kept event
                                     wait=hub.wake(wake.RUNS).wait,  # INFRA-SVC 5: a run handed over
                                     # IN-TASK-STANDBY: the processes of one task take a slot's checkout one at a time
                                     held=runner.Held(box.workdir, slot) if supervisor.supervised() else None,
                                     order=order, reload=reload, gate=gate))
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    # CANCEL-WAKES-RUNNER: a run whose job is cancelled (a full run's test taken back for a gate) stops at once
    runner.watch_cancels(workers, hub.wake(wake.RUNS).wait, quick(database, where, user, password), stop)
    if gate is not None:  # IMAGE-PREWARM-A: the pointer's write (tower_config) turns a standby live at once
        config_data.listen(gate, stop, hub.wake(wake.CONFIG).wait)
    if os.environ.get('TOWER_PREWARM_REPO'):  # HEAD-ON-PUSH: the heads pushed, fetched beside the slots' checkouts
        container.Pushed(container.Container(os.environ.get('TOWER_WORKDIR', '/work'), credential=forge_key,
                                             slot=container.PUSHED_SLOT, token_auth=True), os.environ['TOWER_PREWARM_REPO']).start(
            quick(database, where, user, password), stop, hub.wake(wake.DEPLOY).wait,
            active=None if gate is None else gate.active)
    # IMAGE-SWAP-RELOAD: a reloaded task was warmed when it started: its checkouts are on its disk, its slots open at once
    # (RELOAD-WITHOUT-STANDBY: and so was one that went back in place, code_bundle.afresh)
    # SUCCESSOR-BACK-FAST: nor is a successor that starts under a pointer that already names it (the one its supervisor
    # started after the swap's own ended): its task is warm, the role waits for it, and the warm-up of a task (the base's
    # head fetched, the setup of every slot) was 3.2 of the 5.9 s the role's new code took to work at the drill of 12/11
    late = gate is not None and intask and gate.active() and gate.pointed()
    warm_s = (None if gate is not None and (os.environ.get(code_bundle.RELOADED) or late)
              else prewarm(container, boxes, connect, name))
    cold = container.cold_start()  # P6 F1: a cold task's start, from its image pull to the runner up
    LOG.info('run-container: up as %s with %d slot(s), prewarm_s=%s%s', name, len(workers),
             'off' if warm_s is None else f'{warm_s:.1f}',
             '' if cold is None else f', {cold:.1f} s after its image pull started')
    task_up('runner', quick(database, where, user, password))  # SLOW-PATH-NO-ROLLOUT-WAIT: warmed, its slots open now
    # PROCESS-LIFE-IN-LOG: its start and its stop. SUCCESSOR-BACK-FASTER: a successor the role waits for says its start
    # beside its first work, not before it (a login and an insert: 0.6 s of the 4.6 s of the drill of 12/11 16:25 UTC)
    lifecycle.begin('runner', quick(database, where, user, password), gate, aside=late)
    live_image.orphaned(gate)  # SUCCESSOR-LOST: a successor of this task that ends unasked is heard at once
    # handles SIGTERM, the Spot interruption. IMAGE-SWAP-FAILOVER: a promoted standby hands its pointer back first
    # SUCCESSOR-BACK-FASTER: and its slots log in one after the first's pass, not four at once (0.84 s, against ~0.2 s alone)
    # SPOT-KEEP: the task's process (not a successor, which leaves at once) keeps taking runs at Spot's warning until
    # the task in its place is up, TOWER_SPOT_KEEP_S (60 s) at most; a rollout's stop finds its new task up already
    def replaced():
        with quick(database, where, user, password)() as db:
            return db.rows(runner.REPLACED, {'task': name})[0][0] in (True, 't')

    def kept_on(interrupt):
        if gate is not None and gate.strict:
            return interrupt
        return runner.keep(workers, interrupt, replaced, number(runner.KEEP_S, 60),
                           said=lambda kept_s, found: lifecycle.note(kept_s=kept_s, replaced=found))
    runner.serve_all(workers, stop, poll_s=number('TOWER_POLL_S', 1), staggered=late,
                     term=lambda interrupt: live_image.on_term(gate, quick(database, where, user, password), kept_on(interrupt)))
    LOG.info('run-container: stopping%s', ' (interrupted)' if any(each.interrupted for each in workers) else
             ' (the role was given to the successor)' if gate is not None and gate.gone else
             ' (no longer the live image)' if gate is not None and gate.retired else '')


def healthy():
    path = health_file()
    fresh = path.exists() and time.time() - path.stat().st_mtime < number('TOWER_HEALTH_FRESH_S', 120)
    return 0 if fresh else 1


def main(argv=None):
    logging.basicConfig(level=os.environ.get('TOWER_LOG_LEVEL', 'INFO'), format='%(asctime)s %(name)s %(message)s')
    args = list(argv if argv is not None else sys.argv[1:])
    command = (args or ['serve'])[0]
    from . import supervisor  # IN-TASK-STANDBY: the container's first process holds the role's processes; its child boots
    # RESERVE-NO-DB: `reserve <command>` is the role's command loaded and waiting, with no connection to the database,
    # for its supervisor's word; the bundle is booted with the same words, so a bundle of a code before this one ends
    # here below (an unknown command), never a second successor
    held = command == supervisor.HOLD and bool(supervisor.supervised())
    if held:
        command = (args[1:] or ['serve'])[0]
    if supervisor.due(command):
        return supervisor.run(command, args or [command])
    from . import code_bundle  # IMAGE-PREWARM-B1: first, the head's code by digest (execs it); None = go on here
    if command in ('serve', 'run-container'):
        code_bundle.entered()  # BOOT-PARTS: how old the process is here, before and after the bundle's exec
    failed = code_bundle.boot(command, args)
    if failed is not None:
        return failed
    if command == 'init':
        init()
        return 0
    if command == 'restore-check':  # RESTORE-DRILL: what the database TOWER_DB_HOST names holds, read only, as the owner
        return restore_check()
    if command == 'pooler':  # TASK-POOLER: the task's connections to its database, kept beside the role's processes
        from . import pooler
        return pooler.main(args[1:])
    if held and command in code_bundle.COMMANDS:
        from . import reserve
        reserve.hold(command)  # returns when this process is told it is the successor: the command, from its first line
    from . import lifecycle  # PROCESS-LIFE-IN-LOG: the stop of the two long commands is said in the engine's log
    if command == 'serve':
        return lifecycle.said(serve)
    if command == 'run-container':
        return lifecycle.said(run_container)
    if command == 'healthy':
        return healthy()
    LOG.error('unknown command %r (init, serve, run-container, healthy or restore-check)', command)
    return 2


if __name__ == '__main__':
    sys.exit(main())
