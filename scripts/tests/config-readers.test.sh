#!/usr/bin/env bash
# Every registry key a module reads is declared in that key's x-readers (D-153): the one test of the configuration registry that
# reads the whole tree, apart from the rest (D-174) so that its wide covers do not make the others miss.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec "${OU_PYTHON:-python3}" "$root/scripts/tests/test_config_registry_readers.py"
