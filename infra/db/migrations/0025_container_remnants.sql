-- CONTAINER-REMNANTS (RUNNER-STALL-QUIET; GATE-SHUTDOWN, D-314): the runner of the adapter `container` (the ECS service
-- tower-runner) is gone since 14/11 and nothing takes a run handed over to it. The AWS gate's last jobs (the pregate's
-- plans and checks, the prewarm's bundles of 13-14/11) never ended: 0024 cancelled the full run's (selector `yield`),
-- and at 19/11 05:28 UTC the others took the five slots it freed. Each is handed over, lost to lease_expired five
-- minutes later without spending an attempt, and handed over again (run n in the hundreds): platform.runner.stalled
-- every 2.5 minutes since 16/11 00:24 UTC, two emails each to the platform's topic (447 stalled on 22/11). No one can
-- take such a job and no reader of its verdict is left: each still open is cancelled, as POST /v1/jobs/<id>/cancel
-- does (one job.cancelled per job), and the runs handed over and never taken end now as the reaper would end them
-- (work.end_run: their slot back, run.ended), so no run is left `starting`. A job of the adapter: its exact executor's,
-- the executor of the run that holds its lease, or its selector's. Idempotent: a second pass finds none open.
with gone as (
  update work.job j set state = 'cancelled', version = j.version + 1
  where j.state in ('queued', 'running', 'waiting')
    and (j.selector->>'adapter' = 'container'
         or exists (select 1 from work.executor e where e.adapter = 'container'
                    and (e.name = j.executor
                         or e.name = (select r.executor from work.run r where r.id = j.lease_run_id))))
  returning j.id, j.tenant_id, j.version)
insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
select 'job.cancelled:' || id || ':' || version, tenant_id, 'job.cancelled', clock_timestamp(), 'migration', 'job/' || id,
       jsonb_build_object('job_id', id, 'version', version,
                          'reason', 'CONTAINER-REMNANTS: no runner of the adapter container is left (D-314)')
from gone;

select work.end_run(r.id, j.fencing_token, 'cancelled', 'container_remnants', null, null)
from work.job j join work.run r on r.id = j.lease_run_id join work.executor e on e.name = r.executor
where j.state = 'cancelled' and r.state = 'starting' and e.adapter = 'container';
