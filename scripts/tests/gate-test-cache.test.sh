#!/usr/bin/env bash
# GS1: the per-test script cache (keys, markers, reuse, corruption, TTL). Hermetic: temp repos and temp stores.
set -euo pipefail
python3 "$(dirname "$0")/test_gate_test_cache.py"
# GATE-SPEED v8 (D-116): scripts/test-suite --metrics, the main metric and the guards of the test system.
python3 "$(dirname "$0")/test_test_metrics.py"
