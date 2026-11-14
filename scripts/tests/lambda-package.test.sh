#!/usr/bin/env bash
# The zip packages of the port's Lambdas and the stack that reads them (DEP8). Hermetic, no network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_lambda_package.py'
