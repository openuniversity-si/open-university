#!/usr/bin/env bash
# The AGENT-ENV client (D-341): fetch, refusal, quoting and mode 600 against a local stub on 127.0.0.1, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_agent_env_client.py"
