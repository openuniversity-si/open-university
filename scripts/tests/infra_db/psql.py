"""The psql side of the infrastructure's tests: the rows(sql, params) and run(sql) shape psycopg gives the service, over
the toolchain's psql on a throwaway database (TI1).

Parameters (%(name)s) become quoted literals (standard_conforming_strings, so doubling a quote is the whole escape),
NULL comes back as None, and a refusal keeps its SQLSTATE the way psycopg's errors do, so the code under test maps both
the same. migrated(url) makes a database migrated by the service's own runner.
"""
from pathlib import Path
import atexit
import os
import re
import select
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
import config  # noqa: E402
import test_db  # noqa: E402

NULL = '<null>'
SEPARATOR = '\x1f'
PLACEHOLDER = re.compile(r'%\((\w+)\)s')
SQLSTATE = re.compile(r'ERROR:\s+([0-9A-Z]+):')


class DatabaseError(RuntimeError):
    def __init__(self, message, sqlstate):
        super().__init__(message)
        self.sqlstate = sqlstate


def literal(value):
    return 'null' if value is None else "'" + str(value).replace("'", "''") + "'"


def one_statement(sql):
    """Whether `sql` is one statement for psql's lexer: no semicolon but a last one outside quotes, comments and
    dollar quotes (anything else goes through `psql -c`, one Query message, as before)."""
    body, i, n, quote = sql.rstrip().rstrip(';'), 0, 0, None
    n = len(body)
    while i < n:
        c = body[i]
        if quote is None:
            if c in "'\"":
                quote = c
            elif c == '-' and body.startswith('--', i):
                return False  # a comment: psql's own lexer, not worth reading here
            elif c == '/' and body.startswith('/*', i):
                return False
            elif c == '$':
                return False  # a dollar quote, perhaps
            elif c == ';':
                return False
            elif c == '\\':
                return False  # a backslash outside quotes is a psql command in a session
        elif c == quote:
            quote = None
        i += 1
    return quote is None and bool(body.strip())


STDBUF = shutil.which('stdbuf')
OPEN = set()  # the sessions up, each closed when the process ends


@atexit.register
def close_all():
    for held in list(OPEN):
        held.close()


class Session:
    """PSQL-SESSIONS: a psql process kept up on one database: a statement written, then its end said on both streams."""
    MARK = '__tower_psql_end__'

    def __init__(self, url):
        # psql's stdout is buffered on a pipe: line-buffered by stdbuf, so a statement's rows and its end come at once
        self.process = subprocess.Popen(
            [STDBUF, '-oL', str(test_db.psql_binary()), url, '-X', '-q', '-A', '-t', '-F', SEPARATOR, '-P', f'null={NULL}',
             '-v', 'ON_ERROR_STOP=0', '-v', 'VERBOSITY=verbose'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.buffers = {self.process.stdout.fileno(): b'', self.process.stderr.fileno(): b''}
        OPEN.add(self)

    def read(self, stream, deadline):
        fd, mark = stream.fileno(), f'\n{self.MARK}\n'.encode()
        while True:
            held = b'\n' + self.buffers[fd]
            at = held.find(mark)
            if at >= 0:
                self.buffers[fd] = held[at + len(mark):]
                return held[1:at + 1].decode()
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([fd], [], [], left)[0]:
                raise DatabaseError('psql session: no answer in time', None)
            chunk = os.read(fd, 65536)
            if not chunk:
                raise DatabaseError('psql session ended', None)
            self.buffers[fd] += chunk

    def statement(self, sql):
        deadline = time.monotonic() + config.get('test-db.psql_timeout_s')
        self.process.stdin.write(f"{sql.rstrip().rstrip(';')}\n;\ndiscard all;\n\\echo {self.MARK}\n\\warn {self.MARK}\n".encode())
        self.process.stdin.flush()
        out, err = self.read(self.process.stdout, deadline), self.read(self.process.stderr, deadline)
        if 'ERROR:' in err:
            found = SQLSTATE.search(err)
            raise DatabaseError(err.strip(), found.group(1) if found else None)
        return out

    def close(self):
        OPEN.discard(self)
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        for stream in (self.process.stdout, self.process.stderr):
            stream.close()


class Psql:
    def __init__(self, url, keep=False):
        """keep (PSQL-SESSIONS): its statements on psql sessions that stay up; a throwaway database migrated() makes
        keeps them. A Psql made on any other address (a test that counts the connections a pooler sees) opens one a
        statement, as before."""
        self.url, self.keep = url, keep
        self.idle, self.lock = [], threading.Lock()

    def call(self, args, script=None):
        done = subprocess.run([str(test_db.psql_binary()), self.url, '-X', '-q', '-v', 'ON_ERROR_STOP=1',
                               '-v', 'VERBOSITY=verbose', *args], input=script, capture_output=True, text=True,
                              timeout=config.get('test-db.psql_timeout_s'), check=False)
        if done.returncode:
            found = SQLSTATE.search(done.stderr)
            raise DatabaseError(done.stderr.strip(), found.group(1) if found else None)
        return done.stdout

    def rows(self, sql, params=None):
        sql = PLACEHOLDER.sub(lambda found: literal((params or {})[found.group(1)]), sql)
        if not self.keep or not STDBUF or os.environ.get('TEST_DB_PSQL_ONESHOT') or not one_statement(sql):
            out = self.call(['-A', '-t', '-F', SEPARATOR, '-P', f'null={NULL}', '-c', sql])
        else:
            out = self.session(sql)
        return [tuple(None if cell == NULL else cell for cell in line.split(SEPARATOR))
                for line in out.splitlines() if line]

    def session(self, sql):
        """PSQL-SESSIONS: one statement on a psql that stays up, taken from this database's idle ones (a thread of the
        test takes its own, as it had its own process before). Each statement then DISCARD ALL: the advisory locks,
        LISTENs and settings a statement left end with it, as when its process ended. A psql a call was 12 ms of the
        13 of a statement, most of the Postgres suites' seconds (the gate of #627: gate-infra 44 s on the runner)."""
        with self.lock:
            held = self.idle.pop() if self.idle else None
        if held is None:
            held = Session(self.url)
        try:
            out = held.statement(sql)
        except DatabaseError:
            with self.lock:
                self.idle.append(held)
            raise
        except BaseException:
            held.close()
            raise
        with self.lock:
            self.idle.append(held)
        return out

    def close(self):
        with self.lock:
            idle, self.idle = self.idle, []
        for held in idle:
            held.close()

    def run(self, sql):
        self.call(['-1', '-f', '-'], script=sql)


def database_url(url, name):
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, '/' + name, '', ''))


def migrations_key():
    """TEST-DB-TEMPLATE: a digest of what a migrated database is made of: every migration file and the code that applies them."""
    import hashlib
    digest = hashlib.sha256()
    for path in sorted((ROOT / 'infra/db/migrations').iterdir()) + [ROOT / 'infra/service/tower_infra/migrations.py']:
        if path.is_file():
            digest.update(path.name.encode() + b'\0' + path.read_bytes() + b'\0')
    return digest.hexdigest()


def migrated(url):
    """A throwaway database with every migration of infra/db applied: (its name, a Psql on it). TEST-DB-TEMPLATE: copied
    from a template migrated once for these migrations (CREATE DATABASE ... TEMPLATE), not migrated again for every test:
    each test paid every migration, statement by statement through psql (0.5 s a database here, several times that on the
    runner's slots, where the suites that use it were most of the gate's sum)."""
    template = test_db.template_name(migrations_key())
    if not test_db.template_exists(url, template):
        built = fresh(url)
        test_db.publish_template(url, built, template)
    name = test_db.create(url, template=template)
    return name, Psql(database_url(url, name), keep=True)


def fresh(url):
    """A throwaway database migrated here, statement by statement (what a template is made from)."""
    from tower_infra import migrations
    name = test_db.create(url)
    db = Psql(database_url(url, name))
    try:
        migrations.migrate(db, ROOT / 'infra/db/migrations', 'test')
    except BaseException:
        test_db.destroy(url, name)
        raise
    return name
