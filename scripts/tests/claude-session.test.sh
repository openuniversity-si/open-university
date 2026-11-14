#!/usr/bin/env bash
# Hermetic Claude Code session: no Docker, network credentials, GraphQL forbidden.
# Most of the wall is bash sourcing env.sh in subprocesses, so the module runs as three processes side by side
# (the session tests, and the proxy tests in two halves); each prints whole, the exit is 1 when any failed.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
t="$root/scripts/tests/test_claude_session.py"
n=NodeEnvProxyTests
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT
pids=()
i=0
for sel in ClaudeSessionTests \
  "$n.test_fetch_goes_through_the_proxy_silently_and_loopback_stays_direct $n.test_without_a_proxy_env_sh_sets_nothing" \
  "$n.test_lowercase_proxy_and_existing_no_proxy_are_kept $n.test_claude_env_file_lines_carry_the_names_and_never_the_proxy_url"; do
  # shellcheck disable=SC2086
  python3 "$t" $sel > "$out/$i" 2>&1 &
  pids+=($!)
  i=$((i + 1))
done
rc=0
for k in "${!pids[@]}"; do
  wait "${pids[$k]}" || rc=1
  cat "$out/$k"
done
exit "$rc"
