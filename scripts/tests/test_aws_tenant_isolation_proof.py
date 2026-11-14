"""The live proof of tenant isolation against a stand-in port with two tenants: isolated (PROVEN, rows cleaned up), each kind
of leak (read, cancel, limit change, limits listing, log, shared idempotency key) NOT PROVEN, a missing /v1/limits route NOT
PROVEN, and no token in the output. No network."""
import contextlib
import io
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import aws_tenant_isolation_proof as proof  # noqa: E402
from aws_quota_proof import Refused  # noqa: E402


class Server:
    """One database, a port per tenant; `leak` names the isolation that is broken."""

    def __init__(self, leak=None, listing=True, cancel_refusal=404):
        self.leak, self.listing, self.cancel_refusal = leak, listing, cancel_refusal
        self.jobs, self.limits, self.keys, self.events, self.calls = {}, {}, {}, [], []
        self.puts, self.executors = [], {}     # executors: name -> tenant, a global namespace

    def port(self, tenant):
        return lambda method, path, body=None: self.handle(tenant, method, path, body or {})

    def handle(self, tenant, method, path, body):
        self.calls.append((tenant, method, path))
        if path.startswith('/v1/queues/'):
            return {}
        if path == '/v1/executors':
            if self.executors.setdefault(body['name'], tenant) != tenant and self.leak != 'executor':
                raise Refused('409 executor belongs to another tenant', 409)
            return {'name': body['name']}
        if path == '/v1/limits' and method == 'POST':
            if any(l['tenant'] == tenant and l['scope_id'] == body['scope_id'] for l in self.limits.values()):
                raise Refused('409', 409)
            key = str(uuid.uuid4())
            self.limits[key] = {'tenant': tenant, 'maximum': body['maximum'], 'scope_id': body['scope_id']}
            self.events.append({'tenant': tenant, 'type': 'limit.defined', 'subject': f'limit/{key}',
                                'payload': {'maximum': body['maximum'], 'scope_id': body['scope_id']}})
            return {'id': key}
        if path == '/v1/limits' and method == 'GET':
            if not self.listing:
                raise Refused('404', 404)
            return {'limits': [{'id': k} for k, l in self.limits.items() if l['tenant'] == tenant or self.leak == 'list']}
        if path.startswith('/v1/limits/'):
            row = self.limits.get(path.rsplit('/', 1)[1])
            if row['tenant'] != tenant and self.leak != 'limit':
                raise Refused('404', 404)
            self.puts.append(body)
            return {}
        if path == '/v1/jobs':
            if self.executors.get(body['executor'], tenant) != tenant and self.leak != 'executor':
                raise Refused('409 executor belongs to another tenant', 409)
            key = (tenant if self.leak != 'key' else None, body['idempotency_key'])
            if key not in self.keys:
                self.keys[key] = str(uuid.uuid4())
                self.jobs[self.keys[key]] = {'tenant': tenant, 'state': 'queued'}
                self.events.append({'tenant': tenant, 'type': 'job.created', 'subject': f'job/{self.keys[key]}',
                                    'payload': {'job_id': self.keys[key]}})
            return {'id': self.keys[key], 'created': True}
        if path == '/v1/log/query':
            rows = [e for e in self.events if e['tenant'] == tenant or self.leak == 'log']
            if body.get('payload'):
                rows = [e for e in self.events if e['payload'].get('job_id') == body['payload']['job_id']
                        and (e['tenant'] == tenant or self.leak == 'log')]
            return {'events': rows}
        if method == 'POST' and path.endswith('/cancel') and self.cancel_refusal != 404:
            jid = path.split('/')[3]
            if jid not in self.jobs or self.jobs[jid]['tenant'] != tenant:
                if self.cancel_refusal == 'uniform':
                    raise Refused(f'POST {path}: 409 {{"error": "job {jid} is not open for this tenant"}}', 409)
                if self.cancel_refusal == 'differs':
                    raise Refused(f'POST {path}: 409 ' + ('{"error": "job is held"}' if jid in self.jobs
                                                          else f'{{"error": "job {jid} is not open for this tenant"}}'), 409)
        if path.split('/')[3] not in self.jobs:
            raise Refused('404', 404)
        job = self.jobs[path.split('/')[3]]
        if job['tenant'] != tenant and self.leak != ('read' if method == 'GET' else 'cancel'):
            raise Refused('404', 404)
        if method == 'POST':
            job['state'] = 'cancelled'
        return {'id': path.split('/')[3], 'state': job['state']}


class FakePort:
    def __init__(self, fn):
        self.call = fn


def run(server):
    out = io.StringIO()
    a, b = (proof.Tenant(n, FakePort(server.port(n))) for n in ('torre', 'torre-b'))
    checked = proof.Proof(a, b, 'tag')
    return checked, out


class IsolationTests(unittest.TestCase):
    def test_isolated_tenants_are_proven_and_cleaned_up(self):
        server = Server()
        checked, out = run(server)
        with contextlib.redirect_stdout(out):
            checked.run()
        self.assertIn('PROVEN', out.getvalue())
        self.assertTrue(all(job['state'] == 'cancelled' for job in server.jobs.values()))
        self.assertEqual(len(server.jobs), 4)
        self.assertEqual(server.executors, {'tenant-proof-exec-a': 'torre', 'tenant-proof-exec-b': 'torre-b'})
        self.assertIn('torre-b creating torre executor is refused', out.getvalue())
        self.assertNotIn('FAIL', out.getvalue())

    def test_each_leak_is_not_proven(self):
        for leak in ('read', 'cancel', 'limit', 'list', 'log', 'key', 'executor'):
            with self.subTest(leak=leak):
                checked, out = run(Server(leak=leak))
                with contextlib.redirect_stdout(out), self.assertRaises(proof.NotProven):
                    checked.run()
                self.assertIn('FAIL', out.getvalue())

    def test_a_uniform_409_on_cancel_is_proven(self):
        server = Server(cancel_refusal='uniform')
        checked, out = run(server)
        with contextlib.redirect_stdout(out):
            checked.run()
        self.assertIn('PROVEN', out.getvalue())
        self.assertIn('no existence oracle', out.getvalue())
        self.assertNotIn('FAIL', out.getvalue())

    def test_a_409_that_differs_from_nonexistent_is_not_proven(self):
        checked, out = run(Server(cancel_refusal='differs'))
        with contextlib.redirect_stdout(out), self.assertRaises(proof.NotProven):
            checked.run()
        self.assertIn('FAIL torre cancels torre-b job', out.getvalue().replace('  ', ' ').replace('FAIL ', 'FAIL ', 1))

    def test_a_missing_limits_route_is_not_proven(self):
        checked, out = run(Server(listing=False))
        with contextlib.redirect_stdout(out), self.assertRaises(proof.NotProven):
            checked.run()
        self.assertIn('PR #369', out.getvalue())

    def test_a_repeat_finds_the_existing_limit(self):
        server = Server()
        for _ in range(2):
            checked, out = run(server)
            with contextlib.redirect_stdout(out):
                checked.run()
            self.assertIn('PROVEN', out.getvalue())
        self.assertEqual(len(server.limits), 2)
        self.assertIn({'action': 'refuse', 'maximum': proof.LIMIT_MAX, 'reset_used': True}, server.puts)

    def test_without_the_tokens_it_stops_and_never_prints_one(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(proof.main([], environ={'TOWER_PORT_URL': 'u', 'TOWER_PORT_TOKEN': 'secret-token'}), 2)
        self.assertNotIn('secret-token', err.getvalue())


if __name__ == '__main__':
    unittest.main()
