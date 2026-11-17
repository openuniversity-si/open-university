"""Mentions of a production entrypoint in a line (D-054, D-322): the one matcher of the production guard's check.

A layer-0 helper (engine-config): it imports nothing of the engine, so the literal census (a layer-0 check) can ask
whether the guard would refuse a line naming a path without importing the production guard (deploy, layer 4).
production_guard re-exports mentions for its own callers.
"""
import fnmatch
import re


def _names(entrypoints):
    """name -> regexes of its mention: the scripts/ path, the quoted bare name, a command word, the lib module."""
    patterns = {}
    for name in entrypoints:
        module = name.replace('-', '_') + '.py'
        patterns[name] = re.compile(
            rf'scripts/{re.escape(name)}(?![\w-])|scripts/lib/{re.escape(module)}'
            rf'|["\']{re.escape(name)}["\']|(?:^|[;&|(`]\s*|\$\(\s*){re.escape(name)}(?![\w-])')
    return patterns


def _comment(line):
    stripped = line.strip()
    return stripped.startswith(('#', '//', '*', '/*'))


def mentions(path, added, entrypoints, allowed):
    """(path, entrypoint, line) for every added line of a scanned file that mentions an entrypoint."""
    if any(fnmatch.fnmatch(path, glob) for glob in allowed):
        return []
    found = []
    for line in added:
        if _comment(line):
            continue
        for name, pattern in _names(entrypoints).items():
            if pattern.search(line):
                found.append((path, name, line.strip()))
    return found
