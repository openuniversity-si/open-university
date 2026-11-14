-- The merge train (TRAIN-FRONT-FIRST; docs/operations/aws.md, delivery): one queue of deliveries per base branch, in the order
-- they started. Only the front may land; a delivery leaves it by landing or by leaving (red, given up, removed), and either
-- is an event: a row update here that NOTIFYs tower_train, and a platform.train.* row in the log. A waiting delivery blocks
-- on that notification through the port (POST /v1/train/wait, server-side LISTEN), never on a timer. Additive and idempotent.
create table if not exists work.train (
  id        bigserial primary key,
  tenant_id uuid not null references work.tenant (id),
  base      text not null check (length(base) > 0),
  pr        text not null check (length(pr) > 0),
  head      text not null,
  files     jsonb not null default '[]'::jsonb,
  joined_at timestamptz not null default clock_timestamp(),
  ended_at  timestamptz,
  ended     text check (ended in ('landed', 'left')),
  reason    text,
  check ((ended_at is null) = (ended is null))
);
create unique index if not exists train_one_open on work.train (tenant_id, base, pr) where ended_at is null;
create index if not exists train_order on work.train (tenant_id, base, id);

create or replace function work.wake_train() returns trigger language plpgsql as $$
begin
  perform pg_notify('tower_train', new.base);
  return null;
end $$;
drop trigger if exists wake_train on work.train;
create trigger wake_train after insert or update on work.train
  for each row execute function work.wake_train();
