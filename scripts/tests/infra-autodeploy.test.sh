#!/usr/bin/env bash
# The autodeploy's look (AUTO1, DEP7, DEP-EVENTS): when it rings the deployer and when it does not, the ledger, the
# observation it publishes and its wiring. Hermetic: a stand-in database, an injected clock. The module is also the rig
# of other checks (fastdeploy, rollout, config-data), which import it and never ran its own tests.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 -m unittest discover -s "$root/scripts/tests" -p 'test_infra_autodeploy.py'
