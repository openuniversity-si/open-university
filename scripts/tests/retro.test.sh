#!/usr/bin/env bash
# RETRO-API: the session-log store, its index, ingest and receive on temp directories. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "$root/scripts/tests/test_retro.py"
