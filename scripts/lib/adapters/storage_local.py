"""Local filesystem adapter of the storage port: one file per key under a root directory, atomic replace on put."""
import os
from pathlib import Path
import tempfile

from adapters.storage import check_key


class LocalStorage:
    name = 'local'

    def __init__(self, root):
        self.root = Path(root)

    def path(self, key):
        return self.root / check_key(key)

    def exists(self, key):
        return self.path(key).is_file()

    def get(self, key):
        path = self.path(key)
        return path.read_bytes() if path.is_file() else None

    def put(self, key, data):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix='.put-')
        try:
            with os.fdopen(handle, 'wb') as out:
                out.write(data)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def keys(self, prefix=''):
        base = self.root / check_key(prefix) if prefix else self.root
        if not base.is_dir():
            return []
        return sorted(path.relative_to(self.root).as_posix() for path in base.rglob('*')
                      if path.is_file() and not path.name.startswith('.put-'))
