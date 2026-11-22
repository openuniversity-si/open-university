"""The unit map generator (D-067 (4), plan v3 §4.5): measure today's code and propose the cut into units.

Three inputs, all measured: the import graph (TypeScript/JavaScript imports resolved through the tsconfig `paths`,
Python sibling imports and declared dynamic selections, and the files a shell script runs or sources; a data file imports nothing), the co-change of the git log, and the size ceiling
of the registry (units.size_ceiling, P-04). Every tunable (window, weights, floors, thresholds) is a units.* entry.

  propose  cut the production files into candidates: a directory whose production lines fit the ceiling is one
           candidate; a larger one splits into its subdirectories, and its own files are clustered by affinity
           (co-change and imports, weighted); a candidate below the merge floor joins its closest sibling while the
           pair stays within the target. Nothing moves: the result is data for the manifests.
  measure  for each manifest (or candidate): its own production lines, its transitive import closure in lines and
           tokens (bytes / units.bytes_per_token), and how often its changes stay inside it (cohesion).

scripts/units propose|measure [--json]; measure --emit [--pr N] publishes engine.step.measured and one unit.oversize per
unit above its ceiling through the forge_events port.
"""
import ast
import python_source
import source_facts
from collections import defaultdict
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import subprocess

import config
import units

TS_IMPORT = re.compile(r'''(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*|\bexport\s+\*\s+from\s*)['"]([^'"\n]+)['"]''')
PY_IMPORT = re.compile(r'^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w., ]*))', re.M)
FILE_REFERENCE = re.compile(r'[\w.$/{}-]*?([\w.-]+(?:/[\w.-]+)*\.(?:py|sh|mjs|js|ts|json))\b')
CLI_SCRIPT = re.compile(r'(?:^|/)(scripts/(?:lib/)?[A-Za-z0-9_.-]+)$')
CLI_EXEC_NAMES = frozenset({'run', 'Popen', 'check_output', 'check_call', 'call', 'output', 'spawn', 'execv', 'execvp', '_run'})
TS_SUFFIXES = ('.ts', '.tsx', '.mts', '.mjs', '.js', '.cjs')


def setting(name, root):
    """A units.* registry value, read once per checkout (units.setting caches it; the cut calls it in inner loops)."""
    return units.setting(name, root)


def git(root, *args):
    done = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ''


def resolve_file(candidate, files, root):
    """The tracked file an import path names (as written, then with each of units.import_extensions), else None."""
    candidate = posixpath.normpath(candidate)
    if candidate in files:
        return candidate
    for suffix in setting('import_extensions', root):
        if candidate + suffix in files:
            return candidate + suffix
    stem, ext = posixpath.splitext(candidate)
    if ext in ('.js', '.mjs'):  # TypeScript written with its emitted extension
        for suffix in TS_SUFFIXES:
            if stem + suffix in files:
                return stem + suffix
    return None


def dynamic_selections(text):
    """What a Python text declares and loads through importlib, from its text alone: {declared: the factory names of
    its valid DYNAMIC_IMPORTS, invalid: how many declarations are not a list of names, selector: whether it declares,
    loaded: [module, enclosing function or None] of each literal import_module, computed: how many name no literal}.
    JSON-shaped, so a cached copy (source_facts) is the same answer; a text that does not parse selects nothing."""
    facts = {'declared': [], 'invalid': 0, 'selector': False, 'loaded': [], 'computed': 0}
    try:
        tree = python_source.parse(text)
    except SyntaxError:
        return facts
    declared, factories, calls = set(), {}, []
    for function in python_source.select(tree, ast.FunctionDef, ast.AsyncFunctionDef):
        if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in python_source.select(function, ast.Call):
                if isinstance(child, ast.Call):
                    factories[id(child)] = function.name
    for node in python_source.select(tree, ast.Assign, ast.Call):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and
                                               target.id == 'DYNAMIC_IMPORTS' for target in node.targets):
            facts['selector'] = True
            try:
                value = ast.literal_eval(node.value)
                if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
                    raise ValueError('expected factory names')
                declared.update(value)
            except (ValueError, TypeError):
                facts['invalid'] += 1
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and
                isinstance(node.func.value, ast.Name) and node.func.value.id == 'importlib' and
                node.func.attr == 'import_module'):
            calls.append(node)
    for call in calls:
        if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
            facts['loaded'].append([call.args[0].value, factories.get(id(call))])
        else:
            facts['computed'] += 1
    facts['declared'] = sorted(declared)
    return facts


def _well_formed_selections(facts):
    """Whether cached facts have the shape dynamic_selections writes."""
    return (isinstance(facts, dict) and set(facts) == {'declared', 'invalid', 'selector', 'loaded', 'computed'}
            and isinstance(facts['declared'], list) and all(isinstance(name, str) for name in facts['declared'])
            and type(facts['invalid']) is int and type(facts['computed']) is int and type(facts['selector']) is bool
            and isinstance(facts['loaded'], list)
            and all(isinstance(item, list) and [type(part) for part in item] in ([str, str], [str, type(None)])
                    for item in facts['loaded']))


def cli_calls(text):
    """Relative `scripts/<cmd>` or `scripts/lib/<mod>` paths passed to subprocess/exec calls in a Python source.

    AST-only so comments, docstrings, regex patterns, and ArgumentParser help text never produce false edges.
    """
    if 'scripts' not in text:
        return []
    try:
        tree = python_source.parse(text)
    except SyntaxError:
        return []
    found = set()
    for node in python_source.select(tree, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, 'id', '')
        if name not in CLI_EXEC_NAMES:
            continue
        for arg in [*node.args, *(kw.value for kw in node.keywords)]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                    match = CLI_SCRIPT.search(sub.value)
                    if match:
                        found.add(match.group(1))
                elif isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.Div):
                    parts, current = [], sub
                    while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div):
                        if isinstance(current.right, ast.Constant) and isinstance(current.right.value, str):
                            parts.append(current.right.value)
                        current = current.left
                    if isinstance(current, ast.Constant) and isinstance(current.value, str):
                        parts.append(current.value)
                    parts.reverse()
                    for index, part in enumerate(parts):
                        if part == 'scripts' and index + 1 < len(parts):
                            candidate = '/'.join(parts[index:])
                            match = CLI_SCRIPT.search(candidate)
                            if match:
                                found.add(match.group(1))
    return sorted(found)


class Code:
    """The tracked files of a checkout, which of them are production, their sizes and their import edges."""

    def __init__(self, root, files=None, log=None):
        self.root = Path(root)
        self.files = sorted(files if files is not None else git(self.root, 'ls-files').split())
        self.tracked = set(self.files)
        self.production = units.production(self.files, self.root)[0]
        exempt = units.matcher(setting('size_exempt_globs', self.root))
        self.counted = {path for path in self.production if not exempt.fullmatch(path)}
        self.sizes = {path: self._size(path) for path in self.production}
        self.aliases = self._aliases()
        self.static_edges = {path: self._imports(path) for path in self.production}
        self.dynamic_errors = []
        self.facts = source_facts.store(self.root)
        self.dynamic_edges = {path: self._dynamic_imports(path) for path in self.production}
        self.cli_edges = {path: self._cli_imports(path) for path in self.production}
        self.edges = {path: self.static_edges[path] | self.dynamic_edges[path] for path in self.production}
        self.commits = self._commits(log)

    def _text(self, path):
        try:
            data = (self.root / path).read_bytes()
        except OSError:
            return ''
        return '' if b'\0' in data[:4096] else data.decode('utf-8', errors='replace')

    def _size(self, path):
        text = self._text(path)
        return len(text.splitlines()), len(text.encode('utf-8'))

    def lines(self, paths):
        return sum(self.sizes[path][0] for path in paths if path in self.counted)

    def _aliases(self):
        """tsconfig `paths` (the one source of the import aliases): (prefix, target dir or file, wildcard)."""
        found = []
        for name in setting('tsconfig_files', self.root):
            path = self.root / name
            if not path.is_file():
                continue
            try:
                options = json.loads(path.read_text(encoding='utf-8')).get('compilerOptions', {})
            except json.JSONDecodeError:
                continue
            base = posixpath.normpath(posixpath.join(posixpath.dirname(name), options.get('baseUrl', '.')))
            for key, targets in (options.get('paths') or {}).items():
                for target in targets[:1]:
                    wild = key.endswith('*')
                    found.append((key.rstrip('*'), posixpath.normpath(posixpath.join(base, target.rstrip('*'))), wild))
        return sorted(found, key=lambda item: -len(item[0]))

    def _resolve(self, candidate):
        return resolve_file(candidate, self.tracked, self.root)

    def resolve_import(self, path, spec):
        """The tracked file an import specifier of path names (relative or through a tsconfig alias), else None."""
        if spec.startswith('.'):
            return self._resolve(posixpath.join(posixpath.dirname(path), spec))
        for prefix, target, wild in self.aliases:
            if wild and spec.startswith(prefix):
                return self._resolve(posixpath.join(target, spec[len(prefix):]))
            if not wild and spec == prefix:
                return self._resolve(target)
        return None

    def _imports(self, path):
        text = self._text(path)
        if not text:
            return set()
        found = set()
        folder = posixpath.dirname(path)
        if path.endswith(TS_SUFFIXES):
            found = {self.resolve_import(path, spec) for spec in TS_IMPORT.findall(text)}
        elif path.endswith('.py'):
            for single, several in PY_IMPORT.findall(text):
                for module in ([single] if single else [part.strip().split(' ')[0] for part in several.split(',')]):
                    head = module.split('.')[0]
                    for directory in [folder, *setting('python_import_dirs', self.root)]:
                        found.add(self._resolve(posixpath.join(directory, head + '.py')))
        elif posixpath.splitext(path)[1] in ('', '.sh'):  # shell: the files it runs or sources
            for reference in FILE_REFERENCE.findall(text):
                for directory in (folder, posixpath.dirname(folder), ''):
                    resolved = self._resolve(posixpath.join(directory, reference))
                    if resolved:
                        found.add(resolved)
                        break
        found.discard(None)
        found.discard(path)
        return {item for item in found if item in self.sizes}

    def _cli_imports(self, path):
        if not path.endswith('.py'):
            return set()
        return {target for target in cli_calls(self._text(path)) if target in self.sizes and target != path}

    def _dynamic_imports(self, path):
        """Verify literal importlib selections without turning vendor selection into requires.

        DYNAMIC_IMPORTS declares a selector's factory names in its own source. Literal
        loads anywhere must be declared; computed loads in a declared selector fail
        closed. Other computed plugin mechanisms remain outside this graph's scope.
        The selections are read from the text alone (dynamic_selections, kept by content: F31); the checkout's
        files and python_import_dirs are applied here, live.
        """
        if not path.endswith('.py'):
            return set()
        facts = source_facts.cached(self.facts, source_facts.digest(__file__, python_source.__file__),
                                    self._text(path), dynamic_selections, _well_formed_selections)
        declared = set(facts['declared'])
        loaded = {(module, factory) for module, factory in facts['loaded']}
        self.dynamic_errors += [f'{path}: invalid DYNAMIC_IMPORTS declaration'] * facts['invalid']
        if facts['selector']:
            self.dynamic_errors += [f'{path}: dynamic selection must name a literal module'] * facts['computed']
        for module in sorted(module for module, factory in loaded if factory not in declared):
            self.dynamic_errors.append(f'{path}: undeclared dynamic selection {module}')
        for module in sorted(declared - {factory for _, factory in loaded}):
            self.dynamic_errors.append(f'{path}: dynamic selection {module} is declared but not loaded')
        found = set()
        for module in sorted(module for module, factory in loaded if factory in declared):
            target = None
            for directory in [posixpath.dirname(path), *setting('python_import_dirs', self.root)]:
                candidate = posixpath.join(directory, module.replace('.', '/') + '.py')
                if candidate in self.sizes and (self.root / candidate).is_file():
                    target = candidate
                    break
            if target is None:
                self.dynamic_errors.append(f'{path}: dynamic selection target absent: {module}')
            else:
                found.add(target)
        return found

    def _commits(self, log):
        if log is None:
            log = git(self.root, 'log', '--no-merges', '--name-only', '--format=%x00%H',
                      f'-n{setting("cochange_commits", self.root)}')
        limit = setting('cochange_max_files', self.root)
        commits = []
        for chunk in log.split('\0')[1:]:
            touched = {line for line in chunk.splitlines()[1:] if line in self.sizes}
            if touched and len(touched) <= limit:
                commits.append(frozenset(touched))
        self.masks = defaultdict(int)  # file -> bit set of the commits that touched it
        for bit, commit in enumerate(commits):
            for path in commit:
                self.masks[path] |= 1 << bit
        return commits

    def mask(self, paths):
        found = 0
        for path in paths:
            found |= self.masks.get(path, 0)
        return found

    def closure(self, paths):
        seen, todo = set(), [path for path in paths if path in self.sizes]
        while todo:
            path = todo.pop()
            if path in seen:
                continue
            seen.add(path)
            todo += self.edges.get(path, ())
        return seen

    def measure(self, paths):
        own = [path for path in paths if path in self.sizes]
        mine = set(own)
        closed = self.closure(own)
        touching = [commit for commit in self.commits if commit & mine]
        inside = sum(1 for commit in touching if commit <= mine)
        bytes_ = sum(self.sizes[path][1] for path in closed if path in self.counted)
        return {
            'files': len(own),
            'lines': self.lines(own),
            'closure_files': len(closed),
            'closure_lines': self.lines(closed),
            'closure_tokens': bytes_ // setting('bytes_per_token', self.root),
            'commits': len(touching),
            'cohesion_percent': round(100 * inside / len(touching)) if touching else None,
        }


def affinity(code, first, second):
    """How strongly two file sets belong together: weighted co-change and import density, each in [0, 1]."""
    first, second = set(first), set(second)
    one, two = code.mask(first), code.mask(second)
    alone = min(bin(one).count('1'), bin(two).count('1'))
    shared = bin(one & two).count('1') / alone if alone else 0.0
    small, large = (first, second) if len(first) <= len(second) else (second, first)
    links = sum(len(code.edges.get(path, set()) & large) for path in small)
    links += sum(1 for path in large for target in code.edges.get(path, ()) if target in small)
    imports = min(1.0, links / len(small)) if small else 0.0
    return setting('cochange_weight', code.root) * shared + setting('import_weight', code.root) * imports


def cluster(code, paths):
    """Greedy agglomerative clustering of a flat file group that exceeds the ceiling: merge the closest pair while it
    fits the target and is closer than units.merge_min_affinity; then fold leftovers below the floor into their
    closest cluster while it stays within the ceiling."""
    target = setting('size_target', code.root)
    ceiling = setting('size_ceiling', code.root)
    floor = setting('merge_floor_lines', code.root)
    least = setting('merge_min_affinity', code.root)
    groups = [[path] for path in sorted(paths)]
    while True:
        best = None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if code.lines(groups[i]) + code.lines(groups[j]) > target:
                    continue
                score = affinity(code, groups[i], groups[j])
                if score >= least and (best is None or score > best[0]):
                    best = (score, i, j)
        if best is None:
            break
        _, i, j = best
        groups[i] = sorted(groups[i] + groups.pop(j))
    return _fold(code, groups, floor, ceiling)


def _fold(code, groups, floor, ceiling):
    groups = sorted(groups, key=lambda group: (code.lines(group), group))
    changed = True
    while changed:
        changed = False
        for small in list(groups):
            if code.lines(small) >= floor or len(groups) < 2:
                continue
            others = [group for group in groups if group is not small and code.lines(group) + code.lines(small) <= ceiling]
            if not others:
                continue
            closest = max(others, key=lambda group: (affinity(code, small, group), -code.lines(group)))
            groups.remove(small)
            closest.extend(small)
            closest.sort()
            changed = True
            break
    return sorted(groups, key=lambda group: group[0])


def _roots(code):
    """Start directories of the cut: each production glob's fixed prefix."""
    found = []
    for glob in setting('production_globs', code.root):
        parts = glob.split('/')
        fixed = [part for part in parts[:next((i for i, p in enumerate(parts) if any(c in p for c in '*?[')), len(parts))]]
        found.append('/'.join(fixed))
    return sorted(set(found), key=lambda folder: (-folder.count('/'), folder))  # nested roots first


def _within(path, folder):
    return folder == '' or path == folder or path.startswith(folder + '/')


def _cut(code, folder, files, roots=()):
    mine = [path for path in files if _within(path, folder)]
    if not mine:
        return []
    if code.lines(mine) <= setting('size_ceiling', code.root):
        whole = (not any(root != folder and _within(root, folder) for root in roots)
                 and set(mine) >= {path for path in code.production if _within(path, folder)})
        return [{'base': folder, 'paths': [f'{folder}/**'] if whole else mine, 'files': mine}]
    direct = [path for path in mine if posixpath.dirname(path) == folder]
    children = sorted({path[len(folder) + 1:].split('/')[0] for path in mine if posixpath.dirname(path) != folder})
    found = []
    for child in children:
        found += _cut(code, f'{folder}/{child}', mine, roots)
    if direct:
        if code.lines(direct) <= setting('size_ceiling', code.root):
            found.append({'base': folder, 'paths': direct, 'files': direct})
        else:
            found += [{'base': folder, 'paths': group, 'files': group} for group in cluster(code, direct)]
    return _merge_siblings(code, found)


def _merge_siblings(code, candidates):
    floor = setting('merge_floor_lines', code.root)
    target = setting('size_target', code.root)
    candidates = sorted(candidates, key=lambda item: code.lines(item['files']))
    merged = True
    while merged:
        merged = False
        for small in candidates:
            if code.lines(small['files']) >= floor:
                continue
            others = [item for item in candidates if item is not small
                      and code.lines(item['files']) + code.lines(small['files']) <= target]
            if not others:
                continue
            closest = max(others, key=lambda item: affinity(code, small['files'], item['files']))
            candidates.remove(small)
            closest['paths'] = sorted(set(closest['paths']) | set(small['paths']))
            closest['files'] = sorted(set(closest['files']) | set(small['files']))
            merged = True
            break
    return candidates


def candidate_id(paths):
    common = posixpath.commonpath([path.replace('/**', '') for path in paths]) if paths else ''
    tail = [part for part in PurePosixPath(common).parts if part not in ('apps', 'web', 'src')][-2:]
    return '-'.join(re.sub(r'[^a-z0-9]+', '-', part.lower()).strip('-') for part in tail) or 'root'


def propose(root=None, code=None):
    """Candidates covering every production file, each with its measures; nothing is written."""
    code = code or Code(units._root(root))
    found, covered = [], set()
    roots = _roots(code)
    for start in roots:
        rest = [path for path in code.production if path not in covered and _within(path, start)]
        for item in _cut(code, start, rest, roots):
            covered |= set(item['files'])
            found.append(item)
    ceiling = setting('size_ceiling', code.root)
    return [dict({'id': candidate_id(item['paths']), 'paths': item['paths']}, **code.measure(item['files']),
                 oversize=code.lines(item['files']) > ceiling)
            for item in sorted(found, key=lambda item: item['paths'][0])]


def measure(root=None, code=None):
    """Each manifest's measures against its own budget (units.budget: a cited override, else the registry)."""
    root = units._root(root)
    code = code or Code(root)
    rows = []
    for unit, manifest in sorted(units.manifests(root).items()):
        mine = units.matcher(manifest['paths'])
        files = [path for path in code.files if mine.fullmatch(path)]
        row = dict({'id': unit, 'owner': manifest['owner']}, **code.measure(files))
        row['ceiling'] = units.budget(unit, 'units.size_ceiling', root)
        row['context_budget'] = units.budget(unit, 'units.context_budget', root)
        row['oversize'] = row['lines'] > row['ceiling']
        row['over_context'] = row['closure_tokens'] > row['context_budget']
        rows.append(row)
    return rows


def requires(root=None, code=None):
    """Static imports only: vendor selections are relations, not mandatory unit dependencies (D-283)."""
    return _unit_edges(root, code, 'static_edges')


def cli_requires(root=None, code=None):
    """Cross-unit subprocess CLI invocations (`scripts/<cmd>`), kept distinct from static requires."""
    return _unit_edges(root, code, 'cli_edges')


def _unit_edges(root, code, attr):
    root = units._root(root)
    code = code or Code(root)
    owner = {}
    for path in code.production:
        found = units.units_of(path, root)
        if len(found) == 1:
            owner[path] = found[0]
    needs = defaultdict(set)
    for path, targets in getattr(code, attr).items():
        for target in targets:
            if path in owner and target in owner and owner[path] != owner[target]:
                needs[owner[path]].add(owner[target])
    return {unit: sorted(found) for unit, found in sorted(needs.items())}


def emit(root, pr=None, port=None, sha=None, premises=()):
    """Measure the manifests inside an engine.step.measured step and emit one unit.oversize per unit above its
    ceiling, through the forge_events port (D-065 (1), D-069 item 6). Returns the rows."""
    import forge_events  # the port loads its adapter only when events are emitted
    root = units._root(root)
    sha = sha or git(root, 'rev-parse', 'HEAD').strip()
    repo = config.get('forge-events.repo', root)
    if port is None:
        port = forge_events.ForgeEvents(forge_events.adapter_from_config(), forge_events.clock_from_config(),
                                        setting('event_producer', root), f'units:{sha}')
    subject = forge_events.subject(repo, pr, sha, premises)
    with forge_events.measured(port, setting('measure_step', root), subject):
        rows = measure(root)
    port.publish([port.build('unit.oversize', dict(subject, unit=row['id'], size_lines=row['lines'],
                                                   budget_lines=row['ceiling']))
                  for row in rows if row['oversize']])
    return rows


def table(rows, columns):
    lines = ['\t'.join(columns)]
    for row in rows:
        lines.append('\t'.join('-' if row.get(column) is None else
                               ' '.join(row[column]) if isinstance(row.get(column), list) else str(row[column])
                               for column in columns))
    return '\n'.join(lines)


def main(command, as_json, root=None, emit_pr=None, emitting=False):
    if command == 'propose':
        rows = propose(root)
        columns = ['id', 'lines', 'files', 'closure_tokens', 'cohesion_percent', 'oversize', 'paths']
    else:
        rows = emit(root, emit_pr) if emitting else measure(root)
        columns = ['id', 'owner', 'lines', 'ceiling', 'files', 'closure_tokens', 'context_budget', 'cohesion_percent',
                   'oversize']
    print(json.dumps(rows, indent=2) if as_json else table(rows, columns))
    over = sum(1 for row in rows if row['oversize'])
    if not as_json:
        print(f'units {command}: {len(rows)} unit(s), {sum(row["lines"] for row in rows)} production line(s), '
              f'{over} above the ceiling')
    return 0
