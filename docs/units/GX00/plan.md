# GX-00 plan (mirrored in the PR description)

Premises: the six GA premises recorded in this PR (ids assigned by `scripts/premises propose`), P-30 (premise system, low), P-11 (one decision per entry, inferred, low). CRITICAL: GA-P03 (forge status, decided) and GA-P04 (money: deferred spend, nothing paid). None can change scope in this docs-only unit.

Commits (each green on its own; docs only):
1. `docs/units/GX00/audit.md`, `plan.md`.
2. `docs/programs/gate-excellence/audit-1-fable.md` verbatim from `origin/mod/ga1`.
3. `docs/programs/gate-excellence/audit-2-opus.md` verbatim from `origin/mod/ga2`.
4. Program folder: `plan.md` verbatim from `origin/mod/ga3`, `brief.md`, `audit.md` (index), `retro.md` (template).
5. Six premise records under `docs/process/premises/`.
6. D-070 in `docs/domain/DECISIONS.md`.
7. `docs/units/GX00/retro.md`.

Graph: 1 -> 2, 3, 4 (disjoint files) -> 5 -> 6 -> 7. Commits are sequential (one writer); no parallel ownership.

Targeted tests: `scripts/run test units`, `premises`, `program`; `scripts/premises check`; `scripts/program check gate-excellence`; `scripts/structure-check --pr-body`. Verdict: `scripts/gate-dev --pr N` from a clean base-tip checkout (D-A3), own-checkout run report-only.
Known base defects: none expected.
