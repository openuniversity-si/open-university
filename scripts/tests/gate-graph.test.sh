#!/usr/bin/env bash
# GS1: the stage graph is sound, covers the dev plan, and its runner is deterministic and bounded. Hermetic.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
python3 "$here/test_gate_graph.py"
python3 "$here/../lib/gate_graph.py" check
