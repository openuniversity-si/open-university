-- The log's subscriptions (INFRA-SVC 4, P3 F4): each one reads its tenant's events in the order of the log from a
-- cursor, and the service's deliverer moves the cursor only past what the sink accepted, so a subscriber receives every
-- event of its tenant, in order, with the event_id a repeated batch keeps. A subscription starts at its creation;
-- rewinding it to a point replays the history from there.
alter table log.subscription add column read_event_id text not null default '';
update log.subscription set read_until = clock_timestamp() where read_until is null;
alter table log.subscription alter column read_until set default clock_timestamp();
alter table log.subscription alter column read_until set not null;

-- The next events a subscription has not read: its tenant's, of its types (none named: every type), in the order of the
-- log, and only those older than the settle window, so an event whose transaction commits late is never passed over.
create function log.pending(p_subscription uuid, p_limit int, p_settle interval) returns setof log.event
language sql stable as $$
  select e.* from log.event e join log.subscription s on s.id = p_subscription
  where s.state = 'active' and e.tenant_id = s.tenant_id
    and (cardinality(s.types) = 0 or e.type = any (s.types))
    and (e.occurred_at, e.event_id) > (s.read_until, s.read_event_id)
    and e.occurred_at < clock_timestamp() - p_settle
  order by e.occurred_at, e.event_id
  limit p_limit $$;

-- The cursor moves forward only, past the last event a sink accepted; true when it moved.
create function log.advance(p_subscription uuid, p_occurred_at timestamptz, p_event_id text) returns boolean
language sql as $$
  with moved as (update log.subscription set read_until = p_occurred_at, read_event_id = p_event_id
                 where id = p_subscription and (read_until, read_event_id) < (p_occurred_at, p_event_id)
                 returning id)
  select exists (select 1 from moved) $$;

-- Replay from a point: the tenant's own subscription goes back (or forward) to it, and the deliverer sends the history
-- from there; the rewind is an event of the log. True when the subscription is the tenant's.
create function log.rewind(p_subscription uuid, p_tenant uuid, p_since timestamptz) returns boolean
language sql as $$
  with moved as (update log.subscription set read_until = p_since, read_event_id = ''
                 where id = p_subscription and tenant_id = p_tenant returning id, tenant_id),
  logged as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
             select 'platform.subscription.rewound:' || moved.id || ':' || clock_timestamp(), moved.tenant_id,
                    'platform.subscription.rewound', clock_timestamp(), 'port', 'subscription/' || moved.id,
                    jsonb_build_object('subscription_id', moved.id, 'since', p_since)
             from moved returning event_id)
  select exists (select 1 from moved) $$;
