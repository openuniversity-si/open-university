"""Delivery credentials: the credential mode and the cached probe of the selected forge's credential.

OU_CREDENTIALS=network trusts an egress proxy that injects Authorization for the forge. The forge's credential is the
selected forge's (forge-events.adapter): each forge module answers its own gaps through forge_events.forge_gaps and asks
cached_probe, whose stamp keeps a digest, never a secret. Open University's database and hosting probes left with it (D-111);
the registry keys they read left with the GitHub client (D-293).
"""
import hashlib
import json
import os
from pathlib import Path

from toolchain_manifest import toolchain_dir

MODES = ('env', 'network')


def mode():
    return os.environ.get('OU_CREDENTIALS', 'env')


def _cache_path():
    own = os.environ.get('OU_PREFLIGHT_STAMP')  # TX12: a test's own stamp, so it never reads or writes the shared one
    return Path(own) if own else toolchain_dir() / 'preflight.stamp'


def _load_cache():
    path = _cache_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _store_cache(key, digest):
    path = _cache_path()
    data = _load_cache()
    data[key] = digest
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, sort_keys=True))
    except OSError:
        return


def _material(names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ''


def _digest(key, names, extras):
    digest = hashlib.sha256()
    digest.update(key.encode())
    digest.update(b'\0')
    digest.update(mode().encode())
    for name in extras:
        digest.update(b'\0')
        digest.update(os.environ.get(name, '').encode())
    digest.update(b'\0')
    digest.update(hashlib.sha256(_material(names).encode()).digest())
    return digest.hexdigest()


def cached_probe(key, names, extras, probe):
    """True when `probe()` succeeded for this key and credential material before (preflight.stamp), or now."""
    digest = _digest(key, names, extras)
    if _load_cache().get(key) == digest:
        return True
    if probe():
        _store_cache(key, digest)
        return True
    return False
