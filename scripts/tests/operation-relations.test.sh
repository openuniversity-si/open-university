#!/usr/bin/env bash
# The observed relation of forge operations (D-285, C2): the declaration, the confrontation and the exposed unknown. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$root/scripts/tests/test_operation_relations.py"
