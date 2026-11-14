-- The limit that waits (AWS12; INFRA-SVC 3, docs/operations/aws.md 16): a meter limit whose action is `wait` holds work
-- until a time instead of stopping or refusing it. `stop` and `refuse` are unchanged. Additive and idempotent.
--
-- Semantics: a meter is cumulative (work.limits.used only grows), so the window of a wait limit is [its creation or last
-- reset, resets_at). While used >= maximum and resets_at is in the future the limit BLOCKS: the dispatcher does not claim
-- a job it covers (tenant, executor or job scope); the job goes `waiting` with wait_until = resets_at and run.waiting
-- {until, reason: limit} is logged, no run is opened and no slot is taken. A run whose usage crosses the limit while it
-- runs (not the final usage of its end) goes `waiting` the same way and keeps its slot and lease, because its session is
-- alive. When resets_at passes the window rolls (used = 0, limit.reset) and the held jobs go back to `queued`
-- (job.woken); a lifted or raised limit wakes them at once; a held run resumes through the session adapter, the path the
-- provider's throttle already uses. A capacity at in_use >= slots whose resets_at is in the future holds the jobs it
-- would serve the same way (reason capacity) and wakes them at resets_at, or when a slot frees.

alter table work.limits add column if not exists resets_at timestamptz;
do $$ declare c text;
begin
  for c in select conname from pg_constraint
           where conrelid = 'work.limits'::regclass and contype = 'c' and pg_get_constraintdef(oid) like '%stop%refuse%'
  loop
    execute format('alter table work.limits drop constraint %I', c);
  end loop;
end $$;
alter table work.limits drop constraint if exists limits_action_check;
alter table work.limits add constraint limits_action_check check (action in ('stop','refuse','wait'));
alter table work.limits drop constraint if exists limits_wait_resets;
alter table work.limits add constraint limits_wait_resets check (action <> 'wait' or resets_at is not null);

alter table work.job add column if not exists wait_until timestamptz;
alter table work.job add column if not exists wait_reason text;       -- limit | capacity, for a hold of ours; null: the provider's

-- The wait limits that block a job now (used reached, window open), for the executor it would go to.
create or replace function work.blocking_limits(p_job uuid, p_executor text) returns setof work.limits
language sql stable as $$
  select l.* from work.limits l join work.job j on j.id = p_job
  where l.tenant_id = j.tenant_id and l.action = 'wait' and l.used >= l.maximum and l.resets_at > clock_timestamp()
    and ((l.scope = 'job' and l.scope_id = j.id::text) or (l.scope = 'tenant' and l.scope_id = j.tenant_id::text)
         or (l.scope = 'executor' and l.scope_id = p_executor)) $$;

-- When the quota of the executors a job could go to comes back, if none of them has a free slot and one is waiting for
-- its reset; null otherwise.
create or replace function work.capacity_reset(p_job uuid) returns timestamptz language sql stable as $$
  select min(c.resets_at) from work.job j join work.executor e
    on e.state = 'active' and (e.tenant_id is null or e.tenant_id = j.tenant_id)
   and (j.executor = e.name
        or (j.executor is null
            and (not (j.selector ? 'any_of') or e.name in (select jsonb_array_elements_text(j.selector->'any_of')))
            and (not (j.selector ? 'adapter') or e.adapter = j.selector->>'adapter')
            and (not (j.selector ? 'capabilities') or e.capabilities @> (j.selector->'capabilities'))))
  join work.capacity c on c.executor = e.name
  where j.id = p_job and c.in_use >= c.slots and c.resets_at > clock_timestamp()
    and not exists (select 1 from work.capacity f where f.executor = e.name and f.in_use < f.slots) $$;

-- Whether a hold of ours is over: its time came, or the limit no longer blocks / a slot is free.
create or replace function work.hold_over(p_job uuid) returns boolean language plpgsql stable as $$
declare j work.job; ex text;
begin
  select * into j from work.job where id = p_job;
  if j.id is null or j.wait_reason is null or j.wait_until is null or j.wait_until <= clock_timestamp() then
    return true;
  end if;
  if j.wait_reason = 'limit' then
    ex := coalesce(j.executor, (select executor from work.run where id = j.lease_run_id), work.route(j.id));
    return not exists (select 1 from work.blocking_limits(j.id, ex));
  end if;
  return work.route(j.id) is not null;
end $$;

-- Hold a queued job: waiting until the reset of the limit that blocks it (p_executor given) or of the capacity that
-- has none free (p_executor null). Answers the time, or null when nothing holds it. No run, no slot.
create or replace function work.hold_job(p_job uuid, p_executor text) returns timestamptz language plpgsql as $$
declare j work.job; l work.limits; until_at timestamptz; why text;
begin
  select * into j from work.job where id = p_job and state = 'queued' for update skip locked;
  if j.id is null then return null; end if;
  if p_executor is not null then
    select * into l from work.blocking_limits(p_job, p_executor) order by resets_at desc limit 1;
    if l.id is not null then until_at := l.resets_at; why := 'limit'; end if;
  else
    until_at := work.capacity_reset(p_job); why := 'capacity';
  end if;
  if until_at is null then return null; end if;
  update work.job set state = 'waiting', wait_until = until_at, wait_reason = why, version = version + 1 where id = j.id;
  insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
  values ('run.waiting:job:' || j.id || ':' || (j.version + 1), j.tenant_id, 'run.waiting', clock_timestamp(),
          'dispatcher', 'job/' || j.id,
          jsonb_build_object('job_id', j.id, 'until', until_at, 'reason', why, 'limit_id', l.id));
  return until_at;
end $$;

-- A wait limit whose window passed starts over: its usage is zero again. Answers how many it rolled.
create or replace function work.roll_limits() returns int language plpgsql as $$
declare l work.limits; n int := 0;
begin
  for l in select * from work.limits where action = 'wait' and resets_at <= clock_timestamp() and used > 0
           order by id for update skip locked loop
    update work.limits set used = 0 where id = l.id;
    insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
    values ('limit.reset:' || l.id || ':' || l.resets_at, l.tenant_id, 'limit.reset', clock_timestamp(), 'dispatcher',
            'limit/' || l.id, jsonb_build_object('limit_id', l.id, 'meter', l.meter, 'used', l.used));
    n := n + 1;
  end loop;
  return n;
end $$;

-- The jobs we held (queued work, no run) whose hold is over go back to queued. Answers their ids.
create or replace function work.wake_held() returns setof uuid language plpgsql as $$
declare j work.job;
begin
  for j in select * from work.job where state = 'waiting' and lease_run_id is null and wait_reason is not null
           order by id for update skip locked loop
    if work.hold_over(j.id) then
      update work.job set state = 'queued', wait_until = null, wait_reason = null, version = version + 1 where id = j.id;
      insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
      values ('job.woken:' || j.id || ':' || (j.version + 1), j.tenant_id, 'job.woken', clock_timestamp(),
              'dispatcher', 'job/' || j.id, jsonb_build_object('job_id', j.id, 'reason', j.wait_reason));
      return next j.id;
    end if;
  end loop;
end $$;

-- A run resumed no longer waits on our hold (the provider's own wait carries no wait_until).
create or replace function work.relay_run(p_run uuid, p_fence bigint, p_type text, p_payload jsonb) returns boolean
language plpgsql as $$
declare r work.run; j work.job;
begin
  select * into r from work.run where id = p_run;
  select * into j from work.job where id = r.job_id;
  if r.id is null or r.state = 'ended' or j.lease_run_id is distinct from p_run or j.fencing_token <> p_fence
     or p_type not in ('run.running', 'run.waiting', 'run.reported', 'run.usage') then
    return false;
  end if;
  if p_type in ('run.running', 'run.waiting') and j.state in ('running', 'waiting') then
    update work.run set state = substr(p_type, length('run.') + 1) where id = p_run;
    update work.job set state = substr(p_type, length('run.') + 1), version = version + 1,
                        wait_until = case when p_type = 'run.running' then null else wait_until end,
                        wait_reason = case when p_type = 'run.running' then null else wait_reason end
    where id = j.id;
  end if;
  insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
  values (p_type || ':' || p_run || ':' || md5(p_payload::text || clock_timestamp()::text), j.tenant_id, p_type,
          clock_timestamp(), r.executor, 'job/' || j.id,
          p_payload || jsonb_build_object('job_id', j.id, 'run_id', p_run, 'executor', r.executor));
  return true;
end $$;

-- The usage counter of 0001 plus the wait: a run whose usage crosses an open wait limit waits until its reset (its
-- final usage, flagged by the adapter, only counts: the run is ending).
create or replace function work.count_usage() returns trigger language plpgsql as $$
declare j work.job; ex text; l record; m record;
begin
  if new.type <> 'run.usage' then return new; end if;
  select * into j from work.job where id = (new.payload->>'job_id')::uuid;
  ex := coalesce(new.payload->>'executor', j.executor);
  for m in select new.payload->>'meter' as meter, (new.payload->>'quantity')::numeric as q
           union all
           select r.derived_meter, (new.payload->>'quantity')::numeric * r.rate from work.meter_rate r
           where r.tenant_id = j.tenant_id and r.meter = new.payload->>'meter' loop
    for l in update work.limits set used = used + m.q
             where tenant_id = j.tenant_id and meter = m.meter
               and ((scope = 'job' and scope_id = j.id::text) or (scope = 'executor' and scope_id = ex)
                    or (scope = 'tenant' and scope_id = j.tenant_id::text))
             returning * loop
      if l.used >= l.maximum and l.action = 'stop' and j.state in ('running','waiting') then
        update work.job set state = 'stopped', version = version + 1 where id = j.id;
      elsif l.used >= l.maximum and l.action = 'wait' and l.resets_at > clock_timestamp() and j.state = 'running'
            and j.lease_run_id is not null and not coalesce((new.payload->>'final')::boolean, false) then
        update work.run set state = 'waiting' where id = j.lease_run_id;
        update work.job set state = 'waiting', wait_until = l.resets_at, wait_reason = 'limit', version = version + 1
        where id = j.id;
        insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
        values ('run.waiting:' || j.lease_run_id || ':limit:' || l.id, j.tenant_id, 'run.waiting', clock_timestamp(),
                'dispatcher', 'job/' || j.id,
                jsonb_build_object('job_id', j.id, 'run_id', j.lease_run_id, 'until', l.resets_at, 'reason', 'limit',
                                   'limit_id', l.id, 'executor', ex));
        j.state := 'waiting';
      end if;
    end loop;
  end loop;
  return new;
end $$;

-- A lifted or changed limit wakes the dispatcher at once.
drop trigger if exists wake on log.event;
create trigger wake after insert on log.event for each row
  when (new.type in ('job.created', 'job.cancelled', 'run.started', 'run.ended', 'cache.hit', 'capacity.set',
                     'limit.changed'))
  execute function log.wake();
