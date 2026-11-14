"""Event contracts (D-065, D-069 items 1 and 2): one schema language, locked versions, deterministic ids. No network."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import config  # noqa: E402
import event_contracts  # noqa: E402
import gate_digest  # noqa: E402
import json_schema  # noqa: E402

SHA = 'a' * 40
REQUIRED_NAMES = {
    'gate.passed', 'gate.failed', 'pr.ready', 'pr.merged', 'pr.conflicted', 'pr.ejected', 'integration.advanced',
    'train.queue.empty', 'train.queue.growing', 'unit.addressable', 'release.ready', 'test.flaked',
    'engine.step.measured', 'premise.proposed', 'premise.confirmed', 'premise.refuted',
    'plan.changed', 'plan.note', 'plan.input', 'plan.candidate',
}


def envelope(kind='pr.merged', **payload):
    body = {'repo': 'openuniversity-si/open-university', 'pr': 7, 'sha': SHA, 'unit': None, 'premises': ['P-02'],
            'merge_sha': 'b' * 40, 'batch_id': None}
    body.update(payload)
    event = {'type': kind, 'version': 1, 'occurred_at': '2026-10-26T18:00:00Z', 'producer': 'train',
             'correlation_id': 'batch-1', 'payload': body}
    event['event_id'] = event_contracts.event_id('train', kind, event_contracts.natural_key(event))
    return event


class Validator(unittest.TestCase):
    def schema_dir(self, schema):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        (directory / 's.json').write_text(json.dumps({'$schema': json_schema.DIALECT, **schema}))
        return json_schema.Registry(directory)

    def test_keywords(self):
        registry = self.schema_dir({
            'type': 'object', 'additionalProperties': False, 'required': ['n'],
            'properties': {'n': {'type': 'integer', 'minimum': 1, 'maximum': 3}, 's': {'type': ['string', 'null'], 'pattern': '^x'},
                           'a': {'type': 'array', 'uniqueItems': True, 'maxItems': 2, 'items': {'enum': [1, 2]}}}})
        registry.validate({'n': 2, 's': None, 'a': [1, 2]}, 's.json')
        for bad in ({}, {'n': 0}, {'n': 4}, {'n': True}, {'n': 1, 's': 'y'}, {'n': 1, 'a': [1, 1]},
                    {'n': 1, 'a': [3]}, {'n': 1, 'a': [1, 2, 1]}, {'n': 1, 'z': 1}):
            with self.subTest(bad=bad), self.assertRaises(json_schema.ValidationError):
                registry.validate(bad, 's.json')

    def test_unsupported_keyword_is_refused(self):
        registry = self.schema_dir({'type': 'string', 'format': 'date-time'})
        with self.assertRaisesRegex(json_schema.SchemaError, 'format'):
            registry.load('s.json')

    def test_dialect_is_2020_12(self):
        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        (directory / 's.json').write_text(json.dumps({'$schema': 'http://json-schema.org/draft-07/schema#'}))
        with self.assertRaisesRegex(json_schema.SchemaError, '2020-12'):
            json_schema.Registry(directory).load('s.json')


class Contracts(unittest.TestCase):
    def copy(self):
        directory = Path(tempfile.mkdtemp()) / 'events'
        shutil.copytree(event_contracts.directory(), directory)
        self.addCleanup(shutil.rmtree, directory.parent)
        return directory

    def test_repository_contracts_pass(self):
        self.assertEqual(event_contracts.check(), [])

    def test_the_catalog_is_held_until_the_listing_changes(self):
        """GATE-SPEED R3: one scan per contracts listing; a schema added later is seen, and a caller's copy is its own."""
        directory = self.copy()
        first = event_contracts.catalog(directory)
        first.clear()
        scans = self.enterContext(mock.patch.object(event_contracts, '_scan', wraps=event_contracts._scan))
        self.assertTrue(event_contracts.catalog(directory))
        self.assertEqual(scans.call_count, 0)
        (directory / 'zz.added.v1.json').write_text('{}')
        self.assertIn('zz.added', event_contracts.catalog(directory))
        self.assertEqual(scans.call_count, True + 0)

    def test_required_names_exist_and_follow_one_scheme(self):
        kinds = set(event_contracts.catalog())
        self.assertLessEqual(REQUIRED_NAMES, kinds)
        for kind in kinds:
            self.assertRegex(kind, r'^[a-z][a-z-]*(\.[a-z][a-z-]*)+$')

    def test_events_md_and_the_schemas_name_the_same_events(self):
        doc = (ROOT / 'docs' / 'process' / 'EVENTS.md').read_text()
        table = doc[doc.index('## Events'):doc.index('## The port')]
        named = set()
        for row in table.splitlines():
            if row.startswith('| `'):
                named |= set(re.findall(r'`([a-z][a-z-]*(?:\.[a-z][a-z-]*)+)`', row.split('|')[1]))
        self.assertEqual(sorted(named ^ set(event_contracts.catalog())), [])

    def test_every_payload_carries_subject_unit_and_premises(self):
        schemas = event_contracts.registry()
        exempt = set(config.get('forge-events.subject_exempt_schemas'))
        for kind, versions in event_contracts.catalog().items():
            for name in set(versions.values()) - exempt:
                with self.subTest(kind=kind):
                    self.assertLessEqual(set(config.get('forge-events.subject_fields')), set(schemas.load(name)['required']))

    def test_changed_locked_schema_is_refused(self):
        directory = self.copy()
        path = directory / 'pr.merged.v1.json'
        schema = json.loads(path.read_text())
        schema['properties']['batch_id'] = {'type': 'string'}
        path.write_text(json.dumps(schema))
        self.assertTrue(any('locked schema changed' in e for e in event_contracts.check(directory)))
        event_contracts.lock(directory)
        self.assertTrue(any('locked schema changed' in e for e in event_contracts.check(directory)), 'lock never rewrites')

    def test_new_version_is_expand_and_gaps_are_refused(self):
        directory = self.copy()
        schema = json.loads((directory / 'pr.merged.v1.json').read_text())

        def add(version):
            schema['$id'] = f'contracts/events/pr.merged.v{version}.json'
            (directory / f'pr.merged.v{version}.json').write_text(json.dumps(schema))

        add(3)
        self.assertTrue(any('not locked' in e for e in event_contracts.check(directory)))
        event_contracts.lock(directory)
        self.assertTrue(any('contiguous' in e for e in event_contracts.check(directory)))
        add(2)
        event_contracts.lock(directory)
        self.assertEqual(event_contracts.check(directory), [])

    def test_removed_locked_schema_is_refused(self):
        directory = self.copy()
        (directory / 'test.flaked.v1.json').unlink()
        self.assertTrue(any('locked schema removed' in e for e in event_contracts.check(directory)))

    def test_natural_key_must_name_required_fields(self):
        directory = self.copy()
        path = directory / 'pr.merged.v1.json'
        schema = json.loads(path.read_text())
        schema['x-natural-key'] = ['/occurred_at']
        path.write_text(json.dumps(schema))
        self.assertTrue(any('natural key /occurred_at' in e for e in event_contracts.check(directory)))


DIGEST = hashlib.sha256(b'selection').hexdigest()
V4_INPUT = dict(head_tree=SHA, base_sha=SHA, plan='dev', selection_digest=DIGEST, toolchain_id='tc', gate_version=SHA)


class GateDigest(unittest.TestCase):
    def schemas(self):
        # the head's own contracts, not the tooling checkout's (the verdict of record runs head code under base tooling)
        return json_schema.Registry(ROOT / 'contracts' / 'events')

    def test_input_digest_is_the_documented_recipe(self):
        expected = hashlib.sha256(json.dumps(list(V4_INPUT.values()), separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(gate_digest.input_digest(**V4_INPUT), expected)

    def test_every_input_changes_the_digest_and_none_is_optional(self):
        base = gate_digest.input_digest(**V4_INPUT)
        for name in V4_INPUT:
            with self.subTest(name=name):
                self.assertNotEqual(gate_digest.input_digest(**{**V4_INPUT, name: 'x'}), base)
                with self.assertRaises(ValueError):
                    gate_digest.input_digest(**{**V4_INPUT, name: ''})

    def test_v4_verdicts_validate_and_need_the_digest(self):
        schemas = self.schemas()
        stage = {'name': 'lint', 'result': 'PASS', 'duration_ms': 0, 'class': 'code', 'cached': False, 'inputs_digest': DIGEST}
        payload = dict(repo='openuniversity-si/open-university', pr=None, sha=SHA, unit=None, premises=['P-42'], tier=1, plan='dev', stages=[stage],
                       missing_stages=[], head_tree=SHA, base_sha=SHA, base_tree=SHA, gate_version='g', toolchain_id='t',
                       selection={'kind': 'all', 'digest': DIGEST}, input_digest=gate_digest.input_digest(**V4_INPUT),
                       cost={'wall_s': 1, 'cpu_s': 0, 'rest_calls': 0, 'queue_wait_s': 0, 'cache_hits': 0, 'cache_misses': 1}, lane_id=None)
        for kind in ('passed', 'failed'):
            schemas.validate(payload, f'gate.{kind}.v4.json')
        with self.assertRaises(json_schema.ValidationError):
            schemas.validate({k: v for k, v in payload.items() if k != 'input_digest'}, 'gate.passed.v4.json')

    def test_new_program_events_validate(self):
        schemas = self.schemas()
        subject = dict(repo='openuniversity-si/open-university', pr=1, sha=SHA, unit=None, premises=['P-42'])
        cases = {
            'pr.checked.v1.json': dict(subject, base_sha=SHA, result='pass', errors=[]),
            'gate.started.v1.json': dict(subject, tier=1, plan='dev', expected_wall_s=1, critical_path=['build']),
            'base.red.v1.json': dict(subject, base_sha=SHA, since=SHA, tests=[{'id': 't', 'stage': 'vitest', 'signature': 's'}]),
            'base.green.v1.json': dict(subject, base_sha=SHA, cleared=['t']),
        }
        for name, payload in cases.items():
            with self.subTest(name=name):
                schemas.validate(payload, name)


class Exempt(unittest.TestCase):
    """P1's premise.* v1 payloads predate the port: listed, never emitted, and the list cannot go stale."""

    def test_exempt_schemas_exist_and_cannot_be_emitted(self):
        exempt = config.get('forge-events.subject_exempt_schemas')
        self.assertTrue(all(name.startswith('premise.') for name in exempt))
        event = envelope()
        event.update(type='premise.confirmed', payload={'id': 'P-02', 'status': 'confirmed', 'by': 'Daniel', 'at': None})
        with self.assertRaises(event_contracts.ContractError):
            event_contracts.validate(event)
        with self.assertRaises(event_contracts.ContractError):
            event_contracts.natural_key(event)

    def test_a_stale_exemption_is_refused(self):
        directory = Path(tempfile.mkdtemp()) / 'events'
        shutil.copytree(event_contracts.directory(), directory)
        self.addCleanup(shutil.rmtree, directory.parent)
        (directory / 'premise.blast.v1.json').unlink()
        lock = [e for e in json.loads((directory / 'schemas.lock.json').read_text()) if e['file'] != 'premise.blast.v1.json']
        (directory / 'schemas.lock.json').write_text(json.dumps(lock))
        self.assertEqual([e for e in event_contracts.check(directory) if 'subject_exempt' in e],
                         ['premise.blast.v1.json: listed in forge-events.subject_exempt_schemas but no such schema; drop the entry'])


class Envelope(unittest.TestCase):
    def test_valid_event(self):
        event = envelope()
        self.assertIs(event_contracts.validate(event), event)

    def test_id_is_deterministic_and_ignores_time(self):
        first, second = envelope(), envelope()
        second['occurred_at'] = '2026-10-27T00:00:00Z'
        self.assertEqual(first['event_id'], second['event_id'])
        self.assertNotEqual(first['event_id'], envelope(merge_sha='c' * 40)['event_id'])

    def test_refusals(self):
        cases = {
            'tampered id': dict(envelope(), event_id='0' * 64),
            'unknown type': dict(envelope(), type='pr.vanished'),
            'unknown version': dict(envelope(), version=9),
            'local time': dict(envelope(), occurred_at='2026-10-26T18:00:00-03:00'),
            'extra envelope field': dict(envelope(), sequence=1),
        }
        missing_unit = envelope()
        del missing_unit['payload']['unit']
        cases['payload without unit'] = missing_unit
        bad_premise = envelope()
        bad_premise['payload']['premises'] = ['D-065']
        cases['premise that is not a P-id'] = bad_premise
        for name, event in cases.items():
            with self.subTest(name), self.assertRaises(event_contracts.ContractError):
                event_contracts.validate(event)


def plan_envelope(name, **payload):
    bodies = {
        'plan.changed': {'program': 'live-planning', 'version': 1, 'parent': {'version': 0, 'digest': ''},
                         'ops': [{'op': 'brief_line', 'unit': 'LP3', 'args': {'line': 'x'}}], 'inputs': ['ev-1'],
                         'judgment': ['touches LP3 only'], 'intention': 'one line', 'expected_effect': 'no rework',
                         'decided_by': 'A Torre', 'reversible': True, 'escalated': False, 'digest': hashlib.sha256(b'').hexdigest()},
        'plan.note': {'program': 'live-planning', 'from_unit': 'LP3', 'affects': ['all'], 'kind': 'blocker',
                      'evidence': '#701', 'text': 'one line'},
        'plan.input': {'program': 'live-planning', 'by': 'Daniel', 'at': '2026-10-27T18:00:00Z', 'text': 'ruling',
                       'ref': None},
        'plan.candidate': {'program': 'live-planning', 'signature': 'sig', 'disposition': 'candidate', 'reason': 'env',
                           'source': 'gate', 'inputs': ['ev-1'], 'sightings': 1, 'affected': ['LP3'], 'partition': 'p/a'},
    }
    body = {'repo': 'openuniversity-si/open-university', 'pr': None, 'sha': None, 'unit': None, 'premises': ['P-48'], **bodies[name]}
    body.update(payload)
    event = {'type': name, 'version': 1, 'occurred_at': '2026-10-27T18:00:00Z', 'producer': 'planner',
             'correlation_id': 'live-planning', 'payload': body}
    event['event_id'] = event_contracts.event_id('planner', name, event_contracts.natural_key(event))
    return event


class PlanEvents(unittest.TestCase):
    def test_each_plan_event_is_valid_and_ids_are_deterministic(self):
        for kind in ('plan.changed', 'plan.note', 'plan.input', 'plan.candidate'):
            with self.subTest(kind):
                event = plan_envelope(kind)
                self.assertIs(event_contracts.validate(event), event)
                self.assertEqual(event['event_id'], plan_envelope(kind)['event_id'])

    def test_a_new_version_is_a_new_event(self):
        self.assertNotEqual(plan_envelope('plan.changed')['event_id'], plan_envelope('plan.changed', version=plan_envelope('plan.changed')['payload']['version'] + 1)['event_id'])

    def test_plan_refusals(self):
        max_judgment = event_contracts.registry().load('plan.changed.v1.json')['properties']['judgment']['maxItems']
        cases = {
            'changed without ops': plan_envelope('plan.changed', ops=[]),
            'changed with an unknown op': plan_envelope('plan.changed', ops=[{'op': 'teleport'}]),
            'changed by nobody known': plan_envelope('plan.changed', decided_by='the model'),
            'changed without a chain digest': plan_envelope('plan.changed', digest='short'),
            'changed with 11 judgment lines': plan_envelope('plan.changed', judgment=['x'] * (max_judgment + 1)),
            'note of an unknown kind': plan_envelope('plan.note', kind='gossip'),
            'input by a session': plan_envelope('plan.input', by='lp3'),
            'candidate with zero sightings': plan_envelope('plan.candidate', sightings=0),
            'candidate with an unknown disposition': plan_envelope('plan.candidate', disposition='maybe'),
        }
        for name, event in cases.items():
            with self.subTest(name), self.assertRaises(event_contracts.ContractError):
                event_contracts.validate(event)


class StatusChannel(unittest.TestCase):
    """STATUS-CHANNEL: the repository text must not send a session to write status as a PR comment (Daniel, 02/11).
    The diary is the only status channel, so the two sentences that named a comment are refused here, and the storage
    section has to name the adapter the registry actually selects, not one it used to."""

    def section(self, text, start, end):
        return text[text.index(start):text.index(end)]

    def test_agents_md_sends_each_step_to_the_diary_not_to_a_comment(self):
        doc = (ROOT / 'AGENTS.md').read_text()
        flow = self.section(doc, '## Delivery flow', '## Cloud setup')
        self.assertNotIn('Each step posts a one-line PR comment', flow)
        self.assertIn('plan note', flow)
        self.assertIn('--kind engine', flow)

    def test_the_storage_section_names_the_adapter_the_registry_selects(self):
        doc = (ROOT / 'docs' / 'process' / 'EVENTS.md').read_text()
        storage = self.section(doc, '## Storage', '### Gate evidence')
        self.assertNotIn('**Events: PR comments.**', storage)
        self.assertIn(f'`{config.get("forge-events.log_adapter")}`', storage)
        self.assertNotIn('control', config.entry('forge-events.log_adapter')['enum'])  # D-300: no double path
        self.assertIn(config.get('forge-events.control_token_env'), storage)
        self.assertIn('service.control_url', storage)
        self.assertIn('/v1/check-run', storage)
        self.assertIn('forge_control.py', storage)
        self.assertIn('D-293', storage)
        self.assertIn('selecting it is refused', storage)

    def test_a_broken_transport_is_never_a_reason_to_comment(self):
        doc = (ROOT / 'docs' / 'process' / 'EVENTS.md').read_text()
        storage = self.section(doc, '## Storage', '### Gate evidence')
        self.assertIn('no events token', storage)
        self.assertIn('unreachable', storage)
        self.assertIn('--kind blocker', storage)


class RegistryProducers(unittest.TestCase):
    def test_every_registry_producer_matches_the_envelope_pattern(self):
        """ENV-FIX-PREMISE-BLAST: premises.producer was 'scripts/premises'; one such event on the repository channel
        stopped every config.get. A producer name in the registry must be one the envelope accepts."""
        pattern = event_contracts.registry().load('envelope.v1.json')['properties']['producer']['pattern']
        names = {name: item['default'] for name, item in config._params().items()
                 if name.rsplit('.', 1)[1].endswith('producer') and isinstance(item.get('default'), str)}
        self.assertIn('premises.producer', names)
        bad = {name: value for name, value in names.items() if not re.match(pattern, value)}
        self.assertEqual(bad, {})


if __name__ == '__main__':
    unittest.main(verbosity=1)
