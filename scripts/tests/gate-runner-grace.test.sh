#!/usr/bin/env bash
# The grace of a stage past its limit (gate-runner.sh): TERM, then KILL only for a stage still alive. Hermetic: temp dirs.
set -euo pipefail
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$(dirname "$0")/test_gate_runner_grace.py"
