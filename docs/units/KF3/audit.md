# KF3 audit (read-only evidence)

Base: `f02bff91` (origin/mod/roadmap-integration at launch). Premises: none confirmed from outside this repo.

## 1. gate-heavy-db.test.sh (`expected [5] got [3]`/`[4]`)
- `peak_of` starts 5 background subshells that each log `+`, `sleep 0.4`, log `-`. For an uncapped stage the expected peak is 5, which holds only if all 5 bash processes start inside one 0.4 s window. Under the script stage's parallel load on 4 vCPU the fifth job starts after the first has logged `-`, so the peak is 3 or 4.
- The expectation is therefore a function of host scheduling, not of the cap under test. The "expected value varies with CPU count" in the complaint is the same race.
- Capped cases (`2`,`1`,`3`) can under-run the same way (fewer than `slots` jobs overlapping) but a violation of the cap is what they must catch, so they need the same rendezvous.

## 2. claude-session.test.sh (psql `drop database ... with (force)` not done in 30 s)
- Already isolated: `test_db.new_name()` gives a per-run database; `test_db.destroy` terminates other backends, then drops with FORCE. So isolation and "terminate before drop" exist; the missing piece is bounding contention.
- `test-db.psql_timeout_s` = 30 (registry). Not touched: raising it is out of scope.
- Measured locally (4 vCPU, quiet): drop 0.8 s alone, 1.4 s with 8 parallel create/drop; 1.5 s with 6 concurrent 3M-row insert loads on the same cluster. The 30 s stall was NOT reproduced here, so the exact wait (checkpoint requested by CREATE/DROP DATABASE, or ProcSignalBarrier on a busy backend) is unconfirmed.
- Every create/drop of a database forces a checkpoint on the shared cluster; many tests do it in parallel. That is the one shared resource all script tests touching the cluster contend on.

## 3. Same pattern elsewhere
- Fixed-window concurrency assertions: only `peak_of` in gate-heavy-db. Other `sleep`-overlap tests to be grepped in the guard step.
- Database DDL on the shared cluster: `scripts/lib/test_db.py` is the only helper (callers: test_claude_session.py, test_test_db.py).
