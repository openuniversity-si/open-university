"""TASK-POOLER (docs/operations/aws.md 22.9): the task keeps its connections to the database; its processes come and go.

What is left of a swap whose successor was lost is the database's login: with the reserve loaded and waiting, the new
code took 2.6 to 4.6 s (runner) and 4.7 to 10.8 s (service) to work at the drills of 12/11, and from the word to its
first read, the login apart, under 0.01 s. A login to the db.t4g.micro (a TLS handshake, the IAM token's check, a
backend forked on a host that pages) cost 0.7 to 4.2 s in a swap's second, and the new code needs one before its first
statement (the service, eight). A second successor would hold them open, and is refused: more connections of a
database that has few.

So the connections are the task's, not a process's. This is a small process beside the role's (the supervisor starts
it: `python -m tower_infra pooler <command>`), which listens on a socket of the task's own (a directory only this
user reads; TOWER_DB_POOL in every child's environment) and speaks PostgreSQL's protocol on both sides:

  - a process of the task connects to it as it would to the database (libpq, host = the directory): no TLS, no token,
    milliseconds. The pool gives it a connection to the database for as long as it stays (a SESSION: a LISTEN, a
    prepared statement, an advisory lock, a transaction are the client's, as on a connection of its own), and relays
    every byte both ways without reading the statements;
  - when the client leaves, or dies, the connection stays: what the client left is undone (a COPY failed, the
    protocol synced, ROLLBACK, DISCARD ALL: no transaction, no lock, no LISTEN, no setting, no plan of its own is
    left), a statement still running is cancelled, and the connection waits for the next client. A successor that
    dies as the swap promotes it leaves its connections here, logged in, their backends' catalogs loaded; the process
    that takes its place (the reserve, told to go) has them at its first connect, with no login at all;
  - a connection nobody took for TOWER_POOL_IDLE_S (IDLE_DEFAULT_S, 30 s) is closed: the database holds what the task's processes
    use and the tail of a process that just left, never more than a process of its own would have opened.

The pool logs in as the role's own user by its IAM token, signed here with the standard library from the task
role's credentials (the container's credentials endpoint), over TLS as the direct login (encrypted, sslmode=require).
A client is told how its connection came (a ParameterStatus `tower_pool`: reused, or login with the milliseconds of
its parts: tcp, tls, auth, start), which is how the engine says in its log what a login to this database costs.

The fail-safe is the login as it was: a process whose pool does not answer (not there yet, ended, refused) logs in
directly (tower_infra.database), and a pool that ends is started again by the supervisor. Standard library only.
"""
import json
import logging
import os
from pathlib import Path
import re
import secrets
import select
import signal
import socket
import ssl
import struct
import sys
import threading
import time
import urllib.request

from . import database

LOG = logging.getLogger('tower_infra.pooler')
V3, SSL_REQUEST, GSS_REQUEST, CANCEL_REQUEST = 196608, 80877103, 80877104, 80877102
IDLE_S, RESET_S = 'TOWER_POOL_IDLE_S', 'TOWER_POOL_RESET_S'  # an idle connection's life (IDLE_DEFAULT_S); a reset's longest (5)
# DB-SWAP-CUT (revisão da arquitetura, achado 37: the db.t4g.micro's host 467 to 559 MB in swap on 13/11, 44 backends on
# 1 GiB, 24 of them the two tasks' pools): an idle connection is kept 30 s, not 120. A swap takes the connections the
# process before it left within seconds (the successor's first connect), so the tail past that is backends the host
# pages out for nobody
IDLE_DEFAULT_S = 30.0
CONNECT_S, STARTUP_S = 10.0, 10.0  # a login's and a client's startup's longest
# POOL-KEEPS: a client that finds no idle connection while one is being reset waits for it as long as a reset may last
# (reset_s), not 1 s: at the drill of 12/11 22:21 UTC the service's new process logged in twice (~1 s each) while the
# lost successor's connections were still being reset
MOST = 40  # the connections one pool ever holds: past it a client is refused (and logs in directly, as before)
SAID = 'tower_pool'  # the ParameterStatus a client is told: how its connection came
STATE = 'pool.json'  # what the pool says of itself, beside its socket
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_.]*$')
CREDENTIALS = 'http://169.254.170.2'  # the task role's credentials, where ECS serves them to the task's containers


class PoolError(Exception):
    """What the pool cannot do for a client: said to it in the protocol's words, and the client logs in directly."""


class Gone(Exception):
    """The peer closed."""


def message(kind, body=b''):
    return kind + struct.pack('!I', len(body) + 4) + body


def text(value):
    return str(value).encode() + b'\0'


def failure(words, code='08006', severity='FATAL'):
    """An ErrorResponse a client reads as the server's own."""
    return message(b'E', b'S' + text(severity) + b'V' + text(severity) + b'C' + text(code) + b'M' + text(words) + b'\0')


def words(body):
    """The message of an ErrorResponse's body."""
    fields = dict((part[:1], part[1:].decode('utf-8', 'replace')) for part in body.split(b'\0') if part)
    return fields.get(b'M', 'the server refused')


def exactly(sock, count):
    parts, left = [], count
    while left:
        data = sock.recv(left)
        if not data:
            raise Gone()
        parts.append(data)
        left -= len(data)
    return b''.join(parts)


def one(sock):
    """One message of a blocking socket: (kind, body)."""
    head = exactly(sock, 5)
    return head[:1], exactly(sock, int.from_bytes(head[1:], 'big') - 4)


class Frames:
    """A stream cut into whole messages (a byte of kind, four of length, the body): feed() answers the ones that are
    complete and keeps the rest."""

    def __init__(self):
        self.kept = bytearray()

    def feed(self, data):
        self.kept += data
        whole = []
        while len(self.kept) >= 5:
            end = 1 + int.from_bytes(self.kept[1:5], 'big')
            if end < 5:
                raise PoolError('a message shorter than its own length')
            if len(self.kept) < end:
                break
            whole.append(bytes(self.kept[:end]))
            del self.kept[:end]
        return whole


def quoted(value):
    if '\0' in value:
        raise PoolError('a setting with a NUL in it')
    return "'" + value.replace("'", "''") + "'"


def options(said):
    """libpq's `options` (the startup packet's command line for the backend): [(setting, value)] of its -c name=value
    and --name=value words; a backslash keeps the next character."""
    parts, word, kept = [], '', False
    for char in said or '':
        if kept:
            word, kept = word + char, False
        elif char == '\\':
            kept = True
        elif char.isspace():
            if word:
                parts.append(word)
            word = ''
        else:
            word += char
    if word:
        parts.append(word)
    found, index = [], 0
    while index < len(parts):
        part = parts[index]
        if part == '-c' and index + 1 < len(parts):
            index += 1
            part = parts[index]
        elif part.startswith('-c') and len(part) > 2:
            part = part[2:]
        elif part.startswith('--'):
            name, _, value = part[2:].partition('=')
            part = f"{name.replace('-', '_')}={value}"
        else:
            raise PoolError(f'an option of the backend this pool does not pass on: {part}')
        name, mark, value = part.partition('=')
        if not mark:
            raise PoolError(f'an option with no value: {part}')
        found.append((name, value))
        index += 1
    return found


def settings(startup):
    """The SET of what a client asked in its startup packet (its application_name, its encoding, its options): one
    simple query, or None when it asked nothing."""
    asked = [(name, value) for name, value in startup.items() if name not in ('user', 'database', 'options', 'replication')
             and not name.startswith('_pq_.')] + options(startup.get('options'))
    for name, _ in asked:
        if not NAME.match(name):
            raise PoolError(f'a setting this pool does not pass on: {name}')
    return '; '.join(f'SET {name} = {quoted(value)}' for name, value in asked) or None


def credentials(environ, fetch=None, kept=None, now=time.time):
    """The task role's credentials as the names the token's signer reads (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
    AWS_SESSION_TOKEN): the environment's own when it carries them, else what the container's credentials endpoint
    answers, kept until five minutes before they expire. {} when neither is there: boto3 then signs (database.signer)."""
    if environ.get('AWS_ACCESS_KEY_ID') and environ.get('AWS_SECRET_ACCESS_KEY'):
        return dict(environ)
    where = (environ.get('AWS_CONTAINER_CREDENTIALS_FULL_URI') or '').strip() or (
        CREDENTIALS + environ['AWS_CONTAINER_CREDENTIALS_RELATIVE_URI'] if environ.get('AWS_CONTAINER_CREDENTIALS_RELATIVE_URI') else '')
    if not where:
        return {}
    kept = {} if kept is None else kept
    if kept.get('until', 0) > now():
        return kept['found']
    if fetch is None:
        def fetch(url):
            with urllib.request.urlopen(url, timeout=5) as said:  # noqa: S310 - the task's own link-local endpoint
                return said.read()
    said = json.loads(fetch(where))
    found = {'AWS_ACCESS_KEY_ID': said['AccessKeyId'], 'AWS_SECRET_ACCESS_KEY': said['SecretAccessKey'],
             **({'AWS_SESSION_TOKEN': said['Token']} if said.get('Token') else {})}
    try:
        from datetime import datetime
        until = datetime.fromisoformat(str(said.get('Expiration')).replace('Z', '+00:00')).timestamp() - 300
    except (TypeError, ValueError):
        until = now() + 300
    kept.update(found=found, until=until)
    return found


class Upstream:
    """A connection to the database, logged in: its socket, what the server said of the session at its login (the
    ParameterStatus values, the backend's pid and its cancel key) and where its login's seconds went."""

    def __init__(self, sock, params, pid, key, phases):
        self.sock, self.params, self.pid, self.key, self.phases = sock, params, pid, key, phases
        self.idle_at, self.uses = None, 0

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def reach(where, clock=time.monotonic, phases=None):
    """A socket to the database, over TLS unless sslmode is disable (a local database): encrypted and not verified,
    which is what the direct login asks (sslmode=require)."""
    phases = {} if phases is None else phases
    mark = clock()
    sock = socket.create_connection((where['host'], where['port']), timeout=CONNECT_S)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    phases['tcp'] = clock() - mark
    if where.get('sslmode', 'require') != 'disable':
        mark = clock()
        sock.sendall(struct.pack('!II', 8, SSL_REQUEST))
        if exactly(sock, 1) != b'S':
            sock.close()
            raise PoolError('the database refused TLS')
        context = ssl.create_default_context()
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
        sock = context.wrap_socket(sock, server_hostname=where['host'])
        phases['tls'] = clock() - mark
    return sock


def login(where, user, password, name, clock=time.monotonic):
    """A new connection to the database as `user`: the startup, the password the server asks in clear (an IAM user's
    token, inside TLS; a local database trusts), and what the server says until it is ready. Answers the Upstream;
    the server's refusal raises with its words."""
    phases = {}
    sock = reach(where, clock, phases)
    try:
        mark = clock()
        body = struct.pack('!I', V3) + b''.join(text(key) + text(value) for key, value in (
            ('user', user), ('database', where['name']), ('application_name', name), ('client_encoding', 'UTF8'))) + b'\0'
        sock.sendall(struct.pack('!I', len(body) + 4) + body)
        params, pid, key = {}, b'', b''
        while True:
            kind, body = one(sock)
            if kind == b'R':
                code = int.from_bytes(body[:4], 'big')
                if code == 0:
                    phases['auth'] = clock() - mark
                    mark = clock()
                elif code == 3:
                    sock.sendall(message(b'p', text(password())))
                else:
                    raise PoolError(f'the database asks an authentication this pool does not do ({code})')
            elif kind == b'S':
                found = body.split(b'\0')
                params[found[0].decode()] = found[1].decode('utf-8', 'replace')
            elif kind == b'K':
                pid, key = body[:4], body[4:]
            elif kind == b'E':
                raise PoolError(words(body))
            elif kind == b'Z':
                phases['start'] = clock() - mark
                break
        sock.settimeout(None)
        return Upstream(sock, params, pid, key, {name: round(seconds * 1000, 1) for name, seconds in phases.items()})
    except BaseException:
        sock.close()
        raise


def ask(up, sql, timeout=CONNECT_S):
    """One simple query on a connection nobody else uses, to its end: the ParameterStatus values it changed, or the
    server's refusal raised (the connection is ready again either way)."""
    up.sock.settimeout(timeout)
    try:
        up.sock.sendall(message(b'Q', text(sql)))
        changed, refused = {}, None
        while True:
            kind, body = one(up.sock)
            if kind == b'S':
                found = body.split(b'\0')
                changed[found[0].decode()] = found[1].decode('utf-8', 'replace')
            elif kind == b'E':
                refused = words(body)
            elif kind == b'Z':
                break
        if refused is not None:
            raise PoolError(refused)
        return changed
    finally:
        up.sock.settimeout(None)


class Pool:
    """The task's connections to its database, as one user and one database: the idle ones, newest first (the one a
    client left last is the warmest), and the count of all."""

    def __init__(self, where, user, password, name, idle_s=120.0, reset_s=5.0, clock=time.monotonic, path=None):
        self.where, self.user, self.password, self.name = where, user, password, name
        self.idle_s, self.reset_s, self.clock, self.path = idle_s, reset_s, clock, path
        self.lock, self.writing = threading.Condition(), threading.Lock()
        self.idle, self.count, self.resetting = [], 0, 0
        self.said = {'logins': 0, 'reused': 0, 'refused': 0, 'closed': 0, 'cancelled': 0, 'login_ms': {}, 'slowest_ms': {},
                     # POOL-KEEPS: the waits for a reset, the logins made while one was in flight, the connections a reset
                     # could not clean (closed), and the longest reset
                     'waited': 0, 'waited_ms_max': 0.0, 'login_while_resetting': 0, 'dirty': 0, 'reset_ms_max': 0.0,
                     'reset_again': 0, 'cancel_skipped': 0}

    def take(self):
        """A connection for a client: (the Upstream, whether it was here already). One being reset is waited for, a
        moment (the client that left it and the one that takes it are a swap's two processes), before a new login."""
        with self.lock:
            began = self.clock()
            limit = began + self.reset_s
            waited = not self.idle and self.resetting > 0
            while not self.idle and self.resetting and self.clock() < limit:
                self.lock.wait(max(0.0, limit - self.clock()))
            if waited:
                self.said['waited'] += 1
                self.said['waited_ms_max'] = max(self.said['waited_ms_max'], round((self.clock() - began) * 1000, 1))
            if self.idle:
                up = self.idle.pop()
                self.said['reused'] += 1
                return up, True
            if self.resetting:
                self.said['login_while_resetting'] += 1
            if self.count >= MOST:
                self.said['refused'] += 1
                raise PoolError(f'the pool holds its most connections ({MOST})')
            self.count += 1
        try:
            up = login(self.where, self.user, self.password, self.name, self.clock)
        except BaseException:
            with self.lock:
                self.count -= 1
                self.said['refused'] += 1
            raise
        with self.lock:
            self.said['logins'] += 1
            self.said['login_ms'] = up.phases
            total = round(sum(up.phases.values()), 1)
            if total > sum(self.said['slowest_ms'].values() or [0]):
                self.said['slowest_ms'] = up.phases
        return up, False

    def leaving(self):
        """A client left and its connection is being reset: one that asks for a connection now waits a moment for it."""
        with self.lock:
            self.resetting += 1

    def give(self, up, clean, left=False, reset_ms=None):
        """A client's connection comes back: reset, it waits for the next client (clean), or it is closed. `left`: the
        client had left and the reset was counted (leaving()); reset_ms: how long that reset took."""
        with self.lock:
            if left:
                self.resetting -= 1
                if not clean:
                    self.said['dirty'] += 1
                if reset_ms is not None:
                    self.said['reset_ms_max'] = max(self.said['reset_ms_max'], reset_ms)
            if clean:
                up.idle_at = self.clock()
                self.idle.append(up)
            else:
                self.count -= 1
                self.said['closed'] += 1
            self.lock.notify_all()
        if not clean:
            up.close()
        self.say()

    def drop(self, up):
        """A connection that was taken and never served a client (it did not answer): closed."""
        with self.lock:
            self.count -= 1
            self.said['closed'] += 1
        up.close()

    def sweep(self):
        """The idle connections nobody took for idle_s are closed; answers how many."""
        with self.lock:
            limit = self.clock() - self.idle_s
            old = [up for up in self.idle if up.idle_at <= limit]
            self.idle = [up for up in self.idle if up.idle_at > limit]
            self.count -= len(old)
            self.said['closed'] += len(old)
        for up in old:
            try:
                up.sock.sendall(message(b'X'))
            except OSError:
                pass
            up.close()
        if old:
            self.say()
        return len(old)

    def cancel(self, pid, key):
        """A CancelRequest to the database for the backend (pid, key), on a connection of its own, as the protocol
        asks; never raises."""
        try:
            sock = reach(self.where)
            try:
                sock.sendall(struct.pack('!II', 8 + len(pid) + len(key), CANCEL_REQUEST) + pid + key)
            finally:
                sock.close()
            with self.lock:
                self.said['cancelled'] += 1
        except Exception:  # noqa: BLE001 - the statement then ends by itself, or the reset's limit closes the connection
            LOG.exception('pooler: a cancel did not reach the database')

    def say(self):
        """What the pool holds and did, written whole beside its socket (pool.json); never raises."""
        if self.path is None:
            return
        try:
            with self.writing:  # one writer at a time: every session's thread says
                with self.lock:
                    said = {**self.said, 'connections': self.count, 'idle': len(self.idle), 'at': round(time.time(), 3)}
                draft = Path(self.path) / f'.{STATE}'
                draft.write_text(json.dumps(said))
                os.replace(draft, Path(self.path) / STATE)
        except OSError:
            pass

    def close(self):
        with self.lock:
            idle, self.idle = self.idle, []
            self.count -= len(idle)
        for up in idle:
            try:
                up.sock.sendall(message(b'X'))
            except OSError:
                pass
            up.close()


def startup(client, pool):
    """A client's first words: no TLS and no GSS here (the socket is the task's own), a cancel passed on to the
    database, and its startup packet's parameters; None for a client that only cancelled."""
    while True:
        size = int.from_bytes(exactly(client, 4), 'big')
        if not 8 <= size <= 10000:
            raise PoolError('a startup packet of no size the protocol has')
        body = exactly(client, size - 4)
        code = int.from_bytes(body[:4], 'big')
        if code in (SSL_REQUEST, GSS_REQUEST):
            client.sendall(b'N')
            continue
        if code == CANCEL_REQUEST:
            pool.cancel(body[4:8], body[8:])
            return None
        if code >> 16 != 3:
            raise PoolError(f'a protocol this pool does not speak ({code >> 16}.{code & 0xffff})')
        parts = body[4:].split(b'\0')
        asked = {parts[index].decode(): parts[index + 1].decode('utf-8', 'replace')
                 for index in range(0, len(parts) - 1, 2) if parts[index]}
        return code, asked


def nonblocking(sock):
    """What a socket has for us now: bytes, None (nothing yet), or b'' (it closed)."""
    try:
        return sock.recv(65536)
    except (BlockingIOError, InterruptedError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
        return None
    except (OSError, ssl.SSLError):
        return b''


def push(sock, kept):
    """As much of `kept` as the socket takes now. Answers True while the socket asks to be READ before it writes
    again (TLS); raises Gone when it closed."""
    try:
        if kept:
            del kept[:sock.send(kept)]
    except ssl.SSLWantReadError:
        return True
    except (BlockingIOError, InterruptedError, ssl.SSLWantWriteError):
        pass
    except (OSError, ssl.SSLError):
        raise Gone() from None
    return False


class Session:
    """One client for as long as it stays: its startup answered, a connection of the pool its own, every message
    relayed both ways by one thread, and at its end the connection reset and given back."""

    def __init__(self, client, pool, clock=time.monotonic):
        self.client, self.pool, self.clock = client, pool, clock

    def serve(self):
        client, up = self.client, None
        try:
            client.settimeout(STARTUP_S)
            asked = startup(client, self.pool)
            if asked is None:
                return
            code, asked = asked
            if asked.get('user') != self.pool.user or asked.get('database') != self.pool.where['name']:
                raise PoolError(f"this pool is {self.pool.user}'s on {self.pool.where['name']}")
            wanted = settings(asked)
            for attempt in (0, 1):  # a connection that waited may have been closed by the database: the next, once
                up, reused = self.pool.take()
                try:
                    session = {**up.params, **(ask(up, wanted) if wanted else {})}
                    break
                except PoolError:
                    self.reset(up)  # the server refused a setting the client asked: said to it, as the server would
                    up = None
                    raise
                except (Gone, OSError, ssl.SSLError):
                    self.pool.drop(up)
                    up = None
                    if attempt or not reused:
                        raise PoolError('the database closed the connection') from None
            how = 'reused' if reused else 'login ' + ' '.join(f'{name}={value}' for name, value in up.phases.items())
            hello = [message(b'R', struct.pack('!I', 0))]
            if code & 0xffff:  # a minor version this pool does not speak: the protocol's own answer (3.0, nothing refused)
                hello.insert(0, message(b'v', struct.pack('!II', 0, 0)))
            hello += [message(b'S', text(name) + text(value)) for name, value in {**session, SAID: how}.items()]
            hello += [message(b'K', up.pid + up.key), message(b'Z', b'I')]
            client.sendall(b''.join(hello))
            up.uses += 1
            clean, left = False, [False, None]
            try:
                clean = self.relay(up, left)
            finally:
                self.pool.give(up, clean, left[0], None if left[1] is None else round((self.clock() - left[1]) * 1000, 1))
                up = None
        except PoolError as refused:
            LOG.warning('pooler: a client is refused: %s', refused)
            try:
                client.sendall(failure(str(refused)))
            except OSError:
                pass
        except (Gone, OSError, ssl.SSLError):
            pass
        except Exception:  # noqa: BLE001 - one client's failure is never the pool's
            LOG.exception('pooler: a session failed')
        finally:
            try:
                client.close()
            except OSError:
                pass

    def reset(self, up):
        """A connection taken and not relayed yet (the client was refused): reset alone, and given back."""
        clean = False
        try:
            ask(up, 'ROLLBACK', self.pool.reset_s)
            ask(up, 'DISCARD ALL', self.pool.reset_s)
            clean = True
        except Exception:  # noqa: BLE001
            clean = False
        self.pool.give(up, clean)

    def relay(self, up, left=None):
        """Every message both ways until the client leaves (its Terminate is not passed on: the connection is the
        pool's), then the reset: what a COPY, an unsynced protocol, a transaction and a session left is undone, a
        statement in flight is cancelled, and a row only this session knows says the reset was read to its end. Answers
        whether the connection is clean: DISCARD ALL was done (it is refused inside a transaction, and a cancel that
        came late may end it) and the row came; False when the database closed it or the reset passed its limit.
        `left` (a list of one) is told when the client left: the pool counts the reset from then."""
        client, server = self.client, up.sock
        client.setblocking(False)
        server.setblocking(False)
        to_server, to_client = bytearray(), bytearray()
        from_client, from_server = Frames(), Frames()
        mark = secrets.token_hex(16).encode()
        attached, pending, seen, discarded, limit, thirsty = True, False, False, False, None, False
        running, again = {'still': False}, False  # POOL-KEEPS: the statement the client left, until its end comes

        def reset():
            return (message(b'Q', text('ROLLBACK')) + message(b'Q', text('DISCARD ALL'))
                    + message(b'Q', text("SELECT '%s'" % mark.decode())))

        def cancel():
            # POOL-KEEPS: the cancel goes on a connection of its own (a TLS handshake with RDS: 0.3 to 0.9 s); one sent
            # for a statement that ended meanwhile lands on the reset itself, which then cannot clean the connection
            if running['still']:
                self.pool.cancel(up.pid, up.key)
            else:
                with self.pool.lock:
                    self.pool.said['cancel_skipped'] += 1

        def leave():
            nonlocal attached, limit
            attached, limit = False, self.clock() + self.pool.reset_s
            self.pool.leaving()
            if left is not None:
                left[0] = True
                if len(left) > 1:
                    left[1] = self.clock()
            to_client.clear()
            if pending:  # a statement the client left running: cancelled, so the reset is not behind it
                running['still'] = True
                threading.Thread(target=cancel, name='pool-cancel', daemon=True).start()
            to_server.extend(message(b'f', text('the client left')) + message(b'S') + reset())
        try:
            while True:
                reads = [server] + ([client] if attached else [])
                writes = ([server] if to_server and not thirsty else []) + ([client] if attached and to_client else [])
                wait = None if limit is None else limit - self.clock()
                if wait is not None and wait <= 0:
                    return False
                ready = isinstance(server, ssl.SSLSocket) and server.pending() > 0
                readable, writable, _ = select.select(reads, writes, [], 0 if ready else wait)
                if client in readable:
                    data = nonblocking(client)
                    if data == b'':
                        leave()
                    elif data:
                        for each in from_client.feed(data):
                            if each[:1] == b'X':
                                leave()
                                break
                            to_server.extend(each)
                            pending = True
                if server in readable or ready:
                    thirsty = False
                    while True:
                        data = nonblocking(server)
                        if data is None:
                            break
                        if data == b'':
                            return False
                        for each in from_server.feed(data):
                            kind = each[:1]
                            if attached:
                                to_client.extend(each)
                                if kind == b'Z':
                                    pending = False
                            elif kind == b'C' and each[5:] == b'DISCARD ALL\0':
                                discarded = True
                            elif kind == b'D' and mark in each:
                                seen = True
                            elif kind == b'Z' and seen:
                                if discarded:
                                    return True
                                if again:  # a second reset that could not clean it either: closed
                                    return False
                                # POOL-KEEPS: a cancel that came late landed on the reset: once more, not a closed
                                # connection and a login for the next client
                                again, seen = True, False
                                to_server.extend(reset())
                                with self.pool.lock:
                                    self.pool.said['reset_again'] += 1
                            elif kind == b'Z':
                                running['still'] = False  # the end of what the client left (or of the Sync)
                thirsty = push(server, to_server) or thirsty
                if attached:
                    try:
                        push(client, to_client)
                    except Gone:
                        leave()
        except (Gone, OSError, ssl.SSLError, PoolError):
            return False
        finally:
            try:
                server.setblocking(True)
            except OSError:
                pass


def allowed(client):
    """Only a process of this user: the socket's directory is its own, and the kernel says who connected."""
    try:
        _, uid, _ = struct.unpack('3i', client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
        return uid == os.getuid()
    except (OSError, AttributeError, struct.error):
        return True  # where the kernel does not say, the directory's mode is the guard


def listen(directory, port):
    """The pool's socket, where libpq looks for a server in a directory: <directory>/.s.PGSQL.<port>, in a directory
    only this user enters."""
    where = Path(directory)
    where.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(where, 0o700)
    path = where / f'.s.PGSQL.{port}'
    path.unlink(missing_ok=True)
    found = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    found.bind(str(path))
    os.chmod(path, 0o600)
    found.listen(64)
    return found


def serve(pool, listener, stop, sweep_s=None):
    """Every client in a thread of its own until stop is set; the idle connections are swept as time passes."""
    every = sweep_s or max(1.0, min(30.0, pool.idle_s / 4))
    listener.settimeout(every)
    swept = pool.clock()
    while not stop.is_set():
        if pool.clock() - swept >= every:
            swept = pool.clock()
            pool.sweep()
        try:
            client, _ = listener.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        if not allowed(client):
            client.close()
            continue
        threading.Thread(target=Session(client, pool).serve, name='pool-session', daemon=True).start()
    pool.close()


def main(args=(), environ=None):
    """`python -m tower_infra pooler <command>`: the pool of the role of `command` (serve: service; run-container:
    runner), on the directory TOWER_DB_POOL names, until SIGTERM."""
    environ = os.environ if environ is None else environ
    directory = (environ.get(database.POOL) or '').strip()
    if not directory:
        LOG.error('pooler: no %s: nothing to listen on', database.POOL)
        return 2
    role = 'runner' if (list(args) or ['serve'])[0] == 'run-container' else 'service'
    where = database.settings(environ, role=role)
    user = environ.get('TOWER_DB_USER') or ('tower_runner' if role == 'runner' else 'tower_service')
    kept = {}

    def password():
        if environ.get('TOWER_DB_PASSWORD'):  # a local run
            return environ['TOWER_DB_PASSWORD']
        return database.auth_token(where, user, credentials(environ, kept=kept))
    pool = Pool(where, user, password, database.named(where, 'pooled'), idle_s=float(environ.get(IDLE_S, IDLE_DEFAULT_S)),
                reset_s=float(environ.get(RESET_S, 5)), path=directory)
    listener = listen(directory, where['port'])
    stop = threading.Event()

    def end(*_):
        stop.set()
        try:
            listener.close()
        except OSError:
            pass
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, end)
    pool.say()
    LOG.info('pooler: the %s task keeps its connections to %s as %s; listening in %s', role, where['host'], user, directory)
    serve(pool, listener, stop)
    LOG.info('pooler: stopped')
    return 0


if __name__ == '__main__':
    logging.basicConfig(level=os.environ.get('TOWER_LOG_LEVEL', 'INFO'), format='%(asctime)s %(name)s %(message)s')
    sys.exit(main(sys.argv[1:]))
