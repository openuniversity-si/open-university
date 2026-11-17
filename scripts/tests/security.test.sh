#!/usr/bin/env bash
# Segurança, the 17th system (D-321): the SSDF's practices as controls with their applicability (implemented, partial, a gap or not applicable), the bug bar's deadlines for the repository's own vulnerabilities, the threat models of the architecture and the risks with their treatment. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_security.py"
