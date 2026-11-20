"""The problem space, leap 1 (D-348): what comes before requirements, a module of scripts/model.

One file per object under config/problem/, each validated against its contract (contracts/model/<kind>.v1.json):
  NC        a critical success factor or necessary condition of the Goal Tree, measured (baseline, target); its
            state is derived from its measure by scripts/model's derive_validations (the reading, the benefit)
  UDE       an undesirable effect that violates conditions
  CAUSE     an entity of the current reality tree (intermediate, root, core)
  CONFLICT  the evaporating cloud that perpetuates a core cause
  INJ       a candidate injection (do-nothing, do-minimum or a proposal), chosen or rejected by a decision
  ST        a node of the strategy and tactics tree: its strategy an NC, its tactic a chosen injection
and the options appraisal of a business decision, config/problem/appraisal/D-<n>.json, held by the decision.

Two kinds of rule. What the graph says about itself is an error of `scripts/model check` (errors): a cycle in the
current reality tree, a core cause no conflict perpetuates, a chosen injection with no appraisal, an appraisal whose
criteria were fixed after its scores, a node whose strategy does not descend from its parent's, an active program
outside the tree. What depends on a reading is conformance, never an error (derive marks it and the type's
unconformant_when reads the mark), so a measure that moves never turns an unrelated change red: a condition out of
target with no effect that says so, an effect still observed when every condition it violates is met.
"""
import json
from pathlib import Path

FOLDER = 'config/problem'
APPRAISALS = 'config/problem/appraisal/D-*.json'
KINDS = (('NC', 'nc'), ('UDE', 'ude'), ('CAUSE', 'cause'), ('CONFLICT', 'conflict'), ('INJ', 'injection'),
         ('ST', 'st'))
STATED = ('CAUSE', 'CONFLICT')  # no lifecycle of their own: a stated entity of the tree or the cloud
# the levels of the strategy and tactics tree, from the intention down: who validates a node of each and who writes it
# (the contract's level 1 is the first): the intention and the domains, the programs, the units of the lanes
VALIDATORS = ('Daniel', 'Daniel', 'manager', 'coordinator')
WRITERS = ('manager', 'manager', 'domain-coordinator', 'lane')


def of_level(levels, level):
    return levels[level - 1]


def is_leaf(level):
    """The last level: its tactic is the step's own text; every level above takes a chosen injection."""
    return level == len(VALIDATORS)
DONE = 'delivered'  # a WORK state: a program left the tree's reach once delivered


def links_of(kind, body):
    """The typed links one object's body names."""
    if kind == 'NC':
        return [{'type': 'necessary-for', 'target': target} for target in body['necessary_for']]
    if kind == 'UDE':
        return [{'type': 'violates', 'target': target} for target in body['violates']]
    if kind == 'CAUSE':
        return [{'type': 'causes', 'target': target} for target in body['causes']]
    if kind == 'CONFLICT':
        return ([{'type': 'objective-is', 'target': body['objective']}] +
                [{'type': 'perpetuates', 'target': target} for target in body['perpetuates']] +
                [{'type': 'assumes', 'target': each['premise']} for each in body['assumptions'] if each.get('premise')])
    if kind == 'INJ':
        return ([{'type': 'addresses', 'target': target} for target in body['addresses']] +
                [{'type': 'inverts', 'target': effect['inverts']} for effect in body['effects']] +
                [{'type': 'decided-by', 'target': target} for target in body.get('decided_by', [])])
    if kind == 'ST':
        tactic = [{'type': 'applies', 'target': body['tactic']}] if body['tactic'].startswith('INJ-') else []
        parent = [{'type': 'child-of', 'target': body['child_of']}] if body.get('child_of') else []
        premises = [{'type': 'assumes', 'target': each['premise']} for each in body['assumptions'].values()
                    if each.get('premise')]
        return ([{'type': 'aims-at', 'target': body['strategy']}] + tactic + parent + premises +
                [{'type': 'decomposes-into', 'target': target} for target in body.get('decomposes_into', [])])
    return []


def read(root, declared, thresholds):
    """The problem-space objects of the root, read by scripts/model's `declared` (one file each, against its
    contract) and with each NC's threshold_key resolved by its `thresholds`. CAUSE and CONFLICT are `stated`; an NC's
    and an ST's state are derived later (derive), never read."""
    found = []
    for kind, contract in KINDS:
        items = declared(Path(root), f'{FOLDER}/{kind}-*.json', f'{contract}.v1.json', kind,
                         lambda body, kind=kind: links_of(kind, body))
        if kind == 'NC':
            items = thresholds(items, root)
        for item in items:
            if kind in STATED and 'body' in item:
                item['state'] = 'stated'
        found += items
    return found


def attach(found, root, declared):
    """Each options appraisal of config/problem/appraisal/ held by its decision (`appraisal` of the D object); a file
    the contract refuses, or one whose decision is not recorded, is a problem of that decision or of the file."""
    for item in declared(Path(root), APPRAISALS, 'appraisal.v1.json', 'APPR', lambda body: []):
        body = item.get('body')
        decision = found.get(body['decision']) if body else None
        if body and decision is not None and decision['type'] == 'D' and body['id'] == body['decision']:
            decision['appraisal'] = body
            continue
        target = decision if decision is not None else found.setdefault(item['id'], {**item, 'type': 'D'})
        target.setdefault('problems', []).extend(item.get('problems') or [
            f'{item["source"]}: an appraisal whose decision {body and body["decision"]} is not recorded under its name'])


def reached(found, start):
    """The undesirable effects a cause reaches through the current reality tree, and whether it met a cycle."""
    effects, seen, stack, cycle = set(), set(), [(start, ())], False
    while stack:
        ident, path = stack.pop()
        if ident in path:
            cycle = True
            continue
        item = found.get(ident) or {}
        if item.get('type') == 'UDE':
            effects.add(ident)
            continue
        if ident in seen and item.get('type') == 'CAUSE':
            continue
        seen.add(ident)
        stack += [(target, path + (ident,)) for target in (item.get('body') or {}).get('causes', [])]
    return effects, cycle


def active_effects(found):
    return [item for item in found.values() if item['type'] == 'UDE' and item['state'] != 'gone']


def derive(found):
    """After the conditions are derived from their measures: each node's state from its strategy's condition
    (proposed until validated at its level), each core cause's coverage, and the marks the types'
    unconformant_when read: an NC out of target with no effect (`untracked`), an effect still observed while every
    condition it violates is met (`stale`), a core cause not accepted or not wholly covered, a chosen injection
    with an open branch (`unsettled`)."""
    effects = active_effects(found)
    violated = {target for item in effects for target in item['body']['violates']}
    for item in found.values():
        body = item.get('body')
        if body is None:
            continue
        if item['type'] == 'NC':
            body['untracked'] = item['state'] == 'not-met' and item['id'] not in violated
        elif item['type'] == 'UDE':
            body['stale'] = item['state'] in ('observed', 'returned') and all(
                (found.get(target) or {}).get('state') == 'met' for target in body['violates'])
        elif item['type'] == 'CAUSE' and body['kind'] == 'core':
            reach, _ = reached(found, item['id'])
            body['coverage'] = len(reach) / len(effects) if effects else 1.0
            body['unsettled'] = not body.get('accepted') or body['coverage'] < 1
        elif item['type'] == 'CAUSE':
            body['unsettled'] = False
        elif item['type'] == 'INJ':
            body['unsettled'] = item['state'] == 'chosen' and any(
                not (branch.get('trimmed_by') or branch.get('accepted_by')) for branch in body['branches'])
        elif item['type'] == 'ST':
            validated = body.get('validated') or {}
            refuted = any((found.get(each.get('premise') or '') or {}).get('state') == 'refuted'
                          for each in body['assumptions'].values() if each.get('premise'))
            body['reopened_by_premise'] = refuted
            if refuted or validated.get('by') != of_level(VALIDATORS, body['level']):
                item['state'] = 'proposed'
            elif body['strategy'].startswith('INT-'):
                item['state'] = goal_state(found, body['strategy'])
            else:
                item['state'] = (found.get(body['strategy']) or {}).get('state', 'defined')


def goal_state(found, intention):
    """The state of the intention as a goal: not-met while a condition directly necessary for it is not met, met once
    every one is, else measuring (a level-1 node aims at the intention)."""
    states = [item['state'] for item in found.values() if item['type'] == 'NC' and 'body' in item
              and intention in item['body']['necessary_for']]
    if not states:
        return 'defined'
    if 'not-met' in states:
        return 'not-met'
    return 'met' if all(state == 'met' for state in states) else 'measuring'


def descends(found, child, parent):
    """Whether condition `child` is `parent` or is necessary for it through the Goal Tree."""
    stack, seen = [child], set()
    while stack:
        ident = stack.pop()
        if ident == parent:
            return True
        if ident in seen:
            continue
        seen.add(ident)
        stack += ((found.get(ident) or {}).get('body') or {}).get('necessary_for', [])
    return False


def problem_errors(found):
    """The errors of the graph's own structure (D-348's rules), one line each."""
    out = []
    appraisals = {item['id']: item['appraisal'] for item in found.values() if item['type'] == 'D' and item.get('appraisal')}
    cores = [item for item in found.values() if item['type'] == 'CAUSE' and item.get('body', {}).get('kind') == 'core']
    perpetuated = {target for item in found.values() if item['type'] == 'CONFLICT' and 'body' in item
                   for target in item['body']['perpetuates']}
    injections = [item for item in found.values() if item['type'] == 'INJ' and 'body' in item]
    for item in found.values():
        if item['type'] == 'CAUSE' and 'body' in item and reached(found, item['id'])[1]:
            out.append(f'{item["id"]}: the current reality tree has a cycle through it')
    for item in cores:
        if item['id'] not in perpetuated:
            out.append(f'{item["id"]}: a core cause no conflict perpetuates (the cloud says why it persists)')
        options = {each['body']['option'] for each in injections if item['id'] in each['body']['addresses']}
        for needed in ('do-nothing', 'do-minimum'):
            if needed not in options:
                out.append(f'{item["id"]}: a core cause with no {needed} injection among its candidates')
    tactics = {item['body']['tactic'] for item in found.values() if item['type'] == 'ST' and 'body' in item}
    for item in injections:
        body = item['body']
        if item['state'] != 'chosen':
            continue
        if item['id'] not in tactics:
            out.append(f'{item["id"]}: a chosen injection that is no node\'s tactic in the strategy and tactics tree')
        decisions = [target for target in body.get('decided_by', []) if target in appraisals]
        if not decisions:
            out.append(f'{item["id"]}: a chosen injection with no decision that holds an appraisal')
        for decision in decisions:
            out += [f'{decision}: {line}' for line in appraisal_findings(found, appraisals[decision], item['id'])]
    by_parent = {}
    for item in sorted(found.values(), key=lambda entry: entry['id']):
        if item['type'] == 'ST' and 'body' in item:
            out += [f'{item["id"]}: {line}' for line in node_findings(found, item['body'])]
            parent_id = item['body'].get('child_of')
            if parent_id:
                key = (parent_id, item['body']['tactic'].strip())
                earlier = by_parent.get(key)
                if earlier is not None:
                    out.append(f'{item["id"]}: its tactic duplicates sibling {earlier} under {parent_id}')
                else:
                    by_parent[key] = item['id']
    out += orphans(found)
    return out


def appraisal_totals(body):
    """{option: sum(weight * value)} across the appraisal's declared criteria."""
    weights = {criterion['nc']: criterion['weight'] for criterion in body['criteria']}
    totals = {option: 0.0 for option in body['options']}
    for score in body['scores']:
        if score['option'] in totals and score['nc'] in weights:
            totals[score['option']] += weights[score['nc']] * score['value']
    return totals


def appraisal_findings(found, body, chosen):
    """An appraisal's errors: criteria not from conditions or fixed after the scores, an option missing, duplicate or
    undeclared scores, or a chosen option that is not the decided injection or does not win on the weighted criteria."""
    out = []
    criteria = {criterion['nc'] for criterion in body['criteria']}
    for criterion in body['criteria']:
        if (found.get(criterion['nc']) or {}).get('type') != 'NC':
            out.append(f'its criterion {criterion["nc"]} is no condition of the Goal Tree')
    if body['criteria_fixed'] > body['scored']:
        out.append('its criteria were fixed after its scores')
    options = {(found.get(option) or {}).get('body', {}).get('option') for option in body['options']}
    for needed in ('do-nothing', 'do-minimum'):
        if needed not in options:
            out.append(f'its options leave out the {needed} injection')
    if body['chosen'] != chosen or chosen not in body['options']:
        out.append(f'its chosen option is {body["chosen"]}, not the injection it decides, {chosen}')
    declared_options = set(body['options'])
    scored, duplicates, stray = set(), [], []
    for score in body['scores']:
        pair = (score['option'], score['nc'])
        if score['option'] not in declared_options or score['nc'] not in criteria:
            stray.append(f'{score["option"]}/{score["nc"]}')
        elif pair in scored:
            duplicates.append(f'{score["option"]}/{score["nc"]}')
        scored.add(pair)
    if stray:
        out.append(f'scores for undeclared options or criteria: {", ".join(stray)}')
    if duplicates:
        out.append(f'duplicate scores: {", ".join(duplicates)}')
    missing = [f'{option}/{criterion["nc"]}' for option in body['options'] for criterion in body['criteria']
               if (option, criterion['nc']) not in scored]
    if missing:
        out.append(f'scores missing: {", ".join(missing)}')
    elif not duplicates and chosen in declared_options:
        totals = appraisal_totals(body)
        beaten = [option for option in body['options'] if option != chosen and totals[option] >= totals[chosen]]
        if beaten:
            ranked = ', '.join(f'{option} ({totals[option]:g})' for option in beaten)
            out.append(f'its chosen option {chosen} ({totals[chosen]:g}) does not beat {ranked} on the weighted criteria')
    return out


def node_findings(found, body):
    out = []
    writer = of_level(WRITERS, body['level'])
    if body['owner_role'] != writer:
        out.append(f'a level-{body["level"]} node is written by the {writer}, not the {body["owner_role"]}')
    parent = found.get(body.get('child_of') or '')
    if body['level'] > 1 and not parent:
        out.append('a node below level 1 with no parent node')
    if parent and 'body' in parent:
        if parent['body']['level'] + 1 != body['level']:
            out.append(f'its parent {parent["id"]} is not one level above')
        if not descends(found, body['strategy'], parent['body']['strategy']):
            out.append(f'its strategy {body["strategy"]} does not descend from its parent\'s, {parent["body"]["strategy"]}')
        if body['tactic'].strip() == parent['body']['tactic'].strip():
            out.append(f'its tactic repeats its parent {parent["id"]}\'s tactic')
    if body['level'] == 1:
        if (found.get(body['tactic']) or {}).get('state') != 'chosen':
            out.append(f'a level-1 node whose tactic {body["tactic"]} is no chosen injection')
    elif (not is_leaf(body['level']) and body['tactic'].startswith('INJ-')
          and (found.get(body['tactic']) or {}).get('state') != 'chosen'):
        out.append(f'a level-{body["level"]} node whose tactic {body["tactic"]} is no chosen injection')
    premises = [each['premise'] for each in body['assumptions'].values() if each.get('premise')]
    if not premises:
        out.append('its assumptions link no premise of the register (P-NN)')
    for ident in premises:
        if (found.get(ident) or {}).get('type') != 'P':
            out.append(f'its assumption premise {ident} is not in the premise register')
    programs_level = len(VALIDATORS) - 1
    for target in body.get('decomposes_into', []):
        work = found.get(target)
        if not work or work.get('type') != 'WORK':
            out.append(f'decomposes_into {target} is not a work item')
            continue
        if work.get('state') == DONE:
            out.append(f'decomposes_into {target}, which is no longer active ({work["state"]})')
        kind = (work.get('body') or {}).get('kind')
        if body['level'] == programs_level and kind is not None and kind != 'program':
            out.append(f'decomposes_into {target}, which is not a program ({kind})')
        elif is_leaf(body['level']) and kind == 'program':
            out.append(f'decomposes_into {target}, a program on a leaf node')
    return out


def _measure_signature(body):
    threshold = body.get('threshold')
    return (json.dumps(body.get('measure'), sort_keys=True), body.get('comparator'),
            float(threshold) if isinstance(threshold, (int, float)) else threshold,
            json.dumps(body.get('window'), sort_keys=True))


def duplicate_measures(found):
    """[(nc_id, val_id)] where an NC and a VAL declare the exact same measure, comparator, threshold and window."""
    vals = [(item['id'], _measure_signature(item['body'])) for item in sorted(found.values(), key=lambda entry: entry['id'])
            if item['type'] == 'VAL' and 'body' in item]
    ncs = [(item['id'], _measure_signature(item['body'])) for item in sorted(found.values(), key=lambda entry: entry['id'])
           if item['type'] == 'NC' and 'body' in item]
    return [(nc_id, val_id) for nc_id, nc_sig in ncs for val_id, val_sig in vals if nc_sig == val_sig]


def unvalidated_needs(found):
    """Sorted ids of NEED objects still in state `proposed` (awaiting owner validation)."""
    return sorted(item['id'] for item in found.values() if item['type'] == 'NEED' and item.get('state') == 'proposed')


def diagnostics(found):
    """Audit view of the problem space: gaps, weighted appraisal totals, ST counts per level, NC/VAL duplicates,
    and unvalidated NEEDs."""
    levels = {level: 0 for level in range(1, len(VALIDATORS) + 1)}
    for item in found.values():
        if item['type'] == 'ST' and 'body' in item:
            level = item['body']['level']
            levels[level] = levels.get(level, 0) + 1
    appraisals = {item['id']: appraisal_totals(item['appraisal'])
                  for item in sorted(found.values(), key=lambda entry: entry['id'])
                  if item['type'] == 'D' and item.get('appraisal')}
    return {'gaps': gaps(found), 'appraisals': appraisals, 'st_levels': levels,
            'duplicate_measures': duplicate_measures(found), 'unvalidated_needs': unvalidated_needs(found)}


def orphans(found):
    """No work outside the tree: every program with work still to do sits under a node of the programs' level (the one
    above the leaves)."""
    programs = len(VALIDATORS) - 1
    placed = {target for item in found.values() if item['type'] == 'ST' and 'body' in item
              and item['body']['level'] == programs for target in item['body'].get('decomposes_into', [])}
    open_programs = {(item.get('body') or {}).get('program') for item in found.values()
                     if item['type'] == 'WORK' and item['state'] != DONE}
    return [f'WORK-program-{program}: a program with work to do outside the strategy and tactics tree'
            for program in sorted(open_programs - {None}) if f'WORK-program-{program}' not in placed]


def gaps(found):
    """{NC: {baseline, reading, target, gap}}: the gap per condition, derived from its measure, never stored."""
    out = {}
    for item in found.values():
        if item['type'] != 'NC' or 'body' not in item:
            continue
        body, reading = item['body'], item.get('measured')
        target = body.get('threshold')
        out[item['id']] = {'baseline': body['baseline']['value'], 'reading': reading, 'target': target,
                           'gap': None if reading is None or target is None else target - reading,
                           'state': item['state']}
    return out


def dump(value):
    return json.dumps(value, sort_keys=True)
