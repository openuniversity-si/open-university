# B1 retro: performance budgets with a measured baseline

## 1. Brief quality
- Named a branch (`mod/motor-b1-perf-budgets`) different from the session's assigned one; the assigned one was used.
- "Baseline from `engine.step.measured`" assumed events exist; the real log held none (8 `defect.detected`, 1 `config.changed`). Bytes and latency are not durations, so an additive `budget.measured` v1 was needed. The brief should say so.
- Absolute values for bundle and latency were left open; measured locally (694,601 bytes; Home p95 6.3 ms).

## 2. Audit and plan
- Held: O1's reader (`slo.ordered`, `percentile`) and `battery.unit_time_limit` are reusable as-is (no second name).
- Broke: a generated drift target for the baseline (its input is the log, not git) -> a committed, schema-validated file written by `budgets baseline --write`; the baseline is not committed yet (fewer than `budgets.min_samples` measurements).
- Plan commits 1 and 2 were pushed as one commit; item 2 was ticked by a later trailer.

## 3. Execution (failure classes)
| Failure | Class | Fix |
|---|---|---|
| Registry `x-readers` named files that did not exist yet | order of commits | reader skeleton in the registry commit |
| Unit battery 34.7 s > 10 s: `config.get` costs ~40 ms (store replay) and event validation calls it ~10 times per emit | slow shared helper | tests build events by hand, one port test; 5.2 s. Owner C0: cache the local store read |
| CODEOWNERS drift after a new unit | generated file | `scripts/generate codeowners`; same on the base merge |
| `engine-structure` imported `engine-budgets` undeclared | manifest | added to `requires` |
| `assets.json` entry missing for `scripts/budgets` | inventory | added |

## 4. Gate
- Run 1 (before the base merge): generated drift red (CODEOWNERS) -> fixed.
- Run 2 and 3 (after merging 130+ commits of base): `script tests` red on `scripts/tests/generate.test.sh`, known defect KD-024bbecb (`intents-doc.ts` cannot resolve `@ou/kernel-tables` under plain node; reproduced on a clean base worktree). All earlier stages passed (structure check 61 s, drift, schema compat, secret scans). Stages after script tests did not run. Wall 638 s.

## 5. Lessons
1. The unit battery limit caught a test-design class: any test that emits through the port pays `config.get` per validation. Owner C0: memoize the store read per process; engine-units: lint tests for more than N port emits.
2. A brief that depends on measured data must state whether the data exists (owner: brief template, K0).
3. A base defect that blocks `script tests` blocks every PR behind it; the fix for KD-024bbecb (relative imports in node-run closure, as U3b did for catalog-bake) belongs to engine-lane/U3b.
