"""FAST-ON-LANDED: Origin's push events list no files, so the fast path reads its targets from platform.deploy.landed, which the
delivery records after the forge merge. Hermetic: fake database, fake Lambda/S3, fake port; nothing lands anywhere."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'infra' / 'service'))
sys.path.insert(0, str(ROOT / 'scripts' / 'tests'))
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
from tower_infra import autodeploy, http_port, port  # noqa: E402
import gate_infra  # noqa: E402
import test_infra_autodeploy as base  # noqa: E402
import test_infra_fastdeploy as fast  # noqa: E402

HEAD, MERGE, PR_HEAD, OTHER = base.HEAD, 'f' * 40, 'p' * 40, 'c' * 40
API = 'tower-port-api'


def landed(sha=MERGE, functions=(API,), paths=('infra/service/tower_infra/http_port.py',), pr_head=PR_HEAD, before=HEAD):
    return {'merge_sha': sha, 'base_before': before, 'pr': '423', 'pr_head': pr_head, 'functions': list(functions),
            'manifest_key': f'artifacts/lambda/head/{pr_head}.json', 'paths': None if paths is None else list(paths)}


class Rig:
    """The live shape: the push of the merge carries a headCommit with sha/author/message only, never a file list."""

    def __new__(cls, event=None, lam=None):
        lam = lam or fast.FakeLambda()
        store = fast.FakeS3({f'artifacts/lambda/head/{PR_HEAD}.json': fast.manifest(PR_HEAD, HEAD)})
        rig = base.Rig(fast=fast.fastdeploy.FastDeploy(lam, store, 'bucket', clock=fast.clock()))
        rig.db.artifacts[PR_HEAD] = {function: fast.DIGEST for function in fast.fastdeploy.FUNCTIONS}  # DIGEST-FROM-GATE-JOB
        rig.params[autodeploy.LAST_SHA] = HEAD
        rig.build('succeeded', HEAD, base.T0 - 5000, base.T0 - 4500, build_id='old')
        rig.db.push(base.T0 - 90000, HEAD)
        rig.db.push(base.T0 - 3, MERGE, headCommit={'sha': MERGE, 'author': 'x', 'message': 'one line (#423)'})
        if event is not None:
            rig.db.landed.append((base.T0 - 2, event))
        rig.lam = lam
        return rig

    @staticmethod
    def swaps(rig):
        return [call for call in rig.lam.calls if call[0] == 'update_alias']


class Autodeploy(unittest.TestCase):
    def test_a_landed_event_with_functions_swaps_though_the_push_lists_no_files(self):
        rig = Rig(landed())
        rig.look()
        self.assertEqual(Rig.swaps(rig), [('update_alias', API, '5')])
        entry = next(p for kind, p in rig.db.inserted if kind == autodeploy.FAST)
        self.assertEqual((entry['function'], entry['sha'], entry['ok']), (API, MERGE, True))

    def test_the_manifest_is_read_at_the_events_manifest_key_when_it_carries_no_pr_head(self):
        event = {**landed(), 'pr_head': None}
        rig = Rig(event)
        rig.look()
        self.assertEqual(Rig.swaps(rig), [('update_alias', API, '5')])

    def test_the_pr_head_is_the_first_manifest_candidate_not_the_merge_sha(self):
        rig = Rig(landed())
        rig.look()
        self.assertEqual(rig.watcher.manifest_commits(MERGE)[:2], [PR_HEAD, MERGE])
        self.assertEqual(Rig.swaps(rig), [('update_alias', API, '5')])

    def test_the_artifact_jobs_manifest_key_is_the_one_the_landed_event_names(self):
        import lambda_package
        self.assertEqual(lambda_package.head_key(PR_HEAD), landed()['manifest_key'])

    def test_without_the_landed_event_the_push_alone_cannot_say_and_nothing_swaps(self):
        rig = Rig()
        rig.look()
        self.assertEqual(Rig.swaps(rig), [])

    def test_a_landed_event_without_functions_swaps_nothing(self):
        rig = Rig(landed(functions=(), paths=['docs/x.md']))
        rig.look()
        self.assertEqual(Rig.swaps(rig), [])
        self.assertEqual([p for p in rig.db.observed[-1][1]['fast']], [])

    def test_a_merge_whose_push_never_arrived_is_a_head_of_the_base_through_its_landed_event(self):
        rig = Rig(landed())
        rig.db.pushes.pop()
        rig.look()
        self.assertEqual(Rig.swaps(rig), [('update_alias', API, '5')])

    def test_the_push_paths_stay_a_secondary_source_when_nothing_landed(self):
        rig = Rig()
        rig.db.pushes[-1][1][0]['headCommit'] = {'modified': ['infra/service/tower_infra/http_port.py']}
        rig.db.pushes[-1][1][0]['commits'] = [{'id': PR_HEAD}]
        rig.look()
        self.assertEqual(Rig.swaps(rig), [('update_alias', API, '5')])

    def test_a_change_to_the_same_files_landed_between_the_base_and_the_merge_makes_it_stale(self):
        rig = Rig(landed())
        middle = landed(sha=OTHER, functions=(API,), pr_head='q' * 40, before=HEAD)
        rig.db.landed.insert(0, (base.T0 - 50, middle))
        rig.db.push(base.T0 - 50, OTHER, headCommit={'sha': OTHER})
        rig.db.pushes.sort(key=lambda each: each[0])
        rig.look()
        self.assertEqual(Rig.swaps(rig), [])
        skipped = [each for each in rig.db.observed[-1][1]['fast'] if each['sha'] == MERGE]
        self.assertEqual([each['function'] for each in skipped], [API])
        self.assertIn('predate', skipped[0]['skipped'])

    def test_a_change_to_other_files_between_does_not_make_it_stale(self):
        rig = Rig(landed())
        rig.db.landed.insert(0, (base.T0 - 50, landed(sha=OTHER, functions=(), paths=['docs/a.md'], pr_head='q' * 40)))
        rig.db.push(base.T0 - 50, OTHER, headCommit={'sha': OTHER})
        rig.db.pushes.sort(key=lambda each: each[0])
        rig.look()
        self.assertEqual(Rig.swaps(rig), [('update_alias', API, '5')])

    def test_a_landing_without_paths_between_is_unknown_and_stale(self):
        rig = Rig(landed())
        rig.db.landed.insert(0, (base.T0 - 50, landed(sha=OTHER, functions=(), paths=None, pr_head='q' * 40)))
        rig.db.push(base.T0 - 50, OTHER, headCommit={'sha': OTHER})
        rig.db.pushes.sort(key=lambda each: each[0])
        rig.look()
        self.assertEqual(Rig.swaps(rig), [])

    def test_the_landed_paths_classify_the_slow_ring_instead_of_unknown(self):
        rig = Rig(landed(functions=(), paths=['docs/x.md']))
        rig.now = base.T0 + 25
        decision = rig.look()
        self.assertIn('fast only', decision[1])  # the push listed none: before, unknown rang a build for every merge
        self.assertEqual(rig.rings, [])
        slow = Rig(landed(functions=(), paths=['infra/aws/stacks/40-port.json']))
        slow.now = base.T0 + 25
        self.assertEqual(slow.look()[0], 'ring')

    def test_the_landed_event_wakes_the_look_and_is_in_the_notify_set(self):
        sql = (ROOT / 'infra/db/migrations/0013_wake_landed.sql').read_text()
        self.assertIn("'platform.deploy.landed'", sql)
        for kind in ('forge.repository.pushed', 'platform.deploy.ended', 'config.changed'):
            self.assertIn(f"'{kind}'", sql)


class Rows:
    def __init__(self):
        self.calls = []

    def rows(self, sql, params=None):
        self.calls.append((sql, params))
        return []


class Port(unittest.TestCase):
    def test_the_route_records_the_event_once_per_merge_for_a_tenant(self):
        db = Rows()
        answer = port.deploy_landed(db, ('tenant', '11111111-1111-1111-1111-111111111111'), landed())
        self.assertEqual(answer['event_id'], f'platform.deploy.landed:{MERGE}')
        sql, params = db.calls[0]
        self.assertIn('not exists', sql)
        self.assertEqual(json.loads(params['payload'])['functions'], [API])
        self.assertEqual(params['id'], f'platform.deploy.landed:{MERGE}')
        self.assertTrue(any(verb == 'POST' and pattern == r'/v1/deploy/landed' for verb, pattern, _ in http_port.ROUTES))

    def test_it_needs_a_tenant_a_sha_a_head_and_a_list(self):
        who = ('tenant', '11111111-1111-1111-1111-111111111111')
        with self.assertRaises(port.PortError):
            port.deploy_landed(Rows(), ('installation', None), landed())
        for bad in ({}, {**landed(), 'pr_head': ''}, {**landed(), 'merge_sha': 'zz'}, {**landed(), 'functions': 'x'}):
            with self.assertRaises(port.PortError):
                port.deploy_landed(Rows(), who, bad)


class FakePort:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if self.fail:
            raise gate_infra.Refused(503, 'down')
        return {}


class Publish(unittest.TestCase):
    green = {'verdict': 'green', 'landing': {'state': 'succeeded', 'result': {'merge_sha': MERGE}}}

    def diff(self, paths):
        return mock.patch.object(gate_infra, 'git', return_value='\n'.join(paths))

    def test_after_the_merge_the_event_carries_functions_manifest_and_paths(self):
        fake = FakePort()
        with self.diff(['infra/service/tower_infra/http_port.py', 'docs/x.md']):
            gate_infra.announce_landed(fake, ROOT, 423, PR_HEAD, HEAD, self.green)
        method, path, body = fake.calls[0]
        self.assertEqual((method, path), ('POST', '/v1/deploy/landed'))
        # SLOW-PATH-NO-ROLLOUT-WAIT: the consumer's package holds http_port too: both are named, or the port stack is applied for it
        self.assertEqual({key: value for key, value in body.items() if key != 'code'},  # IMAGE-PREWARM-C: code is
                         landed(functions=(API, 'tower-port-webhook-consumer'),  # test_infra_image_swap's
                                paths=['infra/service/tower_infra/http_port.py', 'docs/x.md']))
        self.assertIn('bundle_same', body['code'])

    def test_a_pr_without_a_fast_target_says_functions_empty(self):
        fake = FakePort()
        with self.diff(['docs/x.md']):
            gate_infra.announce_landed(fake, ROOT, 423, PR_HEAD, HEAD, self.green)
        self.assertEqual(fake.calls[0][2]['functions'], [])

    def test_a_shared_module_names_all_three_functions(self):
        fake = FakePort()
        with self.diff(['infra/service/tower_infra/forge_webhooks.py']):
            gate_infra.announce_landed(fake, ROOT, 423, PR_HEAD, HEAD, self.green)
        self.assertEqual(fake.calls[0][2]['functions'], sorted(gate_infra.LAMBDAS.values()))

    def test_nothing_is_announced_without_a_merge_and_a_failed_announce_never_fails_the_delivery(self):
        fake = FakePort()
        for judged in ({'verdict': 'red', 'landing': {}}, {'verdict': 'green', 'landing': {'state': 'failed'}}):
            gate_infra.announce_landed(fake, ROOT, 423, PR_HEAD, HEAD, judged)
        self.assertEqual(fake.calls, [])
        with self.diff(['docs/x.md']):
            self.assertIsNone(gate_infra.announce_landed(FakePort(fail=True), ROOT, 423, PR_HEAD, HEAD, self.green))

    def test_land_announces_once_the_forge_merge_succeeded(self):
        fake = FakePort()
        with self.diff(['docs/x.md']):
            judged, _ = gate_infra.land(423, PR_HEAD, HEAD, 'units/x', 'main', root=ROOT, port=fake, judged=dict(self.green))
        self.assertEqual([c[1] for c in fake.calls], ['/v1/deploy/landed'])
        self.assertEqual(judged['verdict'], 'green')


if __name__ == '__main__':
    unittest.main()
