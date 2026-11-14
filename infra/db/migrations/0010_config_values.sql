-- DEP9: configuration as data (docs/operations/aws.md 22.5). The behaviour keys of the service (deploy.*, the dispatcher's
-- safety tick, ...) are a value in this table, not a constant in the image: a change is a write (PUT /v1/config/<key>),
-- never a deploy. Scoped to the tenant that wrote it (the service reads the one named by TOWER_CONFIG_TENANT), versioned,
-- with the actor and the reason. No row means the compiled default, which mirrors the registry's. Additive.
create table if not exists work.config_value (
  tenant_id  uuid not null references work.tenant (id),
  key        text not null check (key ~ '^[a-z0-9_.-]+$'),
  value      jsonb not null,
  version    integer not null default 1 check (version > 0),
  actor      text not null,
  reason     text not null check (length(reason) > 0),
  updated_at timestamptz not null default clock_timestamp(),
  primary key (tenant_id, key)
);

-- The wake: every reader of the values refreshes on this event (LISTEN tower_config), never on a timer. The payload is the
-- key; what to read is in the table, so a lost notification costs the readers' safety timeout, never a wrong value.
create or replace function work.wake_config() returns trigger language plpgsql as $$
begin
  perform pg_notify('tower_config', new.key);
  perform pg_notify('tower_deploy', 'config.changed');  -- the autodeploy look is event-driven too (migration 0009 wakes on the log's rows)
  return null;
end $$;
drop trigger if exists wake_config on work.config_value;
create trigger wake_config after insert or update on work.config_value
  for each row execute function work.wake_config();
