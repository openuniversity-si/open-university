#!/usr/bin/env bash
# Gate hygiene (GX-19): per-stage timeouts, report and build-cache retention, atomic cache publish. Hermetic: temp dirs.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_gate_gc*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
