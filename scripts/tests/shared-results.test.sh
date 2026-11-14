#!/usr/bin/env bash
# GATE-SPEED F10 (D-130): script test PASSes shared between boxes by their input key. Hermetic: a local bare remote.
set -euo pipefail
"${OU_PYTHON:-python3}" "$(dirname "$0")/test_shared_results.py"
