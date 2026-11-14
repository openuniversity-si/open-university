#!/usr/bin/env bash
# GATE-API (D-070): scripts/gate-verdict, the gate as an API that runs the tests and returns the result. Hermetic: the
# input, the binding, the metadata check and the run are faked; the record store and the reports are temporary.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "$here/test_gate_verdict.py"
