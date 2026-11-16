#!/usr/bin/env bash
# QUEUE-REARM: scripts/queue-wait's reading of a pull request's timeline and its head's check runs, on fixtures. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_queue_wait*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
