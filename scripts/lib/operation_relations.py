"""The observed relation of the engine's forge operations: its declaration, its reading and its confrontation (D-285, C2).

The declaration is scripts/lib/operation_relations.json: for each operation the port dispatches, the call sites that
name it, the consumers and units behind them, the adapters that implement it, and the responsible — explicitly accepted as engine-lane
for every operation (D-287). Responsibility is declared and never inferred from the implementation or from the lane that
owns a file (D-285; ARQ-OPERATIONS audit F2/F3). The module recomputes that relation from the tree and confronts the two:
an operation called and not declared, a declared site that is gone, a consumer no unit owns, an implementation the
declaration claims and the adapter does not define, and a declared count the tree no longer meets.

A difference is exposed, never refused: C2 records what is observed and keeps the unknown visible, and C5 is the commit
that applies the refused absence of a responsible (ARQ-OPERATIONS plan, Commits). So `confront` answers with findings a
reader prints, and `main` prints them.

The census is textual reach and therefore a floor (audit F3): a call reached through getattr, **kwargs or a test double is
not seen. It reads the port's public surface by AST — the names `ForgeEvents` dispatches through `_operation` and the one
it calls directly — and then each call under scripts/lib whose receiver names the port or the adapter it reaches.

Library:
  load(root)          the declaration, by operation name: {name: {...}}, plus its counters
  surface(root)       {operation: 'operation' | 'direct'} of the port's own public methods
  measured(root)      the sites the tree spells, in the declaration's shape
  adapters(root)      {adapter: [public methods]} of the modules the declaration names
  confront(root)      [(kind, detail)]: every difference between declaration and tree, exposed
  report(root)        the text `scripts/operation-relations` prints
"""
import argparse
import ast
import python_source
from collections import Counter, OrderedDict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
DECLARATION = 'scripts/lib/operation_relations.json'
PORT = 'scripts/lib/forge_events.py'
ADAPTER_MODULES = {
    'origin': ('scripts/lib/forge_origin.py', 'OriginAdapter'),
    'file': ('scripts/lib/forge_events.py', 'FileAdapter'),
    'git-ref': ('scripts/lib/forge_git_ref.py', 'GitRefs'),
}
# The modules whose calls are the port's own implementation: a site is a consumer that calls the port, not the port itself.
NOT_CONSUMERS = frozenset(module for module, _ in ADAPTER_MODULES.values()) | {'scripts/lib/forge_origin_client.py'}
RECEIVERS = frozenset({'port', 'reader', 'publisher', 'events', 'adapter', 'adapter_from_config'})
SCANNED = 'scripts/lib'


class RelationError(ValueError):
    """The declaration cannot be read, or the tree cannot be parsed."""


def load(root=None):
    """The declaration by operation name, plus its counters: {'operations': {...}, 'census': {...}, ...}."""
    path = (Path(root) if root is not None else ROOT) / DECLARATION
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as error:
        raise RelationError(f'cannot read the operation relation: {error}') from None
    rows = document.get('operations')
    if not isinstance(rows, list) or not rows:
        raise RelationError('the operation relation declares no operations')
    by_name = OrderedDict()
    for row in rows:
        name = row.get('name')
        if not isinstance(name, str) or not name:
            raise RelationError('an operation of the relation has no name')
        if name in by_name:
            raise RelationError(f'the relation declares {name} twice')
        by_name[name] = row
    document['operations'] = by_name
    return document


def _tree(path):
    try:
        return python_source.parse(Path(path).read_text(encoding='utf-8'))
    except (OSError, SyntaxError) as error:
        raise RelationError(f'cannot read {path}: {error}') from None


def _class(tree, name):
    return next((node for node in python_source.select(tree, ast.ClassDef) if isinstance(node, ast.ClassDef) and node.name == name), None)


def surface(root=None):
    """{operation: 'operation' | 'direct'} of the port's public methods that reach the adapter: those dispatched
    through `_operation('name')` and the one it calls on the adapter straight (`change`)."""
    base = Path(root) if root is not None else ROOT
    port = _class(_tree(base / PORT), 'ForgeEvents')
    if port is None:
        raise RelationError(f'{PORT} defines no ForgeEvents')
    found = {}
    for method in port.body:
        if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) or method.name.startswith('_'):
            continue
        for node in python_source.walk(method):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == '_operation':
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    found[node.args[0].value] = 'operation'
            if (isinstance(node, ast.Attribute) and node.attr == 'change'
                    and isinstance(node.value, ast.Attribute) and node.value.attr == 'adapter'):
                found['change'] = 'direct'
    return found


def _crossing(receiver):
    """How a call reaches the adapter: through the port, past it (`port.adapter`), or built from configuration."""
    nodes = list(python_source.walk(receiver))
    if any(isinstance(node, ast.Attribute) and node.attr == 'adapter' for node in nodes):
        return 'reach-through'
    if any(isinstance(node, ast.Attribute) and node.attr == 'adapter_from_config' for node in nodes):
        return 'factory'
    if any((isinstance(node, ast.Name) and node.id in RECEIVERS)
           or (isinstance(node, ast.Attribute) and node.attr in RECEIVERS) for node in nodes):
        return 'port'
    return None


def sites(root=None, operations=None):
    """[{operation, file, line, consumer, crossing}] of every call under the scanned tree that names an operation."""
    base = Path(root) if root is not None else ROOT
    wanted = set(operations if operations is not None else surface(root))
    found = []
    for path in sorted((base / SCANNED).rglob('*.py')):
        relative = path.relative_to(base).as_posix()
        if relative in NOT_CONSUMERS or '/tests/' in relative:
            continue
        for function in python_source.select(_tree(path), ast.FunctionDef, ast.AsyncFunctionDef):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in python_source.select(function, ast.Call):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in wanted:
                    continue
                crossing = _crossing(node.func.value)
                if crossing is None:
                    continue
                found.append({'operation': node.func.attr, 'file': relative, 'line': node.lineno,
                              'consumer': function.name, 'crossing': crossing})
    return sorted(found, key=lambda site: (site['operation'], site['file'], site['line']))


def public_methods(root, module, name):
    """The names a class defines itself: no name starting with `_`, no inherited or auxiliary client method. None when
    the module does not define the class, so an adapter this tree does not hold is an unknown and not a gap."""
    base = Path(root) if root is not None else ROOT
    holder = _class(_tree(base / module), name)
    if holder is None:
        return None
    return [method.name for method in holder.body
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and not method.name.startswith('_')]


def adapters(root=None):
    """{adapter: [public methods]} of every module this tree holds; an absent module or class is left out."""
    base = Path(root) if root is not None else ROOT
    found = {}
    for key, (module, name) in ADAPTER_MODULES.items():
        if not (base / module).is_file():
            continue
        methods = public_methods(base, module, name)
        if methods is not None:
            found[key] = methods
    return found


def measured(root=None):
    """The relation the tree spells: {operation: {'sites': [...], 'consumers': sorted files, 'units': sorted ids}}."""
    base = Path(root) if root is not None else ROOT
    rows = OrderedDict()
    for site in sites(base):
        row = rows.setdefault(site['operation'], {'sites': [], 'consumers': [], 'units': []})
        row['sites'].append({'file': site['file'], 'line': site['line'], 'consumer': site['consumer'],
                             'unit': unit_of(base, site['file']), 'crossing': site['crossing']})
    for row in rows.values():
        row['consumers'] = sorted({site['file'] for site in row['sites']})
        row['units'] = sorted({site['unit'] for site in row['sites'] if site['unit']})
    return rows


def unit_of(root, path):
    """The unit that owns a path, or None: a consumer no manifest claims is an unknown, not a guess."""
    import units  # the manifest reader; a checkout with no manifest directory answers None for every path
    try:
        return units.unit_of(path, root)
    except (units.UnitError, KeyError):  # a fixture without a registry, or a broken map: expose, never guess
        return None


def pair_sites(declared_sites, tree_sites):
    """Match declared and tree sites by operation and file, in line order: an edit above a call moves its line and is not
    a finding; only a call that appears or disappears in a file is. Returns ([(declared, tree)], stale, undeclared)."""
    groups = {}
    for side, rows in ((0, declared_sites), (1, tree_sites)):
        for site in rows:
            groups.setdefault((site['operation'], site['file']), ([], []))[side].append(site)
    paired, stale, undeclared = [], [], []
    for key in sorted(groups):
        mine, theirs = (sorted(rows, key=lambda site: site['line']) for rows in groups[key])
        paired += list(zip(mine, theirs))
        stale += mine[len(theirs):]
        undeclared += theirs[len(mine):]
    return paired, stale, undeclared


def confront(root=None):
    """[(kind, detail)] of every difference between the declaration and the tree; a difference is exposed, never refused."""
    base = Path(root) if root is not None else ROOT
    declaration = load(base)
    declared = declaration['operations']
    called = surface(base)
    found = []
    for name in sorted(set(called) - set(declared)):
        found.append(('undeclared-operation', f'{name}: the port dispatches it and the relation does not declare it'))
    for name in sorted(set(declared) - set(called)):
        found.append(('stale-operation', f'{name}: the relation declares it and the port no longer dispatches it'))
    tree_sites = sites(base, set(declared) | set(called))
    declared_sites = [dict(site, operation=name) for name, row in declared.items() for site in row.get('sites') or []]
    paired, stale, undeclared = pair_sites(declared_sites, tree_sites)
    for site in stale:
        found.append(('stale-site', f"{site['file']}:{site['line']} no longer calls {site['operation']} as declared"))
    for site in undeclared:
        found.append(('undeclared-site', f"{site['file']}:{site['line']} calls {site['operation']} and the relation "
                                         'declares no site there'))
    tree = measured(base)
    for name, row in declared.items():
        seen = tree.get(name, {'consumers': [], 'units': []})
        for path in sorted(set(seen['consumers']) - set(row.get('consumers') or [])):
            found.append(('undeclared-consumer', f'{name}: {path} calls it and is not a declared consumer'))
        for path in sorted(set(row.get('consumers') or []) - set(seen['consumers'])):
            found.append(('stale-consumer', f'{name}: the relation declares {path} and it no longer calls it'))
        for path in sorted({site['file'] for site in tree.get(name, {'sites': []})['sites'] if not site['unit']}):
            found.append(('unowned-consumer', f'{name}: {path} calls it and no unit owns that file'))
    for declared_site, site in paired:
        if declared_site.get('crossing') != site['crossing']:
            found.append(('crossing', f'{site["file"]}:{site["line"]}: the tree crosses by {site["crossing"]} and the '
                                      f'relation declares {declared_site.get("crossing")}'))
    found += implementation_findings(base, declaration)
    found += count_findings(base, declaration, tree)
    return found


def implementation_findings(base, declaration):
    """An adapter the declaration says implements an operation, and the module does not define it."""
    found, measured_adapters = [], adapters(base)
    for row in declaration.get('adapters') or []:
        key = row.get('adapter')
        if key not in measured_adapters:
            found.append(('unknown-adapter', f'{key}: the relation names an adapter no module of this tree holds'))
            continue
        methods = set(measured_adapters[key])
        for name in row.get('implements') or []:
            if name not in methods:
                found.append(('stale-implementation', f'{key}: the relation says it implements {name} and it defines no '
                                                      'such method'))
        for name in row.get('missing') or []:
            if name in methods:
                found.append(('false-gap', f'{key}: the relation says it lacks {name} and it defines it'))
    return found


def count_findings(base, declaration, tree=None):
    """The declared census (operations, sites, files) against the tree's own."""
    census = declaration.get('census') or {}
    tree = measured(base) if tree is None else tree
    counted = {'operations': len(surface(base)), 'sites': sum(len(row['sites']) for row in tree.values()),
               'files': len({site['file'] for row in tree.values() for site in row['sites']})}
    return [(f'census-{key}', f'the relation declares {census.get(key)} and the tree spells {value}')
            for key, value in counted.items() if key in census and census[key] != value]


def status(document):
    """{responsible, unknown} counts of the declaration: the observed attribution, without inferring any."""
    rows = list(document['operations'].values())
    unknown = [row['name'] for row in rows if row.get('responsible') in (None, '', 'unknown')]
    return {'operations': len(rows), 'responsible': len(rows) - len(unknown), 'unknown': len(unknown),
            'unknown_operations': unknown}


def report(root=None):
    """The text of `scripts/operation-relations`: the counters, each operation with its crossing counts, and every
    unknown. The declaration is the source; the tree's confrontation follows it, and neither is refused here."""
    base = Path(root) if root is not None else ROOT
    declaration = load(base)
    counts = status(declaration)
    lines = [f'operations: {counts["operations"]}; responsible: {counts["responsible"]}; unknown: {counts["unknown"]}']
    for name, row in declaration['operations'].items():
        crossings = Counter(site.get('crossing') for site in row.get('sites') or [])
        parts = ', '.join(f'{kind} {crossings[kind]}' for kind in sorted(crossings))
        lines.append(f'  {name}: {row.get("dispatch", "operation")}, {len(row.get("sites") or [])} site(s) in '
                     f'{len(row.get("consumers") or [])} consumer(s), responsible {row.get("responsible")}'
                     + (f', crossing {parts}' if parts else ''))
    for item in declaration.get('unknowns') or []:
        lines.append(f'unknown {item["id"]}: {item["what"]}')
    findings = confront(base)
    lines.append(f'confrontation: {len(findings)} finding(s)')
    lines += [f'  {kind}: {detail}' for kind, detail in findings]
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='operation-relations.py', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, help='repository (default: this checkout)')
    args = parser.parse_args(argv)
    try:
        print(report(args.root))
    except RelationError as error:
        print(f'operation-relations: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
