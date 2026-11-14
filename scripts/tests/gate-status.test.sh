#!/usr/bin/env bash
# GV1: the gate status comment (render, edit in place, rate bound, call sites). Hermetic.
# TX24: test_gate_status.py holds the fixtures; each feature is one file in gate_status/, run by glob (adding one needs no edit here).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
for test in "$here"/test_gate_status.py "$here"/gate_status/test_*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
