"""Fast check before the delivery tail. Prints only missing names, never secret values."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

from credentials import MODES, mode
from toolchain_manifest import (
    ROOT, TOOLS, load, observed_version, observed_versions, toolchain_dir,
)

HOST_TOOLS = ('flock', 'git', 'curl')
SETUP_EXIT = 2  # a gap: the machine is not ready (scripts/cloud/preflight, the gate preflight)


def missing_tools():
    """Every tool whose installed binary does not report its pin. The answer is the observed versions (memoized by
    binary identity, GX-28), never install.stamp: a stale stamp over a replaced binary still names that tool."""
    root = toolchain_dir()
    expected = load()
    seen = observed_versions(root, TOOLS, probe=lambda tool, where: observed_version(tool, where))
    return [tool for tool in TOOLS if seen[tool] != expected[tool]['version']]


def _postgres_status():
    path = Path(__file__).resolve().parents[1] / 'cloud' / 'postgres.py'
    spec = importlib.util.spec_from_file_location('ou_cloud_postgres', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.status()


def database_problems():
    """Empty when psql is absent: missing_tools already names that. Starts the server when the binary matches."""
    root = toolchain_dir()
    binary = root / 'bin' / 'psql'
    if not binary.is_file():
        return []
    expected = load()['postgres']['version']
    try:
        got = observed_version('postgres', root)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        got = ''
    if got != expected:
        if 'postgres' in missing_tools():
            return []
        return ['missing toolchain: postgres']
    problem = _postgres_status()
    return [problem] if problem else []


def host_problems():
    return [f'missing host tool: {name}' for name in HOST_TOOLS if shutil.which(name) is None]


def _writable(path, label):
    probe = Path(path) / f'.ou-write-probe-{os.getpid()}'
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        probe.write_text('ok')
        probe.unlink()
    except OSError:
        return [f'missing writable path: {label}']
    return []


def writable_problems():
    return _writable(toolchain_dir(), '.toolchain') + _writable(Path('/tmp'), '/tmp')


def root_problems():
    """Privilege-drop and account tools. Empty when the process is not root."""
    import session_identity
    return session_identity.root_problems()


def forge_problems():
    """ORIGIN-FINISH R3: the gaps of the forge forge-events.adapter selects, never a fixed vendor's."""
    import credentials
    import forge_events
    try:
        return forge_events.forge_gaps(credentials.cached_probe)
    except Exception as error:  # an unreadable selector is itself the gap; preflight names it and goes on
        return [f'forge readiness unknown: {type(error).__name__}: {error}'.splitlines()[0]]


def problems():
    lines = []
    selected = mode()
    if selected not in MODES:
        lines.append('invalid OU_CREDENTIALS')
    lines.extend(f'missing toolchain: {name}' for name in missing_tools())
    if selected in MODES:
        lines.extend(forge_problems())
    lines.extend(database_problems())
    lines.extend(host_problems())
    lines.extend(writable_problems())
    lines.extend(root_problems())
    # One pass. A database failure and a missing drop tool can name the same gap.
    unique = []
    for item in lines:
        for line in str(item).splitlines():
            if line and line not in unique:
                unique.append(line)
    return unique


def require():
    found = problems()
    if found:
        print('\n'.join(found), file=sys.stderr)
        raise SystemExit(SETUP_EXIT)


def _toolchain_gaps():
    return [f'missing toolchain: {name}' for name in missing_tools()]


# GX-01 (D-070): what the gate needs before it takes a lock, a slot or a worktree. No credential or network probe.
GATE_PROBES = {'database': database_problems, 'toolchain': _toolchain_gaps}


def gate_problems(probes=None, without=()):
    """The gaps of the gate preflight, one line each, in probe order (env.gate_preflight_probes by default)."""
    import config
    # By root: a gate's hermetic tooling may have imported the config module of another checkout (the base-tip gate).
    chosen = config.get('env.gate_preflight_probes', ROOT) if probes is None else probes
    unique = []
    for name in chosen:
        if name in without:
            continue
        for item in GATE_PROBES[name]():
            for line in str(item).splitlines():
                if line and line not in unique:
                    unique.append(line)
    return unique


def gate_main(argv):
    """`preflight.py gate [--without PROBE]...`: each gap as `FAIL env: <gap>` and exit SETUP_EXIT, else one ok line."""
    without, words = [], iter(argv)
    for flag in words:
        name = next(words, None)
        if flag != '--without' or name not in GATE_PROBES:
            print(f'usage: preflight.py gate [--without {"|".join(GATE_PROBES)}]...', file=sys.stderr)
            return SETUP_EXIT
        without.append(name)
    found = gate_problems(without=without)
    if found:
        print('\n'.join(f'FAIL env: {line}' for line in found))
        return SETUP_EXIT
    print('gate preflight: ok')
    return 0


def main(argv=()):
    command, *rest = list(argv) or ['']
    if command == 'gate':
        return gate_main(rest)
    require()
    print('preflight: ok')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
