#!/usr/bin/env bash
# The problem space, leap 1 (D-348): the Goal Tree, the current state, the derived gap, the current reality tree and its conflict, the injections with the decision's appraisal and the strategy and tactics tree, read, derived and refused by scripts/lib/problem_space.py. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_problem.py"
