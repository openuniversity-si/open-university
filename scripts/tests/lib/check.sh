# shellcheck shell=bash
# The assertions of a suite part (TX-PROGRAM, D-070; scripts/tests/lib/suite.sh). `check <name> <command...>` counts
# one assertion; `check_done` prints the part's counts, hands them to the suite runner and is the part's exit status.
# CHECK_LABEL names the suite in each FAIL line.
passed=0 failed=0
check() {
  local name="$1"; shift
  if "$@"; then passed=$((passed + 1)); else echo "FAIL ${CHECK_LABEL:-check}: $name"; failed=$((failed + 1)); fi
}
check_done() {
  if [[ -n "${SUITE_COUNTS:-}" ]]; then printf '%s %s\n' "$passed" "$failed" >"$SUITE_COUNTS"; fi
  echo "${CHECK_LABEL:-check} $(basename "$0" .test.sh): $passed passed, $failed failed"
  [[ "$failed" -eq 0 ]]
}
