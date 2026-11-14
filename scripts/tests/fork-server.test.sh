#!/usr/bin/env bash
# GATE-SPEED F4 (D-122): a fork of the warm server is the process python3 would have been. Hermetic: a private server.
set -euo pipefail
"${OU_PYTHON:-python3}" "$(dirname "$0")/test_fork_server.py"
