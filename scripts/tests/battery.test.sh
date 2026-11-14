#!/usr/bin/env bash
# The battery role (plan v3 M6): tier 3 on integration.advanced with a fake forge, a fake tier-3 runner and an injected
# clock. No network, no real gate.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_battery.py"
