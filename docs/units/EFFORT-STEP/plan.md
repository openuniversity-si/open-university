# EFFORT-STEP plan

The gate refuses a plan or PR body that spends effort without saying who needed it: the `pr metadata` stage checks the PR body, the `structure check` stage checks every `docs/units/*/plan.md` against a baseline that only shrinks. The check makes the four answers exist; it never decides whether the cost is worth paying.

## Commit plan
- [ ] 1. Audit: `docs/units/EFFORT-STEP/audit.md` (findings and evidence).
- [ ] 2. Plan: this file, mirrored in the PR body.
- [ ] 3. `scripts/lib/effort.py` (the block parser and its refusals), `config/registry/effort.json` (every field, word and path it reads), its generated types, `scripts/tests/test_structure_effort.py`, the `engine-structure` unit manifest and the structure-check covers. D-069 items 4, 8, 9 and D-065 (5).
- [ ] 4. Wiring: `scripts/lib/structure.py` runs the body check in `metadata_part` (both the `--pr-body` and the `--pr` branch) and the plan check in `tree_part`; `effort.plan_baseline` lists the existing plans without the block and only shrinks against the base. Tests for both stages and the shrink. D-069 items 4, 8, 9 and D-065 (5).
- [ ] 5. Unit checklist: Padrão `v4` = v3 + `effort.md` (the motor rule, copied) + `audit-and-plan.md` item (e) naming the block. `coordinator.padrao_version` stays `v1`: the active version is v1, not v3, so flipping it here would also install the unrelated v2 and v3 changes; the flip is the Padrão owner's (the gate enforces the block whatever version a brief carries).
- [ ] 6. Retro: `docs/units/EFFORT-STEP/retro.md`, with the descent recorded.

## Dependency graph and critical path
- 1 → 2 → 3 → 4 → gate → 6. Commit 5 owns only `docs/padrao/v4/**`: no file shared with 3 or 4 (collision edge removed by design), so it runs in parallel with 3.
- Real edge 3 → 4: the wiring calls `effort.py`. Real edge 5 → 4 only for the rule path in the refusal message (`effort.rule_doc` = `docs/padrao/v4/effort.md`); the registry default names the path, so 4 does not wait for 5's content.
- Critical path: 3 (15 min) → 4 (15 min) → gate-dev (≈ 15 min) → 6 (10 min) ≈ 55 min.

## Premises
- The motor's `rules/effort.md` and `effort-check.py` are not readable here (audit 1); the four fields and the two refused shapes come from the brief. Radius: low (the check is reversible and the field names are registry values). Not CRITICAL.
- Refusing every PR body without the block turns open PRs red at their next `pr metadata` run until their body gains the block. Editing a body does not change the head, so `pr.ready` and the train queue are unaffected. Radius: medium. Not CRITICAL (no money, no production, no source of truth).

## Tests per commit
- 3: `python3 scripts/tests/test_structure_effort.py` (parser, each refusal, the owner rule; mutation: owner rule disabled → red).
- 4: the same file's stage tests + `python3 scripts/tests/test_structure.py`; `scripts/structure-check --metadata --pr-body <file>` on this PR's real body with and without the block.
- 5: `python3 scripts/tests/test_coordinator_launch.py` (the renderer still reads the active version).
- Final: one `scripts/gate-dev --pr 770`.

## Known base defects expected
Read from `docs/operations/known-defects.md` at gate time; none touch `structure-check`. A known defect that blocks the gate is reported with its owner, never fixed here.

## Cheapest useful effort
Action: the final `scripts/gate-dev --pr 770` on the PR head.
Cost: about 15 min wall and one gate run of quota.
Requirement: Daniel needs the merge door to prove that the new refusal does not turn other stages red before the train takes it.
Cheaper rejected: only the targeted tests (they do not prove the wiring inside the real stage plan); `gate-quiet` (the full legacy plan, heavier, and not the merge door).

Premises: none
