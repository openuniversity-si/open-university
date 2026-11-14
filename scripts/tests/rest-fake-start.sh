#!/usr/bin/env bash
# Sourced by script suites (HD1): start scripts/tests/rest_fake.py and wait for its readiness probe, never a fixed count.
# rest_fake_start <api dir> <port file> sets server_pid and rest_fake_port; it returns 1 with "rest fake did not start".
rest_fake_start() {
  local here py="${OU_PYTHON:-python3}"
  here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  "$py" "$here/rest_fake.py" --dir "$1" --port-file "$2" &
  server_pid=$!
  # shellcheck disable=SC2034 # output for the sourcing suite (see the header), not unused
  rest_fake_port=$("$py" "$here/rest_fake.py" --wait-ready --port-file "$2" --pid "$server_pid") ||
    { echo "rest fake did not start" >&2; return 1; }
}
