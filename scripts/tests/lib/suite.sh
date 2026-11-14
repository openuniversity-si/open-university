# shellcheck shell=bash
# A test suite as a directory (TX-PROGRAM, D-070). scripts/tests/<suite>.test.sh calls suite_run, which runs every
# scripts/tests/<suite>/*.test.sh part in its own process (side by side, at most OU_TEST_CPUS), its output in name order, and sums the parts' counts. Nothing lists the
# parts: a unit adds a part file and edits no shared test file. A part sources scripts/tests/lib/check.sh, asserts with
# `check`, and ends with `check_done`. A part that ran no check, or exited non-zero with no failed check (it stopped
# before its end), fails the suite; so does a suite with no part.
suite_run() {  # suite_run <label> <directory>
  local label="$1" dir="$2" part name counts rc parts=0 passed=0 failed=0 p f
  counts="$(mktemp -d)" || return 1
  local -a list=() rcs=()
  local cpus="${OU_TEST_CPUS:-1}" i running=0
  [[ "$cpus" =~ ^[1-9][0-9]*$ ]] || cpus=1
  for part in "$dir"/*.test.sh; do [[ -e "$part" ]] && list+=("$part"); done
  # F122: at most OU_TEST_CPUS parts side by side (D-076); each part's output is held and printed in name order.
  for i in "${!list[@]}"; do
    part="${list[$i]}"; name="$(basename "$part" .test.sh)"
    while [[ "$running" -ge "$cpus" ]]; do wait -n 2>/dev/null; running=$((running - 1)); done
    ( rc=0; SUITE_COUNTS="$counts/$name" bash "$part" >"$counts/$name.out" 2>&1 || rc=$?; echo "$rc" >"$counts/$name.rc" ) &
    running=$((running + 1))
  done
  wait
  for part in "${list[@]}"; do
    parts=$((parts + 1))
    name="$(basename "$part" .test.sh)"
    cat "$counts/$name.out" 2>/dev/null
    rc="$(cat "$counts/$name.rc" 2>/dev/null || echo 1)"
    if [[ ! -s "$counts/$name" ]]; then
      echo "FAIL $label: part $name exited $rc before check_done"
      failed=$((failed + 1)); continue
    fi
    read -r p f <"$counts/$name"
    passed=$((passed + p)); failed=$((failed + f))
    if [[ "$p" -eq 0 && "$f" -eq 0 ]]; then echo "FAIL $label: part $name ran no check"; failed=$((failed + 1)); fi
    if [[ "$rc" -ne 0 && "$f" -eq 0 ]]; then echo "FAIL $label: part $name exited $rc with no failed check"; failed=$((failed + 1)); fi
  done
  rm -rf "$counts"
  if [[ "$parts" -eq 0 ]]; then echo "FAIL $label: no part in $dir"; failed=$((failed + 1)); fi
  echo "$label tests: $passed passed, $failed failed ($parts parts)"
  [[ "$failed" -eq 0 ]]
}
