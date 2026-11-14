#!/usr/bin/env python3
"""Identity of the process running the delivery tail.

The tail used to assume an unprivileged uid. A real session can be uid 0, and
every such assumption fails together: initdb refuses root, Chromium refuses
root without --no-sandbox, npm drops lifecycle scripts to nobody, git
rejects a repository owned by another uid, and files created with a root umask
are not writable by the account that must own the database.

This module is the only branch on the uid. A non-root process keeps the
previous behavior: no account is created, no privilege drop, no environment
rewrite. The one permission change is a lock file that lives directly in
/tmp: that path is a flock token shared with uid 0, so the owner leaves it
mode 0666. Opening that file never uses O_CREAT once it exists.
fs.protected_regular rejects O_CREAT on another user's file in sticky /tmp
even at mode 0666. A private lock keeps its mode.

When the process is root, PostgreSQL runs as the dedicated system user
`ou-postgres`. `useradd` creates that user when it is on PATH (or in sbin).
Fallback, with no useradd: append a free system uid and gid to /etc/passwd and
/etc/group, which a root process can write without any privilege helper. An
existing `ou-postgres` account is reused.

Privilege drop, first match wins: runuser, su, setpriv. Preflight names every
one of those tools when none is installed.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import pwd
import grp
import re
import shutil
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
import toolchain_manifest as manifest

PG_USER = 'ou-postgres'
DROP_TOOLS = ('runuser', 'su', 'setpriv')
TOOL_PATHS = {
    'runuser': ('/usr/bin/runuser', '/usr/sbin/runuser'),
    'su': ('/usr/bin/su', '/bin/su'),
    'setpriv': ('/usr/bin/setpriv', '/bin/setpriv'),
    'useradd': ('/usr/sbin/useradd', '/usr/bin/useradd'),
}


class IdentityError(RuntimeError):
    pass


def running_as_root():
    return os.geteuid() == 0


def find_tool(name):
    found = shutil.which(name)
    if found:
        return found
    for candidate in TOOL_PATHS.get(name, ()):
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def missing_drop_tools():
    """Every privilege-drop tool, when root has none of them. Empty otherwise."""
    if not running_as_root() or any(find_tool(name) for name in DROP_TOOLS):
        return []
    return [f'missing host tool: {name}' for name in DROP_TOOLS]


def service_user_problem():
    """Empty when `ou-postgres` exists or root can create it."""
    if not running_as_root():
        return []
    try:
        pwd.getpwnam(PG_USER)
        return []
    except KeyError:
        pass
    if find_tool('useradd'):
        return []
    if os.access('/etc/passwd', os.W_OK) and os.access('/etc/group', os.W_OK):
        return []
    return ['missing host tool: useradd']


def root_problems():
    return missing_drop_tools() + service_user_problem()


def _used_ids(path, column):
    used = set()
    try:
        text = Path(path).read_text(errors='replace')
    except OSError:
        return used
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        parts = line.split(':')
        if len(parts) > column and parts[column].isdigit():
            used.add(int(parts[column]))
    return used


def _append_line(path, line):
    file = Path(path)
    text = file.read_text(errors='replace') if file.exists() else ''
    if text and not text.endswith('\n'):
        text += '\n'
    file.write_text(text + line + '\n')


def add_system_user(name, home, passwd='/etc/passwd', group='/etc/group'):
    """Create `name` by appending to the account files. Idempotent.

    This is the fallback when `useradd` is not installed. The caller is root.
    """
    home = str(home)
    try:
        text = Path(passwd).read_text(errors='replace')
    except OSError as error:
        raise IdentityError('missing host tool: useradd') from error
    if any(line.split(':', 1)[0] == name for line in text.splitlines()):
        return
    taken = _used_ids(passwd, 2) | _used_ids(group, 2)
    ids = range(config.get('env-premises.session_id_floor'), config.get('env-premises.session_id_ceiling'))
    chosen = next((candidate for candidate in ids if candidate not in taken), None)
    if chosen is None:
        raise IdentityError('missing host tool: useradd')
    shell = '/usr/sbin/nologin' if Path('/usr/sbin/nologin').exists() else '/bin/false'
    _append_line(group, f'{name}:x:{chosen}:')
    _append_line(passwd, f'{name}:x:{chosen}:{chosen}:Open University postgres:{home}:{shell}')


def set_passwd_home(name, home, passwd='/etc/passwd'):
    """Point an existing account at `home`. Fallback when `usermod` is absent."""
    file = Path(passwd)
    lines = []
    found = False
    for line in file.read_text(errors='replace').splitlines():
        parts = line.split(':')
        if parts and parts[0] == name and len(parts) >= 6:
            parts[5] = str(home)
            line = ':'.join(parts)
            found = True
        lines.append(line)
    if not found:
        raise IdentityError('missing host tool: useradd')
    file.write_text('\n'.join(lines) + '\n')


def _create_service_user(home):
    useradd = find_tool('useradd')
    if useradd:
        shell = '/usr/sbin/nologin' if Path('/usr/sbin/nologin').exists() else '/bin/false'
        completed = subprocess.run(
            [useradd, '--system', '--no-create-home', '--home-dir', str(home),
             '--shell', shell, '--user-group', PG_USER],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False,
        )
        if completed.returncode != 0:
            try:
                return pwd.getpwnam(PG_USER)
            except KeyError:
                raise IdentityError('missing host tool: useradd') from None
        return pwd.getpwnam(PG_USER)
    add_system_user(PG_USER, home)
    try:
        return pwd.getpwnam(PG_USER)
    except KeyError:
        raise IdentityError('missing host tool: useradd') from None


def _usable_home(record):
    raw = record.pw_dir or ''
    if raw in ('', '/', '/nonexistent', '/dev/null'):
        return None
    directory = Path(raw)
    return directory if directory.is_dir() else None


def ensure_service_user(home):
    """Return the passwd entry for the database account. None when not root.

    An existing account is reused. A home that was removed (for example a
    previous temporary directory) is pointed at `home` again.
    """
    if not running_as_root():
        return None
    requested = Path(home)
    requested.mkdir(parents=True, exist_ok=True)
    try:
        record = pwd.getpwnam(PG_USER)
    except KeyError:
        record = _create_service_user(requested)
    if _usable_home(record) is None:
        usermod = find_tool('usermod')
        if usermod:
            completed = subprocess.run(
                [usermod, '-d', str(requested), PG_USER],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False,
            )
            if completed.returncode != 0:
                set_passwd_home(PG_USER, requested)
        else:
            set_passwd_home(PG_USER, requested)
        record = pwd.getpwnam(PG_USER)
    directory = _usable_home(record) or requested
    directory.mkdir(parents=True, exist_ok=True)
    os.chown(directory, record.pw_uid, record.pw_gid)
    os.chmod(directory, 0o755)
    return record


def command_as(user, args):
    """argv and env that run `args` as `user`. Root only; the caller checked."""
    tool = None
    for name in DROP_TOOLS:
        tool = find_tool(name)
        if tool:
            break
    if tool is None:
        raise IdentityError('\n'.join(f'missing host tool: {name}' for name in DROP_TOOLS))
    argv = [str(arg) for arg in args]
    name = Path(tool).name
    if name == 'runuser':
        return [tool, '-u', user, '--', *argv], None
    if name == 'su':
        return [tool, '-s', '/bin/sh', user, '-c', 'exec "$0" "$@"', '--', *argv], None
    record = pwd.getpwnam(user)
    group = grp.getgrgid(record.pw_gid).gr_name
    env = os.environ.copy()
    env['HOME'] = record.pw_dir or '/tmp'
    env['USER'] = user
    env['LOGNAME'] = user
    return [tool, f'--reuid={user}', f'--regid={group}', '--init-groups', '--inh-caps=-all', '--', *argv], env


def own(path, record, mode):
    if not running_as_root():
        return
    target = Path(path)
    os.chown(target, record.pw_uid, record.pw_gid)
    os.chmod(target, mode)


def own_tree(path, record):
    """Give `record` the tree. Symlinks stay untouched so a link cannot retarget the toolchain."""
    if not running_as_root():
        return
    root = Path(path)
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if not (Path(dirpath) / name).is_symlink()]
        os.chown(dirpath, record.pw_uid, record.pw_gid)
        for name in filenames:
            target = Path(dirpath) / name
            if target.is_symlink():
                continue
            os.chown(target, record.pw_uid, record.pw_gid)


def traversable(path):
    """Add the search bit (o+x) to every ancestor of `path` that this uid owns and that lacks it: a toolchain under a
    0700 home (`/root/the-tower`, where a cloud session clones) is otherwise unreachable by `ou-postgres` whatever its
    own modes. Only the search bit: the ancestors stay unlistable by others."""
    for parent in Path(path).resolve().parents:
        info = parent.stat()
        if info.st_uid == os.geteuid() and not info.st_mode & stat.S_IXOTH:
            os.chmod(parent, stat.S_IMODE(info.st_mode) | stat.S_IXOTH)


def share_toolchain(root):
    """Root umask 077 makes the toolchain unexecutable by `ou-postgres`. Relax that, not the data dir, and make the
    path to it (and to what its symlinks point at) traversable."""
    if not running_as_root():
        return
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        return
    traversable(root)
    excluded = {'pgdata', 'pgsocket', 'pghome'}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            if (Path(dirpath) / name).is_symlink() and (Path(dirpath) / name).exists():
                traversable(Path(dirpath) / name)
        dirnames[:] = [
            name for name in dirnames
            if name not in excluded and not (Path(dirpath) / name).is_symlink()
        ]
        os.chmod(dirpath, 0o755)
        for name in filenames:
            target = Path(dirpath) / name
            if target.is_symlink():
                continue
            mode = 0o755 if target.stat().st_mode & 0o111 else 0o644
            os.chmod(target, mode)


def _direct_tmp_lock(path):
    """A flock token that lives directly in /tmp, not inside a private subdirectory."""
    return Path(path).parent == Path('/tmp')


def _owner_or_absent(path):
    """True when this uid can chmod `path`: it does not exist yet, or we own it."""
    target = Path(path)
    if not target.exists():
        return True
    try:
        return target.stat().st_uid == os.geteuid()
    except OSError:
        return False


def _share_lock(path):
    """True when this process should leave the lock at mode 0666.

    Root shares every lock; the owner shares a /tmp lock.

    uid 0 on this platform has no CAP_DAC_OVERRIDE, so it cannot open a 0644
    file owned by the session uid. The session uid has to publish the token.
    """
    if running_as_root():
        return True
    return _direct_tmp_lock(path) and _owner_or_absent(path)


def _open_lock_fd(path):
    """Open a lock. An existing file is opened without O_CREAT.

    fs.protected_regular returns EACCES for O_CREAT on another user's file in
    sticky /tmp, including a mode 0666 file. A read-only descriptor is enough
    for flock.
    """
    last = None
    for flags in (os.O_RDWR | os.O_APPEND, os.O_RDONLY):
        try:
            return os.open(path, flags), bool(flags & os.O_RDWR)
        except FileNotFoundError:
            last = None
            break
        except PermissionError as exc:
            last = exc
    try:
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
        return os.open(path, flags, 0o666), True
    except PermissionError as exc:
        last = exc
    for flags in (os.O_RDWR | os.O_APPEND, os.O_RDONLY):
        try:
            return os.open(path, flags), bool(flags & os.O_RDWR)
        except PermissionError as exc:
            last = exc
    raise last if last is not None else PermissionError(path)


def _publish(path):
    if not _share_lock(path):
        return
    try:
        os.chmod(path, 0o666)
    except PermissionError:
        pass


def open_lock(path):
    """Open a lock file. A shared lock is left mode 0666; a private lock is not."""
    fd, writable = _open_lock_fd(path)
    _publish(path)
    return os.fdopen(fd, 'r+' if writable else 'r')


def exclusive_lock(path):
    """Hold an exclusive flock until the context exits. The descriptor is not inherited."""
    @contextmanager
    def _held():
        handle = open_lock(path)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield handle
        finally:
            handle.close()

    return _held()


def prepare_lock(path):
    """Create a shared lock when this uid can. A private lock is untouched."""
    if not _share_lock(path):
        return
    fd, _writable = _open_lock_fd(path)
    try:
        _publish(path)
    finally:
        os.close(fd)


def _owned_by_root(path):
    """True when uid 0 owns `path`. A root process must not keep another user's home."""
    try:
        return Path(path).stat().st_uid == 0
    except OSError:
        return False


def _writable(path):
    probe = Path(path) / f'.ou-write-probe-{os.getpid()}'
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        probe.write_text('ok')
        probe.unlink()
    except OSError:
        return False
    return True


def _shell_quote(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"


def root_environment(environ=None):
    """Assignments a root shell needs. Empty when the process is not root.

    HOME stays only when it is writable and owned by uid 0. A home owned by
    another user is not used: root can write there and would leave caches that
    user cannot update. Otherwise HOME moves to /root, or under the toolchain
    when /root is not writable. XDG directories are created under that home.
    Git accepts any repository ownership. npm keeps lifecycle scripts as
    the current uid instead of dropping them to nobody.
    """
    if not running_as_root():
        return {}
    environ = os.environ if environ is None else environ
    # unsafe-perm keeps lifecycle scripts on this uid. confirmModulesPurge avoids a
    # TTY prompt when a root reinstall has to recreate node_modules. CI stays unset:
    # Playwright and Next treat CI as a different test mode.
    updates = {
        'npm_config_unsafe_perm': 'true',
        'npm_config_confirm_modules_purge': 'false',
    }
    try:
        count = int(environ.get('GIT_CONFIG_COUNT', '0') or '0')
    except ValueError:
        count = 0
    if count < 0:
        count = 0
    if not any(environ.get(f'GIT_CONFIG_KEY_{index}') == 'safe.directory' for index in range(count)):
        updates['GIT_CONFIG_COUNT'] = str(count + 1)
        updates[f'GIT_CONFIG_KEY_{count}'] = 'safe.directory'
        updates[f'GIT_CONFIG_VALUE_{count}'] = '*'
    home = environ.get('HOME', '')
    if not home or not _writable(home) or not _owned_by_root(home):
        fallback = Path('/root')
        if _writable(fallback):
            home = str(fallback)
        else:
            home = str(manifest.toolchain_dir() / 'home')
            Path(home).mkdir(parents=True, exist_ok=True)
            os.chmod(home, 0o700)
        updates['HOME'] = home
    for relative in ('.cache', '.config', '.local/share', '.local/state'):
        Path(home, relative).mkdir(parents=True, exist_ok=True)
    defaults = {
        'XDG_CACHE_HOME': str(Path(home) / '.cache'),
        'XDG_CONFIG_HOME': str(Path(home) / '.config'),
        'XDG_DATA_HOME': str(Path(home) / '.local/share'),
        'XDG_STATE_HOME': str(Path(home) / '.local/state'),
    }
    for key, default in defaults.items():
        current = environ.get(key, '')
        # Writable is not enough: root can write another user's directory and leave it unusable.
        if not current or not _writable(current) or not _owned_by_root(current):
            Path(default).mkdir(parents=True, exist_ok=True)
            updates[key] = default
    runtime = environ.get('XDG_RUNTIME_DIR', '')
    if not runtime or not _writable(runtime):
        runtime_dir = Path('/tmp/ou-xdg-runtime-0')
        runtime_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(runtime_dir, 0o700)
        updates['XDG_RUNTIME_DIR'] = str(runtime_dir)
    return updates


def format_exports(values):
    lines = []
    for key, value in values.items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise IdentityError('invalid export name')
        lines.append(f'export {key}={_shell_quote(value)}')
    return ('\n'.join(lines) + '\n') if lines else ''


def main(argv):
    if argv == ['export']:
        sys.stdout.write(format_exports(root_environment()))
        return 0
    print('Usage: session_identity.py export', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
