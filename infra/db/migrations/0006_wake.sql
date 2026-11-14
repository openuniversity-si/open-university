-- The wake (INFRA-SVC 5; P6 F1, the 1 s path): the database says when work frees, so the dispatcher and the runner go at
-- once instead of up to a tick or a poll later. On 04/11 #306's landing waited 0.62 s of its 1.98 s from ready to landed
-- for the dispatcher's 1 s tick, and each check on the one runner waited for the tick and then for the runner's poll.
-- Channel tower_work wakes the dispatcher: a job created or cancelled, a run ended, a job served from the cache, the
-- capacity of an executor set. Channel tower_runs wakes the runner: a run started, handed over to its executor. The
-- payload is the event's type; a listener reads what to do from the tables, as before, so a lost notification costs a
-- tick, never work. Delivered at commit, and one per type in a transaction.
create function log.wake() returns trigger language plpgsql as $$
begin
  perform pg_notify(case when new.type = 'run.started' then 'tower_runs' else 'tower_work' end, new.type);
  return null;
end $$;
create trigger wake after insert on log.event for each row
  when (new.type in ('job.created', 'job.cancelled', 'run.started', 'run.ended', 'cache.hit', 'capacity.set'))
  execute function log.wake();
