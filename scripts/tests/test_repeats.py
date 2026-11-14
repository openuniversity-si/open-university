"""The repeated actions (D-208): the table is read, the systematised rows leave the open list, and the open ones come most repeated first.

Pure functions over a fixture table; no network.
"""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import repeats  # noqa: E402
STATUS = repeats.STATUS
WHERE = repeats.COLUMNS.index('where')

FIXTURE = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'repeats.json').read_text())


class Register(unittest.TestCase):
    def test_every_row_of_the_table_is_read(self):
        self.assertEqual(len(repeats.rows(FIXTURE['table'])), FIXTURE['total'])

    def test_the_open_rows_come_most_repeated_first(self):
        left = repeats.open_rows(repeats.rows(FIXTURE['table']))
        self.assertEqual([row[0] for row in left], FIXTURE['open_order'])
        self.assertEqual(len(left), FIXTURE['open'])

    def test_a_systematised_row_whose_script_is_absent_is_refused(self):
        table = ('| Action | Count | Status | Where |\n|---|---|---|---|\n'
                 '| Built | 5 | systematised, not adopted | `scripts/repeats` |\n'
                 '| Claimed | 6 | systematised | `scripts/no-such-script` |\n'
                 '| Open | 7 | open | `scripts/no-such-script` |\n')
        self.assertEqual(repeats.unbuilt(repeats.rows(table), ROOT),
                         [('Claimed', 'scripts/no-such-script')])

    def test_the_register_names_no_absent_script_for_a_systematised_row(self):
        text = (ROOT / repeats.REGISTER).read_text()
        self.assertEqual(repeats.unbuilt(repeats.rows(text), ROOT), [])


W = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'repeats-write.json').read_text())
TABLE = W['table']


def transcript(*blocks):
    """A transcript of one assistant message per block: tool_use blocks as (name, input) pairs."""
    return [json.dumps({'message': {'content': [{'type': 'tool_use', 'name': name, 'input': args}]}})
            for name, args in blocks]


class Write(unittest.TestCase):
    """A measured count is the transcripts' measure, up or down (D-254)."""

    def test_a_measured_count_is_set_to_the_measure_below_or_above_the_typed_one(self):
        found = repeats.usage.count(transcript(*[('SendMessage', {})] * W['messages_below']))
        text, changes = repeats.write(TABLE, found)
        self.assertIn(f"| Messages to other sessions to nudge them | {W['messages_below']} |", text)
        self.assertIn((W['messages_action'], W['messages_old'], W['messages_below']), changes)
        found = repeats.usage.count(transcript(*[('SendMessage', {})] * W['messages_above']))
        text, changes = repeats.write(TABLE, found)
        self.assertIn(f"| Messages to other sessions to nudge them | {W['messages_above']} |", text)
        self.assertIn((W['messages_action'], W['messages_old'], W['messages_above']), changes)

    def test_git_verbs_and_pull_requests_are_measured_from_their_own_counters(self):
        found = repeats.usage.count(transcript(('Bash', {'command': 'git fetch origin'}),
                                               ('Bash', {'command': 'git checkout x'}),
                                               ('Bash', {'command': 'git merge y'}),
                                               ('mcp__github__create_pull_request', {}),
                                               ('Bash', {'command': 'scripts/service status'})))
        text, changes = repeats.write(TABLE, found)
        # the messages row has no message in this transcript, so its measure is 0 and it is set down with the others
        self.assertCountEqual(changes, [(W['sync_action'], W['sync_old'], W['sync_measured']),
                                        (W['pr_action'], W['pr_old'], W['pr_measured']),
                                        (W['messages_action'], W['messages_old'], 0)])
        self.assertIn(f"| {W['sync_action']} | {W['sync_measured']} |", text)
        self.assertIn(f"| {W['pr_action']} | {W['pr_measured']} |", text)

    def test_an_unmeasured_row_keeps_its_line(self):
        found = repeats.usage.count(transcript(*[('SendMessage', {})] * W['few_messages']))
        text, _ = repeats.write(TABLE, found)
        self.assertIn(W['unmeasured_row'], text)

    def test_write_needs_a_transcript_and_writes_the_register(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'docs' / 'process').mkdir(parents=True)
            register = Path(root) / repeats.REGISTER
            register.write_text(TABLE)
            log = Path(root) / 'session.jsonl'
            log.write_text('\n'.join(transcript(*[('SendMessage', {})] * W['messages_above'])))
            self.assertEqual(repeats.main(['--write', '--transcript', str(log)], root=root), 0)
            self.assertIn(f"| Messages to other sessions to nudge them | {W['messages_above']} |", register.read_text())

    def test_every_measure_is_appended_to_the_log_with_the_transcripts_it_names(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'docs' / 'process').mkdir(parents=True)
            (Path(root) / repeats.REGISTER).write_text(TABLE)
            for name in ('named-session', 'other-session'):  # one transcript is measured once (the adoption rounds, D-254)
                log = Path(root) / f'{name}.jsonl'
                log.write_text('\n'.join(transcript(*[('SendMessage', {})] * W['messages_above'])))
                repeats.main(['--write', '--transcript', str(log)], root=root)
            lines = [line for line in (Path(root) / repeats.LOG).read_text().splitlines() if 'row' in json.loads(line)]
            self.assertEqual(len(lines), W['measures'] * W['measured_rows'])
            first = json.loads(lines[0])
            self.assertEqual(first['row'], W['messages_action'])
            self.assertEqual(first['count'], W['messages_above'])
            self.assertEqual(first['sources'], [{'transcript': 'named-session', 'modified': first['sources'][0]['modified']}])


def with_rounds(*measured):
    """The fixture table with one round per (transcript, count, tool calls, tool on the base) given, in order."""
    text = ''
    for name, count, calls, on_base in measured:
        text, _ = repeats.add_round(text, name, count, calls, on_base)
    return text


A = json.loads((ROOT / 'scripts' / 'tests' / 'fixtures' / 'repeats-adoption.json').read_text())


def shape(found):
    """The rounds as (number, transcript, count, calls, on the base), to compare with a fixture."""
    return [(row.number, row.transcript, row.count, row.calls, row.on_base) for row in found]


class Adoption(unittest.TestCase):
    def test_a_round_keeps_its_raw_count_its_calls_and_the_state_of_the_tool(self):
        text = with_rounds(('s1', A['first'], A['long_calls'], False), ('s2', A['second'], A['long_calls'], True))
        self.assertEqual(shape(repeats.rounds(text)), [(A['numbers'][0], 's1', A['first'], A['long_calls'], False),
                                                       (A['numbers'][1], 's2', A['second'], A['long_calls'], True)])

    def test_the_same_transcript_is_not_measured_twice(self):
        text = with_rounds(('s1', A['first'], A['long_calls'], False))
        with self.assertRaises(ValueError):
            repeats.add_round(text, 's1', A['third'], A['long_calls'], True)

    def test_pending_until_two_rounds_have_the_tool_on_the_base(self):
        found = repeats.rounds(with_rounds(('s1', A['first'], A['long_calls'], False), ('s2', A['second'], A['long_calls'], True)))
        state, reason = repeats.adoption(found)
        self.assertEqual(state, repeats.PENDING)
        self.assertIn(f"{A['write_numbers'][0]} round(s)", reason)

    def test_adopted_when_the_rate_with_the_tool_is_below_the_one_before(self):
        found = repeats.rounds(with_rounds(('s1', A['third'], A['long_calls'], True), ('s2', A['second'], A['long_calls'], True)))
        self.assertEqual(repeats.adoption(found)[0], repeats.ADOPTED)

    def test_pending_when_the_sync_by_hand_does_not_fall(self):
        found = repeats.rounds(with_rounds(('s1', A['second'], A['long_calls'], True), ('s2', A['third'], A['long_calls'], True)))
        self.assertEqual(repeats.adoption(found)[0], repeats.PENDING)

    def test_a_shorter_session_with_fewer_syncs_is_not_a_fall(self):
        # 4 in 100 calls, then 3 in 50: the rate went up, though the count went down
        found = repeats.rounds(with_rounds(('s1', A['third'], A['long_calls'], True), ('s2', A['second'], A['short_calls'], True)))
        self.assertEqual(repeats.adoption(found)[0], repeats.PENDING)

    def test_a_round_before_the_tool_is_not_compared(self):
        found = repeats.rounds(with_rounds(('s1', A['before_tool'], A['long_calls'], False),
                                           ('s2', A['tail_before'], A['long_calls'], True),
                                           ('s3', A['tail_after'], A['long_calls'], True)))
        self.assertEqual(repeats.adoption(found)[0], repeats.ADOPTED)

    def test_write_records_one_round_and_refuses_the_same_transcript_again(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'docs' / 'process').mkdir(parents=True)
            register = Path(root) / repeats.REGISTER
            register.write_text(TABLE)
            measures = Path(root) / repeats.LOG
            log = Path(root) / 'session.jsonl'
            log.write_text('\n'.join(transcript(('Bash', {'command': 'git fetch origin'}),
                                             ('Bash', {'command': 'git merge y'}))))
            self.assertEqual(repeats.main(['--write', '--transcript', str(log)], root=root), 0)
            self.assertEqual(shape(repeats.rounds(measures.read_text())),
                             [(A['write_numbers'][0], 'session', A['write_count'], A['write_calls'], False)])
            self.assertEqual(repeats.main(['--write', '--transcript', str(log)], root=root), 1)
            self.assertEqual(len(repeats.rounds(measures.read_text())), A['write_numbers'][0])
class HandWrittenDecisions(unittest.TestCase):
    ROW = '| Writing a decision row by hand (Edit or Write to DECISIONS.md) | 0 | adoption pending | `scripts/decision-record` |'

    def test_an_edit_of_the_table_counts_and_a_record_write_does_not(self):
        action = 'Writing a decision row by hand (Edit or Write to DECISIONS.md)'
        table = repeats.MEASURED[action][1][0]
        hand = [('Edit', {'file_path': str(ROOT / table)}), ('Write', {'file_path': table})]
        found = repeats.usage.count(transcript(
            *hand,
            ('Write', {'file_path': 'docs/domain/decisions/D-300.md'}),
            ('Edit', {'file_path': 'docs/process/repeats.md'}),
        ))
        self.assertEqual(repeats.measured(found, repeats.MEASURED[action]), len(hand))
        text, changes = repeats.write(self.ROW + '\n', found)
        self.assertEqual(changes, [(action, 0, len(hand))])
        self.assertIn(f'| {len(hand)} | adoption pending |', text)


class Claims(unittest.TestCase):
    def test_a_status_that_says_check_passes_matches_the_drift_check(self):
        # the register is typed by hand; a status that claims the decision table's check passes must be true of the check (lane 20, I3)
        rows = repeats.rows((ROOT / repeats.REGISTER).read_text())
        claimed = [row for row in rows if 'check passes' in row[repeats.STATUS]]
        if not claimed:
            return
        result = subprocess.run([str(ROOT / 'scripts' / 'decision-table'), '--check'], capture_output=True, cwd=ROOT)
        self.assertFalse(result.returncode, f"{len(claimed)} row(s) claim 'check passes' but scripts/decision-table --check fails")
class ReadMeasures(unittest.TestCase):
    def test_a_transcript_alone_prints_its_measured_calls_and_writes_nothing(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'docs' / 'process').mkdir(parents=True)
            register = Path(root) / repeats.REGISTER
            table = ('| Action | Count | Status | Where |\n|---|---|---|---|\n'
                     '| Running the structure check by hand after each edit | 217 | systematised, not adopted | x |\n')
            register.write_text(table)
            log = Path(root) / 'session.jsonl'
            log.write_text('\n'.join(transcript(*[('Bash', {'command': 'scripts/structure-check'})] * W['structure_checks'])))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(repeats.main(['--transcript', str(log)], root=root), 0)
            self.assertIn(f"- {W['structure_checks']}x Running the structure check by hand after each edit", out.getvalue())
            self.assertEqual(register.read_text(), table)


class StructureCheckRow(unittest.TestCase):
    """The register's structure-check row says what runs the check, and it stays open while the pre-push hook runs only part of it."""

    def test_the_row_names_deliver_as_the_whole_check_and_stays_open(self):
        found = {row[0]: row for row in repeats.rows((ROOT / repeats.REGISTER).read_text())}
        row = found['Running the structure check by hand after each edit']
        self.assertNotEqual(row[STATUS], 'systematised')
        self.assertIn('scripts/deliver', row[WHERE])
        self.assertIn('gate-dev', (ROOT / 'scripts' / 'lib' / 'deliver.py').read_text())
        self.assertIn('structure_fast', row[WHERE])


class SeveralSessions(unittest.TestCase):
    def test_the_counts_of_several_transcripts_are_summed(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'docs' / 'process').mkdir(parents=True)
            register = Path(root) / repeats.REGISTER
            register.write_text(TABLE)
            logs = []
            for index, count in enumerate(W['messages_split']):
                log = Path(root) / f'session{index}.jsonl'
                log.write_text('\n'.join(transcript(*[('SendMessage', {})] * count)))
                logs.append(str(log))
            self.assertEqual(repeats.main(['--write', '--transcript', logs[0], '--transcript', logs[1]], root=root), 0)
            self.assertIn(f"| Messages to other sessions to nudge them | {W['messages_above']} |", register.read_text())


STATUS_ROW = 'Running the status commands one by one (flow metrics, lane status, service, coordinator)'


class StatusCommands(unittest.TestCase):
    """The status row counts runs of the five status commands, not mentions of their paths (D-208)."""

    def test_a_mention_of_a_status_script_is_not_a_run(self):
        found = repeats.usage.count(transcript(('Bash', {'command': 'cat scripts/flow-check; sed -n 1,9p scripts/lane-status'})))
        self.assertEqual(sum(found['scripts'].values()), 0)
        self.assertEqual(sum(found['commands'].values()), 0)

    def test_a_status_script_named_inside_quoted_text_is_not_a_run(self):
        found = repeats.usage.count(transcript(('Bash', {'command': 'python3 -c "print(\'x\'); print(\'scripts/lane-status\')"'}),
                                               ('Bash', {'command': 'echo "cd /x && scripts/service health"'})))
        self.assertEqual(sum(found['commands'].values()), 0)

    def test_a_run_behind_a_wrapper_is_a_run(self):
        found = repeats.usage.count(transcript(('Bash', {'command': 'timeout 300 scripts/flow-check 2>&1 | head -60'}),
                                               ('Bash', {'command': 'env OU_PYTHON=python3 nice -n 5 scripts/lane-status'})))
        self.assertEqual(found['scripts']['flow-check'], 1)
        self.assertEqual(found['commands']['lane-status'], 1)

    def test_the_runs_are_counted_with_their_first_word(self):
        found = repeats.usage.count(transcript(('Bash', {'command': 'cd /x && scripts/service health'}),
                                               ('Bash', {'command': 'scripts/flow-metrics --cycles'}),
                                               ('Bash', {'command': 'scripts/gate-shadow latest 2>&1 | tail -2'})))
        self.assertEqual(found['commands']['service health'], 1)
        self.assertEqual(found['commands']['flow-metrics'], 1)
        self.assertEqual(found['commands']['gate-shadow latest'], 1)

    def test_the_row_is_set_to_the_runs_measured_up_or_down(self):
        before, measured = W['status_before'], W['status_measured']
        table = f"| Action | Count | Status | Where |\n|---|---|---|---|\n| {STATUS_ROW} | {before} | systematised, not adopted | `scripts/flow-check` |\n"
        many = repeats.usage.count(transcript(*[('Bash', {'command': 'scripts/lane-status'})] * measured))
        text, changes = repeats.write(table, many)
        self.assertEqual(changes, [(STATUS_ROW, before, measured)])
        self.assertIn(f'| {STATUS_ROW} | {measured} |', text)
        one = repeats.usage.count(transcript(*[('Bash', {'command': 'scripts/lane-status'})] * W['status_one_run']))
        text, changes = repeats.write(table, one)
        self.assertEqual(changes, [(STATUS_ROW, before, W['status_one_run'])])
        self.assertIn(f"| {STATUS_ROW} | {W['status_one_run']} |", text)


class RegisterVocabulary(unittest.TestCase):
    """The register's statuses are one of four words; a row that is not systematised is open (D-208). `adoption pending` is
    the status `scripts/repeats --write` gives a row it measures by transcript (HandWrittenDecisions)."""

    WORDS = {'open', 'systematised', 'systematised, not adopted', 'adoption pending'}

    def test_every_status_is_one_of_the_four_words(self):
        for action, _count, status, _where in repeats.rows((ROOT / repeats.REGISTER).read_text()):
            self.assertIn(status, self.WORDS, (action, status))

    def test_the_status_row_is_open_while_adoption_is_pending(self):
        left = [action for action, *_ in repeats.open_rows(repeats.rows((ROOT / repeats.REGISTER).read_text()))]
        self.assertIn(STATUS_ROW, left)


if __name__ == '__main__':
    unittest.main()
