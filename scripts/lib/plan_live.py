"""The live plan (live-planning LP3, D-071; design 3): fold, validate and log.

live plan(p) = fold(program.v1 block of plan.md (version 0), plan.changed events of p (versions 1..n, in order)).
The fold is pure, so the plan at any past version is reproducible. The log is docs/programs/<p>/plan-log.jsonl on the
branch named by planner.log_branch: one plan.changed payload per line (contracts/events/plan.changed.v1.json),
append-only, hash-chained through `digest` and `parent`.

The folded plan is the program.v1 mapping plus `version`, `holds` ({unit: {reason, release_when}}), `brief_lines`
({unit: [line]}) and `priority` ({unit: rank}); `records` ([{version, op, unit, args}]) appears once a decision op is
folded. A null `unit` on hold, release or brief_line means every unit (key ALL). The ops (`args` per op):

  add_unit {depends_on, owner, model, wave, done, ...}   set_unit {field: value}   remove_unit {}
  set_deps {depends_on}   reorder {rank} on a unit, or {order: [unit]} on the program (rank = position, from 1)
  hold {reason, release_when}   release {}   brief_line {line}
  set_estimate, rescope, redo, continue, register_defect, apply_lesson, escalate, note: kept in `records` as decided;
  the first five name an existing unit.

After the ops of a change the graph must still validate (program.v1 schema, program.graph_problems) and every hold,
brief line and priority must name a unit of the graph. append() is the only writer: it refuses a parent that is not the
log's head (optimistic concurrency) and leaves committing and pushing to its caller (LP6). Read-only on git.

Stub from the preparation unit (LP2); bodies by LP3. LP5 tests against FIXTURE
(scripts/tests/fixtures/live-planning-fold.json): `plan` is a program.v1 block, `changes` are plan.changed payloads,
`expected` is fold(plan, changes) and `expected_at` maps a version to the folded plan at that version.
"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess

import event_contracts
import json_schema
import program as programs

FIXTURE = Path(__file__).resolve().parent.parent / 'tests' / 'fixtures' / 'live-planning-fold.json'
CONTRACT = 'plan.changed.v1.json'
LOG_FILE = 'plan-log.jsonl'  # fixed by the contract: docs/programs/<program>/plan-log.jsonl
FOLDED = ('version', 'holds', 'brief_lines', 'priority', 'records')
ALL = '*'
UNIT_RECORDS = ('set_estimate', 'rescope', 'redo', 'continue', 'apply_lesson')
RECORDS = UNIT_RECORDS + ('register_defect', 'escalate', 'note')


class PlanError(ValueError):
    """A change that cannot be applied: stale parent, broken digest chain, unknown unit, or a graph that no longer validates."""


def canonical(change):
    return json.dumps(change, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(change):
    """sha256 hex of the canonical JSON (sorted keys, compact separators, UTF-8) of the change without its `digest`."""
    body = {key: value for key, value in change.items() if key != 'digest'}
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def operations():
    """The closed op set, read from the plan.changed contract."""
    schema = json.loads((event_contracts.directory() / CONTRACT).read_text())
    return tuple(schema['properties']['ops']['items']['properties']['op']['enum'])


def initial(plan):
    """Version 0: the program.v1 mapping with the folded fields (an already folded plan is kept as is)."""
    folded = copy.deepcopy(plan)
    folded.setdefault('version', 0)
    for field in ('holds', 'brief_lines', 'priority'):
        folded.setdefault(field, {})
    return folded


def graph(plan):
    """The program.v1 part of a folded plan."""
    return {key: value for key, value in plan.items() if key not in FOLDED}


def _units(plan):
    return {unit['id']: unit for unit in plan['units']}


def _need(units, unit, op):
    if unit not in units:
        raise PlanError(f'{op}: unknown unit {unit!r}')
    return units[unit]


def _arg(args, name, op, kind):
    if not isinstance(args.get(name), kind):
        raise PlanError(f'{op}: args.{name} is missing or not a {kind.__name__}')
    return args[name]


def _target(units, unit, op):
    """The key of a hold, release or brief line: a unit of the graph, or ALL for a null unit."""
    if unit is None:
        return ALL
    _need(units, unit, op)
    return unit


def _apply(plan, change):
    """The plan after the ops of one change, in order; PlanError names the first op that cannot apply."""
    plan = copy.deepcopy(plan)
    for index, item in enumerate(change['ops'], 1):
        op, unit, args = item['op'], item.get('unit'), item.get('args') or {}
        units = _units(plan)
        where = f'op {index} {op}'
        if op == 'add_unit':
            if not unit or unit in units:
                raise PlanError(f'{where}: unit {unit!r} is missing or exists')
            plan['units'].append({'id': unit, **copy.deepcopy(args)})
        elif op == 'set_unit':
            if 'id' in args:
                raise PlanError(f'{where}: a unit id is not renamed; remove_unit then add_unit')
            _need(units, unit, where).update(copy.deepcopy(args))
        elif op == 'remove_unit':
            _need(units, unit, where)
            plan['units'] = [entry for entry in plan['units'] if entry['id'] != unit]
            for field in ('holds', 'brief_lines', 'priority'):
                plan[field].pop(unit, None)
        elif op == 'set_deps':
            _need(units, unit, where)['depends_on'] = list(_arg(args, 'depends_on', where, list))
        elif op == 'reorder':
            if unit is None:
                order = _arg(args, 'order', where, list)
                for rank, name in enumerate(order, 1):
                    _need(units, name, where)
                    plan['priority'][name] = rank
            else:
                _need(units, unit, where)
                plan['priority'][unit] = _arg(args, 'rank', where, int)
        elif op == 'hold':
            key = _target(units, unit, where)
            _arg(args, 'reason', where, str)
            _arg(args, 'release_when', where, str)
            plan['holds'][key] = copy.deepcopy(args)
        elif op == 'release':
            key = _target(units, unit, where)
            if key not in plan['holds']:
                raise PlanError(f'{where}: {key} is not held')
            del plan['holds'][key]
        elif op == 'brief_line':
            key = _target(units, unit, where)
            plan['brief_lines'].setdefault(key, []).append(_arg(args, 'line', where, str))
        elif op in RECORDS:
            if op in UNIT_RECORDS or unit is not None:
                _need(units, unit, where)
            plan.setdefault('records', []).append({'version': change['version'], 'op': op, 'unit': unit,
                                                    'args': copy.deepcopy(args)})
        else:
            raise PlanError(f'{where}: unknown op')
    plan['version'] = change['version']
    return plan


def fold(plan, changes):
    """The plan with every change applied in order; `plan` is a program.v1 mapping, `changes` plan.changed payloads.

    Returns a new mapping (the input is not modified) that adds `version`, `holds` ({unit: reason and release_when}),
    `brief_lines` ({unit: [line]}) and `priority` ({unit: rank}) to the program.v1 fields. Raises PlanError on a stale
    parent, a bad digest or an op that leaves the graph invalid."""
    folded, previous = initial(plan), None
    for change in changes:
        problems = validate(folded, change)
        if previous is not None and change.get('parent', {}).get('digest') != previous.get('digest'):
            problems.append(f'chain broken: parent digest of version {change.get("version")} is not the digest of '
                            f'version {previous.get("version")}')
        if problems:
            raise PlanError(f'version {change.get("version")}: ' + '; '.join(problems))
        folded, previous = _apply(folded, change), change
    return folded


def validate(plan, change):
    """The errors (strings) of one change against the plan it would apply to; empty means it can be appended."""
    plan = initial(plan)
    errors = []
    parent = change.get('parent')
    if not isinstance(parent, dict) or not isinstance(parent.get('version'), int) or not isinstance(parent.get('digest'), str):
        return ['parent must be {version, digest}']
    if parent['version'] != plan['version']:
        errors.append(f'stale parent: version {parent["version"]}, the plan is at version {plan["version"]}')
    if parent['version'] == 0 and parent['digest']:
        errors.append('the parent of version 1 has an empty digest')
    if change.get('version') != parent['version'] + 1:
        errors.append(f'version {change.get("version")} does not follow its parent {parent["version"]}')
    if change.get('program') != plan.get('program'):
        errors.append(f'program {change.get("program")!r} is not {plan.get("program")!r}')
    if 'digest' in change and change['digest'] != digest(change):
        errors.append('digest is not the sha256 of the canonical line')
    ops = change.get('ops')
    if not isinstance(ops, list) or not ops:
        return errors + ['ops must be a non-empty list']
    known = operations()
    for index, item in enumerate(ops, 1):
        if not isinstance(item, dict) or item.get('op') not in known:
            errors.append(f'op {index}: not one of the plan.changed ops')
        elif not isinstance(item.get('args', {}), dict):
            errors.append(f'op {index} {item["op"]}: args must be an object')
    if errors:
        return errors
    try:
        after = _apply(plan, change)
    except PlanError as error:
        return [str(error)]
    shape = graph(after)
    errors += [str(error) for error in json_schema.validate(programs.schema(), shape) or []]
    if not errors:
        errors += programs.graph_problems(shape)
    names = set(_units(after)) | {ALL}
    for field in ('holds', 'brief_lines', 'priority'):
        errors += [f'{field} names unknown unit {name}' for name in after[field] if name not in names]
    return errors


def log_path(program, root=None):
    return programs.programs_dir(root) / program / LOG_FILE


def _git(root, *args):
    return subprocess.run(['git', '-C', str(programs.base(root)), *args], capture_output=True, text=True)


def _text(program, root, ref):
    """The log text from the checkout (ref None) or from a git ref; a missing ref or file is an empty log (version 0)."""
    path = log_path(program, root)
    if ref is None:
        return path.read_text() if path.is_file() else ''
    rel = path.relative_to(programs.base(root)).as_posix()
    if _git(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}').returncode:
        return ''
    if _git(root, 'cat-file', '-e', f'{ref}:{rel}').returncode:
        return ''
    shown = _git(root, 'show', f'{ref}:{rel}')
    if shown.returncode:
        raise PlanError(f'git show {ref}:{rel}: {shown.stderr.strip()}')
    return shown.stdout


def check_chain(changes):
    """Problems of a log's hash chain: consecutive versions from 1, each parent the previous line, each digest its own."""
    problems, previous = [], {'version': 0, 'digest': ''}
    for line, change in enumerate(changes, 1):
        parent = change.get('parent') or {}
        if change.get('version') != previous['version'] + 1:
            problems.append(f'line {line}: version {change.get("version")} after {previous["version"]}')
        if parent.get('version') != previous['version'] or parent.get('digest') != previous['digest']:
            problems.append(f'line {line}: parent is not line {line - 1} (chain broken)')
        if change.get('digest') != digest(change):
            problems.append(f'line {line}: digest does not match its content (chain broken)')
        previous = {'version': change.get('version'), 'digest': change.get('digest')}
    return problems


def read_log(program, root=None, ref=None):
    """The plan.changed payloads of a program from its plan log, in version order, chain-checked.

    ref None reads the log file of the checkout at `root` (the planner's plan/live checkout); a ref (for example
    origin/plan/live) reads it through git without touching the working tree."""
    changes = []
    for line, text in enumerate(_text(program, root, ref).splitlines(), 1):
        if not text.strip():
            continue
        try:
            changes.append(json.loads(text))
        except json.JSONDecodeError as error:
            raise PlanError(f'{LOG_FILE} line {line}: {error}') from None
    problems = check_chain(changes)
    if problems:
        raise PlanError(f'{program}: ' + '; '.join(problems))
    return changes


def head(changes):
    """The parent the next change must name."""
    last = changes[-1] if changes else None
    return {'version': last['version'], 'digest': last['digest']} if last else {'version': 0, 'digest': ''}


def plan_at(program, at=None, root=None, ref=None):
    """The folded plan of a program at version `at` (default: the head of its log)."""
    changes = read_log(program, root, ref)
    if at is not None and not 0 <= at <= len(changes):
        raise PlanError(f'{program}: no version {at}; the log ends at version {len(changes)}')
    return fold(programs.load(program, root), changes[:at] if at is not None else changes)


def append(program, change, root=None):
    """Append one change (parent must be the current head) to the plan log; the caller commits and pushes it.

    A change without `digest` gets it computed; returns the line written."""
    changes = read_log(program, root)
    current = head(changes)
    if change.get('parent') != current:
        raise PlanError(f'{program}: stale parent {change.get("parent")}; the head is {current}')
    change = dict(change)
    change.setdefault('digest', digest(change))
    fold(programs.load(program, root), changes + [change])
    path = log_path(program, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as log:
        log.write(canonical(change) + '\n')
    return change
