#!/usr/bin/env bash
# FAST-ON-LANDED: the landing the Origin-era delivery records (POST /v1/deploy/landed, port.deploy_landed, D-316) and the
# fast targets the autodeploy reads from it. ORPHAN-TESTS (the Torre, 16/11): test_orphans found it run by no wrapper.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_fast_on_landed*.py; do
  [ -e "$test" ] || continue
  PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$test"
done
