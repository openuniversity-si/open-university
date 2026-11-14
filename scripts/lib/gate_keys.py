"""Seam for the content-addressed proof key (GX-39 seam; GX-28 fills it with the attested toolchain).

`key_parts()` returns the extra parts a result-cache key covers beyond the pins and the tree: the attested
`toolchain_id` (`toolchain_manifest.attestation`: the versions the installed binaries report, the effective registry
including the change store, never install.stamp). A container with another toolchain or config gets other keys and
misses every cache. An attestation that cannot be made gives a part no other run shares (fail closed: nothing is
reused). One attestation per process: `reset()` drops it.

Seam for GX-11 (`gate_test_cache.key`, not edited here): append `*gate_keys.key_parts()` to the test key.

D-076 (GATE-FAST, P-56): the parts also cover the judging runner, the content of the tool root's files that run a test
or a stage (gate.content_runner_inputs: the part of gate_version a result depends on), so a key names one result
whichever run or tier recorded it. A runner that cannot be read gives a part no other run shares (fail closed).

D-082 (GATE-TRAIN-SERVICES, GX-23): one gate run keys with one set of parts. gate-local computes them once
(`gate_keys.py export`) and exports them as `GATE_KEY_PARTS`, bound to this tool root and toolchain dir; a child process
of that run keys with the inherited parts instead of attesting again, so a probe that fails, a browser unpacked or a
runner file rewritten mid-run never gives one run two keys for one input. A run that cannot attest shares one nonce
(one per process without the export), still never across runs (fail closed)."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

TOOL_ROOT = Path(__file__).resolve().parent.parent.parent  # the checkout whose scripts/lib this is
ENV = 'GATE_KEY_PARTS'  # D-082: the parts of the gate run this process belongs to (snapshot())
_held = []  # the process's attestation, or the exception that stopped it
_runner = []  # the process's runner digest (D-076), or the exception that stopped it
_nonce = []  # the process's part for what it cannot attest or read: one per process, never shared across runs


def attestation():
    """toolchain_manifest.attestation() of this process; raises what it raised."""
    if not _held:
        try:
            import toolchain_manifest
            _held.append(toolchain_manifest.attestation())
        except Exception as error:  # noqa: BLE001 - any failure means "not attested"; key_parts fails closed
            _held.append(error)
    if isinstance(_held[0], Exception):
        raise _held[0]
    return _held[0]


def toolchain_id():
    return attestation()['toolchain_id']


def runner_digest(root=None):
    """sha256 over (path, content digest) of the tool root's tracked files that gate.content_runner_inputs names."""
    import config
    from gate_areas import glob_match
    root = Path(root) if root is not None else TOOL_ROOT
    globs = config.get('gate.content_runner_inputs')
    listed = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True, check=True).stdout
    digest = hashlib.sha256()
    for name in sorted(item.decode() for item in listed.split(b'\0') if item):
        if any(glob_match(name, pattern) for pattern in globs):
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise OSError(f'{name} is not a regular file')
            digest.update(f'{name}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\0'.encode())
    return digest.hexdigest()


def runner_id():
    """runner_digest() of this tooling, once per process; raises what it raised."""
    if not _runner:
        try:
            _runner.append(runner_digest())
        except Exception as error:  # noqa: BLE001 - any failure means "unknown runner"; key_parts fails closed
            _runner.append(error)
    if isinstance(_runner[0], Exception):
        raise _runner[0]
    return _runner[0]


def nonce():
    if not _nonce:
        _nonce.append(uuid.uuid4().hex)
    return _nonce[0]


def computed_parts():
    """The parts this process attests and reads itself, never inherited."""
    try:
        parts = ['toolchain', toolchain_id()]
    except Exception:  # noqa: BLE001 - see attestation()
        parts = ['toolchain', 'unattested', nonce()]
    try:
        return [*parts, 'runner', runner_id()]
    except Exception:  # noqa: BLE001 - see runner_id()
        return [*parts, 'runner', 'unknown', nonce()]


def binding():
    """What an exported snapshot is valid for: this tool root and this toolchain dir."""
    import toolchain_manifest
    return {'root': str(TOOL_ROOT), 'toolchain_dir': str(toolchain_manifest.toolchain_dir())}


def inherited(environ=None):
    """The parts exported by the gate run this process belongs to, or None: unset, malformed, or bound to another tool
    root or toolchain dir (a nested run of other tooling attests for itself)."""
    raw = (os.environ if environ is None else environ).get(ENV)
    if not raw:
        return None
    try:
        held = json.loads(raw)
        bound = binding()
    except Exception:  # noqa: BLE001 - an unreadable snapshot is ignored: the process attests for itself
        return None
    parts = held.get('parts') if isinstance(held, dict) else None
    if (not isinstance(parts, list) or not parts or not all(isinstance(part, str) and part for part in parts)
            or any(held.get(name) != value for name, value in bound.items())):
        return None
    return list(parts)


def key_parts():
    found = inherited()
    return found if found is not None else computed_parts()


def snapshot():
    """The JSON text gate-local exports as ENV once per run: computed_parts() bound to this tool root and toolchain dir."""
    return json.dumps({**binding(), 'parts': computed_parts()}, sort_keys=True, separators=(',', ':'))


def reset():
    _held.clear()
    _runner.clear()
    _nonce.clear()


if __name__ == '__main__':
    if sys.argv[1:] != ['export']:
        sys.exit('usage: gate_keys.py export  (prints the GATE_KEY_PARTS snapshot of this tool root)')
    print(snapshot())
