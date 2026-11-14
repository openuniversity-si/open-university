#!/usr/bin/env bash
# The session executor by API (engine-infra-service, D-310, D-311): one call to a model's API runs as a session through
# a common layer and one dialect per API shape, each against a stand-in for its API. No network, no database.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_infra_api.py"
