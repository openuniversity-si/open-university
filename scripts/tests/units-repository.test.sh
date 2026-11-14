#!/usr/bin/env bash
# What the unit manifests claim in this checkout (D-064 (d), TX21): the two unit tests that read the whole tree, apart from the
# fixture tests (D-175) so that their wide covers do not make those miss.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec "${OU_PYTHON:-python3}" "$root/scripts/tests/test_repo_unit_claims.py"
