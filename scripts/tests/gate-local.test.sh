#!/usr/bin/env bash
# Real runner, stub workloads: a failed background child must never authorize a merge. The suite is one part per
# feature in scripts/tests/gate-local/ (TX-PROGRAM, D-070): a unit adds its own part file; this runner discovers them.
set -uo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=scripts/tests/lib/suite.sh
source "$root/scripts/tests/lib/suite.sh"
suite_run gate-local "$root/scripts/tests/gate-local"
