"""The configuration registry's gate check (D-068 (6), D-069 items 1, 2, 3 and 9), a module of scripts/structure-check.

check(root, base) returns (errors, warnings) for (the contracts and the registry's compatibility are the schema compat
stage's, scripts/schema-compat; the generated types are the generated drift stage's, scripts/generate):
  registry   every config/registry/<owner>.json validates (config.check: shape, owner, defaults, readers, secrets);
  literals   no file of the engine paths (config.literal_check_roots) spells a registered parameter as a literal.

What counts as a literal of a registered parameter, precisely: in a .py file, an assignment, annotated assignment,
keyword argument, parameter default or string dict key whose name is the parameter's identifier and whose value is a
constant (a number, a string or a boolean; None is not a value); in shell, `NAME=<number|quoted word>` or
`${NAME:-<value>}`; in .mjs/.js, `const|let|var NAME = <constant>` or `NAME: <constant>`. The parameter's identifier is
`<owner>_<key>` anywhere (TRAIN_BATCH_SIZE, train_batch_size), the bare `<key>` only in the owner's own files (a file
named after the owner or listed in x-readers), and each of its x-literal-names. An inline fallback after a registry
read (`config.get("x") or 8`, `config.py get x || echo 8`) is refused too. Names that are not registered are never
judged, so ordinary code is not touched. A literal that predates the registry is listed in its parameter's
x-literal-sites (path:IDENTIFIER); against the base that list only shrinks, and a new site must already be in the base.
"""
import ast
import python_source
import source_facts
import json
from pathlib import Path
import re
import subprocess

import config
import git_objects

SHELL_ASSIGN = re.compile(r'^\s*(?:export\s+|local\s+|readonly\s+|declare(?:\s+-\w+)*\s+)?([A-Za-z_]\w*)='
                          r'(-?\d+(?:\.\d+)?|"[^"$`]*"|\'[^\']*\')\s*(?:$|[;#])')
SHELL_DEFAULT = re.compile(r'\$\{([A-Za-z_]\w*):?[-=]([^}$]+)\}')
SHELL_FALLBACK = re.compile(r'config\.py["\']?\s+get\s+["\']?([a-z][a-z0-9-]*\.[a-z][a-z0-9_]*)[^\n]*?(\|\||:-)')
JS_ASSIGN = re.compile(r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(-?\d[\d_.]*|true|false|\'[^\']*\'|"[^"]*"|`[^`$]*`)\s*[;,\n]')
JS_KEY = re.compile(r'(?:^|[{,\s])([A-Za-z_$][\w$]*)\s*:\s*(-?\d[\d_.]*|true|false|\'[^\']*\'|"[^"]*")\s*(?=[,}\n])')
LITERAL_CACHE_ENV = source_facts.ENV
_EXTRACTOR = []  # the digest of what python_candidates depends on besides the text, computed once per process


def _normal(identifier):
    return identifier.lstrip('_$').lower()


def _git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)


def _at_base(root, base, path):
    shown = _git(root, 'show', f'{base}:{path}')
    return shown.stdout if shown.returncode == 0 else None


def _listed_at_base(root, base, folder):
    listed = _git(root, 'ls-tree', '-r', '--name-only', base, '--', folder)
    return listed.stdout.split() if listed.returncode == 0 else []


class Names:
    """Which identifiers spell which registered parameter, in which files."""

    def __init__(self, params):
        self.anywhere, self.owned = {}, {}
        for name, item in params.items():
            owner, key = name.split('.', 1)
            self.anywhere[_normal(f'{owner.replace("-", "_")}_{key}')] = name
            for alias in item.get('x-literal-names') or []:
                self.anywhere[_normal(alias)] = name
            # by bare key, in registry order: the first owner whose file this is wins, as a scan of every name did
            self.owned.setdefault(_normal(key), []).append((name, owner.replace('-', '_'),
                                                           set(item.get('x-readers') or [])))

    def match(self, identifier, path):
        normal = _normal(identifier)
        if normal in self.anywhere:
            return self.anywhere[normal]
        owners = self.owned.get(normal)
        if not owners:
            return None
        stem = Path(path).name.split('.', 1)[0].replace('-', '_')
        for name, owner, readers in owners:
            if stem == owner or path in readers:
                return name
        return None


def _constant(node):
    if isinstance(node, ast.Constant) and node.value is not None and not isinstance(node.value, bytes):
        return True
    return isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant)


def _target_names(target):
    if isinstance(target, ast.Name):
        return [target.id]
    if isinstance(target, ast.Attribute):
        return [target.attr]
    return []


def _get_argument(node):
    """The string a call passes as the first argument of a `get` (config.get("x") or get("x")), else None; whether it
    names a registered parameter, a registry read, is judge_candidates' question."""
    if not isinstance(node, ast.Call) or not node.args:
        return None
    func = node.func
    called = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
    first = node.args[0]
    if called == 'get' and isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def python_candidates(text):
    """Everything python_findings judges in a source, with no registry input, in the walk's order.

    ['value', line, identifier, string] is a name bound to a constant (`string` is the constant when it is a str: a
    registered parameter's name is a reference, not a value); ['or', line, [string, ...]] is an `or` with a constant
    operand, listing the strings its operands pass to `get` calls. A source that does not parse holds none. Only
    JSON-safe values, so a cached copy (literal_cache) is the same answer."""
    try:
        tree = python_source.parse(text)
    except SyntaxError:
        return []
    found = []

    def bound(identifier, value, line):
        if _constant(value):
            naming = value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None
            found.append(['value', line, identifier, naming])

    for node in python_source.select(tree, ast.Assign, ast.AnnAssign, ast.keyword,
                                     ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Dict, ast.BoolOp):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Tuple) and isinstance(node.value, ast.Tuple):
                    for element, value in zip(target.elts, node.value.elts):
                        for identifier in _target_names(element):
                            bound(identifier, value, node.lineno)
                for identifier in _target_names(target):
                    bound(identifier, node.value, node.lineno)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            for identifier in _target_names(node.target):
                bound(identifier, node.value, node.lineno)
        elif isinstance(node, ast.keyword) and node.arg:
            bound(node.arg, node.value, getattr(node.value, 'lineno', 0))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            positional = args.posonlyargs + args.args
            for arg, value in zip(positional[len(positional) - len(args.defaults):], args.defaults):
                bound(arg.arg, value, value.lineno)
            for arg, value in zip(args.kwonlyargs, args.kw_defaults):
                if value is not None:
                    bound(arg.arg, value, value.lineno)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and re.fullmatch(r'\w+', key.value):
                    bound(key.value, value, key.lineno)
        elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            if any(_constant(value) for value in node.values):
                reads = [_get_argument(value) for value in node.values]
                found.append(['or', node.lineno, [read for read in reads if read is not None]])
    return found


def judge_candidates(path, candidates, names, params):
    """(line, identifier, parameter, kind) of the candidates that spell, or fall back after reading, a registered
    parameter."""
    found = []
    for candidate in candidates:
        if candidate[0] == 'value':
            _, line, identifier, naming = candidate
            name = names.match(identifier, path)
            if name and not (naming is not None and naming in params):
                found.append((line, identifier, name, 'literal'))
        else:
            _, line, reads = candidate
            read = next((read for read in reads if read in params), None)
            if read:
                found.append((line, 'or', read, 'fallback'))
    return found


def python_findings(path, text, names, params, store=None):
    """(line, identifier, parameter, kind) of every literal and inline fallback of a registered parameter; `store`
    (literal_cache) keeps the candidates by content, never the verdict."""
    return judge_candidates(path, cached_candidates(text, store), names, params)


def _extractor():
    """What python_candidates depends on besides the text: the interpreter's grammar and the extracting code itself
    (this module and python_source), so an edit to either is a new key and never reads an old answer."""
    if not _EXTRACTOR:
        _EXTRACTOR.append(source_facts.digest(__file__, python_source.__file__))
    return _EXTRACTOR[0]


def literal_cache(root):
    """The store of python_candidates by content (source_facts.store: config.literal_cache_dir through the storage
    port), or None when it is turned off or cannot be opened: the scan then extracts every file, with the same answer."""
    return source_facts.store(root)


def _well_formed(candidate):
    """Whether a cached candidate has the shape python_candidates writes."""
    if not isinstance(candidate, list):
        return False
    try:
        if candidate[:1] == ['value']:
            _, line, identifier, naming = candidate
            return type(line) is int and isinstance(identifier, str) and (naming is None or isinstance(naming, str))
        if candidate[:1] == ['or']:
            _, line, reads = candidate
            return type(line) is int and isinstance(reads, list) and all(isinstance(read, str) for read in reads)
    except ValueError:  # another length
        pass
    return False


def cached_candidates(text, store):
    """python_candidates(text), read from `store` when it holds them for exactly this text and extractor; a missing,
    unreadable or malformed entry is extracted again and rewritten."""
    return source_facts.cached(store, _extractor(), text, lambda source: python_candidates(source),
                               lambda held: isinstance(held, list) and all(_well_formed(item) for item in held))


def text_findings(path, text, names, shell):
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith('#') or stripped.startswith('//'):
            continue
        pairs = []
        if shell:
            pairs += [(m.group(1), number) for m in SHELL_ASSIGN.finditer(line)]
            pairs += [(m.group(1), number) for m in SHELL_DEFAULT.finditer(line)]
        else:
            pairs += [(m.group(1), number) for m in JS_ASSIGN.finditer(line + '\n')]
            pairs += [(m.group(1), number) for m in JS_KEY.finditer(line + '\n')]
        for identifier, where in pairs:
            name = names.match(identifier, path)
            if name:
                found.append((where, identifier, name, 'literal'))
        for match in SHELL_FALLBACK.finditer(line):
            found.append((number, match.group(2), match.group(1), 'fallback'))
    return found


def engine_files(root, excludes=None):
    """(path, kind) of each scanned file of config.literal_check_roots; `excludes` replaces the literal scan's own."""
    roots = config.get('config.literal_check_roots', root)
    excludes = tuple(config.get('config.literal_check_excludes', root) if excludes is None else excludes)
    suffixes = tuple(config.get('config.literal_check_suffixes', root))
    shebangs = config.get('config.literal_check_shebangs', root)
    listed = _git(root, 'ls-files', '--', *roots)
    paths = listed.stdout.split() if listed.returncode == 0 else []
    for path in paths:
        if path.startswith(excludes) or not (root / path).is_file():
            continue
        suffix = Path(path).suffix
        if suffix:
            if suffix in suffixes:
                yield path, suffix
            continue
        with open(root / path, encoding='utf-8', errors='replace') as handle:
            first = handle.readline()
        kind = next((name for name in shebangs if first.startswith('#!') and name in first), None)
        if kind:
            yield path, '.py' if 'python' in kind else '.js' if 'node' in kind else '.sh'


def literal_findings(root, params=None):
    params = params if params is not None else config._load(root)
    names = Names(params)
    store = literal_cache(root)
    found = []
    for path, kind in engine_files(root):
        text = (root / path).read_text(encoding='utf-8', errors='replace')
        if kind == '.py':
            hits = python_findings(path, text, names, params, store)
        else:
            hits = text_findings(path, text, names, shell=kind == '.sh')
        found += [(path, *hit) for hit in hits]
    return found


def check_literals(root, base=None):
    params = config._load(root)
    errors, warnings, used = [], [], set()
    for path, line, identifier, name, kind in literal_findings(root, params):
        if kind == 'fallback':
            errors.append(f'{path}:{line}: an inline fallback after reading {name}; the registry value is the only '
                          'value (D-068 (2))')
            continue
        site = f'{path}:{identifier}'
        if site in (params[name].get('x-literal-sites') or []):
            used.add((name, site))
            continue
        errors.append(f'{path}:{line}: {identifier} spells the registered parameter {name} as a literal; '
                      f'read it with config.get("{name}") (D-068)')
    for name, item in params.items():
        for site in item.get('x-literal-sites') or []:
            if (name, site) not in used:
                warnings.append(f'{name}: x-literal-sites lists {site}, which no longer spells it; remove the site')
    if base:
        errors += check_sites_shrink(root, base, params)
    return errors, warnings


def _registry_params_at(root, base):
    """Every registry parameter at the base: one batched read of its registry files (git_objects, GATE-SPEED R2),
    not one `git show` per file."""
    paths = [path for path in _listed_at_base(root, base, 'config/registry') if path.endswith('.json')]
    try:
        texts = git_objects.files(root, base, paths)
    except git_objects.GitObjectsError:
        return {}
    params = {}
    for path in paths:
        params.update(json.loads(texts.get(path) or '{}').get('properties', {}))
    return params


def check_sites_shrink(root, base, params):
    before = _registry_params_at(root, base)
    errors = []
    for name, item in params.items():
        old = set((before.get(name) or {}).get('x-literal-sites') or [])
        for site in sorted(set(item.get('x-literal-sites') or []) - old):
            path, identifier = site.rsplit(':', 1)
            text = _at_base(root, base, path)
            if name in before or text is None or not re.search(rf'\b{re.escape(identifier)}\b', text):
                errors.append(f'{name}: x-literal-sites gains {site}; the list only shrinks, and a site is listed only '
                              f'for a literal the base already had (D-068 (6))')
    return errors


def check(root, base=None):
    """(errors, warnings) of the registry and the engine literals."""
    root = Path(root)
    if not (root / 'config' / 'registry').is_dir():
        return [], []
    errors = list(config.check(root))
    literal_errors, warnings = check_literals(root, base)
    return errors + literal_errors, warnings
