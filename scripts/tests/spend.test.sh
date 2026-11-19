#!/usr/bin/env bash
# The AWS spend as a validation source (D-331): the snapshot recorded from the deploy build's daily Cost Explorer reading (last-build.spend, through the port's status) and the aws-spend measure scripts/model judges VAL-aws-200 by. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_spend.py"
