#!/usr/bin/env bash
# GX-12: the gate publish rule, tier 1 and tier 2. Hermetic.
set -euo pipefail
python3 "$(dirname "$0")/test_gate_publish.py"
