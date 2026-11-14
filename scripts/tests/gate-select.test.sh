#!/usr/bin/env bash
# GS1: per-unit selection (fail closed). Hermetic.
# OU-DECOUPLE F5 (D-113): the wiring into the web stages (gate_scope in gate-fixed.sh) left with Open University.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
python3 "$here/test_gate_select.py"
echo "gate-select: ok"
