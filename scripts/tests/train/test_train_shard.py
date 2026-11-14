"""The shard key and the shadow report (SH-1, GX-34; fixtures in scripts/tests/test_train.py). Measurement only."""
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, ROOT, setUpModule  # noqa: E402,F401
import engine_role  # noqa: E402
import forge_events  # noqa: E402
import generate  # noqa: E402
import train_shard  # noqa: E402

KIND = 'train.batch.shards'
MANIFESTS = [
    {'id': 'alpha', 'paths': ['a/**']},
    {'id': 'beta', 'paths': ['b/**'], 'requires': {'alpha': '^1'}},
    {'id': 'gamma', 'paths': ['g/**'], 'requires': {'beta': '^1'}},
    {'id': 'delta', 'paths': ['d/**'], 'requires': {'alpha': '^1'}},
    {'id': 'omega', 'paths': ['o/**']},
]
FIRST, SECOND, THIRD, *_ = range(len(MANIFESTS))  # PR ids of the fixtures, never a number written in a test (LT1)
GENERATED = train_shard.generated_globs(generate.targets(ROOT).values())


class Key(unittest.TestCase):
    def test_a_single_unit_diff_is_the_unit_and_its_dependents_transitively(self):
        self.assertEqual(train_shard.key(MANIFESTS, ['b/x.ts']), ['unit:beta', 'unit:gamma'])
        self.assertEqual(train_shard.key(MANIFESTS, ['a/x.ts']),
                         ['unit:alpha', 'unit:beta', 'unit:delta', 'unit:gamma'])

    def test_two_units_whose_dependents_overlap_share_the_dependent(self):
        both = train_shard.key(MANIFESTS, ['b/x.ts', 'd/y.ts'])
        self.assertEqual(both, ['unit:beta', 'unit:delta', 'unit:gamma'])
        found = train_shard.collisions({FIRST: ['b/x.ts'], SECOND: ['a/y.ts']}, MANIFESTS)
        self.assertEqual(found, [{'prs': [FIRST, SECOND], 'key': ['unit:beta', 'unit:gamma'], 'files': ['a/y.ts', 'b/x.ts']}])

    def test_an_unclaimed_path_is_its_own_key(self):
        self.assertEqual(train_shard.key(MANIFESTS, ['docs/process/EVENTS.md']), ['path:docs/process/EVENTS.md'])
        found = train_shard.collisions({FIRST: ['docs/process/EVENTS.md', 'o/a'], SECOND: ['docs/process/EVENTS.md']}, MANIFESTS)
        self.assertEqual(found, [{'prs': [FIRST, SECOND], 'key': ['path:docs/process/EVENTS.md'],
                                  'files': ['docs/process/EVENTS.md']}])

    def test_generated_aggregates_are_not_unclaimed_collisions(self):
        for path in ('config/registry/train.json', 'scripts/lib/generated/contracts_events_pr_opened_v1.py',
                     'scripts/lib/generated/config_registry_train.py'):
            with self.subTest(path=path):
                self.assertEqual(train_shard.key(MANIFESTS, [path], GENERATED), [])
        # the contract a generated module is rendered from is hand-written: it is still a real path
        self.assertEqual(train_shard.key(MANIFESTS, ['contracts/events/pr.opened.v1.json'], GENERATED),
                         ['path:contracts/events/pr.opened.v1.json'])
        self.assertEqual(train_shard.collisions({FIRST: ['config/registry/train.json'], SECOND: ['config/registry/train.json']},
                                                MANIFESTS, GENERATED), [])

    def test_the_union_key_is_the_union_of_the_members_and_shards_group_by_shared_elements(self):
        files = {FIRST: ['a/x'], SECOND: ['b/y'], THIRD: ['o/z']}
        found = train_shard.report(MANIFESTS, files)
        self.assertEqual(found['union_key'], sorted({e for m in found['members'] for e in m['key']}))
        self.assertEqual([shard['prs'] for shard in found['shards']], [[FIRST, SECOND], [THIRD]])

    def test_only_one_key_mode_is_understood(self):
        self.assertEqual(train_shard.check_mode('units+dependents'), 'units+dependents')
        with self.assertRaises(train_shard.ShardError):
            train_shard.check_mode('lanes')


class Shadow(Fixture):
    def base_files(self):
        return {f'units/{m["id"]}/unit.json': json.dumps(m) for m in MANIFESTS}

    def batch(self):
        one, two, three = self.make({'a/x': '1\n'}, {'b/y': '2\n'}, {'o/z': '3\n'})
        self.train.start_batch(self.train.queue())
        return one, two, three

    def test_a_batch_announces_its_keys_shards_and_collisions_once(self):
        self.assertTrue(engine_role.setting('train.shard_shadow'))
        one, two, three = self.batch()
        [event] = self.events(None, KIND)
        payload = event['payload']
        self.assertEqual(payload['base_sha'], self.base)
        self.assertEqual(payload['shard_key'], 'units+dependents')
        self.assertEqual([m['pr'] for m in payload['members']], [one.number, two.number, three.number])
        self.assertEqual([shard['prs'] for shard in payload['shards']], [[one.number, two.number], [three.number]])
        self.assertEqual([c['prs'] for c in payload['collisions']], [[one.number, two.number]])
        self.assertEqual(payload['collisions'][0]['files'], ['a/x', 'b/y'])
        self.assertEqual(payload['union_key'], train_shard.key(MANIFESTS, ['a/x', 'b/y', 'o/z']))

    def test_the_shadow_changes_nothing_else(self):
        self.batch()
        [started] = self.events(None, 'train.batch.started')
        [shards] = self.events(None, KIND)
        self.assertEqual(shards['payload']['batch_id'], started['payload']['batch_id'])

    def test_a_shadow_the_forge_refuses_never_stops_the_batch(self):
        """GATE-SPEED (#817): a batch of 954 changed files made the event too large for one comment and the train exited;
        the shadow is measurement only, so its failure is printed and the batch goes on."""
        real = forge_events.ForgeEvents.emit

        def emit(port, kind, *args, **kwargs):
            if kind == KIND:
                raise forge_events.ForgeEventsError(f'{kind} does not fit in one comment')
            return real(port, kind, *args, **kwargs)
        with mock.patch.object(forge_events.ForgeEvents, 'emit', autospec=True, side_effect=emit):
            self.batch()
        self.assertEqual(self.events(None, KIND), [])
        self.assertEqual(len(self.events(None, 'train.batch.started')), 1)

    def test_it_emits_nothing_when_shadow_is_off(self):
        real = engine_role.setting
        with mock.patch.object(engine_role, 'setting',
                               side_effect=lambda name: False if name == 'train.shard_shadow' else real(name)):
            self.batch()
        self.assertEqual(self.events(None, KIND), [])
        self.assertEqual(len(self.events(None, 'train.batch.started')), 1)

    def test_a_key_mode_nobody_understands_is_an_error(self):
        real = engine_role.setting
        with mock.patch.object(engine_role, 'setting',
                               side_effect=lambda name: 'lanes' if name == 'train.shard_key' else real(name)):
            self.make({'a/x': '1\n'})
            with self.assertRaises(train_shard.ShardError):
                self.train.start_batch(self.train.queue())


if __name__ == '__main__':
    unittest.main()
