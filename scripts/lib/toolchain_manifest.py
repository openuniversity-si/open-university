"""Pinned tail toolchain (D-069 item 12). Versions live only in the config registry (config/registry/toolchain.json);
scripts/cloud/toolchain.json keeps the checksums of each pinned version, keyed by the registry's version.

scripts/env-check compares the installed tools with these registered pins (D-027). The package update policy
left with the retired product's environment checks (VAZÃO F13, D-111, D-292).
"""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

import config

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'scripts' / 'cloud' / 'toolchain.json'
# The Vercel CLI and gh left (vazão F6): the engine runs neither (AGENTS.md, github_cli), and Vercel's production is
# Open University's, which left the repository (D-105, D-111). pnpm left too (vazão F16, D-292): the engine has no
# package to install, so no file of it runs pnpm. Node stays: control-plane.test.sh runs `node --test`.
TOOLS = ('python', 'node', 'gitleaks', 'postgres')


def toolchain_dir():
    override = os.environ.get('OU_TOOLCHAIN_DIR')
    return Path(override) if override else ROOT / '.toolchain'


def versions():
    """The pinned version of every tool, read from the registry. The key of its checksums is `checksum_key`."""
    return {
        'python': config.get('toolchain.python_version'), 'node': config.get('toolchain.node_version'),
        'gitleaks': config.get('toolchain.gitleaks_version'), 'postgres': config.get('toolchain.postgres_version'),
    }


def checksum_key(tool, pinned=None, tag=None, revision=None):
    """python is keyed by `<version>+<release tag>`, postgres by its binaries revision, every other tool by its version.
    A caller that already read the pins passes them: each registry read replays the change store."""
    pinned = pinned or versions()
    if tool == 'python':
        return f"{pinned['python']}+{tag or config.get('toolchain.python_release_tag')}"
    if tool == 'postgres':
        return revision or config.get('toolchain.postgres_revision')
    return pinned[tool]


def load():
    """Each tool of TOOLS as {version, ...checksums} with the version from the registry, plus the "environment"
    section; any other entry is not a tool and is left out. A pin without checksums is refused."""
    raw = json.loads(MANIFEST.read_text())
    if not isinstance(raw, dict):
        raise RuntimeError('toolchain manifest is not an object')
    data = {key: raw[key] for key in ('environment',) if key in raw}
    pinned = versions()
    tag = config.get('toolchain.python_release_tag')
    revision = config.get('toolchain.postgres_revision')
    for tool in TOOLS:
        spec = {'version': pinned[tool]}
        key = checksum_key(tool, pinned, tag, revision)
        for field, by_key in (raw.get(tool) or {}).items():
            if key not in by_key:
                raise RuntimeError(f'toolchain: no {field} for {tool} {key} in scripts/cloud/toolchain.json')
            spec[field] = by_key[key]
        if tool == 'python':
            spec['tag'] = tag
        if tool == 'postgres':
            spec['revision'] = revision
        data[tool] = spec
    return data


def machine():
    name = platform.machine()
    if name in ('x86_64', 'amd64'):
        return 'x86_64'
    if name in ('aarch64', 'arm64'):
        return 'aarch64'
    raise RuntimeError(f'unsupported architecture: {name}')


def install_id():
    """The installed tools only: the "environment" section (D-027) never forces a reinstall."""
    data = load()
    tools = json.dumps({name: data[name] for name in TOOLS}, sort_keys=True).encode()
    return hashlib.sha256(tools + b'\n' + machine().encode()).hexdigest()


ATTEST_MEMO = 'attest.json'  # observed versions by binary identity, in the toolchain dir; never install.stamp
ABSENT = 'absent'  # the observed version of a tool that is not installed or does not run


def _identity(path):
    """What a reinstall or a hand-replaced binary changes: the resolved path, size, mtime_ns and inode."""
    try:
        resolved = os.path.realpath(path)
        info = os.stat(resolved)
    except OSError:
        return None
    return [resolved, info.st_size, info.st_mtime_ns, info.st_ino]


def _read_memo(root):
    try:
        memo = json.loads((Path(root) / ATTEST_MEMO).read_text())
    except (OSError, ValueError):
        return {}
    return memo if isinstance(memo, dict) else {}


def _write_memo(root, memo):
    """Best effort and atomic: a read-only toolchain dir only costs the probes again."""
    path = Path(root) / ATTEST_MEMO
    try:
        tmp = path.with_name(f'{ATTEST_MEMO}.{os.getpid()}.tmp')
        tmp.write_text(json.dumps(memo, sort_keys=True))
        os.replace(tmp, path)
    except OSError:
        pass


def observed_versions(root=None, tools=None, probe=None):
    """{tool: version} as the installed binaries report it (`toolchain.observed_tools`), `absent` for one missing or
    failing. A probe is reused only while the binary keeps its identity (`_identity`); the install stamp is never read.
    `probe(tool, root)` defaults to `observed_version`."""
    root = Path(root) if root else toolchain_dir()
    probe = probe or observed_version
    tools = tools if tools is not None else config.get('toolchain.observed_tools')
    memo, seen, changed = _read_memo(root), {}, False
    for tool in tools:
        if tool not in TOOLS:
            raise RuntimeError(f'toolchain.observed_tools: unknown tool {tool}')
        identity = _identity(Path(root) / 'bin' / binary_name(tool))
        held = memo.get(tool)
        if identity is None:
            seen[tool] = ABSENT
        elif isinstance(held, dict) and held.get('identity') == identity and isinstance(held.get('version'), str):
            seen[tool] = held['version']
        else:
            try:
                seen[tool] = probe(tool, root) or ABSENT
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                seen[tool] = ABSENT
            memo[tool], changed = {'identity': identity, 'version': seen[tool]}, True
    if changed:
        _write_memo(root, memo)
    return seen


def registry_digest():
    """sha256 of every registered parameter's committed default (TOOLCHAIN-ATTEST-STORE, D-080): the identity hashes
    the head's inputs, never the change store a process reads, so the gate (file store) and the train (shared store)
    attest one id for one head. A store override still acts on behaviour; it is not toolchain identity."""
    values = {name: item.get('default') for _, document in config.files().values()
              for name, item in document['properties'].items()}
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def attestation(root=None):
    """The attested toolchain: what is installed and the committed registry, never the stamp's cached answer.
    toolchain_id = sha256 of canonical JSON {install: install_id(), machine, observed: observed_versions, registry:
    registry_digest}. A stale `.toolchain`, a missing tool or a committed tooling change gives another id."""
    observed, registry = observed_versions(root), registry_digest()
    body = {'install': install_id(), 'machine': machine(), 'observed': observed, 'registry': registry}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'toolchain_id': digest, 'observed_versions': observed, 'registry_digest': registry}


def _vendor_arch(kind):
    arch = machine()
    if kind == 'python':
        return arch
    return 'x64' if arch == 'x86_64' else 'arm64'


def artifact(name, data=None):
    """Public URL, checksum, and archive kind for one tool on this machine. A caller that resolves several tools
    passes one `load()`: each load reads the registry again."""
    spec = (data or load())[name]
    arch = machine()
    digest = spec['sha256'][arch]
    vendor = _vendor_arch(name)
    if name == 'python':
        version, tag = spec['version'], spec['tag']
        filename = f'cpython-{version}+{tag}-{vendor}-unknown-linux-gnu-install_only.tar.gz'
        url = 'https://github.com/astral-sh/python-build-standalone/releases/download/' + tag + '/' + filename
        kind = 'gz'
    elif name == 'node':
        version = spec['version']
        filename = f'node-v{version}-linux-{vendor}.tar.xz'
        url = f'https://nodejs.org/dist/v{version}/{filename}'
        kind = 'xz'
    elif name == 'gitleaks':
        version = spec['version']
        url = f'https://github.com/gitleaks/gitleaks/releases/download/v{version}/gitleaks_{version}_linux_{vendor}.tar.gz'
        kind = 'gz'
    elif name == 'postgres':
        revision = spec['revision']
        filename = f'postgresql-{revision}-{arch}-unknown-linux-gnu.tar.gz'
        url = f'https://github.com/theseus-rs/postgresql-binaries/releases/download/{revision}/{filename}'
        kind = 'gz'
    else:
        raise RuntimeError(f'unknown toolchain tool: {name}')
    return {'url': url, 'sha256': digest, 'kind': kind}


def binary_name(tool):
    if tool == 'python':
        return 'python3'
    if tool == 'postgres':
        return 'psql'
    return tool


def observed_version(tool, root):
    binary = Path(root) / 'bin' / binary_name(tool)
    if tool == 'python':
        args = [str(binary), '-c', 'import sys; print("%d.%d.%d" % sys.version_info[:3])']
    elif tool == 'node':
        args = [str(binary), '-v']
    elif tool == 'gitleaks':
        args = [str(binary), 'version']
    elif tool == 'postgres':
        args = [str(binary), '--version']
    else:
        args = [str(binary), '-v']
    env = dict(os.environ)
    env['PATH'] = str(Path(root) / 'bin') + os.pathsep + env.get('PATH', '')
    env['CI'] = env.get('CI') or '1'
    completed = subprocess.run(args, capture_output=True, text=True, env=env, check=False,
                               timeout=config.get('env.tool_version_probe_timeout_s'))
    if completed.returncode != 0:
        raise RuntimeError(tool)
    return version_of(tool, completed.stdout + '\n' + completed.stderr)


def version_of(tool, text):
    line = next((item.strip() for item in text.splitlines() if item.strip()), '')
    if tool == 'node':
        return line[1:] if line.startswith('v') else line
    if tool == 'postgres':
        # psql (PostgreSQL) 18.6
        return line.split()[-1] if line else ''
    if tool in ('gitleaks', 'python'):
        token = line.split()[-1] if line else ''
        return token[1:] if token.startswith('v') else token
    return ''
