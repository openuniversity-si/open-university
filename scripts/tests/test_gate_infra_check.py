"""F37-INFRA-CHECK (D-313): the infra judge publishes tower/gate on the head: pending before the checks exist, success or
failure before the landing exists. Hermetic: a fake port, an injected clock and an injected publisher; no network."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'lib'))
import config  # noqa: E402
import gate_infra  # noqa: E402
import gate_status  # noqa: E402

SHA = 'a' * 40
SPEC = {'repo': 'org/repo', 'pr': '7', 'head': SHA, 'base': 'b' * 40, 'ref': 'units/x', 'base_ref': 'mod/roadmap-integration'}
PLAN = {'kind': 'scoped', 'stages': ['schema compat'], 'tests': ['scripts/tests/a.test.sh'], 'reason': 'test'}
TREES = {'head': 'h' * 40, 'base': 'g' * 40}


class Trail:
    """One ordered record of what the port and the publisher were asked, to prove the order."""

    def __init__(self):
        self.events = []

    def mark(self, *item):
        self.events.append(item)

    def names(self):
        return [item[0] for item in self.events]


class FakePort:
    def __init__(self, trail, outcome='succeeded', landing='succeeded'):
        self.trail, self.outcome, self.landing, self.jobs, self.n = trail, outcome, landing, {}, 0

    def call(self, method, path, body=None):
        if path == '/v1/jobs/batch':  # JOBS-BATCH: the checks in one call
            return {'jobs': [self.call(method, '/v1/jobs', each) for each in body['jobs']]}
        if path == '/v1/jobs':
            self.n += 1
            kind = 'land' if (body or {}).get('queue') == config.get('gate-infra.land_queue') else 'check'
            self.jobs[f'j{self.n}'] = kind
            self.trail.mark('job:' + kind)
            return {'id': f'j{self.n}', 'created': True}
        if path == '/v1/log/query':
            events = []
            for job, kind in self.jobs.items():
                state = self.landing if kind == 'land' else self.outcome
                events.append({'event_id': f'e-{job}', 'occurred_at': f'2030-01-01T00:00:0{job[1:]}+00:00', 'type': 'run.ended',
                               'payload': {'job_id': job, 'state': state}})
            return {'events': events}
        if path.startswith('/v1/jobs/'):
            return {'state': 'succeeded', 'result': {'merge_sha': 'm' * 40}, 'runs': []}
        if path == '/v1/deploy/landed':
            self.trail.mark('landed')
            return {}
        if path.endswith('/cancel'):
            self.trail.mark('cancel')
            return {}
        raise AssertionError(path)


class Published:
    def __init__(self, trail, fail=False):
        self.trail, self.fail, self.calls = trail, fail, []

    def set_status(self, sha, state, description):
        self.trail.mark('status:' + state, sha, description)
        self.calls.append((sha, state, description))
        if self.fail:
            raise RuntimeError('control plane answered 503')


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        self.t += 0.5
        return self.t


class InfraCheck(unittest.TestCase):
    def setUp(self):
        self.trail = Trail()
        self.switches = {'gate.check_run_enabled': True, 'forge-events.status_enabled': True, 'gate.check_run_required': False}
        read = config.get
        self.enterContext(mock.patch.object(config, 'get', side_effect=lambda key, *a, **k:
                                            self.switches[key] if key in self.switches else read(key, *a, **k)))
        self.enterContext(mock.patch.object(gate_infra, 'plan_of', return_value=PLAN))
        self.enterContext(mock.patch.object(gate_infra, 'git', return_value='t' * 40))
        self.enterContext(mock.patch.object(gate_infra, 'metadata_of', return_value=(True, 'ok')))
        self.enterContext(mock.patch.object(gate_infra, 'kept'))
        self.logs = []

    def hooks(self, publisher):
        return gate_status.check_hooks(SHA, publisher, log=self.logs.append)

    def land(self, port, publisher):
        hooks = self.hooks(publisher)
        hooks[0]()
        return gate_infra.judge(port, SPEC, PLAN, TREES, 'today', shadow=False, clock=Clock(), sleep=lambda s: None,
                                before_landing=hooks[1])

    def test_green_publishes_pending_then_checks_then_success_then_landing(self):
        pub = Published(self.trail)
        verdict = self.land(FakePort(self.trail), pub)
        self.assertEqual(verdict['verdict'], 'green')
        names = self.trail.names()
        self.assertEqual(names[0], 'status:pending')
        self.assertLess(names.index('job:check'), names.index('status:success'))
        self.assertLess(names.index('status:success'), names.index('job:land'))
        self.assertTrue(all(call[0] == SHA for call in pub.calls))
        self.assertIn('passed', pub.calls[-1][2])
        self.assertEqual(self.logs, [])

    def test_red_publishes_failure_and_never_creates_the_landing(self):
        verdict = self.land(FakePort(self.trail, outcome='failed'), Published(self.trail))
        self.assertEqual(verdict['verdict'], 'red')
        self.assertIn('status:failure', self.trail.names())
        self.assertNotIn('job:land', self.trail.names())

    def test_a_failed_publish_is_logged_and_the_delivery_lands_while_not_required(self):
        verdict = self.land(FakePort(self.trail), Published(self.trail, fail=True))
        self.assertEqual(verdict['verdict'], 'green')
        self.assertEqual(len(self.logs), 2)  # pending and success
        self.assertIn('the delivery goes on', self.logs[0])
        self.assertIn('job:land', self.trail.names())

    def test_a_failed_publish_blocks_once_required(self):
        self.switches['gate.check_run_required'] = True
        with self.assertRaisesRegex(RuntimeError, 'gate.check_run_required'):
            self.land(FakePort(self.trail), Published(self.trail, fail=True))
        self.assertNotIn('job:check', self.trail.names())  # pending is the first publish and it stopped the run

    def test_required_success_publish_failure_stops_before_the_landing(self):
        self.switches['gate.check_run_required'] = True
        pub = Published(self.trail)
        hooks = self.hooks(pub)
        hooks[0]()
        pub.fail = True
        with self.assertRaises(RuntimeError):
            gate_infra.judge(FakePort(self.trail), SPEC, PLAN, TREES, 'today', shadow=False, clock=Clock(),
                             sleep=lambda s: None, before_landing=hooks[1])
        self.assertNotIn('job:land', self.trail.names())

    def test_a_red_verdict_is_red_even_when_the_failure_publish_fails_required(self):
        self.switches['gate.check_run_required'] = True
        pub = Published(self.trail)
        hooks = self.hooks(pub)
        hooks[0]()
        pub.fail = True
        verdict = gate_infra.judge(FakePort(self.trail, outcome='failed'), SPEC, PLAN, TREES, 'today', shadow=False,
                                   clock=Clock(), sleep=lambda s: None, before_landing=hooks[1])
        self.assertEqual(verdict['verdict'], 'red')
        self.assertEqual(len(self.logs), 1)

    def test_off_when_the_check_run_is_disabled(self):
        self.switches['gate.check_run_enabled'] = False
        self.assertIsNone(self.hooks(Published(self.trail)))

    def test_without_the_hook_the_landing_is_made_with_the_checks(self):
        verdict = gate_infra.judge(FakePort(self.trail), SPEC, PLAN, TREES, 'today', shadow=False, clock=Clock(),
                                   sleep=lambda s: None)
        self.assertEqual(verdict['verdict'], 'green')
        self.assertEqual(self.trail.names().count('job:land'), 1)
        self.assertLess(self.trail.names().index('job:check'), self.trail.names().index('job:land'))

    def test_late_publishes_failure(self):
        clock = Clock()
        port = FakePort(self.trail)
        port.outcome = 'running'  # never ends: ENDED excludes it
        with mock.patch.dict(self.switches, {'gate-infra.wait_s': 1}):
            pub = Published(self.trail)
            hooks = self.hooks(pub)
            verdict = gate_infra.judge(port, SPEC, PLAN, TREES, 'today', shadow=False, clock=clock, sleep=lambda s: None,
                                       before_landing=hooks[1])
        self.assertEqual(verdict['verdict'], 'late')
        self.assertEqual(pub.calls[-1][1], 'failure')
        self.assertNotIn('job:land', self.trail.names())


if __name__ == '__main__':
    unittest.main()
