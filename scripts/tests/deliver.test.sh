#!/usr/bin/env bash
# Deliver a PR in one call: the gate on the exact head, the merge with --expect-head, the base refreshed and PR/s printed. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_deliver.py"
