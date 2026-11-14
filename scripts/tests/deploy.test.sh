#!/usr/bin/env bash
# The session's deploy (DEP1): infra/aws/deploy.sh with a stubbed aws/docker, GET /v1/deploy/status in process, scripts/deploy
# against a fake doorbell and a fake port, and the bootstrap's buildspec. Hermetic, no AWS call.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
# DEPLOY-SH-OWN-MODULE: the status, the CLI, the smoke, the stacks' order; deploy-slow-{a,b,c}.test.sh run test_deploy_sh.py
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_deploy.py"
