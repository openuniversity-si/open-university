#!/usr/bin/env python3
"""Project-local PostgreSQL from the pinned toolchain. No Docker and no apt.

uid 0 cannot run initdb or the server. That session creates or reuses the
unprivileged account `ou-postgres` and drops to it for initdb and pg_ctl.
Any other uid keeps the previous direct exec.
"""
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import config
import session_identity as identity
import toolchain_manifest as manifest

HOST = config.get('cloud.postgres_host')
DATABASE = config.get('cloud.postgres_database')
ROLE = config.get('cloud.postgres_role')


class PostgresError(RuntimeError):
    pass


def _port():
    raw = os.environ.get('OU_POSTGRES_PORT', '').strip()
    if raw.isdigit() and 1 <= int(raw) <= 65535:
        return int(raw)
    return config.get('cloud.postgres_port')


def _down():
    return f'postgres is not accepting connections on {HOST}:{_port()}'


def _bin(name):
    path = manifest.toolchain_dir() / 'bin' / name
    if not path.is_file():
        raise PostgresError('missing toolchain: postgres')
    return path


def _run(args, log=None, *, as_service=False):
    argv = [str(arg) for arg in args]
    env = None
    # Only uid 0 drops. The same argument list is exec'd directly otherwise.
    if as_service and identity.running_as_root():
        try:
            argv, env = identity.command_as(identity.PG_USER, argv)
        except identity.IdentityError as error:
            raise PostgresError(str(error)) from None
    stdout = subprocess.DEVNULL if log is None else log
    return subprocess.run(
        argv, stdout=stdout, stderr=subprocess.STDOUT, text=True, check=False, env=env,
    )


def _psql(database, sql):
    env = {key: value for key, value in os.environ.items() if key != 'PGPASSWORD'}
    env['PGCLIENTENCODING'] = config.get('cloud.postgres_encoding')
    completed = subprocess.run(
        [str(_bin('psql')), '-X', '-q', '-h', HOST, '-p', str(_port()), '-U', ROLE, '-d', database,
         '-v', 'ON_ERROR_STOP=1', '-tAc', sql],
        env=env, capture_output=True, text=True, timeout=config.get('cloud.postgres_query_timeout_s'), check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _database_up():
    try:
        return _psql(DATABASE, 'select 1') == '1'
    except (OSError, subprocess.TimeoutExpired, PostgresError):
        return False


def _configure(data):
    port = _port()
    permissions = config.get('cloud.postgres_socket_permissions')
    if identity.running_as_root():
        socket_dir = manifest.toolchain_dir() / 'pgsocket'
        socket_dir.mkdir(parents=True, exist_ok=True)
        try:
            record = identity.ensure_service_user(manifest.toolchain_dir() / 'pghome')
        except identity.IdentityError as error:
            raise PostgresError(str(error)) from None
        identity.own(socket_dir, record, 0o755)
        socket = str(socket_dir).replace("'", '')
        body = (
            f"listen_addresses = '{HOST}'\nport = {port}\n"
            f"unix_socket_directories = '{socket}'\nunix_socket_permissions = '{permissions}'\n"
        )
    else:
        socket = str(data).replace("'", '')
        body = f"listen_addresses = '{HOST}'\nport = {port}\nunix_socket_directories = '{socket}'\n"
    extra = data / 'open-university.conf'
    extra.write_text(body)
    conf = data / 'postgresql.conf'
    marker = "include 'open-university.conf'"
    text = conf.read_text()
    if marker not in text:
        conf.write_text(text.rstrip() + '\n' + marker + '\n')


def _tail(log):
    try:
        lines = [line.strip() for line in log.read_text(errors='replace').splitlines() if line.strip()]
    except OSError:
        return ''
    return lines[-1][:config.get('cloud.postgres_log_tail_chars')] if lines else ''


def _start(data, log_path):
    # pg_ctl -l owns the server log. The wrapper's own status output stays off that file.
    status = _run([_bin('pg_ctl'), '-D', data, 'status'], as_service=True)
    action = 'restart' if status.returncode == 0 else 'start'
    started = _run([_bin('pg_ctl'), '-D', data, '-l', log_path, '-w', '-t', str(config.get('cloud.postgres_ready_wait_s')), action], as_service=True)
    if started.returncode != 0 or not _psql('postgres', 'select 1'):
        detail = _tail(log_path)
        raise PostgresError(_down() + (f': {detail}' if detail else ''))


def _ensure_database():
    if _psql('postgres', f"SELECT 1 FROM pg_database WHERE datname='{DATABASE}'") == '1':
        return
    created = _run([_bin('createdb'), '-h', HOST, '-p', str(_port()), '-U', ROLE, DATABASE])
    if created.returncode != 0 or not _database_up():
        raise PostgresError(f'missing database {DATABASE}')


def _service():
    if not identity.running_as_root():
        return None
    try:
        return identity.ensure_service_user(manifest.toolchain_dir() / 'pghome')
    except identity.IdentityError as error:
        raise PostgresError(str(error)) from None


def _boot_time(stat=Path('/proc/stat')):
    """This machine's boot, in seconds since the epoch (Linux /proc/stat btime), or None where it cannot be read."""
    try:
        for line in stat.read_text().splitlines():
            if line.startswith('btime '):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def _stale(data, boot=None):
    """CACHE-PGDATA: True when the cluster's postmaster.pid says its server started before this machine booted. That
    server cannot be running: the cluster is a crash's or a copy's, as tower/gate's actions/cache of .toolchain restored a
    running cluster on a fresh runner (run 43606632818, 14/11: pg_ctl start failed for 30 s and named the copy's
    07:54 log line). Its pid may name another live process here, and a copy of a live cluster may be torn. A pid file
    that cannot be read, or a machine whose boot cannot be read, is not stale (the previous start, unchanged)."""
    boot = _boot_time() if boot is None else boot
    if boot is None:
        return False
    try:
        started = int((data / 'postmaster.pid').read_text().splitlines()[2])
    except (OSError, IndexError, ValueError):
        return False
    return started < boot


def _discard(root, data, log_path):
    """CACHE-PGDATA: the stale cluster goes (GX-29: it holds throwaway test data; setup.sh recreates this checkout's
    database), with its log, whose last line would be named as this start's failure, and the root session's socket
    lock files, which name the dead server's pid."""
    shutil.rmtree(data)
    log_path.unlink(missing_ok=True)
    for lock in (root / 'pgsocket').glob('.s.PGSQL.*'):
        lock.unlink(missing_ok=True)


def _ensure():
    root = manifest.toolchain_dir()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / '.write-probe'
        probe.write_text('ok')
        probe.unlink()
    except OSError:
        raise PostgresError('missing writable path: .toolchain') from None
    if not (root / 'bin' / 'psql').is_file():
        raise PostgresError('missing toolchain: postgres')
    if _database_up():
        return
    if _psql('postgres', 'select 1') == '1':
        _ensure_database()
        return
    identity.share_toolchain(root)
    record = _service()
    data = root / 'pgdata'
    log_path = root / 'postgres.log'
    if _stale(data):
        _discard(root, data, log_path)
    if not (data / 'PG_VERSION').is_file():
        if data.exists() and any(data.iterdir()):
            raise PostgresError(_down() + ': data directory is not a PostgreSQL cluster')
        data.mkdir(parents=True, exist_ok=True)
        if record is not None:
            identity.own(data, record, 0o700)
            log_path.touch(exist_ok=True)
            identity.own(log_path, record, 0o644)
        with log_path.open('a') as log:
            init = _run([
                _bin('initdb'), '--username', ROLE, '--auth', 'trust', '--auth-host', 'trust',
                '--encoding', config.get('cloud.postgres_encoding'), '--locale', config.get('cloud.postgres_locale'), '--no-instructions', '-D', data,
            ], log, as_service=True)
        if init.returncode != 0:
            detail = _tail(log_path)
            raise PostgresError(_down() + (f': {detail}' if detail else ': initdb failed'))
    _configure(data)
    if record is not None:
        identity.own_tree(data, record)
        identity.own(log_path, record, 0o644)
    _start(data, log_path)
    _ensure_database()


def status():
    """Start the project server if needed. None when the test database answers, else the problem line."""
    lock_path = Path(config.get('cloud.postgres_lock_path'))
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with identity.open_lock(str(lock_path)) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            _ensure()
    except PostgresError as error:
        return str(error)
    except OSError:
        return f'missing writable path: {lock_path.parent}'
    return None


def ensure():
    problem = status()
    if problem:
        print(problem, file=sys.stderr)
        return 1
    print('postgres: ready')
    return 0


def main(argv):
    if argv != ['ensure']:
        print('Usage: scripts/cloud/postgres.py ensure', file=sys.stderr)
        return 2
    return ensure()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
