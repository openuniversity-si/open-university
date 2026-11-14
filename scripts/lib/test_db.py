"""Shared throwaway test databases (TI1, D-064 (b), D-069 items 3, 5 and 9; incident 'X1 scope-mix 2026-10-26 22:07').

Every test that needs a database of its own creates and destroys it here, never by hand:
  new_name()                 test-db.name_prefix + hex of test-db.name_token_bytes random bytes; never collides with
                             gate-isolation.sh's tower_test_<10 hex> or int-teardown.ts's tower_test_g<hex>;
  create(url, name=None, owner=None)
                             creates the database (a fresh name when none is given), records its owner (this process,
                             or the pid given) as the database's comment, and returns its name;
  destroy(url, name)         terminates every other backend on it, then DROP DATABASE IF EXISTS ... WITH (FORCE), then
                             checks it is gone. Create and destroy hold test-db.ddl_lock_path, so parallel callers take turns. Idempotent: an absent database is not an error. Any failure raises.
url is any local PostgreSQL URL (TEST_DATABASE_URL by default); the helper talks to its test-db.maintenance_database.
Only names that validate() accepts are ever created or dropped by create/destroy. Shell suites call
`python3 scripts/lib/test_db.py create|destroy <name>`.
Residue (GX-29, GA2 Q9): a fixture that dies before destroy() or boots the toolchain (postgres.py ensure re-creates the
bootstrap database cloud.postgres_database) leaves a tower_test_* database behind.
  residue(url=None, keep=())  the leftover fixture databases: the bootstrap database and generated throwaway names, never this
                              checkout's own database (TEST_DATABASE_URL), never a name in `keep`, never one with a live backend,
                              never one whose recorded owner is alive (a test's database sits idle between create and use,
                              and another gate's sweep must not drop it then; BASEFIX-shellcheck);
  sweep(url=None, keep=())    drops them and returns their names. `test_db.py residue|sweep` print one name per line.
"""
import contextlib
import fcntl
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit

import config
import toolchain_manifest

_LOCAL_HOSTS = ('127.0.0.1', 'localhost')


class TestDatabaseError(RuntimeError):
    pass


def _pattern():
    prefix = config.get('test-db.name_prefix')
    return re.compile('^' + re.escape(prefix) + '[0-9a-f]{' + str(2 * config.get('test-db.name_token_bytes')) + '}$')


def new_name():
    return config.get('test-db.name_prefix') + secrets.token_hex(config.get('test-db.name_token_bytes'))


def validate(name):
    if not isinstance(name, str) or not _pattern().fullmatch(name):
        raise TestDatabaseError(f'refusing database name {name!r}: not a throwaway test database name '
                                f'({config.get("test-db.name_prefix")}<hex>)')
    return name


def maintenance_url(url=None):
    url = url or os.environ.get('TEST_DATABASE_URL') or ''
    parts = urlsplit(url)
    if parts.scheme not in ('postgres', 'postgresql') or parts.hostname not in _LOCAL_HOSTS:
        raise TestDatabaseError('test database URL is not a local PostgreSQL database')
    return urlunsplit((parts.scheme, parts.netloc, '/' + config.get('test-db.maintenance_database'), '', ''))


def psql_binary():
    psql = toolchain_manifest.toolchain_dir() / 'bin' / 'psql'
    if not psql.is_file():
        # A gate checkout carries no .toolchain; env.sh puts the pinned toolchain on PATH.
        found = shutil.which('psql')
        if not found:
            raise TestDatabaseError(f'missing toolchain psql at {psql} and none on PATH')
        psql = found
    return psql


def _psql(url, sql):
    psql = psql_binary()
    limit = config.get('test-db.psql_timeout_s')
    try:
        done = subprocess.run([str(psql), maintenance_url(url), '-v', 'ON_ERROR_STOP=1', '-qtAc', sql],
                              capture_output=True, text=True, timeout=limit, check=False)
    except subprocess.TimeoutExpired:
        raise TestDatabaseError(f'psql did not finish in {limit} s: {sql}\n{_waiting(url, psql, limit)}') from None
    if done.returncode != 0:
        raise TestDatabaseError(f'psql failed ({done.returncode}): {sql}: {done.stderr.strip()}')
    return done.stdout.strip()


def _waiting(url, psql, limit):
    """What the server was waiting on when a call timed out, so a recurrence names its cause (best effort)."""
    sql = ("select coalesce(datname, backend_type), state, wait_event_type, wait_event, left(query, 60) "
           "from pg_stat_activity where wait_event is not null and backend_type <> 'walwriter'")
    try:
        done = subprocess.run([str(psql), maintenance_url(url), '-qtAc', sql],
                              capture_output=True, text=True, timeout=limit, check=False)
    except (subprocess.TimeoutExpired, TestDatabaseError):
        return 'pg_stat_activity: unavailable'
    return 'pg_stat_activity (waiting backends):\n' + (done.stdout.strip() or done.stderr.strip() or 'none')


@contextlib.contextmanager
def _one_ddl_at_a_time():
    """CREATE/DROP DATABASE each force a checkpoint of the shared cluster; callers on this machine take turns."""
    wait = config.get('test-db.ddl_lock_wait_s')
    deadline = time.monotonic() + wait
    # CHECK-USER-SHARED: the lock is shared across users (the runner's root and its check user, CHECK-NOT-ROOT): a plain
    # open(..., 'a') of the other user's file in sticky /tmp is refused (fs.protected_regular); identity.open_lock opens
    # it without O_CREAT, read-only if it must (enough for flock), and leaves it 0666
    import session_identity as identity
    with identity.open_lock(config.get('test-db.ddl_lock_path')) as handle:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TestDatabaseError(f'test database DDL lock not free in {wait} s') from None
                time.sleep(config.get('test-db.ddl_lock_poll_s'))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def exists(url, name):
    return _psql(url, f"select 1 from pg_database where datname = '{validate(name)}'") == '1'


TEMPLATE = 'tower_test_tpl_'  # TEST-DB-TEMPLATE: a migrated database the throwaway ones are copied from
TEMPLATE_NAME = re.compile('^' + re.escape(TEMPLATE) + '[0-9a-f]{20}$')


def template_name(key):
    """The template's name for a key (a hex digest of what it was made from); never a throwaway name, so no sweep drops it."""
    name = TEMPLATE + str(key)[:20]
    if not TEMPLATE_NAME.fullmatch(name):
        raise TestDatabaseError(f'refusing template name {name!r}')
    return name


def template_exists(url, name):
    return _psql(url, f"select 1 from pg_database where datname = '{template_name(name[len(TEMPLATE):])}'") == '1'


def publish_template(url, built, name):
    """TEST-DB-TEMPLATE: a throwaway database that holds every migration becomes the template `name` by a rename, so no
    test ever copies a template half made; answers whether it did (another process may have published it first: then
    `built` is dropped). The templates of other keys are dropped then, unless a copy is being made of them."""
    built, name = validate(built), template_name(name[len(TEMPLATE):])
    with _one_ddl_at_a_time():
        if _psql(url, f"select 1 from pg_database where datname = '{name}'") == '1':
            _drop_held(url, built)
            return False
        _psql(url, f'alter database "{built}" rename to "{name}"')
        for old in _psql(url, f"select datname from pg_database where datname like '{TEMPLATE}%' "
                              f"and datname <> '{name}'").split():
            if TEMPLATE_NAME.fullmatch(old):
                try:
                    _psql(url, f'drop database if exists "{old}"')
                except TestDatabaseError:  # a copy of it is being made now: the next template's turn drops it
                    pass
    return True


def create(url=None, name=None, owner=None, template=None):
    name = validate(name or new_name())
    copied = f' template "{template_name(template[len(TEMPLATE):])}"' if template else ''
    with _one_ddl_at_a_time():
        _psql(url, f'create database "{name}"{copied}')
        _psql(url, f"comment on database \"{name}\" is '{int(owner or os.getpid())}'")
    return name


def _drop_held(url, name):
    """The drop itself; the caller holds the DDL lock."""
    _psql(url, 'select count(pg_terminate_backend(pid)) from pg_stat_activity '
               f"where datname = '{name}' and pid <> pg_backend_pid()")
    _psql(url, f'drop database if exists "{name}" with (force)')


def _gone(url, name):
    if _psql(url, f"select 1 from pg_database where datname = '{name}'") == '1':
        raise TestDatabaseError(f'database {name} still exists after drop')


def _drop(url, name):
    with _one_ddl_at_a_time():
        _drop_held(url, name)
    _gone(url, name)


def destroy(url, name):
    _drop(url, validate(name))


def _own_database(url):
    return urlsplit(url or os.environ.get('TEST_DATABASE_URL') or '').path.lstrip('/')


def _alive(owner):
    """Whether the pid a database's comment records is a live process (another user's process is alive too)."""
    if not owner.isdigit():
        return False
    try:
        os.kill(int(owner), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def residue(url=None, keep=()):
    fixture = _pattern()
    bootstrap = config.get('cloud.postgres_database')
    rows = _psql(url, "select datname, coalesce(shobj_description(oid, 'pg_database'), '') from pg_database "
                      "where datname like 'tower\\_test\\_%' order by 1").splitlines()
    owners = dict(row.split('|', 1) for row in rows)
    busy = set(_psql(url, 'select distinct datname from pg_stat_activity where datname is not null').split())
    skip = {_own_database(url), *keep}
    return [name for name, owner in owners.items()
            if (name == bootstrap or fixture.fullmatch(name)) and name not in skip and name not in busy
            and not _alive(owner)]


def sweep(url=None, keep=()):
    dropped = []
    for name in residue(url, keep):
        # Decided again under the lock create() holds from CREATE DATABASE to its owner comment: a database listed
        # in between has its owner by now.
        with _one_ddl_at_a_time():
            if name not in residue(url, keep):
                continue
            _drop_held(url, name)
        _gone(url, name)
        dropped.append(name)
    return dropped


def main(argv):
    if len(argv) == 2 and argv[0] == 'create':
        print(create(None, argv[1], owner=os.getppid()))  # the suite that ran this command owns the database
    elif len(argv) == 1 and argv[0] == 'create':
        print(create(owner=os.getppid()))
    elif len(argv) == 2 and argv[0] == 'destroy':
        destroy(None, argv[1])
    elif argv == ['residue']:
        print('\n'.join(residue()))
    elif argv == ['sweep']:
        print('\n'.join(sweep()))
    else:
        sys.exit('usage: test_db.py create [<name>] | destroy <name> | residue | sweep')


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except TestDatabaseError as error:
        sys.exit(f'test_db: {error}')
