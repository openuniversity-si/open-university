# INTAKE-RESEARCH — audit

Read-only, cheap evidence, base `13ba2b0e2` (mod/roadmap-integration, 29/10).

## Entradas
- [intake.md](intake.md): the real problem — units audit before anyone wrote down what was asked, why, and who already solved it; resolved when every new unit carries both files, checked at the door.
- [research.md](research.md): the state of the art — fixed headings checked at the door, with a prior-art section and a not-retroactive date (Google design docs, Rust RFCs, ADR linters).
- Read as inputs only; the findings below are this audit's own questions.

## Findings
1. **Where the unit flow is defined.** `docs/padrao/v5/audit-and-plan.md` starts every session at AUDIT; `retro-before-merge.md` ends it. Published versions are never edited (`docs/padrao/README.md`), so a change is a new folder `v6/`.
2. **The active version is not v5.** `scripts/config get coordinator.padrao_version` prints `"v1"`; v3, v4 and v5 were published without moving the key (GATE-API commit `cbb50edab`: "The active Padrao version is not moved here"). Sessions receive the newest folder from A Torre's launch prompt; `coordinator_launch.padrao()` renders the key's version.
3. **Unit files are not checked as a set.** No check requires `audit.md`/`plan.md`/`retro.md` in `docs/units/<UNIT>/`; only `plan.md` is judged (effort block, `scripts/lib/effort.py`, `structure check` stage) and `retro.md` is read by lessons and the program retro. Of 151 unit folders none has `intake.md` or `research.md`.
4. **Programs.** `coordinator.program_files` = brief, audit, plan, retro; `program.check` refuses a program folder missing any of them, for every program (retroactive by construction). `program.create` copies those files from `docs/programs/_template/`.
5. **Model to copy.** `effort.plan_errors` grandfathers a plan by its oldest commit against the registry's first commit, and judges only plans the diff touches when a base is given. It replaced a shrink-only list that broke a train batch on 28/10.
6. **Gate-change rule.** `scripts/lib/structure.py` is a gate file for D-025 (`commit_check.gate_errors`): the PR body cites D-077, approved by Daniel at 16:01 BRT.
7. **Decision numbers.** D-074 (#768) and D-076 (#804) are held by open PRs; D-077 is free (search of open PRs, 29/10).
8. **Docs that describe the unit flow.** `AGENTS.md` (Rules › Commit cadence), `docs/process/STRUCTURE.md` (no unit-flow section today), `docs/operations/coordinator.md` (Padrão → Motor), `docs/padrao/README.md`.
9. **Covers.** `scripts/tests/covers/structure-check.json` lists `docs/units/*/plan.md` and `docs/padrao/v4/*.md`; the new check's files must be added so the gate selects the test.

## Distância do estado da arte
- **Already there:** the door check exists as a pattern (`structure check` + `scripts/lib/effort.py`, grandfathered by first-commit date), so "fixed headings checked at the door" costs one module, not a new stage.
- **Missing at base:** no unit has an intake or a research file (finding 3); no template names context, intent or prior art; the audit template has no inputs and no comparison with a reference.
- **Rung:** this PR reaches rung 1 of the research's ladder (Padrão rule + door check + templates, audit reads both files). Still missing for the state of the art: the coordinator pre-filling the intake (rung 2), a shared reference index (rung 3), Lacunas as an event to Daniel (rung 4).

## Base defects expected
None known for docs/scripts-only changes; the gate's structure-check WARN lines on oversized units predate this PR.
