#!/usr/bin/env bash
# The rule register and scripts/rule (RULE-AUDIT): fixture registers in a temp dir, plus a smoke run of every subcommand
# on this checkout. Local files only: the configuration store is the checkout's local log, never the forge. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
OU_CONFIG_STORE=file PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_rule_registry.py"
