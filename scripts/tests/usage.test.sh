#!/usr/bin/env bash
# What a session did, counted from its transcript: tool calls by kind and the scripts it ran (D-208). Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_usage.py"
