#!/usr/bin/env bash
# LAMBDA-PRUNE (the review's finding 26): the port Lambdas' old versions and the unnamed old packages deleted once a day.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_prune.py"
