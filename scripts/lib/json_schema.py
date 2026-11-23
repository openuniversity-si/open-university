"""The single schema language (D-068 (5), D-069 item 2): the JSON Schema draft 2020-12 subset the contracts use.

validate(schema, instance) returns the errors of an instance; check_schema(schema) refuses a keyword outside the
subset, so a contract never relies on a rule this validator would silently skip. compatible(old, new) lists what a
new revision of a schema breaks: an existing version may only add optional fields or widen, and a breaking shape is a
new version file (expand→contract). Standard library only.

One engine, three entry points: validate/check_schema/compatible (the registry and the gate, C0), Registry (files of
one directory with cross-file $ref, kept to the event-contract keywords; the forge_events port, M2) and errors()
(one inline schema; the premise register, P1).
"""
from datetime import datetime
import json
import math
from pathlib import Path
import re

DIALECT = 'https://json-schema.org/draft/2020-12/schema'
EVENT_PAYLOAD_FILE = re.compile(r'^(?P<type>[a-z][a-z-]*(?:\.[a-z][a-z-]*)+)\.v(?P<version>[1-9][0-9]*)\.json$')
ANNOTATIONS = frozenset({'$schema', '$id', '$comment', 'title', 'description', 'default', 'deprecated', 'examples',
                         'readOnly', 'writeOnly'})
APPLICATORS = frozenset({'$defs', '$ref', 'type', 'enum', 'const', 'properties', 'required', 'additionalProperties',
                         'patternProperties', 'propertyNames', 'items', 'minItems', 'maxItems', 'uniqueItems',
                         'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum', 'minLength', 'maxLength',
                         'pattern', 'format', 'allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else'})
KEYWORDS = ANNOTATIONS | APPLICATORS
SUBSCHEMA = ('additionalProperties', 'propertyNames', 'items', 'not', 'if', 'then', 'else')
SUBSCHEMA_MAPS = ('properties', 'patternProperties', '$defs')
SUBSCHEMA_LISTS = ('allOf', 'anyOf', 'oneOf')
TYPES = ('null', 'boolean', 'integer', 'number', 'string', 'array', 'object')
WIDER = {'integer': {'integer', 'number'}}  # a value of the left type is also valid under each right type


class SchemaError(ValueError):
    pass


def json_type(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'integer' if value.is_integer() else 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, dict):
        return 'object'
    raise SchemaError(f'{type(value).__name__} is not a JSON value')


def is_type(value, name):
    actual = json_type(value)
    return actual == name or (name == 'number' and actual == 'integer')


def canonical(value):
    """A JSON value's canonical text: equal values, equal text (1 and 1.0 included)."""
    def norm(item):
        if isinstance(item, float) and item.is_integer():
            return int(item)
        if isinstance(item, list):
            return [norm(each) for each in item]
        if isinstance(item, dict):
            return {key: norm(each) for key, each in item.items()}
        return item
    return json.dumps(norm(value), sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _types(schema):
    declared = schema.get('type')
    return set(declared) if isinstance(declared, list) else {declared} if declared else set(TYPES)


def check_schema(schema, at='#'):
    """Errors of a schema that leaves the subset: an unknown keyword, a bad type name or an unresolved local $ref."""
    errors = []

    def walk(node, path):
        if isinstance(node, bool):
            return
        if not isinstance(node, dict):
            errors.append(f'{path}: a schema is an object or a boolean')
            return
        for key, value in node.items():
            if key.startswith('x-'):
                continue
            if key not in KEYWORDS:
                errors.append(f'{path}: keyword "{key}" is outside the supported JSON Schema subset')
            elif key in SUBSCHEMA:
                walk(value, f'{path}/{key}')
            elif key in SUBSCHEMA_MAPS:
                for name, child in (value or {}).items():
                    walk(child, f'{path}/{key}/{name}')
            elif key in SUBSCHEMA_LISTS:
                for index, child in enumerate(value or []):
                    walk(child, f'{path}/{key}/{index}')
            elif key == 'type':
                names = value if isinstance(value, list) else [value]
                errors.extend(f'{path}/type: "{name}" is not a JSON type' for name in names if name not in TYPES)
            elif key == '$ref' and '://' in str(value):
                errors.append(f'{path}/$ref: remote references are not supported; name a sibling file instead')
            elif key == '$ref' and str(value).startswith('#'):
                try:
                    resolve(schema, value)
                except SchemaError as error:
                    errors.append(f'{path}/$ref: {error}')
            elif key == 'pattern':
                try:
                    re.compile(value)
                except (re.error, TypeError) as error:
                    errors.append(f'{path}/pattern: {error}')
    walk(schema, at)
    return errors


class Document(dict):
    """A schema document that knows how to load its siblings, so a $ref may name another file: 'defs.v1.json#/x'."""

    def __init__(self, content, loader=None):
        super().__init__(content)
        self.loader = loader


def _follow(root, ref):
    """(target, the document it lives in) of a $ref; another file is loaded through the root's loader."""
    file, _, pointer = ref.partition('#')
    if file:
        loader = getattr(root, 'loader', None)
        if loader is None:
            raise SchemaError(f'{ref}: a reference to another file needs a Registry')
        root = loader(file)
    return resolve(root, '#' + pointer), root


def resolve(root, ref):
    """A local reference: "#" or a JSON pointer "#/..." inside the same document."""
    if not isinstance(ref, str) or not ref.startswith('#'):
        raise SchemaError(f'{ref!r} is not a local reference (a Registry resolves another file of its directory)')
    node = root
    for part in [p for p in ref[1:].split('/') if p]:
        part = part.replace('~1', '/').replace('~0', '~')
        if not isinstance(node, dict) or part not in node:
            raise SchemaError(f'{ref} does not resolve')
        node = node[part]
    return node


def _date_time(text):
    try:
        datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        return False
    return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})', text))


FORMATS = {'date-time': _date_time, 'regex': lambda text: _compiles(text)}


def _compiles(text):
    try:
        re.compile(text)
    except re.error:
        return False
    return True


def validate(schema, instance, root=None, path='$'):
    """The errors of instance under schema, each naming the instance path."""
    root = schema if root is None else root
    if schema is True:
        return []
    if schema is False:
        return [f'{path}: no value is allowed here']
    errors = []
    if '$ref' in schema:
        target, target_root = _follow(root, schema['$ref'])
        errors += validate(target, instance, target_root, path)
    if 'type' in schema and not any(is_type(instance, name) for name in _types(schema)):
        return errors + [f'{path}: expected {" or ".join(sorted(_types(schema)))}, got {json_type(instance)}']
    if 'const' in schema and canonical(instance) != canonical(schema['const']):
        errors.append(f'{path}: must equal {canonical(schema["const"])}')
    if 'enum' in schema and canonical(instance) not in {canonical(item) for item in schema['enum']}:
        errors.append(f'{path}: {canonical(instance)} is not one of {canonical(schema["enum"])}')
    kind = json_type(instance)
    if kind in ('integer', 'number'):
        errors += _numeric(schema, instance, path)
    elif kind == 'string':
        errors += _string(schema, instance, path)
    elif kind == 'array':
        errors += _array(schema, instance, root, path)
    elif kind == 'object':
        errors += _object(schema, instance, root, path)
    for child in schema.get('allOf', []):
        errors += validate(child, instance, root, path)
    if 'anyOf' in schema and not any(not validate(child, instance, root, path) for child in schema['anyOf']):
        errors.append(f'{path}: matches none of anyOf')
    if 'oneOf' in schema:
        matched = sum(1 for child in schema['oneOf'] if not validate(child, instance, root, path))
        if matched != 1:
            errors.append(f'{path}: matches {matched} of oneOf, expected exactly one')
    if 'not' in schema and not validate(schema['not'], instance, root, path):
        errors.append(f'{path}: must not match the "not" schema')
    if 'if' in schema:
        branch = 'then' if not validate(schema['if'], instance, root, path) else 'else'
        if branch in schema:
            errors += validate(schema[branch], instance, root, path)
    return errors


def _numeric(schema, value, path):
    errors = []
    if 'minimum' in schema and value < schema['minimum']:
        errors.append(f'{path}: {value} is below the minimum {schema["minimum"]}')
    if 'maximum' in schema and value > schema['maximum']:
        errors.append(f'{path}: {value} is above the maximum {schema["maximum"]}')
    if 'exclusiveMinimum' in schema and value <= schema['exclusiveMinimum']:
        errors.append(f'{path}: {value} must be above {schema["exclusiveMinimum"]}')
    if 'exclusiveMaximum' in schema and value >= schema['exclusiveMaximum']:
        errors.append(f'{path}: {value} must be below {schema["exclusiveMaximum"]}')
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f'{path}: {value} is not a finite number')
    return errors


def _string(schema, value, path):
    errors = []
    if 'minLength' in schema and len(value) < schema['minLength']:
        errors.append(f'{path}: shorter than {schema["minLength"]} characters')
    if 'maxLength' in schema and len(value) > schema['maxLength']:
        errors.append(f'{path}: longer than {schema["maxLength"]} characters')
    if 'pattern' in schema and not re.search(schema['pattern'], value):
        errors.append(f'{path}: {value!r} does not match {schema["pattern"]!r}')
    check = FORMATS.get(schema.get('format'))
    if check and not check(value):
        errors.append(f'{path}: {value!r} is not a valid {schema["format"]}')
    return errors


def _array(schema, value, root, path):
    errors = []
    if 'minItems' in schema and len(value) < schema['minItems']:
        errors.append(f'{path}: fewer than {schema["minItems"]} items')
    if 'maxItems' in schema and len(value) > schema['maxItems']:
        errors.append(f'{path}: more than {schema["maxItems"]} items')
    if schema.get('uniqueItems') and len({canonical(item) for item in value}) != len(value):
        errors.append(f'{path}: items are not unique')
    if 'items' in schema:
        for index, item in enumerate(value):
            errors += validate(schema['items'], item, root, f'{path}[{index}]')
    return errors


def _object(schema, value, root, path):
    errors = []
    properties = schema.get('properties', {})
    patterns = schema.get('patternProperties', {})
    for name in schema.get('required', []):
        if name not in value:
            errors.append(f'{path}: "{name}" is required')
    for name, item in value.items():
        where = f'{path}.{name}'
        if 'propertyNames' in schema:
            errors += [f'{where}: property name {error.split(": ", 1)[1]}'
                       for error in validate(schema['propertyNames'], name, root, where)]
        matched = False
        if name in properties:
            matched = True
            errors += validate(properties[name], item, root, where)
        for pattern, child in patterns.items():
            if re.search(pattern, name):
                matched = True
                errors += validate(child, item, root, where)
        if not matched and 'additionalProperties' in schema:
            extra = schema['additionalProperties']
            if extra is False:
                errors.append(f'{path}: property "{name}" is not allowed')
            else:
                errors += validate(extra, item, root, where)
    return errors


def compatible(old, new, path='#', removal_needs_deprecation=True):
    """What new breaks for data or readers that old allowed: removed or newly required fields, narrowed types,
    enums, ranges, lengths or patterns. Returns a list of reasons; empty means new only adds optional fields or widens.

    A property may leave only after a revision that marked it "deprecated" (expand→contract) when the value travels
    outside the tree (a contract: another party writes the data, and no measurement here can prove it stopped).
    `removal_needs_deprecation=False` is for the registry, whose only readers are source files in this tree: there the
    caller proves that nothing names the key (D-289), so a prior revision buys nothing."""
    old = {} if old is True else old
    new = {} if new is True else new
    if old is False:
        return []
    if new is False:
        return [f'{path}: nothing is allowed any more']
    reasons = []
    old_types, new_types = _types(old), _types(new)
    lost = {name for name in old_types if not ({name} | WIDER.get(name, set())) & new_types}
    if lost:
        reasons.append(f'{path}: type narrowed, {", ".join(sorted(lost))} no longer allowed')
    if 'const' in new and ('const' not in old or canonical(old['const']) != canonical(new['const'])):
        reasons.append(f'{path}: const added or changed')
    if 'enum' in new:
        before = {canonical(item) for item in old['enum']} if 'enum' in old else None
        after = {canonical(item) for item in new['enum']}
        if before is None:
            reasons.append(f'{path}: enum added')
        elif before - after:
            reasons.append(f'{path}: enum narrowed, {", ".join(sorted(before - after))} removed')
    for key, tighter in (('minimum', '>'), ('exclusiveMinimum', '>'), ('minLength', '>'), ('minItems', '>'),
                         ('maximum', '<'), ('exclusiveMaximum', '<'), ('maxLength', '<'), ('maxItems', '<')):
        if key in new and (key not in old or (new[key] > old[key] if tighter == '>' else new[key] < old[key])):
            reasons.append(f'{path}: {key} tightened to {new[key]}')
    if 'pattern' in new and new.get('pattern') != old.get('pattern'):
        reasons.append(f'{path}: pattern added or changed')
    if new.get('uniqueItems') and not old.get('uniqueItems'):
        reasons.append(f'{path}: uniqueItems added')
    if 'format' in new and new.get('format') != old.get('format'):
        reasons.append(f'{path}: format added or changed')
    added_required = set(new.get('required', [])) - set(old.get('required', []))
    if added_required:
        reasons.append(f'{path}: newly required {", ".join(sorted(added_required))}')
    old_props, new_props = old.get('properties', {}), new.get('properties', {})
    for name, child in old_props.items():
        if name not in new_props:
            if removal_needs_deprecation and not (isinstance(child, dict) and child.get('deprecated')):
                reasons.append(f'{path}/properties/{name}: removed without a revision that marked it deprecated')
        else:
            reasons += compatible(child, new_props[name], f'{path}/properties/{name}', removal_needs_deprecation)
    if old.get('additionalProperties', True) is not False:
        closed = new.get('additionalProperties', True) is False
        if closed:
            reasons.append(f'{path}: additionalProperties closed')
    for key in ('items', 'propertyNames'):
        if key in new:
            reasons += compatible(old.get(key, True), new[key], f'{path}/{key}', removal_needs_deprecation)
    if 'additionalProperties' in new and isinstance(new['additionalProperties'], dict):
        reasons += compatible(old.get('additionalProperties', True), new['additionalProperties'],
                              f'{path}/additionalProperties', removal_needs_deprecation)
    for name, child in old.get('$defs', {}).items():
        if name in new.get('$defs', {}):
            reasons += compatible(child, new['$defs'][name], f'{path}/$defs/{name}', removal_needs_deprecation)
        elif removal_needs_deprecation and not (isinstance(child, dict) and child.get('deprecated')):
            reasons.append(f'{path}/$defs/{name}: removed without a revision that marked it deprecated')
    for key in ('allOf', 'anyOf', 'oneOf', 'not', 'if', 'then', 'else', '$ref'):
        if canonical(old.get(key)) != canonical(new.get(key)) and key in new:
            reasons.append(f'{path}: {key} added or changed; compare the shapes by hand or add a new version')
    return reasons


def errors(instance, schema, path='$'):
    """The premise register's entry point (P1): a keyword outside the subset, then every violation, one line each."""
    unsupported = check_schema(schema)
    if unsupported:
        return [f'{path}: {line} (scripts/lib/json_schema.py)' for line in unsupported]
    return validate(schema, instance, path=path)


# The forge_events port's entry point (M2): schemas of one directory, addressed by file name. It validates with the
# engine above and keeps the event contracts to a narrower keyword set (no format, no conditionals): an event payload
# stays checkable by any consumer's validator.
EVENT_KEYWORDS = frozenset({'$schema', '$id', '$comment', 'title', 'description', 'examples', 'default', '$defs',
                            'type', 'enum', 'const', 'properties', 'required', 'additionalProperties', 'items',
                            'minItems', 'maxItems', 'uniqueItems', 'minimum', 'maximum', 'minLength', 'maxLength',
                            'pattern', '$ref', 'oneOf', 'anyOf'})


class ValidationError(ValueError):
    """An instance does not match its schema. The message names the path and the rule."""


def _event_subset(schema, where):
    if isinstance(schema, bool):
        return
    if not isinstance(schema, dict):
        raise SchemaError(f'{where}: a schema must be an object')
    for key, value in schema.items():
        if key.startswith('x-'):
            continue
        if key not in EVENT_KEYWORDS:
            raise SchemaError(f'{where}: keyword {key} is not supported by scripts/lib/json_schema.py for event contracts')
        if key in ('properties', '$defs'):
            for name, sub in value.items():
                _event_subset(sub, f'{where}/{key}/{name}')
        elif key in ('items', 'additionalProperties'):
            _event_subset(value, f'{where}/{key}')
        elif key in ('oneOf', 'anyOf'):
            for index, sub in enumerate(value):
                _event_subset(sub, f'{where}/{key}/{index}')


class Registry:
    """Schemas of one directory, addressed by file name; a $ref is '<file>#/<pointer>' or '#/<pointer>'."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self._cache = {}

    def load(self, name):
        if name not in self._cache:
            path = self.directory / name
            if path.parent != self.directory or not path.is_file():
                raise SchemaError(f'unknown schema {name}')
            schema = json.loads(path.read_text(encoding='utf-8'))
            if schema.get('$schema') != DIALECT:
                raise SchemaError(f'{name}: $schema must be {DIALECT}')
            _event_subset(schema, name)
            self._cache[name] = Document(schema, self.load)
        return self._cache[name]

    def validate(self, instance, name):
        problems = validate(self.load(name), instance)
        if problems:
            raise ValidationError(problems[0])
