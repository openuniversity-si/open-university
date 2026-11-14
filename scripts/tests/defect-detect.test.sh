#!/usr/bin/env bash
# Detection of base defects in the gate (KD1): fake base runner, a real throwaway git repository, in-memory forge log. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_defect_detect.py"
