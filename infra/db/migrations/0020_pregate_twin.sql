-- PRE-GATE (docs/operations/aws.md 22.9): the dispatcher leaves a memoized job in its queue while a twin of it (the same
-- input_digest) runs, so the pre-gate's run answers the delivery's job from the cache (mechanisms.TWIN). The question is
-- asked of each candidate of each pass over 150 thousand jobs: only the running memoized ones, by digest.
create index if not exists job_running_digest on work.job (input_digest) where state = 'running' and memoize;
