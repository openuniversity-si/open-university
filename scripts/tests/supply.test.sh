#!/usr/bin/env bash
# Fornecimento, the 16th system (D-320): the third-party components read from the files that pin them, their suppliers, the advisories of the audit snapshot, and the check that no lockfile changed after its audit and no high or critical advisory is affecting. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_supply.py"
