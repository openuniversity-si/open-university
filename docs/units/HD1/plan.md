# HD1 plan

Deadline: green on the exact head and 0 behind `mod/roadmap-integration` by 14:30 UTC 2026-10-27; coordinator merges.

## Commits (dependency graph; no file owned by two parallel commits)
1. audit.md.
2. plan.md (this file).
3. **rest fake readiness (class fix)** — owns new `scripts/tests/lib/rest-fake.sh`, `scripts/tests/rest_fake.py` (atomic port file), `scripts/tests/gate-db.test.sh`, `scripts/tests/invoker-tooling.test.sh`, `scripts/tests/merge-phase.test.sh`, `config/registry/delivery.json`, new `scripts/tests/rest-fake-ready.test.sh` (+ its `gate-script-tests.json` entry). One helper `rest_fake_start` waits until the port file holds a port AND a TCP connect succeeds, polling every `delivery.test_fake_start_wait_s`, up to `delivery.test_fake_ready_max_s`, failing at once if the fake exited. The attempt-count key goes away (its only reader is replaced). The new test starts the fake under artificial CPU load (busy loops on every core) and passes.
4. **hermetic gate-db** — depends on 3 (shares gate-db.test.sh). Owns new `scripts/lib/db_hermetic.py`, new `config/registry/db-hermetic.json`, `scripts/lib/gate-db.sh`, `scripts/gate-local` (record line only), `scripts/tests/gate-db.test.sh`. `db_hermetic.py mode` prints `neon` when `credentials.missing_credentials({'neon'}, ...)` is empty, else `hermetic`. Hermetic runs the SAME `neon_pr.py` functions (eligibility, release, migrate, rerun, hooks, accept) with the Neon branch source replaced by a throwaway local database from `test_db.py` on the local PostgreSQL; no stage is skipped. The record says `hermetic=pr-<n>` instead of `neon=pr-<n>`, so the frozen tail (merge-phase, ship_tail) still demands a Neon proof.
5. retro.md.

## Plan change 14:15 UTC: commit 4 is blocked outside this unit's files
`neon_pr.py` migrates with `pnpm db:migrate --target pr`, and `apps/web/scripts/lib/database-target.ts` refuses a `pr`
URL unless it is database `tower_v1`, role `tower_v1_app`, a direct `*.neon.tech` host and `sslmode=require` (lines 53-59).
No local PostgreSQL can satisfy that without weakening a production-safety guard, so a hermetic mode that keeps "the
same migrations" needs an app change first. Measured: a throwaway local database fails with
"Neon targets require database tower_v1 and role tower_v1_app." Decision (safest reversible): this PR ships commit 3
(the load-proof rest fake, a complete step), and commit 4 becomes the next HD1 step on this branch, in this order:
- 4a (app, owner of `database-target.ts`): a `hermetic` target that accepts only a loopback host and a
  `tower_test_*` database, never a Neon host, with its unit test; `pr` stays exactly as strict.
- 4b (this unit): `scripts/lib/db_hermetic.py` swaps neon_pr's branch source for a throwaway local database
  (`test_db.py`) and passes `--target hermetic`; `gate-db.sh` picks it when `credentials.missing_credentials({'neon'})`
  is non-empty; the record says `hermetic=pr-<n>`, so the frozen tail still demands a Neon proof (D-054).
  A draft of 4b exists (LocalBranches over test_db, mode probe, registry key `db-hermetic.state_dir`, a test that runs
  migrate + rerun on local PostgreSQL); it waits on 4a.

## Premises
- P-a: neon_pr's assertions only depend on the URI (read in the audit). Radius: commit 4.
- P-b: the cloud session has a local PostgreSQL (setup.sh) — verified (`postgres 18.6` in the SessionStart hook).
- P-c (CRITICAL? no): db-gate.json hooks run on an empty local database; if a hook needs R2 it fails loudly, never skipped.
- P-d: not changing what `merge-phase`/`ship_tail` accept keeps production rules unchanged (D-054). Safest reversible choice.

## Tests
- 3: `scripts/run test gate-db`, `scripts/run test merge-phase`, `scripts/run test invoker-tooling`, `scripts/run test rest-fake-ready`.
- 4: `scripts/run test gate-db` (hermetic cases call the real local PostgreSQL: migrations + rerun assertions), `scripts/run test gate-db-neon`.
- Final: one `scripts/gate-dev --pr <n>`.

## Known base defects expected
- gate-db.test.sh "rest fake did not start" (BD1 known-defect, #667) — removed by commit 3.
