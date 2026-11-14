#!/usr/bin/env bash
# structure-check, idea-to-prod, the ship-verify fit-review refusal on fixture repositories. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
# D-076: the files run side by side, at most OU_TEST_CPUS at a time (scripts/lib/parallel_tests.py).
exec python3 "$root/scripts/lib/parallel_tests.py" "$root"/scripts/tests/test_structure.py
