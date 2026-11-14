#!/usr/bin/env bash
# The live proof of tenant isolation (AWS-TENANT-ISOLATION-PROOF) against a stand-in port with two tenants. No network.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHONDONTWRITEBYTECODE=1 exec python3 "$root/scripts/tests/test_aws_tenant_isolation_proof.py"
