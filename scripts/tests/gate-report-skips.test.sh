#!/usr/bin/env bash
# GK1: guard-skipped gate stages are reported apart from missing ones. GX-10: the v4 proof of the verdict. Hermetic.
set -euo pipefail
for test in "$(dirname "$0")"/test_gate_report_skips*.py "$(dirname "$0")"/test_gate_report_v4*.py; do
  python3 "$test"
done
