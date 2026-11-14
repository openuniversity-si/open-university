#!/usr/bin/env bash
# The post-deploy ACK smoke and its rollback against an injected aws runner and poster. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_ack_smoke.py"
