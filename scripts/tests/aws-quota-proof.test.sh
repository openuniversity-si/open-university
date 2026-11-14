#!/usr/bin/env bash
# The live proof of the quota that resets (AWS12) against a stand-in port: held waiting, resumed, capped. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_aws_quota_proof.py"
