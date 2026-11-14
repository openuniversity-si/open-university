"""The single schema language (D-068 (5), D-069 item 2): the validator, the subset guard and the compatibility check.

No network, no clock.
"""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts' / 'lib'))
import json_schema  # noqa: E402

META = json.loads((ROOT / 'contracts/config/registry.v1.json').read_text())


def registry(**parameters):
    return {'$schema': json_schema.DIALECT, '$id': 'config/registry/train.json', 'x-owner': 'train',
            'x-schema-version': 1, 'type': 'object', 'additionalProperties': False, 'properties': parameters}


BATCH = {'type': 'integer', 'default': 8, 'minimum': 1, 'x-unit': 'count', 'description': 'PRs per batch.',
         'x-readers': []}


class Validate(unittest.TestCase):
    def test_types_and_ranges(self):
        schema = {'type': 'integer', 'minimum': 1, 'maximum': 64}
        self.assertEqual(json_schema.validate(schema, 8), [])
        self.assertIn('below the minimum', json_schema.validate(schema, 0)[0])
        self.assertIn('above the maximum', json_schema.validate(schema, 65)[0])
        self.assertIn('expected integer', json_schema.validate(schema, True)[0])
        self.assertIn('expected integer', json_schema.validate(schema, 1.5)[0])
        self.assertEqual(json_schema.validate({'type': 'number'}, 3), [])

    def test_objects_arrays_and_strings(self):
        schema = {'type': 'object', 'required': ['a'], 'additionalProperties': False,
                  'properties': {'a': {'type': 'array', 'items': {'type': 'string', 'pattern': '^[a-z]+$'},
                                       'uniqueItems': True, 'maxItems': 2}}}
        self.assertEqual(json_schema.validate(schema, {'a': ['x', 'y']}), [])
        errors = json_schema.validate(schema, {'a': ['x', 'x', 'Y'], 'b': 1})
        self.assertTrue(any('not unique' in error for error in errors))
        self.assertTrue(any('more than 2' in error for error in errors))
        self.assertTrue(any('$.a[2]' in error for error in errors))
        self.assertTrue(any('"b" is not allowed' in error for error in errors))
        self.assertIn('"a" is required', json_schema.validate(schema, {})[0])

    def test_refs_enum_const_and_conditionals(self):
        schema = {'$defs': {'level': {'enum': ['low', 'high']}}, 'type': 'object',
                  'properties': {'level': {'$ref': '#/$defs/level'}, 'kind': {'const': 'x'}},
                  'if': {'properties': {'level': {'const': 'high'}}}, 'then': {'required': ['kind']}}
        self.assertEqual(json_schema.validate(schema, {'level': 'low'}), [])
        self.assertIn('"kind" is required', json_schema.validate(schema, {'level': 'high'})[0])
        self.assertIn('is not one of', json_schema.validate(schema, {'level': 'mid'})[0])
        self.assertIn('must equal', json_schema.validate(schema, {'kind': 'y'})[0])

    def test_date_time_format(self):
        schema = {'type': 'string', 'format': 'date-time'}
        self.assertEqual(json_schema.validate(schema, '2026-10-26T20:51:00Z'), [])
        self.assertEqual(json_schema.validate(schema, '2026-10-26T17:51:00-03:00'), [])
        self.assertTrue(json_schema.validate(schema, '2026-10-26 17:51'))


class Subset(unittest.TestCase):
    def test_a_keyword_outside_the_subset_is_refused(self):
        errors = json_schema.check_schema({'type': 'object', 'dependentRequired': {}, 'x-owner': 'ok'})
        self.assertEqual(len(errors), 1)
        self.assertIn('dependentRequired', errors[0])

    def test_remote_references_and_bad_types_are_refused(self):
        self.assertTrue(json_schema.check_schema({'$ref': 'https://example.invalid/s.json'}))
        self.assertTrue(json_schema.check_schema({'type': 'float'}))
        self.assertTrue(json_schema.check_schema({'$ref': '#/$defs/missing'}))

    def test_every_contract_stays_inside_the_subset(self):
        for path in sorted((ROOT / 'contracts').rglob('*.json')):
            document = json.loads(path.read_text())
            if isinstance(document, list):
                continue  # contracts/events/schemas.lock.json: the hashes of the event schemas (M2), not a schema
            with self.subTest(path=path.name):
                self.assertEqual(json_schema.check_schema(document), [])


class MetaSchema(unittest.TestCase):
    def test_a_registry_file_in_the_shared_format_validates(self):
        self.assertEqual(json_schema.validate(META, registry(**{'train.batch_size': BATCH})), [])

    def test_a_parameter_without_unit_readers_or_description_is_refused(self):
        bare = {'type': 'integer', 'default': 8}
        errors = json_schema.validate(META, registry(**{'train.batch_size': bare}))
        for field in ('x-unit', 'description', 'x-readers'):
            self.assertTrue(any(f'"{field}" is required' in error for error in errors), field)

    def test_names_carry_the_owner_and_snake_case(self):
        errors = json_schema.validate(META, registry(**{'train.BatchSize': BATCH, 'batch_size': BATCH}))
        self.assertEqual(sum('property name' in error for error in errors), 2)

    def test_a_flag_is_boolean_and_an_object_is_locale_text(self):
        flag = dict(BATCH, **{'x-flag': True})
        self.assertTrue(json_schema.validate(META, registry(**{'train.enabled': flag})))
        text = {'type': 'object', 'default': {'en': 'Hi'}, 'x-unit': 'text', 'description': 'A greeting.',
                'x-readers': [], 'propertyNames': {'pattern': '^[a-z]{2}$'},
                'additionalProperties': {'type': 'string'}, 'required': ['en']}
        self.assertTrue(json_schema.validate(META, registry(**{'train.greeting': text})))
        self.assertEqual(json_schema.validate(META, registry(**{'train.greeting': dict(text, **{'x-text': True})})), [])

    def test_an_unknown_parameter_keyword_is_refused(self):
        errors = json_schema.validate(META, registry(**{'train.batch_size': dict(BATCH, fallback=8)}))
        self.assertTrue(any('"fallback" is not allowed' in error for error in errors))


class Compatible(unittest.TestCase):
    OLD = {'type': 'object', 'required': ['name'],
           'properties': {'name': {'type': 'string'}, 'size': {'type': 'integer', 'minimum': 1, 'maximum': 10},
                          'kind': {'enum': ['a', 'b']}, 'old': {'type': 'string', 'deprecated': True}}}

    def test_adding_an_optional_field_or_widening_is_compatible(self):
        new = json.loads(json.dumps(self.OLD))
        new['properties']['extra'] = {'type': 'string'}
        new['properties']['size'] = {'type': 'number', 'minimum': 0, 'maximum': 20}
        new['properties']['kind'] = {'enum': ['a', 'b', 'c']}
        self.assertEqual(json_schema.compatible(self.OLD, new), [])

    def test_removing_a_deprecated_field_is_the_contract_step(self):
        new = json.loads(json.dumps(self.OLD))
        del new['properties']['old']
        self.assertEqual(json_schema.compatible(self.OLD, new), [])

    def test_breaking_changes_are_named(self):
        new = json.loads(json.dumps(self.OLD))
        del new['properties']['name']
        new['required'] = ['name', 'size']
        new['properties']['size'] = {'type': 'string', 'maximum': 5}
        new['properties']['kind'] = {'enum': ['a']}
        new['additionalProperties'] = False
        reasons = '\n'.join(json_schema.compatible(self.OLD, new))
        for expected in ('name: removed without a revision that marked it deprecated', 'newly required size',
                         'size: type narrowed', 'enum narrowed', 'additionalProperties closed'):
            self.assertIn(expected, reasons)

    def test_tightening_a_range_breaks(self):
        old = {'type': 'integer', 'minimum': 1}
        self.assertTrue(json_schema.compatible(old, {'type': 'integer', 'minimum': 2}))
        self.assertTrue(json_schema.compatible(old, {'type': 'integer', 'minimum': 1, 'maximum': 9}))
        self.assertEqual(json_schema.compatible(old, {'type': 'integer', 'minimum': 0}), [])


if __name__ == '__main__':
    unittest.main()
