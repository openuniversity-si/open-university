#!/usr/bin/env bash
# forge_git_ref (GX-FIX-train-lock, D-070): lock refs over the git protocol and the GitHub adapter's lock on them;
# a local bare repository is the remote, the fake forge refuses REST git-data writes. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 python3 "$root/scripts/tests/test_forge_git_ref.py"
# GATE-SPEED (D-092): the batched, sha-keyed reader of a commit's files.
PYTHONDONTWRITEBYTECODE=1 python3 "$root/scripts/tests/test_git_objects.py"
