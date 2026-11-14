#!/usr/bin/env bash
# The census of each unit (CENSO-NO-MANIFESTO): records, fold, digest chain, ownership, writer. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$root/scripts/tests/test_census.py"
