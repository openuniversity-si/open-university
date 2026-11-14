"""Event contract catalog (D-065, D-069 items 1, 2 and 4): contracts/events/*.json is the single source of truth.

The envelope is envelope.v1.json; each payload is <type>.v<N>.json with its natural key (x-natural-key, JSON
pointers into the envelope) that makes the event id deterministic. Schema files are immutable once locked in
schemas.lock.json: a change is a new version file (expand), readers accept every locked version, and an old
version leaves only when no producer emits it and replay no longer needs it (contract; P-07, D-029).

  python3 scripts/lib/event_contracts.py check   # the gate's compatibility check (script tests)
  python3 scripts/lib/event_contracts.py lock    # add new schema files to the lock; never rewrites an entry
"""
import hashlib
import json
from pathlib import Path
import re
import sys

import config
import json_schema

ROOT = Path(__file__).resolve().parents[2]
PAYLOAD_FILE = re.compile(r'^(?P<type>[a-z][a-z-]*(?:\.[a-z][a-z-]*)+)\.v(?P<version>[1-9][0-9]*)\.json$')


class ContractError(ValueError):
    pass


def directory():
    return ROOT / config.get('forge-events.contracts_dir')


def registry():
    return json_schema.Registry(directory())


_CATALOGS = {}


def catalog(base=None):
    """{type: {version: file name}} for every payload schema; envelope and defs have no dotted type, so are not events.

    GATE-SPEED R3: held per directory while its listing is unchanged (a file added, removed or renamed changes the
    directory's mtime): validate() asked for it twice per event, 9,372 globs of the contracts in one structure check.
    The caller gets its own copy."""
    return {kind: dict(versions) for kind, versions in _held(Path(base or directory())).items()}


def _held(folder):
    try:
        stamp = folder.stat().st_mtime_ns
    except OSError:
        stamp = None
    held = _CATALOGS.get(folder)
    if held is None or held[0] != stamp or stamp is None:
        held = (stamp, _scan(folder))
        _CATALOGS[folder] = held
    return held[1]


def _scan(folder):
    found = {}
    for path in sorted(folder.glob('*.json')):
        match = PAYLOAD_FILE.match(path.name)
        if match:
            found.setdefault(match['type'], {})[int(match['version'])] = path.name
    return found


def natural_key(envelope, schemas=None):
    """The values the payload schema names in x-natural-key, read from the envelope."""
    schema = (schemas or registry()).load(f'{envelope["type"]}.v{envelope["version"]}.json')
    if 'x-natural-key' not in schema:
        raise ContractError(f'{envelope["type"]} v{envelope["version"]} has no natural key; the port cannot emit it')
    values = []
    for pointer in schema['x-natural-key']:
        node = envelope
        for part in [p for p in pointer.split('/') if p]:
            node = node.get(part) if isinstance(node, dict) else None
        values.append(node)
    return values


def event_id(producer, kind, key):
    """sha256 of producer, type and natural key (SHARED CONTRACT v3 §4); the algorithm is a registry entry."""
    digest = hashlib.new(config.get('forge-events.event_id_algorithm'))
    digest.update(json.dumps([producer, kind, key], sort_keys=True, separators=(',', ':')).encode())
    return digest.hexdigest()


def validate(envelope, schemas=None):
    """Envelope, then payload against its versioned schema, then the id against the natural key."""
    schemas = schemas or registry()
    try:
        schemas.validate(envelope, config.get('forge-events.envelope_schema'))
        name = f'{envelope["type"]}.v{envelope["version"]}.json'
        known = _held(Path(schemas.directory)).get(envelope['type'], {})
        if name not in known.values():
            raise ContractError(f'unknown event {envelope["type"]} v{envelope["version"]}')
        if name in config.get('forge-events.subject_exempt_schemas'):
            raise ContractError(f'{name} predates the port (no subject, no natural key); emit its v2')
        schemas.validate(envelope['payload'], name)
    except json_schema.ValidationError as error:
        raise ContractError(f'{envelope.get("type", "?")}: {error}') from None
    expected = event_id(envelope['producer'], envelope['type'], natural_key(envelope, schemas))
    if envelope['event_id'] != expected:
        raise ContractError(f'{envelope["type"]}: event_id is not the hash of producer, type and natural key')
    return envelope


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lock_path(base=None):
    return Path(base or directory()) / config.get('forge-events.contracts_lock')


def check(base=None):
    """Every schema loads in the supported subset, is locked with its hash, versions are contiguous, keys resolve."""
    base = Path(base or directory())
    errors = []
    schemas = json_schema.Registry(base)
    lock_file = lock_path(base)
    lock = read_lock(lock_file)
    files = sorted(path for path in base.glob('*.json') if path != lock_file)
    for path in files:
        try:
            schema = schemas.load(path.name)
        except (json_schema.SchemaError, ValueError) as error:
            errors.append(f'{path.name}: {error}')
            continue
        if schema.get('$id') != f'{config.get("forge-events.contracts_dir")}/{path.name}':
            errors.append(f'{path.name}: $id must be its own path')
        if path.name not in lock:
            errors.append(f'{path.name}: not locked; run scripts/lib/event_contracts.py lock')
        elif lock[path.name] != _digest(path):
            errors.append(f'{path.name}: a locked schema changed; add {path.name.split(".v")[0]}.v<N+1>.json instead (expand->contract)')
    for name in sorted(set(lock) - {path.name for path in files}):
        errors.append(f'{name}: locked schema removed; retire it only after no producer emits it and replay does not need it')
    known = {name for versions in catalog(base).values() for name in versions.values()}
    for name in config.get('forge-events.subject_exempt_schemas'):
        if name not in known:
            errors.append(f'{name}: listed in forge-events.subject_exempt_schemas but no such schema; drop the entry')
    for kind, versions in catalog(base).items():
        if sorted(versions) != list(range(1, len(versions) + 1)):
            errors.append(f'{kind}: versions must be contiguous from 1, found {sorted(versions)}')
        for name in versions.values():
            if name in config.get('forge-events.subject_exempt_schemas'):
                continue
            schema = schemas.load(name)
            key = schema.get('x-natural-key')
            if not isinstance(key, list) or not key:
                errors.append(f'{name}: x-natural-key must list JSON pointers')
                continue
            for pointer in key:
                head = [p for p in pointer.split('/') if p]
                if not head or (head[0] == 'payload' and (len(head) != 2 or head[1] not in schema['required'])) \
                        or (head[0] != 'payload' and head != ['correlation_id']):
                    errors.append(f'{name}: natural key {pointer} must be /correlation_id or a required payload field')
            for field in config.get('forge-events.subject_fields'):
                if field not in schema.get('required', []):
                    errors.append(f'{name}: payload must carry {field}')
    return errors


def read_lock(lock_file):
    """{file: sha256}. Stored as a list of {file, sha256} objects so no hash shares a line with a file name
    (a name like common-key.requested next to a hex digest reads as a credential to the secret scan)."""
    if not Path(lock_file).is_file():
        return {}
    return {entry['file']: entry['sha256'] for entry in json.loads(Path(lock_file).read_text())}


def lock(base=None):
    """Add unlocked schema files. An existing entry is never rewritten: a changed schema stays an error."""
    base = Path(base or directory())
    lock_file = lock_path(base)
    current = read_lock(lock_file)
    for path in sorted(base.glob('*.json')):
        if path != lock_file and path.name not in current:
            current[path.name] = _digest(path)
    entries = [{'file': name, 'sha256': digest} for name, digest in sorted(current.items())]
    lock_file.write_text(json.dumps(entries, indent=2) + '\n')
    return current


if __name__ == '__main__':
    if sys.argv[1:] == ['check']:
        problems = check()
        for problem in problems:
            print(f'event contracts: {problem}', file=sys.stderr)
        sys.exit(1 if problems else 0)
    if sys.argv[1:] == ['lock']:
        lock()
        sys.exit(0)
    sys.exit('usage: event_contracts.py check|lock')
