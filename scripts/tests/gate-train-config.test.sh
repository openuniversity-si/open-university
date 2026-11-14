#!/usr/bin/env bash
# The gate and the train as the default configuration of our management (engine-gate-infra, GATE-INFRA 1): no rule of
# ARQUITETURA-ALVO §7 missing, each mechanism one the infrastructure has. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_gate_train_config.py"
