#!/usr/bin/env bash
# FULL-RUN: at each landing the live service runs the base's whole battery with no cache, below the gates, and says the
# landed sha green or red. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_fullrun.py"
