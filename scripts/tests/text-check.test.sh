#!/usr/bin/env bash
# The user-facing text check (D-069 item 15, L1): x-text registry entries and the visible strings of migrated files. Hermetic: temp dirs.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
for test in "$root"/scripts/tests/test_text_check*.py; do
  PYTHONDONTWRITEBYTECODE=1 python3 "$test"
done
