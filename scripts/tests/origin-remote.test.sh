#!/usr/bin/env bash
# The session's origin is Origin (engine-cloud; Daniel 04/11 16:57 BRT): scripts/lib/origin_remote.py on a throwaway
# checkout, and its place in scripts/cloud/setup.sh. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_origin_remote.py"
