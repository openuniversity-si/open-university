-- The phase-1 acceptance test (ARQUITETURA-ALVO §10), run by scripts/tests/test_infra_db.py on a throwaway database after
-- infra/db/migrations/0001_work_log.sql. It is the annex docs/arquitetura-referencia/anexos/infra-v1-aceite.sql statement
-- for statement; the gestao_torre schema below is the test's own management, outside infra/ (D-306).
\set ON_ERROR_STOP on
create function pg_temp.ev(t text, typ text, subj text, body jsonb) returns void language sql as $$
  insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
  select gen_random_uuid()::text, (select id from work.tenant where name = t), typ, clock_timestamp(), 'core', subj, body $$;
create function pg_temp.tid(t text) returns uuid language sql as $$ select id from work.tenant where name = t $$;
create function pg_temp.jid(k text) returns uuid language sql as $$ select id from work.job where idempotency_key = k $$;
create function pg_temp.dispatch(k text) returns uuid language sql as $$
  insert into work.run (job_id, n, executor, state)
  select id, attempts + 1 + (select count(*) from work.run r where r.job_id = j.id and r.outcome = 'lost'),
         work.route(id), 'running' from work.job j where idempotency_key = k returning id $$;

insert into work.tenant (name) values ('torre'), ('livre');
insert into work.executor (name, adapter, capabilities) values
  ('script-runner', 'container', '{"root": true}'), ('claude-sub', 'agent-session', '{}'),
  ('codex-sub', 'agent-session', '{}'), ('pessoa', 'person-queue', '{}'), ('forge', 'forge', '{}');
insert into work.executor (name, adapter, tenant_id) values ('livre-own-key', 'agent-session', pg_temp.tid('livre'));
insert into work.capacity (executor, account, slots, resets_at) values
  ('script-runner', 'fargate', 4, null), ('claude-sub', 'max-1', 0, now() + interval '2 hours'),
  ('codex-sub', 'plus-1', 1, null), ('pessoa', 'daniel', 1, null), ('forge', 'origin', 1, null),
  ('livre-own-key', 'own', 1, null);

-- Cada tenant escolhe a política das suas filas; o mecanismo é o mesmo.
insert into work.queue (tenant_id, name, policy) values
  (pg_temp.tid('torre'), 'default', 'fifo'), (pg_temp.tid('torre'), 'ranked', 'rank'),
  (pg_temp.tid('livre'), 'default', 'deadline');
insert into work.job (tenant_id, queue, rank, executor, input_uri, input_digest, idempotency_key) values
  (pg_temp.tid('torre'), 'ranked', 1, 'script-runner', 's3://a', 'sha256:a', 'rank-1'),
  (pg_temp.tid('torre'), 'ranked', 5, 'script-runner', 's3://b', 'sha256:b', 'rank-5'),
  (pg_temp.tid('torre'), 'ranked', 3, 'script-runner', 's3://c', 'sha256:c', 'rank-3'),
  (pg_temp.tid('torre'), 'default', 9, 'script-runner', 's3://d1', 'sha256:d1', 'fifo-first'),
  (pg_temp.tid('torre'), 'default', 1, 'script-runner', 's3://d2', 'sha256:d2', 'fifo-second');
insert into work.job (tenant_id, queue, deadline, executor, input_uri, input_digest, idempotency_key) values
  (pg_temp.tid('livre'), 'default', now() + interval '2 hours', 'pessoa', 's3://e1', 'sha256:e1', 'deadline-later'),
  (pg_temp.tid('livre'), 'default', now() + interval '1 hour', 'pessoa', 's3://e2', 'sha256:e2', 'deadline-sooner');
select 'ranked' as queue, (select idempotency_key from work.job where id = work.next_job(pg_temp.tid('torre'), 'ranked')) as next
union all select 'fifo', (select idempotency_key from work.job where id = work.next_job(pg_temp.tid('torre'), 'default'))
union all select 'deadline', (select idempotency_key from work.job where id = work.next_job(pg_temp.tid('livre'), 'default'));
update work.job set state = 'cancelled' where queue in ('ranked', 'default');

-- O roteamento: o seletor pede, a capacidade decide entre os aceitos; a escolha de quais aceitar é de quem cria.
insert into work.job (tenant_id, selector, input_uri, input_digest, idempotency_key) values
  (pg_temp.tid('torre'), '{"any_of": ["claude-sub", "codex-sub"]}', 's3://in/regen', 'sha256:same', 'by-ai'),
  (pg_temp.tid('torre'), '{"adapter": "container", "capabilities": {"root": true}}', 's3://in/regen', 'sha256:same', 'by-script');
select idempotency_key, work.route(id) as routed_to from work.job where idempotency_key in ('by-ai', 'by-script') order by 1;

-- O mesmo trabalho (a mesma entrada) por um script, sem sessão de IA, e por uma sessão de IA.
select pg_temp.dispatch('by-script'); select pg_temp.dispatch('by-ai');
update work.job set state = 'running' where idempotency_key in ('by-ai', 'by-script');
select work.finish_run(r.id, 'succeeded', null) from work.run r where r.job_id in (pg_temp.jid('by-ai'), pg_temp.jid('by-script'));
update work.job set result = '{"exit": 0}' where idempotency_key in ('by-ai', 'by-script');
select j.idempotency_key, r.executor, e.adapter, j.state from work.job j join work.run r on r.job_id = j.id
  join work.executor e on e.name = r.executor where j.idempotency_key in ('by-ai', 'by-script') order by 1;

-- A retentativa como mecanismo: três tentativas com espera crescente; o padrão de uma tentativa; um erro que não pede.
insert into work.job (tenant_id, executor, input_uri, input_digest, idempotency_key, max_attempts, retry_on) values
  (pg_temp.tid('torre'), 'script-runner', 's3://flaky', 'sha256:f1', 'retry-3', 3, '{failed}');
insert into work.job (tenant_id, executor, input_uri, input_digest, idempotency_key) values
  (pg_temp.tid('torre'), 'script-runner', 's3://once', 'sha256:f2', 'retry-default');
insert into work.job (tenant_id, executor, input_uri, input_digest, idempotency_key, max_attempts, non_retryable) values
  (pg_temp.tid('torre'), 'script-runner', 's3://auth', 'sha256:f3', 'non-retryable', 3, '{auth}');
insert into work.job (tenant_id, executor, input_uri, input_digest, idempotency_key) values
  (pg_temp.tid('torre'), 'script-runner', 's3://lost', 'sha256:f4', 'lost-executor');
create temp table trail (k text, step int, state text, wait interval);
do $$ declare s int; st text; begin
  for s in 1..3 loop
    perform pg_temp.dispatch('retry-3');
    update work.job set state = 'running', not_before = null where idempotency_key = 'retry-3';
    st := work.finish_run((select id from work.run where job_id = pg_temp.jid('retry-3') and state = 'running'), 'failed', 'exit1');
    insert into trail select 'retry-3', s, st, (select not_before - now() from work.job where idempotency_key = 'retry-3');
  end loop;
end $$;
select pg_temp.dispatch('retry-default'); select pg_temp.dispatch('non-retryable'); select pg_temp.dispatch('lost-executor');
insert into trail select 'retry-default', 1, work.finish_run((select id from work.run where job_id = pg_temp.jid('retry-default')), 'failed', 'exit1'), null;
insert into trail select 'non-retryable', 1, work.finish_run((select id from work.run where job_id = pg_temp.jid('non-retryable')), 'failed', 'auth'), null;
insert into trail select 'lost-executor', 1, work.finish_run((select id from work.run where job_id = pg_temp.jid('lost-executor')), 'lost', null), null;
select k, step, state, date_trunc('second', wait) as wait from trail order by k, step;

-- As dependências como mecanismo: o pouso espera as checagens; outra espera só que uma termine.
insert into work.queue (tenant_id, name, policy) values (pg_temp.tid('torre'), 'land', 'fifo');
insert into work.job (tenant_id, queue, executor, input_uri, input_digest, idempotency_key) values
  (pg_temp.tid('torre'), 'land', 'script-runner', 's3://check1', 'sha256:c1', 'check-1'),
  (pg_temp.tid('torre'), 'land', 'script-runner', 's3://check2', 'sha256:c2', 'check-2');
insert into work.job (tenant_id, queue, executor, input_uri, input_digest, idempotency_key, exclusive_key) values
  (pg_temp.tid('torre'), 'land', 'forge', 's3://land', 'sha256:l', 'landing', 'origin:the-tower:mod/roadmap-integration');
insert into work.dependency (tenant_id, job_id, depends_on, condition)
  select pg_temp.tid('torre'), pg_temp.jid('landing'), pg_temp.jid(k), 'succeeded' from (values ('check-1'), ('check-2')) v(k);
update work.job set state = 'succeeded' where idempotency_key in ('check-1', 'check-2');
select (select idempotency_key from work.job where id = work.next_job(pg_temp.tid('torre'), 'land')) as next_after_checks;

-- Preço por medidor e limite em dinheiro: a gestão dá o preço e o teto; a infraestrutura soma e para.
insert into work.meter_rate (tenant_id, meter, derived_meter, rate) values (pg_temp.tid('torre'), 'tokens', 'usd', 0.000003);
insert into work.job (tenant_id, executor, input_uri, input_digest, idempotency_key, state) values
  (pg_temp.tid('torre'), 'codex-sub', 's3://big', 'sha256:big', 'money-limit', 'running');
insert into work.limits (tenant_id, scope, scope_id, meter, maximum, action)
  select tenant_id, 'job', id::text, 'usd', 0.03, 'stop' from work.job where idempotency_key = 'money-limit';
select pg_temp.ev('torre', 'run.usage', 'job/x', jsonb_build_object('job_id', pg_temp.jid('money-limit'), 'meter', 'tokens', 'quantity', 12000));
select idempotency_key, state, (select used from work.limits where scope_id = pg_temp.jid('money-limit')::text) as usd
  from work.job where idempotency_key = 'money-limit';

-- O cache: a mesma entrada no mesmo executor, com memoize, sai sem despacho.
insert into work.result_cache (executor, input_digest, result, signature) values ('script-runner', 'sha256:same', '{"exit": 0}', '\x01');
insert into work.job (tenant_id, executor, input_uri, input_digest, idempotency_key, memoize) values
  (pg_temp.tid('torre'), 'script-runner', 's3://in/regen', 'sha256:same', 'memoized', true);
update work.job j set state = 'succeeded', result = c.result from work.result_cache c
  where j.idempotency_key = 'memoized' and c.executor = j.executor and c.input_digest = j.input_digest;
select idempotency_key, state, (select count(*) from work.run r where r.job_id = j.id) as runs from work.job j where idempotency_key = 'memoized';

-- A gestão da Torre, com metas e apostas nas tabelas dela; o modelo livre, sem tabela nenhuma. Ela lê o registro bruto.
create schema gestao_torre;
create table gestao_torre.processo (chave text primary key, job_id uuid not null references work.job, objetivo text, aposta text);
insert into gestao_torre.processo values ('F135', pg_temp.jid('by-ai'), 'PRG-vazao', 'BET-1');
select pg_temp.ev('torre', 'run.reported', 'job/x', jsonb_build_object('job_id', pg_temp.jid('by-ai'), 'raw', 'mark audit start'));
select pg_temp.ev('torre', 'run.reported', 'job/x', jsonb_build_object('job_id', pg_temp.jid('by-ai'), 'raw', 'mark audit end'));
select p.chave, max(e.occurred_at) filter (where e.payload->>'raw' = 'mark audit end')
              - min(e.occurred_at) filter (where e.payload->>'raw' = 'mark audit start') > interval '0' as audit_measured
  from gestao_torre.processo p join log.event e on e.payload->>'job_id' = p.job_id::text
  where e.type = 'run.reported' group by 1;

-- Recusas.
do $$ begin
  insert into work.job (tenant_id, executor, input_uri, input_digest) values (pg_temp.tid('torre'), 'livre-own-key', 's3://x', 'x');
  raise exception 'FAIL: torre used the private executor of livre';
exception when raise_exception then
  if sqlerrm like 'FAIL:%' then raise; end if; raise notice 'refused as expected: %', sqlerrm;
end $$;
do $$ begin
  insert into work.job (tenant_id, input_uri, input_digest) values (pg_temp.tid('torre'), 's3://x', 'x');
  raise exception 'FAIL: a job with neither executor nor selector';
exception when check_violation then raise notice 'refused as expected: %', sqlerrm;
end $$;
do $$ begin
  insert into work.job (tenant_id, executor, input_uri, input_digest, idempotency_key, exclusive_key, state)
    values (pg_temp.tid('torre'), 'forge', 's3://land2', 'x', 'landing-2', 'origin:the-tower:mod/roadmap-integration', 'running');
  update work.job set state = 'running' where idempotency_key = 'landing';
  raise exception 'FAIL: two landings ran on the same branch';
exception when unique_violation then raise notice 'refused as expected: %', sqlerrm;
end $$;
do $$ begin
  perform pg_temp.ev('torre', 'torre.bet.accepted', 'bet/BET-1', '{}');
  raise exception 'FAIL: the log took an event of management';
exception when raise_exception then
  if sqlerrm like 'FAIL:%' then raise; end if; raise notice 'refused as expected: %', sqlerrm;
end $$;

do $$ begin
  insert into work.limits (tenant_id, scope, scope_id, meter, maximum, used, action)
    values (pg_temp.tid('livre'), 'tenant', pg_temp.tid('livre')::text, 'usd', 5, 5, 'refuse');
  insert into work.job (tenant_id, executor, input_uri, input_digest) values (pg_temp.tid('livre'), 'pessoa', 's3://y', 'y');
  raise exception 'FAIL: a job entered over a refuse limit';
exception when raise_exception then
  if sqlerrm like 'FAIL:%' then raise; end if; raise notice 'refused as expected: %', sqlerrm;
end $$;
do $$ begin
  insert into work.job (tenant_id, executor, input_uri, input_digest, idempotency_key)
    values (pg_temp.tid('torre'), 'script-runner', 's3://in/regen', 'sha256:same', 'by-script');
  raise exception 'FAIL: the same idempotency key created a second job';
exception when unique_violation then raise notice 'refused as expected: %', sqlerrm;
end $$;

-- O vocabulário e o catálogo.
select count(*) as forbidden_names from information_schema.columns
  where table_schema in ('work','log')
    and (table_name || ' ' || column_name) ~* '(^|[_ ])(objective|objetivo|goal|meta|bet|aposta|choice|intention|intent|lesson|hypothesis|experiment|retro|retrospective|audit|planning|planner|pattern|padrao|premise|decision|domain|program|programa|project|projeto|priority|prioridade|requester|hierarchy|label|labels|annotation|annotations|context|template|step|steps|metric|metrics|dashboard|alert|alerts|report|billing|cost|budget|agent|agents|session|sessions|llm|prompt|model|provider)([_ ]|s?$)';
select string_agg(nspname, ',' order by nspname) as schemas from pg_namespace
  where nspname not like 'pg_%' and nspname not in ('information_schema', 'public');
select count(*) as infra_tables from information_schema.tables
  where table_schema in ('work','log') and table_type = 'BASE TABLE' and table_name not like 'event_2%';
