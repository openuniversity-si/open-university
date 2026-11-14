#!/usr/bin/env bash
# The check's environment is the same on every judge (AWS3): a sample of the heaviest and most environment-sensitive
# script tests gives the same result with the infrastructure runner's variables as without, and the gate's scrub keeps
# the Tower runner's TOWER_JOB_* out of a script test. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_runner_env.py"
