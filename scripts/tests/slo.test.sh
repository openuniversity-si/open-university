#!/usr/bin/env bash
# SLO registry, slo.breached, reader and dashboard (O1, D-069 item 6): fixture logs, injected clock. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_slo.py"
