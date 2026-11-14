#!/usr/bin/env bash
# The control plane (GATE-TRAIN-SERVICES, ADR-41, D-086): the Worker's logic under node --test with the pinned node, no
# network and no Cloudflare runtime (services/control-plane/src/core.js over a MemoryStore).
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
exec node --test "$root/services/control-plane/test/core.test.mjs" "$root/services/control-plane/test/events.test.mjs" \
  "$root/services/control-plane/test/origin.test.mjs" "$root/services/control-plane/test/config.test.mjs" \
  "$root/services/control-plane/test/rows.test.mjs" "$root/services/control-plane/test/checks.test.mjs"
