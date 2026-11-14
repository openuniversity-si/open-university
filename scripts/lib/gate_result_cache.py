#!/usr/bin/env python3
"""Tier-1 result cache for the delivery gate (D-065 V6, M5; GS1 generalizes it to every stage declared deterministic).

A tier-1 stage is skipped when a passing result with the same content key is already cached. A stage keys on its
declaration in gate-stages.json: only a stage declared `deterministic` has a key, and the key covers the stage id, its
declared version, the hash of the files its declared `inputs` match, the toolchain versions and the selection scope it
ran under (GS1). The key is a pure function of what the stage reads: the checkout's tracked and unignored files, the
node version, the toolchain pins of the registry, the key version (registry) and the judging toolchain and runner.
A marker records its key and when it was stored; a marker that does not parse, names another key, is older than
gate.stage_cache_ttl_s or comes from the future is a miss, so a corrupt entry reruns the stage and is never a pass.

GX-23 (B-15, GA-P10): a stage listed in gate-stage-inputs.json keys on the inputs it declares there (globs plus a traced
read set), so a change outside them is a hit. A stage the file does not declare keeps its gate-stages.json inputs.
Narrowing fails closed: the key covers the union of the declared globs and every traced path, a declaration that does
not parse is an error (never a wider hit), and the declared lists and gate-inputs.schema_version are key parts, so
editing a declaration misses.

OU-DECOUPLE F5 (D-113): the lint and typecheck keys (`key`, keyed on the web package's eslint, stylelint and typescript
versions) left with Open University's web stages; their registry keys and their owner left the registry (VAZÃO F43,
D-068 (3) expand then contract).

Tiers 2 and 3 never use the cache. `stage-key` returns an empty string for every mode outside TIER1_MODES, so the caller
runs the stage; `hit` and `store` refuse an empty key.
Markers are kept through the storage port (scripts/lib/adapters/storage.py, D-069 item 7) under tier1/<key> of the
cache location, so a shared store replaces the local directory by a registry change.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from adapters import storage
from config import get
from gate_areas import glob_match
import gate_keys
import gate_tier
from gate_speed import _digest, _node_version

TIER1_MODES = frozenset({'dev'})
# registry names (D-069 item 12), never their values; pnpm left the toolchain (vazão F16)
TOOLCHAIN_PINS = ('toolchain.node_version', 'toolchain.python_version', 'toolchain.claude_cli_version')
DECLARATIONS = Path(__file__).with_name('gate-stages.json')
INPUTS = Path(__file__).with_name('gate-stage-inputs.json')
INPUT_FIELDS = ('inputs', 'traced')


def tier_of(mode):
    """Tier 1 for the PR gate (`--dev`). Every other mode is outside the cache."""
    return 1 if gate_tier.cacheable(mode, TIER1_MODES) else None


def unit_hash(unit=None):
    """Seam for U0 (plan v3): the owning unit's content hash. Null until units/<id>/unit.json exists."""
    return unit


def tree_digest(root, inputs=None):
    """sha256 over every tracked or unignored path and its content. A deleted tracked path changes it too.

    `inputs` (globs, GS1) keeps only the paths a stage declares it reads."""
    listed = subprocess.run(
        ['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard', '--deduplicate'],
        capture_output=True, check=True,
    ).stdout
    digest = hashlib.sha256()
    for raw in sorted(name for name in listed.split(b'\0') if name):
        if inputs is not None and not any(glob_match(os.fsdecode(raw), pattern) for pattern in inputs):
            continue
        path = Path(root) / os.fsdecode(raw)
        digest.update(raw + b'\0')
        if path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
        else:
            digest.update(b'missing\0')
    return digest.hexdigest()


def declared_inputs(stage):
    """(shared_inputs + inputs, traced) of the stage in gate-stage-inputs.json; None when undeclared or narrowing is off.

    A malformed file or entry raises ValueError: fail closed, the caller runs the stage rather than hit a wider key."""
    if not get('gate-inputs.enabled'):
        return None
    try:
        document = json.loads(INPUTS.read_text())
        stages, shared = document['stages'], document['shared_inputs']
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'{INPUTS.name}: unreadable declaration ({error})') from error
    if not isinstance(stages, dict):
        raise ValueError(f'{INPUTS.name}: stages must be an object')
    spec = stages.get(stage)
    if spec is None:
        return None
    globs, traced = (spec.get(field) if isinstance(spec, dict) else None for field in INPUT_FIELDS)
    for field, values in (('shared_inputs', shared), ('inputs', globs), ('traced', traced)):
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
            raise ValueError(f'{INPUTS.name}: {stage} {field} must be a list of non-empty strings')
    if not globs:
        raise ValueError(f'{INPUTS.name}: {stage}.inputs is empty')
    return [*shared, *globs], traced


def _narrowed(stage):
    """(digest globs, key parts) of a declared stage; (None, []) when undeclared."""
    declared = declared_inputs(stage)
    if declared is None:
        return None, []
    globs, traced = declared
    return [*globs, *traced], ['inputs', get('gate-inputs.schema_version'), json.dumps([globs, traced])]


def declaration(stage):
    """The stage's entry in gate-stages.json; None when the stage is not declared."""
    return json.loads(DECLARATIONS.read_text())['stages'].get(stage)


def stage_key(mode, root, stage, scope=''):
    """Content key of a stage declared deterministic, or '' when it must run (undeclared, not deterministic, tier 2 or 3, off)."""
    spec = declaration(stage)
    if not spec or not spec['deterministic'] or not gate_tier.cacheable(mode, TIER1_MODES) or not get('gate.stage_cache_enabled'):
        return ''
    globs, narrowed = _narrowed(stage)
    return _digest([
        'stage', get('gate.stage_cache_version'), stage, spec['version'], _node_version(),
        *(get(name) for name in TOOLCHAIN_PINS), tree_digest(root, spec['inputs'] if globs is None else globs), scope,
        *narrowed, *gate_keys.key_parts(),
    ])


def markers(cache):
    """Where the stage markers live: GATE_STAGE_CACHE_DIR when set (a --cold verdict keeps its content-addressed markers
    apart from its fresh build cache, D-076), else the build cache directory the caller passes."""
    return os.environ.get('GATE_STAGE_CACHE_DIR') or cache


def _marker(key_value):
    return f'tier1/{key_value}'


def _now():
    import forge_events  # the registry's injected clock (forge-events.clock), never the wall clock read here
    return int(forge_events.clock_from_config().now().timestamp())


def hit(cache, key_value, now=None):
    """True when the store holds an unexpired, well-formed marker for exactly this key."""
    if not key_value:
        return False
    blob = storage.open_store(markers(cache)).get(_marker(key_value))
    if blob is None:
        return False
    try:
        marker = json.loads(blob)
        stored_at = marker['stored_at']
        valid = marker['key'] == key_value and isinstance(stored_at, int) and not isinstance(stored_at, bool)
    except (ValueError, KeyError, TypeError):
        return False
    now = _now() if now is None else now
    return valid and 0 <= now - stored_at <= get('gate.stage_cache_ttl_s')


def store(cache, key_value, now=None):
    """Records a pass. Callers store only after the command passed."""
    if not key_value:
        raise ValueError('an empty key is never stored: the step ran outside tier 1')
    marker = {'key': key_value, 'stored_at': _now() if now is None else now}
    storage.open_store(markers(cache)).put(_marker(key_value), json.dumps(marker, sort_keys=True).encode())


def record_cached(logs, step, key_value):
    """Writes the stage record of a cached step in the shape `step` writes, and says so in its log."""
    logs = Path(logs)
    stem = re.sub(r'[^a-zA-Z0-9]', '_', step)
    (logs / f'{stem}.log').write_text(f'cached: tier-1 result {key_value} (D-065 V6); the command did not run\n')
    (logs / f'{stem}.stage.json').write_text(json.dumps(
        {'name': step, 'result': 'PASS', 'exit': 0, 'seconds': 0, 'cached': True, 'key': key_value}))


def main(argv):
    parser = argparse.ArgumentParser(prog='gate_result_cache', description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    staged = commands.add_parser('stage-key')
    staged.add_argument('--mode', default='')
    staged.add_argument('--root', required=True)
    staged.add_argument('--stage', required=True)
    staged.add_argument('--scope', default='')
    for name in ('hit', 'store'):
        command = commands.add_parser(name)
        command.add_argument('--cache', required=True)
        command.add_argument('--key', required=True)
    recorded = commands.add_parser('record-cached')
    recorded.add_argument('--logs', required=True)
    recorded.add_argument('--step', required=True)
    recorded.add_argument('--key', required=True)
    args = parser.parse_args(argv[1:])
    if args.command == 'stage-key':
        print(stage_key(args.mode, args.root, args.stage, args.scope))
        return 0
    if args.command == 'hit':
        return 0 if hit(args.cache, args.key) else 1
    if args.command == 'store':
        store(args.cache, args.key)
        return 0
    record_cached(args.logs, args.step, args.key)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv))
    except (subprocess.CalledProcessError, OSError, ValueError) as error:
        print(f'gate_result_cache failed: {error}', file=sys.stderr)
        sys.exit(2)
