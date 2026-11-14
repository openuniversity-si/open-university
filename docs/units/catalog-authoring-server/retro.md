# catalog-authoring-server retro (U4)

1. **Brief.** It asked to move the unit into `units/catalog-authoring-server/` (S1 keeps units logical, nothing moved) and said every importer already uses `@ou/catalog-authoring-server` (none does; all use relative paths).
2. **Result.** Audit, contract document and the manifest `battery.command`. A `contract.ts` entry was tried and removed: it pushed the catalog cell to 85 files / 8647 lines against a budget of 84 / 8631 (`L3.context-size`, found by the gate's architecture test). The budget is not loosened, so the contract slot stays empty.
3. **Gate.** The first gate-dev (566 s, over the 180 s ceiling on this 4 vCPU) failed only on that rule; see the PR comments for the final run.
4. **Lessons.** Run `scripts/check-architecture.mjs` before pushing a unit-contract entry in a cell at its budget; the unit battery does not check cell budgets. Two pushed commits were red or reverted because a push guard pushes each commit as it is made.
