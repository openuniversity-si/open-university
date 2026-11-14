#!/usr/bin/env bash
# gate-local hook `tier` (GX-38, D-070): called once the arguments are parsed, before the mode is resolved.
# GX-11 (D-B5): the tier is derived from the invocation (gate_tier.py derive, gate-tier.battery, per_pr, batch, working_tree:
# --tier3 the battery, --pr the per-PR gate, --sha without --pr the train's batch, else the working tree) and exported
# as OU_GATE_TIER (<tier>@<this tooling's scripts/lib>: another checkout ignores it) for every stage. The train and battery commands stay as they are. A tier that cannot be derived
# stops the gate (setup error): no run goes on with an unknown tier.
gate_hook_tier() {
  local lib tier rc
  lib="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  tier="$(env OU_CONFIG_STORE=file "${py:-python3}" "$lib/gate_tier.py" derive "${pr:-}" "${sha:-}" "${tier3:-0}")" ||
    { rc=$?; echo "gate tier: cannot derive the tier (scripts/lib/gate_tier.py derive)" >&2; exit "$rc"; }
  export OU_GATE_TIER="$tier"
}
