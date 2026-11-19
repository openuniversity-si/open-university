#!/usr/bin/env bash
# The session's deploy (DEP1), the post-deploy smoke's other half (test_deploy.py SmokeTests, DEPLOY-PY-PARTS): scripts/deploy-smoke
# against a fake port on 127.0.0.1; deploy.test.sh runs the rest of the module. Hermetic, no AWS call.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
DEPLOY_PY_SHARD=smoke PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_deploy.py"
