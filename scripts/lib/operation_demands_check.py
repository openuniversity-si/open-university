"""The confrontation of the forge's consumer demands with the tree (D-285, C3; D-322).

operation_demands (the events layer) declares the demands and refuses an adapter without evidence at run time; this
module confronts that declaration with the call sites, adapter methods and test references operation_relations
extracts from the tree (the planning layer), so the runtime refusal never imports the census. unit_check's operation
check calls confront; `python3 scripts/lib/operation_demands_check.py` prints the report and exits 1 on a finding.
"""
import argparse
from pathlib import Path
import sys

import operation_demands
import operation_relations

ROOT = operation_demands.ROOT


def confront(root=None):
    """Differences against independently extracted call sites, methods and test references."""
    base = Path(root) if root is not None else ROOT
    document, actual, found = operation_demands.load(base), {}, []
    for site in operation_relations.sites(base):
        actual.setdefault(site['file'], set()).add(site['operation'])
    declared = document['consumers']
    for consumer in sorted(set(actual) | set(declared)):
        demand, seen = set(declared.get(consumer, [])), actual.get(consumer, set())
        for operation in sorted(seen - demand):
            found.append(('undeclared-demand', f'{consumer}: {operation}'))
        for operation in sorted(demand - seen):
            found.append(('unknown-demand', f'{consumer}: {operation}; static extraction cannot confirm it'))
    methods = operation_relations.adapters(base)
    methods['memory'] = operation_relations.public_methods(base, operation_relations.PORT, 'MemoryAdapter') or []
    surface = operation_relations.surface(base)
    for adapter, proofs in document['proofs'].items():
        for operation, reference in proofs.items():
            if operation not in surface or operation not in methods.get(adapter, []):
                found.append(('unimplemented-proof', f'{adapter}: {operation}'))
            if not operation_demands._evidence(base, reference, operation):
                found.append(('unknown-proof', f'{adapter}: {operation}: {reference}'))
    return found


def report(root=None):
    base = Path(root) if root is not None else ROOT
    document = operation_demands.load(base)
    operations = set(operation_relations.surface(base))
    methods = operation_relations.adapters(base)
    methods['memory'] = operation_relations.public_methods(base, operation_relations.PORT, 'MemoryAdapter') or []
    lines = [f'demands: {len(set(op for ops in document["consumers"].values() for op in ops))} operations; '
             f'{len(document["consumers"])} consumers']
    for adapter, proofs in document['proofs'].items():
        unproven = sorted((set(methods.get(adapter, [])) & operations) - set(proofs))
        lines.append(f'{adapter}: {len(proofs)} proven; implemented without proof: {unproven}')
        lines += [f'  refuses {operation}: {consumer}' for consumer, operation in
                  operation_demands.refusals(adapter, document['consumers'], document, base)]
    lines += [f'unknown {row["id"]}: {row["what"]}' for row in document.get('unknowns', [])]
    findings = confront(base)
    lines.append(f'confrontation: {len(findings)} finding(s)')
    lines += [f'  {kind}: {detail}' for kind, detail in findings]
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path)
    args = parser.parse_args()
    print(report(args.root))
    return bool(confront(args.root))


if __name__ == '__main__':
    sys.exit(main())
