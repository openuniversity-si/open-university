#!/usr/bin/env bash
# The Operation system's data stores and data subject requests (D-320, D-321): a data store is protected, regenerable, unverified, unprotected or unregistered (personal data without purpose, legal basis and retention), and a request is open, overdue, answered or answered late, each derived from its record. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_operation_data.py"
