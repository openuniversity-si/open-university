#!/usr/bin/env bash
# The schema compat stage (D-069 item 2, P-07): contract shape, additive change, succession and retirement. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$root/scripts/tests/test_schema_compat.py"
"$root/scripts/schema-compat" --root "$root" >/dev/null
