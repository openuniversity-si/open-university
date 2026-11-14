# engine-test-support: plan (U4)

Premises: P-03 (high: units stay logical, so no move), P-04, P-05 (low), P-07 (medium: no contract change).
None is CRITICAL.

| # | Commit | Files owned |
|---|---|---|
| 1 | audit.md | docs/units/engine-test-support/audit.md |
| 2 | plan.md | docs/units/engine-test-support/plan.md |
| 3 | Fix the partial-copy class in the unit's tests | scripts/tests/gate-isolation.test.sh, scripts/tests/invoker-tooling.test.sh |
| 4 | Shrink `tests.unhermetic_sites` to zero for the unit | config/registry/tests.json |
| 5 | Retro | docs/units/engine-test-support/retro.md |

3 and 4 are independent. Targeted tests: the two script tests; `scripts/structure-check`. Final: one `gate-dev`.
Known base defects: `script-tests` wall time over `battery.unit_time_limit` (owner engine-battery / the tests'
speed, not loosened); `gate-db.test.sh` has the same partial-copy shape (owned by another unit).
