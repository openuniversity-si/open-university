#!/usr/bin/env bash
# The pre-push check (TX01, T9): the inventory with its fixes, the owning script tests within the budget, the open-PR
# overlap from fixture PR heads, and the exit codes of --hook and of .githooks/pre-push. Fixture repositories, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$root/scripts/tests/test_prepush.py"
# GATE-SPEED (D-091): the machine's record refs skip the hook's checks; every other push runs them.
PYTHONDONTWRITEBYTECODE=1 "${OU_PYTHON:-python3}" "$root/scripts/tests/test_machine_refs.py"
