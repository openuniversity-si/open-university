-- The dispatch of the infrastructure's service (INFRA-SVC 3, P3 F3): the mechanisms that 0001's functions leave to the
-- service, each one statement or one function so a transition and its event are one transaction (ARQUITETURA-ALVO §3).

-- The jobs a queue may dispatch now, in the order of its policy: work.next_job's rule, also skipping a job whose
-- exclusive key a running or waiting job holds, so one landing that waits for its branch never stops the jobs behind it.
create function work.candidates(p_tenant uuid, p_queue text, p_limit int) returns setof uuid language sql stable as $$
  select j.id from work.job j join work.queue q on q.tenant_id = j.tenant_id and q.name = j.queue
  where j.tenant_id = p_tenant and j.queue = p_queue and j.state = 'queued'
    and (j.not_before is null or j.not_before <= now())
    and not exists (select 1 from work.dependency d join work.job o on o.id = d.depends_on
                    where d.job_id = j.id
                      and not (o.state = 'succeeded' or (d.condition = 'ended'
                               and o.state in ('succeeded','failed','stopped','cancelled'))))
    and (j.exclusive_key is null or not exists (select 1 from work.job held where held.exclusive_key = j.exclusive_key
                                                and held.state in ('running','waiting')))
  order by case when q.policy = 'rank' then -coalesce(j.rank, '-Infinity'::numeric) end nulls last,
           case when q.policy = 'deadline' then j.deadline end nulls last,
           j.id
  limit p_limit $$;

-- The end of a run, fenced by its lease: a run whose lease is gone (it expired and the job went to another run) changes
-- nothing and answers null. Otherwise the slot goes back to its executor, work.finish_run applies the job's retry policy
-- (a job a limit stopped or its tenant cancelled while it ran keeps that state), a memoized success with its signature
-- enters the cache, and run.ended records it.
create function work.end_run(p_run uuid, p_fence bigint, p_outcome text, p_error text, p_result jsonb,
                             p_signature bytea) returns text language plpgsql as $$
declare r work.run; j work.job; next_state text;
begin
  select * into r from work.run where id = p_run for update;
  select * into j from work.job where id = r.job_id for update;
  if r.id is null or r.state = 'ended' or j.lease_run_id is distinct from p_run or j.fencing_token <> p_fence then
    return null;
  end if;
  update work.capacity set in_use = greatest(in_use - 1, 0) where executor = r.executor and account = r.account;
  if p_result is not null then
    update work.job set result = p_result where id = j.id;
  end if;
  if j.state in ('stopped', 'cancelled') then
    update work.run set state = 'ended', outcome = p_outcome, error_type = p_error where id = p_run;
    next_state := j.state;
  else
    next_state := work.finish_run(p_run, p_outcome, p_error);
  end if;
  update work.job set lease_run_id = null, lease_expires_at = null where id = j.id;
  if p_outcome = 'succeeded' and j.memoize and p_result is not null and p_signature is not null then
    insert into work.result_cache (executor, input_digest, result, signature)
    values (r.executor, j.input_digest, p_result, p_signature) on conflict (executor, input_digest) do nothing;
  end if;
  insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
  values ('run.ended:' || p_run, j.tenant_id, 'run.ended', clock_timestamp(), 'dispatcher', 'job/' || j.id,
          jsonb_build_object('job_id', j.id, 'run_id', p_run, 'n', r.n, 'executor', r.executor, 'outcome', p_outcome,
                             'error_type', p_error, 'state', next_state));
  return next_state;
end $$;

-- What an executor relays about a run it holds, fenced like the end: run.running, run.waiting (the job waits for
-- something from outside), run.reported (its raw account) or run.usage (a meter and a quantity, which the limits sum).
create function work.relay_run(p_run uuid, p_fence bigint, p_type text, p_payload jsonb) returns boolean
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
    update work.job set state = substr(p_type, length('run.') + 1), version = version + 1 where id = j.id;
  end if;
  insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
  values (p_type || ':' || p_run || ':' || md5(p_payload::text || clock_timestamp()::text), j.tenant_id, p_type,
          clock_timestamp(), r.executor, 'job/' || j.id,
          p_payload || jsonb_build_object('job_id', j.id, 'run_id', p_run, 'executor', r.executor));
  return true;
end $$;

-- A lease that expired: its executor vanished, so its run ends lost and the job is dispatched again without spending an
-- attempt (work.finish_run's durability); a job a limit stopped or its tenant cancelled only gets its slot back. Answers
-- the jobs whose lease it ended.
create function work.reap() returns setof uuid language plpgsql as $$
declare j work.job;
begin
  for j in select * from work.job where lease_run_id is not null and lease_expires_at < clock_timestamp()
           order by lease_expires_at for update skip locked loop
    if work.end_run(j.lease_run_id, j.fencing_token, 'lost', 'lease_expired', null, null) is not null then
      return next j.id;
    end if;
  end loop;
end $$;
