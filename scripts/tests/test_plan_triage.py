"""Triage of plan inputs and the scripts/plan CLI (live-planning LP4, D-071; design 1.2-1.3)."""
import contextlib
import copy
from datetime import datetime, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import forge_events  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))  # the tests' own helpers
import forge_pin  # noqa: E402
import plan_triage  # noqa: E402

REPO = config.get('forge-events.repo')


def setUpModule():
    unittest.enterModuleContext(config.use_adapter(forge_events.MemoryAdapter()))


def subject(unit=None, pr=None, sha=None, premises=()):
    return forge_events.subject(REPO, pr, sha, premises, unit)


def envelope(kind, payload, at='2026-10-27T17:00:00.000Z', event_id=None):
    return {'type': kind, 'version': 1, 'occurred_at': at, 'producer': 'test', 'correlation_id': 'test',
            'event_id': event_id or f'{kind}-{at}', 'payload': payload}


SHA, INPUT_HASH = hashlib.sha1(b'').hexdigest(), hashlib.sha256(b'').hexdigest()
# Test data is JSON text, so its numbers are data of the fixture, not engine values (literal census, LT1).
SAMPLE = """{
 "contract": "program.v1",
 "program": "p",
 "complaint": {
  "symptom": "s",
  "evidence": "e",
  "goal": {
   "metric": "m",
   "comparator": "gte",
   "target": 1,
   "unit": "u"
  }
 },
 "units": [
  {
   "id": "A1",
   "depends_on": [],
   "owner": "engine-lane",
   "model": "m",
   "wave": 1,
   "done": [
    "d"
   ],
   "area": [
    "scripts/lib/config*.py"
   ],
   "estimate": 60,
   "pr": 10
  },
  {
   "id": "B1",
   "depends_on": [
    "A1"
   ],
   "owner": "engine-lane",
   "model": "m",
   "wave": 2,
   "done": [
    "d"
   ],
   "area": [
    "scripts/tests/gate-db.test.sh",
    "scripts/lib/gate_select.py"
   ],
   "pr": 11
  },
  {
   "id": "B2",
   "depends_on": [
    "A1"
   ],
   "owner": "engine-lane",
   "model": "m",
   "wave": 2,
   "done": [
    "d"
   ],
   "area": [
    "docs/padrao/**"
   ]
  },
  {
   "id": "C1",
   "depends_on": [
    "B1"
   ],
   "owner": "other-lane",
   "model": "m",
   "wave": 3,
   "done": [
    "d"
   ],
   "area": [
    "products/demo/**"
   ]
  }
 ]
}"""
PR = {unit['id'].lower(): unit.get('pr') for unit in json.loads(SAMPLE)['units']}


def sample():
    """A program.v1 graph with areas and an estimate (minutes), two lanes."""
    return copy.deepcopy(json.loads(SAMPLE))


FROM_PLAN = object()  # the unit's PR in SAMPLE


def gate_failed(unit, tests, klass='code', at='2026-10-27T17:00:00.000Z', stage='script tests', pr=FROM_PLAN):
    pr = PR.get(unit) if pr is FROM_PLAN else pr
    payload = dict(subject(unit, pr, SHA), tier=1, plan='dev', missing_stages=[], input_hash=INPUT_HASH,
                   stages=[{'name': stage, 'result': 'FAIL', 'duration_ms': 1, 'class': klass}],
                   failing_tests=[{'id': test, 'stage': stage, 'signature': error} for test, error in tests])
    return envelope('gate.failed', payload, at, f'gate-{unit}-{pr}-{at}')


class JournalOnGitHub(unittest.TestCase):
    """GITHUB-DIARY: plan note and plan input write the journal alone (forge-events.log_adapter), never building the
    forge's main adapter, whose Origin adapter refuses a GitHub remote (every plan note failed after D-314)."""

    def test_a_note_goes_to_the_log_adapter_and_never_builds_the_forge_adapter(self):
        journal = forge_events.MemoryAdapter()

        def refused():
            raise AssertionError('plan note built the forge adapter (Origin)')
        adapters = {**forge_events.ADAPTERS, 'git-ref': lambda: journal, 'origin': refused}
        with mock.patch.dict(forge_events.ADAPTERS, adapters), contextlib.redirect_stdout(io.StringIO()) as out:
            code = plan_triage.main(['note', '--program', 'deploy', '--from', 'QUEUE-SWAP', '--affects', 'deploy',
                                     '--kind', 'engine', '--evidence', 'pr 49', 'the swap landed'])
        self.assertEqual(code, 0)
        said = [event for events in journal.logs.values() for event in events]
        self.assertEqual([event['type'] for event in said], ['plan.note'])
        self.assertEqual((said[0]['payload']['text'], said[0]['payload']['program']), ('the swap landed', 'deploy'))
        self.assertIn(said[0]['event_id'], out.getvalue())
        with mock.patch.dict(forge_events.ADAPTERS, adapters):
            self.assertIsInstance(forge_events.journal_from_config(), (forge_events.MemoryAdapter, forge_events.RoutingAdapter))
        self.assertEqual(plan_triage.JOURNAL_ONLY, ('note', 'input'))


class Signatures(unittest.TestCase):
    def test_failure_signature_ignores_test_id_digits_and_registry_names(self):
        one = gate_failed('a1', [('scripts/tests/a.test.sh', "config: gate.alpha_s is not a registered parameter")])
        two = gate_failed('b1', [('scripts/tests/b.test.sh', "config: planner.beta_2 is not a registered parameter")])
        self.assertEqual(plan_triage.signature(one), plan_triage.signature(two))
        self.assertTrue(plan_triage.signature(one).startswith('failure:'))

    def test_different_causes_differ(self):
        one = gate_failed('a1', [('t', "ModuleNotFoundError: No module named 'gate_select'")])
        two = gate_failed('a1', [('t', "ModuleNotFoundError: No module named 'encodings'")])
        self.assertNotEqual(plan_triage.signature(one), plan_triage.signature(two))

    def test_a_run_splits_into_one_input_per_signature(self):
        event = gate_failed('a1', [('x', 'psql: timeout expired'), ('y', 'psql: timeout expired'), ('z', 'boom')])
        parts = plan_triage.inputs(event)
        self.assertEqual(len(parts), len({'psql: timeout expired', 'boom'}))
        self.assertEqual({len(part['payload']['failing_tests']) for part in parts}, {1})

    def test_red_stage_without_failing_test_is_its_own_input(self):
        event = gate_failed('a1', [])
        self.assertEqual(plan_triage.signature(event), 'failure:script tests:code')
        base = gate_failed(None, [])
        self.assertEqual(plan_triage.source(base), 'base')
        self.assertEqual(plan_triage.signature(base), plan_triage.signature(event))

    def test_other_sources(self):
        lesson = envelope('lesson.recorded', dict(subject('a1'), lesson='l', **{'class': 'registry-keys'}, kind='k',
                                                  owner='o', source_unit='a1'))
        self.assertEqual(plan_triage.signature(lesson), 'lesson:registry-keys')
        self.assertEqual(plan_triage.signature(envelope('premise.refuted', {'id': 'P-51'})), 'premise:P-51')
        self.assertIsNone(plan_triage.source(envelope('plan.changed', {})))


class Affected(unittest.TestCase):
    def test_note_units_areas_and_all(self):
        plan = sample()
        note = envelope('plan.note', dict(subject(), program='p', from_unit='A1', affects=['b2', 'products/demo/x.ts'],
                                          kind='blocker', evidence='#1', text='t'))
        self.assertEqual(plan_triage.affected(note, plan), ['B2', 'C1'])
        note['payload']['affects'] = ['all']
        self.assertEqual(plan_triage.affected(note, plan), ['all'])

    def test_failing_test_path_and_producer(self):
        event = gate_failed('a1', [('scripts/tests/gate-db.test.sh', 'boom')])
        self.assertEqual(plan_triage.affected(event, sample()), ['A1', 'B1'])

    def test_env_class_and_base_touch_all(self):
        self.assertEqual(plan_triage.affected(gate_failed('a1', [('t', 'x')], klass='env'), sample()), ['all'])
        self.assertEqual(plan_triage.affected(gate_failed(None, [('t', 'x')]), sample()), ['all'])

    def test_merged_units_are_never_affected(self):
        merged = envelope('pr.merged', subject('b1', PR['b1']))
        event = gate_failed('a1', [('scripts/tests/gate-db.test.sh', 'boom')])
        self.assertEqual(plan_triage.affected(event, sample(), [merged]), ['A1'])

    def test_premise_by_citing_events_and_refuted_prs(self):
        cites = envelope('work.assigned', dict(subject('b2', premises=['P-51']), lane_id='l', units=['b2'], item='i'))
        refuted = envelope('premise.refuted', {'id': 'P-51', 'by': 'A Torre', 'at': 'now',
                                               'dependents': {'plans': [], 'prs': [PR['a1']]}})
        self.assertEqual(plan_triage.affected(refuted, sample(), [cites]), ['A1', 'B2'])

    def test_lesson_reaches_its_lane_only(self):
        lesson = envelope('lesson.recorded', dict(subject('a1'), lesson='l', **{'class': 'c'}, kind='k', owner='o',
                                                  source_unit='a1'))
        self.assertEqual(plan_triage.affected(lesson, sample()), ['B1', 'B2'])


class Overrun(unittest.TestCase):
    def assigned(self, at):
        return envelope('work.assigned', dict(subject('a1'), lane_id='l', units=['a1'], item='i'), at)

    def test_overrun_at_the_factor(self):
        factor = config.get('planner.overrun_factor')
        start = self.assigned('2026-10-27T10:00:00.000Z')
        estimate = sample()['units'][0]['estimate']
        limit = datetime.fromisoformat('2026-10-27T10:00:00+00:00') + timedelta(minutes=estimate * factor)
        inside = envelope('pr.opened', subject('a1', PR['a1']), forge_events.rfc3339(limit))
        later = envelope('pr.opened', subject('a1', PR['a1']), forge_events.rfc3339(limit + timedelta(seconds=1)))
        self.assertFalse(plan_triage.overrun('A1', sample(), [start, inside]))
        self.assertTrue(plan_triage.overrun('A1', sample(), [start, later]))

    def test_the_latest_folded_set_estimate_wins(self):
        start = self.assigned('2026-10-27T10:00:00.000Z')
        late = envelope('pr.opened', subject('b1', PR['b1']), '2026-10-27T18:00:00.000Z')
        plan = sample()
        self.assertFalse(plan_triage.overrun('B1', plan, [start, late]))
        estimate = sample()['units'][0]['estimate']
        plan['records'] = [{'version': 1, 'op': 'set_estimate', 'unit': 'B1', 'args': {'estimate': estimate}}]
        assigned = envelope('work.assigned', dict(subject('b1'), lane_id='l', units=['b1'], item='i'), start['occurred_at'])
        self.assertTrue(plan_triage.overrun('B1', plan, [assigned, late]))
        plan['records'].append(dict(plan['records'][0], args={'estimate': estimate * estimate}))
        self.assertFalse(plan_triage.overrun('B1', plan, [assigned, late]))

    def test_no_estimate_or_no_assignment_is_no_overrun(self):
        late = envelope('pr.opened', subject('b1', PR['b1']), '2026-10-28T10:00:00.000Z')
        self.assertFalse(plan_triage.overrun('B1', sample(), [self.assigned('2026-10-27T10:00:00.000Z'), late]))
        self.assertFalse(plan_triage.overrun('A1', sample(), [late]))


def port(adapter=None):
    return forge_events.ForgeEvents(adapter or forge_events.MemoryAdapter(), forge_events.SystemClock(), 'test', 'test')


class Promotion(unittest.TestCase):
    def test_own_code_failure_is_seen_until_the_promote_sightings(self):
        promote, seen = config.get('planner.triage_promote_sightings'), {}
        for number in range(1, promote + 1):
            event = gate_failed('a1', [('scripts/tests/own.test.sh', 'boom')], at=f'2026-10-27T17:0{number}:00.000Z')
            result = plan_triage.triage(event, sample(), seen)
            self.assertEqual(result['sightings'], number)
            self.assertEqual(result['disposition'], 'candidate' if number >= promote else 'seen', result['reason'])
        self.assertEqual(list(seen), [plan_triage.signature(event)])
        self.assertEqual(len(result['inputs']), promote)

    def test_touching_another_unit_promotes_at_once(self):
        event = gate_failed('a1', [('scripts/tests/gate-db.test.sh', 'boom')])
        result = plan_triage.triage(event, sample())
        self.assertEqual(result['disposition'], 'candidate')
        self.assertIn('touches B1', result['reason'])

    def test_env_class_owner_and_base_promote(self):
        self.assertEqual(plan_triage.triage(gate_failed('a1', [('t', 'x')], klass='env'), sample())['partition'], 'engine')
        ruling = envelope('plan.input', dict(subject(), program='p', by='Daniel', at='2026-10-27T15:02:00Z', text='t', ref=None))
        self.assertEqual(plan_triage.triage(ruling, sample())['disposition'], 'candidate')

    def test_premise_nobody_cites_is_seen_with_its_reason(self):
        result = plan_triage.triage(envelope('premise.confirmed', {'id': 'P-99', 'status': 'confirmed', 'by': 'A Torre',
                                                                    'at': 'now'}), sample())
        self.assertEqual(result['disposition'], 'seen')
        self.assertIn('premise input', result['reason'])

    def test_overrun_is_derived_once_per_unit(self):
        events = [envelope('work.assigned', dict(subject('a1'), lane_id='l', units=['a1'], item='i'), '2026-10-27T10:00:00.000Z')]
        events += [envelope('pr.opened', subject('a1', PR['a1']), f'2026-10-27T{hour}:00:00.000Z') for hour in ('11', '15', '16')]
        found = plan_triage.triage_all(events, sample())
        self.assertEqual(list(found), ['overrun:a1'])
        self.assertEqual(found['overrun:a1']['affected'], ['A1', 'B1', 'B2', 'C1'])
        self.assertEqual(found['overrun:a1']['sightings'], 1)

    def test_payloads_validate_against_plan_candidate(self):
        for result in plan_triage.triage_all(replay_2710(), gate_excellence()).values():
            port().build('plan.candidate', result)


GATE_EXCELLENCE = """{
 "contract": "program.v1",
 "program": "gate-excellence",
 "complaint": {
  "symptom": "s",
  "evidence": "e",
  "goal": {
   "metric": "m",
   "comparator": "gte",
   "target": 1,
   "unit": "u"
  }
 },
 "units": [
  {
   "id": "HD1",
   "depends_on": [],
   "owner": "engine-lane",
   "model": "m",
   "wave": 1,
   "done": [
    "d"
   ],
   "area": [
    "scripts/lib/gate_select.py",
    "scripts/tests/gate-select.test.sh"
   ],
   "pr": 677
  },
  {
   "id": "GX01",
   "depends_on": [],
   "owner": "engine-lane",
   "model": "m",
   "wave": 1,
   "done": [
    "d"
   ],
   "area": [
    "scripts/lib/gate_report.py",
    "scripts/tests/gate-report.test.sh"
   ],
   "pr": 694
  },
  {
   "id": "GX02",
   "depends_on": [],
   "owner": "engine-lane",
   "model": "m",
   "wave": 1,
   "done": [
    "d"
   ],
   "area": [
    "scripts/lib/engine_role.py"
   ],
   "pr": 692
  },
  {
   "id": "GX03",
   "depends_on": [],
   "owner": "engine-lane",
   "model": "m",
   "wave": 1,
   "done": [
    "d"
   ],
   "area": [
    "scripts/lib/test_db.py"
   ],
   "pr": 667
  }
 ]
}"""
# 27/10 (docs/programs/live-planning/audit.md section 4): case -> the gate.failed runs that carried it.
CASES_2710 = json.loads("""{
 "L1": [
  {
   "unit": "hd1",
   "pr": 677,
   "at": "17:27",
   "test": "scripts/tests/gate-select.test.sh",
   "error": "config: gate.select_budget_s is not a registered parameter (config/registry/<owner>.json)",
   "class": "code"
  },
  {
   "unit": "gx01",
   "pr": 694,
   "at": "17:34",
   "test": "scripts/tests/gate-report.test.sh",
   "error": "config: gate.report_tail_lines is not a registered parameter (config/registry/<owner>.json)",
   "class": "code"
  }
 ],
 "L2": [
  {
   "unit": null,
   "pr": null,
   "at": "07:03",
   "test": "scripts/tests/gate-db.test.sh",
   "error": "ModuleNotFoundError: No module named 'gate_select'",
   "class": "code"
  },
  {
   "unit": "gx01",
   "pr": 694,
   "at": "17:32",
   "test": "scripts/tests/gate-db.test.sh",
   "error": "ModuleNotFoundError: No module named 'gate_select'",
   "class": "code"
  }
 ],
 "L5": [
  {
   "unit": "gx02",
   "pr": 692,
   "at": "16:58",
   "test": "scripts/tests/root-identity.test.sh",
   "error": "ModuleNotFoundError: No module named 'encodings'",
   "class": "code"
  },
  {
   "unit": null,
   "pr": null,
   "at": "17:05",
   "test": "scripts/tests/root-identity.test.sh",
   "error": "ModuleNotFoundError: No module named 'encodings'",
   "class": "code"
  }
 ],
 "L5-store": [
  {
   "unit": "hd1",
   "pr": 677,
   "at": "17:36",
   "test": "scripts/tests/config.test.sh",
   "error": "config.StoreError: missing GH_TOKEN",
   "class": "code"
  },
  {
   "unit": "hd1",
   "pr": 677,
   "at": "17:38",
   "test": "scripts/tests/config.test.sh",
   "error": "config.StoreError: missing GH_TOKEN",
   "class": "code"
  },
  {
   "unit": "hd1",
   "pr": 677,
   "at": "17:40",
   "test": "scripts/tests/config.test.sh",
   "error": "config.StoreError: missing GH_TOKEN",
   "class": "code"
  },
  {
   "unit": "gx01",
   "pr": 694,
   "at": "17:42",
   "test": "scripts/tests/config.test.sh",
   "error": "config.StoreError: missing GH_TOKEN",
   "class": "code"
  },
  {
   "unit": "gx01",
   "pr": 694,
   "at": "17:46",
   "test": "scripts/tests/config.test.sh",
   "error": "config.StoreError: missing GH_TOKEN",
   "class": "code"
  }
 ],
 "L6": [
  {
   "unit": "hd1",
   "pr": 677,
   "at": "07:09",
   "test": "scripts/tests/claude-session.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "gx03",
   "pr": 667,
   "at": "08:09",
   "test": "scripts/tests/gate-heavy-db.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "hd1",
   "pr": 677,
   "at": "09:09",
   "test": "scripts/tests/test-db.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "gx03",
   "pr": 667,
   "at": "10:09",
   "test": "scripts/tests/claude-session.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "hd1",
   "pr": 677,
   "at": "11:09",
   "test": "scripts/tests/gate-heavy-db.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "gx03",
   "pr": 667,
   "at": "12:09",
   "test": "scripts/tests/test-db.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "hd1",
   "pr": 677,
   "at": "13:09",
   "test": "scripts/tests/claude-session.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "gx03",
   "pr": 667,
   "at": "14:09",
   "test": "scripts/tests/gate-heavy-db.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "hd1",
   "pr": 677,
   "at": "15:09",
   "test": "scripts/tests/test-db.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "gx03",
   "pr": 667,
   "at": "16:09",
   "test": "scripts/tests/claude-session.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "hd1",
   "pr": 677,
   "at": "17:09",
   "test": "scripts/tests/gate-heavy-db.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  },
  {
   "unit": "gx03",
   "pr": 667,
   "at": "18:09",
   "test": "scripts/tests/test-db.test.sh",
   "error": "psql: error: connection to server on socket failed: timeout expired",
   "class": "code"
  }
 ]
}""")


def gate_excellence():
    """The units 27/10's cases touched (gate-excellence wave 0-1, reconstructed for the replay)."""
    return json.loads(GATE_EXCELLENCE)


def replay_2710():
    events = [gate_failed(run['unit'], [(run['test'], run['error'])], run['class'], f'2026-10-27T{run["at"]}:00.000Z',
                          pr=run['pr']) for case in CASES_2710.values() for run in case]
    return sorted(events, key=lambda event: event['occurred_at'])


class Replay2710(unittest.TestCase):
    def test_one_candidate_per_signature(self):
        found = plan_triage.triage_all(replay_2710(), gate_excellence())
        expected = {case: plan_triage.signature(gate_failed(None, [(rows[0]['test'], rows[0]['error'])])) for case, rows in CASES_2710.items()}
        self.assertEqual(len(set(expected.values())), len(CASES_2710))
        self.assertEqual(set(found), set(expected.values()))
        for case, key in expected.items():
            self.assertEqual(found[key]['disposition'], 'candidate', (case, found[key]['reason']))
            self.assertEqual(found[key]['sightings'], len(CASES_2710[case]), case)

    def test_replay_is_deterministic(self):
        self.assertEqual(plan_triage.triage_all(replay_2710(), gate_excellence()),
                         plan_triage.triage_all(replay_2710(), gate_excellence()))


class Cli(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.logs = Path(self.folder.name) / 'log'
        self.plan = Path(self.folder.name) / 'plan.json'
        self.plan.write_text(json.dumps(sample()))

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = plan_triage.main(list(argv) + ['--program', 'p', '--log-dir', str(self.logs)])
        return code, out.getvalue()

    def store(self):
        return port(forge_events.FileAdapter(self.logs)).read(REPO)

    def test_note_input_triage_round_trip(self):
        code, out = self.run_main('note', '--from', 'A1', '--affects', 'B2,products/demo/page.tsx', '--kind', 'blocker',
                                  '--evidence', '#713', '--premises', 'P-51', 'the registry needs a key per unit')
        self.assertEqual(code, 0)
        self.assertEqual(self.run_main('input', '--by', 'A Torre', '--at', '2026-10-27T15:01:00Z', 'prep before fan-out')[0], 0)
        kinds = [event['type'] for event in self.store()]
        self.assertEqual(kinds, ['plan.note', 'plan.input'])
        self.assertEqual(out.strip(), self.store()[0]['event_id'])
        self.assertEqual(self.store()[0]['payload']['unit'], 'a1')
        code, out = self.run_main('triage', '--plan', str(self.plan), '--publish')
        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out.splitlines()]
        self.assertEqual([line['source'] for line in lines], ['note', 'owner'])
        self.assertEqual(lines[0]['affected'], ['B2', 'C1'])
        self.assertEqual({line['disposition'] for line in lines}, {'candidate'})
        published = [event for event in self.store() if event['type'] == 'plan.candidate']
        self.assertEqual([event['payload'] for event in published], lines)
        self.run_main('triage', '--plan', str(self.plan), '--publish')
        self.assertEqual(len([event for event in self.store() if event['type'] == 'plan.candidate']), len(lines))

    def test_triage_reads_an_events_file(self):
        events = Path(self.folder.name) / 'events.jsonl'
        events.write_text(''.join(json.dumps(event) + '\n' for event in replay_2710()))
        plan = Path(self.folder.name) / 'gx.json'
        plan.write_text(json.dumps(gate_excellence()))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), forge_pin.origin():  # the configured forge is built, then the file is read
            plan_triage.main(['triage', '--program', 'gate-excellence', '--plan', str(plan), '--events', str(events)])
        self.assertEqual(len(out.getvalue().splitlines()), len(CASES_2710))

    def test_an_invalid_note_is_refused_by_the_contract(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = self.run_main('note', '--from', 'A1', '--affects', 'all', '--kind', 'gossip', '--evidence', 'x', 't')
        self.assertNotEqual(code, 0)
        self.assertIn('plan note', err.getvalue())
        self.assertEqual(self.store(), [])

    def test_entry_script(self):
        env = dict(os.environ, OU_CONFIG_STORE='file')
        done = subprocess.run([str(ROOT / 'scripts' / 'plan'), '--help'], capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('plan note', done.stdout)


if __name__ == '__main__':
    unittest.main()
