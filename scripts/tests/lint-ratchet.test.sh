#!/usr/bin/env bash
# The Python lint ratchet (PADRAO-DEV F4b): ruff over the engine's Python in the rule families of rules.lint_select, minus the rules with a legacy (rules.lint_ignored); any finding fails, and an ignored rule with no finding left must leave the list. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_lint_ratchet.py"
