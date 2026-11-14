-- IMAGE-SWAP-TIGHTEN (docs/operations/aws.md 22.9): the standbys' heartbeat as data. Each process that stands by under
-- the live-image gate (tower_infra.live_image: a prewarm standby, or an ECS task under a pointer naming another digest)
-- upserts its last beat here on every standby pass (about a second), on the same database round trip that proved it
-- healthy. The landing (POST /v1/deploy/landed, port.deploy_landed) swaps the pointers in the statement that records it
-- only when both roles have a beat of the bundle within deploy.standby_fresh_s: database evidence, no AWS call on the
-- clock. A beat older than a day is deleted by the next beat. Additive.
create table if not exists work.standby_beat (
  role    text not null check (role in ('runner', 'service')),
  digest  text not null check (length(digest) > 0),
  task    text not null,
  beat_at timestamptz not null default clock_timestamp(),
  primary key (role, digest, task)
);
