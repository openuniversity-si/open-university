"""A lane's collect (VAZÃO F69): collect with a fake run and a temporary closed-rows record over in-memory ledger rows.
No network, no git, no real cache."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import lane as lane_command  # noqa: E402
import lane_collect  # noqa: E402
from unittest import mock  # noqa: E402


def lane(unit, pr, merged, end, session='s2', weighted=1000):
    return {'role': 'lane', 'unit': unit, 'dir': unit.lower(), 'pr': pr, 'merged': merged, 'end': end, 'session': session,
            'wall_s': 600, 'tool_calls': 40, 'tokens': {'weighted': weighted, 'input': 1, 'cache_read': 2, 'cache_write': 3,
                                                        'output': 4}}


LEDGER = [lane('F50', 140, None, '2026-11-02T10:00Z', session='s1'),  # an older coordinator's lane: not a front now
          lane('F58', 157, None, '2026-11-03T21:00Z'), lane('F59', 159, 'b' * 40, '2026-11-03T21:10Z'),
          lane('F60', None, None, '2026-11-03T21:20Z'), {'role': 'coordinator', 'session': 's2', 'end': '2026-11-03T21:30Z'}]


class FakeRun:
    """Answers `git log -1 --format=%s <sha>` with a unit's merge subject and records every other call."""
    def __init__(self, subject):
        self.subject, self.calls = subject, []

    def __call__(self, argv, **_):
        self.calls.append(argv)
        out = self.subject if argv[:2] == ['git', 'log'] else ''
        return type('Done', (), {'returncode': 0, 'stdout': out, 'stderr': ''})()


class Collect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.record = Path(self.tmp.name) / 'queue-closed.jsonl'
        self.said = []
        self.merges = {159: ('b' * 40, '2026-11-03T21:15:00+00:00'), 170: ('c' * 40, '2026-11-03T21:40:00+00:00')}

    def tearDown(self):
        self.tmp.cleanup()

    def collect(self, pr, run):
        return lane_collect.collect(pr, self.merges, LEDGER, {159: 118.4}, root=self.tmp.name, run=run, out=self.said.append,
                                    record=self.record)

    def test_the_report_names_its_pr(self):
        self.assertEqual(lane_collect.reported_pr('Report. PR #159 merged b3ec584d; earlier PR #120'), 159)
        self.assertIsNone(lane_collect.reported_pr('nothing delivered'))

    def test_a_merged_pr_not_yet_recorded_gets_the_deliver_diary_note_and_its_closed_row(self):
        run = FakeRun('F69: lane collect (#170)')
        self.assertEqual(self.collect(170, run), 0)
        notes = [argv for argv in run.calls if argv[:2] == ['scripts/plan', 'note']]
        self.assertEqual(len(notes), 1)
        self.assertIn('F69', notes[0])
        self.assertEqual(json.loads(self.record.read_text()), {'unit': 'F69', 'pr': 170, 'merge': 'c' * 40})
        self.assertTrue(any('no ledger row for PR #170' in line for line in self.said))

    def test_a_pr_deliver_already_closed_is_not_noted_twice_and_its_ledger_line_is_printed(self):
        self.record.write_text(json.dumps({'unit': 'F59', 'pr': 159, 'merge': 'b' * 40}) + '\n')
        run = FakeRun('F59: ledger (#159)')
        self.assertEqual(self.collect(159, run), 0)
        self.assertEqual(run.calls, [])
        self.assertTrue(any('already noted' in line for line in self.said))
        self.assertTrue(any('F59 lane f59, PR #159: 1000 weighted tokens' in line and '118 s waiting' in line
                            for line in self.said))

    def test_an_unmerged_pr_says_open_or_ejected(self):
        for state, words in (('OPEN', 'has not ended'), ('CLOSED', 'ejected')):
            self.said.clear()
            run = lambda argv, **_: type('Done', (), {'returncode': 0, 'stdout': json.dumps({'state': state}), 'stderr': ''})()  # noqa: E731
            self.assertEqual(self.collect(157, run), 1)
            self.assertTrue(any(words in line for line in self.said), self.said)

    def test_a_pr_not_merged_closes_nothing(self):
        run = FakeRun('')
        self.assertEqual(self.collect(157, run), 1)
        self.assertFalse(any(c[:2] == ['git', 'log'] for c in run.calls))
        self.assertFalse(self.record.exists())


QUEUE = """# Fila

| # | Unidade | Evidência | Valor | Escopo | PRs | Tam. |
|---|---|---|---|---|---|---|
| F90 | **[eficiência]** closed by deliver | e | v | `a.py` | 1 | S |
| F91 | **[eficiência]** merged without a record | e | v | `a.py` | 1 | S |
| F92 | **[eficiência]** in flight | e | v | `a.py` | 1 | S |
| F93 | **[eficiência]** waits | e | v | `a.py`. Depois de F92 | 1 | S |
| F94 | **[eficiência]** free | e | v | `b.py`. Depois de F90 e F91 | 1 | S |
| F95 | **[eficiência]** also free | e | v | `c.py` | 1 | S |
"""


class GitLog:
    """Answers `git log --grep` with the commit that delivers F91; other calls (refs, PR list) per `listing`."""
    def __init__(self, listing=''):
        self.listing, self.calls = listing, []

    def __call__(self, argv, **_):
        self.calls.append(argv)
        if 'log' in argv:
            out = 'abc1234 lane: F91: merged (#191)\n' if any('F91' in a for a in argv) else ''
        else:
            out = self.listing
        return type('Done', (), {'returncode': 0, 'stdout': out, 'stderr': ''})()


class NextFree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'docs/programs/vazao').mkdir(parents=True)
        (self.root / 'docs/process').mkdir(parents=True)
        (self.root / lane_command.QUEUE).write_text(QUEUE)
        (self.root / lane_command.CONTRACT).write_text('# Lane\n\n## The delivery contract\n\n1. rules\n')
        (self.root / lane_command.DIGEST).write_text('<!-- generated -->\n0. `cd <worktree>`\n')
        self.record = self.root / 'queue-closed.jsonl'
        self.record.write_text(json.dumps({'unit': 'F90', 'pr': 1, 'merge': 'a'}) + '\n')
        self.said = []

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_first_row_not_closed_not_in_flight_and_not_waiting_is_next(self):
        self.assertEqual(lane_collect.next_free(self.root, record=self.record, flight={'F92'}, run=GitLog()), ('F94', None))

    def test_a_row_waits_while_a_unit_it_comes_after_is_open(self):
        unit, _ = lane_collect.next_free(self.root, record=self.record, flight={'F92', 'F94'}, run=GitLog())
        self.assertEqual(unit, 'F95')  # F93 waits on F92, open and in flight

    def test_no_free_row_says_why(self):
        unit, why = lane_collect.next_free(self.root, record=self.record, flight={'F92', 'F94', 'F95'}, run=GitLog())
        self.assertIsNone(unit)
        self.assertIn('F93 after F92', why)

    def test_in_flight_reads_unit_branches_and_open_pr_titles(self):
        listing = ('refs/heads/units/f92\nrefs/heads/units/census\nabc\trefs/heads/units/f94-2\n'
                   '#200  open  F95: also free  units/other\n')
        with mock.patch('config.get', side_effect=lambda key: {'push-guard.remote': 'origin',
                                                                'origin-client.cli': 'origin'}[key]):
            run = GitLog(listing)
            self.assertEqual(lane_collect.in_flight(self.root, run), {'F92', 'F95'})
            self.assertIn(['origin', 'pr', 'list', '-s', 'draft'], run.calls)

    def test_print_next_prints_the_brief_lane_brief_gives(self):
        run = GitLog()
        self.assertEqual(lane_collect.print_next(self.root, record=self.record, flight={'F92'}, session='S', run=run,
                                                 out=self.said.append), 'F94')
        self.assertIn('next free row F94', self.said[0])
        self.assertEqual(self.said[1], lane_command.brief('F94', root=self.root, session='S', run=run).rstrip('\n'))
        self.assertIn('# Lane brief: F94, free', self.said[1])

    def test_print_next_without_a_queue_says_so(self):
        (self.root / lane_command.QUEUE).unlink()
        self.assertIsNone(lane_collect.print_next(self.root, record=self.record, flight=set(), run=GitLog(),
                                                  out=self.said.append))
        self.assertTrue(self.said[0].startswith('collect: no next brief:'))


class Main(unittest.TestCase):
    def run_main(self, *extra):
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as report:
            report.write('PR #159 merged')
        with mock.patch.object(lane_collect, 'collect', return_value=0), \
                mock.patch.object(lane_collect.usage, 'merged', return_value={}), \
                mock.patch.object(lane_collect.fronts, 'refresh', return_value=[]), \
                mock.patch.object(lane_collect.fronts, 'lock_waits', return_value={}), \
                mock.patch.object(lane_collect.fronts, 'jsonl', return_value=[]), \
                mock.patch.object(lane_collect, 'print_next') as nxt:
            self.assertEqual(lane_collect.main([report.name, *extra]), 0)
        Path(report.name).unlink()
        return nxt

    def test_collect_prints_the_next_brief_by_default(self):
        self.run_main('--session', 'S').assert_called_once_with(session='S')

    def test_no_next_skips_it(self):
        self.run_main('--no-next').assert_not_called()


class Hookup(unittest.TestCase):
    def test_scripts_lane_collect_hands_its_arguments_to_lane_collect(self):
        with mock.patch.object(lane_collect, 'main', return_value=7) as collect:
            self.assertEqual(lane_collect.command(['collect', 'report.txt', '--pr', '5']), 7)
        collect.assert_called_once_with(['report.txt', '--pr', '5'])

    def test_every_other_subcommand_is_the_lane_brief(self):
        with mock.patch.object(lane_command, 'main', return_value='brief') as brief, \
                mock.patch.object(lane_collect, 'main') as collect:
            self.assertEqual(lane_collect.command(['brief', 'F68']), 'brief')
        brief.assert_called_once_with(['brief', 'F68'])
        collect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
