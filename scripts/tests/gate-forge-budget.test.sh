#!/usr/bin/env bash
# GX-FIX-forge-rate-2 (D-070): a gate run's GitHub reads and writes are bounded and independent of the script tests; the
# script-tests stage makes none; a rate limit is waited out. Loopback REST fake, fake clock; no network, no real sleep.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "$root/scripts/tests/test_gate_forge_budget.py"
