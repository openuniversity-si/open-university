#!/usr/bin/env bash
# The toolchain download retries and the install lock (RUNNER-SETUP-RESILIENCE). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_toolchain_download.py"
