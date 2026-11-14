#!/usr/bin/env bash
# GATE-SPEED F11 (N6): the in-memory git answers the train fixture's commands as git does. Hermetic: temporary repositories.
set -euo pipefail
"${OU_PYTHON:-python3}" "$(dirname "$0")/test_memory_git.py"
