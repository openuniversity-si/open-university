#!/usr/bin/env bash
# The DNS of openuniversity.si (D-323 step 3): the BIND export to the record list, the Route 53 stack and the compare.
# Hermetic: a sample export with fake values, temporary files, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_dns_zone.py"
