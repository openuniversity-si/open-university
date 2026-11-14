#!/usr/bin/env bash
# Uid assumptions of the delivery tail, including a real uid-0 process.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
exec python3 "$root/scripts/tests/test_root_identity.py"
