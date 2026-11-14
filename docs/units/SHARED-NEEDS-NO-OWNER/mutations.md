# SHARED-NEEDS-NO-OWNER mutation proof

Brief item 4: break the fix on purpose and show that the tests notice. Each mutation is applied to
`scripts/lib/train_ownership.py` at the head named below, judged, and undone. A helper replaces the text only when it
occurs exactly once (LANE-OWN retro: no unchecked scripted edit), and the file is byte-identical after the last undo.

| Mutation | What it breaks | Expected red |
|---|---|---|
| M1 | `refusals()` judges the whole `paths` list again: the shared filter is removed from `refusals()` only, and `lanes()` keeps it | (a). (b) is red too: under M1 the refusal also lists the shared file, and (b) pins that it names only the non-shared one |
| M2 | `deciding()` returns the whole `paths` list: the one helper both rules read | (a), (b), and the LANE-OWN lane-rule tests, because `lanes()` reads the same helper |

`forge_events.unit_of` stays green under both: naming reads `units()`, not the refusal.

## Run on the head

Run on 6c3b0bf2, the head that carries items 2 and 3, at 21:09 UTC on 28/10, from a clean checkout:

```
source scripts/cloud/env.sh
OU_CONFIG_STORE=file PYTHONDONTWRITEBYTECODE=1 bash mutation-proof.sh /home/user/the-tower
```

| Mutation | `test_train_role.py` (29 tests) | test (a) alone | `test_structure.py` (66 tests) | `test_unit_of.py` (7 tests) |
|---|---|---|---|---|
| M1 | 2 failures: (a), (b) | fails | 1 failure: the LANE-OWN test of the new rule | green |
| M2 | 2 failures: (a), (b) | fails | 4 failures: three LANE-OWN lane-rule tests and the test of the new rule | green |
| restored | green | green | green | green |

After the second undo the module is byte-identical (the script compares sha256 before and after), and
`git status --short` lists nothing.

Output, verbatim:

```
head 6c3b0bf23f72915b2e1c9cb7b398306b5cdf0715 at 21:09:21
== M1: refusals() judges the whole paths list again (the shared filter removed from refusals() only)
mutate: scripts/lib/train_ownership.py: '            globs = deciding(manifest)\n            touched = [path' -> "            globs = manifest.get('paths', [])\n            touched = [path"
-- scripts/tests/test_train_role.py
FAIL: test_a_shared_path_alone_merges_and_asks_nobody (__main__.Ownership.test_a_shared_path_alone_merges_and_asks_nobody)
FAIL: test_a_shared_path_beside_a_foreign_one_is_refused_for_the_foreign_file_only (__main__.Ownership.test_a_shared_path_beside_a_foreign_one_is_refused_for_the_foreign_file_only)
Ran 29 tests in 9.104s
FAILED (failures=2)
-- test (a) alone
FAIL: test_a_shared_path_alone_merges_and_asks_nobody (__main__.Ownership.test_a_shared_path_alone_merges_and_asks_nobody)
Ran 1 test in 0.493s
FAILED (failures=1)
-- scripts/tests/test_structure.py
FAIL: test_lane_own_a_shared_path_names_its_owner_and_never_refuses (__main__.PlanCompletenessAtGate.test_lane_own_a_shared_path_names_its_owner_and_never_refuses)
Ran 66 tests in 26.159s
FAILED (failures=1)
-- scripts/tests/forge_events/test_unit_of.py
Ran 7 tests in 0.039s
OK
mutate: scripts/lib/train_ownership.py: "            globs = manifest.get('paths', [])\n            touched = [path" -> '            globs = deciding(manifest)\n            touched = [path'
== M2: deciding() returns the whole paths list (the helper both rules read)
mutate: scripts/lib/train_ownership.py: "    return [glob for glob in manifest.get('paths', []) if glob not in shared]" -> "    return list(manifest.get('paths', []))"
-- scripts/tests/test_train_role.py
FAIL: test_a_shared_path_alone_merges_and_asks_nobody (__main__.Ownership.test_a_shared_path_alone_merges_and_asks_nobody)
FAIL: test_a_shared_path_beside_a_foreign_one_is_refused_for_the_foreign_file_only (__main__.Ownership.test_a_shared_path_beside_a_foreign_one_is_refused_for_the_foreign_file_only)
Ran 29 tests in 7.959s
FAILED (failures=2)
-- test (a) alone
FAIL: test_a_shared_path_alone_merges_and_asks_nobody (__main__.Ownership.test_a_shared_path_alone_merges_and_asks_nobody)
Ran 1 test in 0.465s
FAILED (failures=1)
-- scripts/tests/test_structure.py
FAIL: test_lane_own_a_change_of_only_shared_paths_has_no_lane (__main__.PlanCompletenessAtGate.test_lane_own_a_change_of_only_shared_paths_has_no_lane)
FAIL: test_lane_own_a_shared_path_alone_leaves_the_lane_decidable (__main__.PlanCompletenessAtGate.test_lane_own_a_shared_path_alone_leaves_the_lane_decidable)
FAIL: test_lane_own_a_shared_path_names_its_owner_and_never_refuses (__main__.PlanCompletenessAtGate.test_lane_own_a_shared_path_names_its_owner_and_never_refuses)
FAIL: test_lane_own_lane_of_and_lane_errors_agree (__main__.PlanCompletenessAtGate.test_lane_own_lane_of_and_lane_errors_agree)
Ran 66 tests in 26.400s
FAILED (failures=4)
-- scripts/tests/forge_events/test_unit_of.py
Ran 7 tests in 0.036s
OK
mutate: scripts/lib/train_ownership.py: "    return list(manifest.get('paths', []))" -> "    return [glob for glob in manifest.get('paths', []) if glob not in shared]"
== restored
restored: scripts/lib/train_ownership.py is byte-identical
-- scripts/tests/test_train_role.py
Ran 29 tests in 9.552s
OK
-- test (a) alone
Ran 1 test in 0.687s
OK
-- scripts/tests/test_structure.py
Ran 66 tests in 27.127s
OK
-- scripts/tests/forge_events/test_unit_of.py
Ran 7 tests in 0.033s
OK
exit=0
```

## The scripts

`mutation-proof.sh`:

```bash
#!/usr/bin/env bash
# mutation-proof.sh CHECKOUT: the two mutations of SHARED-NEEDS-NO-OWNER item 4, each applied, judged and restored.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
cd "$1" || exit 2
file=scripts/lib/train_ownership.py
before=$(sha256sum "$file")
mutate() { python3 "$here/mutate.py" "$file" "$1" "$2" || exit 2; }
judge() { python3 "$@" 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^(OK|FAILED)'; }
suites() {
  echo "-- scripts/tests/test_train_role.py"; judge scripts/tests/test_train_role.py
  echo "-- test (a) alone"; judge scripts/tests/test_train_role.py Ownership.test_a_shared_path_alone_merges_and_asks_nobody
  echo "-- scripts/tests/test_structure.py"; judge scripts/tests/test_structure.py
  echo "-- scripts/tests/forge_events/test_unit_of.py"; judge scripts/tests/forge_events/test_unit_of.py
}
refusals_fixed=$'            globs = deciding(manifest)\n            touched = [path'
refusals_mutant=$'            globs = manifest.get(\'paths\', [])\n            touched = [path'
helper_fixed="    return [glob for glob in manifest.get('paths', []) if glob not in shared]"
helper_mutant="    return list(manifest.get('paths', []))"

echo "== M1: refusals() judges the whole paths list again (the shared filter removed from refusals() only)"
mutate "$refusals_fixed" "$refusals_mutant"; suites; mutate "$refusals_mutant" "$refusals_fixed"
echo "== M2: deciding() returns the whole paths list (the helper both rules read)"
mutate "$helper_fixed" "$helper_mutant"; suites; mutate "$helper_mutant" "$helper_fixed"
echo "== restored"
[ "$(sha256sum "$file")" = "$before" ] && echo "restored: $file is byte-identical" || { echo "restore FAILED"; exit 1; }
suites
```

`mutate.py`:

```python
"""mutate.py FILE OLD NEW: replace OLD with NEW in FILE, refusing unless OLD occurs exactly once."""
from pathlib import Path
import sys

path, old, new = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
text = path.read_text()
count = text.count(old)
if count != 1:
    sys.exit(f'mutate: {old!r} occurs {count} times in {path}, not once')
path.write_text(text.replace(old, new))
print(f'mutate: {path}: {old!r} -> {new!r}')
```
