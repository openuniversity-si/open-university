-- IMAGE-SWAP-DB-LOAD (docs/operations/aws.md 22.9): no scan of the whole log at the swap's moment. log.event's only
-- index was its primary key (occurred_at, event_id), so every read by type (the autodeploy and prewarm looks the
-- landing's commit wakes, GET /v1/deploy/status, the port's BASE_HEAD) and every idempotency check by event_id read the
-- whole month's partition, all at once with the TAKE and the first dispatch on a db.t4g.micro. EXPLAIN ANALYZE on 2
-- million events (local Postgres, aws.md 22.9; scripts/tests/test_infra_swap_db_load.py pins the plans): PUSHES 249 ->
-- 130 ms, LEDGER 254 -> 17, STANDBYS 218 -> 7, prewarm RECORD 132 -> 0.2, config OBSERVE 127 -> 0.3, LANDED_SWAP 18 ->
-- 1.6; the TAKE 12 -> 0.03 ms and the dispatcher's reap and wake 19 and 22 -> 0.2 ms with 150 thousand jobs. An index
-- on the partitioned parent is made on every partition, and on each new one the service creates
-- (migrations.PARTITIONS). Additive. The lock: the migration runs in one transaction, so not CONCURRENTLY; building
-- takes a SHARE lock on each partition, which holds the log's writers (reads go on) while it builds, ~1.5 s per index
-- per 2 million events on local Postgres, on the slow path's start of a new task.
create index if not exists event_type_at on log.event (type, occurred_at);
create index if not exists event_by_id on log.event (event_id);
-- the runner's TAKE (state starting), the dispatcher's reap (leases) and wake_held (waiting): the few open rows only
create index if not exists run_starting on work.run (id) where state = 'starting';
create index if not exists job_leased on work.job (lease_expires_at) where lease_run_id is not null;
create index if not exists job_waiting on work.job (id) where state = 'waiting';
