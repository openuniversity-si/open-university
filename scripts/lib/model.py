"""The engineering model (PADRAO-DEV, docs/programs/padrao-dev/solucao.md): one graph of typed objects and typed links.

The metamodel is data in config/model/, one file per object type (types/), link type (links/), system (systems/) and
inventory source (inventory/), plus the conformance scale (conformance.json), each validated against its contract in
contracts/model/. The objects are read from where each system keeps them; F1a reads the ones that exist today:

  D     docs/domain/decisions/D-NNN.md (state accepted; its `proof:` file verifies it) and the older rows of
        docs/domain/DECISIONS.md (accepted, proof in prose)
  UNIT  units/<id>/unit.json (active; `requires` are depends-on links)
  TEST  scripts/tests/*.test.sh and the test files under scripts/tests/ (active)

  scripts/model check [--strict]   errors (exit 1) for a metamodel or object that breaks the model; warnings (a link to an
                                   object that does not exist, such as a decision proof that is gone) are counted, and
                                   are errors only with --strict
  scripts/model show <id>          one object: type, state, source, and its links out and in
  scripts/model seed-rules         writes config/standard/rules/<id>.json for every refusal, gate stage, D-069 principle
                                   and the method that has no rule yet (never rewrites a rule)
  scripts/model measure [--json F] the main metric (the share of active requirements whose chain is verified end to
                                   end), the requirement inventory, and each system's objects and calculated conformance

A requirement's chain is verified when an architecture element satisfies it, a unit realizes that element, a test
verifies the requirement, and a validation validates it or the need it derives from. An object is conformant when it
breaks no check and every coverage rule of its type (`covered_by`) holds; a system's conformance is the share of its
objects that are conformant, rated on the scale.
"""
import argparse
import glob as globbing
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json_schema  # noqa: E402

MODEL_DIR = 'config/model'
CONTRACTS_DIR = 'contracts/model'
KINDS = {'types': 'type', 'links': 'link', 'systems': 'system', 'inventory': 'inventory'}
KEY = {'types': 'id', 'links': 'name', 'systems': 'id', 'inventory': 'id'}
DECISION_RECORDS = 'docs/domain/decisions/D-*.md'
DECISION_TABLE = 'docs/domain/DECISIONS.md'
DECISION_ROW = re.compile(r'^\| (D-[0-9]+) ', re.MULTILINE)
FRONT = re.compile(r'^---\n(.*?)\n---\n', re.DOTALL)
UNIT_MANIFESTS = 'units/*/unit.json'
RULES = 'config/standard/rules/*.json'
COVERS = 'scripts/tests/covers/*.json'
GATE_STAGES = 'scripts/lib/gate-stages.json'
TEST_GLOBS = ('scripts/tests/*.test.sh', 'scripts/tests/**/test_*.py')


class ModelError(ValueError):
    pass


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ModelError(f'{path}: {error}') from None


def fingerprint(text):
    """The content fingerprint of an object's source, which a link records to tell when its target changed."""
    return hashlib.sha256(text.encode()).hexdigest()[:len('0123456789ab')]


def metamodel(root=ROOT):
    """{types, links, systems, inventory, scale, errors}: the metamodel files, each checked against its contract."""
    root = Path(root)
    found = {'errors': []}
    for folder, contract in KINDS.items():
        schema = _read_json(root / CONTRACTS_DIR / f'{contract}.v1.json')
        items = {}
        for path in sorted((root / MODEL_DIR / folder).glob('*.json')):
            name = path.relative_to(root).as_posix()
            item = _read_json(path)
            problems = json_schema.validate(schema, item)
            found['errors'] += [f'{name}: {problem}' for problem in problems]
            key = item.get(KEY[folder]) if isinstance(item, dict) else None
            if key != path.stem:
                found['errors'].append(f'{name}: its {KEY[folder]} must equal the file name {path.stem}')
            items[path.stem] = item
        found[folder] = items
    scale = _read_json(root / MODEL_DIR / 'conformance.json')
    found['errors'] += [f'{MODEL_DIR}/conformance.json: {problem}'
                        for problem in json_schema.validate(_read_json(root / CONTRACTS_DIR / 'conformance.v1.json'), scale)]
    found['scale'] = scale.get('scale', [])
    found['errors'] += cross_check(found)
    return found


def cross_check(meta):
    """What the contracts cannot state: every name a metamodel file uses exists."""
    errors = []
    types, links, systems = meta['types'], meta['links'], meta['systems']
    for name, item in types.items():
        if item.get('system') not in systems:
            errors.append(f'type {name}: system {item.get("system")} does not exist')
        states = set(item.get('states', []))
        for field in ('derived_states', 'inactive_states'):
            extra = sorted(set(item.get(field, [])) - states)
            if extra:
                errors.append(f'type {name}: {field} {", ".join(extra)} are not states of the type')
        for link_name in item.get('must_link', []):
            if link_name not in links:
                errors.append(f'type {name}: must_link {link_name} does not exist')
            elif name not in links[link_name]['from']:
                errors.append(f'type {name}: a {name} cannot hold a {link_name} link')
        for rule in item.get('covered_by', []):
            link = links.get(rule['link'])
            if link is None:
                errors.append(f'type {name}: covered_by link {rule["link"]} does not exist')
            elif rule['type'] not in link['from'] or name not in link['to']:
                errors.append(f'type {name}: link {rule["link"]} does not go from {rule["type"]} to {name}')
    for name, link in links.items():
        unknown = sorted((set(link.get('from', [])) | set(link.get('to', []))) - set(types))
        if unknown:
            errors.append(f'link {name}: types {", ".join(unknown)} do not exist')
    for name, source in meta['inventory'].items():
        unknown = sorted(set(source.get('becomes', [])) - set(types))
        if unknown:
            errors.append(f'inventory {name}: types {", ".join(unknown)} do not exist')
    homeless = sorted(set(systems) - {item.get('system') for item in types.values()})
    if homeless:
        errors.append(f'systems {", ".join(homeless)} manage no object type')
    return errors


def _obj(id, type, state, source, text, links=()):
    return {'id': id, 'type': type, 'state': state, 'source': source, 'fingerprint': fingerprint(text),
            'links': [dict(link) for link in links]}


def read_decisions(root):
    objects, seen = [], set()
    for path in sorted(Path(root).glob(DECISION_RECORDS)):
        text = path.read_text()
        head = FRONT.match(text)
        fields = dict(line.split(':', 1) for line in head.group(1).splitlines() if ':' in line) if head else {}
        number = fields.get('number', path.stem).strip()
        seen.add(number)
        objects.append(_obj(number, 'D', 'accepted', path.relative_to(root).as_posix(), text))
        proof = fields.get('proof', '').strip().strip('`')
        if proof:
            objects.append({'id': f'TEST:{proof}', 'type': 'TEST', 'state': 'active', 'source': proof, 'claimed': True,
                            'fingerprint': None, 'links': [{'type': 'verifies', 'target': number}]})
    table = Path(root) / DECISION_TABLE
    if table.is_file():
        text = table.read_text()
        for number in DECISION_ROW.findall(text):
            if number not in seen:
                seen.add(number)
                objects.append(_obj(number, 'D', 'accepted', DECISION_TABLE, number))
    return objects


def read_units(root):
    objects = []
    for path in sorted(Path(root).glob(UNIT_MANIFESTS)):
        text = path.read_text()
        manifest = json.loads(text)
        links = [{'type': 'depends-on', 'target': f'UNIT:{name}'} for name in sorted(manifest.get('requires') or {})]
        objects.append(_obj(f'UNIT:{manifest["id"]}', 'UNIT', 'active', path.relative_to(root).as_posix(), text, links))
    return objects


def read_tests(root):
    root = Path(root)
    paths = sorted({Path(found) for pattern in TEST_GLOBS for found in globbing.glob(str(root / pattern), recursive=True)})
    return [_obj(f'TEST:{path.relative_to(root).as_posix()}', 'TEST', 'active', path.relative_to(root).as_posix(),
                 path.read_text(errors='replace')) for path in paths if path.is_file()]


def _covers(root):
    """[(test script, covers patterns)] of every covers manifest."""
    found = []
    for path in sorted(Path(root).glob(COVERS)):
        manifest = _read_json(path)
        found.append((manifest['script'], [manifest['script'], *manifest.get('covers', [])]))
    return found


def check_file(rule):
    """The file a rule's check lives in, or None for a gate stage."""
    kind, ref = rule['check']['kind'], rule['check']['ref']
    if kind == 'function':
        return ref.split(':', 1)[0]
    if kind in ('test', 'judgment'):
        return ref.split('#', 1)[0]
    return None


def read_rules(root):
    """The rules of the standard (STD). Each is validated against contracts/model/rule.v1.json; its basis becomes
    justified-by links, and every test whose covers names the file of an executable check (a function or a test, never a
    judgment's document) verifies it (derived, never written)."""
    from gate_areas import glob_match
    root = Path(root)
    schema = _read_json(root / CONTRACTS_DIR / 'rule.v1.json')
    manifests = _covers(root)
    found = []
    for path in sorted(root.glob(RULES)):
        text = path.read_text()
        rule = _read_json(path)
        problems = [f'{problem}' for problem in json_schema.validate(schema, rule)]
        if isinstance(rule, dict) and rule.get('id') != path.stem:
            problems.append(f'its id must equal the file name {path.stem}')
        if problems:
            found.append({**_obj(f'STD:{path.stem}', 'STD', 'draft', path.relative_to(root).as_posix(), text),
                          'problems': problems})
            continue
        links = [{'type': 'justified-by', 'target': number} for number in rule.get('basis', [])]
        item = _obj(rule['id'], 'STD', rule['state'], path.relative_to(root).as_posix(), text, links)
        item['rule'] = rule
        found.append(item)
        target = check_file(rule) if rule['check']['kind'] in ('function', 'test') else None
        for script, patterns in manifests if target else []:
            if any(glob_match(target, pattern) for pattern in patterns):
                found.append({'id': f'TEST:{script}', 'type': 'TEST', 'state': 'active', 'source': script, 'claimed': True,
                              'fingerprint': None, 'links': [{'type': 'verifies', 'target': rule['id']}]})
    return found


def discovered_stops(root):
    """Every `<file>:<function>` that refuses, as scripts/rule finds them (rules.stop_patterns)."""
    import config
    import rule_registry
    return rule_registry.discovered(Path(root), config.get('rules.stop_patterns'))


def gate_stages(root):
    path = Path(root) / GATE_STAGES
    return sorted(_read_json(path).get('stages', {})) if path.is_file() else []


def rule_findings(found, root, stops=None, stages=None):
    """Warnings of the standard: a refusal or a gate stage with no rule, a rule whose check does not exist, a rule with
    no basis, a rule in warning with no deadline."""
    root = Path(root)
    rules = [item for item in found.values() if item['type'] == 'STD' and 'rule' in item]
    refs = {(item['rule']['check']['kind'], item['rule']['check']['ref']) for item in rules}
    stops = discovered_stops(root) if stops is None else stops
    stages = gate_stages(root) if stages is None else stages
    warnings = [f'{stop}: a refusal with no rule of the standard' for stop in stops if ('function', stop) not in refs]
    warnings += [f'gate stage {stage}: a stage with no rule of the standard' for stage in stages
                 if ('gate-stage', stage) not in refs]
    for item in rules:
        rule = item['rule']
        kind, ref = rule['check']['kind'], rule['check']['ref']
        target = check_file(rule)
        if kind == 'gate-stage' and ref not in stages:
            warnings.append(f'{item["id"]}: gate stage {ref} does not exist')
        elif target and not (root / target).is_file():
            warnings.append(f'{item["id"]}: its check {ref} does not exist')
        elif kind == 'function' and not re.search(rf'^\s*def {re.escape(ref.split(":", 1)[1])}\(',
                                                  (root / target).read_text(), re.MULTILINE):
            warnings.append(f'{item["id"]}: function {ref} does not exist')
        if not rule.get('basis'):
            warnings.append(f'{item["id"]}: no decision justifies it (basis)')
        if rule['state'] == 'warning' and not rule.get('deadline'):
            warnings.append(f'{item["id"]}: in warning with no deadline')
    return warnings


PRINCIPLES = 'docs/process/principles/D-069.md'
PRINCIPLE = re.compile(r'^### ([0-9]+)\. (.+)$', re.MULTILINE)
METHOD = 'docs/padrao/METODO.md'
VERSION_BASIS = {'v8': 'D-115'}  # the decision that made each version of the Padrão (docs/padrao/README.md)
SEED_NOTE = 'Seeded by scripts/model seed-rules (PADRAO-DEV F1b); its statement, basis and types are to be reviewed.'


def _slug(text):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')


def _docstring(path, function):
    """A function's whole docstring, or ''."""
    import ast
    try:
        tree = ast.parse(Path(path).read_text())
    except (OSError, SyntaxError):
        return ''
    return next((ast.get_docstring(node) or '' for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == function), '')


def _docline(path, function):
    """The first sentence of a function's docstring, or ''."""
    import ast
    try:
        tree = ast.parse(Path(path).read_text())
    except (OSError, SyntaxError):
        return ''
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function:
            doc = (ast.get_docstring(node) or '').strip().split('\n\n', 1)[0].replace('\n', ' ')
            return doc.split('. ', 1)[0].rstrip('.') + '.' if doc else ''
    return ''


def seeds(root, stops=None, stages=None):
    """{rule id: rule} for every refusal, gate stage, D-069 principle and the method, the catalog's first content."""
    root = Path(root)
    stops = discovered_stops(root) if stops is None else stops
    stages = gate_stages(root) if stages is None else stages
    base = {'owner': 'administration', 'applies_to': ['CHG'], 'note': SEED_NOTE}
    found = {}
    for stop in stops:
        path, function = stop.split(':', 1)
        doc = _docline(root / path, function)
        found[f'STD-{_slug(Path(path).stem)}-{_slug(function)}'] = {
            **base, 'statement': doc or f'A change passes the refusing check {function} of {path}.',
            'state': 'blocking', 'check': {'kind': 'function', 'ref': stop},
            'basis': sorted(set(re.findall(r'\bD-[0-9]+\b', _docstring(root / path, function))),
                            key=lambda number: int(number[len('D-'):]))}
    for stage in stages:
        found[f'STD-gate-{_slug(stage)}'] = {
            **base, 'statement': f'A change passes the gate stage "{stage}" on its exact head before it merges.',
            'state': 'blocking', 'check': {'kind': 'gate-stage', 'ref': stage}, 'basis': ['D-314']}
    text = (root / PRINCIPLES).read_text() if (root / PRINCIPLES).is_file() else ''
    for number, title in PRINCIPLE.findall(text.split('\n## Shared contract', 1)[0]):
        found[f'STD-d069-{number}-{_slug(title)}'] = {
            **base, 'statement': f'{title.rstrip(".")} (D-069 principle {number}).', 'state': 'draft',
            'check': {'kind': 'judgment', 'ref': f'{PRINCIPLES}#{number}'}, 'basis': ['D-069']}
    import config
    current = config.get('coordinator.padrao_version')
    listing = root / 'docs' / 'padrao' / current / 'padrao.json'
    for rule in (_read_json(listing).get('rules', []) if listing.is_file() else []):
        found[f'STD-padrao-{rule["id"]}'] = {
            **base, 'applies_to': ['WORK'], 'state': 'draft', 'basis': [VERSION_BASIS.get(current, '')] if VERSION_BASIS.get(current) else [],
            'statement': f'The agent follows the Padrão {current} rule {rule["id"]} ({listing.parent.relative_to(root).as_posix()}/{rule["file"]}).',
            'check': {'kind': 'judgment', 'ref': f'{listing.parent.relative_to(root).as_posix()}/{rule["file"]}'}}
    if (root / METHOD).is_file():
        found['STD-metodo'] = {**base, 'applies_to': ['WORK'], 'state': 'draft', 'basis': [],
                               'statement': 'Work follows the management method: program and project by PDCA, process and '
                                            'operation by SDCA, one retrospective at every level.',
                               'check': {'kind': 'judgment', 'ref': METHOD}}
    return {id: {'id': id, **{key: rule[key] for key in ('statement', 'state', 'owner', 'applies_to', 'check', 'basis',
                                                         'note')}}
            for id, rule in found.items()}


def seed_rules(root=ROOT, stops=None, stages=None):
    """Writes the seed of every rule that has no file yet; never rewrites one. Returns the paths written."""
    written = []
    for id, rule in sorted(seeds(root, stops, stages).items()):
        path = Path(root) / RULES.replace('*', id)
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rule, indent=2, ensure_ascii=False) + '\n')
        written.append(path.relative_to(root).as_posix())
    return written


CHALLENGES = 'docs/process/rule-challenges/RC-*.md'
CHALLENGE_STATE = {'open': 'open', 'changed': 'applied', 'kept': 'rejected', 'rejected': 'rejected'}
FIELD = re.compile(r'^- ([A-Za-z]+): (.*)$', re.MULTILINE)
PROPOSALS = 'config/standard/proposals/*.json'
VERSION_FOLDERS = 'docs/padrao/v*/padrao.json'
VERSIONS = 'config/standard/versions/*.json'
TAILORING = 'config/standard/tailoring/*.json'


def _declared(root, pattern, contract, kind, links_of):
    """Objects of one kind read from one file each, validated against their contract."""
    root = Path(root)
    schema = _read_json(root / CONTRACTS_DIR / contract)
    found = []
    for path in sorted(root.glob(pattern)):
        text = path.read_text()
        body = _read_json(path)
        problems = list(json_schema.validate(schema, body))
        if isinstance(body, dict) and body.get('id') != path.stem:
            problems.append(f'its id must equal the file name {path.stem}')
        if problems:
            found.append({**_obj(f'{kind}:{path.stem}', kind, body.get('state', '') if isinstance(body, dict) else '',
                                 path.relative_to(root).as_posix(), text), 'problems': problems})
            continue
        item = _obj(body['id'], kind, body['state'], path.relative_to(root).as_posix(), text, links_of(body))
        item['body'] = body
        found.append(item)
    return found


def read_proposals(root):
    """Proposals to change the standard (PROP): the rule challenges where they are, and the proposal files."""
    root = Path(root)
    found = []
    for path in sorted(root.glob(CHALLENGES)):
        text = path.read_text()
        fields = {key.lower(): value.strip() for key, value in FIELD.findall(text)}
        state = CHALLENGE_STATE.get(fields.get('status', '').lower(), fields.get('status', '').lower())
        decided = fields.get('d', 'none')
        links = [{'type': 'decided-by', 'target': decided}] if re.fullmatch(r'D-[0-9]+', decided) else []
        item = _obj(f'PROP-{path.stem}', 'PROP', state, path.relative_to(root).as_posix(), text, links)
        item['body'] = {'state': state, **({'decided_by': decided} if links else {})}
        found.append(item)
    found += _declared(root, PROPOSALS, 'proposal.v1.json', 'PROP', lambda body: [
        *({'type': 'changes', 'target': target} for target in body['changes']),
        *([{'type': 'decided-by', 'target': body['decided_by']}] if body.get('decided_by') else [])])
    return found


def read_versions(root):
    """Versions of the standard (VER): every docs/padrao/v<N>/ folder (the one coordinator.padrao_version names is
    effective, the older ones superseded, a newer one a draft) and the version files. The effective or draft
    version of a folder contains the rules its padrao.json lists; a version file with `contains: catalog` contains
    every rule of the catalog that is not replaced."""
    import config
    root = Path(root)
    current = config.get('coordinator.padrao_version')
    number = lambda name: int(name.lstrip('v') or 0)
    rules = {item['id']: item for item in read_rules(root) if item['type'] == 'STD' and 'rule' in item}
    found = []
    for path in sorted(root.glob(VERSION_FOLDERS), key=lambda found_path: number(found_path.parent.name)):
        name = path.parent.name
        state = 'effective' if name == current else 'superseded' if number(name) < number(current) else 'draft'
        listed = [rule['id'] for rule in _read_json(path).get('rules', [])]
        links = [{'type': 'contains', 'target': f'STD-padrao-{id}'} for id in listed] if state != 'superseded' else []
        found.append(_obj(f'VER-{name}', 'VER', state, path.relative_to(root).as_posix(), path.read_text(), links))
    def contained(body):
        links = [{'type': 'contains', 'target': id} for id, item in sorted(rules.items()) if item['state'] != 'replaced']
        return links + ([{'type': 'supersedes', 'target': body['supersedes']}] if body.get('supersedes') else [])
    return found + _declared(root, VERSIONS, 'version.v1.json', 'VER', contained)


def read_tailoring(root):
    return _declared(root, TAILORING, 'tailoring.v1.json', 'TAIL', lambda body: [
        {'type': 'exempts', 'target': body['exempts']}, {'type': 'authorized-by', 'target': body['authorized_by']}])


def management_findings(found, today):
    """Warnings of the standard's management: an open proposal with no deadline or past it, a decided or applied
    proposal with no decision, an active exemption past its validity; an error for more than one effective version."""
    warnings, errors = [], []
    for item in found.values():
        body = item.get('body', {})
        if item['type'] == 'PROP' and item['state'] in ('open', 'warning'):
            if not body.get('deadline'):
                warnings.append(f'{item["id"]}: an open proposal with no deadline')
            elif body['deadline'] < today:
                warnings.append(f'{item["id"]}: past its deadline {body["deadline"]}')
        if item['type'] == 'PROP' and item['state'] in ('decided', 'applied') and not body.get('decided_by'):
            warnings.append(f'{item["id"]}: {item["state"]} with no decision')
        if item['type'] == 'TAIL' and item['state'] == 'active' and body.get('valid_until', today) < today:
            warnings.append(f'{item["id"]}: active past its validity {body["valid_until"]}')
    effective = sorted(id for id, item in found.items() if item['type'] == 'VER' and item['state'] == 'effective')
    if len(effective) > 1:
        errors.append(f'{", ".join(effective)}: more than one effective version of the standard')
    return errors, warnings


INTENT = 'config/intent/*.json'
REQUIREMENTS = 'config/requirements/REQ-*.json'
IMPORTS = 'config/requirements/imports/*.json'


def read_intent(root):
    """Intentions (INT) and needs (NEED), one file each; a need refines intentions."""
    root = Path(root)
    schema = _read_json(root / CONTRACTS_DIR / 'intent.v1.json')
    found = []
    for path in sorted(root.glob(INTENT)):
        body = _read_json(path)
        kind = path.stem.split('-', 1)[0]
        problems = list(json_schema.validate(schema, body))
        if isinstance(body, dict) and body.get('id') != path.stem:
            problems.append(f'its id must equal the file name {path.stem}')
        links = [{'type': 'refines', 'target': target} for target in body.get('refines', [])] if not problems else []
        item = _obj(path.stem, kind, body.get('state', '') if isinstance(body, dict) else '',
                    path.relative_to(root).as_posix(), path.read_text(), links)
        item['body'] = body
        if problems:
            item['problems'] = problems
        found.append(item)
    return found


def _requirement_links(body):
    return [*({'type': 'derives-from', 'target': target} for target in body.get('derives_from', [])),
            *({'type': 'justified-by', 'target': number} for number in body.get('basis', []))]


def source_entries(root, source):
    """{id: (statement, path)} of one inventory source: the matching line, the registry key's description, or the
    first line of the file."""
    root = Path(root)
    found = {}
    for part in source['parts']:
        for path in sorted(root.glob(part['glob'])):
            name = path.relative_to(root).as_posix()
            if part['kind'] == 'files':
                found.setdefault(name, (path.read_text().strip().split('\n', 1)[0].lstrip('# '), name))
            elif part['kind'] == 'filename':
                match = re.search(part['pattern'], path.name)
                if match:
                    found.setdefault(match.group(1), (path.read_text().strip().split('\n', 1)[0].lstrip('# '), name))
            elif part['kind'] == 'content':
                for line in path.read_text().splitlines():
                    for match in re.findall(part['pattern'], line):
                        found.setdefault(match, (line.strip().lstrip('-|* ').strip(), name))
            elif part['kind'] == 'registry':
                for key, spec in _read_json(path).get('properties', {}).items():
                    if not part.get('pattern') or re.search(part['pattern'], key):
                        found.setdefault(key, (spec.get('description', key), name))
    return found


def read_requirements(root):
    """Requirements (REQ): the files of config/requirements/, and the requirements of every inventory source an
    import file names, read where they are (one REQ per source id, its statement taken from the source)."""
    root = Path(root)
    found = _declared(root, REQUIREMENTS, 'requirement.v1.json', 'REQ', _requirement_links)
    schema = _read_json(root / CONTRACTS_DIR / 'import.v1.json')
    for path in sorted(root.glob(IMPORTS)):
        body = _read_json(path)
        problems = list(json_schema.validate(schema, body))
        source_path = root / MODEL_DIR / 'inventory' / f'{path.stem}.json'
        if body.get('id') != path.stem or not source_path.is_file():
            problems.append(f'names no inventory source {path.stem}')
        if problems:
            found.append({**_obj(f'REQ:{path.stem}', 'REQ', 'draft', path.relative_to(root).as_posix(), path.read_text()),
                          'problems': problems})
            continue
        needs = body.get('derives_from', {})
        for source_id, (statement, where) in sorted(source_entries(root, _read_json(source_path)).items()):
            need = needs.get(source_id, needs.get('*'))
            fields = {'type': body['type'], 'statement': statement, 'state': body['state'], 'owner': body['owner'],
                      'source': where, **({'retired_by': body['retired_by']} if body.get('retired_by') else {}),
                      **({'derives_from': [need]} if need else {})}
            item = _obj(f'REQ-{path.stem}-{_slug(source_id)}', 'REQ', body['state'], where, statement,
                        _requirement_links(fields))
            item.update(body=fields, source_id=source_id)
            found.append(item)
    return found


def requirement_findings(found):
    """Warnings of the requirements: a retired requirement with no decision that retired it, an active one that
    derives from no need."""
    warnings = []
    for item in found.values():
        body = item.get('body', {})
        if item['type'] != 'REQ' or 'type' not in body:
            continue
        if item['state'] in ('superseded', 'obsolete') and not body.get('retired_by'):
            warnings.append(f'{item["id"]}: {item["state"]} with no decision that retired it')
        if item['state'] not in ('superseded', 'obsolete') and not body.get('derives_from'):
            warnings.append(f'{item["id"]}: derives from no need')
    return warnings


READERS = (read_decisions, read_units, read_tests, read_rules, read_proposals, read_versions, read_tailoring,
           read_intent, read_requirements)


def objects(root=ROOT, readers=READERS):
    """Every object the readers find, by id. A decision's proof becomes a link on the test it names; a proof that names
    no test file stays as a test object of its own, claimed but without a source, so the link to it can be judged."""
    found = {}
    for reader in readers:
        for item in reader(root):
            current = found.get(item['id'])
            if current is None:
                found[item['id']] = item
            elif current.get('claimed') and not item.get('claimed'):
                found[item['id']] = {**item, 'links': current['links'] + item['links']}
            else:
                current['links'] += item['links']
    return found


def check(meta, found, root=None, today=None):
    """(errors, warnings) of the objects against the metamodel; with `root`, also the warnings of the standard."""
    errors, warnings = [], []
    if root is not None:
        warnings += rule_findings(found, root)
        warnings += requirement_findings(found)
        managed_errors, managed_warnings = management_findings(found, today or utc_today())
        errors += managed_errors
        warnings += managed_warnings
    for id, item in sorted(found.items()):
        kind = meta['types'].get(item['type'])
        if kind is None:
            errors.append(f'{id}: type {item["type"]} does not exist')
            continue
        errors += [f'{id}: {problem}' for problem in item.get('problems', [])]
        if item['state'] not in kind['states']:
            errors.append(f'{id}: state {item["state"]} is not a state of {item["type"]}')
        if item.get('claimed') and item.get('fingerprint') is None:
            warnings.append(f'{id}: named by a link but no such file exists ({", ".join(link["target"] for link in item["links"])})')
        for link in item['links']:
            rule = meta['links'].get(link['type'])
            if rule is None:
                errors.append(f'{id}: link type {link["type"]} does not exist')
                continue
            if item['type'] not in rule['from']:
                errors.append(f'{id}: a {item["type"]} cannot hold a {link["type"]} link')
            target = found.get(link['target'])
            if target is None:
                warnings.append(f'{id}: {link["type"]} {link["target"]}, which does not exist')
                continue
            if target['type'] not in rule['to']:
                errors.append(f'{id}: {link["type"]} cannot point to a {target["type"]} ({link["target"]})')
            if link.get('fingerprint') and link['fingerprint'] != target['fingerprint']:
                warnings.append(f'{id}: {link["type"]} {link["target"]} is suspect (the target changed)')
    return errors, warnings


def incoming(found):
    """{target id: [(link type, source id)]}."""
    into = {}
    for id, item in found.items():
        for link in item['links']:
            into.setdefault(link['target'], []).append((link['type'], id))
    return into


def is_active(meta, item):
    return item['state'] not in meta['types'].get(item['type'], {}).get('inactive_states', [])


def covered(meta, item, into, found):
    """Whether every coverage rule (`covered_by`) and every required outgoing link (`must_link`) of the type holds."""
    held = {link['type'] for link in item['links'] if found.get(link['target'], {}).get('fingerprint') is not None}
    if set(meta['types'][item['type']].get('must_link', [])) - held:
        return False
    for rule in meta['types'][item['type']].get('covered_by', []):
        if not any(kind == rule['link'] and found.get(source, {}).get('type') == rule['type'] and
                   found[source].get('fingerprint') is not None
                   for kind, source in into.get(item['id'], [])):
            return False
    return True


def chain_verified(item, into, found):
    """A requirement's chain: element satisfies it, a unit realizes the element, a test verifies it, a validation
    validates it or the need it derives from."""
    def sources(target, link, kind):
        return [source for name, source in into.get(target, []) if name == link and found.get(source, {}).get('type') == kind]
    elements = sources(item['id'], 'satisfies', 'ARC')
    realized = any(sources(element, 'realizes', 'UNIT') for element in elements)
    tested = bool(sources(item['id'], 'verifies', 'TEST'))
    needs = [link['target'] for link in item['links'] if link['type'] == 'derives-from']
    validated = any(sources(target, 'validates', 'VAL') for target in [item['id'], *needs])
    return bool(elements) and realized and tested and validated


def inventory(meta, found, root=ROOT):
    """{source: {name, ids, imported}}: the distinct ids each source holds, and how many are requirements of the model."""
    root = Path(root)
    imported_ids = {item.get('source_id') for item in found.values() if item['type'] == 'REQ'}
    result = {}
    for name, source in sorted(meta['inventory'].items()):
        ids = set()
        for part in source['parts']:
            paths = sorted(root.glob(part['glob']))
            if part['kind'] == 'files':
                ids |= {path.relative_to(root).as_posix() for path in paths}
            elif part['kind'] == 'filename':
                ids |= {match.group(1) for path in paths if (match := re.search(part['pattern'], path.name))}
            elif part['kind'] == 'content':
                ids |= {match for path in paths for match in re.findall(part['pattern'], path.read_text(), re.MULTILINE)}
            elif part['kind'] == 'registry':
                ids |= {key for path in paths for key in _read_json(path).get('properties', {})}
        result[name] = {'name': source['name'], 'ids': len(ids), 'imported': len(ids & imported_ids)}
    return result


def rate(share, scale):
    for level in scale:
        if share <= level['up_to']:
            return level['level']
    return scale[-1]['level'] if scale else ''


def standard_measure(found, today):
    """The standard's own measure: its rules, those with an executable check, with a test that verifies them, with a
    decision that justifies them, and those in warning past their deadline (dates as YYYY-MM-DD)."""
    into = incoming(found)
    rules = [item for item in found.values() if item['type'] == 'STD' and 'rule' in item and item['state'] != 'replaced']
    def tested(item):
        return any(kind == 'verifies' and found.get(source, {}).get('fingerprint') is not None
                   for kind, source in into.get(item['id'], []))
    return {
        'rules': len(rules),
        'executable': sum(1 for item in rules if item['rule']['check']['kind'] != 'judgment'),
        'tested': sum(1 for item in rules if tested(item)),
        'justified': sum(1 for item in rules if item['rule'].get('basis')),
        'overdue': sum(1 for item in rules if item['state'] == 'warning' and item['rule'].get('deadline', today) < today),
    }


def management_measure(found, today):
    """The standard management's own measure: its proposals by state, those open with no deadline or past it, the
    exemptions in force, and the version in effect."""
    proposals = [item for item in found.values() if item['type'] == 'PROP']
    open_ones = [item for item in proposals if item['state'] in ('open', 'warning')]
    return {
        'proposals': len(proposals),
        'open': len(open_ones),
        'closed': sum(1 for item in proposals if item['state'] in ('decided', 'applied', 'rejected')),
        'undated': sum(1 for item in open_ones if not item.get('body', {}).get('deadline')),
        'overdue': sum(1 for item in open_ones if item.get('body', {}).get('deadline', today) < today),
        'exemptions': sum(1 for item in found.values() if item['type'] == 'TAIL' and item['state'] == 'active'),
        'effective': sorted(id for id, item in found.items() if item['type'] == 'VER' and item['state'] == 'effective'),
    }


def utc_today():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date().isoformat()


def measure(root=ROOT, meta=None, found=None, today=None):
    meta = meta or metamodel(root)
    found = found if found is not None else objects(root)
    errors, warnings = check(meta, found, root, today)
    flagged = {line.split(':', 1)[0] for line in errors + warnings}
    into = incoming(found)
    requirements = [item for item in found.values() if item['type'] == 'REQ' and is_active(meta, item)]
    verified = sum(1 for item in requirements if chain_verified(item, into, found))
    systems = {}
    for name in sorted(meta['systems']):
        kinds = {type_id for type_id, kind in meta['types'].items() if kind['system'] == name}
        mine = [item for item in found.values() if item['type'] in kinds and is_active(meta, item)
                and item.get('fingerprint') is not None]
        good = sum(1 for item in mine if item['id'] not in flagged and covered(meta, item, into, found))
        share = good / len(mine) if mine else 0
        systems[name] = {'objects': len(mine), 'conformant': good, 'share': share, 'level': rate(share, meta['scale'])}
    sources = inventory(meta, found, root)
    return {
        'chain': {'active_requirements': len(requirements), 'verified': verified,
                  'share': verified / len(requirements) if requirements else 0},
        'inventory': {'sources': sources, 'ids': sum(item['ids'] for item in sources.values()),
                      'imported': sum(item['imported'] for item in sources.values())},
        'systems': systems,
        'standard': standard_measure(found, today or utc_today()),
        'standard_management': management_measure(found, today or utc_today()),
        'objects': len(found),
        'errors': len(meta['errors']) + len(errors),
        'warnings': len(warnings),
    }


def show(id, root=ROOT):
    found = objects(root)
    item = found.get(id)
    if item is None:
        raise ModelError(f'{id}: no such object')
    lines = [f'{item["id"]}  {item["type"]}  {item["state"]}  {item["source"]}']
    lines += [f'  -> {link["type"]} {link["target"]}' for link in item['links']]
    lines += [f'  <- {kind} {source}' for kind, source in sorted(incoming(found).get(id, []))]
    return '\n'.join(lines)


def summary(found):
    chain, stock = found['chain'], found['inventory']
    lines = [
        f'chain: {chain["verified"]} of {chain["active_requirements"]} active requirement(s) verified end to end '
        f'({chain["share"]:.0%})',
        f'inventory: {stock["imported"]} of {stock["ids"]} requirement id(s) imported as requirements',
    ]
    lines += [f'  {name}: {item["imported"]} of {item["ids"]}' for name, item in stock['sources'].items()]
    lines.append(f'systems ({found["objects"]} object(s)):')
    lines += [f'  {name}: {item["level"]} ({item["conformant"]} of {item["objects"]} conformant)'
              for name, item in found['systems'].items()]
    rules = found['standard']
    lines.append(f'standard: {rules["rules"]} rule(s), {rules["executable"]} with an executable check, {rules["tested"]} '
                 f'verified by a test, {rules["justified"]} justified by a decision, {rules["overdue"]} in warning past '
                 f'their deadline')
    managed = found['standard_management']
    lines.append(f'standard management: {managed["proposals"]} proposal(s), {managed["open"]} open ({managed["undated"]} '
                 f'with no deadline, {managed["overdue"]} past it), {managed["closed"]} closed; {managed["exemptions"]} '
                 f'exemption(s) in force; effective version {", ".join(managed["effective"]) or "none"}')
    lines.append(f'check: {found["errors"]} error(s), {found["warnings"]} warning(s)')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/model', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    checked = commands.add_parser('check')
    checked.add_argument('--strict', action='store_true')
    shown = commands.add_parser('show')
    shown.add_argument('id')
    commands.add_parser('seed-rules', help='write the seed rule of every refusal, gate stage, D-069 principle and the method')
    measured = commands.add_parser('measure')
    measured.add_argument('--json')
    args = parser.parse_args(argv)
    try:
        if args.command == 'seed-rules':
            written = seed_rules()
            print(f'seed-rules: {len(written)} rule file(s) written')
            return 0
        if args.command == 'show':
            print(show(args.id))
            return 0
        meta = metamodel()
        found = objects()
        if args.command == 'check':
            errors, warnings = check(meta, found, ROOT)
            errors = meta['errors'] + errors
            for line in errors:
                print(f'ERROR {line}')
            for line in warnings:
                print(f'WARN {line}')
            print(f'model check: {len(found)} object(s), {len(errors)} error(s), {len(warnings)} warning(s)')
            return 1 if errors or (args.strict and warnings) else 0
        result = measure(meta=meta, found=found)
        if args.json:
            Path(args.json).write_text(json.dumps(result, indent=1) + '\n')
        print(summary(result))
        return 1 if result['errors'] else 0
    except ModelError as error:
        print(f'model: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
