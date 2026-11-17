"""Path globs (D-322): the one matcher of the area map, the retired-product and retired-vendor records and their readers.

A layer-0 helper (engine-config): it imports nothing of the engine, so a check of any layer can match paths without
importing the gate. gate_areas re-exports glob_match for its own callers.
"""
import functools
import re


def glob_match(path, pattern):
    """`*` stays inside one path segment. `**` crosses directories."""
    return _compile_glob(pattern).fullmatch(path) is not None


@functools.lru_cache(maxsize=None)
def _compile_glob(pattern):
    parts = pattern.split('/')
    out = []
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        if part == '**':
            if index == 0 and not last:
                out.append('(?:.*/)?')
            elif last and index == 0:
                out.append('.*')
            elif last:
                out.append('(?:/.*)?')
            else:
                out.append('(?:/|/.*/)')
            continue
        if index > 0 and parts[index - 1] != '**':
            out.append('/')
        token = []
        for char in part:
            if char == '*':
                token.append('[^/]*')
            elif char == '?':
                token.append('[^/]')
            else:
                token.append(re.escape(char))
        out.append(''.join(token))
    return re.compile('^' + ''.join(out) + '$')
