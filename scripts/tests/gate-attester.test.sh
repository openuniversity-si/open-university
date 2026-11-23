#!/usr/bin/env bash
# tower-gate-attester (THREAT-gate, C7, D-359 Salto 2): the AWS verifier of tower/gate-attested, its stack and its App
# manifest. Hermetic (no network; openssl, when present, checks the RS256 signature).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_gate_attester.py"
