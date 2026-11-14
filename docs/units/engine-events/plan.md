# engine-events — plan
## Alternativas
### R1 Historical reads outside the declared forge surface
| Alternative | Level | Root resolved | Cost | Reversibility | Risk | Rung |
|---|---|---|---|---|---|---|
| A1 Keep catalog exceptions | remendo | no | low | immediate | continued provider coupling | 0 |
| A2 Reuse change_files; add closed_changes and shared adapter proof | corrige a classe | yes | bounded implementation | git revert | provider field mismatch | 1 |
| A3 Replace historical reporting with an event projection | redesenho | yes | new persistence and migration | migration required | historical coverage gaps | 2 |
## Escolha
- R1 → A2: matches both existing reads without a new write operation or persistence model.
## Commits
1. Baseline, ownership, intake, research, audit and plan.
2. Port, adapters, historical report consumer, shared oracle, relations and demands.
3. Premise consumer, error and fixture compatibility, catalog retirement, docs and final evidence.
4. Restore the port section notes the third commit dropped; the surface change stands alone.
## Premises
Premises: none
## Tests
Compare forge-events, premises unittest, structure unittest and structure-check against the base. Run premises shell suite, vendor checks, vendor-ports, operation-relations and the old idea-to-prod fixture format. Gate bypass is not suite evidence.
## Base defects expected
Preserve the measured structure failures item by item and the brief's known unrelated defects.
## Cheapest useful effort
Action: shared adapter and consumer proofs.
Cost: one working session, offline fixtures.
Requirement: Daniel needs provider-independent consumers with observable equivalence.
Cheaper rejected: deleting baseline entries alone would conceal the actual dependency.
