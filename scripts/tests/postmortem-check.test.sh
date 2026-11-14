#!/usr/bin/env bash
# The postmortem check on fixture trees (and the template heading). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec python3 "$root/scripts/tests/test_postmortem_check.py"
