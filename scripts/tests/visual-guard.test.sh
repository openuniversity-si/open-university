#!/usr/bin/env bash
# SG1: STATUS.md and undeclared visual edits are refused (D-006, D-069): hermetic fixtures, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$root/scripts/tests/test_visual_guard.py"
