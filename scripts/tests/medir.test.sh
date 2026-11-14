#!/usr/bin/env bash
# The measures of the phase-1 path (engine-medir, P6 F1): the quantiles, the infrastructure's log page by page from a
# fake port, and the deliveries' logs. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_medir.py"
