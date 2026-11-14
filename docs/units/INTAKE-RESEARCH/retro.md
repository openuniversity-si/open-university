# INTAKE-RESEARCH — retro

Unit: D-077, intake and research before the audit in every new unit, mini-program or system step. PR #806, base `13ba2b0e2`.

## 1. Brief and intake
- The brief carried the concept and the approval, not literal text; the intake fixed the literal ask, the intention and the "resolved" metric in five minutes. It held to the end: no scope moved after the intake.
- Missing from the brief: which D-NNN was free (D-074 and D-076 are held by open PRs #768 and #804; found by a PR search) and that the active Padrão key is still `v1` while sessions run v5 (found in the audit).

## 2. Research, audit and plan
- The research changed the plan in one place: the "not retroactive" rule is a date (`intake.since`), copied from the effort check, never a list, because both the references (template + door check) and our own 28/10 incident point the same way.
- Premises held: date grandfathering (this unit's first commit, 19:04 UTC, is after `intake.since` 19:01 UTC, so it is judged by its own rule); the active key not moved, as v3–v5 did.
- Plan unchanged: 7 items, sequential.

## 3. Execution (UTC, 29/10)
- 19:04 intake (STEP 0, draft PR #806); 19:06 research; 19:07 audit and plan; 19:10 D-077 + Padrão v6 + templates; 19:16 check + tests; 19:18 docs; 19:20 gate.
- Rework 1 (code): the pre-push assets check refused the new `docs/process/templates/*.md` without an entry in `docs/structure/assets.json`; fixed before the push (the commit was still local).
- Rework 2 (code): `program.create` read the intake files from the tested root, but program settings always read this checkout's registry; aligned to `unit_intake.files()`.
- Rework 3 (code): the local literal census refused the number `2` in the test (written twice) and the unit check refused `engine-structure` and `engine-coordinator` importing `engine-intake` undeclared; fixed by deriving the count from the registry and declaring the requires.

- Rework 4 (scope, after MERGE-READY): Daniel's 16:26 BRT comment (the audit reads intake and research as inputs; audit template gains `Entradas` and `Distância do estado da arte`) was posted before the first MERGE-READY and not read; the PR went back to draft and item 8 added it with its check.

## 4. Gate
- Run 1 on `92363aea`: every stage green except `pr metadata`, which refused item 7 (this retro) as not yet ticked — expected by the order "gate, then retro". Run 2 on the retro head.

## 5. Lessons
- A new rule doc folder needs an assets entry; the pre-push check names it, so the cost was one amend. No change proposed.
- `padrao_candidate`: the launch brief should state the active Padrão version and the next free D-NNN, so a unit does not search for them (owner: A Torre, launch template).
- `padrao_candidate`: before posting MERGE-READY, re-read every human comment on the PR since the plan; one posted mid-run is scope (owner: engine-lane, `pr-ready`).
- `padrao_candidate`: the plan item "retro" is always the last tick; the first full gate on a PR that has not committed its retro is always red at `pr metadata`. The Padrão could allow the retro commit before the first gate run (owner: engine-lane, `plan-tick`).
