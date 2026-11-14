#!/usr/bin/env bash
# The engine configuration registry (D-068): the schema language, the registry, the API and its gate check. No network.
# The one test that reads every module for undeclared registry readers is `config-readers.test.sh` (D-174): this half hits when only code moved.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
# D-076: the files run side by side, at most OU_TEST_CPUS at a time.
exec "${OU_PYTHON:-python3}" "$root/scripts/lib/parallel_tests.py" "$root"/scripts/tests/test_json_schema.py "$root"/scripts/tests/test_config.py \
  "$root"/scripts/tests/test_config_api.py "$root"/scripts/tests/test_config_check.py
