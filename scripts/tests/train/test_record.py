"""REC-1: the merge leaves a record a program can follow (TX24: one file per feature; fixtures in test_train.py)."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, setUpModule  # noqa: E402,F401


class MergeRecord(Fixture):
    def test_the_merge_of_a_unit_lands_on_the_repository_and_its_own_channel(self):
        [made] = self.make(({'c.txt': 'one\n'}, 'gx-05'))
        self.train.run_batch(self.train.queue())
        [own] = self.events(made.number, 'pr.merged')
        [repository] = [e for e in self.events(None, 'pr.merged') if e['payload']['pr'] == made.number]
        self.assertEqual((own['payload']['unit'], repository['payload']['unit']), ('gx-05', 'gx-05'))
        self.assertEqual(own['event_id'], repository['event_id'])

    def test_a_merge_without_a_unit_is_on_the_repository_with_unit_null(self):
        [made] = self.make({'c.txt': 'one\n'})
        self.train.run_batch(self.train.queue())
        [repository] = [e for e in self.events(None, 'pr.merged') if e['payload']['pr'] == made.number]
        self.assertIsNone(repository['payload']['unit'])


if __name__ == '__main__':
    unittest.main()
