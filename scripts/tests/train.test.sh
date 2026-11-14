#!/usr/bin/env bash
# The merge train v0 (plan v3 M3) on a temporary bare repository, a fake forge and an injected clock. No network.
# TX24: test_train.py holds the fixtures; each feature is one file in train/, run by glob (adding one needs no edit here).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
# D-076: the files run side by side, at most OU_TEST_CPUS at a time (scripts/lib/parallel_tests.py).
exec python3 "$root/scripts/lib/parallel_tests.py" "$root"/scripts/tests/test_train.py "$root"/scripts/tests/train/test_*.py
