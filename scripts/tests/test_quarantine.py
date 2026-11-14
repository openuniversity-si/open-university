"""The flaky-test quarantine (plan v3 M7). In-memory forge log, fixture unit manifests in a local git repository,
injected clock. No network; every tunable comes from the registry (config.get).
"""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import forge_events  # noqa: E402
import quarantine  # noqa: E402
import train_git  # noqa: E402
import train_ownership  # noqa: E402

REPO = 'openuniversity-si/open-university'
GIT_ENV = {'GIT_AUTHOR_NAME': 'fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.invalid',
           'GIT_COMMITTER_NAME': 'fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.invalid',
           'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}
SHA_A, SHA_B = 'a' * 40, 'b' * 40


class FakeClock:
    def __init__(self, start=datetime(2026, 10, 26, 20, 0, tzinfo=timezone.utc), step=timedelta(seconds=1)):
        self.moment, self.step = start, step

    def now(self):
        current = self.moment
        self.moment += self.step
        return current


class Result:
    def __init__(self, stage, tests=()):
        self.stage, self.tests = stage, tests


class Detection(unittest.TestCase):
    def test_a_red_run_on_a_sha_with_a_green_run_is_a_flake(self):
        runs = [quarantine.Run(SHA_A, True, (), ''), quarantine.Run(SHA_A, False, ('src/x.test.ts',), 'log')]
        self.assertEqual(quarantine.flaked(runs), [(SHA_A, 'src/x.test.ts', 'log')])
        self.assertTrue(quarantine.proven_flaky(runs[1], runs))

    def test_the_order_of_the_runs_does_not_matter(self):
        runs = [quarantine.Run(SHA_A, False, ('t',), None), quarantine.Run(SHA_A, True, (), None)]
        self.assertEqual(quarantine.flaked(runs), [(SHA_A, 't', None)])

    def test_red_without_a_green_run_on_the_same_sha_is_not_a_flake(self):
        runs = [quarantine.Run(SHA_A, True, (), ''), quarantine.Run(SHA_B, False, ('t',), ''),
                quarantine.Run(SHA_B, False, ('t',), '')]
        self.assertEqual(quarantine.flaked(runs), [], 'two reds are no evidence, and another sha is not this one')
        self.assertFalse(quarantine.proven_flaky(runs[1], runs))
        self.assertFalse(quarantine.proven_flaky(runs[0], runs), 'a green run is never a flake')

    def test_each_test_flakes_once_per_sha(self):
        runs = [quarantine.Run(SHA_A, False, ('t', 'u'), ''), quarantine.Run(SHA_A, False, ('t',), ''),
                quarantine.Run(SHA_A, True, (), '')]
        self.assertEqual([test for _, test, _ in quarantine.flaked(runs)], ['t', 'u'])

    def test_failing_tests_prefer_files_then_the_stage_then_the_fallback(self):
        self.assertEqual(quarantine.failing_tests(Result('unit tests', ('src/a.test.ts',)), 'tier2'),
                         ('src/a.test.ts',))
        self.assertEqual(quarantine.failing_tests(Result('unit tests'), 'tier2'), ('unit tests',))
        self.assertEqual(quarantine.failing_tests(Result(None), 'tier2'), ('tier2',))

    def test_stabilizes_lines(self):
        body = 'Fixes the race.\nStabilizes: src/a.test.ts, e2e/b.spec.ts\nStabilizes:  unit tests \nPremises: none\n'
        self.assertEqual(quarantine.stabilized(body), ['src/a.test.ts', 'e2e/b.spec.ts', 'unit tests'])
        self.assertEqual(quarantine.stabilized(None), [])


class Manifests(unittest.TestCase):
    """A local repository with one unit manifest, read through the train's ownership interface."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        self.git('init', '--quiet', '-b', 'main')
        manifest = {'id': 'catalog-domain', 'owner': 'catalog-lane', 'paths': ['products/demo/src/catalog/**']}
        path = self.dir / 'units' / 'catalog-domain' / 'unit.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(manifest))
        self.git('add', '-A')
        self.git('commit', '--quiet', '-m', 'units')
        self.commit = self.git('rev-parse', 'HEAD')
        self.owners = train_ownership.UnitOwnership(train_git.GitWorkspace(self.dir))

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.dir), *args], capture_output=True, text=True, check=True,
                              env=dict(os.environ, **GIT_ENV)).stdout.strip()

    def test_owner_of_a_covered_file_and_of_none(self):
        self.assertEqual(self.owners.owner_of(self.commit, 'products/demo/src/catalog/a.test.ts'),
                         ('catalog-domain', 'catalog-lane'))
        self.assertEqual(self.owners.owner_of(self.commit, 'scripts/tests/test_x.py'), (None, None))

    def test_the_quarantine_tries_the_test_roots_and_falls_back_to_the_unknown_owner(self):
        q = quarantine.Quarantine(REPO, self.owners)
        self.assertEqual(q.owner(self.commit, 'products/demo/src/catalog/a.test.ts'), ('catalog-domain', 'catalog-lane'))
        q.test_roots = ['', 'products/demo/']  # a product's package prefix (the engine registry has only '', D-113)
        self.assertEqual(q.owner(self.commit, 'src/catalog/a.test.ts'), ('catalog-domain', 'catalog-lane'))
        self.assertEqual(q.owner(self.commit, 'unit tests'), (None, config.get('quarantine.unknown_owner')))
        self.assertEqual(quarantine.Quarantine(REPO).owner(self.commit, 'src/catalog/a.test.ts'),
                         (None, config.get('quarantine.unknown_owner')), 'no manifests interface: owner unknown')


class Events(unittest.TestCase):
    def setUp(self):
        self.forge = forge_events.MemoryAdapter()
        self.clock = FakeClock()
        self.port = forge_events.ForgeEvents(self.forge, self.clock, 'train', 'b-1')
        self.q = quarantine.Quarantine(REPO)
        self.unknown = config.get('quarantine.unknown_owner')

    def events(self, kind):
        read = forge_events.ForgeEvents(self.forge, self.clock, 'reader', 'test').read(REPO, None)
        return [event for event in read if event['type'] == kind]

    def test_a_flake_is_reported_and_quarantined_with_its_owner(self):
        self.assertEqual(self.q.report(self.port, [(SHA_A, 't', 'log')]), ['t'])
        [flaked] = self.events('test.flaked')
        [opened] = self.events('test.quarantined')
        self.assertEqual((flaked['payload']['sha'], flaked['payload']['test'], flaked['payload']['pr']),
                         (SHA_A, 't', None))
        self.assertEqual((opened['payload']['owner'], opened['payload']['flaked_event']),
                         (self.unknown, flaked['event_id']))
        [step] = self.events('engine.step.measured')
        self.assertEqual((step['payload']['step'], step['payload']['result']),
                         (config.get('quarantine.step_prefix') + 'flaked', 'ok'))

    def test_a_test_already_in_quarantine_only_adds_evidence(self):
        self.q.report(self.port, [(SHA_A, 't', None)])
        self.assertEqual(self.q.report(self.port, [(SHA_B, 't', None), (SHA_A, 't', None)]), [])
        self.assertEqual(len(self.events('test.flaked')), 2, 'the same sha and test is the same event (idempotent)')
        self.assertEqual(len(self.events('test.quarantined')), 1)

    def test_no_flake_emits_nothing(self):
        self.assertEqual(self.q.report(self.port, []), [])
        self.assertEqual(self.forge.appends, 0)

    def test_the_open_quarantines_are_a_replay_of_the_log(self):
        self.q.report(self.port, [(SHA_A, 't', None), (SHA_A, 'u', None)])
        empty = forge_events.ForgeEvents(forge_events.MemoryAdapter(), self.clock, 'r', 'c')
        self.assertEqual(quarantine.state(empty.read(REPO)), {})
        replayed = quarantine.state(self.forge.read(forge_events.Channel(REPO, None)))
        self.assertEqual(sorted(replayed), ['t', 'u'])
        self.assertEqual(replayed, self.q.open(self.port), 'the raw log and the port read give the same state')
        self.assertEqual(replayed['t']['owner'], self.unknown)

    def test_the_stabilizing_pr_releases_and_a_later_flake_quarantines_again(self):
        self.q.report(self.port, [(SHA_A, 't', None)])
        body = 'Stabilizes: t\nStabilizes: never-quarantined'
        self.assertEqual(self.q.release(self.port, 7, None, SHA_B, body), ['t'])
        [ended] = self.events('test.unquarantined')
        [opened] = self.events('test.quarantined')
        payload = ended['payload']
        self.assertEqual((payload['stabilizing_pr'], payload['quarantined_event'], payload['sha']),
                         (7, opened['event_id'], SHA_B))
        self.assertEqual(self.q.open(self.port), {})
        release = [e for e in self.events('engine.step.measured') if e['payload']['step'].endswith('release')]
        self.assertEqual(release[0]['payload']['result'], 'blocked', 'a named test that was not released is visible')
        self.q.report(self.port, [('c' * 40, 't', None)])
        self.assertEqual(list(self.q.open(self.port)), ['t'])

    def test_only_the_owner_lane_releases_a_test_with_a_known_owner(self):
        subject = forge_events.subject(REPO, None, SHA_A, (), 'catalog-domain')
        flaked = self.port.emit('test.flaked', dict(subject, test='t', log=None))
        self.port.emit('test.quarantined', dict(subject, test='t', owner='catalog-lane',
                                                flaked_event=flaked['event_id']))
        self.assertEqual(self.q.release(self.port, 8, 'media-lane', SHA_B, 'Stabilizes: t'), [])
        self.assertEqual(self.q.release(self.port, 9, 'catalog-lane', SHA_B, 'Stabilizes: t'), ['t'])
        self.assertEqual(self.events('test.unquarantined')[0]['payload']['unit'], 'catalog-domain')

    def test_a_body_without_stabilizes_reads_nothing(self):
        self.assertEqual(self.q.release(self.port, 7, None, SHA_B, 'Premises: none'), [])
        self.assertEqual(self.forge.appends, 0)

    def test_overdue_after_the_registry_age(self):
        self.q.report(self.port, [(SHA_A, 't', None)])
        open_ = self.q.open(self.port)
        since = datetime.fromisoformat(open_['t']['since'].replace('Z', '+00:00'))
        limit = timedelta(seconds=config.get('quarantine.max_age_s'))
        self.assertEqual(quarantine.overdue(open_, since + limit), [])
        self.assertEqual(quarantine.overdue(open_, since + limit + timedelta(seconds=1)), ['t'])

    def test_list_renders_the_open_quarantines_oldest_first(self):
        self.q.report(self.port, [(SHA_A, 't', None)])
        self.q.report(self.port, [(SHA_B, 'u', None)])
        open_ = self.q.open(self.port)
        late = datetime.fromisoformat(open_['u']['since'].replace('Z', '+00:00')) \
            + timedelta(seconds=config.get('quarantine.max_age_s'))
        lines = quarantine.render(open_, late)
        self.assertEqual([line.split()[0] for line in lines], ['t', 'u'])
        self.assertTrue(lines[0].endswith('overdue') and not lines[1].endswith('overdue'))
        self.assertIn(f'owner={self.unknown}', lines[0])


class Registry(unittest.TestCase):
    def test_every_quarantine_entry_is_typed_documented_and_read(self):
        document = config.files()['quarantine'][1]
        self.assertEqual(document['x-owner'], 'quarantine')
        for name, item in document['properties'].items():
            with self.subTest(name=name):
                self.assertTrue(name.startswith('quarantine.'))
                self.assertTrue(item['description'].strip() and item['x-unit'] and item['x-readers'])
                self.assertTrue(all((ROOT / reader).is_file() for reader in item['x-readers']))


if __name__ == '__main__':
    unittest.main()
