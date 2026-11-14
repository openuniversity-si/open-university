#!/usr/bin/env bash
# D-064 (f), Daniel 2026-10-26 14:22: every gate run has a wall-clock ceiling (gate.ceiling_s, registry, D-068).
# An overrun prints each stage's time and is an item to fix before the next front; it never fails the gate.
# Wall clocks can jump during long runs; elapsed time must use the same monotonic clock throughout.
# The registry holds seconds; the gate measures milliseconds, so the conversion is explicit here (D-069 item 3).
# The ceiling is a registry value: it reads the file store whatever the caller's OU_CONFIG_STORE (VAZÃO F25): this
# library is sourced before gate-local pins the store, and a remote store outage must not reach the gate's own ceiling.
GATE_CEILING_MS="${GATE_CEILING_MS:-$(( $(OU_CONFIG_STORE=file "${OU_PYTHON:-python3}" "$(dirname "${BASH_SOURCE[0]}")/config.py" get gate.ceiling_s) * 1000 ))}"
gate_now_ms() {
  # The Linux boot clock is monotonic. Reading it with bash avoids an interpreter per stage timestamp.
  local stamp seconds fraction
  read -r stamp _ </proc/uptime || return
  seconds="${stamp%.*}"; fraction="${stamp#*.}000"
  printf '%s\n' "$((10#$seconds * 1000 + 10#${fraction:0:3}))"
}
# GATE-SPEED: the run's start on the wall clock (epoch ms), for the proof's cost (gate_proof.bind compares it with its own
# epoch clock); gate_now_ms stays the monotonic clock of the budget. The proof read the monotonic start and its
# wall_s and queue_wait_s held about 1.79e9 s (an epoch), not durations.
gate_epoch_ms() {
  local stamp="$EPOCHREALTIME" fraction
  fraction="${stamp#*.}000"
  printf '%s%s\n' "${stamp%.*}" "${fraction:0:3}"
}
# gate_budget_report ELAPSED_MS NIGHTLY [STAGE_DIR]. STAGE_DIR holds the *.stage.json files (default $logs).
gate_budget_report() {
  local elapsed="$1" stages="${3:-${logs:-}}" ceiling="$GATE_CEILING_MS"
  printf 'GATE TOTAL: %d.%03ds (ceiling %ds, D-064 f)\n' "$((elapsed / 1000))" "$((elapsed % 1000))" "$((ceiling / 1000))"
  if [[ $elapsed -le $ceiling ]]; then
    return 0
  fi
  {
    printf '!!! GATE CEILING EXCEEDED: %d.%03ds > %ds (D-064 f). Fix this before the next front goes on. !!!\n' \
      "$((elapsed / 1000))" "$((elapsed % 1000))" "$((ceiling / 1000))"
    if [[ -n "$stages" && -d "$stages" ]]; then
      "${OU_PYTHON:-python3}" - "$stages" <<'PY' || true
import json, sys
from pathlib import Path
rows = []
for path in Path(sys.argv[1]).glob('*.stage.json'):
    try:
        data = json.loads(path.read_text())
        rows.append((float(data['seconds']), str(data['name'])))
    except (OSError, ValueError, KeyError, TypeError):
        continue
for seconds, name in sorted(rows, reverse=True):
    print(f'!!!   {seconds:8.3f}s  {name}')
if not rows:
    print('!!!   (no stage timings recorded)')
PY
    else
      echo '!!!   (no stage timings recorded)'
    fi
  } >&2
}
