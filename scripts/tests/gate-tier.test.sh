#!/usr/bin/env bash
# GX-11 (D-070): the gate tier is explicit (gate-hooks/tier.sh, D-B5) and the caches and the KD1 switch key on it. Hermetic.
set -euo pipefail
python3 "$(dirname "$0")/test_gate_tier.py"
