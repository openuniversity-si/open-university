#!/usr/bin/env bash
# Keep the train serving: refresh the checkout, run train serve, start again after any exit. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_train_loop.py"
