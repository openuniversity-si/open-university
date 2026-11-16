#!/usr/bin/env python3
"""QUEUE-REARM: scripts/lib/queue_wait.py on fixtures shaped like the timelines of #53, #55 and #64. No network."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
import queue_wait  # noqa: E402
import source_remote  # noqa: E402


def run(conclusion, end, name='tower/gate'):
    return {'name': name, 'conclusion': conclusion, 'completed_at': end}


def ev(kind, when):
    return {'event': kind, 'created_at': when}


class WaitTests(unittest.TestCase):
    def test_untouched_wait_counts_from_the_green(self):
        # #53: auto-merge on before the gate ended, queued 68 s after the green with nobody touching it.
        timeline = [ev('auto_merge_enabled', '2026-11-15T21:28:45Z'), ev('committed', None),
                    ev('added_to_merge_queue', '2026-11-15T21:32:06Z'), ev('merged', '2026-11-15T21:32:57Z')]
        wait = queue_wait.wait_of(timeline, [run('success', '2026-11-15T21:30:58Z')])
        self.assertEqual((wait['wait_s'], wait['rearmed']), (68, False))
        self.assertEqual(wait['armed'], '2026-11-15T21:30:58Z')

    def test_off_and_on_after_the_green_is_a_rearm(self):
        # #55: green 22:38:39, auto-merge off and on at 22:40:11-13, queued at once.
        timeline = [ev('auto_merge_enabled', '2026-11-15T22:32:39Z'), ev('auto_merge_disabled', '2026-11-15T22:40:11Z'),
                    ev('auto_merge_enabled', '2026-11-15T22:40:13Z'), ev('added_to_merge_queue', '2026-11-15T22:40:13Z')]
        wait = queue_wait.wait_of(timeline, [run('success', '2026-11-15T22:38:39Z')])
        self.assertEqual((wait['wait_s'], wait['rearmed']), (94, True))
        self.assertIn('rearmed', queue_wait.line(55, '39202fb1aaaa', wait))

    def test_enabled_after_the_green_counts_from_the_enabling(self):
        timeline = [ev('auto_merge_enabled', '2026-11-16T10:05:00Z'), ev('added_to_merge_queue', '2026-11-16T10:05:03Z')]
        wait = queue_wait.wait_of(timeline, [run('success', '2026-11-16T10:00:00Z')])
        self.assertEqual((wait['armed'], wait['wait_s'], wait['rearmed']), ('2026-11-16T10:05:00Z', 3, False))

    def test_the_first_green_counts_and_other_checks_do_not(self):
        runs = [run('failure', '2026-11-16T10:00:00Z'), run('success', '2026-11-16T10:02:00Z'),
                run('success', '2026-11-16T10:09:00Z'), run('success', '2026-11-16T10:01:00Z', name='other')]
        timeline = [ev('auto_merge_enabled', '2026-11-16T09:59:00Z'), ev('added_to_merge_queue', '2026-11-16T10:02:30Z')]
        wait = queue_wait.wait_of(timeline, runs)
        self.assertEqual((wait['green'], wait['wait_s']), ('2026-11-16T10:02:00Z', 30))

    def test_an_entry_before_the_heads_green_is_not_this_wait(self):
        # #64: an earlier head was queued and dropped; the merged head's green came later and was never queued.
        timeline = [ev('added_to_merge_queue', '2026-11-16T00:01:00Z'), ev('auto_merge_enabled', '2026-11-16T00:00:30Z')]
        wait = queue_wait.wait_of(timeline, [run('success', '2026-11-16T00:16:17Z')])
        self.assertIsNone(wait['queued'])
        self.assertIn('never queued', queue_wait.line(64, '6b250d8a0000', wait))

    def test_no_green_says_so(self):
        wait = queue_wait.wait_of([ev('added_to_merge_queue', '2026-11-16T00:01:00Z')], [run('failure', '2026-11-16T00:00:00Z')])
        self.assertIsNone(wait['green'])
        self.assertIn('no green tower/gate', queue_wait.line(1, 'abcdef0123', wait))

    def test_the_line_names_the_wait(self):
        wait = queue_wait.wait_of([ev('added_to_merge_queue', '2026-11-16T00:00:41Z')], [run('success', '2026-11-16T00:00:00Z')])
        self.assertEqual(queue_wait.line(66, 'bf9f7b68ffff', wait),
                         '#66 bf9f7b68 green 2026-11-16T00:00:00Z armed 2026-11-16T00:00:00Z '
                         'queued 2026-11-16T00:00:41Z wait 41 s')


class Done:
    def __init__(self, code, out='', err=''):
        self.returncode, self.stdout, self.stderr = code, out, err


class ApiTests(unittest.TestCase):
    def test_a_page_and_every_page_go_through_gh(self):
        calls = []

        def run(args, **_):
            calls.append(args)
            return Done(0, '[[{"event": "merged"}], [{"event": "closed"}]]' if '--paginate' in args else '{"number": 7}')
        self.assertEqual(source_remote.api('repos/o/r/pulls/7', run=run), {'number': 7})
        pages = source_remote.api('repos/o/r/issues/7/timeline', paginate=True, run=run)
        self.assertEqual(len(pages), 2)
        self.assertEqual(calls, [['gh', 'api', 'repos/o/r/pulls/7'],
                                 ['gh', 'api', '--paginate', '--slurp', 'repos/o/r/issues/7/timeline']])

    def test_a_refusal_names_the_path(self):
        with self.assertRaisesRegex(RuntimeError, 'repos/o/r/pulls/7: HTTP 404'):
            source_remote.api('repos/o/r/pulls/7', run=lambda args, **_: Done(1, err='HTTP 404'))


if __name__ == '__main__':
    unittest.main()
