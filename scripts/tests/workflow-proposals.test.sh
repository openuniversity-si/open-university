#!/usr/bin/env bash
# Workflow proposals (PR W, D-087, D-359): read-only live-site canary (M6), Andon main-health guard (C6),
# external GitHub App fork-attestation verifier (C7 / THREAT-gate), and staged proposal validator. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_workflow_proposals.py"
