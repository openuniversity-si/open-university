#!/usr/bin/env bash
# PR-OBSERVATION, part 2: `pr metadata` judges what the live service read of the PR with the forge's key, through the
# Origin adapter's own mapping, with no credential and no reflog of the lane. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_pr_observation_judge.py"
