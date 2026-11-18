"""The rule register and scripts/rule (RULE-AUDIT rule system). Fixture registers in temporary directories at a fixed
date, plus a smoke run of every subcommand on this checkout. Local files only: the configuration store is the checkout's
local log, never the forge. No network."""
import argparse
import contextlib
from datetime import date, timedelta
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
os.environ.setdefault('OU_CONFIG_STORE', 'file')
import config  # noqa: E402
import premises  # noqa: E402
import rule_registry as rules  # noqa: E402
import fixture_copy  # noqa: E402  (scripts/tests, GATE-SPEED F2)

config.pin_store('file')
TODAY = date.fromisoformat('2026-10-28')
CREATED = '2026-10-01'
REVIEWED = '2026-10-20'
PAST = '2026-10-27'
REVIEW = '2026-12-01'
STAMP = '2026-10-26T17:22-03:00'
DEFAULTS = rules.settings(ROOT)
GUARD = ('def push_errors(body):\n    return []\n\n\ndef merge_block(pr):\n    return None\n\n\n'
         'def helper():\n    return None\n')
DECISIONS = '| ID | Date | Decision |\n|---|---|---|\n| D-001 | 2026-10-01 | A recorded decision. |\n'
WEBKIT = 'The gate machine can launch WebKit.'


def usage_code():
    """The exit code argparse gives a usage error; scripts/rule exits through argparse."""
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            argparse.ArgumentParser().parse_args(['--no-such-flag'])
        except SystemExit as error:
            return error.code


def premise(ident, status, statement=None, at=STAMP):
    """A premise record as premises.load returns it (the answer carries the status date of a settled premise)."""
    answered = status not in premises.setting('open_statuses')
    return {
        'id': ident, 'slug': f'premise-{ident.lower()}', 'statement': statement or f'The {ident} premise holds.',
        'kind': 'process', 'scope': 'global', 'source': {'who': 'daniel', 'where': 'chat', 'quote': None,
                                                         'at': None if answered else at},
        'status': status, 'radius': 'low', 'blast': {'reasons': [], 'if_wrong': 'The rule changes.'},
        'validate': {'kind': 'question', 'how': 'Ask.'},
        'answer': {'by': 'Daniel', 'at': at, 'value': status, 'quote': 'Sim.', 'where': None, 'evidence': None,
                   'translation': None} if answered else None,
        'dependents': premises.sealed([], []), 'supersedes': [],
    }


PREMISES = {
    'P-01': premise('P-01', 'confirmed', 'Pushes carry a plan.'),
    'P-02': premise('P-02', 'refuted', WEBKIT),
    'P-03': premise('P-03', 'to-validate'),
    'P-04': premise('P-04', 'confirmed', at=None),
}


def complete(ident='R-push-plan', **changes):
    """A stopping record with every field."""
    record = {
        'id': ident, 'statement': 'A push carries its commit plan.', 'where': ['scripts/lib/guard.py:push_errors'],
        'owner': 'D-001', 'created': {'on': CREATED, 'by': 'A Torre'}, 'review_by': REVIEW,
        'ends_when': {'kind': 'manual', 'text': 'When the train owns the plan.'}, 'stops': True,
        'damage_if_passed': 'A push without a plan lands.',
        'impact_of_removal': {'positive': 'Pushes skip a check.', 'negative': 'Unplanned pushes land.',
                              'measured': 'Not measured: needs the gate records.'},
        'premises': ['P-01'],
        'question': {'text': 'Why must a push carry a plan?',
                     'answers': [{'on': CREATED, 'by': 'Daniel', 'text': 'So each commit is reviewable.'}]},
        'stop_record': {'count': 0, 'source': 'gate records', 'measured_on': CREATED, 'root_cause': None,
                        'cheapest_fix': None},
        'status': 'active',
    }
    record.update(changes)
    return record


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'scripts' / 'lib').mkdir(parents=True)
        (self.root / 'scripts' / 'lib' / 'guard.py').write_text(GUARD, encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def world(self, records, by_id=None, value_of=None):
        values = dict(DEFAULTS, catalog=records)
        return rules.World(self.root, TODAY, values, PREMISES if by_id is None else by_id, {'D-001'},
                           value_of=value_of or (lambda name: 'unset'))

    def gaps(self, record, **world):
        return rules.record_gaps(record, self.world([record], **world))


class Records(Fixture):
    def test_a_complete_stopping_record_has_no_gap_and_no_finding(self):
        world = self.world([complete()])
        self.assertEqual(rules.record_gaps(complete(), world), [])
        self.assertEqual((rules.due(world), rules.ending(world), rules.accidents(world), rules.unanswered(world),
                          rules.premise_findings(world)), ([], [], [], [], []))

    def test_each_missing_field_is_reported(self):
        for field in rules.REQUIRED + rules.STOPPING:
            record = complete()
            del record[field]
            self.assertTrue(any(gap.startswith(field) for gap in self.gaps(record)), field)
        for part in rules.IMPACT:
            record = complete()
            del record['impact_of_removal'][part]
            self.assertIn(f'impact_of_removal.{part} is missing', self.gaps(record))

    def test_a_record_that_does_not_stop_needs_no_damage_or_impact(self):
        record = complete(stops=False)
        for field in rules.STOPPING:
            del record[field]
        self.assertEqual(self.gaps(record), [])

    def test_a_review_date_already_passed_is_due_not_a_gap(self):
        record = complete(review_by=PAST)
        world = self.world([record])
        self.assertEqual(rules.record_gaps(record, world), [])
        self.assertEqual(rules.due(world), [(record, (TODAY - date.fromisoformat(PAST)).days)])

    def test_a_review_date_beyond_the_ceiling_is_a_gap_counted_from_the_last_review(self):
        limit = DEFAULTS['max_review_days']
        late = (date.fromisoformat(CREATED) + timedelta(days=limit + 1)).isoformat()
        self.assertTrue(any('rules.max_review_days' in gap for gap in self.gaps(complete(review_by=late))))
        self.assertEqual(self.gaps(complete(review_by=late, last_reviewed=REVIEWED)), [])
        for wrong in ('2026-02-30', 'soon', CREATED):
            self.assertTrue(any('review_by' in gap for gap in self.gaps(complete(review_by=wrong))), wrong)

    def test_owner_is_a_recorded_decision_or_a_dated_name(self):
        self.assertEqual(self.gaps(complete(owner='Daniel 2026-10-28')), [])
        for wrong in ('D-999', 'Daniel', 'Daniel 2026-13-01'):
            self.assertTrue(any(gap.startswith('owner') for gap in self.gaps(complete(owner=wrong))), wrong)

    def test_an_unknown_premise_is_a_gap_and_an_empty_list_a_finding(self):
        self.assertIn('premise P-99 is not in the premise register', self.gaps(complete(premises=['P-99'])))
        record = complete(premises=[])
        self.assertEqual(self.gaps(record), [])
        self.assertEqual(rules.premise_findings(self.world([record])),
                         [{'id': 'R-push-plan', 'stops': True, 'premise': None, 'finding': 'cites no premise'}])


class Ending(Fixture):
    def proposals(self, record, **world):
        return rules.ending(self.world([record], **world))

    def test_a_date_end_condition_reached_proposes_the_retirement_with_the_exact_change(self):
        [found] = self.proposals(complete(ends_when={'kind': 'date', 'on': PAST, 'text': 'Until the train.'}))
        self.assertEqual(found['change'], {'status': 'retired', 'retired': {
            'on': TODAY.isoformat(), 'by': rules.PENDING_DECISION, 'reason': f'ends_when date {PAST} reached'}})
        self.assertEqual(self.proposals(complete(ends_when={'kind': 'date', 'on': REVIEW, 'text': 'Later.'})), [])
        self.assertEqual(self.proposals(complete()), [])  # manual never ends by itself

    def test_path_conditions_and_registry_values_end_a_rule(self):
        absent = {'kind': 'path_absent', 'path': 'scripts/lib/gone.py', 'text': 'While gone.py exists.'}
        exists = {'kind': 'path_exists', 'path': 'scripts/lib/guard.py', 'text': 'Until guard.py lands.'}
        flipped = {'kind': 'registry_equals', 'key': 'fixture.mode', 'equals': 'on', 'text': 'Until on.'}  # D-328: not check_mode
        self.assertEqual([item['id'] for item in self.proposals(complete(ends_when=absent))], ['R-push-plan'])
        self.assertEqual([item['id'] for item in self.proposals(complete(ends_when=exists))], ['R-push-plan'])
        self.assertEqual(self.proposals(complete(ends_when=flipped)), [])
        self.assertEqual(len(self.proposals(complete(ends_when=flipped), value_of=lambda name: 'on')), 1)

    def test_code_gone_proposes_the_retirement_and_code_partly_gone_is_a_gap(self):
        gone = complete(where=['scripts/lib/guard.py:vanished_errors', 'scripts/lib/old.py:old_errors'])
        [found] = self.proposals(gone)
        self.assertTrue(found['reason'].startswith('code gone'))
        moved = complete(where=['scripts/lib/guard.py:push_errors', 'scripts/lib/guard.py:vanished_errors'])
        self.assertEqual(self.proposals(moved), [])
        self.assertIn('where ref scripts/lib/guard.py:vanished_errors no longer exists (moved? update where)',
                      self.gaps(moved))

    def test_a_retirement_needs_a_recorded_decision(self):
        retired = {'id': 'R-old', 'status': 'retired', 'retired': {'on': PAST, 'by': 'D-001', 'reason': 'Replaced.'}}
        self.assertEqual(self.gaps(retired), [])
        self.assertIn('retired.by None is not a D-NNN', self.gaps(dict(retired, retired={'on': PAST, 'reason': 'x'})))
        self.assertTrue(any('not a row' in gap for gap in self.gaps(dict(retired, retired=dict(retired['retired'],
                                                                                                by='D-999')))))


class Findings(Fixture):
    def test_stops_are_discovered_and_the_unregistered_ones_have_no_question(self):
        world = self.world([complete()])
        self.assertEqual(rules.discovered(self.root, DEFAULTS['stop_patterns']),
                         ['scripts/lib/guard.py:merge_block', 'scripts/lib/guard.py:push_errors'])
        self.assertEqual(rules.unregistered(world), ['scripts/lib/guard.py:merge_block'])
        report = rules.check(world)
        self.assertEqual(report['unregistered'], ['scripts/lib/guard.py:merge_block'])

    def test_daniel_fixture_a_rule_on_a_refuted_premise_is_stale_one_on_a_confirmed_premise_is_not(self):
        webkit = complete('R-gate-e2e-browser', premises=['P-02'], where=['scripts/lib/guard.py:merge_block'])
        world = self.world([webkit, complete()])
        rows = {row['premise']: row for row in rules.stale(world)}
        self.assertEqual((rows['P-02']['rules'], rows['P-02']['stopping'], rows['P-02']['label']),
                         (['R-gate-e2e-browser'], ['R-gate-e2e-browser'], 'refuted'))
        self.assertNotIn('P-01', rows)
        self.assertNotIn('R-push-plan', [ident for row in rows.values() for ident in row['rules']])
        self.assertEqual(rules.premise_findings(world), [{'id': 'R-gate-e2e-browser', 'stops': True, 'premise': 'P-02',
                                                          'finding': 'refuted'}])
        self.assertEqual((rows['P-03']['label'], rows['P-04']['label']), ('to-validate', 'confirmed, undated'))

    def test_a_stopping_rule_without_a_stop_record_was_never_measured(self):
        record = complete()
        del record['stop_record']
        self.assertEqual(rules.accidents(self.world([record])), [
            {'id': 'R-push-plan', 'finding': 'stops the flow and has never been measured (no stop_record)'}])
        quiet = complete(stops=False)
        del quiet['stop_record']
        self.assertEqual(rules.accidents(self.world([quiet])), [])

    def test_a_stop_record_with_a_null_count_was_never_measured(self):
        record = complete(stop_record={'count': None, 'source': 'not read yet', 'root_cause': None, 'cheapest_fix': None})
        self.assertEqual(self.gaps(record), [])
        self.assertEqual(rules.accidents(self.world([record])), [
            {'id': 'R-push-plan', 'finding': 'stops the flow and has never been measured (stop_record.count is null)'}])

    def test_a_rule_that_stopped_the_flow_needs_its_root_cause(self):
        stopped = {'count': 1, 'source': 'gate records', 'measured_on': PAST, 'root_cause': None, 'cheapest_fix': None}
        [row] = rules.accidents(self.world([complete(stop_record=stopped)]))
        self.assertEqual(row['finding'], f'stopped the flow 1 time(s) (gate records, {PAST}) and no root cause is named')
        named = dict(stopped, root_cause='A generated file was merged by hand.', cheapest_fix='Regenerate on merge.')
        self.assertEqual(rules.accidents(self.world([complete(stop_record=named)])), [])
        self.assertTrue(any('stop_record.count' in gap for gap in self.gaps(complete(stop_record=dict(stopped, count=-1)))))

    def test_a_question_without_an_answer_is_a_finding_and_a_missing_question_a_gap(self):
        silent = complete(question={'text': 'Why must a push carry a plan?', 'answers': []})
        world = self.world([silent])
        self.assertEqual(rules.record_gaps(silent, world), [])
        self.assertEqual([record['id'] for record in rules.unanswered(world)], ['R-push-plan'])
        self.assertEqual(rules.check(world)['unanswered'], ['R-push-plan'])
        self.assertIn('question.text is missing', self.gaps(complete(question={'answers': []})))

    def test_the_check_reports_a_gap_and_refuses_nothing(self):
        record = complete()
        del record['owner']
        report = rules.check(self.world([record]))
        self.assertEqual(report['counts']['stopping_with_gaps'], 1)
        self.assertNotIn('refusals', report)  # D-328: the refuse mode left


class Cli(Fixture):
    """scripts/rule on a fixture checkout: the registry, premise register and decision register as files."""

    def setUp(self):
        super().setUp()
        fixture_copy.registry(self.root)
        shutil.copytree(ROOT / 'contracts' / 'premises', self.root / 'contracts' / 'premises')
        (self.root / 'docs' / 'domain').mkdir(parents=True)
        (self.root / 'docs' / 'domain' / 'DECISIONS.md').write_text(DECISIONS, encoding='utf-8')
        folder = premises.register_dir(self.root)
        folder.mkdir(parents=True)
        shape = premises.schema(self.root)
        for record in PREMISES.values():
            (folder / (record['slug'] + premises.setting('record_suffix'))).write_text(premises.dump(record, shape))
        self.registry = self.root / 'config' / 'registry' / 'rules.json'
        webkit = complete('R-gate-e2e-browser', premises=['P-02'], where=['scripts/lib/guard.py:merge_block'],
                          question={'text': 'Why does the gate need WebKit?', 'answers': [
                              {'on': CREATED, 'by': 'Daniel', 'text': 'First answer.'},
                              {'on': REVIEWED, 'by': 'A Torre', 'text': 'Latest answer.'}]},
                          stop_record={'count': None, 'source': 'gate records', 'root_cause': None, 'cheapest_fix': None})
        self.write([complete(), webkit])

    def write(self, records):
        text = self.registry.read_text(encoding='utf-8')
        document = json.loads(text)
        document['properties']['rules.catalog']['default'] = records
        indent = len(rules.INDENT.search(text).group(1))
        self.registry.write_text(json.dumps(document, indent=indent, ensure_ascii=False) + '\n', encoding='utf-8')

    def run_cli(self, *argv):
        out = io.StringIO()
        code = rules.main([*argv, '--root', str(self.root), '--today', TODAY.isoformat()], out=out)
        return code, out.getvalue().splitlines()

    def usage(self, *argv):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as caught:
            self.run_cli(*argv)
        self.assertEqual(caught.exception.code, usage_code())
        self.assertNotIn(caught.exception.code, (0, 1))
        return err.getvalue()

    def test_show_prints_each_premise_statement_and_status_the_question_and_the_stop_record(self):
        code, lines = self.run_cli('show', 'R-gate-e2e-browser')
        self.assertEqual(code, 0)
        text = '\n'.join(lines)
        self.assertIn(f'  P-02 refuted (low, {STAMP}): {WEBKIT}', lines)
        self.assertIn('question: Why does the gate need WebKit?', lines)
        self.assertIn(f'  latest answer (2 in all): {REVIEWED} A Torre: Latest answer.', lines)
        self.assertIn('stop_record:', lines)
        self.assertIn('  count: null', lines)
        self.assertTrue(lines[-1].startswith('rule R-gate-e2e-browser: 1 premise(s)'), text)
        self.assertIn('no record R-none', self.usage('show', 'R-none'))

    def test_check_exits_zero_with_findings_and_has_no_refuse_mode(self):
        code, lines = self.run_cli('check')
        self.assertEqual(code, 0)
        self.assertIn('ACCIDENT R-gate-e2e-browser: stops the flow and has never been measured (stop_record.count is null)',
                      lines)
        self.assertIn('PREMISE R-gate-e2e-browser (stops): rests on P-02 refuted', lines)
        self.assertTrue(lines[-1].startswith('rules check: '))
        self.assertIn('unrecognized arguments: --mode', self.usage('check', '--mode', 'refuse'))  # D-328
        code, lines = self.run_cli('check', '--json')
        self.assertEqual(json.loads('\n'.join(lines))['counts']['unregistered_stops'], 0)

    def test_an_unregistered_stop_is_reported_as_a_stop_without_a_question(self):
        self.write([complete()])
        code, lines = self.run_cli('check')
        self.assertEqual(code, 0)
        self.assertIn('UNREGISTERED scripts/lib/guard.py:merge_block: a stop without a question (no active record lists it)',
                      lines)

    def test_due_lists_passed_reviews_unanswered_questions_and_proposed_retirements(self):
        silent = complete('R-silent', review_by=PAST, question={'text': 'Why?', 'answers': []})
        ended = complete('R-ended', ends_when={'kind': 'date', 'on': PAST, 'text': 'Until yesterday.'})
        self.write([complete(review_by=PAST), silent, ended])
        code, lines = self.run_cli('due')
        self.assertEqual(code, 0)
        self.assertIn('UNANSWERED R-silent: past its review date and its question has no answer: Why?', lines)
        self.assertFalse(any(line.startswith('UNANSWERED R-push-plan') for line in lines))
        self.assertTrue(any(line.startswith('DUE R-push-plan: review_by') for line in lines))
        self.assertTrue(any(line.startswith('END R-ended: ends_when date') and rules.PENDING_DECISION in line
                            for line in lines))
        self.assertTrue(lines[-1].startswith('rules due: '))

    def test_question_prints_the_evidence_and_records_an_answer_keeping_the_layout(self):
        before = self.registry.read_text(encoding='utf-8')
        code, lines = self.run_cli('question', 'R-push-plan')
        self.assertEqual(code, 0)
        self.assertIn('R-push-plan: Why must a push carry a plan?', lines)
        self.assertIn(f'  premise P-01 confirmed (low, {STAMP}): Pushes carry a plan.', lines)
        self.assertEqual(self.registry.read_text(encoding='utf-8'), before)
        code, lines = self.run_cli('question', 'R-push-plan', '--answer', 'Still needed.', '--by', 'Daniel')
        self.assertEqual(code, 0)
        after = self.registry.read_text(encoding='utf-8')
        document = json.loads(after)
        record = document['properties']['rules.catalog']['default'][0]
        self.assertEqual(record['question']['answers'][-1], {'on': TODAY.isoformat(), 'by': 'Daniel', 'text': 'Still needed.'})
        indent = len(rules.INDENT.search(before).group(1))
        self.assertEqual(after, json.dumps(document, indent=indent, ensure_ascii=False) + '\n')
        record['question']['answers'].pop()
        self.assertEqual(json.dumps(document, indent=indent, ensure_ascii=False) + '\n', before)
        self.assertIn('--answer needs a text', self.usage('question', 'R-push-plan', '--answer', ' ', '--by', 'Daniel'))

    def test_question_of_a_group_prints_the_census_questions_read_only(self):
        self.assertIn('groups.json is absent', self.usage('question', 'G-gate'))
        audits = self.root / 'docs' / 'audits' / 'rules'
        audits.mkdir(parents=True)
        rows = [{'id': 'C-001', 'kind': 'refusal', 'where': 'scripts/lib/guard.py:push_errors', 'what': 'A push plan.',
                 'owner': 'D-001', 'fired': None, 'stops_flow': True, 'question': 'Why must a push carry a plan?'},
                {'id': 'C-002', 'kind': 'refusal', 'where': 'scripts/lib/guard.py:merge_block', 'what': 'A merge block.',
                 'owner': None, 'fired': None, 'stops_flow': True, 'question': None}]
        (audits / 'census.json').write_text(json.dumps({'rows': rows}), encoding='utf-8')
        (audits / 'groups.json').write_text(json.dumps({'groups': [{'id': 'G-gate', 'title': 'Gate stops',
                                                                    'rows': ['C-001', 'C-002']}]}), encoding='utf-8')
        census = (audits / 'census.json').read_text(encoding='utf-8')
        code, lines = self.run_cli('question', 'G-gate')
        self.assertEqual(code, 0)
        self.assertIn('  question: Why must a push carry a plan?', lines)
        self.assertIn('  question: none (a finding)', lines)
        self.assertEqual(lines[-1], f'question G-gate: {len(rows)} row(s), 1 with a question')
        self.assertEqual((audits / 'census.json').read_text(encoding='utf-8'), census)
        self.assertIn('census rows are answered by their group audits',
                      self.usage('question', 'G-gate', '--answer', 'No.', '--by', 'Daniel'))
        self.assertIn('neither a record', self.usage('question', 'G-none'))

    def test_base_names_a_record_deleted_without_a_retirement(self):
        git = ['git', '-C', str(self.root), '-c', 'user.name=fixture', '-c', 'user.email=fixture', '-c', 'commit.gpgsign=false']
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run([*git, 'add', '-A'], check=True)
        subprocess.run([*git, 'commit', '-q', '-m', 'base'], check=True)
        self.write([complete()])
        code, lines = self.run_cli('check', '--base', 'HEAD')
        self.assertEqual(code, 0)
        self.assertIn('DELETED R-gate-e2e-browser: left rules.catalog without a retirement', lines)
        self.assertIn('is not a commit', self.usage('check', '--base', 'no-such-ref'))


class ThisCheckout(unittest.TestCase):
    """The real registry: it validates, keeps a stable layout for --answer, and every subcommand runs and exits 0."""

    def test_the_rules_registry_file_validates(self):
        self.assertEqual([error for error in config.check(ROOT) if 'rules.json' in error], [])

    def test_the_registry_layout_is_what_an_answer_write_keeps(self):
        text = (ROOT / 'config' / 'registry' / 'rules.json').read_text(encoding='utf-8')
        indent = len(rules.INDENT.search(text).group(1))
        self.assertEqual(json.dumps(json.loads(text), indent=indent, ensure_ascii=False) + '\n', text)

    def test_every_subcommand_runs_on_this_checkout(self):
        ident = DEFAULTS['catalog'][0]['id']
        for argv, last in ((['list'], 'rules: '), (['show', ident], f'rule {ident}: '), (['due'], 'rules due: '),
                           (['retired'], 'rules retired: '), (['stale'], 'stale premises: '),
                           (['question', ident], f'question {ident}: '), (['check'], 'rules check: ')):
            out = io.StringIO()
            code = rules.main([*argv, '--root', str(ROOT), '--today', TODAY.isoformat()], out=out)
            self.assertEqual(code, 0, argv)
            self.assertTrue(out.getvalue().splitlines()[-1].startswith(last), (argv, out.getvalue().splitlines()[-1]))


if __name__ == '__main__':
    unittest.main()
