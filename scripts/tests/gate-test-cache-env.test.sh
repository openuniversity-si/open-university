#!/usr/bin/env bash
# TX10 (T6): each script test runs with a private TMPDIR and without the gate's own variables. Hermetic: temp repos.
set -euo pipefail
python3 "$(dirname "$0")/test_gate_test_cache_env.py"
