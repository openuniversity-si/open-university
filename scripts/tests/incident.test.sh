#!/usr/bin/env bash
# Opens, lists and closes incidents: each refusal and each stop is one record with its case, class and design fix (D-231). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_incident.py"
