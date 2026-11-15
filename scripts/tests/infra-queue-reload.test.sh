#!/usr/bin/env bash
# QUEUE-RELOAD: the merge queue's merge_group job rings prepare and landed; the port records the words; the service prepares
# a code-only merge's bundle with last-sha's classifier and bundler, and at its landing (main checked, its parent deployed)
# orders the service alone to reload it. Hermetic: a bare repository on disk as the remote.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_queue_reload.py'
