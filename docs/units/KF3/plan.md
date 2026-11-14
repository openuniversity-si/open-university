# KF3 plan

## Commits (dependency graph; no file owned by two commits)
1. audit.md (done).
2. plan.md (this file).
3. **gate-heavy-db rendezvous** — owns `scripts/tests/gate-heavy-db.test.sh`, `config/registry/gate.json` (new key `gate.script_test_rendezvous_wait_s`). Peak counted at a rendezvous: each job waits until `min(slots, jobs)` are live (event-driven), then holds briefly so a cap violation can still show; no fixed 0.4 s overlap window. Deadline from the registry.
4. **test_db contention + diagnostics** — owns `scripts/lib/test_db.py`, `config/registry/test-db.json`, `scripts/tests/test_test_db.py`. Create/destroy take a machine-wide `flock` (path and wait from the registry) so checkpoint-forcing DDL on the shared cluster does not stack; on a psql timeout the error carries `pg_stat_activity` wait events so a recurrence names its cause. The 30 s limit is NOT changed.
5. **guard** — owns new `scripts/tests/hermetic-expectations.test.sh` (+ `.py`) and `scripts/lib/gate-script-tests.json`. Fails when a script test derives a value from the host (`nproc`, `cpu_count`, `getconf _NPROCESSORS`, `/proc/cpuinfo`, `loadavg`) without a `# host-ok: <reason>` marker on that line. Existing use: merge-phase.test.sh:300 (parallelism limit only) gets the marker.
6. retro.md.
Commits 3, 4, 5 are independent (disjoint files) and run in parallel; gate-script-tests.json is touched only by 5 (3 and 4 are already covered there).

## Premises
- P1 (CRITICAL? no): the 30 s stall is contention on the shared cluster (checkpoint of CREATE/DROP DATABASE). NOT reproduced locally (drop ≤ 1.5 s with 8 parallel and 6 write loads). Blast radius: if wrong, commit 4 reduces but may not remove the stall; the diagnostics then name the real wait on the next occurrence (that would be an incident, reported in the PR).
- P2: heavy-db flake is purely the fixed overlap window (certain: the code has no other source of variance).
- P3: no registry key may be a literal in code (No-literals check).

## Tests
- Per commit: `scripts/run test gate-heavy-db`, `python3 scripts/tests/test_test_db.py`, new hermetic-expectations test. Final: `scripts/gate-dev` x3 on the head, plus a CPU-starved local run of gate-heavy-db (loop with `taskset`/stress) as the measured proof.

## Known base defects expected
None beyond the two named; owners none.
