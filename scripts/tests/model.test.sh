#!/usr/bin/env bash
# The engineering model (PADRAO-DEV): reads the objects of every system against the metamodel in config/model/, checks types, states and links, shows one object with its links, and measures the end-to-end chain, the requirement inventory and each system's conformance. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_model.py"
