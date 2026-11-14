-- RUNNER-OWN-LOGIN (architecture review, finding 14; docs/operations/aws.md 22.9). The runner runs a pull request's
-- checks as the user of its own process, and that process connected as the service's login, the owner of every table:
-- a check could write any row (a job, a pointer to any image, a tenant's token, the log). The runner gets a login of
-- its own, tower_runner (the owner's step creates it, tower_infra.dbinit), that owns nothing and may do only what a
-- runner does:
--   * take, relay, renew and end a run, through the owner's functions (security definer), fenced by the lease as before:
--     work.take_run (the runner's TAKE, which locks the run it picks and so needs more than a read), work.relay_run,
--     work.renew_lease, work.end_run;
--   * say in the log what a runner's process says, and nothing else (log.runner_says: the platform's events of its
--     process, its warm-up, its swap, its reload and its succession; never a job's, a run's, a landing's or a swap's);
--   * beat as a runner (work.standby_beat, role runner only);
--   * hand a pointer back: empty a live-image pointer, never set one (work.config_value);
--   * read what its gate reads (the pointers and the settings, the beats, the log, the canary's job).
-- The guards are triggers that fire only for that login (WHEN current_user = 'tower_runner'): the service, the owner,
-- pays nothing and is bound by none, and inside the owner's functions current_user is the owner. The grants are a
-- function, work.grant_runner(), called after every migration pass (tower_infra.migrations): the login may be created
-- after this migration is applied. A database with no such login is as before. Additive.
alter function work.relay_run(uuid, bigint, text, jsonb) security definer set search_path = work, log, pg_catalog;
alter function work.renew_lease(uuid, bigint, interval) security definer set search_path = work, log, pg_catalog;
alter function work.end_run(uuid, bigint, text, text, jsonb, bytea) security definer set search_path = work, log, pg_catalog;

-- The runner's TAKE (tower_infra.runner.TAKE, statement for statement): the next handed-over run of the adapter's
-- executors, locked, now running under this runner; no row when there is none.
create function work.take_run(p_adapter text, p_runner text)
returns table (id text, job_id text, fencing_token bigint, input_uri text, input_digest text, executor text, n int, taken boolean)
language sql security definer set search_path = work, log, pg_catalog as $$
  with picked as (
    select r.id, r.job_id, j.fencing_token, j.input_uri, j.input_digest, r.executor, r.n
    from work.run r join work.job j on j.id = r.job_id and j.lease_run_id = r.id
    join work.executor e on e.name = r.executor
    where r.state = 'starting' and e.adapter = p_adapter and j.lease_expires_at > clock_timestamp()
    order by r.id limit 1 for update of r skip locked)
  select id::text, job_id::text, fencing_token, input_uri, input_digest, executor, n,
         work.relay_run(id, fencing_token, 'run.running', jsonb_build_object('runner', p_runner))
  from picked $$;

-- FIRST-JOB-REHEARSED, for a login that may insert nothing: a job of no one through the runner's whole path (taken,
-- a usage relayed, the lease renewed, ended), on a tenant, a queue, an executor and a slot of its own, all undone
-- before it returns (the block's exception: a subtransaction), whatever the caller's transaction does next. Answers
-- true when every step did what the real one does.
create function work.rehearse_run(p_name text) returns boolean
language plpgsql security definer set search_path = work, log, pg_catalog as $$
declare t uuid; j uuid; r uuid; f bigint; ok boolean := false;
begin
  if p_name !~ '^rehearsal-[0-9a-f]{1,30}$' then
    raise exception 'not a rehearsal''s name: %', p_name;
  end if;
  begin
    insert into work.tenant (name) values (p_name) returning id into t;
    insert into work.queue (tenant_id, name, policy) values (t, p_name, 'rank');
    insert into work.executor (name, adapter, tenant_id) values (p_name, p_name, t);
    insert into work.capacity (executor, account, slots, in_use) values (p_name, 'rehearsal', 1, 1);  -- its slot, taken
    insert into work.job (tenant_id, queue, executor, input_uri, input_digest)
    values (t, p_name, p_name, 'data:application/json;base64,e30=', 'sha256:' || p_name) returning id into j;
    insert into work.run (job_id, n, executor, account, state) values (j, 1, p_name, 'rehearsal', 'starting')
    returning id into r;  -- as the dispatcher's claim leaves it: the run starting, the job leased to it
    update work.job set state = 'running', lease_run_id = r, lease_expires_at = clock_timestamp() + interval '5 minutes',
                        fencing_token = fencing_token + 1, version = version + 1 where id = j;
    select fencing_token into f from work.take_run(p_name, p_name) where id = r::text and taken;
    ok := f is not null
      and work.relay_run(r, f, 'run.usage', jsonb_build_object('meter', 'cpu_s', 'quantity', 0))
      and work.renew_lease(r, f, interval '5 minutes') = 'running'
      and work.end_run(r, f, 'succeeded', null, jsonb_build_object('exit', 0), null) = 'succeeded';
    raise exception using errcode = 'RHRSL', message = 'the rehearsal is undone';
  exception when sqlstate 'RHRSL' then
    null;
  end;
  return ok;
end $$;

-- What a runner's process says in the log: the installation's events of its own process, and its lifecycle in the
-- configuration tenant; any other type, or an event in the name of another producer's subject, is refused.
create function log.runner_says() returns trigger language plpgsql as $$
begin
  if new.type not in ('platform.deploy.image_live', 'platform.deploy.image_reload', 'platform.deploy.image_retired',
                      'platform.deploy.successor', 'platform.deploy.task_up', 'platform.runner.warm',
                      'platform.process.started', 'platform.process.stopped', 'platform.process.error') then
    raise exception 'the runner''s login may not write a % event', new.type using errcode = '42501';
  end if;
  return new;
end $$;
create trigger runner_says before insert on log.event for each row
  when (current_user = 'tower_runner') execute function log.runner_says();

create function work.runner_beats() returns trigger language plpgsql as $$
begin
  if (tg_op <> 'DELETE' and new.role <> 'runner') or (tg_op <> 'INSERT' and old.role <> 'runner') then
    raise exception 'the runner''s login beats as a runner only' using errcode = '42501';
  end if;
  if tg_op = 'DELETE' then
    return old;
  end if;
  return new;
end $$;
create trigger runner_beats before insert or update or delete on work.standby_beat for each row
  when (current_user = 'tower_runner') execute function work.runner_beats();

-- A handback (tower_infra.live_image.EMPTY): a live-image pointer emptied, its version one more; nothing else of a
-- setting changes by this login, and no other setting at all.
create function work.runner_hands_back() returns trigger language plpgsql as $$
begin
  if new.key not in ('deploy.live_image_service', 'deploy.live_image_runner') or new.key <> old.key
     or new.tenant_id <> old.tenant_id or new.value <> '""'::jsonb or new.version <> old.version + 1 then
    raise exception 'the runner''s login may only empty a live-image pointer' using errcode = '42501';
  end if;
  return new;
end $$;
create trigger runner_hands_back before update on work.config_value for each row
  when (current_user = 'tower_runner') execute function work.runner_hands_back();

-- The owner's functions are the owner's and the runner's, nobody else's (a function is PUBLIC's to execute by default)
revoke all on function work.take_run(text, text), work.rehearse_run(text), work.relay_run(uuid, bigint, text, jsonb),
  work.renew_lease(uuid, bigint, interval), work.end_run(uuid, bigint, text, text, jsonb, bytea) from public;

create function work.grant_runner() returns boolean language plpgsql as $$
begin
  if not exists (select 1 from pg_roles where rolname = 'tower_runner') then
    return false;
  end if;
  grant usage on schema work, log to tower_runner;
  grant execute on function work.take_run(text, text), work.rehearse_run(text),
    work.relay_run(uuid, bigint, text, jsonb), work.renew_lease(uuid, bigint, interval),
    work.end_run(uuid, bigint, text, text, jsonb, bytea) to tower_runner;
  grant select (id, name, state) on work.tenant to tower_runner;  -- never a tenant's token
  grant select on work.config_value, work.standby_beat, work.job, log.event to tower_runner;
  grant insert on log.event to tower_runner;
  grant insert, update, delete on work.standby_beat to tower_runner;
  grant update on work.config_value to tower_runner;
  return true;
end $$;
