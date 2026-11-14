#!/usr/bin/env bash
# GX-25: per-stage quantiles, critical path and the ETA error of the gate timing report. Hermetic.
set -euo pipefail
python3 "$(dirname "$0")/test_gate_timing_report.py"
