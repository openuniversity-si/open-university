"""The cheapest-useful-effort check (EFFORT-STEP; D-069 items 4, 8 and 9, D-065 (5)), a module of scripts/structure-check.

A plan (docs/units/<unit>/plan.md) and a PR body carry the block `## <effort.heading>` with one line per field of
effort.fields (`Action:`, `Cost:`, `Requirement:`, `Cheaper rejected:`). Refused:
  - the block is absent, or a field is absent, empty or a placeholder (effort.placeholders);
  - the requirement field (effort.requirement_field) names no owner: a person or role of effort.owners, or a lane of
    the registry list effort.owner_registry names (units.owners). A requirement that names only a machine
    (effort.machine_words: the gate, the train, the tests) is refused with that word, because a machine is not who needs it.
The check makes the answers exist; it never judges whether the cost is worth paying. body_errors judges a PR body (the
`pr metadata` stage). The check of every unit plan (plan_errors) was retired by
D-292: the management method (docs/padrao/METODO.md) does not require the block of a unit's plan. Every word and field is read from
config/registry/effort.json.
"""
import datetime
from pathlib import Path
import re
import subprocess

# The settings and the word match live under the configuration, for the PR body too (D-322); re-exported here.
from effort_owners import NAMES, settings, names as _names  # noqa: F401

REGISTRY = 'config/registry/effort.json'


def section(text, values):
    """The lines under the effort heading up to the next heading of the same or a higher level; None without one. A
    fenced example is not the block: fenced lines are dropped first."""
    lines, fenced = [], False
    for line in text.splitlines():
        if line.strip().startswith('```'):
            fenced = not fenced
        elif not fenced:
            lines.append(line)
    pattern = re.compile(r'^(#{1,6})\s*' + re.escape(values['effort.heading']) + r'\s*$', re.IGNORECASE)
    for index, line in enumerate(lines):
        match = pattern.match(line.strip())
        if not match:
            continue
        level, body = len(match.group(1)), []
        for rest in lines[index + 1:]:
            heading = re.match(r'^(#{1,6})\s', rest.strip())
            if heading and len(heading.group(1)) <= level:
                break
            body.append(rest)
        return body
    return None


def fields(text, values):
    """{field: value} of the effort block (a value continues on the following non-field lines); None without a block."""
    body = section(text, values)
    if body is None:
        return None
    names = values['effort.fields']
    starts = {name: re.compile(r'^\s*(?:[-*]\s+)?(?:\*\*)?' + re.escape(name) + r'(?:\*\*)?\s*:(?:\*\*)?\s*(.*)$',
                               re.IGNORECASE) for name in names}
    found, current = {}, None
    for line in body:
        hit = next(((name, starts[name].match(line)) for name in names if starts[name].match(line)), None)
        if hit:
            current = hit[0]
            found.setdefault(current, []).append(hit[1].group(1).strip())
        elif current and line.strip():
            found[current].append(line.strip())
        elif not line.strip():
            current = None
    return {name: ' '.join(part for part in parts if part).strip() for name, parts in found.items()}


def _bare(value):
    return value.strip().strip('`*_.').strip().lower()


def errors(text, where, root=None, values=None):
    """The refusals of one plan or body, each naming the missing field and the rule file. values: settings(root)."""
    values = values or settings(root)
    rule, heading, names = values['effort.rule_doc'], values['effort.heading'], values['effort.fields']
    found = fields(text, values)
    if found is None:
        listed = ', '.join(f'`{name}:`' for name in names)
        return [f'effort: {where} has no `## {heading}` block; add it with {listed} for its most expensive action ({rule})']
    placeholders = {_bare(word) for word in values['effort.placeholders']}
    out = []
    for name in names:
        value = found.get(name)
        if value is None:
            out.append(f'effort: {where}: `{name}:` is missing from `## {heading}` ({rule})')
        elif not _bare(value) or _bare(value) in placeholders:
            out.append(f'effort: {where}: `{name}:` is empty or a placeholder ("{value}") in `## {heading}` ({rule})')
    requirement = values['effort.requirement_field']
    value = found.get(requirement)
    if value and _bare(value) and _bare(value) not in placeholders and not _names(value, values['owners']):
        machines = _names(value, values['effort.machine_words'])
        if machines:
            out.append(f'effort: {where}: `{requirement}:` names {", ".join(machines)} (a machine) instead of an owner; '
                       f'say who needs the result: a person, a role or a lane ({rule})')
        else:
            out.append(f'effort: {where}: `{requirement}:` names no owner; say who needs the result: a person, a role '
                       f'or a lane ({rule})')
    return out


def _moment(stamp):
    """A unix time from an ISO 8601 stamp, or None."""
    if not stamp:
        return None
    try:
        return int(datetime.datetime.fromisoformat(str(stamp).replace('Z', '+00:00')).timestamp())
    except ValueError:
        return None


def body_grandfathered(body, root=None, base=None, created=None):
    """True when this PR was born before the rule could reach it, so its body cannot carry the block.

    Same measure as `plan_errors`, applied to the other place the block lives: on 28/10 the rule landed at 15:43 and
    the gate then refused all twenty open PRs at `pr metadata`, every one of them written before it existed — nineteen
    gate stages green and one red for a rule that did not exist when the body was typed. A body written after the
    rule is judged, including one whose block was dropped."""
    born, since = _moment(created), _rule_was_added(root, base)
    if born is None or since is None:
        return False
    if fields(body or '', settings(root)) is not None:
        return False  # it carries a block: judge it, however old the PR is
    return born < since


def body_errors(body, root=None, base=None, created=None):
    """The `pr metadata` refusals of a PR body: the checkout's registry when it has the effort file, else the tool's
    own (a body is judged even in a checkout that predates the rule). A PR born before the rule is exempt."""
    if root is not None and not (Path(root) / REGISTRY).is_file():
        root = None
    if body_grandfathered(body, root, base, created):
        return []
    return errors(body or '', 'the PR body', root)


def _git(root, *args):
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else None


def _rule_was_added(root, base=None):
    """The unix time of the oldest commit that touched this registry, or None: before it, no plan can carry the block.

    With a base that already carries the registry, the base answers: that is when the rule became reachable to every
    author, and a plan written while the rule lived only inside one branch is not late."""
    for ref in ((base, 'HEAD') if base else ('HEAD',)):
        shown = _git(root, 'log', '--format=%ct', ref, '--', REGISTRY)
        stamps = [line.strip() for line in (shown or '').splitlines() if line.strip().isdigit()]
        if stamps:
            return int(stamps[-1])
    return None

