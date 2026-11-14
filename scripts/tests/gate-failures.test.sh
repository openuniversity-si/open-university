#!/usr/bin/env bash
# GS1: failing test ids and signatures, and cached tests, in the gate verdict. Hermetic.
set -euo pipefail
python3 "$(dirname "$0")/test_gate_failures.py"
