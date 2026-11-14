#!/usr/bin/env bash
# The flaky-test quarantine (plan v3 M7): in-memory forge log, fixture unit manifests, injected clock. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_quarantine.py"
