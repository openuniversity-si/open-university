# ADR-34 — DB PRs: gate-dev plus a Neon DB gate, not the 3-browser battery

Accepted 2026-10-19, Daniel's decision at 18:07 BRT. Amends ADR-33's DB exception; ADR-32 is unchanged.

## Decision

Every PR runs `scripts/gate-dev --pr <n>` on its final pushed head. A PR whose actual diff matches
`gate_policy.DB_PATHS` additionally runs `scripts/gate-db --pr <n>` (= `scripts/gate-local --pr <n> --db`) on
the same head. It needs no local database and runs no browser:

1. `db:check` (schema vs. committed migrations) while the cached production build is restored;
2. a fresh disposable Neon branch `pr-<n>` from production via `scripts/neon-pr` (same 0.25 CU, 300 s autosuspend,
   3 PR / 10 total limits); it stays until merge or prune deletes it, as before;
3. migrations forward plus dry-run (0 pending), then a **second run** that must leave the migration ledger and
   a read-only schema fingerprint (`db:fingerprint`) unchanged;
4. optional data-migration hooks declared in `scripts/db-gate.json` (`dry-run`/`apply`/`verify`/`rollback`);
5. the existing acceptance: production build on the branch, health from the database, admin doctor without errors.

Branch URLs live only in child environments and are redacted from logs. The integration suite (every case) runs
on local PostgreSQL 18 in gate-dev on the same head, which merge-phase also requires.

Only success writes `<sha>.db.pass` (`kind=db`, `neon=pr-<n>`), after removing any stale record.
merge-phase reclassifies the actual diff at merge: non-DB needs `.dev.pass`; DB needs `.dev.pass` **and**
`.db.pass` with `neon=pr-<n>` on the exact head, or an exact-head full `nightly=1` record with the same Neon proof.

The full battery (3 browser projects, a11y, operational regressions, full Neon migration/acceptance) runs only in
`scripts/gate-noite` and on demand with `scripts/gate-local --pr <n> --nightly`, which keeps working.
The DB stages are added evidence: the full plan still owns every original stage and the union check is unchanged.

## Trade-off

A DB PR no longer waits for mobile/WebKit/a11y before merge; like any other PR, those regressions surface in the
end-of-day report. Database risk itself is checked more directly than before: idempotency, data hooks and the
integration suite now run on a production clone instead of only on local PostgreSQL. Time above 90 s is reported, never a failure.

**Integration on Neon is deferred.** Pointing the unchanged suite at `pr-<n>` was implemented and measured on
2026-10-19 (PR #174) and is not viable without changing tests or adding retries: the app role has no CREATEDB;
one case needs superuser `session_replication_role` (Neon grants no superuser); template clones race with sessions
invisible to the branch roles ("source database is being accessed by other users"), even serially; parallel WS
connection setup is rejected at 0.25 CU; an idle launcher session is dropped after about 280 s; and the full
suite would take about 15 minutes. Revisit only with a design that keeps every case and needs no retry.
