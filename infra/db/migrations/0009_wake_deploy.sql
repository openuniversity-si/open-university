-- DEP-EVENTS: the deploy is triggered by events, never by the clock. Channel tower_deploy wakes the autodeploy look when the
-- log records a push (forge.repository.pushed, written by the ingress) or the end of a deploy build (platform.deploy.ended,
-- written by the look that reads the build's last-build record). The payload is the event's type; the look reads what to do
-- from the log and Parameter Store as before, so a lost notification costs the safety look, never a deploy.
create function log.wake_deploy() returns trigger language plpgsql as $$
begin
  perform pg_notify('tower_deploy', new.type);
  return null;
end $$;
create trigger wake_deploy after insert on log.event for each row
  when (new.type in ('forge.repository.pushed', 'platform.deploy.ended', 'config.changed'))
  execute function log.wake_deploy();
