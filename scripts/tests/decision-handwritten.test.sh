#!/usr/bin/env bash
# No decision row written by hand in this checkout (the records are the only path, D-217). Reads the live table.
set -euo pipefail
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$(dirname "$0")/test_decision_handwritten_repo.py"
