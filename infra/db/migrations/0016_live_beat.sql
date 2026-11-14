-- IMAGE-SWAP-FAILOVER (docs/operations/aws.md 22.9): the live beat as data. On 10/11 02:14 UTC both standbys an image-only
-- swap had promoted were interrupted by Spot (the service 26 s after the swap, the runner 3.5 min) and exited cleanly
-- with deploy.live_image_<role> still naming their bundle: the ECS tasks stood by and no job was dispatched for 23 min.
-- A process that is live because the pointer names its digest (the promoted standby; the reconciled ECS task while it
-- shares the role) stamps live_at while it works (tower_infra.live_image: the service after each good dispatch tick, the
-- runner at each TAKE and from the keeper of each run in flight). An ECS task standing by reads, in the statement of its
-- own standby beat, how old the newest live_at of the pointed digest is: past deploy.live_stale_s it empties the pointer
-- by compare-and-swap and works. beat_at stays what the landing swaps on (migration 0014). Additive.
alter table work.standby_beat add column if not exists live_at timestamptz;
