"""The live proof of the quota that resets (AWS12) against a stand-in port: the happy path (limit armed, A ends, B held
waiting with run.waiting until, limit lifted, B succeeded, limit lifted at the end), a refusal to spend over the cap
before the call is made, a B that is not held (not proven), and no token in the output. No network."""
import contextlib
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import aws_quota_proof as proof  # noqa: E402


class FakePort:
    def __init__(self, hold=True, spent_tokens=0, existing=None):
        self.existing = existing
        self.calls, self.jobs, self.hold, self.lifted, self.spent_tokens = [], {}, hold, False, spent_tokens
        self.usage = []

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == '/v1/log/query':
            filters = (body or {}).get('filters') or {}
            if filters.get('type') == 'limit.defined':
                return {'events': [{'subject': f'limit/{i}', 'payload': {'meter': 'usd', 'maximum': 0.05}}
                                   for i in (self.existing or [])]}
            if filters.get('type') == 'run.usage':
                return {'events': self.usage}
            if filters.get('type') == 'run.waiting':
                return {'events': [{'payload': {'job_id': self.jobs.get('b'), 'until': 'T', 'reason': 'limit'}}]
                        if self.hold else []}
            return {'events': [{'occurred_at': 't', 'type': 'job.created', 'payload': {}}]}
        if path == '/v1/limits':
            if self.existing:
                raise proof.Refused('POST /v1/limits: 409 duplicate', 409)
            return {'id': 'limit-1'}
        if method == 'PUT':
            self.lifted = self.lifted or (body or {}).get('lift', False)
            return {}
        if method == 'POST' and path == '/v1/jobs':
            name = body['idempotency_key'][-1]
            self.jobs[name] = f'job-{name}'
            if name == 'a':
                self.usage = [{'payload': {'job_id': 'job-a', 'meter': 'tokens_in:m', 'quantity': 20 + self.spent_tokens}},
                              {'payload': {'job_id': 'job-a', 'meter': 'tokens_out:m', 'quantity': 4}}]
            return {'id': self.jobs[name], 'created': True}
        if method == 'GET':
            job = path.rsplit('/', 1)[1]
            if job == 'job-b':
                return {'state': 'succeeded' if self.lifted else ('waiting' if self.hold else 'succeeded')}
            return {'state': 'succeeded'}
        raise AssertionError((method, path))


def run(port, **kwargs):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        return proof.Proof(port, tag='t', sleep=lambda s: None, **kwargs), out


class ProofTests(unittest.TestCase):
    def test_a_held_job_resumes_when_the_limit_is_lifted_and_the_limit_is_lifted_at_the_end(self):
        port = FakePort()
        checked, out = run(port)
        with contextlib.redirect_stdout(out):
            checked.run()
        self.assertIn('PROVEN', out.getvalue())
        post = [call for call in port.calls if call[1] == '/v1/limits'][0][2]
        self.assertEqual((post['action'], post['meter'], post['scope_id']), ('wait', 'usd', 'api-bedrock'))
        sent = [call[2] for call in port.calls if call[1] == '/v1/jobs' and call[0] == 'POST']
        self.assertEqual({job['queue'] for job in sent}, {'sessions'})
        self.assertEqual({job['executor'] for job in sent}, {'api-bedrock'})
        self.assertTrue(port.lifted)

    def test_the_executor_option_moves_the_limit_and_the_jobs_to_another_executor(self):
        port = FakePort()
        checked, out = run(port, executor='api-bedrock-proof')
        with contextlib.redirect_stdout(out):
            checked.run()
        post = [call for call in port.calls if call[1] == '/v1/limits'][0][2]
        self.assertEqual(post['scope_id'], 'api-bedrock-proof')
        sent = [call[2] for call in port.calls if call[1] == '/v1/jobs' and call[0] == 'POST']
        self.assertEqual({job['executor'] for job in sent}, {'api-bedrock-proof'})

    def test_a_409_rearms_the_existing_limit_and_restores_it(self):
        port = FakePort(existing=['old-1'])
        checked, out = run(port, original_action='stop')
        with contextlib.redirect_stdout(out):
            checked.run()
        puts = [call[2] for call in port.calls if call[0] == 'PUT' and call[1] == '/v1/limits/old-1']
        self.assertEqual(puts[0]['action'], 'wait')
        self.assertEqual(puts[0]['maximum'], proof.LIMIT_MAX)
        self.assertEqual(puts[-2:], [{'lift': True}, {'maximum': 0.05, 'action': 'stop'}])

    def test_a_409_with_several_usd_limits_needs_the_id_and_an_unknown_action_stops_before_changing(self):
        port = FakePort(existing=['x', 'y'])
        checked, out = run(port)
        with contextlib.redirect_stdout(out), self.assertRaises(proof.NotProven):
            checked.arm()
        port = FakePort(existing=['x'])
        checked, out = run(port)
        with contextlib.redirect_stdout(out), self.assertRaises(proof.NotProven):
            checked.arm()
        self.assertFalse([c for c in port.calls if c[0] == 'PUT' and c[1].startswith('/v1/limits')])

    def test_a_call_that_could_pass_the_cap_is_not_made(self):
        port = FakePort(spent_tokens=10000)  # 10020 tokens in at US$ 1 per million: US$ 0.01002
        checked, out = run(port)
        with contextlib.redirect_stdout(out), self.assertRaises(proof.OverCap):
            checked.run()
        self.assertEqual([call for call in port.calls if call[1] == '/v1/jobs' and call[0] == 'POST'][1:], [])
        self.assertTrue(port.lifted)

    def test_the_cap_is_at_most_one_cent(self):
        with self.assertRaises(proof.OverCap):
            proof.Proof(FakePort(), cap_usd=0.02)

    def test_a_job_that_was_not_held_is_not_proven(self):
        checked, out = run(FakePort(hold=False))
        with contextlib.redirect_stdout(out), self.assertRaises(proof.NotProven):
            checked.run()

    def test_without_the_port_it_stops_and_never_prints_a_token(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(proof.main([], environ={'TOWER_PORT_TOKEN': 'secret-token'}), 2)
        self.assertNotIn('secret-token', err.getvalue())


if __name__ == '__main__':
    unittest.main()
