#!/usr/bin/env bash
# The factory's AWS infrastructure (engine-infra-aws, D-303): the declared budget and the templates, hermetic, no AWS call.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_aws.py"
