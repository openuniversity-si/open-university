#!/usr/bin/env python3
"""Exercise the uid-0 tail path. The parent starts this process as root."""
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import stat
import subprocess
import sys
import tempfile

REPO = Path(os.environ['OU_REPO'])
REAL = Path(os.environ['OU_REAL_TOOLCHAIN'])
sys.path.insert(0, str(REPO / 'scripts' / 'lib'))
sys.path.insert(0, str(REPO / 'scripts' / 'cloud'))
import session_identity as identity
import postgres


def _port():
    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _git(env, repo):
    return subprocess.run(
        ['git', '-C', str(repo), 'status', '--porcelain'],
        env=env, capture_output=True, text=True, check=False,
    )


def _package_uid(tool, node, foreign):
    """Root-package lifecycle script, run by npm (Node's own; pnpm left the toolchain, vazão F16).

    `foreign` is a home owned by another uid. The root environment must leave it
    and send npm's cache to a directory uid 0 owns.
    """
    work = Path(tempfile.mkdtemp(prefix='ou-pkg-uid-'))
    os.chmod(work, 0o755)
    out = work / 'uid.txt'
    (work / 'write-uid.js').write_text(
        "require('fs').writeFileSync(process.env.UID_OUT, String(process.getuid()))\n"
    )
    (work / 'package.json').write_text(json.dumps({
        'name': 'uid-probe', 'private': True, 'scripts': {'preinstall': 'node write-uid.js'},
    }))
    env = os.environ.copy()
    env['HOME'] = str(foreign)
    for key in ('XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_RUNTIME_DIR'):
        env.pop(key, None)
    env.update(identity.root_environment(env))
    if env.get('HOME') == str(foreign) or Path(env['HOME']).stat().st_uid != 0:
        raise RuntimeError('root kept a home owned by another user')
    env['UID_OUT'] = str(out)
    env['PATH'] = str(node.parent) + os.pathsep + env.get('PATH', '')
    completed = subprocess.run(
        [str(tool), 'install', '--no-audit', '--no-fund', '--no-update-notifier', '--offline'],
        cwd=work, env=env, capture_output=True, text=True, check=False, timeout=120,
    )
    uid = out.read_text().strip() if out.is_file() else ''
    detail = (completed.stderr or completed.stdout)[-300:]
    shutil.rmtree(work, ignore_errors=True)
    leftover = [path.name for path in foreign.iterdir()]
    if leftover:
        raise RuntimeError('root npm wrote into a foreign home: ' + ','.join(leftover))
    return {'uid': uid, 'exit': completed.returncode, 'detail': detail, 'home': env['HOME']}


def main():
    if os.geteuid() != 0:
        print('probe requires uid 0', file=sys.stderr)
        return 2
    if not (REAL / 'bin' / 'initdb').is_file() or not (REAL / 'postgres' / 'bin' / 'initdb').is_file():
        print('missing toolchain: postgres', file=sys.stderr)
        return 2
    work = Path(tempfile.mkdtemp(prefix='ou-root-pg-'))
    os.chmod(work, 0o755)
    # A previous probe can leave the account pointing at a directory that still
    # exists. Remove that home so this run has to repair it.
    try:
        stale = Path(pwd.getpwnam(identity.PG_USER).pw_dir)
    except KeyError:
        stale = None
    if stale is not None and str(stale).startswith('/tmp/') and stale.is_dir():
        shutil.rmtree(stale)
    data = None
    try:
        (work / 'postgres').symlink_to(REAL / 'postgres', target_is_directory=True)
        bindir = work / 'bin'
        bindir.mkdir()
        for name in ('initdb', 'psql', 'pg_ctl', 'createdb'):
            (bindir / name).symlink_to(REAL / 'bin' / name)
        hidden = work / 'secret-bin'
        hidden.write_text('#!/bin/sh\n')
        hidden.chmod(0o700)
        identity.share_toolchain(work)
        if stat.S_IMODE(hidden.stat().st_mode) != 0o755:
            raise RuntimeError('toolchain permissions stayed private')
        os.environ['OU_TOOLCHAIN_DIR'] = str(work)
        os.environ['OU_POSTGRES_PORT'] = str(_port())
        data = work / 'pgdata'
        started = postgres.status()
        if started is not None:
            raise RuntimeError(started)
        again = postgres.status()
        if again is not None:
            raise RuntimeError(again)
        record = identity.ensure_service_user(work / 'pghome')
        if not Path(record.pw_dir).is_dir():
            raise RuntimeError('service user home is not a directory')
        info = data.stat()
        if info.st_uid != record.pw_uid or info.st_uid == 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise RuntimeError('pgdata is not owned by the unprivileged account')
        socket_dir = work / 'pgsocket'
        socket_info = socket_dir.stat()
        if socket_info.st_uid != record.pw_uid or stat.S_IMODE(socket_info.st_mode) != 0o755:
            raise RuntimeError('socket directory is not traversable')
        config = (data / 'open-university.conf').read_text()
        if "unix_socket_permissions = '0777'" not in config or "unix_socket_directories" not in config:
            raise RuntimeError('socket permissions were not published')
        pid = int((data / 'postmaster.pid').read_text().splitlines()[0])
        uid_line = next(line for line in Path(f'/proc/{pid}/status').read_text().splitlines() if line.startswith('Uid:'))
        server_uid = int(uid_line.split()[1])
        if server_uid != record.pw_uid or server_uid == 0:
            raise RuntimeError('postgres server is running as root')
        if postgres._psql(postgres.DATABASE, 'select 1') != '1':
            raise RuntimeError('test database did not answer')
        lock = Path('/tmp/open-university-postgres.lock')
        if stat.S_IMODE(lock.stat().st_mode) != 0o666:
            raise RuntimeError('postgres lock is not shared')
        bare_env = os.environ.copy()
        for key in list(bare_env):
            # sudo sets SUDO_UID, and git then treats that uid as the owner.
            # A real uid-0 session has no SUDO_UID; that is the case under test.
            # OU_ROOT_SESSION marks a shell that already sourced root-session.sh; a fresh session has not.
            if key.startswith('GIT_CONFIG_') or key.startswith('SUDO_') or key == 'OU_ROOT_SESSION':
                bare_env.pop(key)
        home = work / 'empty-home'
        home.mkdir()
        bare_env['HOME'] = str(home)
        bare_env['GIT_CONFIG_GLOBAL'] = '/dev/null'
        bare_env['GIT_CONFIG_SYSTEM'] = '/dev/null'
        # A repository another uid owns, whoever owns this checkout (a cloud
        # checkout can belong to root itself, which git rightly accepts).
        foreign_repo = work / 'foreign-repo'
        foreign_repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(foreign_repo)], env=bare_env, check=True)
        for path in [foreign_repo, *foreign_repo.rglob('*')]:
            os.lchown(path, 1000, 1000)
        bare = _git(bare_env, foreign_repo)
        if bare.returncode == 0 or 'dubious' not in bare.stderr.lower():
            raise RuntimeError('git did not reject a foreign owner for uid 0')
        fixed = bare_env.copy()
        fixed.update(identity.root_environment(bare_env))
        good = _git(fixed, foreign_repo)
        if good.returncode != 0:
            raise RuntimeError('git safe.directory was not applied')
        sourced = subprocess.run(
            ['bash', '-c', 'source scripts/cloud/root-session.sh && git -C "$1" status --porcelain', 'probe', str(foreign_repo)],
            cwd=REPO, env=bare_env, capture_output=True, text=True, check=False,
        )
        if sourced.returncode != 0 or 'dubious' in sourced.stderr.lower():
            raise RuntimeError('root-session.sh did not make git usable: ' + sourced.stderr[-300:])
        node = REAL / 'bin' / 'node'
        if not node.is_file():
            node = Path(shutil.which('node') or '')
        if not node.is_file():
            raise RuntimeError('missing toolchain: node')
        npm = node.resolve().parent / 'npm'  # Node's own npm, beside the node binary it ships with
        if not npm.is_file():
            raise RuntimeError('missing toolchain: npm (node)')
        foreign = work / 'foreign-home'
        foreign.mkdir()
        os.chown(foreign, 1000, 1000)
        os.chmod(foreign, 0o755)
        kept = _package_uid(npm, node, foreign)
        if kept['uid'] != '0' or kept['exit'] != 0:
            raise RuntimeError('npm lifecycle script did not stay uid 0: ' + kept['detail'])
        tool = next(name for name in identity.DROP_TOOLS if identity.find_tool(name))
        report = {
            'user': record.pw_name,
            'uid': record.pw_uid,
            'server_uid': server_uid,
            'drop': tool,
            'npm_uid': kept['uid'],
            'git': 'safe.directory',
            'lock': '0666',
        }
        print(json.dumps(report))
        return 0
    finally:
        try:
            if data is not None and (data / 'PG_VERSION').is_file():
                argv, env = identity.command_as(identity.PG_USER, [
                    work / 'bin' / 'pg_ctl', '-D', data, '-m', 'fast', 'stop',
                ])
                subprocess.run(argv, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except Exception:
            pass
        shutil.rmtree(work, ignore_errors=True)
        try:
            identity.ensure_service_user(REAL / 'pghome')
        except Exception:
            pass


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
