#!/usr/bin/env bash
# The program coordinator (D-069 CO1): decision function, launch adapter, program gate and retro. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_coordinator*.py "$root"/scripts/tests/test_program_gate*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
