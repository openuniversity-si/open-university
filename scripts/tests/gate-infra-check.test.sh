#!/usr/bin/env bash
# F37-INFRA-CHECK (D-313): the infra judge publishes tower/gate before the landing; hermetic, no network, no database.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_gate_infra_check.py"
