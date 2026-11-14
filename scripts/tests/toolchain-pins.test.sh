#!/usr/bin/env bash
# Toolchain pins in the registry, checksums-only manifest (D-069 item 12). No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_toolchain_pins.py"
