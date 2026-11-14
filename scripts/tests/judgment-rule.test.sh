#!/usr/bin/env bash
# The entry documents carry D-294: the session's judgment is final; it questions only when it disagrees. Reads three files; no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_judgment_rule.py"
