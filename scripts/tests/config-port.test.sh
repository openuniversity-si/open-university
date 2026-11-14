#!/usr/bin/env bash
# DEP9 step 2: scripts/config through the port, the webhook consumer's rules from the table, config_version, scripts/config-latency. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_config_port.py'
