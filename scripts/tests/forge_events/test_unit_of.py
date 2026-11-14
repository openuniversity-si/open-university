"""REC-1: forge_events.unit_of and the repository mirror of pr.merged (TX24: one file per feature)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_forge_events import HEAD, MERGE, REPO, gate, port  # noqa: E402,F401
import forge_events  # noqa: E402


class Ownership:
    """The part of train_ownership.UnitOwnership that unit_of uses: the same units() over fixed manifests."""

    def __init__(self, manifests):
        import train_ownership
        self.manifests_ = manifests
        self.real = train_ownership.UnitOwnership.__new__(train_ownership.UnitOwnership)
        self.real.manifests = lambda commit: manifests

    def units(self, *args):
        return self.real.units(*args)


PR = gate('passed')[1]['pr']
OTHER = PR + 1

UNITS = [{'id': 'GX-05', 'owner': 'a', 'paths': ['scripts/a/**']},
         {'id': 'GX-06', 'owner': 'b', 'paths': ['scripts/b/**', 'shared/**']},
         {'id': 'GX-07', 'owner': 'c', 'paths': ['shared/**']}]


class UnitOf(unittest.TestCase):
    def test_one_manifest_gives_its_lower_case_id(self):
        self.assertEqual(forge_events.unit_of(Ownership(UNITS), 'c', ['scripts/a/x.py']), 'gx-05')

    def test_no_manifest_gives_none(self):
        self.assertIsNone(forge_events.unit_of(Ownership(UNITS), 'c', ['docs/x.md']))

    def test_two_manifests_give_none(self):
        self.assertIsNone(forge_events.unit_of(Ownership(UNITS), 'c', ['shared/x.py']))

    def test_a_shared_path_still_names_its_unit(self):
        """SHARED-NEEDS-NO-OWNER: a shared path never refuses a change, yet it stays owned for naming."""
        units = [{'id': 'GX-08', 'owner': 'd', 'paths': ['scripts/d/**', 'census/**'], 'shared': ['census/**']}]
        self.assertEqual(forge_events.unit_of(Ownership(units), 'c', ['census/x.json']), 'gx-08')


class MergedOnTheRepositoryChannel(unittest.TestCase):
    def test_the_merge_lands_on_both_channels_with_its_unit(self):
        adapter = forge_events.MemoryAdapter()
        events = port(adapter)
        payload = dict(forge_events.subject(REPO, PR, HEAD, ['P-02'], 'gx-05'), merge_sha=MERGE, batch_id='b1')
        with events.batched():
            events.emit('pr.merged', payload, repository=True)
        [own] = adapter.read(forge_events.Channel(REPO, PR))
        [repo] = adapter.read(forge_events.Channel(REPO, None))
        self.assertEqual((own['payload']['unit'], repo['payload']['unit']), ('gx-05', 'gx-05'))
        self.assertEqual(own['event_id'], repo['event_id'])

    def test_replay_of_the_pr_channel_is_unchanged(self):
        plain, mirrored = forge_events.MemoryAdapter(), forge_events.MemoryAdapter()
        payload = dict(forge_events.subject(REPO, PR, HEAD), merge_sha=MERGE, batch_id='b1')
        port(plain).emit('pr.merged', payload)
        port(mirrored).emit('pr.merged', payload, repository=True)
        channel = forge_events.Channel(REPO, PR)
        self.assertEqual(forge_events.replay(plain.read(channel)), forge_events.replay(mirrored.read(channel)))

    def test_a_merge_without_a_unit_stays_legal_and_visible(self):
        adapter = forge_events.MemoryAdapter()
        port(adapter).emit('pr.merged', dict(forge_events.subject(REPO, OTHER, HEAD), merge_sha=MERGE, batch_id='b1'),
                           repository=True)
        [repo] = adapter.read(forge_events.Channel(REPO, None))
        self.assertIsNone(repo['payload']['unit'])


if __name__ == '__main__':
    unittest.main()
