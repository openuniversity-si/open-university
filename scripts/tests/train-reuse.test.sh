#!/usr/bin/env bash
# Tier-2 reuse of exactly-matching attested proofs (GX-31) on a temporary bare repository and in-memory forges. No network.
# F121: each test builds its own repository (~0.4 s), so the classes run in two processes at once, balanced by tests.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
run() { python3 "$root/scripts/tests/test_train_reuse.py" "$@"; }
run OneByteChange ToolingVersion Switch & first=$!
run ExactMatch FailClosed BoxLocal & second=$!
status=0
wait "$first" || status=1
wait "$second" || status=1
exit "$status"
