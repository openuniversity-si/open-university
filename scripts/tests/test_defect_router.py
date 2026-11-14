"""The known-defect router (KD1). Fixture register in a temp directory, in-memory forge log, injected clock."""
from datetime import timedelta
import contextlib
import io
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
import config  # noqa: E402
import defect_router  # noqa: E402
import defects  # noqa: E402
import forge_events  # noqa: E402
import gate_script_tests  # noqa: E402
import test_defects  # noqa: E402
import units  # noqa: E402

REPO = config.get('forge-events.repo')
BASE = config.get('train.base_branch')
MANIFESTS = {'engine-x': {'requires': {}}, 'app': {'requires': {'engine-x': '>=1'}}, 'site': {'requires': {'app': '>=1'}},
             'other': {'requires': {}}}
MAPPING = {'tests': ({'script': 'a.test.sh', 'covers': ('scripts/tests/*.test.sh',)},
                     {'script': 'b.test.sh', 'covers': ('scripts/lib/x.py', 'scripts/tests/x.test.sh')},
                     {'script': 'c.test.sh', 'covers': ('products/demo/**',)})}


class Adapter(forge_events.MemoryAdapter):
    def __init__(self, open_):
        super().__init__()
        self.open_ = open_

    def open_changes(self, repo, base):
        return list(self.open_)


class Router(test_defects.Fixture):
    def setUp(self):
        super().setUp()
        for target, value in ((units, 'manifests'), (gate_script_tests, 'load')):
            patch = mock.patch.object(target, value, side_effect=lambda *a, _v=value, **k: MANIFESTS if _v == 'manifests' else MAPPING)
            patch.start()
            self.addCleanup(patch.stop)
        self.port = forge_events.ForgeEvents(Adapter([3, 7, 9]), self.clock, 'defects', 'test')

    def opened(self, pr, named):
        self.port.emit('pr.opened', dict(forge_events.subject(REPO, pr, test_defects.SHA_A, (), None), units=named,
                                         base_sha=test_defects.SHA_B, lane_id=None))

    def queue(self, *named):
        for pr, units_ in zip((3, 7, 9), named):
            if units_ is not None:
                self.opened(pr, units_)
        return defect_router.queue(self.port, REPO, BASE)

    def types(self):
        return [e['type'] for e in self.port.adapter.read(forge_events.Channel(REPO, None))]


class Priority(Router):
    def test_queue_lists_open_prs_with_units_only(self):
        self.assertEqual(self.queue(['engine-x'], None, ['other', 'app']), [{'pr': 3, 'units': ['engine-x']}, {'pr': 9, 'units': ['app', 'other']}])

    def test_priority_is_weights_times_counts(self):
        found, _ = self.record()
        cost = defect_router.impact(found, self.queue(['engine-x'], ['engine-x', 'app'], ['other']), self.tmp)
        w = config.get
        expected = w('defects.weight_touching_unit') * 2 + w('defects.weight_dependent_unit') * 2 + w('defects.weight_masked_test') * 2
        self.assertEqual(cost['priority'], expected)
        self.assertEqual((cost['touching'], cost['dependent_units'], cost['masked']), ([3, 7], ['app', 'site'], 2))

    def test_dependents_follow_requires_transitively(self):
        self.assertEqual(defect_router.dependents('engine-x', self.tmp), ['app', 'site'])
        self.assertEqual(defect_router.dependents('site', self.tmp), [])

    def test_masked_counts_tests_covering_the_area_or_the_test(self):
        found, _ = self.record()
        self.assertEqual(defect_router.masked(found, MAPPING), 2)
        self.assertEqual(defect_router.masked(dict(found, area=[], test='nowhere'), MAPPING), 0)

    def test_classes_follow_the_thresholds(self):
        found, _ = self.record()
        low, high, critical = config.get('defects.priority_classes')
        by_count = {}
        for touching in range(4):
            cost = defect_router.impact(found, [{'pr': n + 1, 'units': ['engine-x']} for n in range(touching)], self.tmp)
            by_count[touching] = cost
            limits = (config.get('defects.high_priority'), config.get('defects.critical_priority'))
            want = critical if cost['priority'] >= limits[1] else high if cost['priority'] >= limits[0] else low
            self.assertEqual(cost['class'], want)
        self.assertEqual([by_count[0]['class'], by_count[3]['class']], [high, critical])
        self.assertLess(by_count[0]['priority'], by_count[3]['priority'])

    def test_no_clock_or_deadline_enters_the_priority(self):
        found, _ = self.record()
        queue = self.queue(['engine-x'])
        first = defect_router.impact(found, queue, self.tmp)
        self.clock.moment += timedelta(hours=5)
        self.assertEqual(defect_router.impact(found, queue, self.tmp), first)
        self.assertNotIn('time', ' '.join(config.get('defects.priority_classes')))

    def test_a_defect_without_a_unit_is_priced_by_the_queue_only(self):
        with mock.patch.object(defects, 'derive_owner', side_effect=lambda *a, **k: (None, 'maestro', [])):
            found, _ = self.record(test='nowhere')
            cost = defect_router.impact(found, [{'pr': 3, 'units': ['engine-x']}], self.tmp)
            self.assertEqual((cost['touching'], cost['dependent_units'], cost['masked'], cost['priority']), ([], [], 0, 0))
            self.assertEqual(defect_router.route(self.tmp, self.port, REPO, test_defects.SHA_A, [], 'router', self.clock), [])


class Routing(Router):
    def test_route_assigns_work_routes_and_moves_to_fixing_once(self):
        found, _ = self.record()
        queue = self.queue(['engine-x'], ['app'])
        routed = defect_router.route(self.tmp, self.port, REPO, test_defects.SHA_B, queue, 'router', self.clock)
        self.assertEqual([item['id'] for item in routed], [found['id']])
        self.assertEqual(self.types().count('work.assigned'), 1)
        self.assertEqual(self.types().count('defect.routed'), 1)
        now = defects.load(self.tmp)[0][found['id']]
        assigned = [e for e in self.port.adapter.read(forge_events.Channel(REPO, None)) if e['type'] == 'work.assigned'][0]
        self.assertEqual(now['status'], 'fixing')
        self.assertEqual(now['fix'], {'lane': 'engine-lane', 'item': config.get('defects.fix_item').format(id=found['id']),
                                      'work_event': assigned['event_id'], 'pr': None, 'merge_sha': None})
        self.assertEqual((assigned['payload']['lane_id'], assigned['payload']['units'], assigned['payload']['pr']), ('engine-lane', ['engine-x'], None))
        self.assertEqual(defects.check(self.tmp)[1], [])

    def test_route_is_idempotent(self):
        self.record()
        queue = self.queue(['engine-x'])
        defect_router.route(self.tmp, self.port, REPO, test_defects.SHA_B, queue, 'router', self.clock)
        again = defect_router.route(self.tmp, self.port, REPO, test_defects.SHA_B, queue, 'router', self.clock)
        self.assertEqual(again, [])
        self.assertEqual((self.types().count('work.assigned'), self.types().count('defect.routed')), (1, 1))

    def test_dependents_only_at_or_above_depends_min_priority(self):
        found, _ = self.record()
        queue = self.queue(['engine-x'])
        threshold = config.get('defects.depends_min_priority')
        self.assertGreaterEqual(defect_router.impact(found, queue, self.tmp)['priority'], threshold)
        defect_router.route(self.tmp, self.port, REPO, test_defects.SHA_B, queue, 'router', self.clock)
        routed = [e for e in self.port.adapter.read(forge_events.Channel(REPO, None)) if e['type'] == 'defect.routed'][0]['payload']
        self.assertEqual((routed['touching'], routed['dependents']), ([3], [3]))
        with mock.patch.object(config, 'get', side_effect=lambda key: 10 ** 6 if key == 'defects.depends_min_priority' else config_get(key)):
            self.record(signature='other sig')
            defect_router.route(self.tmp, self.port, REPO, test_defects.SHA_B, queue, 'router', self.clock)
        later = [e for e in self.port.adapter.read(forge_events.Channel(REPO, None)) if e['type'] == 'defect.routed'][-1]['payload']
        self.assertEqual((later['touching'], later['dependents']), ([3], []))

    def test_highest_priority_first_then_id(self):
        self.record()
        self.record(signature='other sig')
        routed = defect_router.route(self.tmp, self.port, REPO, test_defects.SHA_B, self.queue(['engine-x']), 'router', self.clock)
        self.assertEqual([item['id'] for item in routed], sorted(item['id'] for item in routed))

    def test_below_the_minimum_nothing_is_opened(self):
        self.record()
        with mock.patch.object(config, 'get', side_effect=lambda key: 10 ** 6 if key == 'defects.fix_unit_min_priority' else config_get(key)):
            self.assertEqual(defect_router.route(self.tmp, self.port, REPO, test_defects.SHA_B, [], 'router', self.clock), [])
        self.assertEqual(self.types(), ['defect.registered'])

    def test_priority_command_prints_and_writes_nothing(self):
        found, _ = self.record()
        self.queue(['engine-x'])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(defect_router.main(['priority'], self.tmp, self.port), 0)
        self.assertIn(found['id'], out.getvalue())
        self.assertIn('touching=3', out.getvalue())
        self.assertEqual(defects.load(self.tmp)[0][found['id']]['status'], 'open')

    def test_route_command_routes(self):
        found, _ = self.record()
        self.queue(['engine-x'])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(defect_router.main(['route', '--base-sha', test_defects.SHA_B], self.tmp, self.port), 0)
        self.assertIn(found['id'], out.getvalue())
        self.assertEqual(defects.load(self.tmp)[0][found['id']]['status'], 'fixing')


config_get = config.get

if __name__ == '__main__':
    unittest.main()
