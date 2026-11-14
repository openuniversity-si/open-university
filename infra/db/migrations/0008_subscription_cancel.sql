-- A subscription can be cancelled (P3 F4): the port's POST /v1/subscriptions/{id}/cancel sets state = 'cancelled', which
-- the deliverer's active query (state = 'active') skips and log.pending never reads. Final, unlike `paused`. Idempotent.
do $$ declare c text;
begin
  for c in select conname from pg_constraint
           where conrelid = 'log.subscription'::regclass and contype = 'c' and pg_get_constraintdef(oid) like '%paused%'
  loop
    execute format('alter table log.subscription drop constraint %I', c);
  end loop;
end $$;
alter table log.subscription drop constraint if exists subscription_state_check;
alter table log.subscription add constraint subscription_state_check check (state in ('active','paused','cancelled'));
