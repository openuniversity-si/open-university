#!/usr/bin/env bash
# D-260: the gate lock (the bypass and the train's tier 2) asks the exception regime, on both sides. Fixtures only.
set -euo pipefail
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$(dirname "$0")/test_gate_regime_lock.py"
