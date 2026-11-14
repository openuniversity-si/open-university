#!/usr/bin/env bash
# The ack-integration probe against an injected aws runner: variant table, CLI arguments, cleanup. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_aws_ack_integration_probe.py"
