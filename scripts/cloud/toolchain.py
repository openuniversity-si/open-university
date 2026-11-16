#!/usr/bin/env python3
"""Install the pinned tail toolchain into .toolchain/. Checksums come from toolchain.json."""
import contextlib
import fcntl
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import config
import toolchain_manifest as manifest

POSTGRES_SHIM = """#!/bin/sh
here=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
export LD_LIBRARY_PATH="$here/../postgres/lib${{LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}}"
exec "$here/../postgres/bin/{name}" "$@"
"""

ROOT = manifest.ROOT


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(config.get('cloud.download_chunk_bytes')), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url, dest):
    request = Request(url, headers={'User-Agent': config.get('cloud.download_user_agent')})
    with urlopen(request, timeout=config.get('cloud.download_timeout_s')) as response, dest.open('wb') as handle:
        while True:
            chunk = response.read(config.get('cloud.download_chunk_bytes'))
            if not chunk:
                break
            handle.write(chunk)


def _why(url, error):
    """What a failed download says: the URL's host and the exception's type (and an HTTP status), never the URL itself,
    whose query may carry a credential."""
    status = getattr(error, 'code', None)
    return f"{urlparse(url).hostname or 'unknown host'}, {type(error).__name__}{f' {status}' if status else ''}"


def _download_retrying(url, dest, tool, download=None, sleep=time.sleep):
    """_download tried cloud.download_tries times with exponential pauses (cloud.download_backoff_s, then twice, four
    times...): a cold runner task that starts many runs at once meets a network that is not ready or a CDN that throttles
    (09/11: 16 gate jobs, `download failed for python`). The last failure is named, with its host and exception type."""
    download = download or _download
    tries = config.get('cloud.download_tries')
    for attempt in range(tries):
        try:
            return download(url, dest)
        except (OSError, ValueError) as error:
            dest.unlink(missing_ok=True)
            if attempt + 1 == tries:
                raise SystemExit(f'toolchain: download failed for {tool} ({_why(url, error)}, {tries} tries)') from None
            sleep(config.get('cloud.download_backoff_s') * 2 ** attempt)


def _check_sha256(path, expected, tool):
    got = _sha256(path)
    if got != expected:
        path.unlink(missing_ok=True)
        raise SystemExit(f'toolchain: checksum mismatch for {tool}')


def _extract(archive, dest, kind):
    dest.mkdir(parents=True, exist_ok=True)
    flag = '-xJf' if kind == 'xz' else '-xzf'
    subprocess.run(['tar', flag, str(archive), '-C', str(dest)], check=True, stdout=subprocess.DEVNULL)


def _link(bin_dir, name, target):
    path = bin_dir / name
    path.unlink(missing_ok=True)
    path.symlink_to(target)


def _find(root, name):
    matches = [item for item in root.rglob(name) if item.is_file() and item.name == name]
    if len(matches) != 1:
        raise SystemExit('toolchain: unexpected archive layout')
    return matches[0]


def _install_one(tool, root, staging):
    spec = manifest.artifact(tool)
    archive = staging / tool
    _download_retrying(spec['url'], archive, tool)
    _check_sha256(archive, spec['sha256'], tool)
    bin_dir = root / 'bin'
    bin_dir.mkdir(parents=True, exist_ok=True)
    unpacked = staging / f'{tool}-src'
    if unpacked.exists():
        shutil.rmtree(unpacked)
    _extract(archive, unpacked, spec['kind'])
    if tool == 'python':
        source = unpacked / 'python'
        if not (source / 'bin' / 'python3').is_file():
            raise SystemExit('toolchain: unexpected archive layout')
        dest = root / 'python'
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(source), str(dest))
        _link(bin_dir, 'python3', Path('..') / 'python' / 'bin' / 'python3')
    elif tool == 'node':
        found = [item for item in unpacked.iterdir() if item.is_dir() and item.name.startswith('node-')]
        if len(found) != 1 or not (found[0] / 'bin' / 'node').is_file():
            raise SystemExit('toolchain: unexpected archive layout')
        dest = root / 'node'
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(found[0]), str(dest))
        _link(bin_dir, 'node', Path('..') / 'node' / 'bin' / 'node')
    elif tool in ('gitleaks', 'ruff'):
        shutil.copyfile(_find(unpacked, tool), bin_dir / tool)
        (bin_dir / tool).chmod(0o755)
    elif tool == 'postgres':
        found = [item for item in unpacked.iterdir() if item.is_dir() and (item / 'bin' / 'psql').is_file()]
        if len(found) != 1:
            raise SystemExit('toolchain: unexpected archive layout')
        dest = root / 'postgres'
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(found[0]), str(dest))
        for name in config.get('cloud.postgres_binaries'):
            shim = bin_dir / name
            shim.write_text(POSTGRES_SHIM.format(name=name))
            shim.chmod(0o755)
    else:
        raise SystemExit(f'toolchain: unknown tool {tool}')


def ready(root):
    stamp = root / 'install.stamp'
    try:
        if stamp.read_text().strip() != manifest.install_id():
            return False
    except OSError:
        return False
    return all((root / 'bin' / manifest.binary_name(tool)).is_file() for tool in manifest.TOOLS)


def _share(root):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
    import session_identity
    session_identity.share_toolchain(root)


def install():
    root = ROOT / '.toolchain'
    if ready(root):
        _share(root)
        print('toolchain: ready')
        return 0
    root.mkdir(parents=True, exist_ok=True)
    with _locked(root):  # one install per root at a time: the others wait, then find it installed
        if ready(root):
            _share(root)
            print('toolchain: ready')
            return 0
        return _install(root)


@contextlib.contextmanager
def _locked(root):
    with (root / '.install.lock').open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _install(root):
    staging = Path(tempfile.mkdtemp(prefix='toolchain-', dir=root))
    try:
        expected = manifest.load()
        for tool in manifest.TOOLS:
            binary = root / 'bin' / manifest.binary_name(tool)
            current = ''
            if binary.is_file():
                try:
                    current = manifest.observed_version(tool, root)
                except (OSError, RuntimeError):
                    current = ''
            if current != expected[tool]['version']:
                _install_one(tool, root, staging)
                if manifest.observed_version(tool, root) != expected[tool]['version']:
                    raise SystemExit(f'toolchain: {tool} version does not match the manifest')
        (root / 'install.stamp').write_text(manifest.install_id() + '\n')
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    _share(root)
    print('toolchain: installed')
    return 0


def main(argv):
    if argv != ['install']:
        print('Usage: scripts/cloud/toolchain.py install', file=sys.stderr)
        return 2
    try:
        return install()
    except subprocess.CalledProcessError:
        print('toolchain: extract failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
