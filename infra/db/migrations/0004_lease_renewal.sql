-- The renewal of a lease (INFRA-EXE 1, P4 F1): an executor whose run outlives the lease keeps it while the job is its
-- own, fenced like the end of the run. Answers the job's state, so the executor stops when the job was stopped or
-- cancelled, or null when the lease is no longer this run's (it expired and the job went to another run).
create function work.renew_lease(p_run uuid, p_fence bigint, p_lease interval) returns text language sql as $$
  update work.job set lease_expires_at = clock_timestamp() + p_lease
  where lease_run_id = p_run and fencing_token = p_fence
  returning state $$;
