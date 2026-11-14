"""The whole life of a base defect (KD1): detected by the gate, registered, routed to its owner, resolved by the fix PR's
merge, verified by the gate seeing the test pass on the base. Fake runner, in-memory forge log, fixture register."""
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
import defect_detect  # noqa: E402
import defect_router  # noqa: E402
import defects  # noqa: E402
from test_defects import SHA_A, SHA_B, SIGNATURE, STAGE, TEST, Fixture  # noqa: E402


class Lifecycle(Fixture):
    def setUp(self):
        super().setUp()
        # route() receives the queue explicitly. Its full forge contract still includes discovery, but this flow
        # must never rediscover or replace those inputs.
        self.port.adapter.open_changes = mock.Mock(side_effect=AssertionError('route must use the supplied queue'))
        for target, name, stand_in in ((defect_router, 'dependents', lambda unit, root: []),
                                       (defect_router.gate_script_tests, 'load', lambda root=None: {'tests': []})):
            patch = mock.patch.object(target, name, new=stand_in)
            patch.start()
            self.addCleanup(patch.stop)

    def event(self, kind, **extra):
        return self.port.build(kind, dict({
            'repo': config.get('forge-events.repo'), 'pr': None, 'sha': SHA_A, 'unit': None, 'premises': [],
            'defect': defects.defect_id(TEST, SIGNATURE), 'test': TEST, 'signature': SIGNATURE, 'owner': 'engine-lane',
            'base_sha': SHA_A, 'run': 'run-1'}, **extra))

    def status(self):
        return defects.load(self.tmp)[0][defects.defect_id(TEST, SIGNATURE)]['status']

    def test_open_fixing_resolved_verified_with_a_trail_and_events(self):
        ident = defects.defect_id(TEST, SIGNATURE)
        defects.sync(self.tmp, [self.event('defect.detected', stage=STAGE)], self.port, self.clock)
        self.assertEqual(self.status(), 'open')
        queue = [{'pr': 5, 'units': ['engine-x']}, {'pr': 6, 'units': ['elsewhere']}]
        routed = defect_router.route(self.tmp, self.port, config.get('forge-events.repo'), SHA_A, queue, 'router', self.clock)
        self.assertEqual([(item['id'], item['class']) for item in routed], [(ident, 'high')])
        self.assertEqual(self.status(), 'fixing')
        self.assertEqual(defect_router.route(self.tmp, self.port, config.get('forge-events.repo'), SHA_A, queue, 'router', self.clock), [])
        defects.resolve(self.tmp, ident, 9, SHA_B, 'train', self.port, self.clock)
        self.assertEqual(self.status(), 'resolved')
        records = defects.load(self.tmp)[0]
        decided = defect_detect.verification(records, SHA_B, ROOT, self.tmp / 'cache', lambda test, base, root: {'result': 'pass', 'signature': ''}, now=1)
        self.assertEqual([(d['defect'], d['result']) for d in decided], [(ident, 'verified')])
        defects.sync(self.tmp, [self.event('defect.verified', base_sha=SHA_B, sha=SHA_B, run='run-2')], self.port, self.clock)
        done = defects.load(self.tmp)[0][ident]
        self.assertEqual(done['status'], 'verified')
        self.assertEqual([entry['action'] for entry in done['trail']], ['registered', 'routed', 'resolved', 'verified'])
        self.assertEqual(defects.check(self.tmp)[1], [])
        self.assertEqual(self.types(), ['defect.registered', 'work.assigned', 'defect.routed', 'defect.resolved'])

    def test_an_open_defect_that_no_longer_reproduces_is_resolved_then_verified_by_the_tool(self):
        """GX-13 (KD-024bbecb, KD-4db6e693): open defects are verified on every adjudication."""
        ident = defects.defect_id(TEST, SIGNATURE)
        defects.sync(self.tmp, [self.event('defect.detected', stage=STAGE)], self.port, self.clock)
        passes = lambda test, base, root: {'result': 'pass', 'signature': ''}
        decided = defect_detect.verification(defects.load(self.tmp)[0], SHA_B, ROOT, self.tmp / 'cache', passes, now=1)
        self.assertEqual([(d['defect'], d['result']) for d in decided], [(ident, 'verified')])
        self.assertEqual(defects.sync(self.tmp, [self.event('defect.verified', base_sha=SHA_B, sha=SHA_B, run='run-2')], self.port, self.clock),
                         [(ident, 'resolved')])
        self.assertEqual(self.status(), 'resolved')
        defects.sync(self.tmp, [self.event('defect.verified', base_sha=SHA_B, sha=SHA_B, run='run-3')], self.port, self.clock)
        done = defects.load(self.tmp)[0][ident]
        self.assertEqual((done['status'], [entry['action'] for entry in done['trail']]), ('verified', ['registered', 'resolved', 'verified']))
        self.assertEqual(defects.check(self.tmp)[1], [])

    def test_with_verify_open_off_an_open_defect_stays_open(self):
        defects.sync(self.tmp, [self.event('defect.detected', stage=STAGE)], self.port, self.clock)
        real = defects.setting
        with mock.patch.object(defects, 'setting', side_effect=lambda name: False if name == 'verify_open' else real(name)), \
             mock.patch.object(defect_detect, 'setting', side_effect=lambda name: False if name == 'verify_open' else config.get(f'defects.{name}')):
            records = defects.load(self.tmp)[0]
            passes = lambda test, base, root: {'result': 'pass', 'signature': ''}
            self.assertEqual(defect_detect.verification(records, SHA_B, ROOT, self.tmp / 'cache', passes, now=1), [])
            self.assertEqual(defects.sync(self.tmp, [self.event('defect.verified', base_sha=SHA_B, sha=SHA_B, run='run-2')], self.port, self.clock), [])
        self.assertEqual(self.status(), 'open')

    def test_the_units_touching_the_area_wait_only_above_the_registered_priority(self):
        defects.sync(self.tmp, [self.event('defect.detected', stage=STAGE)], self.port, self.clock)
        one = [{'pr': 5, 'units': ['engine-x']}]
        low = defect_router.priced(self.tmp, [])[0][1]
        high = defect_router.priced(self.tmp, one)[0][1]
        self.assertLess(low['priority'], high['priority'])
        self.assertEqual(high['touching'], [5])
        defect_router.route(self.tmp, self.port, config.get('forge-events.repo'), SHA_A, one, 'router', self.clock)
        routed = [e for e in self.port.adapter.read((config.get('forge-events.repo'), None)) if e['type'] == 'defect.routed'][0]
        expected = [5] if high['priority'] >= config.get('defects.depends_min_priority') else []
        self.assertEqual(routed['payload']['dependents'], expected)


if __name__ == '__main__':
    unittest.main()
