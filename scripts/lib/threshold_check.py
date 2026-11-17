"""Registry thresholds only tighten (D-069 item 14; enforcement audit 2026-10-26 rule 5), a module of scripts/structure-check.

check(root, base, body, messages) returns the errors of the registry defaults at HEAD against the base. Judged: every
entry whose name matches a glob of config.monotonic_patterns (at the base or at HEAD) or that declares x-monotonic, when
both defaults are numbers. Its direction is x-monotonic, the base's declaration winning: "max" is a ceiling (a higher
value is looser), "min" a floor (a lower value is looser); a pattern match without the key is a ceiling. A looser value
fails unless the PR body and a commit message of the PR each carry the line `Loosens: <name> D-NNN` naming a decision
recorded in docs/domain/DECISIONS.md. Tightening, an equal value and a new key pass; a removed key is schema compat's.
config.monotonic_patterns itself only grows: a pattern dropped against the base is a loosening of the check.

report(root, base, pr, body) is the audit trail of a default edited in the PR instead of through scripts/config set
(D-068 (3), D-069 item 3): one config.changed envelope per changed default (config.diff_ref against the base), built
through the forge_events port on a memory adapter and printed by structure-check as an `EVENT <json>` line of the gate
report. It is never written to the change store and never refuses.
"""
import fnmatch
import re
import subprocess

import config
import forge_events
import units

PATTERNS = 'config.monotonic_patterns'
PRODUCER = 'structure-check'
REASON = 'registry default edited in the PR, not through scripts/config set'
DECISION = re.compile(r'\bD-\d{3}\b')
LOOSENS = re.compile(r'^\s*Loosens:\s*([a-z][a-z0-9-]*\.[a-z][a-z0-9_]*)\b(.*)$', re.M)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def direction(name, before, after, patterns):
    """"max", "min" or None (not judged) for one parameter."""
    declared = before.get('x-monotonic') or after.get('x-monotonic')
    if declared:
        return declared
    return 'max' if any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns) else None


def loosenings(root, base):
    """[(name, direction, old, new)] of each judged default that is looser at HEAD than at the base."""
    before, after = config._registry_at(base, root), config._load(root)
    old_patterns = (before.get(PATTERNS) or {}).get('default') or []
    new_patterns = (after.get(PATTERNS) or {}).get('default') or []
    found = []
    dropped = sorted(set(old_patterns) - set(new_patterns))
    if dropped:
        found.append((PATTERNS, 'patterns', dropped, None))
    patterns = set(old_patterns) | set(new_patterns)
    for name in sorted(set(before) & set(after)):
        old, new = before[name].get('default'), after[name].get('default')
        if not (_number(old) and _number(new)) or old == new:
            continue
        way = direction(name, before[name], after[name], patterns)
        if (way == 'max' and new > old) or (way == 'min' and new < old):
            found.append((name, way, old, new))
    return found


def cited(text, known):
    """{name: decisions} of the `Loosens: <name> D-NNN` lines of a text, keeping only recorded decisions."""
    out = {}
    for match in LOOSENS.finditer(text or ''):
        decisions = set(DECISION.findall(match.group(2))) & known
        if decisions:
            out.setdefault(match.group(1), set()).update(decisions)
    return out


def messages(root, base):
    """The commit messages of base..HEAD, or [] when git cannot tell."""
    shown = subprocess.run(['git', '-C', str(root), 'log', '--format=%B%x00', f'{base}..HEAD'], capture_output=True, text=True)
    return [text.strip() for text in shown.stdout.split('\0') if text.strip()] if shown.returncode == 0 else []


def check(root, base, body='', notes=()):
    if not base or not (root / 'config' / 'registry' / 'config.json').is_file():
        return []
    known = units.decisions(root)  # the decision register (units, planning; D-322: not commit_check, delivery)
    in_body = cited(body, known)
    in_commits = {}
    for note in notes:
        for name, decisions in cited(note, known).items():
            in_commits.setdefault(name, set()).update(decisions)
    errors = []
    for name, way, old, new in loosenings(root, base):
        if name in in_body and name in in_commits:
            continue
        if way == 'patterns':
            change = f'drops the pattern(s) {", ".join(old)}'
        else:
            change = f'{"raises" if way == "max" else "lowers"} the {"ceiling" if way == "max" else "floor"} {old} -> {new}'
        errors.append(f'threshold: {name} {change} against {base}; thresholds only tighten (D-069 item 14). A loosening '
                      f'needs the line "Loosens: {name} D-NNN" with a recorded decision in the PR body and in a commit')
    return errors


def _git(root, *args):
    shown = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True)
    return shown.stdout.strip() if shown.returncode == 0 else ''


def report(root, base, pr=None, body=''):
    """The config.changed envelopes of every registry default edited in base..HEAD (a report, never a store write)."""
    if not base or not (root / 'config' / 'registry' / 'config.json').is_file():
        return []
    changed = [item for item in config.diff_ref(base, root) if item['kind'] == 'changed']
    if not changed:
        return []
    sha = _git(root, 'rev-parse', 'HEAD') or None
    port = forge_events.ForgeEvents(forge_events.MemoryAdapter(), forge_events.clock_from_config(), PRODUCER,
                                    f'{PRODUCER}:{pr or sha}')
    envelopes = []
    for item in changed:
        path = f'config/registry/{item["name"].split(".", 1)[0]}.json'
        actor = _git(root, 'log', '-1', '--format=%an', f'{base}..HEAD', '--', path) or PRODUCER
        subject = forge_events.subject(config.get('forge-events.repo', root), pr, sha,
                                       forge_events.premises_from_body(body), units.unit_of(path, root))
        payload = {**subject, 'name': item['name'], 'old': item['old'], 'new': item['new'], 'actor': actor,
                   'reason': REASON, 'at': forge_events.rfc3339(port.clock.now())}
        envelopes.append(port.build('config.changed', payload))
    return envelopes
