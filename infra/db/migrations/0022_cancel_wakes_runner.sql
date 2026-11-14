-- CANCEL-WAKES-RUNNER (criterion 3: the delivery's gate, p99 10 s): a job cancelled while it runs is heard by its runner at
-- once, not at the keeper's next renewal (every 60 s). A full run's test taken back for a gate's job (mechanisms.PREEMPT) kept
-- its slot until then: #684's artifact job (13/11 19:36 UTC) waited 82.6 s for a slot and ran 2.2 s. job.cancelled now
-- notifies tower_runs too, which the runner's process listens to (runner.watch_cancels); tower_work, the dispatcher's, as
-- before. Idempotent: the function is replaced, the trigger and its types stay.
create or replace function log.wake() returns trigger language plpgsql as $$
begin
  perform pg_notify(case when new.type = 'run.started' then 'tower_runs' else 'tower_work' end, new.type);
  if new.type = 'job.cancelled' then
    perform pg_notify('tower_runs', new.type);
  end if;
  return null;
end $$;
