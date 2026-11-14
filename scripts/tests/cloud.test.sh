#!/usr/bin/env bash
# The cloud machine setup (engine-cloud, U4): registered values wired into scripts/cloud, hermetic, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_cloud.py"
