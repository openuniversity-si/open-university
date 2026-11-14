# GX-13 plan

Base eaeeb29d. PR #729, branch `mod/gx13`. Decision D-070. Premises: P-46 (GA-PG1: the verdict comes from the pinned gate on the base tip; low for this unit).

## Commits (`Plan: N`)
1. `docs/units/GX13/audit.md` (done).
2. `docs/units/GX13/plan.md` (this file).
3. Preparation: registry keys in `config/registry/defects.json` — `defects.never_excuse_touched` (true), `defects.verify_open` (true), `defects.rerun_install_command` (the gate's own frozen install), `defects.base_env` (`OU_GATE_BASE_SHA`), `defects.fetch_remote` (`origin`); `open>resolved` added to `defects.transitions`; generated module via `scripts/generate`. Test: `scripts/run test defects`.
4. Recorded base: `defect_detect.recorded_base()` reads `OU_GATE_BASE_SHA` (tier 1 `baseRefOid`, tier 2 batch base); set but empty means no recorded base (nothing excused); unset (a direct call outside gate-local) keeps the old local resolution. A base sha whose objects are missing is fetched (`git fetch <remote> <sha>`); a fetch that fails leaves no base. `rerun` uses the base's own install: no `node_modules` when the base's covers manifest says `modules: false`, otherwise the registered frozen install in the base worktree, never a symlink to the tool root's. `gate_adjudicate.adjudicate` uses it. Files: `defect_detect.py`, `gate_adjudicate.py`, `test_defect_detect.py`.
5. Never excuse a touched test: `defect_detect.touched(test, changed)` is true when the PR changed the test's own file, its covers manifest, or a file its declared covers match; `adjudicate` keeps such a failure the PR's without re-running it (`defects.never_excuse_touched`). `gate_adjudicate` computes the changed files from `git diff --name-only <base> <sha>`; an undiffable pair counts as everything changed (nothing excused). The #662 fixture stays red. The excused stage keeps `raw_result: FAIL` and its defect ids (`defects` on the stage in the report). Files: same as 4.
6. Verify open defects: `verification` also re-runs `open` defects when `defects.verify_open` is on; one that passes on the base yields `verified`, and `defects.sync` moves an `open` record to `resolved` on it (tool-made; `resolved → verified` on a later pass, as today). Switch off: today's behaviour. Then the tool applies it to KD-024bbecb and KD-4db6e693 (both pass on eaeeb29d). Files: `defect_detect.py`, `defects.py` (sync branch only, own dependency), `test_defect_lifecycle.py`, `test_defect_detect.py`, `docs/process/defects/*` (tool output).
7. RETRO `docs/units/GX13/retro.md`.

## Graph and critical path
3 → 4 → 5 → 6 → gate → 7. Every code commit edits `defect_detect.py` and its test: real file edges, no parallel split worth its cost (a sub-agent per commit would collide on the same two files). Estimates: 3 ≈ 8 min, 4 ≈ 15, 5 ≈ 15, 6 ≈ 15, gate ≈ 15 wall, 7 ≈ 10. Critical path ≈ 80 min. Parallel during the gate: the RETRO draft.

## Tests
Per commit: `scripts/run test defects` (3), `scripts/run test defect-detect` (4, 5, 6), `scripts/run test defect-lifecycle` (6). Final: one pinned `scripts/gate-dev --pr 729`.

## Not in this unit
- Per-stage `raw_result` in the published verdict: `gate_proof.stage_records` (GX-10's file) drops it; one-line proposal in the PR, owner GX-10. The defect id reaches the verdict through `known_defects` already.
- Known base defects KD-335a14a4, KD-71c8e5fe, KD-27b768cb, KD-a3870679, KD-41f822d3 and env failures (GX-ENV, GX-FIX-modules).

## Rollback
`scripts/config` set `defects.never_excuse_touched=false` and/or `defects.verify_open=false` restores today's excuse and lifecycle; revert PR of the merge commit for the rest.
