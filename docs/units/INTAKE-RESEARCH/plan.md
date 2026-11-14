# INTAKE-RESEARCH — plan

Mirrors the PR body of #806.

## Commits (sequential; one file owner per commit)
1. `intake.md` — the unit's intake in the new format.
2. `research.md` — the unit's research in the new format.
3. `audit.md`, `plan.md` — this audit and plan.
4. D-077 (`docs/domain/DECISIONS.md`); Padrão v6 = v5 + `intake-and-research.md` (first rule after `think-before-acting`), `audit-and-plan.md` rewritten to start after RESEARCH; templates `docs/process/templates/intake.md`, `research.md`, also copied into `docs/programs/_template/`.
5. `config/registry/intake.json`, `scripts/lib/unit_intake.py`, wired in `structure.tree_part`; `program.create` copies the intake files; tests `scripts/tests/test_structure_intake.py`; covers.
6. `docs/process/STRUCTURE.md` (new section on the unit flow), `AGENTS.md`, `docs/operations/coordinator.md`, `docs/padrao/README.md`.
7. `retro.md`.
8. Daniel's 16:26 BRT complement: the audit reads intake and research as inputs. `## Entradas` and `## Distância do estado da arte` in the audit templates (`docs/process/templates/audit.md`, `docs/programs/_template/audit.md`), Padrão v6 (`audit-and-plan.md`, `intake-and-research.md`), `STRUCTURE.md` B3, this unit's `audit.md`; `intake.audit_*` in the registry and `unit_intake.py` refuse a new unit's audit.md without them (or whose `Entradas` does not name both files); tests.

## Premises
- Not retroactive by date: a folder whose oldest commit is before `intake.since` (2026-10-29T19:01:00Z, Daniel's approval) is grandfathered. Blast radius: a unit started before 16:01 BRT that lands later is not judged — accepted, it is what "not retroactive" means. Not critical.
- `coordinator.padrao_version` stays where it is (v1), as v3–v5 did; v6 is published, its activation is A Torre's launch choice. Blast radius: the coordinator's rendered brief keeps v1 until someone moves the key; the structure check enforces the files regardless. Not critical; reversible with one `scripts/config set`.
- Section names are pt-BR as Daniel dictated, read from the registry, compared without accents and case. Not critical.

## Tests
Commits 5 and 8: `python3 -m unittest scripts/tests/test_structure_intake.py`, `scripts/tests/test_structure_effort.py`, the program tests. Final: `scripts/gate-dev --pr 806` once on the exact head.

## Cheapest useful effort
Action: a new structure-check module with its tests, wired into the `structure check` stage
Cost: about 30 minutes of session time and one gate run
Requirement: Daniel, who wants every new unit to start from intake and research without reminding each session
Cheaper rejected: only a Padrão rule text (nothing refuses a unit that skips the files, which is how the 29/10 rework happened); a list of units to check (lists only shrink and broke a batch on 28/10)
