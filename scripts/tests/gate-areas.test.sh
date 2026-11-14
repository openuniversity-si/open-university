#!/usr/bin/env bash
set -euo pipefail
for test in "$(dirname "$0")"/test_gate_areas*.py "$(dirname "$0")"/test_gate_plan*.py; do
  python3 "$test"
done
