#!/usr/bin/env bash
# forge_events port (D-065, M2): fake adapter, fake clock, loopback REST; branch age (D-069 item 11). No network.
# TX24: test_forge_events.py holds the fixtures; each feature is one file in forge_events/, run by glob (adding one needs no edit here).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
# D-076: the files run side by side, at most OU_TEST_CPUS at a time (scripts/lib/parallel_tests.py).
exec python3 "$root/scripts/lib/parallel_tests.py" "$root"/scripts/tests/test_forge_events.py "$root"/scripts/tests/forge_events/test_*.py "$root"/scripts/tests/test_branch_age.py "$root"/scripts/tests/test_operation_integration.py
