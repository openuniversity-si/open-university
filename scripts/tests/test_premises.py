"""The premise register and scripts/premises (D-066). Fixture registers in a temporary directory; no network."""
import io
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
import forge_events  # noqa: E402
import json_schema  # noqa: E402
import premises  # noqa: E402

SCHEMA = 'contracts/premises/premise.v1.json'
AT = '2026-10-26T20:00:00Z'


def record(ident='P-01', slug='one-thing', status='inferred', radius='low', reasons=(), answer=None, **extra):
    data = {
        'id': ident, 'slug': slug, 'statement': f'The {slug} premise holds.', 'kind': 'process', 'scope': 'global',
        'source': {'who': 'orchestrator', 'where': 'plan v3', 'quote': None, 'at': None},
        'status': status, 'radius': radius,
        'blast': {'reasons': list(reasons), 'if_wrong': 'The plan changes.'},
        'validate': {'kind': 'question', 'how': 'Ask.'},
        'answer': answer, 'dependents': premises.sealed([], []), 'supersedes': [],
    }
    data.update(extra)
    return data


def answer(value, by='Daniel', quote='Sim.', where=None, evidence=None):
    return {'by': by, 'at': '2026-10-26T17:22-03:00', 'value': value, 'quote': quote, 'where': where,
            'evidence': evidence, 'translation': None}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / 'contracts' / 'premises', self.root / 'contracts' / 'premises')
        (self.root / 'contracts' / 'events').symlink_to(ROOT / 'contracts' / 'events')  # read-only here
        self.folder = premises.register_dir(self.root)
        self.folder.mkdir(parents=True)
        self.shape = premises.schema(self.root)

    def git_init(self):
        subprocess.run(['git', 'init', '-q', '--template=', str(self.root)], check=True)

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, data, name=None):
        path = self.folder / ((name or data['slug']) + premises.setting('record_suffix'))
        path.write_text(premises.dump(data, self.shape))
        return path

    def errors(self):
        return premises.load(self.root)[1]

    def run_cli(self, *argv, fetch=None, port=None):
        out = io.StringIO()
        flags = [] if port else ['--no-emit']
        code = premises.main(['--root', str(self.root), '--at', AT, *flags, *argv], out=out, fetch=fetch or (lambda number: ''), port=port)
        lines = out.getvalue().splitlines()
        events = [json.loads(line[len('event: '):]) for line in lines if line.startswith('event: ')]
        return code, [line for line in lines if not line.startswith('event: ')], events


class Format(Fixture):
    def test_dump_and_parse_round_trip(self):
        data = record(status='confirmed', answer=answer('confirmed', quote='eu não quero ficar sendo o gargalo'))
        text = premises.dump(data, self.shape)
        self.assertTrue(text.startswith('#'))
        self.assertIn('  who: "orchestrator"', text)
        self.assertEqual(premises.parse(text), data)

    def test_parse_refuses_lines_outside_the_subset(self):
        for text in ('id: P-01\n', '- item\n', 'source:\n    who: "x"\n', 'id: "P-01"\nid: "P-02"\n'):
            with self.assertRaises(premises.FormatError, msg=text):
                premises.parse(text)

    def test_schema_reader_refuses_unknown_keywords(self):
        self.assertTrue(json_schema.errors({}, {'dependentRequired': {}})[0].endswith('(scripts/lib/json_schema.py)'))
        self.assertEqual(json_schema.errors({'a': 1}, {'type': 'object', 'required': ['b'], 'additionalProperties': False}),
                         ['$: "b" is required', '$: property "a" is not allowed'])


class Register(Fixture):
    def test_a_valid_register_loads(self):
        self.put(record())
        self.put(record('P-02', 'two-things', 'confirmed', 'high', ['decision:D-065'], answer('confirmed')))
        by_id, errors = premises.load(self.root)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(by_id), ['P-01', 'P-02'])

    def test_refuses_duplicates_names_and_schema_errors(self):
        self.put(record())
        self.put(record(slug='other'), name='wrong-name')
        self.put(record('P-03', 'third', kind='weather'))
        errors = self.errors()
        self.assertTrue(any('id P-01 is also' in line for line in errors), errors)
        self.assertTrue(any('not named after slug other' in line for line in errors), errors)
        self.assertTrue(any('"weather" is not one of' in line for line in errors), errors)

    def test_radius_may_rise_but_never_fall_below_the_computed_one(self):
        self.put(record(radius='high'))
        self.put(record('P-02', 'gate-rule', radius='low', reasons=['gate:structure-check']))
        self.put(record('P-03', 'three-units', radius='low', reasons=['unit:a', 'unit:b', 'unit:c']))
        errors = self.errors()
        self.assertEqual(len(errors), 2, errors)
        self.assertIn('radius low is below high', errors[0])
        self.assertIn('radius low is below medium', errors[1])

    def test_a_paraphrase_is_never_confirmed(self):
        self.put(record(status='confirmed', answer=answer('confirmed', quote=None)))
        self.put(record('P-02', 'measured', status='validated', answer=answer('validated', by='measurement:X1')))
        self.put(record('P-03', 'answered-open', answer=answer('inferred')))
        errors = self.errors()
        self.assertTrue(any('needs a literal quote or a link' in line for line in errors), errors)
        self.assertTrue(any('needs the measurement in answer.evidence' in line for line in errors), errors)
        self.assertTrue(any('status inferred has an answer' in line for line in errors), errors)

    def test_hand_edited_dependents_break_the_seal(self):
        data = record()
        data['dependents'] = {**premises.sealed(['docs/plan.md'], [7]), 'prs': [7, 8]}
        self.put(data)
        self.assertIn('do not match their seal', self.errors()[0])

    def test_schema_id_pattern_follows_the_registry(self):
        shape = json.loads((self.root / SCHEMA).read_text())
        shape['properties']['id']['pattern'] = '^Q-[0-9]+$'
        (self.root / SCHEMA).write_text(json.dumps(shape))
        self.assertIn('one fact, one source', self.errors()[0])

    def test_a_committed_index_is_refused(self):
        self.git_init()
        nested = self.root / 'docs' / premises.setting('index_file')
        nested.write_text('# index\n')
        subprocess.run(['git', '-C', str(self.root), 'add', str(nested)], check=True)
        errors, count = premises.check_register(self.root)
        self.assertEqual(count, 0)
        self.assertIn('is committed', errors[0])



PROPOSE = ['propose', '--slug', 'cache-is-safe', '--statement', 'The tier-1 cache never hides a failing test.',
           '--kind', 'process', '--scope', 'unit:gate', '--who', 'agent:motor-4', '--if-wrong', 'M5 changes.',
           '--validate-kind', 'experiment', '--validate-how', 'Break a test and rerun.']


class Commands(Fixture):
    def test_find_ranks_by_statement_and_slug(self):
        self.put(record(statement='GitHub is the source of truth of the code today.', slug='github-truth'))
        self.put(record('P-02', 'events-only', statement='Events, never a clock.'))
        code, lines, _ = self.run_cli('find', 'GitHub source of truth')
        self.assertEqual(code, 0)
        self.assertEqual([line.split()[0] for line in lines], ['P-01'])
        self.assertTrue(self.run_cli('find', 'events-only')[1][0].startswith('P-02 1.00'))

    def test_propose_registers_with_the_computed_radius_and_emits_once(self):
        self.put(record())
        code, lines, events = self.run_cli(*PROPOSE, '--reason', 'gate:tier-1', '--reason', 'unit:gate')
        self.assertEqual(code, 0, lines)
        self.assertEqual(lines[0], 'P-02 high docs/process/premises/cache-is-safe.yml')
        by_id, errors = premises.load(self.root)
        self.assertEqual(errors, [])
        self.assertEqual((by_id['P-02']['status'], by_id['P-02']['radius']), ('to-validate', 'high'))
        self.assertEqual(events[0]['type'], 'premise.proposed')
        self.assertEqual(events[0]['occurred_at'], AT)
        again = premises.event('premise.proposed', 'P-02', events[0]['payload'], AT, self.root)
        self.assertEqual(again['event_id'], events[0]['event_id'])

    def test_events_are_published_through_the_port_not_printed(self):
        self.put(record())
        adapter = forge_events.MemoryAdapter()
        code, lines, events = self.run_cli(*PROPOSE, port=premises.ForgePort(adapter, 'o/r'))
        self.assertEqual((code, events), (0, []))
        held = adapter.read(forge_events.Channel('o/r', None))
        self.assertEqual([e['type'] for e in held], ['premise.proposed'])
        self.assertEqual(held[0]['payload']['id'], 'P-02')
        self.run_cli('answer', 'P-02', '--value', 'confirmed', '--by', 'Daniel', '--quote', 'Sim.',
                     port=premises.ForgePort(adapter, 'o/r'))
        self.assertEqual([e['type'] for e in adapter.read(forge_events.Channel('o/r', None))],
                         ['premise.proposed', 'premise.confirmed'])

    def test_publishing_twice_is_idempotent(self):
        adapter = forge_events.MemoryAdapter()
        port = premises.ForgePort(adapter, 'o/r')
        envelope = premises.event('premise.blast', 'P-01\nd', {'id': 'P-01', 'radius': 'low', 'reasons': [],
                                  'dependents': {'plans': [], 'prs': []}, 'blocking': False}, AT, self.root)
        port.publish(envelope)
        port.publish(envelope)
        self.assertEqual(adapter.appends, 1)

    def test_publish_reads_the_newest_window_never_the_whole_channel(self):
        """GATE-ON-PUSH: the repository channel (#548) is past forge-events.github_max_pages; a full read raises."""
        class Windowed(forge_events.MemoryAdapter):
            def read(self, channel):
                raise forge_events.ForgeEventsError('more event comments than forge-events.github_max_pages reads')

            def recent(self, channel):
                return forge_events.MemoryAdapter.read(self, channel), False
        adapter = Windowed()
        port = premises.ForgePort(adapter, 'o/r')
        envelope = premises.event('premise.blast', 'P-01\nd', {'id': 'P-01', 'radius': 'low', 'reasons': [],
                                  'dependents': {'plans': [], 'prs': []}, 'blocking': False}, AT, self.root)
        port.publish(envelope)
        port.publish(envelope)
        self.assertEqual(adapter.appends, 1, 'published once, deduplicated against the window')

    def test_publish_refuses_an_envelope_the_readers_would_refuse(self):
        """ENV-FIX-PREMISE-BLAST: the producer 'scripts/premises' reached the shared log once; publish now validates."""
        adapter = forge_events.MemoryAdapter()
        envelope = premises.event('premise.blast', 'P-01\nd', {'id': 'P-01', 'radius': 'low', 'reasons': [],
                                  'dependents': {'plans': [], 'prs': []}, 'blocking': False}, AT, self.root)
        self.assertEqual(envelope['producer'], 'premises')
        with self.assertRaises(premises.event_contracts.ContractError):
            premises.ForgePort(adapter, 'o/r').publish(dict(envelope, producer='scripts/premises'))
        self.assertEqual(adapter.read(forge_events.Channel('o/r', None)), [])

    def test_an_unreachable_forge_prints_the_event_with_a_warning(self):
        class Down:
            def read(self, channel):
                raise forge_events.ForgeEventsError('no network')
        self.put(record())
        out, err = io.StringIO(), io.StringIO()
        import contextlib
        with contextlib.redirect_stderr(err):
            code = premises.main(['--root', str(self.root), '--at', AT, *PROPOSE], out=out,
                                 port=premises.ForgePort(Down(), 'o/r'))
        self.assertEqual(code, 0)
        self.assertIn('event: {', out.getvalue())
        self.assertIn('printed instead', err.getvalue())

    def test_propose_refuses_a_duplicate(self):
        self.put(record(statement='The tier-1 cache never hides a failing test.'))
        code, lines, events = self.run_cli(*PROPOSE)
        self.assertEqual((code, events), (1, []))
        self.assertIn('P-01 (one-thing) already says this', lines[0])

    def test_answer_needs_a_quote_and_emits_confirmed_or_refuted(self):
        self.put(record(radius='high', reasons=['decision:D-065']))
        self.put(record('P-02', 'two', dependents=premises.sealed(['docs/plan.md'], [491])))
        code, lines, _ = self.run_cli('answer', 'P-01', '--value', 'confirmed', '--by', 'Daniel')
        self.assertEqual(code, 1)
        self.assertIn('needs the literal words', lines[0])
        code, _, events = self.run_cli('answer', 'P-01', '--value', 'confirmed', '--by', 'Daniel', '--quote', 'Sim.')
        self.assertEqual((code, events[0]['type'], events[0]['payload']['quote']), (0, 'premise.confirmed', 'Sim.'))
        code, _, events = self.run_cli('answer', 'P-02', '--value', 'refuted', '--by', 'Daniel', '--where', 'chat 16:18')
        self.assertEqual(events[0]['type'], 'premise.refuted')
        self.assertEqual(events[0]['payload']['dependents'], {'plans': ['docs/plan.md'], 'prs': [491]})
        by_id, errors = premises.load(self.root)
        self.assertEqual((errors, by_id['P-01']['status'], by_id['P-02']['status']), ([], 'confirmed', 'refuted'))

    def test_propose_reaching_a_large_share_of_the_units_is_high(self):
        self.put(record())
        share = premises.setting('high_blast_unit_share_percent')
        units = [f'unit:u{n}' for n in range(2)]
        active = (len(units) * 100) // share
        argv = [*PROPOSE, '--reason', units[0], '--reason', units[1], '--active-units']
        self.assertEqual(premises.computed_radius(units, active + 1), premises.setting('default_radius'))
        code, lines, _ = self.run_cli(*argv, str(active))
        self.assertEqual(code, 0, lines)
        self.assertIn(' high ', lines[0])

    def test_list_writes_the_index_outside_git(self):
        self.put(record())
        limit = premises.setting('batch_max_questions')
        for n in range(limit + 1):
            self.put(record(f'P-{n + 2:02d}', f'open-high-{n}', radius='high'))
        code, lines, _ = self.run_cli('list')
        index = (self.root / premises.setting('index_dir') / premises.setting('index_file')).read_text()
        self.assertEqual(code, 0)
        self.assertIn('| P-01 | inferred | low |', index)
        batch = index.split('## Next question batch', 1)[1]
        self.assertEqual(batch.count('Ask.'), limit)
        self.assertNotIn('P-01:', batch)
        self.assertEqual(premises.check_register(self.root), ([], limit + 2))

    def test_blast_computes_and_seals_dependents(self):
        self.git_init()
        self.put(record(radius='high', reasons=['decision:D-065']))
        plan = self.root / 'docs/plan.md'
        plan.write_text('# Plan\n\nPremises: P-01, P-07\n')
        subprocess.run(['git', '-C', str(self.root), 'add', 'docs/plan.md'], check=True)
        bodies = {12: 'Premises: P-01', 13: 'Premises: none'}
        code, lines, events = self.run_cli('blast', 'P-01', '--pr', '12', '--pr', '13', '--write', fetch=bodies.get)
        self.assertEqual(code, 0)
        self.assertIn('blocks its dependents; plans: docs/plan.md; PRs: 12', lines[0])
        self.assertEqual(events[0]['payload']['dependents'], {'plans': ['docs/plan.md'], 'prs': [12]})
        self.assertTrue(events[0]['payload']['blocking'])
        by_id, errors = premises.load(self.root)
        self.assertEqual((errors, by_id['P-01']['dependents']['prs']), ([], [12]))


class Check(Fixture):
    def register(self):
        self.put(record('P-01', 'open-high', radius='high'))
        self.put(record('P-02', 'open-medium', 'to-validate', 'medium'))
        self.put(record('P-03', 'said-no', 'refuted', answer=answer('refuted')))
        self.put(record('P-04', 'said-yes', 'confirmed', 'high', answer=answer('confirmed')))
        self.put(record('P-05', 'small'))

    def test_check_refuses_unknown_refuted_and_unsettled_high(self):
        self.register()
        code, lines, _ = self.run_cli('check', '--text', 'Body.\nPremises: P-01, P-03, P-09, Q-1, P-04')
        self.assertEqual(code, 1)
        failures = [line for line in lines if line.startswith('FAIL')]
        self.assertEqual(len(failures), 4, lines)
        self.assertIn('P-01 has radius high and is inferred; it blocks this work', failures[0])
        self.assertIn('P-03 is refuted', failures[1])
        self.assertIn('P-09 is not in', failures[2])
        self.assertIn('"Q-1" is not a premise id', failures[3])
        code, lines, _ = self.run_cli('check', '--text', 'Premises: P-02, P-04, P-05')
        self.assertEqual(code, 0)
        self.assertEqual(lines[0], 'WARN Premises: P-02 has radius medium and is to-validate')
        self.assertEqual(self.run_cli('check', '--text', 'Premises: none')[0], 0)

    def test_the_change_that_records_a_premise_may_cite_it(self):
        self.register()
        own = 'docs/process/premises/said-no.yml'
        self.assertEqual(self.run_cli('check', '--text', 'Premises: P-03', '--changed', own)[0], 0)
        pulls = {7: ('Premises: P-01, P-03', ['docs/process/premises/open-high.yml'])}
        out = io.StringIO()
        code = premises.main(['--root', str(self.root), 'check', '--pr', '7'], out=out, fetch_pull=pulls.get)
        self.assertEqual(code, 1)
        self.assertNotIn('P-01', out.getvalue())
        self.assertIn('P-03 is refuted', out.getvalue())

    def test_unreadable_pr_preserves_failure_for_runtime_and_port_errors(self):
        from unittest.mock import Mock
        for error in (RuntimeError('unavailable'), forge_events.ForgeEventsError('unavailable')):
            out = io.StringIO()
            code = premises.main(['--root', str(self.root), 'check', '--pr', '1'],
                                 out=out, fetch_pull=Mock(side_effect=error))
            self.assertEqual(code, 1)
            self.assertEqual(out.getvalue(), 'FAIL PR #1 not readable (unavailable)\n')

    def test_missing_line_is_a_warning_in_v0(self):
        self.register()
        self.assertFalse(premises.setting('missing_line_fails'))
        code, lines, _ = self.run_cli('check', '--text', 'A body without the line.')
        self.assertEqual(code, 0)
        self.assertIn('a warning in v0', lines[0])
        errors, warnings, _ = premises.check_line('No line.', {})
        self.assertEqual((errors, len(warnings)), ([], 1))

class Quote(Fixture):
    """PB1: a cited premise is confirmed with a literal quote, or its blast radius decides (D-069 item 10)."""

    def cite(self, **fields):
        data = record(ident='P-90', slug='cited-one', **fields)
        return premises.check_line('Premises: P-90', {'P-90': {**data, 'path': 'x'}})

    def settled(self, quote, radius, ident='P-90'):
        return self.cite(status='confirmed', radius=radius, answer=answer('confirmed', quote=quote, where='chat'))

    def test_confirmed_with_quote_is_counted(self):
        self.assertEqual(self.settled('Sim, pode.', 'high'), ([], [], 1))

    def test_confirmed_without_quote_and_high_radius_fails(self):
        errors, warnings, counted = self.settled(None, 'high')
        self.assertEqual((len(errors), warnings, counted), (1, [], 0))
        self.assertIn('without a literal quote', errors[0])

    def test_blank_quote_counts_as_no_quote(self):
        self.assertEqual(len(self.settled('  ', 'high')[0]), 1)

    def test_confirmed_without_quote_medium_warns_low_counts(self):
        errors, warnings, counted = self.settled(None, 'medium')
        self.assertEqual((errors, len(warnings), counted), ([], 1, 0))
        self.assertEqual(self.settled(None, 'low'), ([], [], 1))

    def test_validated_needs_no_quote(self):
        data = self.cite(status='validated', radius='high', answer=answer('validated', quote=None, evidence='measured'))
        self.assertEqual(data, ([], [], 1))

    def test_grandfathered_premise_is_counted(self):
        by_id = {'P-27': {**record(ident='P-27', status='confirmed', radius='high',
                                   answer=answer('confirmed', quote=None, where='chat')), 'path': 'x'}}
        self.assertEqual(premises.check_line('Premises: P-27', by_id), ([], [], 1))

    def test_unconfirmed_high_still_fails_and_medium_warns(self):
        self.assertEqual(len(self.cite(status='inferred', radius='high')[0]), 1)
        self.assertEqual(len(self.cite(status='inferred', radius='medium')[1]), 1)

    def test_answer_refuses_confirmed_without_quote(self):
        self.put(record(radius='high'))
        code, lines, events = self.run_cli('answer', 'P-01', '--value', 'confirmed', '--by', 'Daniel', '--where', 'chat')
        self.assertEqual((code, events), (1, []))
        self.assertIn('--quote', lines[0])
        self.assertEqual(self.errors(), [])
        self.assertEqual(premises.load(self.root)[0]['P-01']['status'], 'inferred')

    def test_answer_accepts_confirmed_with_quote(self):
        self.put(record(radius='high'))
        code, _, events = self.run_cli('answer', 'P-01', '--value', 'confirmed', '--by', 'Daniel', '--quote', 'Sim.')
        self.assertEqual((code, len(events)), (0, 1))

    def test_registry_grandfathers_only_unquoted_confirmed_premises(self):
        by_id, _ = premises.load(ROOT)
        for ident in premises.setting('unquoted_grandfathered'):
            self.assertEqual(by_id[ident]['status'], 'confirmed', ident)
            self.assertFalse((by_id[ident]['answer']['quote'] or '').strip(), ident)
        self.assertEqual([i for i, r in by_id.items() if premises.unquoted(r)], [])


class Repository(unittest.TestCase):
    def test_repository_register_is_valid(self):
        by_id, errors = premises.load(ROOT)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(by_id), [f'P-{n:02d}' for n in range(len(by_id))])  # contiguous from P-00; the register grows without a count here
        self.assertEqual(by_id['P-00']['status'], 'refuted')
        self.assertEqual({by_id[i]['answer']['by'] for i in ('P-01', 'P-04', 'P-05', 'P-06', 'P-07')}, {'A Torre'})
        self.assertEqual((by_id['P-03']['status'], by_id['P-03']['answer']['by']), ('validated', 'measurement:S1'))  # spike S1 settled it
        self.assertEqual([by_id[i]['status'] for i in ('P-02', 'P-08', 'P-26')], ['confirmed', 'validated', 'validated'])

class ForgeBodyMigration(unittest.TestCase):
    def test_body_uses_selected_adapter_and_preserves_null_body(self):
        from unittest.mock import patch
        import forge_doubles
        for body, expected in [('Premises: P-01', 'Premises: P-01'), (None, '')]:
            asked = []
            adapter = forge_doubles.origin(change=lambda repo, number, body=body: asked.append((repo, number)) or
                                           {'head': 'h', 'base': 'b', 'body': body})
            with patch.object(premises.forge_events, 'adapter_from_config', return_value=adapter):
                self.assertEqual(premises.fetch_body(1), expected)
            self.assertEqual(asked, [(premises.config.get('forge-events.repo'), 1)])

    def test_fetch_pr_preserves_body_file_names_and_empty_success(self):
        from unittest.mock import patch
        import forge_doubles
        for files in ([], [{'filename': 'a.py'}, {'filename': 'b.py'}]):
            asked = []
            adapter = forge_doubles.origin(change_files=lambda repo, number, files=files: asked.append((repo, number))
                                           or files)
            with patch.object(premises.forge_events, 'adapter_from_config', return_value=adapter), \
                    patch.object(premises, 'fetch_body', return_value='Premises: none') as body:
                self.assertEqual(premises.fetch_pr(1), ('Premises: none', [f['filename'] for f in files]))
                body.assert_called_once_with(1)
            self.assertEqual(asked, [(premises.config.get('forge-events.repo'), 1)])

    def test_change_files_preserves_origin_pagination_and_empty_success(self):
        from urllib.parse import parse_qs, urlsplit
        import forge_origin_client
        size = forge_origin_client.settings()['page_size']
        for count in (0, size + 1):
            files = [{'filename': f'file-{n}.py'} for n in range(count)]
            asked = []
            def request(method, path, body):
                query = parse_qs(urlsplit(path).query)
                start = int(query.get('pageToken', ['0'])[0])
                stop = start + int(query['pageSize'][0])
                asked.append(start)
                return {'files': files[start:stop], 'nextPageToken': str(stop) if stop < count else ''}
            self.assertEqual(forge_origin_client.OriginClient(run=request).change_files('o/r', 1), files)
            self.assertEqual(asked, [0] if count == 0 else [0, size])



if __name__ == '__main__':
    unittest.main(verbosity=1 if os.environ.get('CI') else 2)
