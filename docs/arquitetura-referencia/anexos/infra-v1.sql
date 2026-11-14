-- A infraestrutura da fase 1 (ARQUITETURA-ALVO.md §3 e §4): só trabalho, com mecanismos parametrizáveis; os valores
-- vêm de fora. Testado no PostgreSQL 18.6 do toolchain com infra-v1-aceite.sql.
-- Dois esquemas, work e log; nada da gestão nem da liderança.
create schema work;
create schema log;

create table work.tenant (                                      -- o isolamento: quem divide a infraestrutura sem se ver
  id uuid primary key default uuidv7(),
  name text not null unique check (name ~ '^[a-z][a-z0-9-]{1,39}$'),
  state text not null default 'active' check (state in ('active','paused','retired')),
  version int not null default 1);

create table work.executor (                                    -- quem ou o que executa, por um adaptador
  name text primary key,
  adapter text not null,                                        -- o núcleo não conhece a lista de adaptadores
  tenant_id uuid references work.tenant,                        -- nulo: da instalação; senão, só daquele tenant
  config jsonb not null default '{}',                           -- o que o adaptador precisa; segredo só por referência
  capabilities jsonb not null default '{}',                     -- propriedades técnicas que um seletor pode pedir
  state text not null default 'active' check (state in ('active','paused')));

create table work.capacity (                                    -- a capacidade física: vagas, cota que zera, agenda
  executor text not null references work.executor, account text not null,
  slots int not null check (slots >= 0), in_use int not null default 0 check (in_use >= 0),
  resets_at timestamptz,
  primary key (executor, account), check (in_use <= slots));

create table work.queue (                                       -- uma fila e a política dela; os valores vêm de fora
  tenant_id uuid not null references work.tenant, name text not null,
  policy text not null default 'fifo',                          -- o módulo de ordenação: fifo, rank, deadline ou outro plugado
  config jsonb not null default '{}',                           -- os parâmetros do módulo (pesos, por exemplo)
  primary key (tenant_id, name));

create table work.job (                                         -- um trabalho: identificador, entrada opaca, estado
  id uuid primary key default uuidv7(),
  tenant_id uuid not null references work.tenant,
  queue text not null default 'default',
  rank numeric, not_before timestamptz, deadline timestamptz,   -- parâmetros de ordenação; a política da fila escolhe quais usa
  executor text references work.executor,                       -- um executor exato, ou
  selector jsonb not null default '{}',                         -- o que se pede dele: any_of em ordem, adapter, capabilities
  max_attempts int not null default 1 check (max_attempts >= 1),   -- a retentativa: o padrão é um valor, uma tentativa
  backoff_initial interval not null default '10 seconds', backoff_factor numeric not null default 2,
  backoff_max interval not null default '10 minutes',
  retry_on text[] not null default '{failed,timed_out}',        -- os desfechos que pedem outra tentativa
  non_retryable text[] not null default '{}',                   -- os tipos de erro que nunca pedem
  input_uri text not null, input_digest text not null,          -- a entrada, que só o executor lê
  idempotency_key text,                                         -- só para não criar duas vezes
  exclusive_key text,                                           -- um por vez na mesma chave (um ramo, por exemplo)
  memoize boolean not null default false,                       -- reaproveitar a saída de uma entrada idêntica
  state text not null default 'queued'
    check (state in ('queued','running','waiting','succeeded','failed','stopped','cancelled')),
  result jsonb,                                                 -- a saída, como o executor a produziu
  lease_run_id uuid, lease_expires_at timestamptz, fencing_token bigint not null default 0,
  attempts int not null default 0,
  version int not null default 1,
  unique (tenant_id, idempotency_key), unique (tenant_id, id),
  foreign key (tenant_id, queue) references work.queue,
  check (executor is not null or selector <> '{}'::jsonb));
create index job_queued on work.job (tenant_id, queue, id) where state = 'queued';

create table work.dependency (                                  -- um trabalho espera outro, do mesmo tenant
  tenant_id uuid not null, job_id uuid not null, depends_on uuid not null,
  condition text not null default 'succeeded' check (condition in ('succeeded','ended')),
  primary key (job_id, depends_on), check (job_id <> depends_on),
  foreign key (tenant_id, job_id) references work.job (tenant_id, id),
  foreign key (tenant_id, depends_on) references work.job (tenant_id, id));
create unique index job_exclusive on work.job (exclusive_key)
  where state in ('running','waiting') and exclusive_key is not null;

create table work.run (                                         -- cada despacho do trabalho ao executor
  id uuid primary key default uuidv7(), job_id uuid not null references work.job, n int not null,
  executor text not null references work.executor, account text,
  external_id text,                                             -- a sessão, a tarefa do contêiner, o chamado
  state text not null check (state in ('starting','running','waiting','ended')),
  outcome text check (outcome in ('succeeded','failed','timed_out','stopped','lost','cancelled')),
  error_type text,                                              -- como o adaptador o nomeou
  unique (job_id, n));

create table work.limits (                                      -- o mecanismo de limite; o valor vem de quem o define
  id uuid primary key default uuidv7(), tenant_id uuid not null references work.tenant,
  scope text not null check (scope in ('tenant','executor','job')), scope_id text not null,
  meter text not null,                                          -- o que o adaptador relata; o núcleo não escolhe
  maximum numeric not null check (maximum >= 0), used numeric not null default 0,
  action text not null check (action in ('stop','refuse')),
  unique (tenant_id, scope, scope_id, meter));

create table work.meter_rate (                                  -- converte um medidor em outro (tokens em dólares, por exemplo)
  tenant_id uuid not null references work.tenant, meter text not null, derived_meter text not null,
  rate numeric not null check (rate >= 0), primary key (tenant_id, meter, derived_meter));

create table work.result_cache (                                -- a saída de entrada idêntica, assinada pelo executor
  executor text not null references work.executor, input_digest text not null,
  result jsonb not null, signature bytea not null, stored_at timestamptz not null default now(),
  primary key (executor, input_digest));

create table log.event (                                        -- tudo o que a infraestrutura observa, bruto
  event_id text not null, tenant_id uuid references work.tenant,   -- nulo: da própria plataforma
  type text not null, occurred_at timestamptz not null,
  producer text not null, subject text not null, correlation_id text, causation_id text,
  payload jsonb not null, published_at timestamptz,
  primary key (occurred_at, event_id)) partition by range (occurred_at);
create table log.event_2026_11 partition of log.event for values from ('2026-11-01') to ('2026-12-01');
create table log.received (event_id text primary key, received_at timestamptz not null default now());
create table log.subscription (                                 -- o fluxo assinável, e até onde cada um já leu
  id uuid primary key default uuidv7(), tenant_id uuid not null references work.tenant,
  sink text not null, types text[] not null default '{}', read_until timestamptz,
  state text not null default 'active' check (state in ('active','paused')));

-- O isolamento: um executor privado serve só ao tenant dele.
create function work.job_executor_isolated() returns trigger language plpgsql as $$
begin
  if new.executor is not null and exists (select 1 from work.executor e where e.name = new.executor
             and e.tenant_id is not null and e.tenant_id <> new.tenant_id) then
    raise exception 'executor "%" belongs to another tenant', new.executor;
  end if;
  return new;
end $$;
create trigger job_executor_isolated before insert or update of executor, tenant_id on work.job
  for each row execute function work.job_executor_isolated();

-- O limite que recusa: um trabalho novo não entra quando um limite de recusa do tenant ou do executor já passou.
create function work.refuse_over_limit() returns trigger language plpgsql as $$
begin
  if exists (select 1 from work.limits l where l.tenant_id = new.tenant_id and l.action = 'refuse'
             and l.used >= l.maximum
             and ((l.scope = 'tenant' and l.scope_id = new.tenant_id::text)
                  or (l.scope = 'executor' and l.scope_id = coalesce(new.executor, '')))) then
    raise exception 'a refuse limit of tenant % is reached', new.tenant_id;
  end if;
  return new;
end $$;
create trigger refuse_over_limit before insert on work.job for each row execute function work.refuse_over_limit();

-- Só o que a infraestrutura observa entra no registro.
create function log.observed_type() returns trigger language plpgsql as $$
begin
  if new.type !~ '^(job|run|executor|capacity|limit|cache|forge|platform)\.' then
    raise exception 'event type "%" is not something the infrastructure observes', new.type;
  end if;
  return new;
end $$;
create trigger observed_type before insert on log.event for each row execute function log.observed_type();

-- O limite que para: um uso relatado soma nos limites daquele medidor; ao passar o máximo, o trabalho para.
create function work.count_usage() returns trigger language plpgsql as $$
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
      end if;
    end loop;
  end loop;
  return new;
end $$;
create trigger count_usage after insert on log.event for each row execute function work.count_usage();

-- O mecanismo de ordenação: entre os trabalhos prontos de uma fila, o próximo pela política dela.
create function work.next_job(p_tenant uuid, p_queue text) returns uuid language sql stable as $$
  select j.id from work.job j join work.queue q on q.tenant_id = j.tenant_id and q.name = j.queue
  where j.tenant_id = p_tenant and j.queue = p_queue and j.state = 'queued'
    and (j.not_before is null or j.not_before <= now())
    and not exists (select 1 from work.dependency d join work.job o on o.id = d.depends_on
                    where d.job_id = j.id
                      and not (o.state = 'succeeded' or (d.condition = 'ended'
                               and o.state in ('succeeded','failed','stopped','cancelled'))))
  order by case when q.policy = 'rank' then -coalesce(j.rank, '-Infinity'::numeric) end nulls last,
           case when q.policy = 'deadline' then j.deadline end nulls last,
           j.id
  limit 1 $$;

-- O mecanismo de roteamento: o executor exato, ou o primeiro que o seletor aceita e tem vaga.
create function work.route(p_job uuid) returns text language sql stable as $$
  with j as (select * from work.job where id = p_job),
  candidates as (
    select e.name, coalesce(array_position(array(select jsonb_array_elements_text(j.selector->'any_of')), e.name), 0) as pos
    from work.executor e, j
    where e.state = 'active' and (e.tenant_id is null or e.tenant_id = j.tenant_id)
      and (j.executor = e.name
           or (j.executor is null
               and (not (j.selector ? 'any_of') or e.name in (select jsonb_array_elements_text(j.selector->'any_of')))
               and (not (j.selector ? 'adapter') or e.adapter = j.selector->>'adapter')
               and (not (j.selector ? 'capabilities') or e.capabilities @> (j.selector->'capabilities'))))
      and exists (select 1 from work.capacity c where c.executor = e.name and c.in_use < c.slots))
  select name from candidates order by pos, name limit 1 $$;

-- O mecanismo de retentativa: o desfecho de uma execução, a política do trabalho e o próximo estado.
create function work.finish_run(p_run uuid, p_outcome text, p_error text) returns text language plpgsql as $$
declare r work.run; j work.job; wait interval;
begin
  update work.run set state = 'ended', outcome = p_outcome, error_type = p_error where id = p_run returning * into r;
  select * into j from work.job where id = r.job_id;
  if p_outcome = 'lost' then                                    -- o executor sumiu: durabilidade, sem contar tentativa
    update work.job set state = 'queued', version = version + 1 where id = j.id;
    return 'queued';
  end if;
  update work.job set attempts = attempts + 1 where id = j.id returning * into j;
  if p_outcome = any (j.retry_on) and not (coalesce(p_error, '') = any (j.non_retryable))
     and j.attempts < j.max_attempts then
    wait := least(j.backoff_initial * power(j.backoff_factor, j.attempts - 1), j.backoff_max);
    update work.job set state = 'queued', not_before = now() + wait, version = version + 1 where id = j.id;
    return 'queued';
  end if;
  update work.job set state = case p_outcome when 'succeeded' then 'succeeded' when 'stopped' then 'stopped'
                                             when 'cancelled' then 'cancelled' else 'failed' end,
                      version = version + 1 where id = j.id;
  return (select state from work.job where id = j.id);
end $$;
