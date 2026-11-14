#!/usr/bin/env bash
# A gate refusal is an incident the machine writes (D-240): scripts/lib/gate_incident.py, hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_gate_incident.py"
