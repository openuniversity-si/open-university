"""Repository hygiene (OU-DECOUPLE F2, D-105), a module of scripts/structure-check.

Two rules about every tracked file lived only in Open University's vitest suite; they are ported here so they outlive
it, and every word of them is a registry entry (config/registry/structure/):
  - no tracked text file holds an address on the legacy domain (structure.legacy_email_pattern, case-insensitive),
    except the paths of structure.legacy_email_exempt; a file that is not UTF-8 text is not scanned. Ported from
    Open University's no-legacy-email test;
  - no tracked raster image (structure.raster_pattern, case-insensitive) outside structure.raster_allowed: images live
    in object storage, never in git (AGENTS.md). Ported from Open University's repo assets check.
  - no tracked text file under structure.conflict_marker_roots holds a merge conflict marker line
    (structure.conflict_marker_pattern; D-189): a committed block in DECISIONS.md once stayed green.
  - no git write passes a variable as its message on the command line (C1, D-206): it goes through stdin.
check(root) returns the errors, one per offending file and address. The address scan is one `git grep -P` (tens of
milliseconds); a git without PCRE gets the same scan in Python.
"""
import ast
import python_source
from pathlib import Path
import re
import subprocess

import config


def tracked(root):
    """The tracked paths; none outside a git work tree (a test fixture of the structure check)."""
    listed = subprocess.run(['git', '-C', str(root), 'ls-files', '-z'], capture_output=True)
    return [path for path in listed.stdout.decode().split('\0') if path] if listed.returncode == 0 else []


def addresses(root, pattern, paths):
    """{(path, address)} of every match of `pattern` (case-insensitive) in a tracked UTF-8 text file."""
    found = subprocess.run(['git', '-C', str(root), 'grep', '-I', '-i', '-o', '-z', '-P', '-e', pattern, '--', '.'],
                           capture_output=True)
    if found.returncode in (0, 1):
        rows = (line.split(b'\0', 1) for line in found.stdout.splitlines() if line)
        return {(path.decode(), match.decode()) for path, match in rows}
    compiled, hits = re.compile(pattern, re.IGNORECASE), set()
    for path in paths:
        try:
            text = (Path(root) / path).read_text()
        except (OSError, UnicodeDecodeError):
            continue
        hits.update((path, match.group(0)) for match in compiled.finditer(text))
    return hits


def argv_message_errors(path, source, verbs, message_flags):
    """One error per call of `path` that names a git write verb and passes `-m` or `--message` followed by anything
    but a literal or an f-string (a name, a call, an attribute: text of unbounded size on the command line)."""
    try:
        tree = python_source.parse(source)
    except SyntaxError:
        return []
    errors = []
    for node in python_source.select(tree, ast.Call, ast.List, ast.Tuple):
        items = node.args if isinstance(node, ast.Call) else node.elts if isinstance(node, (ast.List, ast.Tuple)) else []
        names = [item.value for item in items if isinstance(item, ast.Constant) and isinstance(item.value, str)]
        if not set(names) & set(verbs):
            continue
        for item, after in zip(items, items[1:]):
            if isinstance(item, ast.Constant) and item.value in message_flags and \
                    not isinstance(after, (ast.Constant, ast.JoinedStr)):
                errors.append(f'{path}:{after.lineno}: a git write passes its message as a command-line argument; '
                              'write it through stdin (forge_git_ref._commit) (structure.git_message_argv_allowed)')
    return errors


def source_check(root):
    """Syntax diagnostics over source/configuration only; returned separately from the live text checks."""
    root = Path(root)
    allowed = set(config.get('structure.git_message_argv_allowed'))
    verbs, flags = config.get('structure.git_write_verbs'), ('-m', '--message')
    errors = []
    for path in tracked(root):
        if path.startswith('scripts/') and path.endswith('.py') and '/tests/' not in path and path not in allowed:
            try:
                errors += argv_message_errors(path, (root / path).read_text(), verbs, flags)
            except (OSError, UnicodeDecodeError):
                continue
    return errors, []


def tree_check(root):
    root = Path(root)
    exempt = set(config.get('structure.legacy_email_exempt'))
    raster = re.compile(config.get('structure.raster_pattern'), re.IGNORECASE)
    allowed = [re.compile(pattern) for pattern in config.get('structure.raster_allowed')]
    paths = tracked(root)
    errors = [f'{path}: a tracked raster image; images live in object storage, never in git (structure.raster_allowed)'
              for path in paths if raster.search(path) and not any(pattern.search(path) for pattern in allowed)]
    hits = addresses(root, config.get('structure.legacy_email_pattern'), [path for path in paths if path not in exempt])
    errors += [f'{path}: holds {found}, an address on the legacy domain (structure.legacy_email_pattern)'
               for path, found in sorted(hits) if path not in exempt]
    roots = tuple(config.get('structure.conflict_marker_roots'))
    scanned = [path for path in paths if path.startswith(roots)]
    marked = addresses(root, config.get('structure.conflict_marker_pattern'), scanned)
    errors += [f'{path}: holds a merge conflict marker line {found!r} (structure.conflict_marker_pattern); resolve the merge'
               for path, found in sorted(marked) if path.startswith(roots)]
    return errors


def check(root):
    return tree_check(root) + source_check(root)[0]
