#!/usr/bin/env bash
# The uid-0 tail path, once: a real uid-0 process runs postgres, git and npm (VAZÃO F51).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
exec python3 "$root/scripts/tests/test_uid0_probe.py"
