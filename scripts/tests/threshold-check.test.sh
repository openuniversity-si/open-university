#!/usr/bin/env bash
# The threshold check on fixture repositories (its own wrapper since structure-check.test.sh ran it with five other files). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec python3 "$root/scripts/lib/parallel_tests.py" "$root"/scripts/tests/test_threshold_check*.py
