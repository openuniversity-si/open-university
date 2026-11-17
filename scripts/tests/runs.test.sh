#!/usr/bin/env bash
# Run durations as a validation source (PADRAO-DEV F8d): the snapshot of a workflow's completed runs recorded from GitHub's API, its nearest-rank percentile, and the run-durations measure that is still measuring while the snapshot is short or stale. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_runs.py"
