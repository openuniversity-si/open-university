#!/usr/bin/env bash
# D-285 C4: local fixture proofs of the declared configuration boundary.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec "${OU_PYTHON:-python3}" "$root/scripts/tests/test_operation_config.py"
