# LANE-OWN plan

## Commits (dependency graph)

1. Audit skeleton (draft PR's first state). Done, `a692eb16`.
2. Audit and plan: `docs/units/LANE-OWN/audit.md`, `plan.md`.
3. Schema and validation. Files: `contracts/units/unit.v1.json` (optional `shared`: unique globs),
   `scripts/lib/generated/contracts_units_unit_v1.py` (`scripts/generate python-types`), `scripts/lib/units.py`
   (`shared` ⊆ `paths`), `scripts/tests/test_units.py`. Tests: `test_units.py`, `scripts/generate --check`.
4. Lane rule. Files: `scripts/lib/train_ownership.py` (one helper `lanes(commit, files)` → {unit: lane} over
   the non-shared paths; `lane_of` uses it), `scripts/lib/structure.py` (`lane_errors` uses it),
   `scripts/tests/test_structure.py`. Tests: shared alone decidable; shared + a real second lane refused;
   only shared paths → no lane; `lane_of` and `lane_errors` agree over the same cases.
5. Declarations and the approval duty. Files: `units/engine-structure/unit.json`, `units/web-build/unit.json`,
   `scripts/tests/test_structure.py` (refusals test: a shared path outside the lane still names its owner).
   Tests: `test_units.py` (every manifest of the checkout valid), `test_structure.py`.
6. Retro `docs/units/LANE-OWN/retro.md` after the gate on the head is green.

Edges: 3 → 5 (real: the declarations need the schema field). 4 → 5 (collision only: `test_structure.py`;
kept in sequence). 3 and 4 own disjoint files and run in parallel (3 in a sub-agent, 4 here). 6 after the gate.
Critical path: 4 (~20 min) → 5 (~10 min) → gate (~2 min wall, plus queue) → 6 (~10 min).

## Premises (radius)

- The census files are generated, never hand-edited (`literals:census`, `catalog_files`). Low.
- `web-build` owning the web config is for approval, not lane. Low.
- A PR touching two real units is still refused (test in 4). Low; it is the unit's reason to exist.
- Manifests are read at the merge base, so the declarations act only after merge (audit 4). Low.
None is CRITICAL (no money, production or source of truth).

Premises: none

## Final proof

One `scripts/gate-dev --pr 771` on the head after commit 5. First real run: after merge, `structure-check
--pr <n>` on one of the 7 census-only PRs the brief lists (e.g. #632) reports no `lane undecidable`.

## Known base defects expected

None registered for these files.

## Cheapest useful effort

Action: teach `train_ownership.lane_of` and `structure.lane_errors` that a shared path does not decide a lane, reading one registry list instead of two rules.
Cost: one registry key, two modules and their tests, about 40 minutes and no new dependency.
Requirement: the merge train (Daniel, 28/10 15:06), which cannot merge the 7 census-only PRs while a generated file names two lanes.
Cheaper rejected: adding the census files to a lane's own glob — it hides the collision and leaves the same file claimed twice.
