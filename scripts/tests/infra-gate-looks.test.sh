#!/usr/bin/env bash
# GATE-SHUTDOWN follow-up: the service starts the AWS gate's looks, warms the forge's key and refreshes its webhook keys
# only under service.gate_looks (default false); the deploy's, the drills' and the prune's looks always. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_gate_looks.py'
