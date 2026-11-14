-- FAST-ON-LANDED: the delivery that merged a PR records platform.deploy.landed (POST /v1/deploy/landed: merge sha, the base before,
-- the PR head, the fast Lambdas it changed, the gate's manifest key and the paths) and that event wakes the autodeploy look at once,
-- like a push does: the fast path reads its targets from it, because Origin's push events list no files. Events, never the clock.
-- Idempotent: the trigger is replaced with the same function and one more type.
drop trigger if exists wake_deploy on log.event;
create trigger wake_deploy after insert on log.event for each row
  when (new.type in ('forge.repository.pushed', 'platform.deploy.ended', 'config.changed', 'platform.deploy.landed'))
  execute function log.wake_deploy();
