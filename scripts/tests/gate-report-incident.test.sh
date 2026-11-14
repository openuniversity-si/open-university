#!/usr/bin/env bash
# D-240: a FAIL verdict of gate_report opens its gate-refusal incident in the run's logs. Hermetic: temp dirs, no forge.
set -euo pipefail
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$(dirname "$0")/test_gate_report_incident.py"
