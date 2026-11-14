"""What a session did, counted from its transcript (D-208): the tool calls, the scripts and the git verbs, a line that is not JSON
skipped. The fixture is a transcript of three lines and one broken one.

Pure functions over the fixture; no network.
"""
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import usage  # noqa: E402

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'usage.json').read_text())


class GitVerbs(unittest.TestCase):
    def test_a_git_verb_counts_where_a_command_starts_and_not_inside_a_quoted_argument(self):
        commands = ['git fetch origin', 'cd x && git checkout y', "grep -n 'git merge' file.md", 'echo "git log"',
                    'true; git merge z']
        lines = [json.dumps({'message': {'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': c}}]}})
                 for c in commands]
        git = usage.count(lines)['git']
        self.assertEqual((git['fetch'], git['checkout'], git['merge'], git['log']), (1, 1, 1, 0))


class Count(unittest.TestCase):
    def setUp(self):
        self.found = usage.count((ROOT / 'scripts' / 'tests' / 'fixtures' / 'usage.jsonl').read_text().splitlines())

    def test_the_tool_calls_are_counted_by_name(self):
        self.assertEqual(dict(self.found['tools']), FIXTURE['tools'])
        self.assertEqual(sum(self.found['tools'].values()), FIXTURE['total'])

    def test_the_scripts_and_the_git_verbs_come_from_the_shell_only(self):
        self.assertEqual(dict(self.found['scripts']), FIXTURE['scripts'])
        self.assertEqual(dict(self.found['git']), FIXTURE['git'])

    def test_a_name_inside_another_command_is_not_a_run(self):
        # an rg or grep that names a script or a git verb is a search, not a run (the decision-record count was inflated this way)
        self.assertEqual(usage.runs('rg -n "decision-record" scripts && cd /x', usage.SCRIPT), [])
        self.assertEqual(usage.runs('rg -n "git fetch" scripts | head -3', usage.GIT), [])
        self.assertEqual(usage.runs('OU_PYTHON=python3 scripts/decision-table --check | tail -1', usage.SCRIPT), ['decision-table'])
        self.assertEqual(usage.runs('cd /x && bash scripts/repeats --write; git log -1', usage.SCRIPT), ['repeats'])
        self.assertEqual(usage.runs('cd /x && git fetch origin && git checkout -B b', usage.GIT), ['fetch', 'checkout'])

    def test_the_render_names_every_section(self):
        text = usage.render(self.found)
        self.assertIn('tool calls: 2', text)
        self.assertIn('scripts run from the shell', text)
        self.assertIn('git verbs in the shell', text)



class Tokens(unittest.TestCase):
    def test_usage_is_counted_once_per_message_and_the_span_is_read(self):
        rows = [{'timestamp': '2026-11-03T05:00:00Z', 'message': {'id': 'm1', 'role': 'assistant',
                 'usage': {'input_tokens': 2, 'output_tokens': 10, 'cache_creation_input_tokens': 5, 'cache_read_input_tokens': 100}}},
                {'timestamp': '2026-11-03T05:00:01Z', 'message': {'id': 'm1', 'role': 'assistant',
                 'usage': {'input_tokens': 2, 'output_tokens': 10, 'cache_creation_input_tokens': 5, 'cache_read_input_tokens': 100}}},
                {'timestamp': '2026-11-03T06:00:00Z', 'message': {'id': 'm2', 'role': 'assistant', 'usage': {'output_tokens': 1}}},
                'not json']
        lines = [row if isinstance(row, str) else json.dumps(row) for row in rows]
        found = usage.tokens(lines)
        self.assertEqual((found['output_tokens'], found['input_tokens'], found['messages']), (11, 2, 2))
        self.assertEqual((found['first'], found['last']), ('2026-11-03T05:00:00Z', '2026-11-03T06:00:00Z'))
        self.assertIn('9 non-cached tokens and 6 output tokens per PR', usage.render_tokens(found, 2))


WEIGHTS = {'input': 1, 'cache_write': 1.25, 'cache_read': 0.1, 'output': 5}
SECRET = 'do-not-copy-this-text'


def entry(stamp, role, content, usage_row=None, message_id=None):
    message = {'role': role, 'content': content}
    if usage_row:
        message.update(id=message_id, usage=usage_row)
    return json.dumps({'timestamp': stamp, 'sessionId': 's1', 'message': message})


def lane(folder, name, brief, command, report, start='2026-11-03T20:00:00.000Z', end='2026-11-03T20:10:00.000Z'):
    """A lane transcript: the brief, one assistant turn that runs a command, the final report."""
    used = {'input_tokens': 10, 'output_tokens': 100, 'cache_creation_input_tokens': 1000, 'cache_read_input_tokens': 10000}
    rows = [entry(start, 'user', brief),
            entry('2026-11-03T20:05:00.000Z', 'assistant', [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': command}}],
                  used, 'm1'),
            entry(end, 'assistant', [{'type': 'text', 'text': report}], {'output_tokens': 20}, 'm2')]
    (folder / name).write_text('\n'.join(rows) + '\n')


class Ledger(unittest.TestCase):
    """F59: each transcript of a subagents directory and its coordinator becomes one ledger row, no text copied."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.folder = self.tmp / 'sess' / 'subagents'
        self.folder.mkdir(parents=True)
        lane(self.folder, 'agent-a.jsonl', f'Worktree dir: f59. Unit: queue row F59 in fila.md. Another lane (F60). {SECRET}',
             'cd /root/wt/f59 && scripts/deliver --pr 160 --branch units/f59', 'PR #999 was an older one; done')
        lane(self.folder, 'agent-b.jsonl', 'Survey the queue rows F23 and F27', 'ls', 'see PR #100')
        lane(self.folder, 'agent-c.jsonl', 'Worktree dir: f61.\n\nUnit F61. Its row.', 'git status', 'Delivered PR #161, merged')
        (self.tmp / 'sess.jsonl').write_text(entry('2026-11-03T19:00:00.000Z', 'user', 'go') + '\n'
                                            + entry('2026-11-03T21:00:00.000Z', 'assistant', 'ok', {'output_tokens': 1000}, 'c1') + '\n')
        self.prs = {160: ('a' * 40, '2026-11-03T17:20:00-03:00'), 161: ('b' * 40, '2026-11-03T20:30:00+00:00'),
                    100: ('c' * 40, '2026-11-02T10:00:00+00:00')}
        self.rows = usage.lanes(self.folder, WEIGHTS, self.prs)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def test_a_lane_row_names_the_unit_the_dir_and_the_pr_it_delivered(self):
        row = self.rows[0]
        self.assertEqual((row['role'], row['unit'], row['dir'], row['pr'], row['merged']), ('lane', 'F59', 'f59', 160, 'a' * 40))
        self.assertEqual((row['wall_s'], row['tool_calls'], row['messages']), (600, 1, 2))

    def test_the_tokens_are_counted_by_kind_and_weighted(self):
        tokens = self.rows[0]['tokens']
        self.assertEqual((tokens['input'], tokens['cache_read'], tokens['cache_write'], tokens['output']), (10, 10000, 1000, 120))
        self.assertEqual(tokens['weighted'], 10 + 1000 + 1250 + 600)

    def test_without_a_deliver_run_the_pr_comes_from_the_report(self):
        self.assertEqual((self.rows[2]['unit'], self.rows[2]['pr'], self.rows[2]['merged']), ('F61', 161, 'b' * 40))

    def test_a_brief_without_a_worktree_line_takes_the_dir_from_the_delivered_branch(self):
        pr = next(iter(self.prs))
        lane(self.folder, 'agent-d.jsonl', 'Unit: deliver prints its refusals. Worktree dir `refusal`.',
             f'export PATH=x; scripts/deliver --pr {pr} --branch units/refusal', f'PR #{pr} merged')
        rows = usage.lanes(self.folder, WEIGHTS, self.prs)
        row = next(row for row in rows if row['transcript'] == 'agent-d.jsonl')
        self.assertEqual((row['role'], row['dir'], row['pr']), ('lane', 'refusal', pr))

    def test_the_brief_worktree_line_wins_over_the_delivered_branch(self):
        self.assertEqual(usage.identify([entry('2026-11-03T10:00:00Z', 'user', 'Worktree dir: f59.'),
                                         turn('2026-11-03T10:01:00Z', 'scripts/deliver --pr 1 --branch units/other', 'm')])['dir'],
                         'f59')

    def test_a_brief_without_a_unit_or_a_worktree_is_a_subagent(self):
        self.assertEqual((self.rows[1]['role'], self.rows[1]['unit'], self.rows[1]['pr']), ('subagent', None, None))

    def test_the_coordinator_divides_its_tokens_among_the_prs_merged_in_its_span(self):
        row = self.rows[-1]
        self.assertEqual((row['role'], row['prs'], row['tokens']['weighted'], row['weighted_per_pr']),
                         ('coordinator', [160, 161], 5000, 2500))

    def test_the_ledger_keeps_no_transcript_text_and_a_rerun_replaces_its_rows(self):
        ledger = self.tmp / 'cache' / 'lanes.jsonl'
        ledger.parent.mkdir()
        ledger.write_text(json.dumps({'session': 'other', 'transcript': 'x.jsonl', 'role': 'lane'}) + '\nbroken\n')
        usage.write_ledger(self.rows, ledger)
        usage.write_ledger(self.rows, ledger)
        text = ledger.read_text()
        self.assertNotIn(SECRET, text)
        self.assertEqual(len(text.splitlines()), 1 + len(self.rows))
        self.assertNotIn(SECRET, usage.render_lanes(self.rows))
        self.assertIn('2 PRs merged in its span, 2500 weighted tokens per PR', usage.render_lanes(self.rows))


def turn(stamp, command, message_id, used=None):
    """An assistant entry that runs one shell command, with its usage."""
    return entry(stamp, 'assistant', [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': command}}],
                 used or {'output_tokens': 10}, message_id)


class PerDelivery(unittest.TestCase):
    """F59 per PR: a lane that delivers several units gives one ledger row per delivery, the tokens and the time from the
    end of the previous delivery to this one."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.folder = self.tmp / 'sess' / 'subagents'
        self.folder.mkdir(parents=True)
        self.prs = {170: ('a' * 40, '2026-11-03T20:20:00+00:00'), 171: ('b' * 40, '2026-11-03T20:50:00+00:00')}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp)

    def write(self, rows):
        (self.folder / 'agent-x.jsonl').write_text('\n'.join(rows) + '\n')
        return usage.lanes(self.folder, WEIGHTS, self.prs)

    def test_each_delivery_is_a_row_with_its_own_tokens_time_and_unit(self):
        rows = self.write([
            entry('2026-11-03T20:00:00.000Z', 'user', f'Two units, worktrees `ledgerpr` and `f72`. {SECRET}'),
            turn('2026-11-03T20:05:00.000Z', 'cd /root/wt/ledgerpr && git commit -m x', 'm1'),
            turn('2026-11-03T20:10:00.000Z', 'cd /root/wt/ledgerpr && scripts/deliver --pr 170 --branch units/ledgerpr', 'm2'),
            turn('2026-11-03T20:12:00.000Z', 'cd /root/wt/ledgerpr && git commit -m fix', 'm3'),
            turn('2026-11-03T20:15:00.000Z', 'cd /root/wt/ledgerpr && scripts/deliver --pr 170 --branch units/ledgerpr', 'm4'),
            turn('2026-11-03T20:30:00.000Z', 'cd /root/wt/f72 && git push', 'm5', {'output_tokens': 1000}),
            turn('2026-11-03T20:40:00.000Z', 'cd /root/wt/f72 && scripts/deliver --pr 171 --branch units/f72', 'm6'),
            entry('2026-11-03T20:45:00.000Z', 'assistant', [{'type': 'text', 'text': 'PR #170 and PR #171 merged'}],
                  {'output_tokens': 7}, 'm7')])
        lanes = [row for row in rows if row['role'] == 'lane']
        self.assertEqual([(row['pr'], row['dir'], row['unit'], row['merged'], row['part']) for row in lanes],
                         [(170, 'ledgerpr', None, 'a' * 40, '1/2'), (171, 'f72', 'F72', 'b' * 40, '2/2')])
        self.assertEqual([row['wall_s'] for row in lanes], [900, 1800])  # 20:00-20:15, then 20:15-20:45 (report included)
        self.assertEqual([row['tokens']['output'] for row in lanes], [40, 1017])
        self.assertEqual([row['tool_calls'] for row in lanes], [4, 2])
        self.assertEqual(sum(row['tokens']['weighted'] for row in lanes), usage.weigh(usage.tokens(
            (self.folder / 'agent-x.jsonl').read_text().splitlines()), WEIGHTS))

    def test_a_unit_authored_after_the_last_delivery_is_a_row_in_flight(self):
        rows = self.write([
            entry('2026-11-03T20:00:00.000Z', 'user', 'Worktree dir: f70.'),
            turn('2026-11-03T20:10:00.000Z', 'cd /root/wt/f70 && scripts/deliver --pr 170 --branch units/f70', 'm1'),
            turn('2026-11-03T20:20:00.000Z', 'cd /root/wt/f71 && git commit -m y', 'm2'),
            turn('2026-11-03T20:25:00.000Z', 'origin pr ready 172', 'm3')])
        self.assertEqual([(row['pr'], row['dir'], row['merged'], row['wall_s']) for row in rows],
                         [(170, 'f70', 'a' * 40, 600), (172, 'f71', None, 900)])

    def test_reading_the_result_after_the_last_delivery_stays_in_it(self):
        rows = self.write([
            entry('2026-11-03T20:00:00.000Z', 'user', 'Worktree dir: f70.'),
            turn('2026-11-03T20:10:00.000Z', 'cd /root/wt/f70 && scripts/deliver --pr 170 --branch units/f70', 'm1'),
            turn('2026-11-03T20:20:00.000Z', 'cd /root/wt/f70 && git log -1', 'm2')])
        self.assertEqual([(row['pr'], row['wall_s'], row.get('part')) for row in rows], [(170, 1200, None)])

    def test_a_rewrite_replaces_the_one_row_an_older_ledger_kept_for_the_transcript(self):
        ledger = self.tmp / 'lanes.jsonl'
        ledger.write_text(json.dumps({'session': 's1', 'transcript': 'agent-x.jsonl', 'role': 'lane', 'pr': 171}) + '\n')
        rows = self.write([
            entry('2026-11-03T20:00:00.000Z', 'user', 'Worktree dir: f70.'),
            turn('2026-11-03T20:10:00.000Z', 'scripts/deliver --pr 170 --branch units/f70', 'm1'),
            turn('2026-11-03T20:20:00.000Z', 'scripts/deliver --pr 171 --branch units/f71', 'm2')])
        usage.write_ledger(rows, ledger)
        self.assertEqual([json.loads(line)['pr'] for line in ledger.read_text().splitlines()], [170, 171])
        self.assertNotIn(SECRET, ledger.read_text())


class NewestDirectory(unittest.TestCase):
    """`usage --lanes` with no DIR reads the newest subagents directory (flow.transcripts_glob), as deliver runs it."""

    def test_the_newest_matching_directory_is_read_and_none_when_nothing_matches(self):
        import os
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        old, new = tmp / 'a' / 'subagents', tmp / 'b' / 'subagents'
        for folder, stamp in ((old, 1000), (new, 2000)):
            folder.mkdir(parents=True)
            os.utime(folder, (stamp, stamp))
        (tmp / 'c').mkdir()
        (tmp / 'c' / 'subagents').write_text('a file, not a directory')
        self.assertEqual(usage.newest_transcripts(str(tmp / '*' / 'subagents')), new)
        self.assertIsNone(usage.newest_transcripts(str(tmp / 'none' / '*')))

    def test_a_session_that_ran_no_lane_still_writes_its_coordinators_row(self):
        # 04/11: a session with no subagents directory refreshed nothing after each merge, and deliver warned every time
        from unittest import mock
        import config
        import hashlib
        import os
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        old = tmp / 'proj' / 'old' / 'subagents'  # an older session that ran lanes: no longer the newest session
        old.mkdir(parents=True)
        (tmp / 'proj' / 'old.jsonl').write_text(entry('2026-11-02T10:00:00.000Z', 'user', 'old') + '\n')
        (tmp / 'proj' / 'sess.jsonl').write_text(entry('2026-11-03T19:00:00.000Z', 'user', 'go') + '\n'
                                                + entry('2026-11-03T21:00:00.000Z', 'assistant', 'ok',
                                                        {'output_tokens': 1}, 'c1') + '\n')
        os.utime(tmp / 'proj' / 'old.jsonl', (0, 0))  # the epoch: older than any write
        pattern = str(tmp / '*' / '*' / 'subagents')
        real = config.get
        with mock.patch.object(config, 'get', side_effect=lambda name, *a: pattern if name == 'flow.transcripts_glob'
                               else real(name, *a)), \
                mock.patch.object(usage, 'merged', return_value={1: (hashlib.sha1(b'the merge').hexdigest(),
                                                                  '2026-11-03T20:30:00+00:00')}), \
                mock.patch.object(usage, 'write_ledger') as written, mock.patch('builtins.print'):
            self.assertEqual(usage.main(['--lanes', '--write']), 0)
        rows = written.call_args.args[0]
        self.assertEqual([(row['role'], row['prs'], row['transcript']) for row in rows], [('coordinator', [1], 'sess.jsonl')])

    def test_with_no_directory_found_nothing_is_written(self):
        from unittest import mock
        import config
        with mock.patch.object(config, 'get', return_value='/nonexistent/*/subagents'), \
                mock.patch.object(usage, 'write_ledger') as written:
            self.assertEqual(usage.main(['--lanes', '--write']), 1)
        written.assert_not_called()


if __name__ == '__main__':
    unittest.main()
