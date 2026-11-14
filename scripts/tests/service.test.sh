#!/usr/bin/env bash
# The gate and the train as services (GATE-TRAIN-SERVICES, D-086, ADR-41): status, health and metrics, the Tower runner
# and its admin controls. Fake sources, a local bare remote, no network. Each test_service*.py file runs by glob.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec python3 "$root/scripts/lib/parallel_tests.py" "$root"/scripts/tests/test_service*.py
