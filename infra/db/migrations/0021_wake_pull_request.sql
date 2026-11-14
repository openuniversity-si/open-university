-- PREGATE-WAKE (docs/operations/aws.md 22.9): a PR opened (forge.pull_request.created) or its head pushed
-- (forge.pull_request.head_ref.pushed) wakes the pre-gate's look at once, as a push does, so the PR's observation is made
-- while it is authored (OBSERVE-ON-PUSH) and not by the delivery's own ask. Without it the look woke at the next push or
-- its 60 s look: #656 and #657 (13/11) were delivered 20 to 35 s after their PRs opened, and each delivery's `pr metadata`
-- waited 8 s for the read of Origin it asked itself. Events, never the clock.
-- Idempotent: the trigger is replaced with the same function and two more types.
drop trigger if exists wake_deploy on log.event;
create trigger wake_deploy after insert on log.event for each row
  when (new.type in ('forge.repository.pushed', 'platform.deploy.ended', 'config.changed', 'platform.deploy.landed',
                     'forge.pull_request.created', 'forge.pull_request.head_ref.pushed'))
  execute function log.wake_deploy();
