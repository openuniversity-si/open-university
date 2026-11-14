"""The performance budgets' registry check (D-069 item 14), a module of scripts/structure-check.

check(root, base) returns (errors, warnings):
  looser     an entry of budgets.tighten_only (a max may not grow, a min may not shrink) that differs from the base
             in the loosening direction is refused unless its x-source gains a decision id recorded in
             docs/domain/DECISIONS.md; tightening needs nothing, and a new entry has no base to be looser than;
  baseline   budgets.baseline_path, when present, validates against contracts/budgets/baseline.v1.json, names only
             budgeted metrics, and no value grew beyond budgets.regression_tolerance_percent over the base baseline
             unless its metric's entry gains such a decision (a baseline rewritten upward would hide a regression).
D-064 (f), the gate ceiling, stays a warning and is not a budget of this list.
"""
import json
from pathlib import Path
import re

import config
import config_check
import budgets

DECISION = re.compile(r'\bD-\d{3}\b')
ROW = re.compile(r'^\|\s*(D-\d{3})\s*\|', re.M)


def decisions(root):
    path = Path(root) / 'docs' / 'domain' / 'DECISIONS.md'
    return set(ROW.findall(path.read_text(encoding='utf-8'))) if path.is_file() else set()


def cited(entry):
    return set(DECISION.findall(entry.get('x-source') or ''))


def looser(new, old, bound):
    return new > old if bound == 'max' else new < old


def registry(root):
    params = {}
    for path in sorted((Path(root) / 'config' / 'registry').glob('*.json')):
        params.update(json.loads(path.read_text(encoding='utf-8'))['properties'])
    return params


def new_decision(name, params, before, known):
    """True when the entry's x-source gains a decision id that DECISIONS.md records."""
    return bool((cited(params[name]) - cited(before.get(name) or {})) & known)


def check_entries(root, base, params, before, known):
    errors = []
    for item in params['budgets.tighten_only']['default']:
        name, bound = item['name'], item['bound']
        if name not in before or name not in params:
            continue
        old, new = before[name].get('default'), params[name].get('default')
        if looser(new, old, bound) and not new_decision(name, params, before, known):
            errors.append(f'{name}: the budget went from {old} to {new}, which is looser ({bound}); a budget only '
                          f'tightens, and loosening needs a decision recorded in DECISIONS.md added to its x-source '
                          f'(D-069 item 14)')
    return errors


def check_baseline(root, base, params, before, known):
    path = Path(root) / params['budgets.baseline_path']['default']
    if not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as error:
        return [f'{path.name}: not JSON ({error})']
    errors = [f'{params["budgets.baseline_path"]["default"]}: {text}' for text in budgets.schema_errors(document)]
    old = json.loads(config_check._at_base(root, base, params['budgets.baseline_path']['default']) or '{"metrics": []}') if base else {'metrics': []}
    previous = {(m['metric'], m['subject']): m['value'] for m in old.get('metrics', [])}
    tolerance = params['budgets.regression_tolerance_percent']['default']
    for item in document.get('metrics', []):
        if item['metric'] not in budgets.METRICS:
            errors.append(f'{item["metric"]}: the baseline names a metric that is not budgeted ({", ".join(budgets.METRICS)})')
            continue
        was = previous.get((item['metric'], item['subject']))
        if was is not None and item['value'] > was * (1 + tolerance / params['budgets.percent_whole']['default']) and not new_decision(item['metric'], params, before, known):
            errors.append(f'{item["metric"]} {item["subject"]}: the baseline grew from {was} to {item["value"]}, beyond '
                          f'{tolerance} percent; a baseline is never rewritten upward without a decision (D-069 item 14)')
    return errors


def check(root, base=None):
    root = Path(root)
    if not (root / 'config' / 'registry' / 'budgets.json').is_file():
        return [], []
    params, known = registry(root), decisions(root)
    before = config_check._registry_params_at(root, base) if base else {}
    return check_entries(root, base, params, before, known) + check_baseline(root, base, params, before, known), []
