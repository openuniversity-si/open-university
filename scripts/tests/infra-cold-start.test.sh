#!/usr/bin/env bash
# PORT2: the port's cold start: the handler module loads without boto3, botocore, psycopg, urllib.request or http.client,
# within its time budget; a refused delivery touches no database. No network, no database. COLD-START-GREEN: the test
# had no runner (no gate ran it) while tower_infra.checks brought urllib.request into the handler's load.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_cold_start.py"
