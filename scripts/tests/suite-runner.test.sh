#!/usr/bin/env bash
# The directory suite runner (scripts/tests/lib/suite.sh, TX-PROGRAM, D-070) on fixture parts: counts are summed, and a
# failed check, a part that stops before check_done, a part with no check and an empty suite each fail the suite.
# Verifies: UNIT:engine-test-support
set -uo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
# shellcheck source=scripts/tests/lib/suite.sh
source "$root/scripts/tests/lib/suite.sh"
CHECK_LABEL="suite runner"
# shellcheck source=scripts/tests/lib/check.sh
source "$root/scripts/tests/lib/check.sh"
fixture() {  # fixture <suite> <part> <body>
  mkdir -p "$work/$1"
  printf '#!/usr/bin/env bash\nset -uo pipefail\nsource "%s/scripts/tests/lib/check.sh"\n%s\n' "$root" "$3" >"$work/$1/$2.test.sh"
}
fails() { ! "$@"; }
run() { local rc=0; suite_run "$1" "$work/$1" >"$work/$1.out" 2>&1 || rc=$?; return "$rc"; }
# The expected counts are read from the fixtures, never written as numbers (no literals, D-068).
parts() { find "$work/$1" -name '*.test.sh' | wc -l; }
checks() { cat "$work/$1"/*.test.sh | grep -o 'check "[a-z]' | wc -l; }
fixture green a 'check "one" true; check "two" true; check_done'
fixture green b 'check "three" true; check_done'
check "a green suite passes" run green
check "the counts of every part are summed" grep -Fxq "green tests: $(checks green) passed, 0 failed ($(parts green) parts)" "$work/green.out"
fixture red a 'check "fine" true; check_done'
fixture red b 'check "broken" false; check_done'
check "a failed check fails the suite" fails run red
check "the failed check is named" grep -Fq 'FAIL check: broken' "$work/red.out"
check "a failed check is counted once" grep -Fxq "red tests: 1 passed, 1 failed ($(parts red) parts)" "$work/red.out"
fixture stopped a 'check "before" true; set -e; false; check_done'
check "a part that stops before check_done fails the suite" fails run stopped
check "the stopped part is named with its exit code" grep -Fq 'FAIL stopped: part a exited 1 before check_done' "$work/stopped.out"
fixture empty a 'check_done'
check "a part with no check fails the suite" fails run empty
check "the part with no check is named" grep -Fq 'FAIL empty: part a ran no check' "$work/empty.out"
mkdir -p "$work/none"
check "a suite with no part fails" fails run none
printf 'exit 1\n' >"$work/green/helper.sh"
check "a file that is not a part is not run" run green
fixture par a 'sleep 1; check "slow" true; check_done'
fixture par b 'sleep 1; check "slow" true; check_done'
fixture par c 'sleep 1; check "slow" true; check_done'
start=$SECONDS; OU_TEST_CPUS=3 run par
check "parts run side by side, at most OU_TEST_CPUS" test "$((SECONDS - start))" -lt "$(parts par)"
check "the parallel counts are still summed" grep -Fxq "par tests: $(checks par) passed, 0 failed ($(parts par) parts)" "$work/par.out"
check_done
