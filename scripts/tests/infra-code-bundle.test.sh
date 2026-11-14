#!/usr/bin/env bash
# IMAGE-PREWARM-B1: the service/runner boots from a code bundle named by its digest (tower_infra.code_bundle) and the gate's
# builder of that bundle (lambda_package.build_code). Hermetic: a fake store, execve stubbed, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_code_bundle.py'
