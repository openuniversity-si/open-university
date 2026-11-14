# TRAIN-ORIGIN-INTEGRATION — plan

Reads audit.md's Causas raiz and research.md's Escada de ambição. Performance acceptance stays closed.

## Alternativas
### R1. Merge-selected observations
- A1 Retain one parent's census: rejected; neither parent's counts describe the combined source.
- A2 Recompute sites/counts and retain meaningful static expectations from both units: chosen; preserve declared
  responsibilities and adapter proofs instead of inferring them from ownership.
- A3 Replace the port or merge mechanism: rejected; existing source and checks suffice for this repair.

### R2. Split interface and fixture assumptions
- A1 Rename a test argument and suppress the other failures: rejected; leaves journal routes and creation ownership incoherent.
- A2 Reconcile the single mandatory checkout API and complete-surface fixtures against the merged production port:
  chosen; retains both units' behavioral assertions without a compatibility alias.
- A3 Replace the forge port: rejected; the existing Origin and GitHub contracts already express the required behavior.

### R3. Cross-file hook output
- A1 Disable lint for the hook: rejected; hides unrelated mistakes.
- A2 Annotate the one assignment consumed by gate-local: chosen; expresses the existing shell interface precisely.
- A3 Move the proof hook back into gate-local: rejected; no runtime redesign is needed for this analyzer limitation.

## Escolha
- R1 → A2: restore the declaration/source invariant without discarding either unit's operations.
- R2 → A2: one mandatory checkout identity for incident reporting; current journal doubles and catalog-derived adapter-only
  creation checks; preserve complete-surface and unused-operation assertions.
- R3 → A2: annotate the specific output assignment; keep runtime behavior and all other lint rules unchanged.

## Commits
- [ ] 1. Record intake, research, audit, plan and the observed integration gate.
- [ ] 2. Reconcile contracts, metadata and fixtures; run touched suites and confront declarations.
- [ ] 3. Record final validation and retro; run the ordinary gate and present the repair PR.
Graph: 1 → 2 → 3. All work stays on the new branch from a8feab76d.

## Premises
Premises: none

## Tests
Push-guard, forge-events, forge-rate, gate-forge-budget, lessons, planner-role, train-role, commit-check, PR creation,
operation relations/configuration and readers. Then the full ordinary gate with bypass disabled, all 145 script
suites and ShellCheck. Root integration executes in the isolated root profile; no privileged test is silently skipped.

## Base defects expected
All observed integration failures remain in scope until repaired.

## Cheapest useful effort
Action: reconcile merge-selected interfaces and derived declarations.
Cost: the existing checkout and toolchain; no paid service.
Requirement: the coordinator needs a green integration tree preserving both units.
Cheaper rejected: selecting a parent wholesale discards the other parent's intent again.
