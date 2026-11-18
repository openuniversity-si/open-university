#!/usr/bin/env bash
# DEPLOY-FILES: the deploy's own files (the stack templates, the parameters) read as files, apart from the six slow parts
# that run deploy.sh on a fixture repository. Hermetic, no AWS call.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_deploy_files.py"
