#!/usr/bin/env bash
# Configuration as data (DEP9): work.config_value, GET/PUT /v1/config, the refresh on the tower_config event. Hermetic; the SQL
# class needs TEST_DATABASE_URL (Postgres) and is skipped without it.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_config_data.py'
