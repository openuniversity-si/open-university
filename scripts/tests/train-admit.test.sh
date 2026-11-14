#!/usr/bin/env bash
# Verdict admission (D-075): train_admit.admissible, one refusal per condition. Pure, no git, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_train_admit.py"
