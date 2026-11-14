#!/usr/bin/env bash
# ENGINE-REPO: the engine's repository on its forge from configuration (tower_infra.engine). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_engine_repo.py"
