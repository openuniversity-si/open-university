#!/usr/bin/env bash
# Agent execution environments (AGENT-ENV, D-341): the declarations' validator, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_agent_env.py"
