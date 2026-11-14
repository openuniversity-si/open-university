"""FIRST-JOB-REHEARSED (docs/operations/aws.md 22.9): a job of no one through the whole path of a real one, rolled back.

A swap moves the two roles to processes that never dispatched, took or ended a job. Their connections were warmed for
the first pass's statements and for the swap's record (live_image.Warm), and the swap itself is under a second; the
first job after it still paid each statement of its path for the first time on its backend, on a host that pages: live
12/11, over nine swaps the swap's canary was dispatched in 0.40 to 1.54 s (0.03 to 0.10 s on a warm engine) and taken in
0.11 to 1.02 s (0.02 s).

job(db, role) runs that path on the connection it is given, with the functions the roles themselves call: the port's
create_job, the dispatcher's dispatch_one (the queue's candidates, the route, the account, the cache, the hold, the
claim), the runner's take (run.running), a usage relayed, the lease renewed, and the end of the run. What it runs them
on is its own and nobody else's: a tenant, a queue, an executor (private to that tenant, with an adapter no runner
asks for) and one slot, all inserted first, in the same transaction, under a name drawn for this call. So it reads and
locks no row a live process uses, a live dispatcher or runner never sees any of it, and the caller's transaction is
rolled back (live_image.Warm.step: force_rollback): nothing of it is ever committed, no event of it is ever notified.
A rollback leaves dead rows, so it runs when a connection first warms and when the delivery at the front asks whether
its successors are ready (READY-REHEARSAL), never on a cadence.

It answers the seconds of each part, for the swap's record. A step that did not do what the real one does raises
Unrehearsed: the caller logs it and goes on (a rehearsal is a courtesy). Standard library only.
"""
import hashlib
import time
import uuid

from . import canary, mechanisms, port, runner

TENANT = 'insert into work.tenant (name) values (%(name)s) returning id::text'
QUEUE = "insert into work.queue (tenant_id, name, policy) values (%(tenant)s::uuid, %(name)s, 'rank')"
EXECUTOR = ('insert into work.executor (name, adapter, tenant_id) '
            'values (%(name)s, %(name)s, %(tenant)s::uuid)')  # its adapter is its name: no runner's TAKE asks for it
CAPACITY = 'insert into work.capacity (executor, account, slots) values (%(name)s, %(account)s, 1)'
ACCOUNT = 'rehearsal'
INPUT = 'data:application/json;base64,e30='  # {}: nothing reads it


RUN = 'select work.rehearse_run(%(name)s)'


class Unrehearsed(Exception):
    """A step of the rehearsal that did not do what the real one does."""


class Rows:
    """rows(sql, params) over a cursor of the caller's transaction: no commit of its own (database.Database commits)."""

    def __init__(self, cursor):
        self.cursor = cursor

    def rows(self, sql, params=None):
        self.cursor.execute(sql, params)
        return self.cursor.fetchall() if self.cursor.description else []


def job(db, role, lease='5 minutes', clock=time.monotonic, mark=None, canary_of=None):
    """One job created, dispatched, taken and ended on db, inside the caller's transaction, which the caller rolls back.
    Answers {create_s, dispatch_s, take_s, end_s}. FIRST-JOB-AT-ONCE: canary_of (the configuration tenant's name: the
    service) also makes and reads a canary under a key of this call, as the service that takes the role does after its
    first tick (canary.settle: the job by its key, the tenant, its settings, the base's head, the reserved slot, the
    job, its reading): a job of that tenant's queue of checks that no one sees, since it is never committed, and that
    this call does not dispatch; canary_s. A log with no head of the base makes none, as after a swap."""
    name = f'rehearsal-{mark or uuid.uuid4().hex[:16]}'  # a tenant's name: ^[a-z][a-z0-9-]{1,39}$
    began = clock()
    tenant = db.rows(TENANT, {'name': name})[0][0]
    db.rows(QUEUE, {'tenant': tenant, 'name': name})
    db.rows(EXECUTOR, {'tenant': tenant, 'name': name})
    db.rows(CAPACITY, {'name': name, 'account': ACCOUNT})
    made = port.create_job(db, ('tenant', tenant), {
        'queue': name, 'rank': 1, 'executor': name, 'memoize': False, 'input_uri': INPUT,
        'input_digest': 'sha256:' + hashlib.sha256(name.encode()).hexdigest(), 'idempotency_key': name},
        said={'rehearsal': role})
    created = clock()
    claimed = mechanisms.dispatch_one(db, tenant, name, lease, 1)
    if not claimed or claimed.get('job') != made['id'] or claimed.get('cached'):
        raise Unrehearsed(f'dispatch: {claimed!r}')
    dispatched = clock()
    run = runner.take(db, name, name)
    if run is None or run['run'] != claimed['run']:
        raise Unrehearsed(f'take: {run!r}')
    taken = clock()
    if not mechanisms.relay(db, run['run'], run['fence'], 'run.usage', {'meter': 'cpu_s', 'quantity': 0}):
        raise Unrehearsed('usage: refused')
    if runner.renew(db, run, lease) not in runner.OPEN:
        raise Unrehearsed('renew: the lease is not this run\'s')
    state = mechanisms.end(db, run['run'], run['fence'], 'succeeded', None, {'exit': 0}, None)
    if state != 'succeeded':
        raise Unrehearsed(f'end: {state!r}')
    ended = clock()
    parts = {'create_s': round(created - began, 3), 'dispatch_s': round(dispatched - created, 3),
             'take_s': round(taken - dispatched, 3), 'end_s': round(ended - taken, 3)}
    if canary_of:
        try:
            canary.settle(db, canary_of, name, {'rehearsal': role}, fire=True, publish=lambda verdict: None)
        except port.PortError:  # no head of the base in the log: the service's own canary is not made either
            return parts
        parts['canary_s'] = round(clock() - ended, 3)
    return parts


def run(db, clock=time.monotonic, mark=None):
    """RUNNER-OWN-LOGIN: the runner's rehearsal, for a login that may insert nothing: the owner's function (migration
    0019, work.rehearse_run) takes, relays, renews and ends a run of no one on rows of its own and undoes all of it
    before it returns. Answers {run_s}; Unrehearsed when a step did not do what the real one does."""
    began = clock()
    found = db.rows(RUN, {'name': f'rehearsal-{mark or uuid.uuid4().hex[:16]}'})
    if not found or found[0][0] not in (True, 't'):
        raise Unrehearsed(f'run: {found!r}')
    return {'run_s': round(clock() - began, 3)}
