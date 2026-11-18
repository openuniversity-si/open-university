"""The live proof that tenants `torre` and `torre-b` cannot see or touch each other through the port
(docs/operations/aws.md 16, aws-pendencias F3 "dois tenants").

  scripts/aws-tenant-isolation-proof [--run N] [--queue NAME] [--executor NAME]

Each tenant creates its own queue (the same name in both: queues are per tenant), its own executor (NAME-a and NAME-b:
executors are a global namespace in the port, so one name cannot be shared; no capacity, nothing ever runs, nothing is
spent), a limit and a queued job. A repeat finds the tenant's existing limit (409) and re-arms it. Then each tenant tries to
create the executor and a job on the other's executor name: the port must refuse with 409 (that refusal is the PASS). Then, in both directions (A against B and B against A):
GET /v1/jobs/<other's id>, POST /v1/jobs/<other's id>/cancel (404, or the same refusal, id masked, as for a nonexistent id: live run 2 gave a uniform 409) and PUT /v1/limits/<other's limit> must answer 404 (or
nothing) and leave the other's job and limit as they were; GET /v1/limits must list only the caller's rows; POST
/v1/log/query must return only the caller's events and none about the other's ids. The same idempotency key sent by both
tenants must give two distinct jobs. At the end each tenant cancels its own jobs and lifts its limit, whatever happened.

Env: TOWER_PORT_URL, TOWER_PORT_TOKEN (torre), TOWER_PORT_TOKEN_B (torre-b); no token is ever printed. Only ids and status
codes are printed. Exit: 0 proven, 1 not proven, 2 not configured.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from aws_quota_proof import Port, Refused, encode  # noqa: E402

QUEUE, EXECUTOR = 'tenant-proof', 'tenant-proof-exec'
LIMIT_MAX = 1000000          # never reached: the limit is a row to attack, not a brake
ABSENT = (None, 404)         # what a tenant gets for a row that is not its own


class NotProven(RuntimeError):
    pass


def say(*parts):
    print(*parts, flush=True)


def spec(note):
    return {'provider': 'none', 'brief': note}


class Tenant:
    """One tenant: its port, its name and the rows it made (ids only)."""

    def __init__(self, label, port):
        self.label, self.port = label, port
        self.jobs, self.limit, self.executor = {}, None, None

    def try_call(self, method, path, body=None):
        """(answer, status): the answer on success with status 200, or (None, the refusal's status)."""
        try:
            return self.port.call(method, path, body), 200
        except Refused as error:
            return None, error.status

    def attempt(self, method, path, body, job):
        """(status, the refusal's text with `job` masked), or (200, None) when the port answered."""
        try:
            self.port.call(method, path, body)
        except Refused as error:
            return error.status, str(error).replace(job, '<id>')
        return 200, None


class Proof:
    def __init__(self, a, b, tag, queue=QUEUE, executor=EXECUTOR):
        self.a, self.b, self.tag, self.queue, self.executor = a, b, tag, queue, executor
        a.executor, b.executor = f'{executor}-a', f'{executor}-b'
        self.results = []

    def check(self, name, ok, evidence):
        self.results.append((name, ok))
        say(f'  {"ok  " if ok else "FAIL"} {name}: {evidence}')

    def setup(self, tenant):
        _, status = tenant.try_call('PUT', f'/v1/queues/{self.queue}', {'policy': 'fifo'})
        if status != 200:
            raise NotProven(f'tenant {tenant.label}: PUT queue answered {status}')
        _, status = tenant.try_call('POST', '/v1/executors', {'name': tenant.executor, 'adapter': 'session', 'config': {}})
        if status not in (200, 409):
            raise NotProven(f'tenant {tenant.label}: POST executor answered {status}')
        made, status = tenant.try_call('POST', '/v1/limits', {
            'scope': 'executor', 'scope_id': tenant.executor, 'meter': 'usd', 'maximum': LIMIT_MAX, 'action': 'refuse'})
        if status == 409:       # a repeat: the row is the tenant's own, found in its own log and re-armed
            found = tenant.port.call('POST', '/v1/log/query', {'filters': {'type': 'limit.defined'}, 'limit': 100})
            ids = [e['subject'].split('/', 1)[1] for e in found['events']
                   if e.get('subject', '').startswith('limit/') and e['payload'].get('maximum') == LIMIT_MAX
                   and e['payload'].get('scope_id', tenant.executor) == tenant.executor]
            if not ids:
                raise NotProven(f'tenant {tenant.label}: the limit exists (409) but its own log does not show it')
            made = {'id': ids[-1]}
            _, status = tenant.try_call('PUT', f'/v1/limits/{made["id"]}', {
                'action': 'refuse', 'maximum': LIMIT_MAX, 'reset_used': True})
            if status != 200:
                raise NotProven(f'tenant {tenant.label}: re-arming limit {made["id"]} answered {status}')
            say(f'tenant {tenant.label}: limit {made["id"]} existed, re-armed')
        elif status != 200:
            raise NotProven(f'tenant {tenant.label}: POST limit answered {status}')
        tenant.limit = made['id']
        for name, key in (('own', f'{self.tag}-own-{tenant.label}'), ('same', f'{self.tag}-same')):
            job = tenant.port.call('POST', '/v1/jobs', {
                'queue': self.queue, 'executor': tenant.executor, 'input_uri': encode(spec(key)),
                'input_digest': 'sha256:' + hashlib.sha256(key.encode()).hexdigest(), 'idempotency_key': key})
            tenant.jobs[name] = job['id']
            say(f'tenant {tenant.label}: job {name} {job["id"]} created={job.get("created")}')
        say(f'tenant {tenant.label}: limit {tenant.limit}')

    def mine(self, tenant):
        """The caller's own rows answer to the caller."""
        got, status = tenant.try_call('GET', f'/v1/jobs/{tenant.jobs["own"]}')
        self.check(f'{tenant.label} reads its own job', status == 200 and got.get('id') == tenant.jobs['own'],
                   f'GET job {tenant.jobs["own"]} -> {status}')

    def cancel(self, who, victim, job):
        """A cross-tenant cancel is refused: 404, or a refusal identical (id masked) to the one for a nonexistent id."""
        status, text = who.attempt('POST', f'/v1/jobs/{job}/cancel', {}, job)
        control = str(uuid.uuid4())
        c_status, c_text = who.attempt('POST', f'/v1/jobs/{control}/cancel', {}, control)
        ok = status == 404 or (status != 200 and (status, text) == (c_status, c_text))
        self.check(f'{who.label} cancels {victim.label} job', ok,
                   f'POST cancel {job} -> {status}; nonexistent id -> {c_status}' + (' (same answer: no existence oracle)' if ok and status != 404 else ''))

    def attack(self, who, victim):
        """`who` tries every route against `victim`'s rows; the victim's rows must not change."""
        job = victim.jobs['own']
        before, _ = victim.try_call('GET', f'/v1/jobs/{job}')
        got, status = who.try_call('GET', f'/v1/jobs/{job}')
        self.check(f'{who.label} reads {victim.label} job', (got, status) == ABSENT or not (got or {}).get('id'),
                   f'GET job {job} -> {status}')
        self.cancel(who, victim, job)
        got, status = who.try_call('PUT', f'/v1/limits/{victim.limit}', {'maximum': LIMIT_MAX + 1})
        self.check(f'{who.label} changes {victim.label} limit', (got, status) == ABSENT,
                   f'PUT limit {victim.limit} -> {status}')
        after, _ = victim.try_call('GET', f'/v1/jobs/{job}')
        self.check(f'{victim.label} job untouched', bool(before) and bool(after) and before.get('state') == after.get('state'),
                   f'job {job} state {(before or {}).get("state")} -> {(after or {}).get("state")}')
        self.listing(who, victim)
        self.log(who, victim)

    def listing(self, who, victim):
        got, status = who.try_call('GET', '/v1/limits')
        if status != 200:
            self.check(f'{who.label} lists only its limits', False, f'GET /v1/limits -> {status} (route missing? PR #369)')
            return
        rows = got if isinstance(got, list) else (got.get('limits') or [])
        ids = [row.get('id') for row in rows]
        self.check(f'{who.label} lists only its limits', who.limit in ids and victim.limit not in ids,
                   f'GET /v1/limits -> 200, {len(ids)} rows, own {who.limit in ids}, {victim.label} limit {victim.limit in ids}')

    def log(self, who, victim):
        events = who.port.call('POST', '/v1/log/query', {'limit': 100}).get('events') or []
        theirs = [victim.limit, *victim.jobs.values()]
        mine = {who.limit, *who.jobs.values()}
        seen = [e for e in events if any(t in json.dumps(e, sort_keys=True) for t in theirs if t not in mine)]
        self.check(f'{who.label} log holds none of {victim.label} ids', bool(events) and not seen,
                   f'POST log/query -> 200, {len(events)} events, {len(seen)} naming {victim.label} ids')
        direct = who.port.call('POST', '/v1/log/query', {'payload': {'job_id': victim.jobs['own']}, 'limit': 100})
        self.check(f'{who.label} log query by {victim.label} job id is empty', not direct.get('events'),
                   f'POST log/query job_id={victim.jobs["own"]} -> {len(direct.get("events") or [])} events')

    def namespace(self, who, victim):
        """Executors are global: `who` using `victim`'s executor name must be refused (409). That refusal is the PASS."""
        _, status = who.try_call('POST', '/v1/executors', {'name': victim.executor, 'adapter': 'session', 'config': {}})
        self.check(f'{who.label} creating {victim.label} executor is refused', status == 409,
                   f'POST executor {victim.executor} -> {status}')
        key = f'{self.tag}-xexec-{who.label}'
        job, status = who.try_call('POST', '/v1/jobs', {
            'queue': self.queue, 'executor': victim.executor, 'input_uri': encode(spec(key)),
            'input_digest': 'sha256:' + hashlib.sha256(key.encode()).hexdigest(), 'idempotency_key': key})
        if job and job.get('id'):
            who.jobs['xexec'] = job['id']      # it should not exist; cleaned up all the same
        self.check(f'{who.label} queueing a job on {victim.label} executor is refused', status == 409,
                   f'POST job executor={victim.executor} -> {status}')

    def same_key(self):
        one, two = self.a.jobs['same'], self.b.jobs['same']
        self.check('same idempotency key, two distinct jobs', one != two, f'torre {one} torre-b {two}')

    def clean(self, tenant):
        for name, job in tenant.jobs.items():
            _, status = tenant.try_call('POST', f'/v1/jobs/{job}/cancel', {})
            say(f'tenant {tenant.label}: cancel {name} {job} -> {status}')
        if tenant.limit:
            _, status = tenant.try_call('PUT', f'/v1/limits/{tenant.limit}', {'lift': True})
            say(f'tenant {tenant.label}: lift limit {tenant.limit} -> {status}')

    def run(self):
        try:
            for tenant in (self.a, self.b):
                self.setup(tenant)
                self.mine(tenant)
            self.same_key()
            self.namespace(self.a, self.b)
            self.namespace(self.b, self.a)
            self.attack(self.a, self.b)
            self.attack(self.b, self.a)
        finally:
            for tenant in (self.a, self.b):
                try:
                    self.clean(tenant)
                except Exception as error:  # noqa: BLE001
                    say(f'tenant {tenant.label}: could not clean up: {type(error).__name__}')
        failed = [name for name, ok in self.results if not ok]
        if failed:
            raise NotProven(f'{len(failed)} of {len(self.results)} checks failed: ' + '; '.join(failed))
        say(f'PROVEN: torre and torre-b cannot see or touch each other ({len(self.results)} checks); nothing was spent')


def main(argv=None, environ=None, ports=None):
    environ = os.environ if environ is None else environ
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument('--run', default='1')
    args.add_argument('--queue', default=QUEUE)
    args.add_argument('--executor', default=EXECUTOR)
    args = args.parse_args(argv)
    if ports is None:
        if not all(environ.get(name) for name in ('TOWER_PORT_URL', 'TOWER_PORT_TOKEN', 'TOWER_PORT_TOKEN_B')):
            print('aws-tenant-isolation-proof: set TOWER_PORT_URL, TOWER_PORT_TOKEN (torre) and TOWER_PORT_TOKEN_B (torre-b)',
                  file=sys.stderr)
            return 2
        ports = (Port(environ['TOWER_PORT_URL'], environ['TOWER_PORT_TOKEN']),
                 Port(environ['TOWER_PORT_URL'], environ['TOWER_PORT_TOKEN_B']))
    tag = f'tenant-proof-{datetime.now(timezone.utc):%Y%m%d}-{args.run}'
    try:
        Proof(Tenant('torre', ports[0]), Tenant('torre-b', ports[1]), tag, args.queue, args.executor).run()
    except (NotProven, Refused) as error:
        print(f'aws-tenant-isolation-proof: NOT PROVEN: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
