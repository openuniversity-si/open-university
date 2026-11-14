"""The storage port (D-069 item 7, plan v3.1 R1): the engine keeps blobs by key here, never in a vendor's store.

Adapter interface (the local filesystem; s3 is the shared object store of the DEP8 artifacts, location = bucket, no keys()):
  exists(key)      whether the key holds a blob.
  get(key)         the blob's bytes, or None.
  put(key, data)   store the bytes under the key, atomically: a reader sees the old blob or the new one.
  keys(prefix)     the stored keys under a prefix, sorted.
A key is relative segments of [A-Za-z0-9._-] joined by '/', never '.' or '..'. open_store(location) gives the adapter
providers.storage_adapter names, rooted at location (for the local adapter, a directory).
"""
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

SEGMENT = re.compile(r'^[A-Za-z0-9._-]+$')


class StorageError(ValueError):
    pass


def check_key(key):
    parts = (key or '').split('/')
    if not key or any(not SEGMENT.match(part) or part in ('.', '..') for part in parts):
        raise StorageError(f'storage key {key!r} is not relative segments of [A-Za-z0-9._-]')
    return key


def _local(location):
    from adapters import storage_local  # the adapter module loads only when the registry selects it
    return storage_local.LocalStorage(location)


def _s3(location):
    from adapters import storage_s3  # likewise: only a caller that asks for the shared store loads it
    return storage_s3.S3Storage(location)


ADAPTERS = {'local': _local, 's3': _s3}


def open_store(location, name=None):
    name = name or config.get('providers.storage_adapter')
    if name not in ADAPTERS:
        raise StorageError(f'unknown storage adapter {name}')
    return ADAPTERS[name](location)
