#!/usr/bin/env bash
# KF3 guard: a script test must not take a value from the host it runs on (CPU count, load), because the same head then
# passes on one machine and fails on another (incident: gate-heavy-db "expected [5] got [3]"). Derive it from the
# configuration registry or inject it. A line that only bounds parallelism and asserts nothing carries
# `# host-ok: <reason>`.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
exec python3 -I - <<'PY'
import pathlib, re, sys

HOST = re.compile(r'\bnproc\b|os\.cpu_count|multiprocessing\.cpu_count|_NPROCESSORS|proc/(?:cpuinfo|loadavg)|os\.getloadavg|sched_getaffinity|getconf\s+_NPROC')
MARKER = re.compile(r'host-ok:\s*\S')
bad = []
for path in sorted(pathlib.Path('scripts/tests').glob('*')):
    if path.suffix not in ('.sh', '.py') or path.name == 'hermetic-expectations.test.sh':
        continue
    for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
        if HOST.search(line) and not MARKER.search(line):
            bad.append(f'{path}:{number}: {line.strip()[:100]}')
if bad:
    print('FAIL host-dependent value in a script test (derive it from the registry, or mark a parallelism-only bound with `# host-ok: <reason>`):', file=sys.stderr)
    print('\n'.join(bad), file=sys.stderr)
    sys.exit(1)

# The guard itself must see what it forbids.
for sample in ('limit=$(nproc)', 'n = os.cpu_count()', 'getconf _NPROCESSORS_ONLN', 'os.getloadavg()'):
    assert HOST.search(sample), sample
assert MARKER.search('limit=$(nproc) # host-ok: parallelism bound only')
print('hermetic-expectations: ok')
PY
