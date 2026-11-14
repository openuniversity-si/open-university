"""The declared configuration of forge operations, its reading and confrontation (D-285, C4).

Split registry files are the census, not the declaration. Consumers are file paths,
confronted both with x-readers and with literal reads in the tree. This textual floor
cannot prove dynamic reads or semantic use through helpers. Selection, adjacent
journal configuration and unknown keys stay separate from operational ownership.
Sharing is declared with shared=true, never inferred from a common consumer.
Differences are exposed, never hidden: C5 connects refusal to the flow.
"""
import argparse
import ast
import python_source
from collections import OrderedDict
import json
from pathlib import Path
import sys

import operation_relations

ROOT = Path(__file__).resolve().parent.parent.parent
DECLARATION = 'scripts/lib/operation_config_relations.json'
REGISTRY = 'config/registry/forge-events'


class RelationError(ValueError):
    """The declaration, registry or source cannot be read."""


def _document(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise RelationError(f'cannot read {path}: {error}') from None


def load(root=None):
    """The declaration by key, preserving explicit classification and sharing."""
    base = Path(root) if root is not None else ROOT
    document = _document(base / DECLARATION)
    rows = document.get('keys')
    if not isinstance(rows, list):
        raise RelationError('the configuration relation declares no keys list')
    indexed = OrderedDict()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or not row['name']:
            raise RelationError('a configuration key has no name')
        name = row['name']
        if name in indexed:
            raise RelationError(f'the relation declares {name} twice')
        if row.get('kind') not in ('operation', 'selection', 'adjacent', 'unknown'):
            raise RelationError(f'{name}: invalid configuration kind')
        for field in ('operations', 'consumers'):
            values = row.get(field)
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise RelationError(f'{name}: {field} must be a list of names')
            if len(values) != len(set(values)):
                raise RelationError(f'{name}: duplicate {field}')
        if not isinstance(row.get('reason'), str) or not row['reason']:
            raise RelationError(f'{name}: classification needs evidence or an explicit unknown reason')
        indexed[name] = row
    document['keys'] = indexed
    return document


def registry(root=None):
    """The split registry's keys and declared readers; no effective values or external store."""
    base = Path(root) if root is not None else ROOT
    return {path.stem: set(_document(path).get('x-readers') or [])
            for path in sorted((base / REGISTRY).glob('*.json')) if path.name != '_owner.json'}


def measured(root=None):
    """Literal keys in Python sources under scripts/lib, independently of the declaration.

    Constants also cover dictionary-based readers; dynamic construction remains unknown.
    Tests and generated code are not consumers. No import of a consumer is needed.
    """
    base = Path(root) if root is not None else ROOT
    keys, found = set(registry(base)), {}
    for path in sorted((base / 'scripts/lib').rglob('*.py')):
        relative = path.relative_to(base).as_posix()
        if '/generated/' in relative or '/tests/' in relative:
            continue
        try:
            tree = python_source.parse(path.read_text(encoding='utf-8'))
        except (OSError, SyntaxError) as error:
            raise RelationError(f'cannot read {relative}: {error}') from None
        for node in python_source.select(tree, ast.Constant):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in keys:
                found.setdefault(node.value, set()).add(relative)
    return found


def confront(root=None):
    """[(kind, detail)] of differences; an orphan is a finding C5 can refuse."""
    base = Path(root) if root is not None else ROOT
    declared, actual, reads = load(base)['keys'], registry(base), measured(base)
    operations = set(operation_relations.load(base)['operations'])
    found = []
    for name in sorted(set(declared) - set(actual)):
        found.append(('stale-key', f'{name}: declared but absent from the registry'))
    for name in sorted(set(actual) - set(declared)):
        found.append(('orphan-key', f'{name}: no declared configuration boundary'))
    for name, row in declared.items():
        owned = row['operations']
        if row['kind'] == 'operation' and not owned:
            found.append(('orphan-key', f'{name}: operational key without an operation'))
        if row['kind'] != 'operation' and owned:
            found.append(('kind-conflict', f'{name}: {row["kind"]} key declares operational ownership'))
        if len(owned) > 1 and row.get('shared') is not True:
            found.append(('implicit-sharing', f'{name}: multiple operations require shared=true'))
        if row.get('shared') is True and len(owned) <= 1:
            found.append(('false-sharing', f'{name}: shared key needs multiple operations'))
        for operation in sorted(set(owned) - operations):
            found.append(('unknown-operation', f'{name}: {operation} is not a declared operation'))
        if row['kind'] == 'unknown':
            found.append(('unknown-key', f'{name}: {row["reason"]}'))
        if name not in actual:
            continue
        consumers = set(row['consumers'])
        if consumers != actual[name]:
            found.append(('readers', f'{name}: declaration-only {sorted(consumers - actual[name])}; '
                          f'x-readers-only {sorted(actual[name] - consumers)}'))
        observed = reads.get(name, set())
        for path in sorted(consumers - observed):
            found.append(('stale-consumer', f'{name}: {path} no longer spells the key'))
        for path in sorted(observed - consumers):
            found.append(('undeclared-consumer', f'{name}: {path} spells the key but is not declared'))
    return found


def status(root=None):
    """Counts use the registry denominator; non-operational exceptions are explicit."""
    base = Path(root) if root is not None else ROOT
    declared, actual = load(base)['keys'], registry(base)
    rows = [row for name, row in declared.items() if name in actual]
    return {'keys': len(actual), 'covered': len(rows),
            'operational': sum(row['kind'] == 'operation' for row in rows),
            'shared': sum(len(row['operations']) > 1 and row.get('shared') is True for row in rows),
            'unknown': sum(row['kind'] == 'unknown' for row in rows),
            'without_operation': sum(not row['operations'] for row in rows) + len(set(actual) - set(declared)),
            'orphans': len(set(actual) - set(declared)) + sum(
                row['kind'] == 'operation' and not row['operations'] for row in rows)}


def report(root=None):
    counts = status(root)
    lines = ['; '.join(f'{key}: {value}' for key, value in counts.items())]
    for name, row in load(root)['keys'].items():
        lines.append(f'  {name}: {row["kind"]}; operations {row["operations"]}; '
                     f'shared {row.get("shared", False)}; {row["reason"]}')
    findings = confront(root)
    lines.append(f'confrontation: {len(findings)} finding(s)')
    lines += [f'  {kind}: {detail}' for kind, detail in findings]
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path)
    args = parser.parse_args(argv)
    try:
        print(report(args.root))
    except (RelationError, operation_relations.RelationError) as error:
        print(f'operation-config: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
