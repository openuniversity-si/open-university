#!/usr/bin/env bash
# COVERS-IMPORTS: every covers manifest names the engine modules and test helpers its Python tests import. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_covers_imports.py"
