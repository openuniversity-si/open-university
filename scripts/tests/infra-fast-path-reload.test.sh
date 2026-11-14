#!/usr/bin/env bash
# FAST-PATH-RELOAD: a code-only merge's deploy build asks the live service to load the head's bundle in place
# (last-build.reload); the look orders the service alone, the service proves its reload by its own good ticks (or says
# failed and goes back), and the look writes deploy.live_code; the port hears the build start. Hermetic.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_fast_path_reload.py'
