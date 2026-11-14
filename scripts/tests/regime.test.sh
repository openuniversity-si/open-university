#!/usr/bin/env bash
# The exception regime (D-260): lifted(lock), lift(), the lock.lifted event and the kept locks. Hermetic: an in-memory event port.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_regime.py"
