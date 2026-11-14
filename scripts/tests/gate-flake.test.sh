#!/usr/bin/env bash
# Flake attribution on the PR's own head (TX11) and the base class (F73): the classes, the re-runs and their fixtures. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "$root/scripts/tests/test_gate_classify_flake.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$root/scripts/tests/test_gate_classify_base.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$root/scripts/tests/test_gate_flake.py"
