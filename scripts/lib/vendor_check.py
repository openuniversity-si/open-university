"""The engine vendor check (D-069 item 7, plan v3.1 R1), a module of scripts/structure-check.

The vendor catalog (providers.vendor_catalog, validated by providers.vendor_catalog_schema) names each vendor the
engine may call and how a call to it is recognized. check(root, base) scans the engine paths the literal check scans
(config.literal_check_*: scripts/, minus providers.vendor_check_excludes: tests and generated types) and returns (errors, warnings). A call is:
  endpoint  a string that contains one of the vendor's endpoints (a host or an API path); in Python only string
            constants count, never a docstring or a comment; in shell and JavaScript any line but a comment;
  cli       a vendor command run: a Python list whose first item is the command (an argv), a shell command word,
            or a JavaScript spawn/exec of it;
  module    an import of the vendor's client module or package, or its .py file named in shell, JavaScript or a string
            of a Python file that imports subprocess (a process that runs it: ORIGIN-FINISH R1).
A call is allowed in the vendor's adapters, an import of its adapter module also in its selectors (the port's
adapter factory), and anywhere else only as a baseline site path:token. Against the base the baseline only shrinks,
a new adapter lives under providers.adapter_dir, and a vendor marked forbidden has no adapter and no baseline.
"""
import ast
import python_source
import source_facts
import json
from pathlib import Path
import re
import subprocess

import config
import config_check
import json_schema

JS_IMPORT = re.compile(r'''(?:\bfrom\s+|\bimport\s*\(\s*|\brequire\s*\(\s*|^\s*import\s+)['"]([^'"]+)['"]''')
JS_SPAWN = re.compile(r'''\b(?:spawn|spawnSync|exec|execSync|execFile|execFileSync|execa)\s*\(\s*['"`]([a-z][a-z0-9-]*)['"`]''')
PY_MODULE = re.compile(r'[a-z_][a-z0-9_.]*')
SHELL_WORD = r'(?:^|[;&|({]|\$\(|`|\b(?:then|do|else|exec|command|time|xargs|if|while|until)\s)\s*(?:[A-Za-z_]\w*=\S*\s+)*'


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)


def load(root):
    """(catalog, errors): the catalog file validated against its schema."""
    path = Path(root) / config.get('providers.vendor_catalog', root)
    schema_path = Path(root) / config.get('providers.vendor_catalog_schema', root)
    if not path.is_file():
        return {'vendors': []}, [f'{path.relative_to(root)}: the vendor catalog is missing (D-069 item 7)']
    catalog = json.loads(path.read_text(encoding='utf-8'))
    schema = json.loads(schema_path.read_text(encoding='utf-8'))
    return catalog, [f'{path.relative_to(root)}: {error}' for error in json_schema.validate(schema, catalog)]


def _module_file(module):
    return module.replace('.', '/') + '.py'


def _docstrings(tree):
    found = set()
    for node in python_source.select(tree, ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                found.add(id(first.value))
    return found


def _imported(node):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module] + [f'{node.module}.{alias.name}' for alias in node.names]
    return []


def parse(text):
    """The facts of Python source every vendor is matched against, from one walk of one parse (GATE-SPEED F8: the
    walk ran once per vendor, 2.1 million node visits for the repository): (strings that are not docstrings, the first
    element of each list literal, imported module names), each with its line; empty when it does not parse."""
    try:
        tree = python_source.parse(text)
    except SyntaxError:
        return [], [], []
    docstrings, strings, firsts, modules = _docstrings(tree), [], [], []
    for node in python_source.select(tree, ast.Constant, ast.List, ast.Import, ast.ImportFrom):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                strings.append((node.lineno, node.value))
        elif isinstance(node, ast.List) and node.elts:
            first = node.elts[0]
            if isinstance(first, ast.Constant):
                firsts.append((node.lineno, first.value))
        else:
            modules += [(node.lineno, name) for name in _imported(node)]
    return strings, firsts, modules


def python_facts(text):
    """parse(text) as JSON, so a cached copy (source_facts, F31) is the same answer: [line, value] pairs, and of the
    list literals' first elements only the strings, the one kind a vendor's clis can match."""
    strings, firsts, modules = parse(text)
    return [[list(item) for item in strings], [[line, value] for line, value in firsts if isinstance(value, str)],
            [list(item) for item in modules]]


def _well_formed_facts(facts):
    """Whether cached facts have the shape python_facts writes."""
    return isinstance(facts, list) and len(facts) == len(('strings', 'firsts', 'modules')) and all(
        isinstance(pairs, list) and all(isinstance(pair, list) and [type(part) for part in pair] == [int, str]
                                        for pair in pairs) for pairs in facts)


def endpoint_tokens(text, vendor, shadows):
    """Keep an endpoint occurrence unless another vendor owns its more specific enclosing endpoint.

    Ownership is per occurrence, so a string containing both an Origin URL and a Cursor agent URL
    still calls both vendors. Overlapping endpoints of the same vendor keep their historical counts.
    """
    for endpoint in vendor['endpoints']:
        if endpoint not in text:
            continue
        covered = [(match.start(), match.end()) for specific in shadows.get(endpoint, ())
                   for match in re.finditer(re.escape(specific), text)]
        if any(not any(start <= match.start() and match.end() <= end for start, end in covered)
               for match in re.finditer(re.escape(endpoint), text)):
            yield endpoint


def python_calls(parsed, vendor, shadows=None):
    """(line, token, how) of each call to the vendor in parsed Python source."""
    strings, firsts, modules = parsed
    found = [(line, endpoint, 'endpoint') for line, text in strings for endpoint in endpoint_tokens(text, vendor, shadows or {})]
    found += [(line, value, 'cli') for line, value in firsts if value in vendor['clis']]
    found += [(line, name, 'module') for line, name in modules if name in vendor['modules']]
    # ORIGIN-FINISH R1: in a file that starts processes, a string that names the module's file is a process that
    # runs it (an argv such as [sys.executable, root / 'scripts/lib/github_cli.py', ...]): the rule the shell and
    # JavaScript scan applies. A file that starts none (a static reader of adapter source) only names it.
    if any(name == 'subprocess' for _, name in modules):
        found += [(line, module, 'module') for line, text in strings for module in vendor['modules']
                  if PY_MODULE.fullmatch(module) and _names_file(text, module)]
    return found


def _names_file(text, module):
    """True when `text` names the module's .py file as a path component (never a longer name that ends with it); the
    plain substring test first, since almost no string names one (F31: the regex ran 180 000 times a scan)."""
    name = _module_file(module).rsplit('/', 1)[-1]
    return name in text and bool(re.search(rf'(?<![\w.]){re.escape(name)}\b', text))


def text_calls(text, vendor, shell, shadows=None):
    """(line, token, how) of each call to the vendor in shell or JavaScript source."""
    found = []
    clis = '|'.join(re.escape(cli) for cli in vendor['clis'])
    command = re.compile(SHELL_WORD + rf'({clis})(?=\s|$|\)|;)') if clis else None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('*'):
            continue
        found += [(number, endpoint, 'endpoint') for endpoint in endpoint_tokens(line, vendor, shadows or {})]
        if shell and command:
            found += [(number, match.group(1), 'cli') for match in command.finditer(line)]
        if not shell:
            found += [(number, match.group(1), 'cli') for match in JS_SPAWN.finditer(line)
                      if match.group(1) in vendor['clis']]
            found += [(number, match.group(1), 'module') for match in JS_IMPORT.finditer(line)
                      if match.group(1) in vendor['modules']]
        for module in vendor['modules']:
            if PY_MODULE.fullmatch(module) and _names_file(line, module):
                found.append((number, module, 'module'))
    return found


def calls(root, files, catalog):
    """(path, line, vendor, token, how) of every vendor call in the given (path, kind) files."""
    found = []
    shadows = {vendor['name']: {
        endpoint: [specific for other in catalog['vendors'] if other['name'] != vendor['name']
                   for specific in other['endpoints'] if endpoint != specific and endpoint in specific]
        for endpoint in vendor['endpoints']}
        for vendor in catalog['vendors']}
    store, extractor = source_facts.store(root), source_facts.digest(__file__, python_source.__file__)
    for path, kind in files:
        text = (Path(root) / path).read_text(encoding='utf-8', errors='replace')
        parsed = (source_facts.cached(store, extractor, text, python_facts, _well_formed_facts) if kind == '.py'
                  else None)
        for vendor in catalog['vendors']:
            hits = (python_calls(parsed, vendor, shadows[vendor['name']]) if parsed is not None else
                    text_calls(text, vendor, shell=kind == '.sh', shadows=shadows[vendor['name']]))
            found += [(path, line, vendor['name'], token, how) for line, token, how in sorted(set(hits))]
    return found


def judge(found, catalog):
    """(errors, warnings): a call outside its adapters and baseline is an error; an unused baseline site a warning."""
    vendors = {vendor['name']: vendor for vendor in catalog['vendors']}
    errors, used = [], set()
    for path, line, name, token, how in found:
        vendor = vendors[name]
        if path in vendor['adapters'] or (how == 'module' and path in vendor['selectors']):
            continue
        site = f'{path}:{token}'
        if site in vendor['baseline']:
            used.add((name, site))
            continue
        where = ', '.join(vendor['adapters']) or f'no adapter ({vendor["status"]})'
        errors.append(f'{path}:{line}: {how} call to {name} ({token}) outside its adapter ({where}); go through its '
                      f'port (D-069 item 7)')
    warnings = [f'{vendor["name"]}: baseline lists {site}, which no longer calls it; remove the site'
                for vendor in catalog['vendors'] for site in vendor['baseline'] if (vendor['name'], site) not in used]
    return errors, warnings


def catalog_errors(root, catalog):
    errors = []
    for vendor in catalog['vendors']:
        for path in vendor['adapters'] + vendor['selectors']:
            if not (Path(root) / path).is_file():
                errors.append(f'vendor catalog: {vendor["name"]} names {path}, which does not exist')
        classifications = vendor.get('baseline_classification', {})
        for site in vendor['baseline']:
            entry = classifications.get(site, {})
            for field in ('nature', 'reason'):
                value = entry.get(field)
                if not isinstance(value, str) or not value.strip():
                    errors.append(f'vendor catalog: {vendor["name"]} baseline {site} requires nonblank {field}')
        for site in sorted(set(classifications) - set(vendor['baseline'])):
            errors.append(f'vendor catalog: {vendor["name"]} classification {site} has no baseline site')
        if vendor['status'] == 'forbidden' and (vendor['adapters'] or vendor['baseline']):
            errors.append(f'vendor catalog: {vendor["name"]} is forbidden and may have no adapter and no baseline')
        if vendor['status'] == 'slot' and vendor['adapters']:
            errors.append(f'vendor catalog: {vendor["name"]} is a slot; with an adapter its status is active')
    return errors


def shrink_errors(catalog, before, text_at_base, adapter_dir):
    """Against the base catalog (None when the base has none): the baseline only shrinks, new adapters live in
    adapter_dir, except an existing module when first registering its vendor.
    text_at_base(path) is the file's text at the base, or None."""
    errors = []
    old = {vendor['name']: vendor for vendor in (before or {}).get('vendors', [])}
    for vendor in catalog['vendors']:
        previous = old.get(vendor['name'])
        for site in sorted(set(vendor['baseline']) - set((previous or {}).get('baseline', []))):
            path, token = site.rsplit(':', 1)
            text = text_at_base(path)
            if before is not None or text is None or token not in text:
                errors.append(f'{vendor["name"]}: baseline gains {site}; the list only shrinks, and a site is listed '
                              'only for a call the base already had (D-069 item 7)')
        for path in sorted(set(vendor['adapters']) - set((previous or {}).get('adapters', []))):
            grandfathered = previous is None and text_at_base(path) is not None
            if not path.startswith(adapter_dir.rstrip('/') + '/') and not grandfathered:
                errors.append(f'{vendor["name"]}: new adapter {path} is outside {adapter_dir}/ (D-069 item 7)')
    return errors


def check(root, base=None):
    """(errors, warnings) of the catalog and of every engine file; a checkout without the providers registry (a test
    fixture of another check) has nothing to judge."""
    root = Path(root)
    if not (root / 'config' / 'registry' / 'providers.json').is_file():
        return [], []
    catalog, errors = load(root)
    if errors:
        return errors, []
    errors += catalog_errors(root, catalog)
    scope = config_check.engine_files(root, config.get('providers.vendor_check_excludes', root))
    call_errors, warnings = judge(calls(root, scope, catalog), catalog)
    errors += call_errors
    if base:
        def text_at_base(path):
            shown = _git(root, 'show', f'{base}:{path}')
            return shown.stdout if shown.returncode == 0 else None
        before = text_at_base(config.get('providers.vendor_catalog', root))
        errors += shrink_errors(catalog, json.loads(before) if before else None, text_at_base,
                                config.get('providers.adapter_dir', root))
    return errors, warnings
