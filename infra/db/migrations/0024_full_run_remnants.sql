-- FULL-RUN-REMNANTS (REQ-deploy-1s; FULL-RUN-GONE, D-316): the base's full run (tower_infra.fullrun, gone in #55) made
-- the only jobs whose selector says `yield`, and its last ones never ended: live 19/11, of its 211-test batteries of
-- 14/11, some are still queued in `checks` and four still hold the runner's four slots, lost to lease_expired and
-- dispatched again every five minutes (run n=918; platform.runner.stalled every 3 min since 16/11 00:24). While the
-- dispatcher skipped a battery that could not go (FULL-RUN-SKIP), they cost one look a pass; since #07c0346 took that
-- skip out with the yield handling, every pass of the service (each service.dispatch_s, and the first pass after a swap)
-- routes and holds each of them, up to the candidates' scan of 50: an empty pass went from 0.04-0.11 s (15/11) to
-- 0.30-0.61 s (16-18/11), and a queue swap's image_live is recorded at the end of that pass (live_image's
-- IMAGE-SWAP-TICK), so it was a third of a code-only merge's landing to live. Nothing makes such a job now, nothing
-- waits for one and no reader of their verdict is left: each still open is cancelled, as POST /v1/jobs/<id>/cancel
-- does (one job.cancelled per job, which wakes the dispatcher and the runner); a running one gives its slot back when its
-- lease ends (work.end_run of a cancelled job). Idempotent: a second pass finds none open.
with gone as (
  update work.job set state = 'cancelled', version = version + 1
  where state in ('queued', 'running', 'waiting') and selector ? 'yield'
  returning id, tenant_id, version)
insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
select 'job.cancelled:' || id || ':' || version, tenant_id, 'job.cancelled', clock_timestamp(), 'migration', 'job/' || id,
       jsonb_build_object('job_id', id, 'version', version, 'reason', 'FULL-RUN-REMNANTS: the full run left (D-316)')
from gone;
