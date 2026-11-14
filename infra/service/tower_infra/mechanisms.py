"""The mechanisms of the infrastructure's service (P3 F3; ARQUITETURA-ALVO §4): dispatch, the end of a run, what an
executor relays, and the reaper of expired leases.

dispatch(db, lease) goes through every queue with queued work and takes its candidates in the order of the queue's
policy (work.candidates, which already leaves out jobs whose dependencies are open, whose time has not come, or whose
exclusive key another job holds). For the first candidate whose route (work.route: the exact executor, or the first one
the selector accepts with capacity) has a free slot, a memoized job whose output the cache holds succeeds from it with
no run; any other is claimed: one statement takes the slot, opens the run, leases the job with a new fencing token and
writes run.started. A candidate with no executor free waits and the next one goes, so one busy executor never stops a
queue. A wait limit reached or a capacity at no slots that resets later puts the candidate `waiting` until the reset
(work.hold_job, no run and no slot) and every dispatch first rolls the windows that passed and wakes the held jobs
whose hold is over (migration 0007). end, relay and reap are migration 0003's functions, fenced by the lease: a run that comes back after its lease
expired changes nothing. The database is any object with rows(sql, params). Standard library only.
"""
import json

PRODUCER = 'dispatcher'
QUEUES = "select distinct tenant_id::text, queue from work.job where state = 'queued' order by 1, 2"
# FULL-RUN-SKIP: each with whether it yields (a full run's test), in the same statement and the candidates' order
CANDIDATES = ("select c.id::text, coalesce(j.selector ? 'yield', false) "
              'from work.candidates(%(tenant)s::uuid, %(queue)s, %(scan)s::int) with ordinality as c(id, n) '
              'join work.job j on j.id = c.id order by c.n')
# FULL-RUN: and, in the same statement (no round trip more on a claim, the swap's first job's too), whether the job yields
# to a gate's job waiting in its queue (YIELD_HELD)
ROUTE = ("select work.route(%(job)s::uuid), exists (select 1 from work.job j where j.id = %(job)s::uuid and j.selector ? 'yield') "
         "and exists (select 1 from work.job q join work.job j on j.id = %(job)s::uuid where q.state = 'queued' "
         "and q.queue = j.queue and q.tenant_id = j.tenant_id and not q.selector ? 'yield')")
# CANARY-OWN-SLOT: the account RESERVED is of the jobs whose selector names it ({'account': 'canary'}: the swap's
# canary, tower_infra.canary) and of no other, so a runner whose slots are all in checks still has one for the canary;
# the job that names it takes it first and, with it taken, any other with a free slot
RESERVED = 'canary'
ACCOUNT = ('select c.account from work.capacity c join work.job j on j.id = %(job)s::uuid '
           'where c.executor = %(executor)s and c.in_use < c.slots '
           f"and (c.account <> '{RESERVED}' or j.selector->>'account' = '{RESERVED}') "
           f"order by (c.account = '{RESERVED}') desc, c.in_use, c.account limit 1")
FROM_CACHE = """with job as (
  select id, tenant_id, input_digest from work.job where id = %(job)s::uuid and state = 'queued' and memoize
  for update skip locked),
hit as (select c.result from work.result_cache c join job on c.input_digest = job.input_digest
        where c.executor = %(executor)s),
done as (update work.job j set state = 'succeeded', result = hit.result, version = j.version + 1 from hit, job
         where j.id = job.id returning j.id, j.tenant_id),
logged as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
           select 'cache.hit:' || done.id, done.tenant_id, 'cache.hit', clock_timestamp(), %(producer)s,
                  'job/' || done.id, jsonb_build_object('job_id', done.id, 'executor', %(executor)s::text) from done)
select id::text from done"""
HOLD = 'select work.hold_job(%(job)s::uuid, %(executor)s)::text'  # a wait limit or a capacity waiting for its reset
# PRE-GATE: a memoized job whose twin (the same input_digest) is running waits for it in its queue: the twin's success is
# then its answer from the cache; a twin that failed leaves no answer, and this one runs. The delivery's gate makes the jobs
# the pre-gate is still running at the push: they run once
TWIN = ("select 1 from work.job t where t.state = 'running' and t.memoize and t.id <> %(job)s::uuid "  # job_running_digest
        "and t.input_digest = (select j.input_digest from work.job j where j.id = %(job)s::uuid and j.memoize) limit 1")
REAP = 'select id::text from work.reap() id'
ROLL = 'select work.roll_limits()'
WAKE = 'select id::text from work.wake_held() id'
CLAIM = """with job as (
  select id, tenant_id, attempts from work.job where id = %(job)s::uuid and state = 'queued' for update skip locked),
slot as (update work.capacity set in_use = in_use + 1
         where executor = %(executor)s and account = %(account)s and in_use < slots and exists (select 1 from job)
         returning executor, account),
opened as (insert into work.run (job_id, n, executor, account, state)
           select job.id, job.attempts + 1 + (select count(*) from work.run r where r.job_id = job.id
                                              and r.outcome = 'lost'), slot.executor, slot.account, 'starting'
           from job, slot returning id, job_id, n, executor, account),
leased as (update work.job j set state = 'running', lease_run_id = opened.id,
                                 lease_expires_at = clock_timestamp() + %(lease)s::interval,
                                 fencing_token = j.fencing_token + 1, version = j.version + 1
           from opened where j.id = opened.job_id
           returning j.id, j.tenant_id, j.fencing_token, j.input_uri, j.input_digest, opened.id as run_id, opened.n,
                     opened.executor, opened.account),
logged as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload)
           select 'run.started:' || run_id, tenant_id, 'run.started', clock_timestamp(), %(producer)s, 'job/' || id,
                  jsonb_build_object('job_id', id, 'run_id', run_id, 'n', n, 'executor', executor, 'account', account,
                                     'fencing_token', fencing_token) from leased)
select leased.id::text, leased.run_id::text, leased.fencing_token, leased.n, leased.executor, leased.account,
       leased.input_uri, leased.input_digest, e.adapter, e.config::text
from leased join work.executor e on e.name = leased.executor"""
UNIQUE = '23505'  # another dispatcher took the exclusive key between the candidates and the claim
# FULL-RUN (revisão da arquitetura, achado 29): a job whose selector says `yield` (tower_infra.fullrun: the base's whole
# battery at a landing) never starts while a job of its queue that does not yield waits, and one of them running is taken
# back (cancelled: the full run makes it again) when such a job finds no free slot. By the event of a job that cannot go,
# never by a clock: the runner's slots are the gates' first
YIELD_HELD = ROUTE  # its second column
PREEMPT = ("with mine as (select j.queue, j.tenant_id from work.job j where j.id = %(job)s::uuid and not j.selector ? 'yield'), "
           "taken as (select y.id from work.job y join mine on y.queue = mine.queue and y.tenant_id = mine.tenant_id "
           "where y.state = 'running' and y.selector ? 'yield' order by y.lease_run_id desc limit 1), "
           "cancelled as (update work.job j set state = 'cancelled', version = version + 1 from taken "
           "where j.id = taken.id and j.state = 'running' returning j.id, j.tenant_id, j.version), "
           "logged as (insert into log.event (event_id, tenant_id, type, occurred_at, producer, subject, payload) "
           "select 'job.cancelled:' || id || ':' || version, tenant_id, 'job.cancelled', clock_timestamp(), %(producer)s, "
           "'job/' || id, jsonb_build_object('job_id', id, 'version', version, 'yielded_to', %(job)s::text) from cancelled) "
           "select id::text from cancelled")


def held(db, job, executor):
    """True when the job was put to wait (work.hold_job); a lost race for its exclusive key is not an error."""
    try:
        return bool(db.rows(HOLD, {'job': job, 'executor': executor})[0][0])
    except Exception as error:  # noqa: BLE001
        if getattr(error, 'sqlstate', None) != UNIQUE:
            raise
        return False


def dispatch_one(db, tenant, queue, lease, scan):
    """The first candidate of a queue that can go now: a cache answer, a claimed run, or None when none can."""
    blocked = False  # FULL-RUN-SKIP: a full run's test that cannot go says none after it can, in this pass
    for job, yields in db.rows(CANDIDATES, {'tenant': tenant, 'queue': queue, 'scan': scan}):
        yields = yields in (True, 't')
        if yields and blocked:
            continue  # asked nothing: the battery's 211 tests cost one look a pass, not four statements each
        routed = db.rows(ROUTE, {'job': job})[0]
        executor = routed[0]
        # CANARY-OWN-SLOT: the route answers an executor whose only free slot is the reserved one; a job it is not for
        # has no slot there, as when the route answers none
        if len(routed) > 1 and routed[1] in (True, 't'):
            blocked = True
            continue  # FULL-RUN: a gate's job waits in its queue: this one stays behind it
        account = db.rows(ACCOUNT, {'job': job, 'executor': executor}) if executor else None
        if not account and yields:  # no slot for a full run's test: it takes none back (only a gate's job does)
            blocked = True
            continue
        if not account:
            # FULL-RUN: no free slot (the route answers none then): a full run's test of this queue that holds one gives
            # it to this job (its run ends at the runner's beat, which sees the cancel)
            db.rows(PREEMPT, {'job': job, 'producer': PRODUCER})
            held(db, job, None)  # no slot: a capacity that resets later makes the job wait for it (AWS12)
            continue
        if db.rows(FROM_CACHE, {'job': job, 'executor': executor, 'producer': PRODUCER}):
            return {'job': job, 'cached': True, 'executor': executor}
        if db.rows(TWIN, {'job': job}):
            continue  # PRE-GATE: its twin's end answers it
        if held(db, job, executor):  # a wait limit already reached: waiting until its reset, no run, no slot
            continue
        try:
            claimed = db.rows(CLAIM, {'job': job, 'executor': executor, 'account': account[0][0], 'lease': lease,
                                      'producer': PRODUCER})
        except Exception as error:  # noqa: BLE001 - only a lost race for the exclusive key is skipped
            if getattr(error, 'sqlstate', None) != UNIQUE:
                raise
            continue
        if claimed:
            job_id, run, fence, n, executor, account, uri, digest, adapter, config = claimed[0]
            return {'job': job_id, 'run': run, 'fence': int(fence), 'n': int(n), 'executor': executor,
                    'account': account, 'input_uri': uri, 'input_digest': digest, 'adapter': adapter,
                    'config': json.loads(config or '{}'), 'cached': False}
    return None


def dispatch(db, lease='5 minutes', scan=50, claimed=None):
    """Dispatch every queue until nothing more can go now; answers the runs and the cache answers it made.
    IMAGE-SWAP-TICK: claimed(got) is called as each one is made, its statement committed, while the pass goes on."""
    made = []
    db.rows(ROLL)  # a wait limit whose window passed starts over,
    db.rows(WAKE)  # and the jobs held for it, or for a capacity's reset, go back to the queue (AWS12)
    for tenant, queue in db.rows(QUEUES):
        while True:
            got = dispatch_one(db, tenant, queue, lease, scan)
            if got is None:
                break
            made.append(got)
            if claimed is not None:
                claimed(got)
    return made


def end(db, run, fence, outcome, error=None, result=None, signature=None):
    """The end of a run: the job's next state, or None when the lease is no longer this run's."""
    return db.rows('select work.end_run(%(run)s::uuid, %(fence)s::bigint, %(outcome)s, %(error)s, %(result)s::jsonb, '
                   '%(signature)s::bytea)',
                   {'run': run, 'fence': fence, 'outcome': outcome, 'error': error,
                    'result': None if result is None else json.dumps(result),
                    'signature': None if signature is None else '\\x' + signature.hex()})[0][0]


def finish(db, run, ended, signature=None):
    """The end of a run an adapter answered: each meter of its usage relayed as run.usage, fenced, then the end."""
    for meter, quantity in sorted((ended.get('usage') or {}).items()):
        relay(db, run['run'], run['fence'], 'run.usage', {'meter': meter, 'quantity': quantity, 'final': True})
    return end(db, run['run'], run['fence'], ended['outcome'], ended.get('error'), ended.get('result'), signature)


def relay(db, run, fence, kind, payload=None):
    """What the executor of a run says while it holds the lease: True when taken, False when refused."""
    taken = db.rows('select work.relay_run(%(run)s::uuid, %(fence)s::bigint, %(kind)s, %(payload)s::jsonb)',
                    {'run': run, 'fence': fence, 'kind': kind, 'payload': json.dumps(payload or {})})[0][0]
    return taken in (True, 't')


def reap(db):
    """Give back every job whose lease expired; answers their ids."""
    return [row[0] for row in db.rows(REAP)]
