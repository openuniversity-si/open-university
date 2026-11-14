#!/usr/bin/env bash
# Hook exit (GX-19): owned by report and build-cache eviction.
set -uo pipefail
# shellcheck source=scripts/tests/gate-local/setup.sh
source "$(dirname "$0")/setup.sh"
# GX-19: the exit hook is the eviction call; without a tool_root it does nothing and never fails the exit trap.
# shellcheck disable=SC2016 # the child shell expands its own $1
check "hook exit calls gate_gc.py collect and is a no-op without a tool_root" bash -c 'source "$1"; grep -q "gate_gc.py\" collect" "$1" && (unset tool_root; gate_hook_exit)' _ "$root/scripts/lib/gate-hooks/exit.sh"
# GATE-GC-CHEIO: the folder bound is told what is live: this run's own sha, the lock, and the advisory run's own folder.
# shellcheck disable=SC2016,SC2034 # the child shell expands its own variables; py, sha, lock and report_only are read by the hook
check "hook exit names its own sha, the lock and the advisory folder to gate_gc.py" bash -c 'source "$1"
  out=$(mktemp); fake() { printf "%s\n" "$@" >"$out"; }; py=fake tool_root=/x record_dir=/r cache=/c report_only=1
  sha=$(printf "" | sha1sum); sha=${sha%% *}; lock=/l/gate.lock; gate_hook_exit
  grep -qx -- --report-only "$out" && grep -A1 -x -- --live-sha "$out" | grep -qx "$sha" &&
    grep -A1 -x -- --lock "$out" | grep -qx "$lock"' _ "$root/scripts/lib/gate-hooks/exit.sh"
check_done
