# TX21 — plan

Decision D-070, Premises P-46. Lane engine-lane. Deadline MERGE-READY about 86 min after launch.

## Commits (graph): 1 → 2 → 3 → 4 → 5 → 6

1. **Audit** (`docs/units/TX21/audit.md`). Done.
2. **Plan** (this file).
3. **Minimal CODEOWNERS.** `scripts/lib/generate_codeowners.py`: resolve each tracked path's owner set through
   `units.units_of` (the one resolver) and emit a directory-tree cover (one default per directory, chosen to minimise
   rows; `/dir/` rows shallow to deep, file rows for exceptions, a bare row for "no owner"). The legacy one-row-per-glob
   renderer stays as `render_legacy` for the proof. `CODEOWNERS` regenerated. New `scripts/tests/test_codeowners_minimal.py`
   (run by `generate.test.sh`, listed in `covers/generate.json`): every tracked path resolves to the same owner set
   through the legacy and the minimal file (a CODEOWNERS resolver, last match wins); adding a fixture path in an owned
   region leaves the file byte-identical; changing a lane's identity does change it. `test_generate.py` Codeowners
   fixture: its two row-shape assertions restated for the new shape (same count). Tests: generate, units.
4. **Companion rule.** `config/registry/units.json` `units.companions` (pattern pairs, `*` = one segment):
   `scripts/tests/covers/*.json` belongs to the unit of `scripts/tests/*.test.sh`. `units.units_of` returns the
   derived unit when the primary has one; `unit_check.ownership` allows a claim by that same unit and refuses a claim by
   any other unit with `units/<id>/unit.json:<line>` of the glob to remove and the rule that owns the file.
   `units/engine-gate-plan/unit.json` drops `scripts/tests/covers/**`; CODEOWNERS regenerated. New
   `scripts/tests/test_units_companion.py`: derived owner, idempotent same-unit claim, foreign claim message (#740's
   shape, replayed), primary without a unit falls back to claims. Tests: units, generate, structure-check.
5. **Unowned production names a sibling unit.** `unit_check.ownership`: the error names the unit(s) owning the other
   tracked files of the same directory, else of the nearest ancestor directory with an owner. Test in
   `test_units_companion.py`. Tests: units, structure-check.
6. **Retro** (`docs/units/TX21/retro.md`) and the single final pinned gate.

## Premises

| Premise | Blast radius | Held by |
|---|---|---|
| **CRITICAL** No ownership check is weakened: every fixture that fails before still fails. | every PR's structure check | the assertions of test_unit_check / test_units / test_unit_map unchanged (counts quoted before/after); new cases only add. The foreign-claim case keeps failing, with a better message. |
| **CRITICAL** CODEOWNERS keeps the same owner set for every tracked path. | review routing on GitHub | the equivalence test over `git ls-files`, legacy vs minimal. |
| A covers file is never production (`scripts/tests/**` is a test glob), so a covers file whose test has no unit may stay unowned. | ownership rule | `units.production` unchanged. |
| The train's lane reader ignores files no manifest covers, so dropping `covers/**` adds no lane. | train refusals | `train_ownership.lane_of`. |
| P-46: the verdict comes from the pinned gate on the base tip. | gate | pinned gate run recorded in the PR. |

## Final gate

Pinned gate once at the end: `OU_CONFIG_STORE=file bash scripts/cloud/setup.sh`, then
`(export OU_CONFIG_STORE=file; source scripts/cloud/env.sh; unset OU_CONFIG_STORE; scripts/gate-dev --pr <n>)`.
