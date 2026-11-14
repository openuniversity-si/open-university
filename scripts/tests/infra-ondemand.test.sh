#!/usr/bin/env bash
# RUNNER-ON-DEMAND: while Spot cannot place the runner, the live service runs one on Fargate on demand, and stops it when
# Spot's runner is up again. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_ondemand.py"
