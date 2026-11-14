"""The service's connections to its database (P3 F1). Only in the image: psycopg, SQLAlchemy and boto3.

The service connects as an IAM database user: every new connection of the engine gets a fresh token
(rds.generate_db_auth_token; a token lives 15 minutes, a pooled connection may live longer), so no password lives in
the service. The init step alone connects with the owner's password, which only its container receives. Database wraps
one psycopg connection in the rows/run shape the migrations, the init step and the port take; a script of many statements
goes by the simple query protocol, since it carries no parameters, and the port's single statements carry theirs.

DB-LISTEN-ONE: every connection says who opened it and what for in its application_name, tower-<role>:<purpose>
(named()): the role is the process's (settings(role=): service, runner, port, consumer), the purpose is the caller's
(listen, loop, pool, slot, gate, ...). platform.db.vitals counts the connections by it (peak_by_app).
"""
from datetime import datetime, timezone
import hashlib
import hmac
import logging
import os
from urllib.parse import quote


LOG = logging.getLogger('tower_infra.database')
POOL = 'TOWER_DB_POOL'  # TASK-POOLER: the directory of the task's pool's socket, in a supervised process's environment
POOL_SAID = 'tower_pool'  # the ParameterStatus the pool tells a client: reused, or login with its parts' milliseconds
# TASK-POOLER: how this process's connections came: from the pool with no login (reused), from the pool by a login
# the pool made (login; login_ms: the parts of the newest, slowest_ms: of the slowest), or by a login of its own (direct)
CAME = {'reused': 0, 'login': 0, 'direct': 0, 'login_ms': {}, 'slowest_ms': {}, 'login_by': {}}


POOL_SIZE, POOL_OVERFLOW = 2, 13  # DB-SWAP-CUT: a process's engine keeps 2 idle connections, 15 at most


def pooled(where, environ=None):
    """TASK-POOLER: the directory of the task's pool (tower_infra.pooler), when this process has one and its socket
    is there; None for a process with no pool (a Lambda, a local run, a task before its pool listens)."""
    environ = os.environ if environ is None else environ
    path = (environ.get(POOL) or '').strip()
    return path if path and os.path.exists(os.path.join(path, f".s.PGSQL.{where['port']}")) else None


def came(connection=None):
    """TASK-POOLER: counts how a connection came (CAME): one of the pool says so itself (POOL_SAID); None is a
    login of this process's own. Never raises: a count."""
    try:
        said = connection.info.parameter_status(POOL_SAID) if connection is not None else None
        if not said:
            CAME['direct'] += 1
        elif said.startswith('login'):
            CAME['login'] += 1
            # POOL-KEEPS: which of the process's connections needed a login (its application_name: its purpose)
            name = connection.info.parameter_status('application_name') or '?'
            CAME['login_by'] = {**CAME['login_by'], name: CAME['login_by'].get(name, 0) + 1}
            parts = {name: float(value) for name, _, value in (each.partition('=') for each in said.split()[1:])}
            CAME['login_ms'] = parts
            if sum(parts.values()) > sum(CAME['slowest_ms'].values() or [0]):
                CAME['slowest_ms'] = parts
        else:
            CAME['reused'] += 1
    except Exception:  # noqa: BLE001
        pass
    return connection


def pool_said(environ=None):
    """TASK-POOLER, for a process's word in the log: {pool: {reused, login, direct, login_ms, slowest_ms}} of its
    connections so far; {} for a process with no pool."""
    environ = os.environ if environ is None else environ
    if not (environ.get(POOL) or '').strip():
        return {}
    said = {'pool': {name: value for name, value in CAME.items() if value}}
    # POOL-KEEPS: and what the task's pool says of itself then (pool.json): its waits for a reset, its logins made while
    # one was in flight, the connections a reset could not clean, its longest reset
    try:
        import json as _json
        with open(os.path.join(environ[POOL].strip(), 'pool.json'), encoding='utf-8') as found:
            task = _json.loads(found.read())
        kept = {name: task[name] for name in ('connections', 'idle', 'logins', 'reused', 'waited', 'waited_ms_max',
                                              'login_while_resetting', 'dirty', 'reset_ms_max', 'reset_again',
                                              'cancel_skipped', 'cancelled') if task.get(name)}
        if kept:
            said['pool_task'] = kept
    except (OSError, ValueError, TypeError):
        pass
    return said


def settings(environ=None, role='engine'):
    """Where the database is, from the environment the task definition sets, and as which role of the engine this
    process connects to it (DB-LISTEN-ONE: named())."""
    environ = os.environ if environ is None else environ
    return {'host': environ['TOWER_DB_HOST'], 'port': int(environ['TOWER_DB_PORT']), 'name': environ['TOWER_DB_NAME'],
            'region': environ.get('AWS_REGION') or environ.get('AWS_DEFAULT_REGION', ''),
            'sslmode': environ.get('TOWER_DB_SSLMODE', 'require'), 'role': role}


def named(where, purpose):
    """DB-LISTEN-ONE: a connection's application_name, tower-<role>:<purpose>."""
    return f"tower-{where.get('role', 'engine')}:{purpose}"


SIGNERS = {}  # LOGIN-ONE-SIGNER: region -> the RDS client this process signs its logins' tokens with


def signer(region, make=None):
    """LOGIN-ONE-SIGNER: the RDS client a login's token is signed with, one a region for the life of the process. Each
    login of an ECS process made a client of its own (the service model's load: tens of milliseconds of CPU, tenths of
    a second on the service's quarter of a vCPU) before it opened its socket, on the swap's second as on any other.
    The signing is local and the client is boto3's, which is safe across threads; its credentials are the session's,
    renewed by it. RESERVE-NO-DB: a reserve makes it ahead (no call is made: a client made is a model loaded)."""
    found = SIGNERS.get(region)
    if found is None:
        if make is None:
            import boto3
            make = boto3.client
        found = SIGNERS.setdefault(region, make('rds', region_name=region))
    return found


def iam_engine(where, user, token=None):
    """A SQLAlchemy engine on psycopg whose connections authenticate as `user` with an IAM token; `token` replaces the
    RDS call (a local run passes a function that returns a password). DB-LISTEN-ONE: its connections are named `pool`
    (DBOS's too: the engine is its system database's, and its own listener is a connection it takes from this pool)."""
    import sqlalchemy
    from sqlalchemy import event

    if token is None:
        def token():
            rds = signer(where['region'])  # LOGIN-ONE-SIGNER (made when a login of this process's own is needed)
            return rds.generate_db_auth_token(DBHostname=where['host'], Port=where['port'], DBUsername=user,
                                              Region=where['region'])
    url = sqlalchemy.URL.create('postgresql+psycopg', username=user, host=where['host'], port=where['port'],
                                database=where['name'], query={'sslmode': where['sslmode']})
    # POOL-LIFO: the pool hands out the connection that came back last, not the one that waited longest. In turns (the
    # default) every statement of the pool went to its coldest backend, and on a host that pages a backend that waited is
    # one paged out (live 12/11: the swap's record, written on a pooled connection, 365 ms). The backends the load does
    # not need stay idle, and their memory is the host's to take
    # DB-SWAP-CUT (revisão da arquitetura, achado 37): the pool keeps POOL_SIZE idle connections, not SQLAlchemy's 5; the
    # same 15 at most (POOL_SIZE + POOL_OVERFLOW), so no burst waits more than before. An overflow connection a burst
    # used goes back to the task's pool (TASK-POOLER), where the task's other process takes it or it is closed
    engine = sqlalchemy.create_engine(url, pool_pre_ping=True, pool_use_lifo=True, pool_size=POOL_SIZE,
                                      max_overflow=POOL_OVERFLOW, connect_args={'application_name': named(where, 'pool')})

    @event.listens_for(engine, 'do_connect')
    def authenticate(dialect, record, cargs, cparams):
        # TASK-POOLER: through the task's pool when it listens (no TLS, no token: the pool holds the login); a pool
        # that does not answer is the login as it was
        pool = pooled(where)
        if pool:
            try:
                return came(dialect.connect(*cargs, **{**{name: value for name, value in cparams.items() if name != 'password'},
                                                      'host': pool, 'sslmode': 'disable'}))
            except Exception as refused:  # noqa: BLE001
                LOG.warning('database: the pool did not give a connection (%s): a login of its own', refused)
        cparams['password'] = token()
        came(None)

    return engine


def auth_token(where, user, environ=None, now=None):
    """The RDS IAM token (a SigV4-presigned `connect` URL, 15 minutes), signed here with the standard library from the
    credentials the Lambda's environment carries. boto3 costs the port's cold start its import and a client (the
    service model's load): seconds on a 256 MB Lambda, against microseconds of HMAC. Without those credentials in the
    environment (a local run) boto3 resolves them."""
    environ = os.environ if environ is None else environ
    key, secret = environ.get('AWS_ACCESS_KEY_ID'), environ.get('AWS_SECRET_ACCESS_KEY')
    if not key or not secret:
        return signer(where['region']).generate_db_auth_token(  # LOGIN-ONE-SIGNER: not a client a login
            DBHostname=where['host'], Port=where['port'], DBUsername=user, Region=where['region'])
    moment = (now or datetime.now(timezone.utc)).strftime('%Y%m%dT%H%M%SZ')
    day, region, host = moment[:8], where['region'], f"{where['host']}:{where['port']}"
    scope = f'{day}/{region}/rds-db/aws4_request'
    query = {'Action': 'connect', 'DBUser': user, 'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
             'X-Amz-Credential': f'{key}/{scope}', 'X-Amz-Date': moment, 'X-Amz-Expires': '900',
             'X-Amz-SignedHeaders': 'host'}
    if environ.get('AWS_SESSION_TOKEN'):
        query['X-Amz-Security-Token'] = environ['AWS_SESSION_TOKEN']
    canonical = '&'.join(f'{quote(name, safe="-_.~")}={quote(query[name], safe="-_.~")}' for name in sorted(query))
    request = f'GET\n/\n{canonical}\nhost:{host}\n\nhost\n{hashlib.sha256(b"").hexdigest()}'
    signing = hmac.new(('AWS4' + secret).encode(), day.encode(), hashlib.sha256).digest()
    for part in (region, 'rds-db', 'aws4_request'):
        signing = hmac.new(signing, part.encode(), hashlib.sha256).digest()
    unsigned = f'AWS4-HMAC-SHA256\n{moment}\n{scope}\n{hashlib.sha256(request.encode()).hexdigest()}'
    signature = hmac.new(signing, unsigned.encode(), hashlib.sha256).hexdigest()
    return f'{host}/?{canonical}&X-Amz-Signature={signature}'


def iam_connection(where, user, purpose='other', phases=None, **options):
    """One psycopg connection authenticated by an IAM token (the Lambda of the port keeps one between calls); options
    are libpq's (IMAGE-SWAP-FAILOVER: the handback's connect_timeout and statement_timeout). DB-LISTEN-ONE: purpose
    names it (named()). PORT-LOGIN-PHASES: with `phases` (a dict), the login says in it where its seconds went."""
    import psycopg
    connect = psycopg.connect if phases is None else phased(phases).connect
    # TASK-POOLER: through the task's pool when it listens (no TLS, no token: the pool holds the login); a pool that
    # does not answer is the login as it was
    pool = pooled(where)
    if pool:
        try:
            return came(connect(host=pool, port=where['port'], dbname=where['name'], user=user, sslmode='disable',
                                application_name=named(where, purpose), **options))
        except Exception as refused:  # noqa: BLE001
            LOG.warning('database: the pool did not give a connection (%s): a login of its own', refused)
    found = connect(host=where['host'], port=where['port'], dbname=where['name'], user=user,
                    password=auth_token(where, user), sslmode=where['sslmode'],
                    application_name=named(where, purpose), **options)
    if pool is not None or os.environ.get(POOL):
        came(None)
    return found


# PORT-LOGIN-PHASES: libpq's connection states (ConnStatus, by name) -> the part of a login each one is; any other: start
PHASES = ('tcp', 'tls', 'auth', 'start')
PHASE_OF = {'STARTED': 'tcp', 'MADE': 'tls', 'SSL_STARTUP': 'tls', 'GSS_STARTUP': 'tls', 'AWAITING_RESPONSE': 'auth'}


def login(pgconn, phases, kinds, clock):
    """PORT-LOGIN-PHASES: libpq's non-blocking connect of `pgconn` (already started), as the driver's own generator
    runs it (psycopg.generators: poll, yield (socket, wait) until ready, poll again), with the clock read around every
    poll and every wait, so `phases` says where a login's seconds went: tcp (the socket), tls (the server's accept, its
    fork of a backend and the TLS handshake), auth (the startup packet to AuthenticationOk: pg_hba and, for an IAM
    user, RDS's check of the token) and start (the backend's own start, to ReadyForQuery: its own part only when it
    comes after AuthenticationOk's packet; a backend that starts at once is inside auth). A poll's time goes to the
    state it began in, a wait's to the state it waits in. `kinds` names the driver's constants: ok, reading, writing
    (PollingStatus), r, w (Wait), bad (ConnStatus) and phase(status). Answers pgconn; a failure raises kinds.error."""
    def spend(status, since):
        now = clock()
        name = kinds.phase(status)
        phases[name] = phases.get(name, 0.0) + now - since
        return now

    mark = clock()
    while True:
        before = pgconn.status
        if before == kinds.bad:
            raise kinds.error(f'connection is bad: {said(pgconn)}')
        polled = pgconn.connect_poll()
        mark = spend(before, mark)
        if polled == kinds.ok:
            return pgconn
        if polled not in (kinds.reading, kinds.writing):
            raise kinds.error(f'connection failed: {said(pgconn)}')
        waits = pgconn.status
        while not (yield pgconn.socket, kinds.r if polled == kinds.reading else kinds.w):
            pass
        mark = spend(waits, mark)


def said(pgconn):
    message = pgconn.error_message
    return message.decode(errors='replace').strip() if isinstance(message, bytes) else str(message).strip()


def phased(phases, clock=None):
    """PORT-LOGIN-PHASES: psycopg's Connection whose connect() fills `phases` (login()): the same parameters, timeout
    and attempts as psycopg.connect, only the generator that polls libpq is this module's."""
    import time
    import psycopg
    from psycopg import pq, waiting
    clock = clock or time.monotonic
    names = {int(status): PHASE_OF.get(status.name, 'start') for status in pq.ConnStatus}

    class Kinds:
        ok, reading, writing = pq.PollingStatus.OK, pq.PollingStatus.READING, pq.PollingStatus.WRITING
        r, w, bad, error = waiting.Wait.R, waiting.Wait.W, pq.ConnStatus.BAD, psycopg.OperationalError

        @staticmethod
        def phase(status):
            return names.get(int(status), 'start')

    class Phased(psycopg.Connection):
        @classmethod
        def _connect_gen(cls, conninfo='', **more):
            pgconn = yield from login(pq.PGconn.connect_start(conninfo.encode()), phases, Kinds, clock)
            pgconn.nonblocking = 1
            return cls(pgconn)

    return Phased


def driver():
    """PORT-COLD-SPLIT: the driver, imported and nothing else, so who times a connection can time its import apart."""
    import psycopg  # noqa: F401


def password_connection(where, user, password, purpose='other', **options):
    import psycopg
    return psycopg.connect(host=where['host'], port=where['port'], dbname=where['name'], user=user, password=password,
                           sslmode=where['sslmode'], application_name=named(where, purpose), **options)


class Database:
    """rows/run over one psycopg connection, the session the migrations' advisory lock lives in."""

    def __init__(self, connection):
        self.connection = connection

    def rows(self, sql, params=None):
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                found = cursor.fetchall() if cursor.description else []
            self.connection.commit()
            return found
        except BaseException:
            self.connection.rollback()
            raise

    def run(self, sql):
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql)
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise
