"""VAZÃO F36: the train on the box, one batch per leadership from the box queue (train_box, D-297)."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_train import Fixture, setUpModule  # noqa: E402,F401
import box_queue  # noqa: E402
import train_box  # noqa: E402
import train_queue  # noqa: E402

LOW_RED = {'runs': 10, 'p': 0.0}  # the meter: no red run in the window, so k_max is train.batch_size


class Box(Fixture):
    def setUp(self):
        super().setUp()
        self.queue_dir = Path(tempfile.mkdtemp())
        self.checked = []
        self.problems = {}

    def check(self, pr, body):
        self.checked.append(pr)
        return self.problems.get(pr, [])

    def wait(self, *made):
        """Each PR queued on the box by a live delivery (this process), oldest first."""
        for index, item in enumerate(made):
            box_queue.enqueue(item.number, f'pr-{item.number}', item.head, self.queue_dir, os.getpid(), index)

    def lead(self, red=LOW_RED):
        return train_box.lead(self.train, self.train.port('box'), self.queue_dir, lambda count: red, self.check)

    def result(self, made):
        return box_queue.result(made.number, made.head, self.queue_dir)

    def test_one_tier2_run_merges_the_whole_batch_and_writes_each_result(self):
        made = self.make({'c.txt': 'one\n'}, {'d.txt': 'two\n'}, {'e.txt': 'three\n'}, ready=False)
        self.wait(*made)
        self.assertEqual(self.lead(), 'batched')
        self.assertEqual(len(self.gate.runs), 1, 'one gate run for the batch')
        self.assertEqual(self.forge.merges, [item.number for item in made])
        [green] = self.events(None, 'train.batch.green')
        for item in made:
            found = self.result(item)
            self.assertEqual((found['outcome'], found['batch_id']), ('merged', green['payload']['batch_id']))
        self.assertEqual(self.checked, [item.number for item in made], 'the PR checks ran for every member')

    def test_a_red_batch_merges_the_proven_prefix_ejects_the_culprit_and_the_rest_waits(self):
        made = self.make({'c.txt': 'one\n'}, {'BREAK': 'x\n'}, {'e.txt': 'three\n'}, ready=False)
        self.wait(*made)
        self.lead()
        first, culprit, after = made
        self.assertEqual(self.forge.merges, [first.number])
        self.assertEqual((self.result(first)['outcome'], self.result(culprit)['outcome']), ('merged', 'ejected'))
        self.assertIsNone(self.result(after), 'after the culprit: no result, its delivery leads the next batch')

    def test_the_base_comes_into_each_member_before_the_batch(self):
        made = self.make({'c.txt': 'one\n'}, {'d.txt': 'two\n'}, ready=False)
        self.wait(*made)
        self.run_git(self.seed, 'checkout', '--quiet', '-B', 'moved', self.base)
        self.write({'base-moved.txt': 'later\n'})
        self.set_origin_ref(f'refs/heads/{self.base_branch}', self.commit('the base moved'))
        self.lead()
        for item in made:
            found = self.result(item)
            self.assertEqual(found['outcome'], 'merged')
            self.assertNotEqual(found['sha'], item.head, 'the judged head is the base merge, pushed to the branch')
            self.assertEqual(self.forge.change(None, item.number)['head'], found['sha'])
        steps = [e['payload']['step'] for e in self.events(None, 'engine.step.measured')]
        self.assertIn(self.train.step_prefix + 'admit', steps)

    def test_a_member_the_pr_checks_refuse_leaves_with_its_reason(self):
        made = self.make({'c.txt': 'one\n'}, {'d.txt': 'two\n'}, {'e.txt': 'three\n'}, ready=False)
        self.problems[made[1].number] = ['FAIL plan: the PR body needs a D-022 commit plan']
        self.wait(*made)
        self.lead()
        self.assertEqual(self.result(made[1])['outcome'], 'refused')
        self.assertIn('commit plan', self.result(made[1])['detail'])
        self.assertEqual(self.forge.merges, [made[0].number, made[2].number])

    def test_a_member_that_does_not_take_the_base_is_conflicted(self):
        made = self.make({'a.txt': 'mine\n'}, {'d.txt': 'two\n'}, {'e.txt': 'three\n'}, ready=False)
        self.wait(*made)
        self.run_git(self.seed, 'checkout', '--quiet', '-B', 'moved', self.base)
        self.write({'a.txt': 'theirs\n'})
        self.set_origin_ref(f'refs/heads/{self.base_branch}', self.commit('the base changed a.txt'))
        self.lead()
        self.assertEqual(self.result(made[0])['outcome'], 'conflicted')
        self.assertIn('a.txt', self.result(made[0])['detail'])
        self.assertEqual(self.forge.merges, [made[1].number, made[2].number])

    def test_no_batch_with_one_waiting_or_a_red_share_past_the_table(self):
        made = self.make({'c.txt': 'one\n'}, {'d.txt': 'two\n'}, ready=False)
        self.wait(made[0])
        self.assertEqual(self.lead(), 'no batch')
        self.wait(*made)
        self.assertEqual(self.lead({'runs': 10, 'p': 0.5}), 'no batch')
        self.assertEqual(self.lead({'prs': [], 'error': 'no credential'}), 'no batch', 'an unread meter is no batch')
        self.assertEqual((self.gate.runs, self.forge.merges), ([], []))

    def test_the_batch_takes_the_oldest_k_max(self):
        made = self.make(*({f'f{n}.txt': 'x\n'} for n in range(5)), ready=False)
        self.wait(*made)
        self.lead({'runs': 10, 'p': 0.2})  # p 0.20: k_max 2 (train.batch_size_by_red)
        self.assertEqual(self.forge.merges, [made[0].number, made[1].number])

    def test_dead_deliveries_and_moved_heads_are_not_waiting(self):
        made = self.make({'c.txt': 'one\n'}, {'d.txt': 'two\n'}, {'e.txt': 'three\n'}, ready=False)
        self.wait(*made)
        box_queue.enqueue(made[0].number, 'pr-x', made[0].head, self.queue_dir, pid=2 ** 22 + 7, at=0)
        box_queue.enqueue(made[1].number, 'pr-y', 'f' * 40, self.queue_dir, os.getpid(), 1)
        self.assertEqual(self.lead(), 'no batch', 'one live delivery at its pushed head is left')

    def test_the_summary_line_is_what_the_lock_log_keeps(self):
        made = self.make({'c.txt': 'one\n'}, {'BREAK': 'x\n'}, ready=False)
        self.wait(*made)
        printed = []
        original = train_box.print if hasattr(train_box, 'print') else None
        train_box.print = printed.append
        self.addCleanup(lambda: delattr(train_box, 'print') if original is None else setattr(train_box, 'print', original))
        self.lead()
        [line] = [text for text in printed if text.startswith('box: batch ')]
        summary = json.loads(line[len('box: batch '):])
        self.assertEqual((summary['merged'], summary['ejected'], summary['runs'], summary['size']),
                         ([made[0].number], [made[1].number], 1 + 1 + 1, 2))


class Queue(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_entries_results_and_leave(self):
        box_queue.enqueue(7, 'b', 'h1', self.dir, os.getpid(), 2)
        box_queue.enqueue(3, 'a', 'h0', self.dir, os.getpid(), 1)
        self.assertEqual([row['pr'] for row in box_queue.entries(self.dir)], [3, 7], 'oldest first')
        box_queue.write_result(3, 'h0', 'merged', self.dir, batch_id='b-x')
        self.assertEqual(box_queue.result(3, 'h0', self.dir)['batch_id'], 'b-x')
        self.assertIsNone(box_queue.result(3, 'other', self.dir), 'a result is read for its own head only')
        self.assertEqual([row['pr'] for row in box_queue.entries(self.dir)], [3, 7], 'results are not entries')
        box_queue.leave(3, self.dir, pid=os.getpid() + 1)
        self.assertEqual(len(box_queue.entries(self.dir)), 2, 'another delivery never removes this entry')
        box_queue.leave(3, self.dir)
        self.assertEqual([row['pr'] for row in box_queue.entries(self.dir)], [7])
        with self.assertRaises(ValueError):
            box_queue.write_result(7, 'h1', 'lost', self.dir)

    def test_the_premises_line_of_a_body(self):
        self.assertEqual(train_queue.premises_of('x\nPremises: P-02, P-56\nFit-Review: y'), ('P-02', 'P-56'))
        self.assertEqual(train_queue.premises_of('Premises: none'), ())
        self.assertEqual(train_queue.premises_of(None), ())

    def test_a_held_lock_is_not_taken_again(self):
        lock = self.dir / 'gate.lock'
        os.environ[box_queue.HELD_ENV] = str(lock)
        self.addCleanup(os.environ.pop, box_queue.HELD_ENV, None)
        with box_queue.hold(str(lock)):
            self.assertFalse(lock.exists(), 'the parent holds it: nothing is opened')
        os.environ.pop(box_queue.HELD_ENV)
        with box_queue.hold(str(lock)):
            self.assertTrue(lock.exists())


if __name__ == '__main__':
    unittest.main()
