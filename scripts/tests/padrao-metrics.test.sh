#!/usr/bin/env bash
# Measures the PADRAO-DEV panel: the gate selection's completeness, from strace traces of the script tests: the code files each test opens that its covers does not name. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_padrao_metrics.py"
