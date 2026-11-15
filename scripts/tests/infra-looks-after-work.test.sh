#!/usr/bin/env bash
# LOOKS-AFTER-WORK: a process the role waits for makes the autodeploy's look, and its AWS clients, in
# their own threads after its first work; any other process makes them before it goes on, as before. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_looks_after_work.py'
