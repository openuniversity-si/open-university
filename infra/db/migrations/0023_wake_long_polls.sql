-- PORT-LONG-POLL (PADRAO-DEV F8b, D-065: the flow runs on events, never a clock): two reads of the port that clients asked
-- on an interval become long polls (port.long_poll, ?wait_s=N, the bound of GET /v1/deploy/canary/<id>), and each needs
-- the event that ends its wait. A NOTIFY nobody listens to costs nothing; a lost one costs the long poll's own bound
-- (at most canary.WAIT_MAX_S), never a verdict: the reader reads what changed from the tables, as every wake does.
--
-- Channel tower_jobs: a job's state or version changed (GET /v1/jobs/<id>). Every state a job takes is an update of
-- work.job, so this covers the transitions no event of migration 0006 notifies: run.running, run.waiting (a limit's
-- hold, migration 0007) and a waiting job queued again. The payload is the job's id.
create or replace function work.wake_job() returns trigger language plpgsql as $$
begin
  perform pg_notify('tower_jobs', new.id::text);
  return null;
end $$;
drop trigger if exists wake_job on work.job;
create trigger wake_job after update of state, version on work.job for each row
  when (old.state is distinct from new.state or old.version is distinct from new.version)
  execute function work.wake_job();

-- Channel tower_status: an event GET /v1/deploy/status answers was recorded, above all the service's
-- platform.deploy.observed (autodeploy.observe), which woke nobody. Its own channel, not tower_deploy: the autodeploy look,
-- the drill look, the prune and the runner listen to tower_deploy, and an observation is their output, not their input.
-- The payload is the event's type.
create or replace function log.wake_status() returns trigger language plpgsql as $$
begin
  perform pg_notify('tower_status', new.type);
  return null;
end $$;
drop trigger if exists wake_status on log.event;
create trigger wake_status after insert on log.event for each row
  when (new.type like 'platform.deploy.%' or new.type in ('platform.runner.warm', 'platform.ecs.task_stopped',
                                                          'platform.ecs.service_action', 'platform.config.observed'))
  execute function log.wake_status();
