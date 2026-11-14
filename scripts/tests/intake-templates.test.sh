#!/usr/bin/env bash
# Writes docs/process/templates/ from the intake registry (D-205) Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_intake_templates.py"
