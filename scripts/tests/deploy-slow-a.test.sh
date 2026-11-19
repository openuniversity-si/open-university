#!/usr/bin/env bash
# The session's deploy (DEP1), the tests that run infra/aws/deploy.sh (test_deploy_sh.py: DeployShTests and SlowPathShTests), part a:
# filled by its tests' seconds (DEPLOY-SHARDS-BY-SECONDS). DEPLOY-TEST-SHARDS, DEPLOY-COVERS-SPLIT: these eight parts, each on a slot of its own, are
# selected by the deploy's own files. Hermetic, no AWS call.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
DEPLOY_TEST_SHARD=slow-a PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_deploy_sh.py"
