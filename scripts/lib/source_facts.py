"""What a tree check extracts from one file's text alone, kept by that text across runs (F21, F31).

A check that walks every file's syntax splits the walk from the verdict: an extractor reads only the text (no registry,
no path, no other file) and returns JSON-shaped facts, and the check applies its registry to those facts live. The
facts are kept in one store (config.literal_cache_dir through the storage port; CONFIG_LITERAL_CACHE_DIR overrides it
for one run, empty turns it off) under the hash of the extractor's digest and the text. The digest is the
interpreter's version and the source bytes of every module the extractor runs, so an edit to the code is a new key and
never reads an answer the old code gave. A missing, unreadable, malformed or read-only store is only slower: the
facts are extracted again, the same answer.

Library: store(root), digest(*modules), cached(store, extractor, text, extract, well_formed).
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import config

ENV = 'CONFIG_LITERAL_CACHE_DIR'
_DIGESTS = {}  # modules -> digest, computed once per process


def store(root):
    """The store of extracted facts, or None when it is turned off or cannot be opened."""
    try:
        location = os.environ.get(ENV)
        location = config.get('config.literal_cache_dir', root) if location is None else location
        if not location:
            return None
        from adapters import storage
        return storage.open_store(os.path.expanduser(location))
    except Exception:  # noqa: BLE001 - a missing cache is only slower, never a different answer
        return None


def digest(*modules):
    """The extractor's identity: the interpreter's version (its grammar) and the bytes of each module it runs."""
    if modules not in _DIGESTS:
        found = hashlib.sha256(sys.version.encode())
        for module in modules:
            found.update(Path(module).read_bytes())
        _DIGESTS[modules] = found.hexdigest()
    return _DIGESTS[modules]


def cached(held, extractor, text, extract, well_formed):
    """extract(text), read from the store `held` when it keeps facts for exactly this text and extractor and
    well_formed(facts) accepts them; anything else is extracted again and rewritten."""
    if held is None:
        return extract(text)
    key = hashlib.sha256(f'{extractor}\0{text}'.encode('utf-8', 'surrogatepass')).hexdigest()
    try:
        facts = json.loads(held.get(key) or b'null')
        if well_formed(facts):
            return facts
    except Exception:  # noqa: BLE001 - an unreadable entry is a miss
        pass
    facts = extract(text)
    try:
        held.put(key, json.dumps(facts, separators=(',', ':')).encode())
    except Exception:  # noqa: BLE001 - a read-only cache is only slower
        pass
    return facts
