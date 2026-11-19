"""The engineering model (PADRAO-DEV, docs/programs/padrao-dev/solucao.md): one graph of typed objects and typed links.

The metamodel is data in config/model/, one file per object type (types/), link type (links/), system (systems/) and
inventory source (inventory/), plus the conformance scale (conformance.json), each validated against its contract in
contracts/model/. The objects are read from where each system keeps them; F1a reads the ones that exist today:

  D     docs/domain/decisions/D-NNN.md (state accepted; its `proof:` file verifies it) and the older rows of
        docs/domain/DECISIONS.md (the state its Status cell says, the test files and cases its Proof cell names verify
        it when they all exist; row_proof)
  UNIT  units/<id>/unit.json (active; `requires` are depends-on links)
  TEST  scripts/tests/*.test.sh (active), each with the test files it runs as its parts, and the test files under
        scripts/tests/ that no script test runs (active, a test of their own)

  scripts/model check [--strict]   errors (exit 1) for a metamodel or object that breaks the model; warnings (a link to an
                                   object that does not exist, such as a decision proof that is gone) are counted, and
                                   are errors only with --strict
  scripts/model show <id>          one object: type, state, source, and its links out and in
  scripts/model reflexion          the dependencies between components: convergent, divergent, absent
  scripts/model view               the component view (C4 level 3) as Mermaid, generated from the model
  scripts/model seed-rules         writes config/standard/rules/<id>.json for every refusal, gate stage, D-069 principle
                                   and the method that has no rule yet (never rewrites a rule)
  scripts/model measure [--json F] the main metric (the share of active requirements whose chain is verified end to
                                   end), the requirement inventory, and each system's objects and calculated conformance,
                                   under a heading per group of systems (management, engineering: D-330), and the
                                   measurement system's share of sampled PRs with a clearly cheaper path (D-327);
                                   it first rebuilds a day-old run-durations snapshot from GitHub's checks (scripts/runs)

A requirement's chain is verified when an architecture element satisfies it, a unit realizes that element, a test
verifies the requirement, and a validation validates it or the need it derives from; a link whose only validations not
met are VAL-ladder-1 or VAL-escape-under-1, measuring, holds (D-331), and so does VAL-intention-ladder-1 while
VAL-ladder-1 is measuring (D-332). A merged change implements a requirement when one of its commits' `Implements:`
trailers names it, or when the requirement names it in `implemented_by` (D-332: history the trailer rule did not reach;
CHG-initial is the initial public tree, the root commit of HEAD). An object is conformant when a
rule judges it (a rule of its type, or the findings of its system), it breaks no check, every coverage rule of its
type (`covered_by`) holds and it is in no state or condition its type calls unconformant; an object no rule judges is known, not judged, and is not conformant. A system's conformance
is the share of its objects that are conformant, rated on the scale; a system with a significant weakness (a dependency
an advisory affects) is rated below F whatever its share.
"""
import argparse
import glob as globbing
import hashlib
import json
import os
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
VERIFIER = 'scripts/lib/verify_commit.py'  # tower/gate: its SKIPPED names the stages the live gate does not run (D-326)
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
        for condition in item.get('unconformant_when', []):
            if not condition:
                errors.append(f'type {name}: an unconformant_when condition names no field')
            extra = sorted(set(condition.get('state', [])) - states)
            if extra:
                errors.append(f'type {name}: unconformant_when state {", ".join(extra)} are not states of the type')
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
        index = {}
        for row in table_rows(table.read_text()):
            number = row['Id']
            if number in seen:
                continue
            seen.add(number)
            state = row_state(row.get('Status', ''))
            proof = row_proof(root, row.get('Proof', ''), index)
            item = _obj(number, 'D', state, DECISION_TABLE, row['line'])
            item['proof'] = {key: proof[key] for key in ('outcome', 'missing', 'outside')}
            objects.append(item)
            if state == 'accepted' and proof['outcome'] == 'proven':
                for name in proof['files']:
                    objects.append({'id': f'TEST:{name}', 'type': 'TEST', 'state': 'active', 'source': name,
                                    'claimed': True, 'fingerprint': None,
                                    'links': [{'type': 'verifies', 'target': number}]})
    return objects


def table_rows(text):
    """The rows of the decision tables of DECISIONS.md, each a {column: cell} by the names of its header row plus the
    whole `line` (the row's fingerprint); a column whose name starts with Proof is `Proof`. A table counts when its
    header names an Id column; a row counts when its Id is D-NNN, and one with as many cells as the first header with
    a Proof column takes that header's names. A cell never holds a pipe (decision_table.cell)."""
    rows, header, decisions = [], None, None
    lines = text.splitlines()
    for at, line in enumerate(lines):
        if not line.startswith('|'):
            header = None
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if header is None:
            following = lines[at + 1] if at + 1 < len(lines) else ''
            if 'Id' in cells and re.match(r'^\|[\s:|-]+\|?\s*$', following):
                header = ['Proof' if name.startswith('Proof') else name for name in cells]
            if header and 'Proof' in header and decisions is None:
                decisions = header
            continue
        if not header or not re.match(r'^D-[0-9]+$', cells[0]):
            continue
        # A decision row appended below another table (the Resolved questions) still has the register's columns.
        names = decisions if decisions and len(cells) == len(decisions) else header
        rows.append(dict(zip(names, cells), line=line))
    return rows


INACTIVE_ROW = {'superseded': 'superseded', 'replaced': 'superseded', 'retired': 'deprecated',
                'deprecated': 'deprecated'}


def row_state(status):
    """A row's state from its Status cell: one that starts with superseded or replaced is superseded, one that starts
    with retired or deprecated is deprecated (the D type's inactive states); any other status (proven, recorded, test
    pending, rite, implemented) is accepted."""
    word = re.match(r'\W*([a-z]+)', status.lower())
    return INACTIVE_ROW.get(word.group(1), 'accepted') if word else 'accepted'


PROOF_FILE = re.compile(r'(?<![\w./-])((?:[\w.-]+/)*(?:test_\w+\.py|[\w-]+(?:\.[\w-]+)*\.(?:test|spec)\.(?:sh|ts|tsx|js|mjs)))'
                        r'(?![\w/-])')
PROOF_QUOTED = re.compile(r'["“]([^"”]+)["”]')
PROOF_NAMED = re.compile(r'`((?:test|Test)\w*|[A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*)`')
PLACEHOLDERS = ('', '-', '—', 'none', 'n/a')
SKIPPED = {'node_modules', '.git', '.toolchain', '.gate', '.next', '__pycache__'}


def proof_refs(cell):
    """[(file, [cases])] the Proof cell names: every test file (test_*.py, *.test.*, *.spec.*), each with the cases named
    after it up to the next file or semicolon: the quoted names after a `›`, and the backticked test names (test_…,
    or a CamelCase class) after it or in its parentheses. Prose between them names nothing."""
    found = list(PROOF_FILE.finditer(cell))
    refs = []
    for at, match in enumerate(found):
        end = found[at + 1].start() if at + 1 < len(found) else len(cell)
        segment = cell[match.end():end].lstrip('`').split(';', 1)[0]
        cases = PROOF_QUOTED.findall(segment) if segment.lstrip().startswith('›') else []
        cases += [name for name in PROOF_NAMED.findall(segment) if name not in cases]
        refs.append((match.group(1), cases))
    return refs


def _resolve(root, name, index):
    """The repository path of a test file a proof names: the path itself, the same path under apps/web (the site's
    proofs were written relative to it), or the one file of the tree that ends with it; None when none or several."""
    root = Path(root)
    for candidate in (name, f'apps/web/{name}'):
        if (root / candidate).is_file():
            return candidate
    if '\0files' not in index:
        index['\0files'] = True
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIPPED and not d.startswith('.')]
            for file in files:
                index.setdefault(file, []).append((Path(folder) / file).relative_to(root).as_posix())
    matches = [path for path in index.get(Path(name).name, []) if path == name or path.endswith(f'/{name}')]
    return matches[0] if len(matches) == 1 else None


def _has_case(sources, case):
    """Whether a test holds the case, in its own file or in a test file it runs (`sources`: [(path, text)]): a Python
    test or class by its def/class, a shell function by its definition, a test title (quoted, `…` where it was cut) by
    every piece of it in the file."""
    for path, text in sources:
        if re.match(r'^[A-Za-z_]\w*$', case):
            if path.endswith('.py'):
                found = re.search(rf'^\s*(?:async\s+)?(?:def|class)\s+{case}\b', text, re.MULTILINE)
            elif path.endswith('.sh'):
                found = re.search(rf'^\s*(?:function\s+)?{case}\s*(?:\(\s*\)|\{{)', text, re.MULTILINE)
            else:
                found = re.search(rf'\b{case}\b', text)
            if found:
                return True
            continue
        pieces = [piece.strip() for piece in re.split(r'…|\.\.\.', case) if piece.strip()]
        if pieces and all(piece in text for piece in pieces):
            return True
    return False


def _runs(root, index):
    """{script test: [test files it runs]} (test_orphans.runners), read once per index."""
    if '\0runs' not in index:
        import test_orphans
        runs = {}
        for name, wrappers in test_orphans.runners(root).items():
            for wrapper in wrappers or ():
                runs.setdefault(wrapper, []).append(name)
        index['\0runs'] = runs
    return index['\0runs']


def in_model(root, path):
    """Whether a test file is a test object of the model (read_tests): an engine test, or a site test that declares
    what it verifies (D-319)."""
    if any(globbing.fnmatch.fnmatch(path, pattern.replace('**/', '*')) for pattern in TEST_GLOBS):
        return True
    return any(Path(path).match(pattern.replace('**/', '')) or globbing.fnmatch.fnmatch(path, pattern.replace('**/', '*'))
               for pattern in SITE_TESTS) and bool(VERIFIES.search((Path(root) / path).read_text(errors='replace')))


def row_proof(root, cell, index=None):
    """What a row's Proof cell proves: {outcome, files, missing, outside}. `proven` when it names at least one test file
    and every file and case it names exists and is a test of the model; `dangling` when a file or case it names does not
    exist (missing lists them as `file` or `file › case`); `outside` when they exist but a file is not a test of the
    model (a site test that declares nothing, D-319); `prose` when it names no test file; `none` when it is empty.
    Only the cell is read: nothing is inferred from elsewhere."""
    index = {} if index is None else index
    refs = proof_refs(cell)
    if not refs:
        return {'outcome': 'none' if cell.strip().strip('.').lower() in PLACEHOLDERS else 'prose', 'files': [],
                'missing': [], 'outside': []}
    files, missing, outside = [], [], []
    for name, cases in refs:
        path = _resolve(root, name, index)
        if path is None:
            missing.append(name)
            continue
        sources = [(part, (Path(root) / part).read_text(errors='replace'))
                   for part in [path, *(_runs(root, index).get(path, []) if cases else [])] if (Path(root) / part).is_file()]
        missing += [f'{name} › {case}' for case in cases if not _has_case(sources, case)]
        (files if in_model(root, path) else outside).append(path)
    outcome = 'dangling' if missing else 'outside' if outside else 'proven'
    return {'outcome': outcome, 'files': list(dict.fromkeys(files)), 'missing': missing,
            'outside': list(dict.fromkeys(outside))}


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
    (derived from the declared covers, never written twice). A test file a script test runs (test_orphans.runners,
    the reading of the gate's "gate maps" stage) is part of that script test, not a test of its own: the script test
    is what the gate selects and reports, so its object lists the file among its parts, its fingerprint covers the
    file's text and the file's `Verifies:` lines are its links. A test file no script test runs stays a test of its
    own, linked only by its own `Verifies:` lines."""
    import test_orphans
    root = Path(root)
    paths = sorted({Path(found) for pattern in TEST_GLOBS for found in globbing.glob(str(root / pattern), recursive=True)})
    run_by = {name: wrappers for name, wrappers in test_orphans.runners(root).items() if wrappers}
    texts = {}
    for path in paths:
        if path.is_file():
            texts[path.relative_to(root).as_posix()] = path.read_text(errors='replace')
    parts = {}
    for name, wrappers in sorted(run_by.items()):
        for wrapper in wrappers:
            if name in texts and wrapper in texts:
                parts.setdefault(wrapper, []).append(name)
    folded = {name for names in parts.values() for name in names}
    found = []
    for name, text in texts.items():
        if name in folded:
            continue
        mine = parts.get(name, [])
        whole = text + ''.join(f'\n{part}\n{texts[part]}' for part in mine)
        targets = [target.strip() for source in [text, *(texts[part] for part in mine)]
                   for listed in VERIFIES.findall(source) for target in listed.split(',') if target.strip()]
        item = _obj(f'TEST:{name}', 'TEST', 'active', name, whole,
                    [{'type': 'verifies', 'target': target} for target in dict.fromkeys(targets)])
        if mine:
            item['parts'] = mine
        found.append(item)
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


def skipped_stages(root):
    """The gate stages tower/gate skips: the literal SKIPPED of scripts/lib/verify_commit.py, read without importing it
    (D-326). No verifier, no skipped stage."""
    import ast
    path = Path(root) / VERIFIER
    if not path.is_file():
        return []
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'SKIPPED'
                                                for target in node.targets):
            return sorted(ast.literal_eval(node.value))
    return []


def skipped_stage_errors(found, root, skipped=None):
    """D-326: a rule marked blocking is one whose check tower/gate or the pre-push check runs, so a blocking gate-stage
    rule whose stage verify_commit skips is an error (the catalog would declare a control that does not operate): the
    rule is dormant, or the stage comes back."""
    skipped = skipped_stages(root) if skipped is None else skipped
    return [f'{item["id"]}: blocking, but tower/gate skips its stage {item["rule"]["check"]["ref"]} '
            f'({VERIFIER} SKIPPED): mark it dormant with dormant_by, or run the stage (D-326)'
            for item in sorted(found.values(), key=lambda item: item['id'])
            if item['type'] == 'STD' and 'rule' in item and item['state'] == 'blocking'
            and item['rule']['check']['kind'] == 'gate-stage' and item['rule']['check']['ref'] in skipped]


def rule_findings(found, root, stops=None, stages=None):
    """Warnings of the standard: a refusal or a gate stage with no rule, a rule whose check does not exist, a rule with
    no basis (a dormant rule needs none, D-326), a rule in warning with no deadline, a dormant rule that names no
    decision that stopped its tooling (dormant_by) and a dormant_by on a rule that is not dormant."""
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
        if not rule.get('basis') and rule['state'] != 'dormant':
            warnings.append(f'{item["id"]}: no decision justifies it (basis)')
        if rule['state'] == 'dormant' and not rule.get('dormant_by'):
            warnings.append(f'{item["id"]}: dormant with no decision that stopped its tooling (dormant_by)')
        if rule.get('dormant_by') and rule['state'] != 'dormant':
            warnings.append(f'{item["id"]}: dormant_by {rule["dormant_by"]} on a rule in {rule["state"]}')
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
CHALLENGE_STATE = {'open': 'open', 'escalated': 'open', 'changed': 'applied', 'lifted': 'applied', 'upheld': 'rejected'}  # rule_challenges.STATUSES
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
                      **({'derives_from': [need]} if need else {}),
                      **({'implemented_by': own['implemented_by']} if 'implemented_by' in own else {})}
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
    the status as the state, the radius and the record's path as the source id the inventory counts. The body says
    whether its radius blocks (premises.blocking_radii, veto V0) and whether it is settled the way a Premises: line
    reads it (a settled status, with the literal quote D-069 item 10 asks for); what the register refuses in the record
    (an answer that does not match the status, a radius below the computed one, a broken dependents seal) is a
    problem of the object."""
    import premises
    records, errors = premises.load(Path(root))
    found = []
    for ident, record in sorted(records.items()):
        path = Path(root) / record['path']
        item = _obj(ident, 'P', record['status'], record['path'], path.read_text() if path.is_file() else ident)
        item.update(source_id=record['path'], body={
            'radius': record.get('radius'), 'statement': record.get('statement'),
            'blocking': record.get('radius') in premises.setting('blocking_radii'),
            'settled': record['status'] in premises.setting('settled_statuses') and not premises.unquoted(record)})
        problems = [error.split(': ', 1)[1] for error in errors if error.startswith(record['path'] + ': ')]
        if problems:
            item['problems'] = problems
        found.append(item)
    return found


TRAILER_IMPLEMENTS = re.compile(r'^Implements:\s*(.+)$', re.MULTILINE)
PR_NUMBER = re.compile(r'#([0-9]+)')


def _git(root, *args):
    run = subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)
    return run.stdout if run.returncode == 0 else ''


def _changed_units(root):
    """{merge sha: [UNIT:<id>]}: the units whose paths each first-parent merge's diff (against its first parent)
    touched, matched with the unit graph's own matcher (units.units_of, the manifests of the working tree). One git
    call for every merge; a tree with no valid unit map derives nothing."""
    import units
    from config import ConfigError
    listed = _git(root, 'log', '--first-parent', '--merges', '--diff-merges=first-parent', '--name-only',
                  '--format=%x1e%H', 'HEAD')
    if not listed:
        return {}
    try:
        units.manifests(root)
    except (units.UnitError, ConfigError):
        return {}
    owners, result = {}, {}
    for block in listed.split('\x1e')[1:]:
        sha, *paths = block.split('\n')
        hit = []
        for path in filter(None, paths):
            if path not in owners:
                owners[path] = units.units_of(path, root)
            hit += owners[path]
        result[sha.strip()] = [f'UNIT:{unit}' for unit in sorted(set(hit))]
    return result


def read_changes(root):
    """Changes (CHG): every merge on the first-parent line of HEAD, one per pull request (CHG-<number>, else
    CHG-<sha>), merged; the `Implements:` trailers of its commits become implements links (requirements, decisions
    or units, comma-separated: intent), and each unit its diff touched becomes an implements link marked
    `source: diff` (a fact: the link type's "changes a unit"). Only a trailer or the requirement's own
    `implemented_by` (link_implemented_by, D-332) names a requirement, so a diff-derived link never implements one
    (`implemented`). The initial public tree is CHG-initial."""
    found = []
    touched = _changed_units(Path(root))
    for line in _git(root, 'log', '--first-parent', '--merges', '--format=%H%x1f%s', 'HEAD').splitlines():
        sha, _, subject = line.partition('\x1f')
        number = PR_NUMBER.search(subject)
        ident = f'CHG-{number.group(1)}' if number else f'CHG-{sha[:len("0123456789ab")]}'
        records = _git(root, 'log', '--format=%x1e%s%x1f%B', f'{sha}^1..{sha}').split('\x1e')[1:]
        bodies = ''.join(record.partition('\x1f')[2] for record in records)
        named = records[0].partition('\x1f')[2] if records else ''  # the merge's own message holds the PR title
        named += '\n'.join(record.partition('\x1f')[0] for record in records)
        targets = []
        for listed in TRAILER_IMPLEMENTS.findall(bodies):
            targets += [target.strip() for target in listed.split(',') if target.strip()]
        links = [{'type': 'implements', 'target': target} for target in dict.fromkeys(targets)]
        links += [{'type': 'implements', 'target': unit, 'source': 'diff'} for unit in touched.get(sha, [])
                  if unit not in targets]
        item = _obj(ident, 'CHG', 'merged', f'git:{sha}', sha, links)
        item['body'] = {'sha': sha, 'subject': subject, 'names': sorted(set(PHASE_ITEM_NAME.findall(named)))}
        found.append(item)
    # D-332: the initial public tree (the one root commit of HEAD, never a merge) is one merged change, CHG-initial;
    # a shallow clone's boundary is no root, so it reads none
    roots = _git(root, 'rev-list', '--max-parents=0', 'HEAD').split()
    if len(roots) == 1 and _git(root, 'rev-parse', '--is-shallow-repository').strip() == 'false':
        item = _obj(INITIAL_CHANGE, 'CHG', 'merged', f'git:{roots[0]}', roots[0], [])
        item['body'] = {'sha': roots[0], 'subject': _git(root, 'log', '-1', '--format=%s', roots[0]).strip()}
        found.append(item)
    return found


INITIAL_CHANGE = 'CHG-initial'


def link_implemented_by(found):
    """D-332: a requirement's `implemented_by` becomes an implements link from each change it names; a change that does
    not exist or is not merged is a problem of the requirement (an error of the model)."""
    for item in list(found.values()):
        if item['type'] != 'REQ':
            continue
        for target in item.get('body', {}).get('implemented_by', []):
            change = found.get(target, {})
            if change.get('type') == 'CHG' and change.get('state') in ('merged', 'deployed'):
                change['links'].append({'type': 'implements', 'target': item['id'], 'source': 'requirement'})
            else:
                item.setdefault('problems', []).append(f'implemented_by {target}, which is not a merged change')


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


def refresh_runs(found, root):
    """Before a measure (the CLI's, never check's or the gate's): each run-durations snapshot of a workflow GitHub's
    check runs hold (runs.CHECKS) is rebuilt from them when it is a day old (runs.refresh), so VAL-gate-60s does not go
    stale with no hand. Offline it keeps the recorded snapshot. The workflows whose snapshot was rewritten."""
    import runs
    done = []
    for item in found.values():
        measure = (item.get('body') or {}).get('measure') or {}
        if item['type'] != 'VAL' or measure.get('kind') != 'run-durations' or measure.get('workflow') not in runs.CHECKS:
            continue
        before = (runs.read(root, measure['workflow']) or {}).get('at')
        if (runs.refresh(root, measure['workflow']) or {}).get('at') != before:
            done.append(measure['workflow'])
    return done


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


def implemented(item, into, found):
    """Whether a merged (or deployed) change implements the requirement."""
    return any(kind == 'implements' and found.get(source, {}).get('state') in ('merged', 'deployed')
               for kind, source in into.get(item['id'], []))


def requirement_tested(item, into, found):
    """Whether the requirement is verified: a test that exists verifies it, or, for a requirement whose verification is
    a validation, a validation of its own is met. The one rule the chain, the coverage and the derived state use."""
    sources = into.get(item['id'], [])
    if any(kind == 'verifies' and found.get(source, {}).get('type') == 'TEST' and
           found[source].get('fingerprint') is not None for kind, source in sources):
        return True
    return item.get('body', {}).get('verification') == 'validation' and any(
        kind == 'validates' and found.get(source, {}).get('type') == 'VAL' and found[source]['state'] == 'met'
        for kind, source in sources)


def requirement_states(found):
    """{requirement id: derived state}: implemented when a merged change implements it, verified when it is also
    verified (requirement_tested; the verdicts on main join with the verification phase), else its declared state."""
    into = incoming(found)
    states = {}
    for item in found.values():
        if item['type'] != 'REQ' or item['state'] in ('superseded', 'obsolete'):
            continue
        done = implemented(item, into, found)
        states[item['id']] = ('verified' if done and requirement_tested(item, into, found) else
                              'implemented' if done else item['state'])
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
    declared and not present, each a sorted list of (from, to). Only components are its nodes: a capability (CAP-NNN)
    a unit also realizes is what the unit does, not a layer, so it declares no dependency and takes none from its
    units (they already count through the component the same unit realizes)."""
    components = {id for id, item in found.items() if item['type'] == 'ARC' and item.get('body', {}).get('kind') == 'component'}
    realized = {id: [link['target'] for link in item['links'] if link['type'] == 'realizes' and link['target'] in components]
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
    """The decisions system's own measure: decisions by state, the accepted ones a test proves, the decision
    records edited after the commit that wrote them (an accepted decision changes by a new one that supersedes it), and
    the accepted rows of DECISIONS.md by what their Proof cell proves (row_proof), when there are any."""
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
    rows = {}
    for item in accepted:
        if 'proof' in item:
            rows[item['proof']['outcome']] = rows.get(item['proof']['outcome'], 0) + 1
    return {'by_state': dict(sorted(by_state.items())), 'accepted': len(accepted), 'proven': proven,
            'edited_records': edited, **({'table_proofs': dict(sorted(rows.items()))} if rows else {})}


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
    (scripts/lib/queue_checks.py): staged, installed or required. What queue_checks refuses of a check (required with no
    installed job that runs it, an installed workflow that differs from its staged copy) is a problem of that check."""
    import queue_checks
    refusals = queue_checks.check(root)
    found = []
    for entry in queue_checks.checks(root):
        source = (f'{queue_checks.INSTALLED}/{entry["workflow"]}' if entry['installed'] else
                  f'{queue_checks.STAGED}/{entry["workflow"]}' if entry['workflow'] else entry['required_by'])
        item = _obj(queue_checks.check_id(entry['name']), 'CHK', entry['state'], source, json.dumps(entry, sort_keys=True))
        item['body'] = entry
        mine = (f'check {entry["name"]}: ',) + ((f'{queue_checks.INSTALLED}/{entry["workflow"]}: ',)
                                                 if entry['workflow'] else ())
        problems = [error.split(': ', 1)[1] for error in refusals if error.startswith(mine)]
        if problems:
            item['problems'] = problems
        found.append(item)
    return found


# The four results slo.evaluate folds from the forge event log, as (registry entry, bound); their limits are the entries.
SLO_MEASURES = (('slo.gate_tier1_p95_s', 'max'), ('slo.train_queue_time_p95_s', 'max'),
                ('slo.merged_prs_per_hour_min', 'min'), ('slo.gate_failure_rate_max_percent', 'max'))
SLO_REGISTRY = 'config/registry/slo.json'
SLO_CONSUMER = 'docs/process/EVENTS.md'  # slo.breached, the event a breach emits, asks a PR there
BASE_KINDS = ('incident-count', 'code-scan')  # a count of one attribute (15939 base measure); the rest derive one


def _measure_id(val_id, measure):
    qualifier = next((measure[key] for key in ('name', 'workflow', 'incident', 'trailer') if measure.get(key)),
                     val_id.removeprefix('VAL-'))
    return f'MEAS-{measure["kind"]}-{_slug(qualifier)}'


def _measure(id, state, source, body):
    item = _obj(id, 'MEAS', state, source, json.dumps(body, sort_keys=True))
    item['body'] = body
    return item


def read_measures(root):
    """Measures (MEAS, the Measurement system) with their ISO/IEC/IEEE 15939 metadata, read from what already defines
    them: the four SLOs of the registry (config/registry/slo.json, folded by scripts/lib/slo.py), the measure of every
    validation (config/validation/, computed by measured()) and the cheaper-path measure (D-327, the retrospective
    samples). Each body says its information need, its consumer, whether it is base or derived, its function and its
    decision criterion. A validation measure with no function wired (kind `unwired`) is proposed. Freshness is set by
    derive_measures: an SLO's source is the forge event log, which HEAD does not hold, so it is never fresh here."""
    root = Path(root)
    found = []
    registry = _read_json(root / SLO_REGISTRY).get('properties', {}) if (root / SLO_REGISTRY).is_file() else {}
    for name, bound in SLO_MEASURES:
        entry = registry.get(name)
        if entry is None:
            continue
        found.append(_measure(f'MEAS-{_slug(name.removeprefix("slo."))}', 'active', SLO_REGISTRY, {
            'need': entry.get('description', ''), 'consumer': SLO_CONSUMER if SLO_CONSUMER in entry.get('x-readers', []) else '',
            'scale': 'derived', 'function': 'scripts/lib/slo.py evaluate', 'unit': entry.get('x-unit', ''),
            'criterion': f'{bound} {entry.get("default")}', 'source': 'the forge event log', 'fresh': False}))
    seen = set()
    for path in sorted(root.glob(VALIDATIONS)):
        body = _read_json(path)
        if not isinstance(body, dict) or not isinstance(body.get('measure'), dict) or 'kind' not in body['measure']:
            continue  # read_validations says what is wrong with the file
        measure = body['measure']
        id = _measure_id(body['id'], measure)
        if id in seen:
            continue
        seen.add(id)
        wired = measure['kind'] != 'unwired'
        found.append(_measure(id, 'active' if wired else 'proposed', path.relative_to(root).as_posix(), {
            'need': body.get('statement', ''), 'consumer': body.get('owner', ''),
            'scale': 'base' if measure['kind'] in BASE_KINDS else 'derived',
            'function': f'scripts/lib/model.py measured ({measure["kind"]})' if wired else '',
            'criterion': f'{body.get("comparator", "")} {body.get("threshold", "")}'.strip(), 'validation': body['id'],
            'fresh': False}))
    cheaper = cheaper_path_measure(root)
    found.append(_measure('MEAS-cheaper-path', 'active', RETRO_SAMPLES, {
        'need': 'D-327: was there a clearly cheaper path that solved it?', 'consumer': 'the retrospective (administration)',
        'scale': 'derived', 'function': 'scripts/lib/model.py cheaper_path_measure', 'unit': 'share of sampled PRs',
        'criterion': f'lt {cheaper["target"]}', 'fresh': cheaper['prs'] > 0}))
    return found


def derive_measures(found):
    """After the validations are derived: each validation is measured by its measure, which is fresh while the
    validation holds a value (any state but defined)."""
    for item in found.values():
        validation = (item.get('body') or {}).get('validation') if item['type'] == 'MEAS' else None
        if validation in found:
            item['body']['fresh'] = found[validation]['state'] != 'defined'
            found[validation]['links'].append({'type': 'measured-by', 'target': item['id']})


PHASE_ITEM = re.compile(r'^[0-9]+\. \*\*(F[0-9]+[a-z])\b([^*]*)\*\*(.*)$', re.MULTILINE)  # a Padrão v8 phase plan item
PHASE_TITLE = re.compile(r'^# (.+)$', re.MULTILINE)
PHASE_ITEM_NAME = re.compile(r'\b(F[0-9]+[a-z])\b')
QUEUE_FILE = 'docs/programs/vazao/fila.md'  # lane.QUEUE: its active table starts with `| # |`


def _work(id, state, source, body):
    item = _obj(id, 'WORK', state, source, json.dumps(body, sort_keys=True))
    item['body'] = body
    return item


def _queue_rows(text):
    """[(unit, scope)] of the queue's active table (the one whose header starts with `| # |`; lane.queue_rows)."""
    rows, header = [], None
    for line in text.splitlines():
        if line.startswith('| # |'):
            header = [cell.strip() for cell in line.strip('|').split('|')]
            continue
        if header is None:
            continue
        if not line.startswith('|'):
            break
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if cells and cells[0] and not set(cells[0]) <= {'-'}:
            rows.append((cells[0], dict(zip(header, cells))))
    return rows


def read_work(root):
    """Work items (WORK, the Work system), read from what already plans the work: every program folder under
    coordinator.programs_dir (the template excluded), the units of its plan (the coordinator.plan_fence block of
    plan.md), the numbered items of its phases (`N. **F7e, ...**`, Padrão v8) and the open rows of the queue
    (docs/programs/vazao/fila.md). Each body says what the item delivers (a unit's done criteria, an item's text, a row's
    scope). A unit is delivered when its plan records its PR; a phase item when a merge on HEAD names it
    (derive_work); the rest are queued. A plan that does not parse is a problem of its program."""
    import config
    root = Path(root)
    folder = root / config.get('coordinator.programs_dir')
    template, plan_file, fence = (config.get(f'coordinator.{key}') for key in ('template_dir', 'plan_file', 'plan_fence'))
    found = []
    for program in sorted(path for path in folder.iterdir() if path.is_dir() and path.name != template) if folder.is_dir() else ():
        items, problems = [], []
        plan = program / plan_file
        if plan.is_file():
            block = re.search(r'^```' + re.escape(fence) + r'[ \t]*\n(.*?)^```[ \t]*$', plan.read_text(), re.M | re.S)
            try:
                units = json.loads(block.group(1))['units'] if block else []
            except (ValueError, KeyError, TypeError) as error:
                units, problems = [], [f'{plan.name}: its {fence} block does not parse ({error})']
            for unit in units if isinstance(units, list) else ():
                if not isinstance(unit, dict) or 'id' not in unit:
                    continue
                items.append(_work(f'WORK-{program.name}-{unit["id"]}', 'delivered' if unit.get('pr') else 'queued',
                                   plan.relative_to(root).as_posix(),
                                   {'program': program.name, 'kind': 'unit', 'title': unit.get('title', ''),
                                    'delivers': bool(unit.get('done')), 'pr': unit.get('pr')}))
        for phase in sorted((program / 'phases').glob('*.md')):
            text = phase.read_text()
            listed = PHASE_ITEM.findall(text)
            for short, named, rest in listed:
                said = ' '.join(part.strip(' ,:') for part in (named, rest) if part.strip(' ,:'))
                items.append(_work(f'WORK-{program.name}-{short}', 'queued', phase.relative_to(root).as_posix(),
                                   {'program': program.name, 'kind': 'phase-item', 'short': short,
                                    'delivers': bool(said), 'text': said}))
            if not listed:  # a phase that lists no items is one item itself, its title what it delivers
                title = PHASE_TITLE.search(text)
                items.append(_work(f'WORK-{program.name}-{phase.stem}', 'queued', phase.relative_to(root).as_posix(),
                                   {'program': program.name, 'kind': 'phase', 'delivers': bool(title),
                                    'text': title.group(1) if title else ''}))
        queue = root / QUEUE_FILE
        if queue.parent == program and queue.is_file():
            for unit, row in _queue_rows(queue.read_text()):
                items.append(_work(f'WORK-{program.name}-{unit}', 'queued', QUEUE_FILE,
                                   {'program': program.name, 'kind': 'queue-row',
                                    'delivers': bool(row.get('Escopo (arquivos)') or row.get('Valor'))}))
        program_item = _work(f'WORK-program-{program.name}', 'queued', program.relative_to(root).as_posix(),
                             {'program': program.name, 'kind': 'program', 'delivers': bool(items)})
        if problems:
            program_item['problems'] = problems
        found += [program_item, *items]
    return found


def derive_work(found):
    """A merge that names a phase item (its PR title or a commit subject, `F7d`) tracks it, and the item is delivered;
    a name two programs share links nothing. A program is delivered when every item is, in progress when some are."""
    phase_items = {}
    for id, item in found.items():
        if item['type'] == 'WORK' and (item.get('body') or {}).get('kind') == 'phase-item':
            phase_items.setdefault(item['body']['short'], []).append(id)
    for id, item in found.items():
        if item['type'] != 'CHG':
            continue
        for name in (item.get('body') or {}).get('names', []):
            if len(phase_items.get(name, [])) == 1:
                item['links'].append({'type': 'tracks', 'target': phase_items[name][0]})
                found[phase_items[name][0]]['state'] = 'delivered'
    programs = {}
    for item in found.values():
        if item['type'] == 'WORK' and item['body']['kind'] != 'program':
            programs.setdefault(item['body']['program'], []).append(item['state'] == 'delivered')
    for item in found.values():
        if item['type'] == 'WORK' and item['body']['kind'] == 'program':
            done = programs.get(item['body']['program'], [])
            item['state'] = 'delivered' if done and all(done) else 'in-progress' if any(done) else 'queued'


READERS = (read_decisions, read_units, read_tests, read_rules, read_proposals, read_versions, read_tailoring,
           read_intent, read_requirements, read_premises, read_changes, read_architecture, read_adrs, read_validations,
           read_suppliers, read_dependencies, read_advisories, read_checks, read_data, read_requests,
           read_risks, read_controls, read_vulns, read_threats, read_measures, read_work)


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
    fold_parts(found)
    if read_requirements in readers and read_changes in readers:
        link_implemented_by(found)
    if read_validations in readers:
        derive_validations(found, root)
    if read_controls in readers:
        derive_controls(found)
    if read_measures in readers:
        derive_measures(found)
    if read_work in readers:
        derive_work(found)
    return found


def fold_parts(found):
    """A link to a test file a script test runs (a decision's proof, a control's implemented-by) is a link to that
    script test: the file is one of its parts (read_tests), not an object of its own. The claimed object the link made
    is dropped and its links move to every script test that runs the file; a link that targets the file is retargeted."""
    owners = {}
    for item in found.values():
        for part in item.get('parts', ()):
            owners.setdefault(f'TEST:{part}', []).append(item['id'])
    if not owners:
        return
    for id in [id for id in owners if id in found and found[id].get('claimed') and found[id].get('fingerprint') is None]:
        claimed = found.pop(id)
        for owner in owners[id]:
            found[owner]['links'] += [dict(link) for link in claimed['links']]
    for item in found.values():
        if any(link['target'] in owners for link in item['links']):
            item['links'] = [{**link, 'target': owner} for link in item['links']
                             for owner in owners.get(link['target'], [link['target']])]


def check(meta, found, root=None, today=None):
    """(errors, warnings) of the objects against the metamodel; with `root`, also the warnings of the standard."""
    errors, warnings = [], []
    if root is not None:
        warnings += rule_findings(found, root)
        errors += skipped_stage_errors(found, root)
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
        for missing in (item.get('proof') or {}).get('missing', []):
            warnings.append(f'{id}: its proof names {missing}, which does not exist ({item["source"]})')
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


# Types check() judges through the findings of their own system, not through a rule of the type (rule_findings judges a
# rule of the standard; management_findings a proposal, an exemption and the version in effect).
JUDGED_BY_FINDINGS = {'STD': 'rule_findings', 'PROP': 'management_findings', 'TAIL': 'management_findings',
                      'VER': 'management_findings'}
# A significant weakness (ISO/IEC 33020 F: "no significant weaknesses"): while an active object is in one of these
# states its system is rated below F, however small a share it is (a dependency an advisory affects, not exempted).
WEAKNESS_STATES = {'DEP': ('vulnerable',)}
# The verdict type that would say whether a type's objects pass; while it has no object, the measure says so.
VERDICTS = {'TEST': ('VERD', 'linked to what they verify')}


def judged(meta, type_id):
    """Whether any rule judges the objects of a type: a rule of the type (`must_link`, `covered_by`,
    `unconformant_states`, `unconformant_when`) or the findings of its system. An object no rule judges is known, not judged (ISO/IEC 33020
    N: little or no evidence of achievement), and is never counted conformant."""
    kind = meta['types'].get(type_id, {})
    return (any(kind.get(key) for key in ('must_link', 'covered_by', 'unconformant_states', 'unconformant_when'))
            or type_id in JUDGED_BY_FINDINGS)


def meets(condition, item):
    """Whether an object meets one `unconformant_when` condition: every field it names (`state`, else a field of the
    object's body) holds one of the condition's values."""
    body = item.get('body') or {}
    return all((item['state'] if field == 'state' else body.get(field)) in values for field, values in condition.items())


def covered(meta, item, into, found):
    """Whether every coverage rule (`covered_by`) and every required outgoing link (`must_link`) of the type holds, and
    the object is in no unconformant state or condition (`unconformant_states`, `unconformant_when`). A
    requirement's test rule is requirement_tested, the rule the chain uses (a met validation of its own counts when its
    verification is a validation)."""
    if item['state'] in meta['types'][item['type']].get('unconformant_states', []):
        return False
    if any(meets(condition, item) for condition in meta['types'][item['type']].get('unconformant_when', [])):
        return False
    held = {link['type'] for link in item['links'] if found.get(link['target'], {}).get('fingerprint') is not None}
    if set(meta['types'][item['type']].get('must_link', [])) - held:
        return False
    for rule in meta['types'][item['type']].get('covered_by', []):
        if item['type'] == 'REQ' and (rule['type'], rule['link']) == ('TEST', 'verifies'):
            if not requirement_tested(item, into, found):
                return False
            continue
        if not any(kind == rule['link'] and found.get(source, {}).get('type') == rule['type'] and
                   found[source].get('fingerprint') is not None
                   for kind, source in into.get(item['id'], [])):
            return False
    return True


# D-331: these validations are measured after the program's stop criterion; while one is measuring (never while it
# is not met) a requirement whose only open link is that validation counts as verified end to end.
MEASURED_AFTER = ('VAL-ladder-1', 'VAL-escape-under-1', 'VAL-intention-ladder-1')
# D-332: a validation of MEASURED_AFTER named here waits on the one it names instead of its own state:
# VAL-intention-ladder-1 is all of the ladder's validations met at once, so it cannot be met while VAL-ladder-1 is
# measuring, and it counts (met or not) once VAL-ladder-1 is no longer measuring.
WAITS_ON = {'VAL-intention-ladder-1': 'VAL-ladder-1'}


def _waiting(source, found):
    """Whether a validation is one of MEASURED_AFTER still waiting: measuring, or, for one of WAITS_ON, not met while
    the validation it waits on is measuring."""
    if source not in MEASURED_AFTER:
        return False
    if source in WAITS_ON:
        return found[source]['state'] != 'met' and found.get(WAITS_ON[source], {}).get('state') == 'measuring'
    return found[source]['state'] == 'measuring'


def _only_measured_after(validations, found):
    """Whether every validation of the list is met or one of MEASURED_AFTER that is waiting, and one of them is."""
    waiting = [source for source in validations if _waiting(source, found)]
    return bool(waiting) and all(found[source]['state'] == 'met' or source in waiting for source in validations)


def chain_verified(item, into, found):
    """A requirement's chain: element satisfies it, a unit realizes the element, a merged change implements it, it is
    verified (requirement_tested), a validation validates it or the need it derives from. D-331: a validation link
    (or, for a requirement verified by validation, the verification link) whose only validations not met are of
    MEASURED_AFTER and measuring holds."""
    def sources(target, link, kind):
        return [source for name, source in into.get(target, []) if name == link and found.get(source, {}).get('type') == kind]
    elements = sources(item['id'], 'satisfies', 'ARC')
    realized = any(sources(element, 'realizes', 'UNIT') for element in elements)
    own = sources(item['id'], 'validates', 'VAL')
    tested = requirement_tested(item, into, found) or (
        item.get('body', {}).get('verification') == 'validation' and _only_measured_after(own, found))
    needs = [link['target'] for link in item['links'] if link['type'] == 'derives-from']
    validations = list(dict.fromkeys(source for target in [item['id'], *needs]
                                     for source in sources(target, 'validates', 'VAL')))
    validated = any(found[source]['state'] == 'met' for source in validations) or _only_measured_after(validations, found)
    return bool(elements) and realized and implemented(item, into, found) and tested and validated


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
    decision that justifies them, and those in warning past their deadline (dates as YYYY-MM-DD). A dormant rule (D-326)
    counts in none of them, only in `dormant`."""
    into = incoming(found)
    rules = [item for item in found.values() if item['type'] == 'STD' and 'rule' in item
             and item['state'] not in ('replaced', 'dormant')]
    def tested(item):
        return any(kind == 'verifies' and found.get(source, {}).get('fingerprint') is not None
                   for kind, source in into.get(item['id'], []))
    return {
        'rules': len(rules),
        'executable': sum(1 for item in rules if item['rule']['check']['kind'] != 'judgment'),
        'tested': sum(1 for item in rules if tested(item)),
        'justified': sum(1 for item in rules if item['rule'].get('basis')),
        'overdue': sum(1 for item in rules if item['state'] == 'warning' and item['rule'].get('deadline', today) < today),
        'dormant': sum(1 for item in found.values() if item['type'] == 'STD' and 'rule' in item
                       and item['state'] == 'dormant'),
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


def measures_measure(found):
    """The measurement system's own counts: its measures, those with a value on HEAD, those proposed (no function
    wired) and those whose source HEAD does not hold (the SLOs' forge event log)."""
    measures = [item for item in found.values() if item['type'] == 'MEAS']
    return {'measures': len(measures), 'fresh': sum(1 for item in measures if item['body']['fresh']),
            'proposed': sum(1 for item in measures if item['state'] == 'proposed'),
            'unread': sum(1 for item in measures if item['body'].get('source') == 'the forge event log')}


def work_measure(found):
    """The work system's own counts: programs, their items by state, and the items a merge on HEAD tracks."""
    work = [item for item in found.values() if item['type'] == 'WORK']
    items = [item for item in work if item['body']['kind'] != 'program']
    by_state = {}
    for item in items:
        by_state[item['state']] = by_state.get(item['state'], 0) + 1
    tracked = {link['target'] for item in found.values() if item['type'] == 'CHG' for link in item['links']
               if link['type'] == 'tracks'}
    return {'programs': len(work) - len(items), 'items': len(items), 'by_state': dict(sorted(by_state.items())),
            'tracked': len(tracked)}


RETRO_SAMPLES = 'docs/programs/*/retro-sample-*.json'
CHEAPER_TARGET = 0.10  # D-327: under 10 %, reviewed after three retrospectives


def cheaper_path_measure(root=ROOT):
    """The measurement system's D-327 measure (management group, D-330): over the PRs the retrospectives sample
    (docs/programs/<program>/retro-sample-<n>.json, contracts/model/retro-sample.v1.json), the share whose answer to
    "was there a clearly cheaper path that solved it?" is yes; share None when there is no sample yet. A sample that
    breaks its contract is a problem, counted as a model error, and left out of the share."""
    root = Path(root)
    schema = _read_json(root / CONTRACTS_DIR / 'retro-sample.v1.json')
    samples, problems = [], []
    for path in sorted(root.glob(RETRO_SAMPLES)):
        body = _read_json(path)
        broken = list(json_schema.validate(schema, body))
        if isinstance(body, dict) and body.get('id') != path.stem:
            broken.append(f'its id must equal the file name {path.stem}')
        if broken:
            problems += [f'{path.relative_to(root).as_posix()}: {problem}' for problem in broken]
            continue
        samples.append(body)
    prs = [pr for body in samples for pr in body['prs']]
    cheaper = sum(1 for pr in prs if pr['cheaper'])
    share = cheaper / len(prs) if prs else None
    return {'samples': len(samples), 'prs': len(prs), 'cheaper': cheaper, 'share': share, 'target': CHEAPER_TARGET,
            'met': None if share is None else share < CHEAPER_TARGET, 'problems': problems}


def cheaper_path_line(item):
    """The summary line of cheaper_path_measure."""
    head = 'measurement: cheaper path (D-327): '
    if item['share'] is None:
        return head + f'no sample (target under {item["target"]:.0%})'
    return head + (f'{item["cheaper"]} of {item["prs"]} sampled PR(s) in {item["samples"]} retrospective(s) had a '
                   f'clearly cheaper path ({item["share"]:.0%}), target under {item["target"]:.0%}: '
                   f'{"met" if item["met"] else "not met"}')


def utc_today():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).date().isoformat()


def rate_system(meta, found, into, flagged, name):
    """One system's conformance: its active objects, those a rule judges and pass every rule, the share, the level
    (below F while a significant weakness stands), the types no rule judges and the verdict types not read."""
    kinds = {type_id for type_id, kind in meta['types'].items() if kind['system'] == name}
    mine = [item for item in found.values() if item['type'] in kinds and is_active(meta, item)
            and item.get('fingerprint') is not None]
    unjudged = sorted({item['type'] for item in mine if not judged(meta, item['type'])})
    good = sum(1 for item in mine if judged(meta, item['type']) and item['id'] not in flagged
               and covered(meta, item, into, found))
    share = good / len(mine) if mine else 0
    level = rate(share, meta['scale'])
    weak = sum(1 for item in mine if item['state'] in WEAKNESS_STATES.get(item['type'], ()))
    levels = [step['level'] for step in meta['scale']]
    if weak and level == levels[-1] and len(levels) > 1:
        level = levels[levels.index(level) - 1]
    unread = {type_id: {'verdict': VERDICTS[type_id][0], 'means': VERDICTS[type_id][1]}
              for type_id in sorted(kinds & set(VERDICTS))
              if not any(item['type'] == VERDICTS[type_id][0] for item in found.values())}
    return {'group': meta['systems'][name].get('group', ''), 'objects': len(mine), 'conformant': good,
            'share': share, 'level': level,
            'not_judged': sum(1 for item in mine if item['type'] in unjudged), 'unjudged_types': unjudged,
            'weaknesses': weak, 'verdicts_unread': unread}


def assessment(name, rated, sha):
    """The conformance assessment (ASSESS) of one system on a sha, calculated from its rating: it rests on evidence
    when at least one of the system's objects is judged by a rule (ISO/IEC 33020 N: little or no evidence otherwise)."""
    body = {'system': name, 'sha': sha, 'level': rated['level'], 'share': rated['share'], 'objects': rated['objects'],
            'evidence': rated['objects'] - rated['not_judged'] > 0}
    item = _obj(f'ASSESS-{name}', 'ASSESS', 'calculated', 'scripts/model measure', json.dumps(body, sort_keys=True))
    item['body'] = body
    return item


def assess_systems(meta, found, into, flagged, root):
    """{system: rating} and the found objects with one assessment per system on HEAD. The systems that manage the
    assessment type (conformance) are rated after the others are assessed, and their own assessment last, so the
    conformance system's level is the share of systems assessed on evidence."""
    sha = _git(root, 'rev-parse', 'HEAD').strip()
    assessors = {meta['types']['ASSESS']['system']} if 'ASSESS' in meta['types'] else set()
    systems = {name: rate_system(meta, found, into, flagged, name) for name in sorted(meta['systems'])}
    found = {**found, **{f'ASSESS-{name}': assessment(name, systems[name], sha) for name in systems
                         if name not in assessors}}
    for name in sorted(assessors):
        systems[name] = rate_system(meta, found, into, flagged, name)
        found[f'ASSESS-{name}'] = assessment(name, systems[name], sha)
    for name in sorted(assessors):
        systems[name] = rate_system(meta, found, into, flagged, name)
    return systems, found


def measure(root=ROOT, meta=None, found=None, today=None):
    meta = meta or metamodel(root)
    found = found if found is not None else objects(root)
    errors, warnings = check(meta, found, root, today)
    flagged = {line.split(':', 1)[0] for line in errors + warnings}
    into = incoming(found)
    requirements = [item for item in found.values() if item['type'] == 'REQ' and is_active(meta, item)]
    verified = sum(1 for item in requirements if chain_verified(item, into, found))
    systems, found = assess_systems(meta, found, into, flagged, root)
    sources = inventory(meta, found, root)
    cheaper_path = cheaper_path_measure(root)
    return {
        'chain': {'active_requirements': len(requirements), 'verified': verified,
                  'share': verified / len(requirements) if requirements else 0},
        'inventory': {'sources': sources, 'ids': sum(item['ids'] for item in sources.values()),
                      'imported': sum(item['imported'] for item in sources.values())},
        'systems': systems,
        'groups': {group: {'systems': names, 'levels': {step['level']: count for step in reversed(meta['scale'])
                                                        if (count := sum(1 for name in names
                                                                         if systems[name]['level'] == step['level']))}}
                   for group, names in system_groups(systems).items()},
        'standard': standard_measure(found, today or utc_today()),
        'standard_management': management_measure(found, today or utc_today()),
        'knowledge': knowledge_measure(found),
        'requirements': requirements_measure(found),
        'architecture': architecture_measure(found),
        'decisions': decisions_measure(found, root),
        'validation': validation_measure(found),
        'measurement': {'cheaper_path': cheaper_path, **measures_measure(found)},
        'work': work_measure(found),
        'objects': len(found),
        'errors': len(meta['errors']) + len(errors) + len(cheaper_path['problems']),
        'warnings': len(warnings),
    }


def show(id, root=ROOT):
    found = objects(root)
    item = found.get(id)
    if item is None:
        raise ModelError(f'{id}: no such object')
    lines = [f'{item["id"]}  {item["type"]}  {item["state"]}  {item["source"]}']
    lines += [f'  part {part}' for part in item.get('parts', ())]
    lines += [f'  -> {link["type"]} {link["target"]}' for link in item['links']]
    lines += [f'  <- {kind} {source}' for kind, source in sorted(incoming(found).get(id, []))]
    return '\n'.join(lines)


GROUPS = ('management', 'engineering')  # D-330: contracts/model/system.v1.json's `group`, in the order measure reports them


def system_groups(systems):
    """{group: [system names]} in GROUPS order, then a system with no group under ''; D-330."""
    order = {group: index for index, group in enumerate(GROUPS)}
    grouped = {}
    for name in sorted(systems, key=lambda name: (order.get(systems[name].get('group', ''), len(order)), name)):
        grouped.setdefault(systems[name].get('group', ''), []).append(name)
    return grouped


def system_line(item):
    """What a system's count means: conformant, or, for a type whose verdicts are not read, what is counted; the
    objects no rule judges; the significant weaknesses that keep it below F."""
    counted = 'conformant'
    for unread in item.get('verdicts_unread', {}).values():
        counted = f'{unread["means"]}; pass state not read: no {unread["verdict"]} source'
    parts = [f'{item["conformant"]} of {item["objects"]} {counted}']
    if item.get('not_judged'):
        parts.append(f'{item["not_judged"]} not judged: no rule of {", ".join(item["unjudged_types"])}')
    if item.get('weaknesses'):
        parts.append(f'{item["weaknesses"]} significant weakness(es), below F whatever the share')
    return '; '.join(parts)


def summary(found):
    chain, stock = found['chain'], found['inventory']
    lines = [
        f'chain: {chain["verified"]} of {chain["active_requirements"]} active requirement(s) verified end to end '
        f'({chain["share"]:.0%})',
        f'inventory: {stock["imported"]} of {stock["ids"]} requirement id(s) of the inventory are objects of the model',
    ]
    lines += [f'  {name}: {item["imported"]} of {item["ids"]}' for name, item in stock['sources'].items()]
    lines.append(f'systems ({found["objects"]} object(s)):')
    for group, item in found['groups'].items():  # D-330: each group's levels apart
        counted = ', '.join(f'{count} {level}' for level, count in item['levels'].items())
        lines.append(f'  {group or "no group"} ({len(item["systems"])} system(s): {counted}):')
        lines += [f'    {name}: {found["systems"][name]["level"]} ({system_line(found["systems"][name])})'
                  for name in item['systems']]
    rules = found['standard']
    lines.append(f'standard: {rules["rules"]} rule(s), {rules["executable"]} with an executable check, {rules["tested"]} '
                 f'verified by a test, {rules["justified"]} justified by a decision, {rules["overdue"]} in warning past '
                 f'their deadline; {rules["dormant"]} dormant (D-326)')
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
                 f'record(s) edited after they were written'
                 + (f'; table rows by proof: {", ".join(f"{count} {kind}" for kind, count in decided["table_proofs"].items())}'
                    if decided.get('table_proofs') else ''))
    proved = found['validation']
    lines.append(f'validation: {", ".join(f"{count} {state}" for state, count in proved["by_state"].items()) or "none"}; '
                 f'{proved["needs_met"]} of {proved["needs"]} needs with a validation met')
    known = found['knowledge']
    lines.append(f'knowledge: {known["premises"]} premise(s), {known["high_unsettled"]} high-blast not confirmed, '
                 f'{known["refuted_assumed"]} refuted and still assumed')
    counted = found['measurement']
    lines.append(f'measurement: {counted["measures"]} measure(s), {counted["fresh"]} fresh on HEAD, {counted["proposed"]} '
                 f'proposed (no function wired), {counted["unread"]} whose source HEAD does not hold')
    lines.append(cheaper_path_line(found['measurement']['cheaper_path']))
    planned = found['work']
    lines.append(f'work: {planned["programs"]} program(s), {planned["items"]} item(s): '
                 f'{", ".join(f"{count} {state}" for state, count in planned["by_state"].items()) or "none"}; '
                 f'{planned["tracked"]} tracked by a merge on HEAD')
    lines += [f'  ERROR {problem}' for problem in found['measurement']['cheaper_path']['problems']]
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
        if refresh_runs(found, ROOT):
            derive_validations(found, ROOT)  # the states objects() derived read the snapshot before it was renewed
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
