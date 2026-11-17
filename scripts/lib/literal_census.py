"""Unregistered literals in the engine (LT1; D-068 (6), D-069 items 1, 3 and 9), a module of scripts/structure-check.

config_check judges only identifiers that spell a registered parameter, so a brand-new value in a scanned file passed.
This census judges every value: each number outside literals.allowed_numbers and each match of literals.patterns
(durations, URLs, hosts, ports, absolute paths) outside literals.allowed_values, in the files config_check scans
(config.literal_check_*: scripts/, tests included, generated types left to the drift stage). Python is read by its
AST (docstrings and f-string format specs are prose, not values); shell and JavaScript line by line, without comments,
positional parameters, descriptor redirections and the `:-` default operator (the default itself is a value).

No list is read (TX22, T2): the offenders that predate the rule are allowed by the census of the base tree, computed
at check time; the old list (literals.baseline, deprecated) stays only until this is the base, then goes. check(root,
base) fails when a unit (D-067; a file no unit owns is literals.unowned_area) spells a kind and value more times than
the census of the merge-base of `base` (else of literals.base_ref) does, under this checkout's rules and manifests: a
new literal in a new file, a file that gains one, a value moved to another unit. A value moved between files of one
unit passes; a removed one needs nothing rewritten. Each error names the file:line of the grown literals and the
registry fix. A checkout that cannot read its base fails closed. Plain, the module checks against literals.base_ref;
`--base REF` names another.

A file the production guard forbids naming (D-054: its path mentions an entrypoint of production.forbidden_entrypoints,
entrypoint_mentions.mentions) is not judged: its literals would be named in the errors, and widening the guard's
allowlist is not this check's to do. When the release pipeline of roadmap step 8 owns those frozen files (D-054,
docs/process/RELEASES.md), it brings them into the census.

Old lists (TX22 option b, F96): with_legacy adds the counts of the old per-area baseline files at the merge-base to the
allowed census (legacy_lists reads them, and the catalogs, in the old shape); an absent list adds nothing.

Library: Census(root), python_values, python_literals, text_literals, key, occurrences(root), census(root), base_census(root, commit,
current), merge_base, default_base, derived, check. The D-063 absolute list of scripts/lib/structure.py is read by
scripts/lib/census.py (each unit's record, CENSO-NO-MANIFESTO).
"""
import ast
import python_source
import source_facts
import json
from pathlib import Path
import re
import subprocess
import sys

import config
import config_check
import entrypoint_mentions
import units

ROOT = Path(__file__).resolve().parents[2]
SHELL_IGNORED = re.compile(r'\$\{?#?\d+\}?|\$\{#\w+\}|\d*[<>]&?\d*|:[-=+?]')
NUMBER = re.compile(r'(?<![\w$.#@%{}/:\\-])-?\d+(?:\.\d+)?(?![\w.%/:])')


class BaseError(Exception):
    """The base tree cannot be read, so no count is allowed: the census fails closed (LT1)."""


FIX = ('an engine value is a registry entry: declare it in config/registry/<owner>.json with x-readers naming the file '
       'and read it with config.get; a string that is not a parameter goes to literals.allowed_values, a number to '
       'literals.allowed_numbers (D-068, D-069 item 3, LT1)')


class Census:
    """The literals.* rules of a checkout, compiled once."""

    def __init__(self, root):
        self.numbers = set(config.get('literals.allowed_numbers', root))
        self.values = set(config.get('literals.allowed_values', root))
        self.patterns = [(item['kind'], re.compile(item['pattern'])) for item in config.get('literals.patterns', root)]

    def strings(self, text):
        """((kind, value) of every pattern match in a text, the text with each matched span masked); a span one kind
        matched is not matched again by the next."""
        found = []
        for kind, pattern in self.patterns:
            hits = list(pattern.finditer(text))
            found += [(kind, hit.group(0)) for hit in hits if hit.group(0) not in self.values]
            for hit in hits:
                text = text[:hit.start()] + ' ' * (hit.end() - hit.start()) + text[hit.end():]
        return found, text

    def number(self, value):
        return [] if value in self.numbers else [('number', value)]


def _skip_prose(node, skipped):
    """Mark the constants under `node` that are not values: a docstring of a module, class or function, and the parts
    of an f-string's format spec (`{n:02d}`). Breadth first, the owner is met before the constants it marks."""
    if isinstance(node, ast.FormattedValue) and node.format_spec is not None:
        skipped.update(id(part) for part in python_source.walk(node.format_spec))
    if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
        first = node.body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            skipped.add(id(first.value))



def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def python_values(text):
    """[line, 'number' or 'string', value] of every value of a Python file in walk order, before any rule: the part
    of python_literals that reads the text alone, JSON-shaped so a cached copy (source_facts, F31) is the same answer."""
    try:
        tree = python_source.parse(text)
    except SyntaxError:
        return []
    skipped, found = set(), []
    # one walk (GATE-SPEED F3; the prose was a walk of its own): breadth first, a negation is met before its operand
    # and a docstring's owner before the docstring
    for node in python_source.select(tree, ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.FormattedValue, ast.UnaryOp, ast.Constant):
        _skip_prose(node, skipped)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and isinstance(node.operand, ast.Constant) \
                and _numeric(node.operand.value):
            skipped.add(id(node.operand))
            found.append([node.lineno, 'number', -node.operand.value])
        elif isinstance(node, ast.Constant) and id(node) not in skipped:
            if _numeric(node.value):
                found.append([node.lineno, 'number', node.value])
            elif isinstance(node.value, str):
                found.append([node.lineno, 'string', node.value])
    return found


def _well_formed_values(values):
    """Whether cached values have the shape python_values writes."""
    return isinstance(values, list) and all(
        isinstance(item, list) and [type(part) for part in item[:-1]] == [int, str] and (
            (item[1] == 'number' and _numeric(item[-1])) or (item[1] == 'string' and isinstance(item[-1], str)))
        for item in values)


def python_literals(text, census, store=None):
    """(line, kind, value) of every unregistered literal of a Python file: its values (python_values, read from
    `store` when it keeps them for this text) judged by the census rules, live."""
    found = []
    for line, sort, value in source_facts.cached(store, source_facts.digest(__file__, python_source.__file__), text,
                                                 python_values, _well_formed_values):
        hits = census.number(value) if sort == 'number' else census.strings(value)[0]
        found += [(line, kind, found_value) for kind, found_value in hits]
    return found


def text_literals(text, census, shell):
    """(line, kind, value) of every unregistered literal of a shell or JavaScript file, line by line."""
    comment = re.compile(r'(?:^|\s)#.*$' if shell else r'(?:^|\s)//.*$')
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith(('#', '//', '*')):
            continue
        hits, masked = census.strings(comment.sub('', line))
        found += [(number, kind, value) for kind, value in hits]
        if shell:
            masked = SHELL_IGNORED.sub(' ', masked)
        for match in NUMBER.finditer(masked):
            value = float(match.group(0)) if '.' in match.group(0) else int(match.group(0))
            found += [(number, kind, value) for kind, value in census.number(value)]
    return found


def key(kind, value):
    """The list key of a literal: its kind and its value as JSON, without the line, so a moved literal stays the same
    entry (D-063)."""
    return f'{kind} {json.dumps(value)}'


def _area(path, root, unowned):
    try:
        return units.unit_of(path, root) or unowned
    except (config.ConfigError, units.UnitError):
        return unowned  # no units registry (a fixture), or an overlap scripts/lib/unit_check.py reports


def _unlistable(root):
    """Whether the production guard refuses a list that names a path (D-054); nothing is, without its registry."""
    try:
        entrypoints = config.get('production.forbidden_entrypoints', root)
    except config.ConfigError:
        return lambda path: False
    return lambda path: bool(entrypoint_mentions.mentions(path, [json.dumps(path)], entrypoints, []))


def _hits(text, kind, rules, store=None):
    return python_literals(text, rules, store) if kind == '.py' else text_literals(text, rules, shell=kind == '.sh')


def occurrences(root):
    """{path: (area, {key: [line, ...]})} of every scanned file that spells an unregistered literal."""
    rules, unowned, found, unlistable = Census(root), config.get('literals.unowned_area', root), {}, _unlistable(root)
    store = source_facts.store(root)
    for path, kind in config_check.engine_files(root):
        if unlistable(path):
            continue
        hits = _hits((root / path).read_text(encoding='utf-8', errors='replace'), kind, rules, store)
        if hits:
            lines = found.setdefault(path, (_area(path, root, unowned), {}))[1]
            for line, kind_found, value in hits:
                lines.setdefault(key(kind_found, value), []).append(line)
    return found


def census(root):
    """{area: {path: {key: count}}} of every unregistered literal in the scanned files; the area is the owning unit."""
    areas = {}
    for path, (area, lines) in occurrences(root).items():
        areas.setdefault(area, {})[path] = {found: len(at) for found, at in lines.items()}
    return {area: {path: dict(sorted(counts.items())) for path, counts in sorted(files.items())}
            for area, files in sorted(areas.items())}


def _git(root, *args, **options):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True, **options)


def _blobs(root, commit, paths):
    """{path: text} of each path at commit, read in one `git cat-file --batch` (the `git show` of every changed file)."""
    if not paths:
        return {}
    out = _git(root, 'cat-file', '--batch', input=''.join(f'{commit}:{path}\n' for path in paths).encode()).stdout
    texts, at = {}, 0
    for path in paths:
        end = out.index(b'\n', at)
        header = out[at:end].split()
        at = end + 1
        if header[-1] == b'missing':
            continue
        size = int(header[-1])
        texts[path] = out[at:at + size].decode('utf-8', errors='replace')
        at += size + 1
    return texts


def _kind(path, text, suffixes, shebangs):
    """The scanned kind of a file of another tree, by the rule of config_check.engine_files; None if not scanned."""
    suffix = Path(path).suffix
    if suffix:
        return suffix if suffix in suffixes else None
    first = text.splitlines()[0] if text else ''
    kind = next((name for name in shebangs if first.startswith('#!') and name in first), None)
    return None if kind is None else '.py' if 'python' in kind else '.js' if 'node' in kind else '.sh'


def base_census(root, commit, current):
    """{path: (area, {key: count})} of the scanned files at commit, under this checkout's rules and unit manifests, so
    a literal moving with its file is the same literal. A path the worktree has unchanged since commit (absent from
    `git diff --no-renames --name-only commit`) reuses `current` (occurrences); every other one is read once from commit."""
    roots = config.get('config.literal_check_roots', root)
    excludes = tuple(config.get('config.literal_check_excludes', root))
    listed = _git(root, 'ls-tree', '-r', '-z', '--name-only', commit, '--', *roots, text=True)
    changed = _git(root, 'diff', '--no-renames', '-z', '--name-only', commit, '--', *roots, text=True)
    if listed.returncode or changed.returncode:
        raise BaseError(f'cannot list the scanned files of {commit}: {(listed.stderr or changed.stderr).strip()}')
    unlistable, edited = _unlistable(root), set(changed.stdout.split('\0'))
    found, unowned, read = {}, config.get('literals.unowned_area', root), []
    for path in filter(None, listed.stdout.split('\0')):
        if path.startswith(excludes) or unlistable(path):
            continue
        if path in edited:
            read.append(path)
        elif path in current:
            area, lines = current[path]
            found[path] = (area, {value: len(at) for value, at in lines.items()})
    rules = Census(root)
    suffixes = tuple(config.get('config.literal_check_suffixes', root))
    shebangs = config.get('config.literal_check_shebangs', root)
    store = source_facts.store(root)
    for path, text in _blobs(root, commit, read).items():
        kind = _kind(path, text, suffixes, shebangs)
        for _, kind_found, value in _hits(text, kind, rules, store) if kind else []:
            counts = found.setdefault(path, (_area(path, root, unowned), {}))[1]
            counts[key(kind_found, value)] = counts.get(key(kind_found, value), 0) + 1
    return found


def merge_base(root, base):
    found = _git(root, 'merge-base', base, 'HEAD', text=True)
    if found.returncode:
        raise BaseError(f'no merge-base of {base} and HEAD: {found.stderr.strip() or "no common history"}')
    return found.stdout.strip()


def _totals_of(found):
    totals = {}
    for area, counts in found.values():
        for value, count in counts.items():
            totals[(area, value)] = totals.get((area, value), 0) + (count if isinstance(count, int) else len(count))
    return totals


LEGACY_DIRS = {'baseline': ('scripts/lib/absolute-literals-baseline', 'files'),
               'catalog': ('scripts/lib/literal-catalogs', 'catalogs')}  # the old per-area lists and their entry key


def legacy_lists(root, commit, census):
    """{path: entry} of one old list (TX22 option b, F96) as it stood at commit: every *.json of the folder and of its
    subfolders (absolute-literals-baseline/engine/<unit>.json). An absent folder or an unreadable file holds nothing:
    the old data is an input that may be gone, never one that fails the census."""
    folder, entry_key = LEGACY_DIRS[census]
    listed = _git(root, 'ls-tree', '-r', '-z', '--name-only', commit, '--', folder, text=True)
    held = {}
    for name in filter(None, listed.stdout.split('\0') if not listed.returncode else []):
        if not name.endswith('.json'):
            continue
        shown = _git(root, 'show', f'{commit}:{name}', text=True)
        try:
            entries = json.loads(shown.stdout).get(entry_key) or {}
        except (ValueError, AttributeError):
            continue
        if shown.returncode == 0 and isinstance(entries, dict):
            held.update(entries)
    return held


def with_legacy(root, commit, before):
    """before (base_census) plus the counts of the old baseline lists at commit: per path and key the larger count, so a
    count recorded only in the old format still allows what it allowed and the migration loses none."""
    merged, unowned = dict(before), config.get('literals.unowned_area', root)
    for path, counts in legacy_lists(root, commit, 'baseline').items():
        if not isinstance(counts, dict):
            continue
        area, held = merged.get(path) or (_area(path, root, unowned), {})
        held = dict(held)
        for found, count in counts.items():
            if isinstance(count, int):
                held[found] = max(held.get(found, 0), count)
        merged[path] = (area, held)
    return merged


def derived(root, base):
    """Errors of the derived rule: per unit, kind and value, the tree spells it no more times than the census of the
    merge-base of `base` allows. A value moved between files of one unit passes; one moved to another unit does not."""
    commit = merge_base(root, base)
    now = occurrences(root)
    before = with_legacy(root, commit, base_census(root, commit, now))
    allowed, errors = _totals_of(before), []
    for (area, found), count in sorted(_totals_of(now).items()):
        if count <= allowed.get((area, found), 0):
            continue
        places = [f'{path}:{line}' for path, (owner, lines) in sorted(now.items())
                  if owner == area and len(lines.get(found, [])) > before.get(path, (owner, {}))[1].get(found, 0)
                  for line in sorted(lines[found])]
        errors.append(f'{area}: {found} is written {count} times and the census of {base} (merge-base {commit}) allows '
                      f'{allowed.get((area, found), 0)}, at {", ".join(places)}; {FIX}')
    return errors


def default_base(root):
    """The ref of literals.base_ref, when this checkout has it; BaseError (fail closed) when it does not."""
    ref = config.get('literals.base_ref', root)
    if _git(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}').returncode:
        remote, _, branch = ref.partition('/')
        raise BaseError(f'{ref} (literals.base_ref) is not in this checkout, so the base census cannot be computed: run '
                        f'git fetch {remote} {branch}, or pass --base <ref>')
    return ref


def check(root, base=None):
    """(errors, warnings): no unit spells a value more times than the census of the base (`base`, else
    literals.base_ref) allows; without a readable base, one error and nothing allowed."""
    root = Path(root)
    try:
        config.get('literals.base_ref', root)
    except config.ConfigError:
        return [], []  # a checkout without the literals registry (a fixture of another check)
    try:
        return derived(root, base or default_base(root)), []
    except BaseError as error:
        return [f'literals: {error}; the allowed counts are the base census, so nothing is allowed (fail closed)'], []


def main(argv):
    if argv[:1] == ['--base'] and len(argv) == len(['--base', 'REF']):
        base = argv[1]
    elif not argv:
        base = None
    else:
        sys.exit('usage: literal_census.py [--base REF]')
    errors = check(ROOT, base)[0]
    print('\n'.join(errors) or 'literals: no unit spells a value more times than the base census')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
