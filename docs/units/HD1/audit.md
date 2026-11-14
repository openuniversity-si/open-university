# HD1 audit (2026-10-27 13:35 UTC, base efc7f3b4)

## Brief sources verified on the base
- `scripts/gate-db` exists: 4 lines, `exec gate-local --db`.
- `scripts/gate-db.sh` does not exist; the stage list is `scripts/lib/gate-db.sh` (`gate_db_stages`), sourced by `scripts/gate-local`.
- `scripts/tests/gate-db.test.sh` exists (Neon lifecycle via a `neon-pr` stub, loopback `rest_fake.py`).
- `scripts/lib/db_hermetic.*` does not exist. `scripts/lib/hermetic.py` exists but is the unrelated test-isolation shim.

## (1) gate-db needs Neon
- Every gate-db stage after `db:check` calls `scripts/neon-pr` -> `scripts/lib/neon_pr.py`, whose `Neon` class asks the Neon API for a `pr-<n>` branch URI.
- `migrate`, `rerun`, `hooks`, `accept` only need that URI (`APP_DATABASE_URL_PR_UNPOOLED`); the assertions (dry-run after migrate, same fingerprint after a second run, hooks, health reads the database, doctor ok) are database-agnostic.
- Neon credential presence is already decided by `scripts/lib/credentials.py` (`missing_credentials({'neon'}, ...)`).
- A local PostgreSQL 18.6 on 127.0.0.1:54322 is installed by `scripts/cloud/setup.sh`; `scripts/lib/test_db.py` creates/destroys throwaway databases safely (name prefix, DDL lock).
- `gate-local` writes `neon=pr-<n>` into the `.db.pass` record; `merge-phase` and `ship_tail.py` (frozen tail, D-054) require it.

## (2) "rest fake did not start"
- `rest_fake.py` writes its port file after bind; callers poll for the file a FIXED number of times: 20 x 0.05 s = 1 s total.
- Same pattern in three suites (class): `gate-db.test.sh:59-65`, `invoker-tooling.test.sh:80-86` (literal loop), `merge-phase.test.sh:27-32` (registry keys `delivery.test_fake_start_attempts` x `delivery.test_fake_start_wait_s`).
- `rest_fake.py` writes the port with `write_text` (not atomic): a poller can see a partial port number.
- Python callers (`test_claude_session.py`, `test_forge_events.py`) read the file without the 1 s shell cap; they are outside this class.

## Fences
- BD1 #667 (defect_detect.py, defects.json): not touched; comment on #667 when the fix lands.
- AR1 (gate-areas.json), KF3 #665 (test_db, gate.json): not touched. test_db.py is used read-only (import).
