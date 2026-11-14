-- The merge train's lease (TRAIN-LEASE; docs/operations/aws.md, delivery): every open entry holds a lease its own delivery
-- renews on each of its events (joined, checks started, checks decided, each long poll it asks). An entry whose lease ran out
-- is a dead delivery: the port marks it `expired` (an event, platform.train.expired) when a join, wait, renew or end arrives
-- or the long poll hits its safety timeout, and the next waiter is woken by the NOTIFY. The lease is a safety for a dead
-- process, never a clock the live ones follow. The trigger now fires on insert and on ended_at only, so a renewal wakes nobody.
-- Additive and idempotent.
alter table work.train add column if not exists lease_until timestamptz;
update work.train set lease_until = clock_timestamp() + interval '900 seconds' where ended_at is null and lease_until is null;
alter table work.train drop constraint if exists train_ended_check;
alter table work.train add constraint train_ended_check check (ended in ('landed', 'left', 'expired'));
drop trigger if exists wake_train on work.train;
create trigger wake_train after insert or update of ended_at on work.train
  for each row execute function work.wake_train();
