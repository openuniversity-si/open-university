"""Mechanical enforcement of the docs/SEMENTE.md §6 intention lock (D-317, audit C4).

Locked targets:
  - docs/SEMENTE.md sections 3 and 6 (the intention, its ladder goals, and its locked constraints);
    non-locked sections (§1, §2, §4, §5, §7, §8) remain freely updatable through the normal flow.
  - config/intent/INT-*.json (the model's locked INT objects).

Any change to a locked target against a base ref requires a PR whose title starts with `intencao:`
(when a title is judged) and an explicit owner authorization trailer in the PR body or commits:
    Intention-Change: approved by Daniel YYYY-MM-DD HH:MM BRT (<where he approved>)
"""
import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SEMENTE = 'docs/SEMENTE.md'
LOCKED_SECTIONS = ('3', '6')
INTENT_PREFIX = 'config/intent/INT-'
INTENT_SUFFIX = '.json'
OWNER = 'Daniel'
TITLE_PREFIX = 'intencao:'
DEFAULT_BASE = 'origin/main'
SECTION_HEADING = re.compile(r'^## ([0-9]+)\.\s', re.MULTILINE)
APPROVAL = re.compile(
    r'^Intention-Change:[ \t]+approved by Daniel[ \t]+'
    r'(?P<day>[0-9]{4}-[0-9]{2}-[0-9]{2})[ \t]+'
    r'(?P<clock>[0-9]{2}:[0-9]{2})[ \t]+BRT[ \t]+'
    r'\((?P<where>[^()\n]+)\)[ \t]*$',
    re.MULTILINE,
)


def extract_sections(text):
    """Return {section_number_str: section_text} for top-level numbered headings (`## N. ...`)."""
    matches = list(SECTION_HEADING.finditer(text or ''))
    found = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        found[match.group(1)] = text[match.start():end].strip()
    return found


def is_locked_intent_file(path):
    """True when `path` is a locked INT object file (`config/intent/INT-*.json`)."""
    normalized = str(path).replace('\\', '/')
    return normalized.startswith(INTENT_PREFIX) and normalized.endswith(INTENT_SUFFIX)


def parse_approval(text):
    """Return {day, clock, where, line} for the first valid Daniel Intention-Change trailer, else None."""
    for match in APPROVAL.finditer(text or ''):
        where = match.group('where').strip()
        if not where or '<' in where or '>' in where:
            continue
        day, clock = match.group('day'), match.group('clock')
        try:
            datetime.strptime(f'{day} {clock}', '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        return {'day': day, 'clock': clock, 'where': where, 'line': match.group(0).strip()}
    return None


def _git(root, *args):
    done = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, check=False)
    return done.returncode, done.stdout


def _git_show(root, ref, path):
    code, out = _git(root, 'show', f'{ref}:{path}')
    return out if code == 0 else None


def _merge_base(root, base, head):
    code, out = _git(root, 'merge-base', base, head)
    return out.strip() if code == 0 and out.strip() else None


def locked_changes(root, base, head='HEAD', include_worktree=False):
    """Sorted list of locked intention targets modified between `base` and `head` (or working tree)."""
    root = Path(root)
    merge_base = _merge_base(root, base, head)
    if not merge_base:
        return None
    if include_worktree:
        code, out = _git(root, 'diff', '--name-only', merge_base)
        names = set(out.splitlines()) if code == 0 else set()
        code_other, other = _git(root, 'ls-files', '--others', '--exclude-standard', '--', 'config/intent', SEMENTE)
        if code_other == 0:
            names |= set(other.splitlines())
    else:
        code, out = _git(root, 'diff', '--name-only', f'{merge_base}..{head}')
        names = set(out.splitlines()) if code == 0 else set()
    changed = sorted(name.strip() for name in names if name.strip())
    locked = [name for name in changed if is_locked_intent_file(name)]
    if SEMENTE in changed:
        base_text = _git_show(root, merge_base, SEMENTE)
        if include_worktree:
            semente_file = root / SEMENTE
            head_text = semente_file.read_text(encoding='utf-8') if semente_file.is_file() else None
        else:
            head_text = _git_show(root, head, SEMENTE)
        if head_text is None:
            locked.append(SEMENTE)
        else:
            before, after = extract_sections(base_text or ''), extract_sections(head_text)
            for section in LOCKED_SECTIONS:
                if before.get(section) != after.get(section):
                    locked.append(f'{SEMENTE}#{section}')
    return sorted(set(locked))


def approval_in_commits(root, merge_base, head='HEAD'):
    """Return parsed Intention-Change approval from commit messages in `merge_base..head`, else None."""
    code, out = _git(root, 'log', '--format=%B', f'{merge_base}..{head}')
    return parse_approval(out) if code == 0 else None


def intention_lock_errors(root, base, body=None, title=None, head='HEAD', include_worktree=False):
    """Refuse changes to locked sections of docs/SEMENTE.md (§3, §6) or config/intent/INT-*.json without an
    `intencao:` PR title and Daniel's Intention-Change authorization line (SEMENTE.md §6, D-317)."""
    root = Path(root)
    merge_base = _merge_base(root, base, head)
    if not merge_base:
        return [f'intention-lock: cannot resolve merge-base between {base!r} and {head!r} (SEMENTE.md §6)']
    locked = locked_changes(root, base, head=head, include_worktree=include_worktree)
    if not locked:
        return []
    found = []
    targets = ', '.join(locked)
    if title is not None and not title.strip().startswith(TITLE_PREFIX):
        found.append(
            f'intention-lock: PR touching locked intention ({targets}) must have a title starting with '
            f'"{TITLE_PREFIX}" (SEMENTE.md §6)'
        )
    approval = parse_approval(body or '') or approval_in_commits(root, merge_base, head=head)
    if approval is None:
        found.append(
            f'intention-lock: locked intention changed ({targets}) without a valid '
            '"Intention-Change: approved by Daniel YYYY-MM-DD HH:MM BRT (<where>)" line (SEMENTE.md §6)'
        )
    return found


def check_intent_objects(found, root):
    """Validate structural invariants of active INT objects: owner must be Daniel and source section must exist."""
    root = Path(root)
    semente_file = root / SEMENTE
    semente_sections = extract_sections(semente_file.read_text(encoding='utf-8')) if semente_file.is_file() else {}
    problems = []
    for ident, item in sorted(found.items()):
        if item.get('type') != 'INT' or item.get('state') == 'superseded' or 'body' not in item:
            continue
        body = item['body']
        if body.get('owner') != OWNER:
            problems.append(f'{ident}: locked intention owner must be {OWNER}, not {body.get("owner")!r} (SEMENTE.md §6)')
        source = body.get('source') or ''
        rel, _, anchor = source.partition('#')
        if rel and not (root / rel).is_file():
            problems.append(f'{ident}: source file {rel} does not exist')
        elif rel == SEMENTE and anchor.isdigit() and anchor not in semente_sections:
            problems.append(f'{ident}: source section {source} does not exist in {SEMENTE}')
    return problems


def pending_lock_warnings(root, base=None):
    """Warn in plain `scripts/model check` when locked intention changed vs `base` without a commit trailer."""
    root = Path(root)
    ref = base or DEFAULT_BASE
    code, _ = _git(root, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}')
    if code != 0:
        return []
    merge_base = _merge_base(root, ref, 'HEAD')
    if not merge_base:
        return []
    locked = locked_changes(root, ref)
    if not locked or approval_in_commits(root, merge_base, 'HEAD'):
        return []
    return [
        (
            f'intention-lock: locked intention changed vs {ref} ({", ".join(locked)}) without Intention-Change trailer '
            f'in commits; requires Daniel\'s approval on an "{TITLE_PREFIX}" PR before merge (SEMENTE.md §6)'
        )
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(prog='scripts/intention-lock', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=ROOT, help='checkout to verify')
    parser.add_argument('--base', default=DEFAULT_BASE, help='base ref to compare against (default: origin/main)')
    parser.add_argument('--head', default='HEAD', help='head ref to compare (default: HEAD)')
    parser.add_argument('--pr-body', type=Path, help='PR body file holding an Intention-Change: authorization line')
    parser.add_argument('--title', help='PR title (must start with intencao: when locked intention changes)')
    parser.add_argument('--worktree', action='store_true', help='include uncommitted working-tree edits')
    args = parser.parse_args(argv)
    body = args.pr_body.read_text(encoding='utf-8') if args.pr_body else None
    refusals = intention_lock_errors(
        args.root.resolve(), args.base, body=body, title=args.title, head=args.head, include_worktree=args.worktree
    )
    for line in refusals:
        print('FAIL ' + line)
    print(f'intention-lock: {len(refusals)} refusal(s)')
    return 1 if refusals else 0


if __name__ == '__main__':
    sys.exit(main())
