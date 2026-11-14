# B1 plan (mirrored in the PR description)

## Commit plan
1. Audit (`docs/units/B1/audit.md`).
2. Plan (this file).
3. Registry and contracts: `budgets.*` entries (bundle bytes, page latency p95, regression tolerance, window, baseline path,
   metric names), `contracts/budgets/baseline.v1.json`, additive `budget.measured` v1, unit `engine-budgets`, generated types.
4. Reader and baseline: `scripts/lib/budgets.py` + `scripts/budgets` (`baseline [--write]`, `show`): folds `engine.step.measured`
   (battery per unit) and `budget.measured` (bundle, latency) through `slo.collect/ordered/percentile`, writes the committed
   baseline with provenance. Tests with a fixture log and an injected clock.
5. Regression verdict: `budgets check` compares the newest window's p95 with the baseline plus `budgets.regression_tolerance_percent`
   and with the absolute entries (`battery.unit_time_limit`, bundle, latency); `no_data` never fails, a breach fails. Hermetic tests per refusal.
6. Registry looseness check: structure-check module `budget_check.py` refuses a `budgets.*` bound made looser against the base
   unless its `x-source` gains a decision present in DECISIONS.md; also refuses a baseline that fails its schema. Tests per refusal.
7. Bundle producer + gate wiring: `scripts/budgets measure-bundle` (sums built chunk bytes, emits `budget.measured`), the check
   run by the gate (D-069 item 14, D-025), docs (`docs/operations/budgets.md`).
8. Retro (`docs/units/B1/retro.md`) and RETRO comment.

## Dependency graph and owned files
`1 -> 2 -> 3 -> 4 -> 5`; `6` depends on 3 only and runs in parallel with 4-5 (disjoint files); `7` after 4-6; `8` last.
Sub-agents write files, the coordinator commits and pushes each step alone.

| Commit | Files owned |
|---|---|
| 3 | `config/registry/budgets.json`, `contracts/budgets/*`, `contracts/events/budget.measured.v1.json`, lock, `docs/process/EVENTS.md`, `units/engine-budgets/unit.json`, generated types |
| 4 | `scripts/lib/budgets.py`, `scripts/budgets`, `scripts/tests/test_budgets.py`, `scripts/tests/budgets.test.sh`, `scripts/lib/gate-script-tests.json` entry |
| 5 | `scripts/lib/budgets.py` (verdict, after 4), `scripts/tests/test_budgets_check.py` |
| 6 | `scripts/lib/budget_check.py`, `scripts/lib/structure.py` (one call), `scripts/tests/test_budget_check.py` |
| 7 | bundle producer in `scripts/lib/budgets.py`, gate wiring files, `docs/operations/budgets.md` |

## Premises (blast radius)
- P-12 (unit battery is tier 1, within `battery.unit_time_limit`) - medium: if wrong the battery budget has no subject.
- P-15 (observability is the event log) - medium: if wrong the baseline source changes, the reader is one function.
- P-41 (config in the registry, D-068) - high: a literal budget would fail `config_check`.
- CRITICAL none: no production, spend, secret or source-of-truth change. The log being empty today is handled by `no_data`.

## Decisions (reported, reversible)
- The baseline is a committed file computed from the log, not a `generate` target (its input is not in git).
- `no_data` (fewer samples than `budgets.min_samples`) never fails the gate and never invents a baseline.
- Looseness needs a new decision id in `x-source`; tightening needs nothing.

## Tests and gate
Targeted per commit (`scripts/tests/test_budgets*.py`, `test_budget_check.py`, `test_event_contracts.py`, `test_config*.py`); one `gate-dev` at the end.
