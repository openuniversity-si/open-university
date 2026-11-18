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
  scripts/model reflexion          the dependencies between components: convergent, divergent, absent
  scripts/model view               the component view (C4 level 3) as Mermaid, generated from the model
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
import subprocess
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
        for field in ('derived_states', 'inactive_states', 'unconformant_states'):
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


REFUTES = re.compile(r'\brefutes (P-[0-9]+)\b')  # a decision that names the premise it refutes (D-320 refutes P-58)


def read_decisions(root):
    objects, seen = [], set()
    for path in sorted(Path(root).glob(DECISION_RECORDS)):
        text = path.read_text()
        head = FRONT.match(text)
        fields = dict(line.split(':', 1) for line in head.group(1).splitlines() if ':' in line) if head else {}
        number = fields.get('number', path.stem).strip()
        seen.add(number)
        refuted = set(REFUTES.findall(text))
        assumed = [{'type': 'refutes' if ident in refuted else 'assumes', 'target': ident}
                   for ident in re.findall(r'\bP-[0-9]+\b', fields.get('premises', ''))]
        objects.append(_obj(number, 'D', 'accepted', path.relative_to(root).as_posix(), text, assumed))
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
        links += [{'type': 'realizes', 'target': element} for element in manifest.get('realizes', [])]
        objects.append(_obj(f'UNIT:{manifest["id"]}', 'UNIT', 'active', path.relative_to(root).as_posix(), text, links))
    return objects


VERIFIES = re.compile(r'^\s*(?:(?:#|//|\*)\s*)?Verifies:\s*(.+)$', re.MULTILINE)
SITE_TESTS = ('apps/web/src/**/*.test.ts', 'apps/web/scripts/**/*.test.ts', 'apps/web/test/**/*.test.ts',
              'apps/web/e2e/**/*.spec.ts')


def read_tests(root):
    """Tests (TEST): every script test and test file. A test file declares what it verifies on a `Verifies:` line (a
    comment or a docstring line naming requirements, decisions or units, comma-separated: the link on the test
    itself, as OpenFastTrace tags do); a script test verifies the units whose code its covers manifest names
    (derived from the declared covers, never written twice)."""
    root = Path(root)
    paths = sorted({Path(found) for pattern in TEST_GLOBS for found in globbing.glob(str(root / pattern), recursive=True)})
    found = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(errors='replace')
        targets = [target.strip() for listed in VERIFIES.findall(text) for target in listed.split(',') if target.strip()]
        found.append(_obj(f'TEST:{path.relative_to(root).as_posix()}', 'TEST', 'active', path.relative_to(root).as_posix(),
                          text, [{'type': 'verifies', 'target': target} for target in dict.fromkeys(targets)]))
    # The site's tests count only when they declare what they verify: the site keeps its own suite (D-319).
    for pattern in SITE_TESTS:
        for path in sorted(root.glob(pattern)):
            text = path.read_text(errors='replace')
            targets = [target.strip() for listed in VERIFIES.findall(text) for target in listed.split(',') if target.strip()]
            if targets:
                found.append(_obj(f'TEST:{path.relative_to(root).as_posix()}', 'TEST', 'active', path.relative_to(root).as_posix(),
                                  text, [{'type': 'verifies', 'target': target} for target in dict.fromkeys(targets)]))
    covered = covered_units(root)
    by_id = {item['id']: item for item in found}
    for script, unit_ids in covered.items():
        item = by_id.get(f'TEST:{script}')
        if item is not None:
            item['links'] += [{'type': 'verifies', 'target': f'UNIT:{unit}'} for unit in unit_ids]
    return found


def covered_units(root):
    """{script test: [unit ids]}: the units that own a code file each covers manifest names (literal paths and globs
    over the tracked files, test files left out)."""
    from gate_areas import glob_match
    import units
    root = Path(root)
    listed = _git(root, 'ls-files')
    code = [name for name in listed.splitlines() if name.startswith(('scripts/', 'infra/', 'services/'))
            and not name.startswith('scripts/tests/')]
    if not code:
        return {}
    owner = {}
    for name in code:
        claims = units.units_of(name, root)
        if claims:
            owner[name] = claims
    result = {}
    for script, patterns in _covers(root):
        hit = set()
        for pattern in patterns:
            if pattern.startswith('scripts/tests/'):
                continue
            if any(mark in pattern for mark in '*?['):
                hit |= {unit for name, claims in owner.items() if glob_match(name, pattern) for unit in claims}
            elif pattern in owner:
                hit |= set(owner[pattern])
        if hit:
            result[script] = sorted(hit)
    return result


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
        item = _obj(body['id'], kind, body.get('state', 'defined'), path.relative_to(root).as_posix(), text, links_of(body))
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
            own = body.get('overrides', {}).get(source_id, {})
            retired = own.get('retired_by', body.get('retired_by'))
            fields = {'type': body['type'], 'statement': statement, 'state': own.get('state', body['state']),
                      'owner': body['owner'], 'source': where, **({'retired_by': retired} if retired else {}),
                      **({'derives_from': [need]} if need else {})}
            item = _obj(f'REQ-{path.stem}-{_slug(source_id)}', 'REQ', fields['state'], where, statement,
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


def read_premises(root):
    """Premises (P), read where they are through the register's own loader (scripts/lib/premises.py, D-066): the id,
    the status as the state, the radius and the record's path as the source id the inventory counts."""
    import premises
    records, _ = premises.load(Path(root))
    found = []
    for ident, record in sorted(records.items()):
        path = Path(root) / record['path']
        item = _obj(ident, 'P', record['status'], record['path'], path.read_text() if path.is_file() else ident)
        item.update(source_id=record['path'], body={'radius': record.get('radius'), 'statement': record.get('statement')})
        found.append(item)
    return found


TRAILER_IMPLEMENTS = re.compile(r'^Implements:\s*(.+)$', re.MULTILINE)
PR_NUMBER = re.compile(r'#([0-9]+)')


def _git(root, *args):
    run = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)
    return run.stdout if run.returncode == 0 else ''


def read_changes(root):
    """Changes (CHG): every merge on the first-parent line of HEAD, one per pull request (CHG-<number>, else
    CHG-<sha>), merged; the `Implements:` trailers of its commits become implements links (requirements or units,
    comma-separated)."""
    found = []
    for line in _git(root, 'log', '--first-parent', '--merges', '--format=%H%x1f%s', 'HEAD').splitlines():
        sha, _, subject = line.partition('\x1f')
        number = PR_NUMBER.search(subject)
        ident = f'CHG-{number.group(1)}' if number else f'CHG-{sha[:len("0123456789ab")]}'
        bodies = _git(root, 'log', '--format=%B', f'{sha}^1..{sha}')
        targets = []
        for listed in TRAILER_IMPLEMENTS.findall(bodies):
            targets += [target.strip() for target in listed.split(',') if target.strip()]
        links = [{'type': 'implements', 'target': target} for target in dict.fromkeys(targets)]
        item = _obj(ident, 'CHG', 'merged', f'git:{sha}', sha, links)
        item['body'] = {'sha': sha, 'subject': subject}
        found.append(item)
    return found


VALIDATIONS = 'config/validation/VAL-*.json'


def read_validations(root):
    """Validations (VAL), one file each; the state is derived later (derive_validations), never read from the file."""
    return _declared(Path(root), VALIDATIONS, 'validation.v1.json', 'VAL',
                     lambda body: [{'type': 'validates', 'target': target} for target in body['validates']])


def _merges(root):
    """[(sha, date)] of main's first-parent merges in HEAD, newest first."""
    lines = _git(root, 'log', '--first-parent', '--merges', '--format=%H %ad', '--date=short', 'HEAD').splitlines()
    return [tuple(line.split(' ', 1)) for line in lines if ' ' in line]


def measured(body, found, root, today):
    """(value, enough) of one validation's measure; value None when there is no source or no data."""
    measure, window = body['measure'], body.get('window', {'kind': 'days', 'size': 1})
    if measure['kind'] == 'merges-per-day':
        from datetime import date, timedelta
        last = date.fromisoformat(today) - timedelta(days=1)
        days = {(last - timedelta(days=offset)).isoformat() for offset in range(window['size'])}
        dates = [day for _, day in _merges(root)]
        return (sum(1 for day in dates if day in days) / window['size'], bool(dates) and min(dates) <= min(days))
    if measure['kind'] == 'trailer-rate':
        merges = _merges(root)[:window['size']]
        if not merges:
            return None, False
        marked = sum(1 for sha, _ in merges if re.search(rf'^{re.escape(measure["trailer"])}:',
                                                         _git(root, 'log', '--format=%B', f'{sha}^1..{sha}'), re.MULTILINE))
        return marked / len(merges), len(merges) >= window['size']
    if measure['kind'] == 'model-share':
        if measure['name'] == 'reflexion':
            return reflexion_share(found)['share'], True
        counted = requirements_measure(found)
        return (counted['with_verification'] / counted['active'] if counted['active'] else 0), True
    if measure['kind'] == 'incident-count':
        from datetime import date, timedelta
        start = (date.fromisoformat(today) - timedelta(days=window['size'])).isoformat()
        dates = [day for _, day in _merges(root)]
        return (len(incidents(root, measure['incident'], start, today)), bool(dates) and min(dates) <= start)
    if measure['kind'] == 'run-durations':
        import runs
        from datetime import date
        recorded = runs.read(root, measure['workflow'])
        if not recorded or not recorded['runs']:
            return None, False
        fresh = (date.fromisoformat(today) - date.fromisoformat(recorded['at'][:len('2026-01-01')])).days <= measure['max_age_days']
        values = [run['seconds'] for run in recorded['runs']]
        return runs.percentile(values, measure['percentile']), fresh and len(values) >= measure['min_runs']
    if measure['kind'] == 'all-met':
        states = [found.get(ident, {}).get('state', 'defined') for ident in measure['of']]
        missed = sum(1 for state in states if state == 'not-met')
        return (missed, True) if missed or all(state == 'met' for state in states) else (missed, False)
    if measure['kind'] == 'code-scan':
        return len(polling_left(root, measure['paths'], measure.get('exclude', []))), True
    return None, False


INCIDENT_FIELD = re.compile(r'^(kind|time): (\S+)$', re.MULTILINE)


def incidents(root, kind, start, end):
    """The incident records (docs/operations/incidents, scripts/incident) of one kind opened on [start, end)."""
    found = []
    for path in sorted((Path(root) / 'docs/operations/incidents').glob('I-*.md')):
        fields = dict(INCIDENT_FIELD.findall(path.read_text().split('\n---', 1)[0]))
        if fields.get('kind') == kind and start <= fields.get('time', '')[:len('2026-01-01')] < end:
            found.append(path.stem)
    return found


SHELL_SLEEP = re.compile(r'(^|[;&|(\s])sleep\s')
SHELL_OPEN = re.compile(r'\b(do)\b')
SHELL_CLOSE = re.compile(r'\b(done)\b')


def _python_sleeps(text):
    """[(line, function)] of a sleep call inside a loop, from the module's syntax tree; the function is the innermost
    one that holds the call, '<module>' outside any."""
    import ast
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    def holder(line):
        inside = [node for node in functions if node.lineno <= line <= node.end_lineno]
        return min(inside, key=lambda node: node.end_lineno - node.lineno).name if inside else '<module>'
    lines = set()
    for loop in ast.walk(tree):
        if not isinstance(loop, (ast.While, ast.For)):
            continue
        for node in ast.walk(loop):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
                if name == 'sleep':
                    lines.add(node.lineno)
    return [(line, holder(line)) for line in sorted(lines)]


SHELL_FUNCTION = re.compile(r'^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{?')


def _shell_sleeps(text):
    """[(line, function)] of a sleep inside a do ... done loop (a line count of the loop keywords, not a parser); the
    function is the last `name()` opened above it, '<script>' before any."""
    depth, found, current = 0, [], '<script>'
    for number, line in enumerate(text.splitlines(), 1):
        code = line.split('#', 1)[0]
        named = SHELL_FUNCTION.match(code)
        if named:
            current = named.group(1)
        depth += len(SHELL_OPEN.findall(code))
        if depth > 0 and SHELL_SLEEP.search(code):
            found.append((number, current))
        depth = max(0, depth - len(SHELL_CLOSE.findall(code)))
    return found


def polling_candidates(root, paths, exclude):
    """[(path, function, line)] of every sleep inside a loop in the code under `paths` (globs), less `exclude`: the
    candidates for polling a state on an interval (REQ-events-no-polling)."""
    root = Path(root)
    skipped = {path for pattern in exclude for path in root.glob(pattern)}
    found = set()
    for pattern in paths:
        for path in sorted(root.glob(pattern)):
            if path in skipped or not path.is_file() or '__pycache__' in path.parts:
                continue
            text = path.read_text(errors='replace')
            sleeps = _python_sleeps(text) if path.suffix == '.py' else _shell_sleeps(text) if (
                path.suffix == '.sh' or text.startswith('#!/usr/bin/env bash') or text.startswith('#!/bin/bash')) else []
            found |= {(path.relative_to(root).as_posix(), function, line) for line, function in sleeps}
    return sorted(found)


def polling_sites(root, paths, exclude):
    """['path:line'] of every candidate (polling_candidates)."""
    return [f'{path}:{line}' for path, _, line in polling_candidates(root, paths, exclude)]


POLLING_DECISIONS = 'config/validation/polling/POLL-*.json'
NOT_POLLING = ('backoff', 'dormant', 'test-infra', 'measurement')


def polling_decisions(root):
    """{'path::function': decision} of config/validation/polling/ (contracts/model/polling.v1.json)."""
    return {body['site']: body for body in (_read_json(path) for path in sorted(Path(root).glob(POLLING_DECISIONS)))}


def polling_left(root, paths, exclude):
    """The candidates that still count as polling: undecided, or decided external-wait (a real wait on a state)."""
    decided = polling_decisions(root)
    return [(path, function, line) for path, function, line in polling_candidates(root, paths, exclude)
            if decided.get(f'{path}::{function}', {}).get('class') not in NOT_POLLING]


def derive_validations(found, root, today=None):
    """Sets each validation's state from its measure: met or not-met when the window holds data, measuring while it
    is short, defined while no source is wired."""
    today = today or utc_today()
    vals = [item for item in found.values() if item['type'] == 'VAL' and 'body' in item]
    # a composite reads the states of the others, so it is derived after them
    for item in sorted(vals, key=lambda item: item['body']['measure']['kind'] == 'all-met'):
        value, enough = measured(item['body'], found, root, today)
        if value is None:
            item['state'] = 'defined'
        elif not enough:
            item['state'] = 'measuring'
        else:
            passes = value >= item['body']['threshold'] if item['body']['comparator'] == 'gte' else value <= item['body']['threshold']
            item['state'] = 'met' if passes else 'not-met'
        item['measured'] = value


def validation_measure(found):
    """The validation system's own measure: validations by state, and the needs that have a validation met."""
    into = incoming(found)
    by_state = {}
    for item in found.values():
        if item['type'] == 'VAL':
            by_state[item['state']] = by_state.get(item['state'], 0) + 1
    needs = [item for item in found.values() if item['type'] == 'NEED']
    met = sum(1 for item in needs if any(kind == 'validates' and found.get(source, {}).get('state') == 'met'
                                         for kind, source in into.get(item['id'], [])))
    return {'by_state': dict(sorted(by_state.items())), 'needs': len(needs), 'needs_met': met}


def requirement_states(found):
    """{requirement id: derived state}: implemented when a merged change implements it, verified when it is also
    verified by a test (the verdicts on main join with the verification phase), else its declared state."""
    into = incoming(found)
    states = {}
    for item in found.values():
        if item['type'] != 'REQ' or item['state'] in ('superseded', 'obsolete'):
            continue
        sources = into.get(item['id'], [])
        implemented = any(kind == 'implements' and found.get(source, {}).get('state') in ('merged', 'deployed')
                          for kind, source in sources)
        tested = any(kind == 'verifies' and found.get(source, {}).get('fingerprint') is not None for kind, source in sources)
        states[item['id']] = 'verified' if implemented and tested else 'implemented' if implemented else item['state']
    return states


def requirements_measure(found):
    """The requirements system's own measure: active requirements by type, implemented, verified, with an
    architecture element, with a test, and the suspect links pointing at them."""
    into = incoming(found)
    states = requirement_states(found)
    active = [found[id] for id in states]
    by_type = {}
    for item in active:
        kind = item.get('body', {}).get('type', '?')
        by_type[kind] = by_type.get(kind, 0) + 1
    def has(item, link, kind):
        return any(name == link and found.get(source, {}).get('type') == kind for name, source in into.get(item['id'], []))
    return {
        'active': len(active), 'by_type': dict(sorted(by_type.items())),
        'implemented': sum(1 for state in states.values() if state in ('implemented', 'verified')),
        'verified': sum(1 for state in states.values() if state == 'verified'),
        'with_element': sum(1 for item in active if has(item, 'satisfies', 'ARC')),
        'with_test': sum(1 for item in active if has(item, 'verifies', 'TEST')),
        'with_verification': sum(1 for item in active if has(item, 'verifies', 'TEST') or (
            item.get('body', {}).get('verification') == 'validation' and has(item, 'validates', 'VAL'))),
    }


ARCHITECTURE = 'config/architecture/ARC-*.json'
ARCHITECTURE_IMPORTS = 'config/architecture/imports/*.json'
CAPABILITIES = 'docs/capabilities/CAP-*.md'
CAPABILITY_STATE = {'requested': 'proposed', 'approved': 'active', 'done': 'active'}
ADRS = 'docs/adr/ADR-*.md'
ADR_STATUS = re.compile(r'Status:\s*(proposed|accepted|rejected|deprecated|superseded)\b(?:\s+by\s+\[?((?:D|ADR)-[0-9]+))?', re.IGNORECASE)
ADR_STATE = {'rejected': 'deprecated'}


def read_architecture(root):
    """Architecture elements (ARC): the files of config/architecture/ (satisfies and depends-on links), and the
    capabilities of docs/capabilities/ read where they are, through config/architecture/imports/capabilities.json."""
    root = Path(root)
    found = _declared(root, ARCHITECTURE, 'architecture.v1.json', 'ARC', lambda body: [
        *({'type': 'satisfies', 'target': target} for target in body.get('satisfies', [])),
        *({'type': 'depends-on', 'target': target} for target in body.get('depends_on', []))])
    for item in found:
        item.setdefault('body', {})
    imports = root / ARCHITECTURE_IMPORTS.replace('*', 'capabilities')
    declared = _read_json(imports) if imports.is_file() else {}
    problems = list(json_schema.validate(_read_json(root / CONTRACTS_DIR / 'architecture-import.v1.json'), declared)) if declared else []
    for path in sorted(root.glob(CAPABILITIES)):
        text = path.read_text()
        number = re.match(r'(CAP-[0-9]+)', path.stem).group(1)
        status = re.search(r'^status:\s*([a-z]+)', text, re.MULTILINE)
        own = declared.get('overrides', {}).get(number, {})
        state = own.get('state', CAPABILITY_STATE.get(status.group(1) if status else '', 'proposed'))
        links = [{'type': 'satisfies', 'target': target} for target in declared.get('satisfies', {}).get(number, [])]
        item = _obj(f'ARC-cap-{number[len("CAP-"):]}', 'ARC', state, path.relative_to(root).as_posix(), text, links)
        item.update(source_id=path.relative_to(root).as_posix(),
                    body={'kind': 'capability', 'statement': text.split('\n', 1)[0].lstrip('# '),
                          **({'retired_by': own['retired_by']} if own.get('retired_by') else {})})
        if problems:
            item['problems'] = problems
        found.append(item)
    return found


def read_adrs(root):
    """Architecture decision records as decisions (D): the state is the MADR status the record states (proposed,
    accepted, deprecated, superseded; rejected reads as deprecated); `superseded by X` becomes a supersedes link on X,
    and `deprecated by D-NNN` the decision that retired it."""
    root = Path(root)
    found = []
    for path in sorted(root.glob(ADRS)):
        text = path.read_text()
        ident = re.match(r'(ADR-[0-9]+)', path.stem).group(1)
        status = ADR_STATUS.search('\n'.join(text.splitlines()[:len('0123456789')]))
        state = ADR_STATE.get(status.group(1).lower(), status.group(1).lower()) if status else 'proposed'
        by = status.group(2) if status else None
        item = _obj(ident, 'D', state, path.relative_to(root).as_posix(), text)
        item['body'] = {'adr': True, **({'retired_by': by} if by and state == 'deprecated' else {})}
        found.append(item)
        if by and state == 'superseded':
            found.append({'id': by, 'type': 'D', 'state': 'accepted', 'source': '', 'fingerprint': None, 'claimed': True,
                          'links': [{'type': 'supersedes', 'target': ident}]})
    return found


def layer_errors(found):
    """An architecture element may declare a dependency on its own layer or a lower one (D-322); one that goes up is
    a defect to break, never accepted by declaring it."""
    layers = {id: item['body'].get('layer') for id, item in found.items() if item['type'] == 'ARC' and 'body' in item}
    return [f'{id}: depends on {link["target"]} of a higher layer ({layers[link["target"]]} > {layers[id]}); break the '
            f'dependency instead of declaring it (D-322)'
            for id in sorted(layers) for link in found[id]['links']
            if link['type'] == 'depends-on' and layers[id] is not None and layers.get(link['target']) is not None
            and layers[link['target']] > layers[id]]


def reflexion(found):
    """The reflexion model (Murphy, Notkin, Sullivan 1995) of the architecture: the dependencies the elements declare
    (depends-on between ARC) against those extracted from the units (a unit of A depends on a unit of B, A and B the
    elements they realize). {convergences, divergences, absences}: declared and present, present and not declared,
    declared and not present, each a sorted list of (from, to)."""
    realized = {id: [link['target'] for link in item['links'] if link['type'] == 'realizes']
                for id, item in found.items() if item['type'] == 'UNIT'}
    extracted = set()
    for id, item in found.items():
        if item['type'] != 'UNIT':
            continue
        for link in item['links']:
            if link['type'] == 'depends-on' and link['target'] in realized:
                extracted |= {(start, end) for start in realized[id] for end in realized[link['target']] if start != end}
    declared = {(id, link['target']) for id, item in found.items() if item['type'] == 'ARC'
                for link in item['links'] if link['type'] == 'depends-on'}
    return {'convergences': sorted(extracted & declared), 'divergences': sorted(extracted - declared),
            'absences': sorted(declared - extracted)}


def view(found):
    """The component view (C4 level 3) of the engine as a Mermaid flowchart, generated from the model: one node per
    active component, a solid arrow for a convergent dependency, a dashed one for a divergence, a crossed one for an
    absence."""
    model_reflexion = reflexion(found)
    elements = sorted(id for id, item in found.items() if item['type'] == 'ARC' and item['state'] == 'active'
                      and item.get('body', {}).get('kind') == 'component')
    lines = ['flowchart LR']
    lines += [f'  {id.replace("-", "_")}["{found[id].get("body", {}).get("name", id)}"]' for id in elements]
    for arrow, pairs in (('-->', 'convergences'), ('-.->', 'divergences'), ('--x', 'absences')):
        lines += [f'  {start.replace("-", "_")} {arrow} {end.replace("-", "_")}' for start, end in model_reflexion[pairs]]
    return '\n'.join(lines)


def architecture_measure(found):
    """The architecture system's own measure: active elements by kind, those that satisfy a requirement, those a
    unit realizes, the units that realize an element, and the ADRs by state."""
    into = incoming(found)
    elements = [item for item in found.values() if item['type'] == 'ARC' and item['state'] in ('proposed', 'active')]
    by_kind = {}
    for item in elements:
        kind = item.get('body', {}).get('kind', '?')
        by_kind[kind] = by_kind.get(kind, 0) + 1
    units = [item for item in found.values() if item['type'] == 'UNIT']
    adrs = {}
    for item in found.values():
        if item.get('body', {}).get('adr'):
            adrs[item['state']] = adrs.get(item['state'], 0) + 1
    return {
        'elements': len(elements), 'by_kind': dict(sorted(by_kind.items())),
        'satisfying': sum(1 for item in elements if any(link['type'] == 'satisfies' for link in item['links'])),
        'realized': sum(1 for item in elements if any(kind == 'realizes' for kind, _ in into.get(item['id'], []))),
        'units_realizing': sum(1 for item in units if any(link['type'] == 'realizes' for link in item['links'])),
        'units': len(units), 'adrs': dict(sorted(adrs.items())),
        'reflexion': reflexion_share(found),
    }


def reflexion_share(found):
    model_reflexion = reflexion(found)
    counts = {name: len(pairs) for name, pairs in model_reflexion.items()}
    total = sum(counts.values())
    return {**counts, 'share': counts['convergences'] / total if total else 0}


def decisions_measure(found, root=ROOT):
    """The decisions system's own measure: decisions by state, the accepted ones a test proves, and the decision
    records edited after the commit that wrote them (an accepted decision changes by a new one that supersedes it)."""
    into = incoming(found)
    decisions = [item for item in found.values() if item['type'] == 'D' and item.get('fingerprint') is not None]
    by_state = {}
    for item in decisions:
        by_state[item['state']] = by_state.get(item['state'], 0) + 1
    accepted = [item for item in decisions if item['state'] == 'accepted']
    proven = sum(1 for item in accepted if any(kind == 'verifies' and found.get(source, {}).get('fingerprint') is not None
                                               for kind, source in into.get(item['id'], [])))
    edited = 0
    for path in sorted(Path(root).glob(DECISION_RECORDS)):
        commits = _git(root, 'log', '--format=%H', '--', path.relative_to(root).as_posix()).split()
        edited += len(commits) > 1
    return {'by_state': dict(sorted(by_state.items())), 'accepted': len(accepted), 'proven': proven,
            'edited_records': edited}


def knowledge_measure(found, radius='high'):
    """The knowledge system's own measure: the premises, the high-blast ones not confirmed or validated, the refuted
    ones still assumed by an active object."""
    into = incoming(found)
    settled = ('confirmed', 'validated')
    premises_found = [item for item in found.values() if item['type'] == 'P']
    return {
        'premises': len(premises_found),
        'high_unsettled': sum(1 for item in premises_found if item['body'].get('radius') == radius
                              and item['state'] not in settled + ('refuted',)),
        'refuted_assumed': sum(1 for item in premises_found if item['state'] == 'refuted'
                               and any(kind == 'assumes' for kind, _ in into.get(item['id'], []))),
    }


def read_suppliers(root):
    """Suppliers (SUP), one file each (config/supply/suppliers/, PADRAO-DEV F7c)."""
    return _declared(Path(root), 'config/supply/suppliers/SUP-*.json', 'supplier.v1.json', 'SUP', lambda body: [])


def read_dependencies(root):
    """Third-party components (DEP), derived from the files that pin them (scripts/lib/supply.py): a lockfile, a pip
    file, the toolchain manifest, a workflow. Supplied-by its supplier; state vulnerable while an advisory affects it."""
    import supply
    ecosystems, tools = supply.suppliers_of(root)
    snapshot = supply.read_snapshot(root) or {'advisories': []}
    granted, today = supply.exemptions(root), utc_today()
    hit = {(advisory['package'], version) for advisory in snapshot['advisories']
           if supply.advisory_state(advisory, granted.get(advisory['id']), today) == 'affecting'
           for version in advisory['versions']}
    found = []
    for entry in supply.dependencies(root):
        ident = supply.dep_id(entry['ecosystem'], entry['name'], entry['version'])
        owner = supply.supplier(entry, ecosystems, tools)
        state = 'vulnerable' if (entry['ecosystem'] == 'npm' and (entry['name'], entry['version']) in hit) else (
            'in-use' if entry['pinned'] else 'unpinned')
        item = _obj(ident, 'DEP', state, entry['sources'][0], json.dumps(entry, sort_keys=True),
                    [{'type': 'supplied-by', 'target': owner}] if owner else [])
        item['body'] = entry
        found.append(item)
    return found


def read_advisories(root):
    """Advisories (ADV) of the audit snapshot (config/supply/advisories.json): affecting, or exempted while an exemption
    with a reason and a deadline holds; each affects the DEPs of its package and versions."""
    import supply
    snapshot = supply.read_snapshot(root)
    if snapshot is None:
        return []
    granted, today = supply.exemptions(root), utc_today()
    found = []
    for advisory in snapshot['advisories']:
        links = [{'type': 'affects', 'target': supply.dep_id('npm', advisory['package'], version)}
                 for version in advisory['versions']]
        item = _obj(advisory['id'], 'ADV', supply.advisory_state(advisory, granted.get(advisory['id']), today),
                    supply.SNAPSHOT, json.dumps(advisory, sort_keys=True), links)
        item['body'] = advisory
        found.append(item)
    return found


def registered(body):
    """Whether a store of personal data records its processing: every personal field in a `processing` entry (each
    with purpose, legal basis and retention), or one purpose, legal basis and retention for the whole store."""
    if body.get('processing'):
        covered = {field for entry in body['processing'] for field in entry['fields']}
        return set(body.get('personal_fields', [])) <= covered
    return all(body.get(field) for field in ('purpose', 'legal_basis', 'retention'))


def data_state(body, today, max_days):
    """A data store's state: unregistered (personal data without purpose, legal basis and retention) first, then
    unprotected (no backup), regenerable, unverified (no restore verified within max_days) or protected."""
    from datetime import date
    if body['personal'] and not registered(body):
        return 'unregistered'
    method = body['backup']['method']
    if method == 'none':
        return 'unprotected'
    if method == 'regenerable':
        return 'regenerable'
    verified = body['backup'].get('last_restore_verified')
    if not verified or (date.fromisoformat(today) - date.fromisoformat(verified)).days > max_days:
        return 'unverified'
    return 'protected'


def read_data(root):
    """Data stores (DATA, the Operation system), one file each (config/operation/data/); the state is derived."""
    import config
    found = _declared(Path(root), 'config/operation/data/DATA-*.json', 'data.v1.json', 'DATA',
                      lambda body: [{'type': 'supplied-by', 'target': body['supplier']}] if body.get('supplier') else [])
    today, max_days = utc_today(), config.get('operation.restore_max_days', ROOT)
    for item in found:
        if 'body' in item:
            item['state'] = data_state(item['body'], today, max_days)
    return found


def request_state(body, today):
    if body.get('answered'):
        return 'answered' if body['answered'] <= body['due'] else 'answered-late'
    return 'overdue' if today > body['due'] else 'open'


def read_requests(root):
    """Data subject requests (REQUEST, the Operation system), one file each (config/operation/requests/)."""
    found = _declared(Path(root), 'config/operation/requests/REQUEST-*.json', 'request.v1.json', 'REQUEST',
                      lambda body: [{'type': 'concerns', 'target': target} for target in body.get('data', [])])
    today = utc_today()
    for item in found:
        if 'body' in item:
            item['state'] = request_state(item['body'], today)
    return found


def read_risks(root):
    """Security risks (RISK, the Segurança system), one file each (config/security/risks/); the state is the risk
    process's own record: an owner's acceptance is a decision, never derived."""
    return _declared(Path(root), 'config/security/risks/RISK-*.json', 'risk.v1.json', 'RISK',
                     lambda body: [{'type': 'threatens', 'target': asset} for asset in body['assets']])


def control_state(body, found_ids):
    """not-applicable with its reason; gap while nothing that exists implements it; partial or implemented by coverage."""
    if not body['applicable']:
        return 'not-applicable'
    if not [target for target in body.get('implemented_by', []) if target in found_ids]:
        return 'gap'
    return 'implemented' if body.get('coverage', 'full') == 'full' else 'partial'


def read_controls(root):
    """Security controls (CTRL), one file each (config/security/controls/), with their applicability; the state is
    derived once every object is known (derive_controls)."""
    return _declared(Path(root), 'config/security/controls/CTRL-*.json', 'control.v1.json', 'CTRL',
                     lambda body: [{'type': 'implemented-by', 'target': target} for target in body.get('implemented_by', [])])


def derive_controls(found):
    ids = set(found)
    for item in found.values():
        if item['type'] == 'CTRL' and 'body' in item:
            item['state'] = control_state(item['body'], ids)


def vuln_state(body, today, deadlines):
    """verified, fixed, accepted while its acceptance holds, overdue past the bug bar's deadline, else open."""
    from datetime import date, timedelta
    if body.get('fixed'):
        return 'verified' if body.get('verified_by') else 'fixed'
    if body.get('accepted_until') and body['accepted_until'] >= today:
        return 'accepted'
    due = date.fromisoformat(body['found']) + timedelta(days=deadlines[body['severity']])
    return 'overdue' if date.fromisoformat(today) > due else 'open'


def read_vulns(root):
    """Vulnerabilities of the repository's own code (VULN), one file each (config/security/vulns/)."""
    import config
    found = _declared(Path(root), 'config/security/vulns/VULN-*.json', 'vuln.v1.json', 'VULN',
                      lambda body: [{'type': 'threatens', 'target': target} for target in body['in']])
    today = utc_today()
    deadlines = {'critical': config.get('security.vuln_critical_days', ROOT), 'high': config.get('security.vuln_high_days', ROOT),
                 'moderate': config.get('security.vuln_moderate_days', ROOT), 'low': config.get('security.vuln_low_days', ROOT)}
    for item in found:
        if 'body' in item:
            item['state'] = vuln_state(item['body'], today, deadlines)
    return found


def read_threats(root):
    """Threat models (THREAT), one file each (config/security/threats/): reviewed once a review date is recorded."""
    found = _declared(Path(root), 'config/security/threats/THREAT-*.json', 'threat.v1.json', 'THREAT',
                      lambda body: [{'type': 'models', 'target': body['models']}])
    for item in found:
        if 'body' in item:
            item['state'] = 'reviewed' if item['body'].get('reviewed') else 'written'
    return found


def read_checks(root):
    """Checks the merge queue requires (CHK, the Configuration system), derived from the workflows and the rulesets
    (scripts/lib/queue_checks.py): staged, installed or required."""
    import queue_checks
    found = []
    for entry in queue_checks.checks(root):
        source = (f'{queue_checks.INSTALLED}/{entry["workflow"]}' if entry['installed'] else
                  f'{queue_checks.STAGED}/{entry["workflow"]}' if entry['workflow'] else entry['required_by'])
        item = _obj(queue_checks.check_id(entry['name']), 'CHK', entry['state'], source, json.dumps(entry, sort_keys=True))
        item['body'] = entry
        found.append(item)
    return found


READERS = (read_decisions, read_units, read_tests, read_rules, read_proposals, read_versions, read_tailoring,
           read_intent, read_requirements, read_premises, read_changes, read_architecture, read_adrs, read_validations,
           read_suppliers, read_dependencies, read_advisories, read_checks, read_data, read_requests,
           read_risks, read_controls, read_vulns, read_threats)


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
    if read_validations in readers:
        derive_validations(found, root)
    if read_controls in readers:
        derive_controls(found)
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
    errors += layer_errors(found)
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
    if item['state'] in meta['types'][item['type']].get('unconformant_states', []):
        return False
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
    tested = bool(sources(item['id'], 'verifies', 'TEST')) or (
        item.get('body', {}).get('verification') == 'validation' and
        any(found[source]['state'] == 'met' for source in sources(item['id'], 'validates', 'VAL')))
    needs = [link['target'] for link in item['links'] if link['type'] == 'derives-from']
    validated = any(found[source]['state'] == 'met' for target in [item['id'], *needs]
                    for source in sources(target, 'validates', 'VAL'))
    return bool(elements) and realized and tested and validated


def inventory(meta, found, root=ROOT):
    """{source: {name, ids, imported}}: the distinct ids each source holds, and how many of them are objects of the
    model of a type the source may become (the object's id, or the source id it was imported from)."""
    root = Path(root)
    result = {}
    for name, source in sorted(meta['inventory'].items()):
        imported_ids = {key for item in found.values() if item['type'] in source['becomes']
                        for key in (item['id'], item.get('source_id')) if key}
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
                ids |= {key for path in paths for key in _read_json(path).get('properties', {})
                        if not part.get('pattern') or re.search(part['pattern'], key)}
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
        'knowledge': knowledge_measure(found),
        'requirements': requirements_measure(found),
        'architecture': architecture_measure(found),
        'decisions': decisions_measure(found, root),
        'validation': validation_measure(found),
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
        f'inventory: {stock["imported"]} of {stock["ids"]} requirement id(s) of the inventory are objects of the model',
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
    wanted = found['requirements']
    lines.append(f'requirements: {wanted["active"]} active ({", ".join(f"{count} {kind}" for kind, count in wanted["by_type"].items())}); '
                 f'{wanted["implemented"]} implemented, {wanted["verified"]} verified, {wanted["with_element"]} with an '
                 f'architecture element, {wanted["with_test"]} with a test')
    built = found['architecture']
    lines.append(f'architecture: {built["elements"]} active element(s) ({", ".join(f"{count} {kind}" for kind, count in built["by_kind"].items())}); '
                 f'{built["satisfying"]} satisfy a requirement, {built["realized"]} realized by a unit; {built["units_realizing"]} '
                 f'of {built["units"]} units realize an element; ADRs {", ".join(f"{count} {state}" for state, count in built["adrs"].items())}')
    mirror = built['reflexion']
    lines.append(f'reflexion: {mirror["share"]:.0%} conformant ({mirror["convergences"]} convergent, {mirror["divergences"]} '
                 f'divergent, {mirror["absences"]} absent dependencies between components)')
    decided = found['decisions']
    lines.append(f'decisions: {", ".join(f"{count} {state}" for state, count in decided["by_state"].items())}; '
                 f'{decided["proven"]} of {decided["accepted"]} accepted proven by a test; {decided["edited_records"]} '
                 f'record(s) edited after they were written')
    proved = found['validation']
    lines.append(f'validation: {", ".join(f"{count} {state}" for state, count in proved["by_state"].items()) or "none"}; '
                 f'{proved["needs_met"]} of {proved["needs"]} needs with a validation met')
    known = found['knowledge']
    lines.append(f'knowledge: {known["premises"]} premise(s), {known["high_unsettled"]} high-blast not confirmed, '
                 f'{known["refuted_assumed"]} refuted and still assumed')
    lines.append(f'check: {found["errors"]} error(s), {found["warnings"]} warning(s)')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/model', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    checked = commands.add_parser('check')
    checked.add_argument('--strict', action='store_true')
    commands.add_parser('view', help='print the component view (C4) as Mermaid, generated from the model')
    commands.add_parser('reflexion', help='list the convergent, divergent and absent dependencies between components')
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
        if args.command == 'view':
            print(view(objects()))
            return 0
        if args.command == 'reflexion':
            for name, pairs in reflexion(objects()).items():
                print(f'{name} ({len(pairs)}):')
                print('\n'.join(f'  {start} -> {end}' for start, end in pairs))
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
